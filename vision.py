import asyncio
import logging
import os
from typing import Dict, List

from groq import Groq

logger = logging.getLogger(__name__)

VISION_MODELS = [
    os.getenv("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "llama-3.2-90b-vision-preview",
]


def create_vision_message(text: str, image_urls: List[str], detail: str = "auto") -> Dict:
    """Erstellt eine Nachricht mit Text und Bildern fuer das Vision-Modell."""
    content = [{"type": "text", "text": text}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url, "detail": detail}})
    return {"role": "user", "content": content}


async def analyze_images(
    client: Groq,
    chat_id: str,
    prompt: str,
    image_urls: List[str],
    history: List[Dict],
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    """Analysiert ein oder mehrere Bilder mit Modell-Fallbacks."""
    if not image_urls:
        return "Kein Bild angekommen, Digga."

    messages = history.copy()
    messages.append(create_vision_message(prompt, image_urls))

    last_error = None
    for model_name in VISION_MODELS:
        try:
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=0.95,
                stream=False,
            )
            reply = (completion.choices[0].message.content or "").strip()
            if reply:
                return reply
        except Exception as exc:
            last_error = exc
            logger.warning("Vision-Modell %s fehlgeschlagen fuer chat_id %s: %s", model_name, chat_id, exc)

    if last_error and ("400" in str(last_error) or "413" in str(last_error)):
        return "Bild zu gross oder kaputt (max etwa 20 MB / 33 MP)."
    return f"Vision abgekackt: {str(last_error)[:80]}..." if last_error else "Vision hat kein Ergebnis geliefert."
