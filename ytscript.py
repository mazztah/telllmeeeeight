import asyncio
import html
import logging
import os
import re
import textwrap
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import httpx
import requests
from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi
from dv import create_pdf_from_text

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("XAI_API_KEY")

YOUTUBE_HOST_MARKERS = (
    "youtube.com/",
    "youtu.be/",
    "m.youtube.com/",
    "music.youtube.com/",
    "youtube-nocookie.com/",
)

YOUTUBE_URL_PATTERN = re.compile(r"(https?://[^\s]+|(?:www\.)?[^\s]+)")
VIDEO_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]{11}$")
TRANSCRIPT_LANGUAGES = ["de", "en"]

_groq_client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client()) if GROQ_API_KEY else None


def extract_youtube_url(text: str) -> str | None:
    if not text:
        return None

    for raw_candidate in YOUTUBE_URL_PATTERN.findall(text):
        candidate = raw_candidate.strip().rstrip(".,!?)]}>\"'")
        lower_candidate = candidate.lower()

        if not any(marker in lower_candidate for marker in YOUTUBE_HOST_MARKERS):
            continue

        normalized = candidate if lower_candidate.startswith(("http://", "https://")) else f"https://{candidate}"
        if extract_video_id(normalized):
            return normalized

    return None


def extract_video_id(url: str) -> str | None:
    if not url:
        return None

    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().replace("www.", "").replace("m.", "")
    path_parts = [part for part in parsed.path.split("/") if part]

    video_id = None

    if host == "youtu.be" and path_parts:
        video_id = path_parts[0]
    elif "youtube" in host:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif path_parts and path_parts[0] in {"shorts", "embed", "live", "v"} and len(path_parts) > 1:
            video_id = path_parts[1]

    if video_id and VIDEO_ID_PATTERN.fullmatch(video_id):
        return video_id

    return None


def _clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _truncate(text: str, limit: int) -> str:
    text = _clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def fetch_video_metadata(video_id: str, language: str = "de") -> dict:
    result = {
        "success": False,
        "title": "YouTube-Video",
        "description": "",
        "channel_title": "",
        "published_at": "",
        "duration": "",
        "caption_state": "",
        "error": None,
    }

    if not YOUTUBE_API_KEY:
        result["error"] = "YOUTUBE_API_KEY fehlt. Die Video-Beschreibung kann nur über die YouTube Data API geladen werden."
        return result

    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "snippet,contentDetails",
                "id": video_id,
                "hl": language,
                "key": YOUTUBE_API_KEY,
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") or []

        if not items:
            result["error"] = "Video nicht gefunden oder nicht über die YouTube Data API abrufbar."
            return result

        item = items[0]
        snippet = item.get("snippet", {})
        localized = snippet.get("localized", {})
        content_details = item.get("contentDetails", {})

        result.update(
            {
                "success": True,
                "title": localized.get("title") or snippet.get("title") or result["title"],
                "description": localized.get("description") or snippet.get("description") or "",
                "channel_title": snippet.get("channelTitle") or "",
                "published_at": snippet.get("publishedAt") or "",
                "duration": content_details.get("duration") or "",
                "caption_state": content_details.get("caption") or "",
                "error": None,
            }
        )
        return result

    except Exception as exc:
        logger.exception("YouTube-Metadaten konnten nicht geladen werden")
        result["error"] = str(exc)
        return result


def _normalize_transcript(raw_transcript) -> dict:
    if hasattr(raw_transcript, "to_raw_data"):
        segments = raw_transcript.to_raw_data()
        language = getattr(raw_transcript, "language", "")
        language_code = getattr(raw_transcript, "language_code", "")
        is_generated = getattr(raw_transcript, "is_generated", None)
    else:
        segments = raw_transcript or []
        language = ""
        language_code = ""
        is_generated = None

    full_text = _clean_text(" ".join(segment.get("text", "") for segment in segments if segment.get("text")))

    return {
        "success": bool(full_text),
        "text": full_text,
        "segments": segments,
        "language": language,
        "language_code": language_code,
        "is_generated": is_generated,
        "error": None if full_text else "Kein Transcript verfügbar.",
    }


