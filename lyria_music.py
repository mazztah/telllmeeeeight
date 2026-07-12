# lyria_music.py – Fixed for Google GenAI SDK
import asyncio
import logging
import os
from io import BytesIO
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

async def generate_lyria_music(prompt: str, use_pro: bool = True) -> tuple[BytesIO | None, str | None]:
    if not client:
        return None, None

    model_name = "lyria-3-pro-preview" if use_pro else "lyria-3-clip-preview"
    
    try:
        # FIX: response_mime_type ENTFERNT, da dies nur für Text/JSON erlaubt ist.
        # Audio wird allein über response_modalities gesteuert.
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO", "TEXT"],
        )

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=prompt.strip(),
            config=config,
        )

        audio_data = None
        lyrics_parts = []

        for part in response.parts:
            if part.text:
                lyrics_parts.append(part.text)
            elif part.inline_data and part.inline_data.data:
                audio_data = part.inline_data.data

        lyrics = "\n".join(lyrics_parts).strip() if lyrics_parts else None
        if not audio_data:
            return None, lyrics

        return BytesIO(audio_data), lyrics
    except Exception as e:
        logger.error(f"Lyria Fehler: {e}")
        return None, None

def format_music_caption(prompt: str, lyrics: str | None = None) -> str:
    caption = f"🎵 **Lyria 3** • {prompt[:100]}"
    if lyrics:
        caption += f"\n\n📜 **Lyrics:**\n{lyrics[:400]}"
    return caption
