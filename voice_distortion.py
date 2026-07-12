# voice_distortion.py – Voice-Effekt-Engine für telllmeeedrei
# Unterstützt pedalboard (Spotify) als Primary und pydub als Fallback.
import io
import logging
import os
from typing import BinaryIO

from pydub import AudioSegment

logger = logging.getLogger(__name__)

# ── Optional: pedalboard für hochwertigere Effekte ───────────────────────────
try:
    import pedalboard
    from pedalboard import (
        Bitcrush, Chorus, Delay, Distortion, Gain,
        HighpassFilter, LowpassFilter, PitchShift, Reverb,
    )
    PEDALBOARD_AVAILABLE = True
except Exception:
    PEDALBOARD_AVAILABLE = False
    pedalboard = None

# ── Optional: numpy für Array-Operationen ────────────────────────────────────
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except Exception:
    NUMPY_AVAILABLE = False
    np = None

EFFECT_PRESETS = {
    # ── Original 6 ──
    "robot":        {"description": "🤖 Roboter-Stimme mit Bitcrush & Verzerrung"},
    "deep_voice":   {"description": "👿 Extrem tiefe Stimme (Darth-Vader-Style)"},
    "chipmunk":     {"description": "🐿️ Hohe Chipmunk-Stimme"},
    "demon":        {"description": "😈 Dämonische Stimme mit Hall & Distortion"},
    "telephone":    {"description": "☎️ Altes Telefon (Bandpass 300-3400Hz)"},
    "echo_chamber": {"description": "🌌 Großer Echo-Hall"},
    # ── Neue 10 ──
    "alien":        {"description": "👽 Alien-Stimme (Hoch + Verzerrung)"},
    "underwater":   {"description": "🌊 Unterwasser (Dumpf + Chorus)"},
    "radio":        {"description": "📻 Altes AM-Radio (Bandpass + Rauschen)"},
    "megaphone":    {"description": "📢 Megaphon (Mid-Boost + Distortion)"},
    "whisper":      {"description": "🤫 Flüstern (Leise + Hochpass)"},
    "monster":      {"description": "🐲 Monster (Tief + Knurren)"},
    "cyberpunk":    {"description": "🦾 Cyberpunk (Glitch + Bitcrush)"},
    "cave":         {"description": "🪨 Höhle (Tiefer Reverb)"},
    "helium":       {"description": "🎈 Helium (Extrem hoch)"},
    "reverse":      {"description": "⏪ Rückwärts (Reverse Playback)"},
}


def list_effects() -> dict:
    """Gibt eine Kopie der verfügbaren Effekte zurück."""
    return EFFECT_PRESETS.copy()


def _read_audio(input_path: str) -> AudioSegment:
    """Lädt eine Audio-Datei mit automatischer Format-Erkennung."""
    return AudioSegment.from_file(input_path)


def _export_to_bytesio(segment: AudioSegment, fmt: str = "ogg") -> io.BytesIO:
    """Exportiert ein AudioSegment in einen BytesIO-Puffer."""
    buf = io.BytesIO()
    segment.export(buf, format=fmt)
    buf.seek(0)
    return buf


def apply_effect(input_path: str, effect_name: str) -> io.BytesIO | None:
    """Wendet einen Distortion-Effekt auf eine Audio-Datei an.

    Args:
        input_path: Pfad zur Input-Audiodatei (beliebiges Format).
        effect_name: Schlüssel aus EFFECT_PRESETS.

    Returns:
        BytesIO mit OGG-Audio oder None bei Fehler.
    """
    if effect_name not in EFFECT_PRESETS:
        logger.warning("Unbekannter Effekt: %s", effect_name)
        return None

    try:
        sound = _read_audio(input_path)

        # Einheitlich Mono für konsistente Effekte
        if sound.channels > 1:
            sound = sound.set_channels(1)

        if PEDALBOARD_AVAILABLE and NUMPY_AVAILABLE:
            result = _apply_pedalboard(sound, effect_name)
        else:
            result = _apply_pydub_fallback(sound, effect_name)

        return _export_to_bytesio(result, fmt="ogg")
    except Exception as e:
        logger.exception("Fehler bei Voice-Distortion (%s): %s", effect_name, e)
        return None


# ── Pedalboard Engine ────────────────────────────────────────────────────────

def _audio_segment_to_ndarray(sound: AudioSegment) -> np.ndarray:
    """Konvertiert pydub AudioSegment zu numpy float32 Array (-1.0 … 1.0)."""
    samples = np.array(sound.get_array_of_samples(), dtype=np.float32)
    if sound.channels == 2:
        samples = samples.reshape((-1, 2))
    max_val = float(1 << (sound.sample_width * 8 - 1))
    return samples / max_val


