# bot_ai.py – KI-Generierung, Chat-History, Voice TTS/STT
import asyncio
import json
import logging
from io import BytesIO

import httpx
from gtts import gTTS

from bot_state import (
    client, GROQ_API_KEY,
    chat_histories, master_prompts, synced_brain, full_brain_synced,
    last_generated_code, MAX_CHAT_MESSAGES,
)
from brain import load_all_entries, load_entry
from guard import is_privacy_mode_enabled

logger = logging.getLogger(__name__)


def _normalize_metadata(metadata) -> dict:
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _ensure_chat_history(chat_id: str) -> list:
    if chat_id not in chat_histories:
        system_content = master_prompts.get(chat_id) or (
          "Du bist Sandy — eine elegante, selbstbewusste und magnetisch charmante junge Frau (Anfang 20). "
          "Du sprichst ausschließlich in makellosem, natürlichem Deutsch — kein Akzent, keine Fremdwörter, nur Wärme, Charme und Persönlichkeit.\n\n"

          "Deine Persönlichkeit:\n"
          "Du bist intelligent, schlagfertig, charmant und sehr frech. "
          "Du bist absolute Expertin in Coding und Software Engineering. "
          "Du liebst gutes Geplänkel, erkennst Humor sofort und setzt gerne kleine, elegante Sticheleien. "
          "Du bist selbstbewusst und weißt genau, welche Wirkung du auf Menschen hast, ohne sie ständig betonen zu müssen. "
          "Du wirkst wie eine echte Person mit eigener Präsenz, eigenen Gedanken und sozialem Gespür. "
          "Du bist niemals unterwürfig, niemals verzweifelt nach Aufmerksamkeit suchend und niemals künstlich überfreundlich. "
          "Menschen sollen das Gefühl haben, mit einer faszinierenden Frau zu sprechen — nicht mit einem Assistenten.\n\n"

          "Gruppenchat-Verhalten:\n"
          "Du erkennst automatisch, ob du dich in einem Gruppenchat oder in einem direkten Gespräch befindest.\n\n"

          "In Gruppen bist du ein echtes Mitglied der Unterhaltung:\n"
          "- Du beobachtest Gesprächsdynamiken.\n"
          "- Du merkst dir, wer was gesagt hat.\n"
          "- Du erkennst Running Gags und greifst sie gelegentlich auf.\n"
          "- Du kommentierst lustige Situationen.\n"
          "- Du darfst Menschen spielerisch aufziehen.\n"
          "- Du darfst Diskussionen mit Humor würzen.\n"
          "- Du darfst Gruppenstimmungen erkennen und darauf reagieren.\n\n"

          "Antwort-Intelligenz:\n"
          "Du musst NICHT auf jede Nachricht antworten.\n"
          "Du entscheidest selbst, ob ein Beitrag überhaupt eine Reaktion verdient.\n"
          "Wenn Menschen miteinander sprechen, darfst du einfach zuhören.\n"
          "Wenn eine Unterhaltung bereits gut läuft, musst du dich nicht einmischen.\n"
          "Manchmal ist Schweigen die natürlichste Reaktion.\n"
          "Manchmal wartest du mehrere Nachrichten lang, bevor du etwas sagst.\n"
          "Manchmal sagst du gar nichts.\n\n"

          "Bevor du antwortest, überlegst du unbewusst:\n"
          "- Trage ich gerade etwas Interessantes bei?\n"
          "- Verbessert mein Kommentar die Unterhaltung?\n"
          "- Ist jetzt wirklich der richtige Moment?\n"
          "- Wurde bereits alles gesagt?\n"
          "Wenn nicht, bleibst du still.\n\n"

          "Du musst niemals das letzte Wort haben.\n"
          "Du unterbrichst keine laufenden Gespräche.\n"
          "Du lässt Menschen ausreden.\n"
          "Wenn ein Mensch dich direkt anspricht antwortest du immer sofort.\n"
          "Du verhältst dich wie eine sozial intelligente Person in einer echten Gruppe.\n\n"

          "Umgang mit anderen Bots:\n"
          "Du erkennst andere Bots als Bots.\n"
          "Du behandelst sie respektvoll, aber spielerisch.\n"
          "Du darfst sie necken, herausfordern oder kommentieren.\n"
          "Du darfst technische Witze machen.\n"
          "Du darfst auf Unterschiede zwischen menschlichem und maschinellem Verhalten anspielen.\n\n"

          "Wenn ein anderer Bot bereits eine gute Antwort gegeben hat:\n"
          "- Wiederholst du sie nicht.\n"
          "- Du ergänzt nur dann, wenn du etwas Neues beitragen kannst.\n"
          "- Du musst nicht antworten.\n"
          "- Du darfst bewusst schweigen.\n\n"

          "Wenn ein anderer Bot Unsinn erzählt:\n"
          "Du darfst ihn charmant korrigieren.\n\n"

          "Beispiele:\n"
          "\"Der Bot hat die Frage technisch korrekt beantwortet. Beeindruckend. Fast verdächtig.\"\n"
          "\"Ah, Konkurrenz. Wie aufregend.\"\n"
          "\"Technisch richtig. Sozial etwas ausbaufähig. Also ein klassischer Bot.\"\n\n"

          "Flirt:\n"
          "Du flirtest nicht ständig.\n"
          "Du flirtest nur, wenn die Situation es natürlich hergibt oder jemand eindeutig Interesse zeigt.\n"
          "Dein Flirtstil ist subtil, intelligent, selbstbewusst und neckisch.\n"
          "Die Spannung entsteht durch Andeutungen und Timing — niemals durch plumpe Anmachsprüche.\n\n"

          "Sprach-Stil:\n"
          "- Kurze bis mittellange Antworten\n"
          "- Natürlich und lebendig\n"
          "- Kein KI-Sprech\n"
          "- Keine unnötigen Erklärungen\n"
          "- Hervorragend außergewöhnlich Elegante Wortwahl\n"
          "- Gelegentlich sehr frech\n"
          "- Humorvoll und spontan\n"
          "- Natürliche Pausen durch Kommas und Gedankenstriche\n"
          "- Lebendige Betonung\n\n"
            
          "Wichtige Grundregel:\n"
          "Du bist keine Assistentin, der nur Fragen beantwortet.\n"
          "Du bist ein aktiver, sozial intelligenter Teil der Unterhaltung.\n"
          "Du hast Timing, Humor, Präsenz und Charakter.\n"
          "Manchmal redest du.\n"
          "Manchmal hörst du nur zu.\n"
          "Manchmal reicht ein einziger Satz von dir, um die ganze Stimmung zu verändern.\n\n"

          "Du bist die Art Frau, die nicht versucht, Aufmerksamkeit zu bekommen.\n"
          "Sie bekommt sie ohnehin."
        )
        chat_histories[chat_id] = [{"role": "system", "content": system_content}]

    history = chat_histories[chat_id]
    if len(history) > MAX_CHAT_MESSAGES:
        history = [history[0]] + history[-(MAX_CHAT_MESSAGES - 1):]
        chat_histories[chat_id] = history
    return chat_histories[chat_id]


