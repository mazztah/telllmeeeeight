# ttv26.py – Text-to-Video Modul (reine Text-to-Video mit Dashscope)
import asyncio
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

CREATE_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
POLL_URL_BASE = "https://dashscope-intl.aliyuncs.com/api/v1/tasks/"

active_task_id = None
active_task_lock = asyncio.Lock()
MAX_POLL_TIME_SECONDS = 300  # 5 Minuten maximale Wartezeit

# ─────────────────────────────────────────────────────────────
# MODEL-ÜBERSICHT (Stand April 2026)
# ─────────────────────────────────────────────────────────────
MODEL_LIST = [
    {"name": "wan2.2-t2v-plus",     "desc": "Neuestes reines Text-to-Video (beste Qualität)"},
    {"name": "wan2.7-t2v",          "desc": "Sehr gute Motion & Qualität (Pure T2V)"},
    {"name": "wan2.2-t2v-flash",    "desc": "Schnell & günstig (Pure T2V)"},
    {"name": "wan2.5-i2v-preview",  "desc": "Fallback – Hybrid (Image-to-Video)"},
]

async def generate_text_to_video(
    prompt: str,
    duration: int = 5,
    resolution: str = "720P",
    aspect_ratio: str = "16:9",
) -> tuple[Path | None, str | None]:
    """
    Generiert ein Video nur aus Text (Pure Text-to-Video).
    Rückgabe: (video_path, used_model) oder (None, Fehlermeldung)
    """
    global active_task_id

    if not DASHSCOPE_API_KEY:
        return None, "❌ DASHSCOPE_API_KEY fehlt."

    clean_prompt = (prompt or "").strip()
    if len(clean_prompt) < 10:
        return None, "❌ Prompt ist zu kurz."

    norm_duration = max(2, min(int(duration), 15))
    norm_res = resolution.upper() if resolution.upper() in {"480P", "720P", "1080P"} else "720P"
    norm_ratio = aspect_ratio if aspect_ratio in {"16:9", "9:16", "1:1", "4:3", "3:4"} else "16:9"

    async with httpx.AsyncClient(timeout=180.0) as client:
        for model in MODEL_LIST:
            model_name = model["name"]
            logger.info(f"[TTV26] Versuche Video mit {model_name} — {norm_duration}s | {norm_res} | {norm_ratio}")

            payload = {
                "model": model_name,
                "input": {"prompt": clean_prompt},
                "parameters": {
                    "resolution": norm_res,
                    "duration": norm_duration,
                    "aspect_ratio": norm_ratio,
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
                    logger.error(f"[TTV26] Create fehlgeschlagen: {error.get('message') or create_resp.text}")
                    continue

                task_id = create_resp.json().get("output", {}).get("task_id")
                if not task_id:
                    continue

                async with active_task_lock:
                    active_task_id = task_id

                poll_url = f"{POLL_URL_BASE}{task_id}"

                for _ in range(90):
                    await asyncio.sleep(4.0)

                    if _ == 0:
                        start_time = asyncio.get_event_loop().time()
                
                    if asyncio.get_event_loop().time() - start_time > MAX_POLL_TIME_SECONDS:
                        logger.warning("[TTV26] Timeout nach 5 Minuten")
                        break

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
                            logger.info(f"[TTV26] ✅ Video erfolgreich mit {model_name}")
                            return path, model_name

                    elif status in ("FAILED", "UNKNOWN", "CANCELED"):
                        error_msg = result.get("output", {}).get("task_message", "Unbekannt")
                        logger.warning(f"[TTV26] Task FAILED mit {model_name}: {error_msg}")
                        break

            except Exception as exc:
                logger.warning(f"[TTV26] Fehler bei {model_name}: {exc}")

            finally:
                async with active_task_lock:
                    if active_task_id == task_id:
                        active_task_id = None

    async with active_task_lock:
        active_task_id = None

    return None, "❌ Alle Modelle fehlgeschlagen. Der Prompt wurde wahrscheinlich von der Moderation blockiert."
