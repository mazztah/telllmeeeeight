import httpx
import asyncio
import base64
from io import BytesIO
import logging

logger = logging.getLogger(__name__)

# Kostenlos bei Hugging Face erstellbar
HF_TOKEN = "DEIN_HUGGINGFACE_TOKEN" 
# Modell-Beispiel: facebook/musicgen-medium oder small
API_URL = "https://api-inference.huggingface.co/models/facebook/musicgen-small"

async def generate_free_music(prompt: str) -> BytesIO | None:
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": prompt}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(API_URL, headers=headers, json=payload)
            
            if response.status_code == 200:
                # Das Modell gibt direkt die Audio-Bytes zurück
                return BytesIO(response.content)
            else:
                logger.error(f"HF Fehler: {response.status_code} - {response.text}")
                return None
    except Exception as e:
        logger.error(f"Fehler bei MusicGen: {e}")
        return None