def fetch_transcript(video_id: str, languages: list[str] | None = None) -> dict:
    preferred_languages = languages or TRANSCRIPT_LANGUAGES
    transcript_list = None

    try:
        api = YouTubeTranscriptApi()

        if hasattr(api, "fetch"):
            return _normalize_transcript(api.fetch(video_id, languages=preferred_languages))

        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            return _normalize_transcript(YouTubeTranscriptApi.get_transcript(video_id, languages=preferred_languages))

    except Exception as primary_error:
        logger.warning("Primärer Transcript-Abruf fehlgeschlagen: %s", primary_error)

        try:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
            transcript = transcript_list.find_transcript(preferred_languages)
            return _normalize_transcript(transcript.fetch())
        except Exception:
            try:
                first_transcript = next(iter(transcript_list))
                if getattr(first_transcript, "is_translatable", False):
                    target_language = preferred_languages[0]
                    return _normalize_transcript(first_transcript.translate(target_language).fetch())
                return _normalize_transcript(first_transcript.fetch())
            except Exception as fallback_error:
                logger.warning("Transcript-Fallback fehlgeschlagen: %s", fallback_error)
                return {
                    "success": False,
                    "text": "",
                    "segments": [],
                    "language": "",
                    "language_code": "",
                    "is_generated": None,
                    "error": str(primary_error),
                }

    return {
        "success": False,
        "text": "",
        "segments": [],
        "language": "",
        "language_code": "",
        "is_generated": None,
        "error": "Kein kompatibler youtube-transcript-api Aufruf gefunden.",
    }


def _fallback_summary(text: str, description: str = "") -> str:
    source = _clean_text(text) or _clean_text(description)
    if not source:
        return "Keine Zusammenfassung möglich, weil weder Transcript noch Beschreibung verfügbar sind."

    sentences = re.split(r"(?<=[.!?])\s+", source)
    picked = []

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 30:
            continue
        picked.append(sentence)
        if len(" ".join(picked)) >= 650 or len(picked) >= 4:
            break

    if not picked:
        return _truncate(source, 650)

    return _truncate(" ".join(picked), 650)


def generate_summary(title: str, description: str, transcript: str) -> str:
    if not _groq_client:
        return _fallback_summary(transcript, description)

    transcript_excerpt = _truncate(transcript, 14000)
    description_excerpt = _truncate(description, 2500)

    try:
        completion = _groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            temperature=0.2,
            max_tokens=320,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du fasst YouTube-Videos knapp, klar und auf Deutsch zusammen. "
                        "Antworte in 4 bis 6 kurzen Sätzen ohne Bulletpoints."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Titel: {title or 'Unbekannt'}\n\n"
                        f"Beschreibung:\n{description_excerpt or 'Keine Beschreibung'}\n\n"
                        f"Transcript:\n{transcript_excerpt or 'Kein Transcript verfügbar'}"
                    ),
                },
            ],
        )
        summary = _clean_text(completion.choices[0].message.content)
        return summary or _fallback_summary(transcript, description)

    except Exception as exc:
        logger.warning("Zusammenfassung per Groq fehlgeschlagen: %s", exc)
        return _fallback_summary(transcript, description)


async def get_youtube_script(video_url: str) -> dict:
    video_id = extract_video_id(video_url)
    if not video_id:
        return {
            "success": False,
            "error": "Ungültiger YouTube-Link.",
            "video_url": video_url,
        }

    metadata = await asyncio.to_thread(fetch_video_metadata, video_id, "de")
    transcript = await asyncio.to_thread(fetch_transcript, video_id, TRANSCRIPT_LANGUAGES)
    summary = await asyncio.to_thread(
        generate_summary,
        metadata.get("title", ""),
        metadata.get("description", ""),
        transcript.get("text", ""),
    )

    success = metadata.get("success") or transcript.get("success")

    return {
        "success": success,
        "video_id": video_id,
        "video_url": video_url,
        "title": metadata.get("title") or "YouTube-Video",
        "description": metadata.get("description") or "",
        "channel_title": metadata.get("channel_title") or "",
        "published_at": metadata.get("published_at") or "",
        "duration": metadata.get("duration") or "",
        "caption_state": metadata.get("caption_state") or "",
        "transcript": transcript.get("text") or "",
        "transcript_language": transcript.get("language") or transcript.get("language_code") or "",
        "summary": summary,
        "metadata_error": metadata.get("error"),
        "transcript_error": transcript.get("error"),
        "error": None if success else metadata.get("error") or transcript.get("error") or "Unbekannter Fehler",
    }


def format_youtube_result_for_user(result: dict) -> str:
    title = html.escape(result.get("title") or "YouTube-Video")
    description = _truncate(result.get("description") or "Keine Beschreibung verfügbar.", 900)
    summary = _truncate(result.get("summary") or "Keine Zusammenfassung verfügbar.", 1100)
    transcript = result.get("transcript") or ""
    transcript_preview = _truncate(transcript, 1400) if transcript else ""

    lines = [f"<b>🎬 {title}</b>"]

    if result.get("channel_title"):
        lines.append(f"<b>📺 Kanal:</b> {html.escape(result['channel_title'])}")
    if result.get("published_at"):
        lines.append(f"<b>📅 Veröffentlicht:</b> <code>{html.escape(result['published_at'][:10])}</code>")
    if result.get("duration"):
        lines.append(f"<b>⏱ Dauer:</b> <code>{html.escape(result['duration'])}</code>")

    lines.extend(
        [
            "",
            "<b>📝 Beschreibung</b>",
            html.escape(description),
            "",
            "<b>✨ Zusammenfassung</b>",
            html.escape(summary),
        ]
    )

    if transcript_preview:
        lines.extend(
            [
                "",
                "<b>📄 Transcript</b>",
                html.escape(transcript_preview),
            ]
        )
        if len(transcript) > len(transcript_preview):
            lines.append("")
            lines.append("<i>Das vollständige Transcript kommt zusätzlich als TXT-Datei.</i>")
    else:
        lines.extend(
            [
                "",
                "<b>📄 Transcript</b>",
                html.escape(result.get("transcript_error") or "Kein Transcript gefunden."),
            ]
        )

    if result.get("metadata_error") and not result.get("description"):
        lines.append("")
        lines.append(
            "<i>Hinweis: Beschreibung konnte nicht vollständig über die YouTube Data API geladen werden: "
            f"{html.escape(result['metadata_error'])}</i>"
        )

    return "\n".join(lines)