def _ndarray_to_audio_segment(
    arr: np.ndarray, frame_rate: int, sample_width: int = 2, channels: int = 1
) -> AudioSegment:
    """Konvertiert numpy float32 Array zurück zu pydub AudioSegment."""
    max_val = float(1 << (sample_width * 8 - 1))
    arr = np.clip(arr, -1.0, 1.0)
    arr_int = (arr * max_val).astype(np.int16)
    if channels > 1 and arr_int.ndim > 1:
        arr_int = arr_int.reshape((-1, channels))
    raw_bytes = arr_int.tobytes()
    return AudioSegment(
        data=raw_bytes,
        sample_width=sample_width,
        frame_rate=frame_rate,
        channels=channels,
    )


def _apply_pedalboard(sound: AudioSegment, effect_name: str) -> AudioSegment:
    """Wendet Effekte via Spotify pedalboard an."""
    samples = _audio_segment_to_ndarray(sound)
    sr = sound.frame_rate
    board = pedalboard.Pedalboard([])

    if effect_name == "robot":
        board.append(Bitcrush(bit_depth=4))
        board.append(Distortion(drive_db=25.0))
        board.append(HighpassFilter(cutoff_frequency_hz=800))
        board.append(LowpassFilter(cutoff_frequency_hz=4000))
    elif effect_name == "deep_voice":
        board.append(PitchShift(semitones=-8))
        board.append(Gain(gain_db=5.0))
    elif effect_name == "chipmunk":
        board.append(PitchShift(semitones=+10))
        board.append(Gain(gain_db=-2.0))
    elif effect_name == "demon":
        board.append(PitchShift(semitones=-6))
        board.append(Chorus(rate_hz=2.0, depth=0.8))
        board.append(Distortion(drive_db=15.0))
        board.append(Reverb(room_size=0.8, wet_level=0.4))
    elif effect_name == "telephone":
        board.append(HighpassFilter(cutoff_frequency_hz=300))
        board.append(LowpassFilter(cutoff_frequency_hz=3400))
        board.append(Gain(gain_db=8.0))
    elif effect_name == "echo_chamber":
        board.append(Delay(delay_seconds=0.3, feedback=0.4, mix=0.35))
        board.append(Reverb(room_size=0.9, wet_level=0.5))
    # ── Neue 10 ──
    elif effect_name == "alien":
        board.append(PitchShift(semitones=+7))
        board.append(Bitcrush(bit_depth=3))
        board.append(HighpassFilter(cutoff_frequency_hz=2000))
        board.append(Distortion(drive_db=10.0))
    elif effect_name == "underwater":
        board.append(LowpassFilter(cutoff_frequency_hz=600))
        board.append(Chorus(rate_hz=0.5, depth=0.9))
        board.append(Gain(gain_db=-4.0))
    elif effect_name == "radio":
        board.append(HighpassFilter(cutoff_frequency_hz=400))
        board.append(LowpassFilter(cutoff_frequency_hz=2500))
        board.append(Distortion(drive_db=8.0))
        board.append(Gain(gain_db=6.0))
    elif effect_name == "megaphone":
        board.append(HighpassFilter(cutoff_frequency_hz=500))
        board.append(LowpassFilter(cutoff_frequency_hz=4500))
        board.append(Distortion(drive_db=20.0))
        board.append(Gain(gain_db=10.0))
    elif effect_name == "whisper":
        board.append(HighpassFilter(cutoff_frequency_hz=2000))
        board.append(Gain(gain_db=-18.0))
        board.append(Reverb(room_size=0.3, wet_level=0.2))
    elif effect_name == "monster":
        board.append(PitchShift(semitones=-10))
        board.append(Distortion(drive_db=30.0))
        board.append(LowpassFilter(cutoff_frequency_hz=800))
        board.append(Gain(gain_db=8.0))
    elif effect_name == "cyberpunk":
        board.append(Bitcrush(bit_depth=2))
        board.append(Chorus(rate_hz=4.0, depth=0.6))
        board.append(Delay(delay_seconds=0.1, feedback=0.3, mix=0.25))
        board.append(HighpassFilter(cutoff_frequency_hz=1000))
    elif effect_name == "cave":
        board.append(Reverb(room_size=0.95, wet_level=0.7, damping=0.2))
        board.append(Delay(delay_seconds=0.5, feedback=0.5, mix=0.3))
        board.append(Gain(gain_db=-6.0))
    elif effect_name == "helium":
        board.append(PitchShift(semitones=+14))
        board.append(Gain(gain_db=-4.0))
        board.append(HighpassFilter(cutoff_frequency_hz=1500))
    elif effect_name == "reverse":
        # Reverse wird im Fallback separat behandelt, hier nur Placeholder
        return sound.reverse()

    # pedalboard erwartet (num_channels, num_samples)
    if samples.ndim == 1:
        effected = board.process(samples, sample_rate=sr)
    else:
        effected = board.process(samples.T, sample_rate=sr)
        if effected.ndim > 1:
            effected = effected.T

    return _ndarray_to_audio_segment(effected, sr)


