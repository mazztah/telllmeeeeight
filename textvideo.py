# textvideo.py – Finale stabile Version (Base64 + klare Fehler)
import asyncio
import logging
import os
import base64
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

CREATE_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
POLL_URL_BASE = "https://dashscope-intl.aliyuncs.com/api/v1/tasks/"

active_task_id = None
active_task_lock = asyncio.Lock()


def _image_to_base64(image_path: str) -> str:
    """Wandelt lokales Bild in Base64 Data-URI um (wie von Dashscope verlangt)."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


async def generate_text_to_video(
    prompt: str,
    img_url: str,                    # Lokaler Pfad zum Bild
    duration: int = 5,
    resolution: str = "720P",
    aspect_ratio: str = "16:9",
) -> tuple[Path | None, str | None]:

    global active_task_id

    if not DASHSCOPE_API_KEY:
        return None, "❌ DASHSCOPE_API_KEY fehlt."

    clean_prompt = (prompt or "smooth natural movement").strip()

    # Bild in Base64 umwandeln (wichtig!)
    try:
        base64_url = _image_to_base64(img_url)
    except Exception as e:
        logger.error(f"Bild konnte nicht in Base64 umgewandelt werden: {e}")
        return None, "❌ Bild konnte nicht verarbeitet werden."

    async with httpx.AsyncClient(timeout=180.0) as client:
        for model in ["wan2.2-i2v-plus", "wan2.2-i2v-flash", "wan2.1-i2v-plus", "wan2.5-i2v-preview"]:
            logger.info(f"Versuche Video mit {model} — {duration}s | {resolution} | {aspect_ratio}")

            payload = {
                "model": model,
                "input": {
                    "prompt": clean_prompt,
                    "img_url": base64_url          # Base64 statt lokalem Pfad
                },
                "parameters": {
                    "resolution": resolution,
                    "duration": duration,
                    "aspect_ratio": aspect_ratio,
                    "prompt_extend": True,
                }
            }

            try:
                create_resp = await client.post(
                    CREATE_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                        "X-DashScope-Async": "enable"
                    }
                )

                if create_resp.status_code != 200:
                    error = create_resp.json()
                    msg = error.get("message") or create_resp.text
                    logger.error(f"Create fehlgeschlagen: {msg}")
                    continue

                task_id = create_resp.json().get("output", {}).get("task_id")
                if not task_id:
                    continue

                async with active_task_lock:
                    active_task_id = task_id

                poll_url = f"{POLL_URL_BASE}{task_id}"

                for _ in range(80):
                    await asyncio.sleep(4.0)

                    poll_resp = await client.get(poll_url, headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"})
                    result = poll_resp.json()
                    status = result.get("output", {}).get("task_status")

                    if status == "SUCCEEDED":
                        video_url = result.get("output", {}).get("video_url")
                        if video_url:
                            video_data = await client.get(video_url, timeout=90)
                            video_data.raise_for_status()

                            path = Path("generated_video.mp4")
                            path.write_bytes(video_data.content)

                            async with active_task_lock:
                                active_task_id = None
                            return path, model

                    elif status in ("FAILED", "UNKNOWN", "CANCELED"):
                        error_msg = result.get("output", {}).get("task_message", "Unbekannt")
                        logger.warning(f"Task FAILED: {error_msg}")
                        break

            except Exception as e:
                logger.warning(f"Fehler bei Modell {model}: {e}")

            finally:
                async with active_task_lock:
                    if active_task_id == task_id:
                        active_task_id = None

    return None, "❌ Dashscope konnte kein Video erstellen (Bildformat oder Inhalt wurde abgelehnt)."
