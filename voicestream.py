# voicestream.py – Real-Time Voice Streaming (korrigiert)
import asyncio
import logging
from io import BytesIO

from bot_ai import generate_voice
from voicecl import synthesize_with_cloned_voice, list_cloned_voices
from guard import can_process_text

logger = logging.getLogger(__name__)

CHUNK_LENGTH_SECONDS = 13
STREAM_DELAY_BETWEEN_CHUNKS = 0.4


async def start_live_voice_mode(chat_id: str, voice_name: str | None = None, context=None) -> str:
    from bot_state import stream_active
    stream_active[chat_id] = True

    msg = (
        f"🎙️ **Live Voice Stream aktiviert**\n\n"
        "Schick mir jetzt Voice-Nachrichten.\n"
        "Ich antworte dir **live** in kurzen Voice-Chunks.\n"
        "Tippe /endstream oder /stopstream zum Beenden."
    )
    return msg


async def stream_voice_response(
    chat_id: str,
    text: str,
    voice_name: str | None = None,
    context=None,
) -> None:
    if not text or not context:
        return

    from bot_state import stream_active
    if chat_id not in stream_active or not stream_active[chat_id]:
        return

    decision = can_process_text(chat_id, text, action="voice")
    if not decision.allowed:
        await context.bot.send_message(chat_id=chat_id, text=decision.message)
        return

    # Prüfen, ob eine geklonte Voice existiert
    available_voices = list_cloned_voices(chat_id)
    use_cloned = voice_name and voice_name in available_voices

    chunks = _chunk_text(text)                    # ← KEIN await mehr!

    for i, chunk in enumerate(chunks, 1):
        try:
            if use_cloned:
                audio_buffer, warning = await synthesize_with_cloned_voice(
                    chat_id=chat_id, voice_name=voice_name, text=chunk, language="de"
                )
            else:
                audio_buffer = await generate_voice(chunk)
                warning = None

            if not audio_buffer:
                continue

            if i > 1:
                await asyncio.sleep(STREAM_DELAY_BETWEEN_CHUNKS)

            await context.bot.send_voice(
                chat_id=chat_id,
                voice=audio_buffer,
                caption=f"✨ Stream Chunk {i}/{len(chunks)}" if len(chunks) > 1 else None,
                disable_notification=True,
            )

        except Exception as e:
            logger.exception(f"Voice-Stream Chunk {i} fehlgeschlagen")
            break


def _chunk_text(text: str, max_chars_per_chunk: int = 280) -> list[str]:
    """Teilt Text in sinnvolle kleine Stücke auf (synchron)"""
    if len(text) <= max_chars_per_chunk:
        return [text]

    chunks = []
    current = ""
    for sentence in text.replace("!", "! ").replace("?", "? ").replace(".", ". ").split():
        if len(current) + len(sentence) > max_chars_per_chunk:
            if current:
                chunks.append(current.strip())
            current = sentence + " "
        else:
            current += sentence + " "
    if current:
        chunks.append(current.strip())
    return chunks
