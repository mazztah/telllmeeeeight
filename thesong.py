# thesong.py – AudD Music Recognition (Shazam + Humming-Modus)
import os
import logging
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)

AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")

def has_audd_key() -> bool:
    return bool(AUDD_API_TOKEN and len(AUDD_API_TOKEN) > 15)

# ── NORMALER SONG (wie bisher) ─────────────────────────────────────
async def recognize_song(
    file_path: str,
    return_params: str = "spotify,apple_music,deezer",
    max_seconds: int = 25
) -> Dict:
    if not has_audd_key():
        return {"success": False, "error": "Kein AUDD_API_TOKEN!"}

    if not os.path.exists(file_path):
        return {"success": False, "error": "Datei nicht gefunden"}

    url = "https://api.audd.io/"

    try:
        with open(file_path, "rb") as audio_file:
            files = {"file": audio_file}
            data = {"api_token": AUDD_API_TOKEN, "return": return_params}

            response = requests.post(url, data=data, files=files, timeout=18)
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "success":
                song_data = result.get("result")
                return {
                    "success": True,
                    "result": song_data,
                    "mode": "normal"
                } if song_data else {"success": True, "result": None, "message": "Kein Song erkannt"}
            else:
                return {"success": False, "error": result.get("error", "AudD Fehler")}
    except Exception as e:
        logger.exception("recognize_song Fehler")
        return {"success": False, "error": str(e)[:120]}


# ── NEU: HUMMING / SUMMEN / PFEIFEN ─────────────────────────────────
async def recognize_humming(
    file_path: str,
    return_params: str = "spotify,apple_music,deezer"
) -> Dict:
    """
    Spezieller Modus für Summen, Pfeifen oder Gesang (weniger genau als normaler Song)
    Nutzt den recognizeWithOffset-Endpoint von AudD
    """
    if not has_audd_key():
        return {"success": False, "error": "Kein AUDD_API_TOKEN!"}

    if not os.path.exists(file_path):
        return {"success": False, "error": "Datei nicht gefunden"}

    url = "https://api.audd.io/recognizeWithOffset/"   # ← das war der fehlende Teil!

    try:
        with open(file_path, "rb") as audio_file:
            files = {"file": audio_file}
            data = {
                "api_token": AUDD_API_TOKEN,
                "return": return_params
                # Keine extra Parameter nötig – der Endpoint ist genau für Humming gedacht
            }

            response = requests.post(url, data=data, files=files, timeout=20)
            response.raise_for_status()
            result = response.json()

            if result.get("status") == "success":
                song_data = result.get("result")
                return {
                    "success": True,
                    "result": song_data,
                    "mode": "humming",
                    "offset_info": result.get("offset")  # extra Timing-Info
                } if song_data else {
                    "success": True,
                    "result": None,
                    "message": "Kein Song beim Summen erkannt (versuch länger oder klarer zu summen)"
                }
            else:
                return {"success": False, "error": result.get("error", "AudD Humming-Fehler")}
    except Exception as e:
        logger.exception("recognize_humming Fehler")
        return {"success": False, "error": str(e)[:120]}


def format_song_result(result_dict: Dict) -> str:
    """Funktioniert jetzt für BOTH Modi (normal + humming)"""
    if not result_dict.get("success"):
        return f"❌ Erkennung abgefuckt: {result_dict.get('error', 'no idea')} 😭"

    res = result_dict.get("result")
    if not res:
        mode = result_dict.get("mode", "normal")
        return f"🤷 Kein Song gefunden {'beim Summen' if mode == 'humming' else ''}, Digga. War das nur Atemgeräusche oder was? [sus af]"

    artist = res.get("artist", "Unbekannt")
    title = res.get("title", "Unbekannt")
    album = res.get("album", "")
    timecode = res.get("timecode", "")
    song_link = res.get("song_link", "")

    text = f"🎵 **BOOM – Song erkannt, du Legend!** {'(Humming-Modus)' if result_dict.get('mode') == 'humming' else ''}\n"
    text += f"**{title}** – {artist}\n"

    if album: text += f"Album: {album}\n"
    if timecode: text += f"Ab Minute: {timecode}\n"
    if song_link: text += f"🔗 {song_link}\n"

    for service in ["spotify", "apple_music", "deezer"]:
        if service in res:
            link = res[service].get("url") or ""
            if link:
                text += f"▶ **{service.capitalize()}**: {link}\n"

    return text.strip()
