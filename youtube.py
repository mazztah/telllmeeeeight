# youtube.py – LUXUS VERSION 2026 (Queen’s Crystal Ball Edition)
import re
import logging
import requests
import os
from io import BytesIO
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from youtube_transcript_api.formatters import TextFormatter, SRTFormatter

from dv import create_pdf_from_text
from brain import save_text

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")  # ← in .env eintragen!

def extract_video_id(url: str) -> str | None:
    match = re.search(r"(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None


async def fetch_official_metadata(video_id: str):
    """Offizielle YouTube Data API v3 – Description, Title, Thumbnails"""
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "snippet,contentDetails",
        "id": video_id,
        "key": YOUTUBE_API_KEY
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        item = data["items"][0]
        return {
            "title": item["snippet"]["title"],
            "description": item["snippet"]["description"],
            "thumbnail": item["snippet"]["thumbnails"]["maxres"]["url"] if "maxres" in item["snippet"]["thumbnails"] else item["snippet"]["thumbnails"]["high"]["url"]
        }
    except:
        return {"title": "Unbekanntes Video", "description": "Keine Beschreibung verfügbar", "thumbnail": None}


async def get_transcript(video_id: str):
    """Transcript mit Zeitstempeln (Fallback auf offizielle API möglich)"""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['de', 'en'])
        return {
            "text": TextFormatter().format_transcript(transcript),
            "srt": SRTFormatter().format_transcript(transcript),
            "raw": transcript
        }
    except:
        return {"text": None, "srt": None, "raw": None}


async def process_youtube_link(chat_id: str, video_url: str, context):
    video_id = extract_video_id(video_url)
    if not video_id:
        await context.bot.send_message(chat_id=chat_id, text="❌ Kein gültiger YouTube-Link, Digga 😭")
        return

    loading = await context.bot.send_message(chat_id=chat_id, text="🌟 Queen’s Crystal Ball wird aktiviert... ✨")

    metadata = await fetch_official_metadata(video_id)
    transcript_data = await get_transcript(video_id)

    base_data = {
        "video_id": video_id,
        "video_url": video_url,
        "title": metadata["title"],
        "description": metadata["description"],
        "thumbnail": metadata["thumbnail"],
        "transcript": transcript_data["text"] or "Kein Transcript verfügbar",
        "srt": transcript_data["srt"]
    }

    # Luxus-Keyboard
    keyboard = [
        [{"text": "📝 Queen-Zusammenfassung", "callback_data": f"yt:summary:{video_id}"}],
        [{"text": "🔥 Queen Roast Version", "callback_data": f"yt:roast:{video_id}"}],
        [{"text": "📌 Key Points", "callback_data": f"yt:keypoints:{video_id}"}],
        [{"text": "⏱️ Voll-Transcript mit Timestamps", "callback_data": f"yt:timestamps:{video_id}"}],
        [{"text": "📜 Description anzeigen", "callback_data": f"yt:description:{video_id}"}],
        [{"text": "📄 PDF erstellen", "callback_data": f"yt:pdf:{video_id}"}],
        [{"text": "📜 TXT herunterladen", "callback_data": f"yt:txt:{video_id}"}],
        [{"text": "⏱️ SRT herunterladen", "callback_data": f"yt:srt:{video_id}"}],
    ]

    from telegram import InlineKeyboardMarkup
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=loading.message_id,
        text=f"🌸 **Queen’s Crystal Ball** hat gesprochen!\n\n**{metadata['title']}**\n\nWas darf ich für dich zaubern, meine Königin?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    context.bot_data[f"yt_{video_id}"] = base_data
