# imagedit.py – FLUX.1-Kontext-dev Image-to-Image via HF Router (fal-ai backend)
import os
import logging
import httpx
import base64
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

HF_TOKEN = os.getenv("HF_TOKEN")

API_URL = "https://router.huggingface.co/fal-ai/fal-ai/flux-kontext/dev"

async def edit_image_kontext(
    image_bytes: BytesIO,
    prompt: str,
    strength: float = 0.85,
    num_inference_steps: int = 12
) -> Optional[BytesIO]:
    """
    Image-to-Image mit FLUX.1-Kontext-dev
    Besser als normales FLUX.1-schnell bei Edit-Aufgaben.
    """
    if not HF_TOKEN:
        logger.error("HF_TOKEN fehlt für Kontext Edit!")
        return None

    # Bild zu Base64
    image_bytes.seek(0)
    image_b64 = base64.b64encode(image_bytes.read()).decode("utf-8")

    payload = {
        "inputs": image_b64,           # Base64 direkt als "inputs"
        "parameters": {
            "prompt": prompt.strip(),
            "strength": strength,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": 7.5,
            "width": 1024,
            "height": 1024
        }
    }

    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(API_URL, json=payload, headers=headers)

            if response.status_code == 200:
                output = BytesIO(response.content)
                output.seek(0)
                logger.info(f"✅ FLUX.1-Kontext Edit erfolgreich | Strength: {strength}")
                return output
            else:
                logger.error(f"Kontext Edit Fehler {response.status_code}: {response.text[:500]}")
                return None

    except Exception as e:
        logger.exception("Fehler in edit_image_kontext")
        return None


def format_edit_caption(prompt: str) -> str:
    return (
        f"✨ **FLUX.1-Kontext Edit fertig, Queen!** ✨\n\n"
        f"**Prompt:** {prompt[:200]}{'…' if len(prompt) > 200 else ''}\n"
        f"• Model: FLUX.1-Kontext-dev (stark bei Edit)\n"
        f"• Aura +800 🔥"
    )
