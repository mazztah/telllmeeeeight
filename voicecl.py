import asyncio
import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VOICE_STORAGE_DIR = Path(os.getenv("DATA_DIR", "/data")) / "voiceclones"
try:
    VOICE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError) as exc:
    # "/data" ist nur auf Plattformen mit gemountetem Persistent Storage
    # beschreibbar (z.B. HF Spaces). Auf Cloud Run, Render & Co. ohne Disk
    # existiert "/data" nicht und kann vom non-root User nicht angelegt
    # werden -> Fallback auf einen lokalen Ordner neben dem Code.
    fallback_dir = Path(__file__).resolve().parent / "data" / "voiceclones"
    logger.warning(
        "VOICE_STORAGE_DIR '%s' nicht beschreibbar (%s) – verwende Fallback '%s'",
        VOICE_STORAGE_DIR, exc, fallback_dir,
    )
    VOICE_STORAGE_DIR = fallback_dir
    VOICE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
VOICE_INDEX_FILE = VOICE_STORAGE_DIR / "voices.json"
XTTS_MODEL_NAME = os.getenv("XTTS_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
MAX_SYNTHESIS_CHARS = int(os.getenv("VOICE_MAX_TEXT_CHARS", "1800"))

try:
    from TTS.api import TTS  # type: ignore
    XTTS_AVAILABLE = True
except Exception:
    XTTS_AVAILABLE = False
    TTS = None

try:
    from pydub import AudioSegment
except Exception:
    AudioSegment = None

_tts_engine = None
_tts_engine_lock = threading.Lock()
_index_lock = threading.Lock()


def _ensure_storage() -> None:
    VOICE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not VOICE_INDEX_FILE.exists():
        VOICE_INDEX_FILE.write_text("{}", encoding="utf-8")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8", suffix=".json") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _load_index() -> dict[str, dict[str, Any]]:
    _ensure_storage()
    with _index_lock:
        try:
            raw = json.loads(VOICE_INDEX_FILE.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}


def _save_index(index: dict[str, dict[str, Any]]) -> None:
    _ensure_storage()
    with _index_lock:
        _atomic_write_json(VOICE_INDEX_FILE, index)


def _coerce_voice_entry(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"path": value}
    return {}


def _sanitize_voice_name(voice_name: str) -> str:
    if not voice_name:
        voice_name = "voice"
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in voice_name)
    return safe_name.strip("_") or "voice"


def _estimate_audio_seconds(source_path: str) -> float | None:
    if AudioSegment is None:
        return None
    try:
        audio = AudioSegment.from_file(source_path)
        return len(audio) / 1000.0
    except Exception:
        return None


def _audio_metadata(source_path: str) -> dict[str, Any]:
    metadata = {"duration_seconds": _estimate_audio_seconds(source_path)}
    if AudioSegment is None:
        return metadata
    try:
        audio = AudioSegment.from_file(source_path)
        metadata["frame_rate"] = audio.frame_rate
        metadata["channels"] = audio.channels
    except Exception:
        pass
    return metadata


def backend_status() -> str:
    return "XTTS-v2 bereit" if XTTS_AVAILABLE else "XTTS-v2 nicht installiert (nur Referenzen werden gespeichert)"


async def clone_voice_from_file(chat_id: str, source_path: str, voice_name: str) -> tuple[bool, str]:
    if not source_path or not os.path.exists(source_path):
        return False, "Referenz-Audio wurde nicht gefunden."

    duration = _estimate_audio_seconds(source_path)
    if duration is not None and duration < 2.0:
        return False, "Die Referenz ist zu kurz. Schick bitte mindestens 2 Sekunden klare Stimme."
    if duration is not None and duration > 180.0:
        return False, "Die Referenz ist zu lang. Für Klonen reichen etwa 5 bis 60 Sekunden."

    safe_name = _sanitize_voice_name(voice_name)
    suffix = Path(source_path).suffix.lower() or ".wav"
    chat_dir = VOICE_STORAGE_DIR / str(chat_id)
    chat_dir.mkdir(parents=True, exist_ok=True)

    # Absoluter Pfad für Robustheit
    destination = (chat_dir / f"{safe_name}{suffix}").resolve()
    shutil.copy2(source_path, destination)

    index = _load_index()
    chat_key = str(chat_id)
    chat_map = index.setdefault(chat_key, {})

    # Verhindere leere Keys
    clean_voice_name = voice_name.strip() or safe_name
    chat_map[clean_voice_name] = {
        "path": str(destination),
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "backend": "xtts_v2" if XTTS_AVAILABLE else "reference_only",
        **_audio_metadata(str(destination)),
    }
    _save_index(index)

    return True, f"Voice '{clean_voice_name}' gespeichert. {backend_status()}."


