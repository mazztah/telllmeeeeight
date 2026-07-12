# imgrem.py – FLUX.1-schnell über Hugging Face Inference Providers (2026-aktuell)
import os
import logging
import httpx
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

HF_TOKEN = os.getenv("HF_TOKEN")

# Neue Router-URL + Provider (fal-ai ist meist am schnellsten und stabilsten für FLUX)
HF_ROUTER_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

async def generate_image(prompt: str, width: int = 1024, height: int = 1024) -> Optional[BytesIO]:
    if not prompt or len(prompt.strip()) < 3:
        return None

    headers = {
        "Content-Type": "application/json",
        "Accept": "image/png"   # Wichtig! Damit wir direkt ein Bild bekommen
    }
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    payload = {
        "inputs": prompt.strip(),
        "parameters": {
            "width": width,
            "height": height,
            "num_inference_steps": 4,      # Schnell-Modus
            "guidance_scale": 0.0,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(HF_ROUTER_URL, json=payload, headers=headers)

            if response.status_code == 200:
                image_bytes = BytesIO(response.content)
                image_bytes.seek(0)
                logger.info(f"✅ FLUX Bild generiert: {prompt[:80]}...")
                return image_bytes

            else:
                error_text = response.text[:400]
                logger.error(f"HF Router Fehler {response.status_code}: {error_text}")
                
                if response.status_code == 503 or "loading" in error_text.lower():
                    return None  # Modell lädt gerade → später Retry möglich
                
                return None

    except Exception as e:
        logger.exception("Fehler in generate_image (Router)")
        return None


def format_image_caption(prompt: str) -> str:
    return (
        f"✨ **FLUX.1-schnell Bild fertig, Queen!** ✨\n\n"
        f"**Prompt:** {prompt[:180]}{'…' if len(prompt) > 180 else ''}\n"
        f"• Via Hugging Face Router (fal-ai)\n"
        f"• Aura +500 🔥"
    )
