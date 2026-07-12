# imgedi.py – FINAL VERSION – Qwen-Image-Edit (DashScope)
import os
import logging
import httpx
import base64
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

CREATE_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


async def edit_image(image_bytes: bytes, prompt: str) -> Optional[BytesIO]:
    logger.info("🚀 edit_image gestartet")

    if not DASHSCOPE_API_KEY:
        logger.error("❌ DASHSCOPE_API_KEY fehlt!")
        return None

    if not image_bytes or len(image_bytes) < 1000:
        logger.error("❌ Kein oder zu kleines Bild")
        return None

    if not prompt or len(prompt.strip()) < 5:
        logger.warning("❌ Edit-Prompt zu kurz")
        return None

    # Base64 mit korrektem Prefix
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    image_data = f"data:image/jpeg;base64,{image_base64}"

    enhanced_prompt = (
        "Keep the original composition, pose, face, body, lighting, background and style exactly the same. "
        f"Only apply these changes: {prompt.strip()}"
    )

    payload = {
        "model": "qwen-image-edit",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": image_data},
                        {"text": enhanced_prompt}
                    ]
                }
            ]
        },
        "parameters": {
            "n": 1,
            "size": "1024*1024"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            logger.info("📤 Sende Anfrage an DashScope...")
            resp = await client.post(CREATE_URL, json=payload, headers={
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
            })

            logger.info(f"📥 Status: {resp.status_code}")

            if resp.status_code != 200:
                logger.error(f"❌ API-Fehler: {resp.text[:400]}")
                return None

            result = resp.json()
            logger.info(f"📦 Antwort erhalten")

            # ── KORREKTE URL-Extraktion ──
            try:
                image_url = result["output"]["choices"][0]["message"]["content"][0]["image"]
                logger.info(f"✅ Bild-URL gefunden: {image_url[:80]}...")
            except (KeyError, IndexError, TypeError):
                logger.error("❌ Konnte Bild-URL nicht aus Antwort extrahieren")
                logger.error(f"Struktur: {result}")
                return None

            # Bild herunterladen
            img_resp = await client.get(image_url, timeout=60.0)
            if img_resp.status_code == 200:
                edited = BytesIO(img_resp.content)
                edited.seek(0)
                logger.info("✅ Bild erfolgreich heruntergeladen und zurückgegeben")
                return edited
            else:
                logger.error(f"❌ Bild-Download fehlgeschlagen: {img_resp.status_code}")
                return None

    except Exception as e:
        logger.exception("💥 Fehler in edit_image")
        return None


def format_edit_caption(prompt: str) -> str:
    return (
        f"✨ **Bild editiert mit Qwen-Image-Edit** ✨\n\n"
        f"**Änderung:** {prompt[:220]}{'…' if len(prompt) > 220 else ''}\n"
        f"• Struktur gut erhalten\n"
        f"• Aura +1500 🔥"
    )