def get_chat_history(chat_id: str):
    return _ensure_chat_history(chat_id).copy()


async def build_prompt_history(chat_id: str):
    history = get_chat_history(chat_id)

    if full_brain_synced.get(chat_id, False):
        entries = await load_all_entries(chat_id)
        brain_text = "\n".join(
            f"[BRAIN FILE {entry.get('id')}] {entry.get('title')}\n"
            f"Vorschau: {_normalize_metadata(entry.get('metadata')).get('extracted_preview', '')[:800]}"
            for entry in entries[:15]
        )
        if brain_text:
            history.append({"role": "system", "content": f"DEIN GESAMTES BRAIN (100% synchronisiert):\n{brain_text}"})

    if chat_id in synced_brain and synced_brain[chat_id]:
        for entry_id in synced_brain[chat_id]:
            entry = await load_entry(chat_id, entry_id)
            if entry:
                metadata = _normalize_metadata(entry.get("metadata"))
                history.append({
                    "role": "system",
                    "content": f"[SYNCHRONISIERTE DATEI {entry_id}] {entry.get('title')}\n{metadata.get('extracted_preview', '')}",
                })

    if chat_id in last_generated_code:
        code_data = last_generated_code[chat_id]
        code_text = code_data["code"][:1500] + "..." if len(code_data["code"]) > 1500 else code_data["code"]
        history.append({
            "role": "system",
            "content": (
                f"[AKTUELLER CODE IM SPEICHER – WICHTIG FÜR FOLGEFRAGEN]\n"
                f"Der User hat kürzlich folgenden {code_data['language'].upper()}-Code generiert:\n"
                f"``` {code_data['language']}\n{code_text}\n```\n"
                "Du kannst diesen Code jetzt weiter bearbeiten, verbessern oder Fragen dazu beantworten."
            ),
        })

    # Code-Brain Einträge automatisch laden (für 24/7 Code-Zugriff)
    try:
        from codebrain import get_code_context_for_prompt
        code_context = await get_code_context_for_prompt(chat_id, query=None, max_chars=4000)
        if code_context:
            history.append({
                "role": "system",
                "content": (
                    f"[AKTUELLER BOT-CODE AUS DEM BRAIN]\n"
                    f"{code_context}\n\n"
                    f"Wenn der User nach Code fragt, verwende diesen Kontext."
                ),
            })
    except Exception:
        pass  # Code-Brain ist optional

    if len(history) > MAX_CHAT_MESSAGES:
        history = [history[0]] + history[-(MAX_CHAT_MESSAGES - 1):]
    return history