def build_youtube_export_file(result: dict) -> BytesIO:
    safe_title = re.sub(r"[^0-9A-Za-z_-]+", "_", result.get("title") or "youtube_video").strip("_") or "youtube_video"
    filename = f"{safe_title[:50]}_{result.get('video_id', 'video')}.txt"

    content = "\n".join(
        [
            f"Titel: {result.get('title') or 'YouTube-Video'}",
            f"URL: {result.get('video_url') or ''}",
            f"Video-ID: {result.get('video_id') or ''}",
            f"Kanal: {result.get('channel_title') or ''}",
            f"Veröffentlicht: {result.get('published_at') or ''}",
            f"Dauer: {result.get('duration') or ''}",
            "",
            "Beschreibung",
            "============",
            result.get("description") or "Keine Beschreibung verfügbar.",
            "",
            "Zusammenfassung",
            "===============",
            result.get("summary") or "Keine Zusammenfassung verfügbar.",
            "",
            "Transcript",
            "==========",
            result.get("transcript") or (result.get("transcript_error") or "Kein Transcript verfügbar."),
            "",
        ]
    )

    buffer = BytesIO(content.encode("utf-8"))
    buffer.seek(0)
    buffer.name = filename
    return buffer


def _wrap_for_pdf(text: str, width: int = 90) -> str:
    wrapped_lines = []

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            wrapped_lines.append("")
            continue

        wrapped = textwrap.wrap(
            line,
            width=width,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=False,
            break_on_hyphens=False,
        )
        wrapped_lines.extend(wrapped or [""])

    return "\n".join(wrapped_lines).strip()


def build_youtube_pdf(result: dict, mode: str = "transcript") -> tuple[BytesIO, str, str]:
    safe_title = re.sub(r"[^0-9A-Za-z_-]+", "_", result.get("title") or "youtube_video").strip("_") or "youtube_video"
    title = result.get("title") or "YouTube-Video"

    base_header = [
        f"Titel: {title}",
        f"URL: {result.get('video_url') or ''}",
        f"Video-ID: {result.get('video_id') or ''}",
        f"Kanal: {result.get('channel_title') or ''}",
        f"Veroeffentlicht: {result.get('published_at') or ''}",
        f"Dauer: {result.get('duration') or ''}",
        "",
    ]

    if mode in {"transcript", "transcript_download"}:
        body = base_header + [
            "Transcript",
            "==========",
            result.get("transcript") or (result.get("transcript_error") or "Kein Transcript verfuegbar."),
        ]
        filename = f"{safe_title[:50]}_{result.get('video_id', 'video')}_transcript.pdf"
        caption = "PDF mit Transcript"
    elif mode in {"summary", "summary_download"}:
        body = base_header + [
            "Beschreibung",
            "============",
            result.get("description") or "Keine Beschreibung verfuegbar.",
            "",
            "Zusammenfassung",
            "===============",
            result.get("summary") or "Keine Zusammenfassung verfuegbar.",
        ]
        filename = f"{safe_title[:50]}_{result.get('video_id', 'video')}_summary.pdf"
        caption = "PDF mit Beschreibung und Zusammenfassung"
    else:
        body = base_header + [
            "Beschreibung",
            "============",
            result.get("description") or "Keine Beschreibung verfuegbar.",
            "",
            "Zusammenfassung",
            "===============",
            result.get("summary") or "Keine Zusammenfassung verfuegbar.",
            "",
            "Transcript",
            "==========",
            result.get("transcript") or (result.get("transcript_error") or "Kein Transcript verfuegbar."),
        ]
        filename = f"{safe_title[:50]}_{result.get('video_id', 'video')}_full.pdf"
        caption = "PDF mit Transcript und Zusammenfassung"

    pdf_text = _wrap_for_pdf("\n".join(body))
    pdf_buffer = create_pdf_from_text(pdf_text, title=filename)
    pdf_buffer.seek(0)
    pdf_buffer.name = filename
    return pdf_buffer, filename, caption