# ── Pydub Fallback Engine ────────────────────────────────────────────────────

def _apply_pydub_fallback(sound: AudioSegment, effect_name: str) -> AudioSegment:
    """Fallback-Effekte nur mit pydub (keine zusätzlichen Dependencies nötig)."""
    if effect_name == "robot":
        crushed = (
            sound.set_channels(1)
            .set_frame_rate(8000)
            .set_sample_width(1)
        )
        buf = io.BytesIO()
        crushed.export(buf, format="wav")
        buf.seek(0)
        reimported = AudioSegment.from_file(buf, format="wav")
        reimported = reimported.set_frame_rate(sound.frame_rate)
        reimported = reimported.high_pass_filter(800).low_pass_filter(4000) + 8
        return reimported

    elif effect_name == "deep_voice":
        new_sr = int(sound.frame_rate * (2.0 ** (-8 / 12.0)))
        shifted = sound._spawn(sound.raw_data, overrides={"frame_rate": new_sr})
        return shifted.set_frame_rate(sound.frame_rate)

    elif effect_name == "chipmunk":
        new_sr = int(sound.frame_rate * (2.0 ** (10 / 12.0)))
        shifted = sound._spawn(sound.raw_data, overrides={"frame_rate": new_sr})
        return shifted.set_frame_rate(sound.frame_rate)

    elif effect_name == "demon":
        shifted = _apply_pydub_fallback(sound, "deep_voice")
        delay_ms = 80
        quieter = shifted - 12
        combined = shifted.overlay(quieter, position=delay_ms)
        return combined.high_pass_filter(80).low_pass_filter(5000)

    elif effect_name == "telephone":
        return sound.high_pass_filter(300).low_pass_filter(3400) + 8

    elif effect_name == "echo_chamber":
        original = sound
        e1 = original - 10
        e2 = original - 18
        e3 = original - 25
        combined = (
            original.overlay(e1, position=250)
                   .overlay(e2, position=500)
                   .overlay(e3, position=750)
        )
        return combined
    # ── Neue 10 Fallbacks ──
    elif effect_name == "alien":
        new_sr = int(sound.frame_rate * (2.0 ** (7 / 12.0)))
        shifted = sound._spawn(sound.raw_data, overrides={"frame_rate": new_sr})
        return shifted.set_frame_rate(sound.frame_rate).high_pass_filter(2000) + 5

    elif effect_name == "underwater":
        return sound.low_pass_filter(600) - 4

    elif effect_name == "radio":
        return sound.high_pass_filter(400).low_pass_filter(2500) + 6

    elif effect_name == "megaphone":
        return sound.high_pass_filter(500).low_pass_filter(4500) + 10

    elif effect_name == "whisper":
        return sound.high_pass_filter(2000) - 18

    elif effect_name == "monster":
        new_sr = int(sound.frame_rate * (2.0 ** (-10 / 12.0)))
        shifted = sound._spawn(sound.raw_data, overrides={"frame_rate": new_sr})
        return shifted.set_frame_rate(sound.frame_rate).low_pass_filter(800) + 8

    elif effect_name == "cyberpunk":
        crushed = sound.set_frame_rate(8000).set_sample_width(1)
        buf = io.BytesIO()
        crushed.export(buf, format="wav")
        buf.seek(0)
        reimported = AudioSegment.from_file(buf, format="wav")
        return reimported.set_frame_rate(sound.frame_rate).high_pass_filter(1000)

    elif effect_name == "cave":
        original = sound
        e1 = original - 15
        e2 = original - 25
        combined = original.overlay(e1, position=400).overlay(e2, position=800)
        return combined - 6

    elif effect_name == "helium":
        new_sr = int(sound.frame_rate * (2.0 ** (14 / 12.0)))
        shifted = sound._spawn(sound.raw_data, overrides={"frame_rate": new_sr})
        return shifted.set_frame_rate(sound.frame_rate).high_pass_filter(1500) - 4

    elif effect_name == "reverse":
        return sound.reverse()

    return sound

