# hybrid_music.py - Hybrid Music Engine (MusicGen als Haupt + Fallbacks)
import asyncio
import logging
import os
from io import BytesIO
from typing import Optional, Tuple

from huggingface_hub import InferenceClient
import httpx

logger = logging.getLogger(__name__)

HF_TOKEN = os.getenv("HF_TOKEN")

# ── Clients (lazy init) ──────────────────────────────────────────────────────
def get_ace_client() -> Optional[InferenceClient]:
    if not HF_TOKEN:
        logger.warning("HF_TOKEN missing – skipping HF models")
        return None
    try:
        return InferenceClient(token=HF_TOKEN)
    except Exception as e:
        logger.error(f"HF Client init failed: {e}")
        return None

ace_client = None  # Lazy

riffusion_url = "https://api-inference.huggingface.co/models/riffusion/riffusion-model-v1"

async def generate_hybrid_music(prompt: str, prefer_full_track: bool = True) -> Tuple[Optional[BytesIO], str]:
    """
    Hauptfunktion: Versucht MusicGen (ACE-Step Proxy) zuerst, dann Fallbacks.
    Returns: (audio_bytesio, source_name)
    """
    global ace_client
    prompt = prompt.strip() or "energetic futuristic club beats with heavy bass"

    # 1. MusicGen Large (Haupt – volle Tracks, ACE-Step Proxy)
    logger.info("Hybrid: Versuche MusicGen Large (Haupt)")
    ace_client = ace_client or get_ace_client()
    if ace_client:
        try:
            audio = await asyncio.to_thread(
                ace_client.text_to_audio,
                prompt=prompt,
                model="facebook/musicgen-large",
                duration=30,  # ~30s track
            )
            if audio and len(audio) > 20000:  # Reasonable min size
                logger.info("Hybrid: MusicGen Erfolg (%d Bytes)", len(audio))
                buf = BytesIO(audio)
                buf.seek(0)
                return buf, "MusicGen Large (ACE-Style)"
        except Exception as e:
            logger.warning("MusicGen fehlgeschlagen: %s", e)

    # 2. Riffusion Fallback (schnell & kreativ)
    logger.info("Hybrid: Fallback zu Riffusion")
    try:
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        payload = {"inputs": prompt}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(riffusion_url, headers=headers, json=payload)
            if resp.status_code == 200 and len(resp.content) > 10000:
                buf = BytesIO(resp.content)
                buf.seek(0)
                return buf, "Riffusion"
    except Exception as e:
        logger.warning("Riffusion fehlgeschlagen: %s", e)

    # 3. Stable Audio Open (gute Effekte / kurze Stereo-Clips)
    logger.info("Hybrid: Fallback zu Stable Audio Open")
    if ace_client:
        try:
            stable_model = "stabilityai/stable-audio-open-1.0"
            audio = await asyncio.to_thread(
                ace_client.text_to_audio,
                prompt=prompt,
                model=stable_model,
                duration=47,
            )
            if audio and len(audio) > 8000:
                buf = BytesIO(audio)
                buf.seek(0)
                return buf, "Stable Audio Open"
        except Exception as e:
            logger.warning("Stable Audio fehlgeschlagen: %s", e)

    # 4. Bark (für Vocals / Gesang)
    logger.info("Hybrid: Fallback zu Bark (Vocals)")
    if ace_client:
        try:
            bark_model = "suno/bark-small"
            audio = await asyncio.to_thread(
                ace_client.text_to_audio,
                prompt=prompt + " [music]",
                model=bark_model,
            )
            if audio and len(audio) > 8000:
                buf = BytesIO(audio)
                buf.seek(0)
                return buf, "Bark Vocals"
        except Exception as e:
            logger.warning("Bark fehlgeschlagen: %s", e)

    logger.error("Hybrid: Alle Generatoren fehlgeschlagen")
    return None, "no_generator"
