import os
from datetime import datetime, timedelta
from typing import Iterable

import httpx

BUFFER_ACCESS_TOKEN = os.getenv("BUFFER_ACCESS_TOKEN")
BUFFER_PROFILE_ID = os.getenv("BUFFER_PROFILE_ID")

PLATFORM_GUIDANCE = {
    "instagram": {
        "tone": "visuell, klarer Hook in den ersten 125 Zeichen",
        "best_windows": ["08:30", "12:30", "18:30"],
        "hashtags": 8,
        "caption_limit": 2200,
    },
    "tiktok": {
        "tone": "direkter Hook, kurze Zeilen, starker CTA",
        "best_windows": ["09:00", "17:00", "20:30"],
        "hashtags": 6,
        "caption_limit": 400,
    },
    "linkedin": {
        "tone": "kompetent, persoenlich, wenige Emojis",
        "best_windows": ["07:45", "12:15", "17:45"],
        "hashtags": 5,
        "caption_limit": 3000,
    },
}


def _normalize_platforms(platforms: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw_value in platforms or ["instagram", "tiktok"]:
        platform = (raw_value or "").strip().lower()
        if platform in PLATFORM_GUIDANCE and platform not in normalized:
            normalized.append(platform)
    return normalized or ["instagram", "tiktok"]


def _extract_keywords(text: str, limit: int = 8) -> list[str]:
    words: list[str] = []
    for raw_word in (text or "").replace("#", " ").split():
        word = "".join(ch for ch in raw_word.lower() if ch.isalnum())
        if len(word) < 4 or word in words:
            continue
        words.append(word)
        if len(words) >= limit:
            break
    return words


def _build_caption_variants(caption: str, hook: str, limit: int) -> dict[str, str]:
    clean_caption = (caption or "").strip()
    clean_hook = (hook or "").strip()
    combined = f"{clean_hook}\n\n{clean_caption}".strip()
    short = combined[:limit].strip()
    if len(combined) > limit:
        short = short.rstrip() + "..."
    return {
        "primary": clean_caption[:limit].strip() or short,
        "hook_first": short,
    }


def suggest_next_slot(platform: str = "instagram", now: datetime | None = None) -> datetime:
    rules = PLATFORM_GUIDANCE.get(platform, PLATFORM_GUIDANCE["instagram"])
    current = now or datetime.now()

    for candidate_time in rules["best_windows"]:
        hour, minute = [int(part) for part in candidate_time.split(":")]
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > current:
            return candidate

    hour, minute = [int(part) for part in rules["best_windows"][0].split(":")]
    return (current + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def build_social_pack(
    title: str,
    caption: str,
    script: str,
    platforms: list[str] | None = None,
    hook: str | None = None,
) -> dict:
    selected = _normalize_platforms(platforms)
    source_text = f"{title}\n{caption}\n{script}\n{hook or ''}"
    keywords = _extract_keywords(source_text, limit=10)
    base_hashtags = [f"#{word}" for word in keywords]
    posts = []

    for platform in selected:
        rules = PLATFORM_GUIDANCE.get(platform, PLATFORM_GUIDANCE["instagram"])
        variants = _build_caption_variants(caption, hook or title, rules["caption_limit"])
        next_slot = suggest_next_slot(platform)
        posts.append(
            {
                "platform": platform,
                "tone": rules["tone"],
                "best_windows": rules["best_windows"],
                "next_slot": next_slot.isoformat(timespec="minutes"),
                "caption": variants["primary"],
                "hook_first_caption": variants["hook_first"],
                "hashtags": base_hashtags[: rules["hashtags"]],
                "cta": "Sag Bescheid, wenn ich daraus direkt Assets, eine Carousel-Struktur oder einen Buffer-Post bauen soll.",
            }
        )

    return {
        "title": title,
        "keywords": keywords,
        "posts": posts,
    }


def format_social_pack(pack: dict) -> str:
    posts = pack.get("posts") or []
    if not posts:
        return "Kein Social-Plan vorhanden."

    lines = [f"Social-Plan fuer: {pack.get('title', 'Unbenannt')}"]
    if pack.get("keywords"):
        lines.append(f"Keywords: {', '.join(pack['keywords'][:8])}")

    for post in posts:
        hashtags = " ".join(post.get("hashtags") or []) or "keine"
        lines.append(
            f"{post['platform'].upper()} | Beste Zeiten: {', '.join(post['best_windows'])} | Next Slot: {post.get('next_slot', '-')}\n"
            f"Ton: {post['tone']}\n"
            f"CTA: {post['cta']}\n"
            f"Hashtags: {hashtags}"
        )
    return "\n\n".join(lines)


def is_buffer_ready() -> bool:
    return bool(BUFFER_ACCESS_TOKEN and BUFFER_PROFILE_ID)


async def schedule_buffer_post(text: str, scheduled_at: datetime, media_url: str | None = None) -> dict:
    if not is_buffer_ready():
        return {"success": False, "message": "Buffer ist nicht konfiguriert."}

    payload = {
        "profile_ids": [BUFFER_PROFILE_ID],
        "text": text,
        "scheduled_at": scheduled_at.isoformat(),
    }
    if media_url:
        payload["media"] = {"link": media_url}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.bufferapp.com/1/updates/create.json",
            data=payload,
            headers={"Authorization": f"Bearer {BUFFER_ACCESS_TOKEN}"},
        )
        if response.status_code >= 400:
            return {"success": False, "message": response.text[:250]}
        return {"success": True, "message": "Buffer-Post eingeplant.", "data": response.json()}
