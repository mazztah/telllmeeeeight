# suno_music.py – Fixed Endpoints
import logging
import httpx
import asyncio
import os
from io import BytesIO

logger = logging.getLogger(__name__)
SUNO_API_KEY = os.getenv("SUNO_API_KEY")
# FIX: Base URL angepasst
SUNO_BASE_URL = "https://api.sunoapi.org" 

async def generate_suno_music(prompt: str) -> BytesIO | None:
    if not SUNO_API_KEY:
        return None
        
    headers = {"Authorization": f"Bearer {SUNO_API_KEY}", "Content-Type": "application/json"}
    payload = {"prompt": prompt, "model": "v3.5", "wait_audio": True}
    
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            # FIX: Endpunkt von /api/generate auf /generate geändert (Standard für die meisten Wrapper)
            endpoint = f"{SUNO_BASE_URL}/generate" 
            resp = await client.post(endpoint, json=payload, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                results = data if isinstance(data, list) else [data]
                if results and results[0].get("audio_url"):
                    audio_url = results[0].get("audio_url")
                    audio_resp = await client.get(audio_url)
                    return BytesIO(audio_resp.content)
            else:
                logger.error(f"Suno API Error {resp.status_code}: {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Suno Error: {e}")
        return None

def format_suno_caption(prompt: str) -> str:
    return f"🎵 **Suno AI Track**\nPrompt: `{prompt[:100]}`"