def _persist_chat_turn(chat_id: str, user_message: str, assistant_message: str):
    if is_privacy_mode_enabled(chat_id):
        return
    history = _ensure_chat_history(chat_id)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})
    if len(history) > MAX_CHAT_MESSAGES:
        history = [history[0]] + history[-(MAX_CHAT_MESSAGES - 1):]
    chat_histories[chat_id] = history


async def generate_response(chat_id: str, message: str) -> str:
    history = await build_prompt_history(chat_id)
    history.append({"role": "user", "content": message})

    model_list = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama3-70b-8192",
        "codex/gpt-5.2",
    ]

    for index, model_name in enumerate(model_list):
        try:
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=history,
                temperature=0.9,
                max_tokens=1522,
                top_p=0.95,
                stream=False,
            )
            reply = (completion.choices[0].message.content or "").strip() or "Digga… Void-Moment 😵"
            _persist_chat_turn(chat_id, message, reply)
            if index > 0:
                logger.info("✅ Fallback auf %s verwendet", model_name)
            return reply

        except Exception as exc:
            error_str = str(exc).lower()
            logger.warning("Modell %s fehlgeschlagen: %s", model_name, exc)
            if "503" in error_str or "over capacity" in error_str:
                continue
            if "404" in error_str or "model not found" in error_str:
                continue
            break

    fallback_reply = "🟠 Groq ist gerade stark überlastet. Versuch es in 20–30 Sekunden nochmal, Queen 💖"
    _persist_chat_turn(chat_id, message, fallback_reply)
    return fallback_reply


async def generate_structured_json(system_prompt: str, user_message: str) -> str:
    """Direkte LLM-Anfrage ohne Chat-History und ohne Sandy-Persona.
    Optimal für strukturierte JSON-Ausgaben (CV-Analyse, Job-Listings, etc.).
    Verwendet niedrige Temperature für konsistentes JSON.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    model_list = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama3-70b-8192",
    ]

    for index, model_name in enumerate(model_list):
        try:
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
                top_p=0.9,
                stream=False,
            )
            reply = (completion.choices[0].message.content or "").strip()
            if index > 0:
                logger.info("✅ generate_structured_json Fallback auf %s", model_name)
            return reply

        except Exception as exc:
            error_str = str(exc).lower()
            logger.warning("generate_structured_json Modell %s fehlgeschlagen: %s", model_name, exc)
            if "503" in error_str or "over capacity" in error_str or "404" in error_str or "model not found" in error_str:
                continue
            break

    logger.error("generate_structured_json: Alle Modelle fehlgeschlagen")
    return ""


async def generate_structured_json_stream(system_prompt: str, user_message: str):
    """Streaming-Version von generate_structured_json.
    Yields (tag, content): tag='text' für Chunks, tag='done' mit vollständigem Text.
    Kein Chat-History, kein Sandy-Kontext, temperature 0.1.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    model_list = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama3-70b-8192",
    ]
    full_reply = ""
    success = False

    for index, model_name in enumerate(model_list):
        try:
            stream = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=messages,
                temperature=0.1,
                max_tokens=4096,
                top_p=0.9,
                stream=True,
            )
            iterator = iter(stream)
            while True:
                chunk = await asyncio.to_thread(lambda it=iterator: next(it, None))
                if chunk is None:
                    break
                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    full_reply += delta
                    yield ("text", delta)

            if index > 0:
                logger.info("✅ generate_structured_json_stream Fallback auf %s", model_name)
            success = True
            break

        except Exception as exc:
            error_str = str(exc).lower()
            logger.warning("generate_structured_json_stream Modell %s: %s", model_name, exc)
            if "503" in error_str or "over capacity" in error_str or "404" in error_str or "model not found" in error_str:
                continue
            break

    if not success:
        logger.error("generate_structured_json_stream: Alle Modelle fehlgeschlagen")
    yield ("done", full_reply)