def _prune_missing_voices(chat_id: str, index: dict[str, dict[str, Any]]) -> dict[str, str]:
    chat_key = str(chat_id)
    voice_map = index.get(chat_key, {})
    normalized: dict[str, str] = {}
    changed = False

    # Kopie der Items, um Modifikation während Iteration sicher zu machen
    for voice_name, raw_entry in list(voice_map.items()):
        if not voice_name or not isinstance(voice_name, str) or not voice_name.strip():
            voice_map.pop(voice_name, None)
            changed = True
            continue

        entry = _coerce_voice_entry(raw_entry)
        path = entry.get("path")
        if isinstance(path, str):
            # Absoluter Pfad prüfen
            abs_path = Path(path).resolve()
            if abs_path.exists():
                normalized[voice_name] = str(abs_path)
                continue

        # Ungültigen Eintrag entfernen
        voice_map.pop(voice_name, None)
        changed = True

    if changed:
        if voice_map:
            index[chat_key] = voice_map
        else:
            index.pop(chat_key, None)
        _save_index(index)

    return normalized


def list_cloned_voices(chat_id: str) -> dict[str, str]:
    index = _load_index()
    return _prune_missing_voices(chat_id, index)


def describe_cloned_voices(chat_id: str) -> str:
    list_cloned_voices(chat_id)  # prune aufrufen
    index = _load_index()
    voice_map = index.get(str(chat_id), {})
    if not voice_map:
        return f"Keine Voices gespeichert. {backend_status()}."

    lines = [f"Meine Voices ({backend_status()}):"]
    for entry_index, (voice_name, raw_entry) in enumerate(voice_map.items(), start=1):
        entry = _coerce_voice_entry(raw_entry)
        created_at = str(entry.get("created_at") or "-")
        backend = str(entry.get("backend") or "unknown")
        duration = entry.get("duration_seconds")
        duration_text = f" | Dauer: {round(float(duration), 1)}s" if duration else ""
        lines.append(f"{entry_index}. {voice_name} | Backend: {backend}{duration_text} | Erstellt: {created_at}")
    return "\n".join(lines)


def delete_cloned_voice(chat_id: str, voice_name: str) -> str:
    index = _load_index()
    voice_map = index.get(str(chat_id), {})
    # Case-insensitive Delete
    target_key = None
    for k in list(voice_map.keys()):
        if k.lower() == voice_name.lower():
            target_key = k
            break

    if target_key:
        raw_entry = voice_map.pop(target_key, None)
        entry = _coerce_voice_entry(raw_entry)
        target = entry.get("path")
        if isinstance(target, str) and os.path.exists(target):
            try:
                os.unlink(target)
            except Exception:
                logger.warning("Konnte Referenzdatei %s nicht löschen", target)

        if not voice_map:
            index.pop(str(chat_id), None)
        else:
            index[str(chat_id)] = voice_map
        _save_index(index)
        return f"Voice '{voice_name}' wurde gelöscht."
    return "Diese Voice existiert nicht."


def _get_tts_engine():
    global _tts_engine
    if not XTTS_AVAILABLE:
        return None
    if _tts_engine is None:
        with _tts_engine_lock:
            if _tts_engine is None:
                _tts_engine = TTS(XTTS_MODEL_NAME)
                logger.info("XTTS-Engine geladen: %s", XTTS_MODEL_NAME)
    return _tts_engine


def _synthesize_sync(text: str, speaker_wav: str, language: str) -> bytes:
    engine = _get_tts_engine()
    if engine is None:
        raise RuntimeError("XTTS Backend nicht verfügbar.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
        output_path = temp.name

    try:
        engine.tts_to_file(
            text=text,
            speaker_wav=speaker_wav,
            language=language,
            file_path=output_path,
        )
        with open(output_path, "rb") as handle:
            return handle.read()
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


async def synthesize_with_cloned_voice(
    chat_id: str,
    voice_name: str,
    text: str,
    language: str = "de",
) -> tuple[BytesIO | None, str]:
    voices = list_cloned_voices(chat_id)

    # Case-insensitive Suche + Fallback
    speaker_wav = voices.get(voice_name)
    if not speaker_wav:
        lower_name = voice_name.lower()
        for k, p in voices.items():
            if k.lower() == lower_name:
                speaker_wav = p
                voice_name = k  # korrigierter Name für Logging
                break

    if not speaker_wav:
        logger.warning(f"Voice '{voice_name}' nicht gefunden. Verfügbare Voices: {list(voices.keys())}")
        return None, f"Voice '{voice_name}' nicht gefunden. Verfügbare Voices: {', '.join(voices.keys()) or 'keine'}."

    if not XTTS_AVAILABLE:
        return None, "XTTS-v2 ist noch nicht installiert."

    cleaned_text = (text or "").strip()
    if not cleaned_text:
        return None, "Kein Text zum Sprechen angegeben."

    truncated = len(cleaned_text) > MAX_SYNTHESIS_CHARS
    audio_bytes = await asyncio.to_thread(
        _synthesize_sync,
        cleaned_text[:MAX_SYNTHESIS_CHARS],
        speaker_wav,
        language or "de",
    )
    buffer = BytesIO(audio_bytes)
    buffer.seek(0)

    if truncated:
        return buffer, "Hinweis: Text wurde für die Synthese gekürzt."
    return buffer, ""


# Hilfsfunktion für Handler (falls noch woanders verwendet)
def get_voice_path(chat_id: str, voice_name: str) -> str | None:
    voices = list_cloned_voices(chat_id)
    # case-insensitive
    for k, p in voices.items():
        if k.lower() == voice_name.lower():
            return p
    return None