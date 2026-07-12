import webbrowser
import subprocess
from typing import Optional, List, Dict, Tuple
from sclib import SoundcloudAPI, Track

class SoundCloudBackend:
    # Deine Lieblings-Playlist (bereits eingetragen)
    FAVORITE_PLAYLIST_URL = "https://soundcloud.com/filip-maka/sets/allwweeellll"

    def __init__(self, default_player: str = "vlc"):
        self.api = SoundcloudAPI()
        self.default_player = default_player

    def play_favorite_playlist(self) -> Tuple[str, str]:
        """Telegram HTML embed - returns (bot_text, embed_html). No browser.open"""
        widget_url = (
            f"https://w.soundcloud.com/player/?url={self.FAVORITE_PLAYLIST_URL}"
            f"&auto_play=false&show_artwork=true&color=%23ff5500"
        )

        bot_text = (
            "🎵 **Allwweeellll Playlist** (5 Tracks)\n\n"
            "Ähm … das sind meine absoluten Favoriten …\n"
            "Jeder Track hat eine besondere Stimmung …\n"
            "Klick Play unten! 🎧"
        )

        embed_html = f'''<iframe width="100%" height="166" scrolling="no" frameborder="no" allow="autoplay" src="{widget_url}" style="border-radius:12px;"></iframe>'''

        return bot_text, embed_html

    def search_tracks(self, query: str, limit: int = 12) -> List[Dict]:
        try:
            results = self.api.search(query, limit=limit)
            tracks = []
            for item in results:
                if isinstance(item, Track):
                    duration = f"{item.duration // 1000 // 60}:{item.duration // 1000 % 60:02d}"
                    tracks.append({
                        "title": item.title,
                        "artist": item.artist,
                        "duration": duration,
                        "track_obj": item
                    })
            return tracks
        except Exception:
            return []

    def play_track(self, track_obj: Track, player: Optional[str] = None):
        player = player or self.default_player
        try:
            stream_url = track_obj.get_stream_url()
            if not stream_url:
                print("⚠️ Kein Stream verfügbar.")
                return

            if player == "vlc":
                subprocess.run(["vlc", "--play-and-exit", "--quiet", stream_url],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif player == "mpv":
                subprocess.run(["mpv", "--no-video", "--quiet", stream_url])
        except Exception as e:
            print(f"Fehler beim Abspielen: {e}")