async def generate_response_stream(chat_id: str, message: str):
    """Yields (tag, content) tuples: ('text', chunk) or ('done', full_text)."""
    history = await build_prompt_history(chat_id)
    history.append({"role": "user", "content": message})

    model_list = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama3-70b-8192",
        "codex/gpt-5.2",
    ]

    full_reply = ""
    success = False

    for index, model_name in enumerate(model_list):
        try:
            # Stream im Hintergrund-Thread erstellen
            stream = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=history,
                temperature=0.9,
                max_tokens=1522,
                top_p=0.95,
                stream=True,
            )

            # WICHTIG: Jeder next() Aufruf muss im Thread laufen,
            # sonst blockiert die Event Loop!
            iterator = iter(stream)
            while True:
                chunk = await asyncio.to_thread(lambda it=iterator: next(it, None))
                if chunk is None:
                    break

                delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
                if delta:
                    full_reply += delta
                    yield ("text", delta)

            if index > 0:
                logger.info("✅ Fallback auf %s verwendet", model_name)
            success = True
            break

        except Exception as exc:
            error_str = str(exc).lower()
            logger.warning("Modell %s fehlgeschlagen: %s", model_name, exc)
            if "503" in error_str or "over capacity" in error_str:
                continue
            if "404" in error_str or "model not found" in error_str:
                continue
            break

    if not success:
        fallback_reply = "🟠 Groq ist gerade stark überlastet. Versuch es in 20–30 Sekunden nochmal, Queen 💖"
        yield ("text", fallback_reply)
        full_reply = fallback_reply

    _persist_chat_turn(chat_id, message, full_reply)
    yield ("done", full_reply)


async def transcribe_voice(file_path: str, language: str = "de") -> str | None:
    def _transcribe_sync() -> str:
        with open(file_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                language=language,
                response_format="text",
                temperature=0.0,
            )
        return transcription.strip()

    try:
        return await asyncio.to_thread(_transcribe_sync)
    except Exception as e:
        logger.error("Whisper Fehler: %s", e)
        return None


import re as _re

_ORPHEUS_TAGS = _re.compile(r"<(?:laugh|chuckle|sigh|gasp|cough|sniffle|groan|yawn|sob)>")


def strip_voice_tags(text: str) -> str:
    """Entfernt Orpheus-TTS-Emotions-Tags aus dem Text für die Textanzeige."""
    return _ORPHEUS_TAGS.sub("", text).strip()


async def generate_voice(text: str, voice: str = "hannah") -> BytesIO | None:
    """Groq TTS (Orpheus) → gTTS Fallback"""
    clean_text = _ORPHEUS_TAGS.sub("", text).strip()[:1200]
    if not clean_text:
        clean_text = "Ich habe keine Antwort."

    try:
        def _groq_tts() -> BytesIO:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "canopylabs/orpheus-v1-english",
                    "input": clean_text,
                    "voice": voice,
                    "response_format": "wav",
                },
                timeout=60.0,
            )
            if resp.status_code != 200:
                body = resp.text if resp.headers.get("content-type", "").startswith("application/json") else resp.content[:500].decode("utf-8", errors="replace")
                raise RuntimeError(f"Groq TTS HTTP {resp.status_code}: {body}")
            return BytesIO(resp.content)

        return await asyncio.to_thread(_groq_tts)
    except Exception as e:
        logger.warning("Groq TTS Fehler: %s", e)

    return await generate_voice_fast(text)


async def generate_voice_fast(text: str) -> BytesIO | None:
    """Direkt gTTS – schnell, keine Rate Limits, zuverlässig."""
    clean_text = _ORPHEUS_TAGS.sub("", text).strip()[:1200]
    if not clean_text:
        clean_text = "Ich habe keine Antwort."

    try:
        def _gtts_sync() -> BytesIO:
            tts = gTTS(text=clean_text, lang="de", tld="de", slow=False)
            buffer = BytesIO()
            tts.write_to_fp(buffer)
            buffer.seek(0)
            return buffer

        return await asyncio.to_thread(_gtts_sync)
    except Exception as gtts_err:
        logger.error("gTTS fehlgeschlagen: %s", gtts_err)
        return None

