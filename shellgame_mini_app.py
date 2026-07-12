# shellgame_mini_app.py – Cyberpunk Shell Game Mini-App für Telegram
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import json
import logging
import os

logger = logging.getLogger(__name__)

app = FastAPI(title="Neon Shell Game 2077 🎰")

# ── Statische Dateien servieren (CSS, JS falls extern) ───────────────────────
STATIC_DIR = Path(__file__).with_name("static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Template laden ───────────────────────────────────────────────────────────
TEMPLATE_PATH = Path(__file__).with_name("templates") / "shellgame.html"
if not TEMPLATE_PATH.exists():
    TEMPLATE_PATH = Path("templates/shellgame.html")

HTML_TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8") if TEMPLATE_PATH.exists() else "<!-- Template fehlt -->"

# ── Score Persistenz ─────────────────────────────────────────────────────────
# HF Spaces Support
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError) as exc:
    # "/data" ist nur auf Plattformen mit gemountetem Persistent Storage
    # beschreibbar (z.B. HF Spaces). Auf Cloud Run, Render & Co. ohne Disk
    # existiert "/data" nicht und kann vom non-root User nicht angelegt
    # werden -> Fallback auf einen lokalen Ordner neben dem Code.
    fallback_dir = Path(__file__).resolve().parent / "data"
    logger.warning(
        "DATA_DIR '%s' nicht beschreibbar (%s) – verwende Fallback '%s'",
        DATA_DIR, exc, fallback_dir,
    )
    DATA_DIR = fallback_dir
    DATA_DIR.mkdir(parents=True, exist_ok=True)

SCORE_FILE = DATA_DIR / "shellgame_scores.json"


def _load_scores() -> dict:
    if SCORE_FILE.exists():
        try:
            with open(SCORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Score-Laden fehlgeschlagen: %s", e)
    return {}


def _save_scores(scores: dict) -> None:
    try:
        with open(SCORE_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Score-Speicherung fehlgeschlagen: %s", e)


@app.get("/", response_class=HTMLResponse)
async def shellgame_page(request: Request):
    """Liefert die Shellgame HTML-Seite."""
    return HTMLResponse(HTML_TEMPLATE)


@app.post("/api/save_score")
async def save_score(request: Request):
    """Empfängt Score-Daten und speichert sie serverseitig."""
    try:
        body = await request.json()
        user_name = body.get("name", "").strip()
        balance = body.get("balance", 0)
        highscore = body.get("highscore", 0)

        if not user_name:
            return JSONResponse({"success": False, "error": "name required"})

        scores = _load_scores()

        # Update nur wenn neuer Highscore oder User noch nicht existiert
        existing = scores.get(user_name, {})
        new_highscore = max(highscore, existing.get("highscore", 0))
        new_balance = balance  # Aktueller Stand wird immer gespeichert

        scores[user_name] = {
            "balance": new_balance,
            "highscore": new_highscore,
        }
        _save_scores(scores)

        return JSONResponse({"success": True, "highscore": new_highscore})

    except Exception as e:
        logger.exception("Save-Score Fehler")
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/leaderboard")
async def get_leaderboard():
    """Liefert das Top 5 Leaderboard."""
    try:
        scores = _load_scores()
        sorted_scores = sorted(
            scores.items(),
            key=lambda x: x[1].get("highscore", 0),
            reverse=True,
        )[:5]

        leaderboard = [
            {
                "name": name,
                "highscore": stats.get("highscore", 0),
                "balance": stats.get("balance", 0),
            }
            for name, stats in sorted_scores
        ]

        return JSONResponse({"success": True, "leaderboard": leaderboard})

    except Exception as e:
        logger.exception("Leaderboard Fehler")
        return JSONResponse({"success": False, "error": str(e)})