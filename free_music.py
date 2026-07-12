# free_music.py – Kostenlose KI-Musik via HuggingFace MusicGen
import httpx
import asyncio
import logging
import os
from io import BytesIO

logger = logging.getLogger(__name__)

# API Key wird jetzt sicher aus den Environment Variables geladen
HF_TOKEN = os.getenv("HF_TOKEN") 
# Wir nutzen musicgen-small für schnellere Antwortzeiten und geringere Fehlerquote
API_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

async def generate_free_music(prompt: str) -> BytesIO | None:
    """Generiert Musik via HuggingFace Inference API."""
    if not HF_TOKEN:
        logger.error("HF_TOKEN fehlt in den Umgebungsvariablen!")
        return None

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": prompt}

    try:
        # Erhöhter Timeout, da HF-Modelle oft "kalt" sind und erst laden müssen
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(API_URL, headers=headers, json=payload)
            
            if response.status_code == 200:
                # Das Modell gibt direkt die Audio-Bytes (wav/mp3) zurück
                return BytesIO(response.content)
            elif response.status_code == 503:
                logger.warning("HF Modell lädt noch (503 Service Unavailable)...")
                return None
            else:
                logger.error(f"HF Fehler {response.status_code}: {response.text}")
                return None
    except Exception as e:
        logger.error(f"Fehler bei MusicGen: {e}")
        return None
