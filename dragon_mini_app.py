"""
Dragon Jump v2.1 - FastAPI Mini App Backend
Leaderboard Fix
"""

import logging
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    from brain import load_all_entries, save_file
    BRAIN_AVAILABLE = True
except ImportError:
    BRAIN_AVAILABLE = False
    logger.warning("Brain not available")

# ═══ MODELS ═══

class ScoreRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=30)
    score: int = Field(..., ge=0)
    level: int = Field(..., ge=1)
    coins: int = Field(default=0, ge=0)
    date: str = Field(default_factory=lambda: datetime.now().isoformat())
    user_id: int = Field(default=None)


# ═══ STORAGE ═══

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
SCORES_FILE = DATA_DIR / "dragon_scores.json"


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_file() -> list:
    _ensure_dir()
    if not SCORES_FILE.exists():
        return []
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Load error: {e}")
        return []


def _save_file(scores: list):
    _ensure_dir()
    try:
        with open(SCORES_FILE, "w", encoding="utf-8") as f:
            json.dump(scores, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save error: {e}")


async def _load_brain(chat_id: str = "global") -> list:
    if not BRAIN_AVAILABLE:
        return _load_file()

    try:
        entries = await load_all_entries(chat_id)
        scores = []

        for entry in entries:
            if "dragon_score" in entry.get("title", ""):
                try:
                    content = entry.get("content", "")
                    data = json.loads(content) if isinstance(content, str) else content
                    if isinstance(data, dict) and "score" in data:
                        scores.append(data)
                except Exception:
                    continue

        scores.sort(key=lambda x: x.get("score", 0), reverse=True)
        return scores

    except Exception as e:
        logger.error(f"Brain error: {e}")
        return _load_file()


async def _save_brain(score_data: dict, chat_id: str = "global") -> bool:
    if not BRAIN_AVAILABLE:
        scores = _load_file()
        scores.append(score_data)
        scores.sort(key=lambda x: x.get("score", 0), reverse=True)
        _save_file(scores[:100])
        return True

    try:
        username = score_data.get("username", "unknown")
        score = score_data.get("score", 0)
        entry_id = f"dragon_score_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{username}_{score}"

        await save_file(
            chat_id=chat_id,
            entry_id=entry_id,
            title=f"dragon_score_{username}_{score}",
            content=json.dumps(score_data),
            filename=f"{entry_id}.json",
            mime_type="application/json"
        )
        return True

    except Exception as e:
        logger.error(f"Brain save error: {e}")
        scores = _load_file()
        scores.append(score_data)
        scores.sort(key=lambda x: x.get("score", 0), reverse=True)
        _save_file(scores[:100])
        return True


# ═══ APP ═══

app = FastAPI(
    title="Dragon Jump v2.1",
    description="Street Life Edition - Speed Fix",
    version="2.1.0"
)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="dragon_static")


@app.get("/", response_class=HTMLResponse)
async def game_page():
    html_file = TEMPLATES_DIR / "dragon.html"

    if html_file.exists():
        with open(html_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    return HTMLResponse("<html><body><h1>Dragon Jump</h1><p>Upload static files</p></body></html>")


@app.post("/api/dragon/score")
async def submit_score(request: ScoreRequest):
    try:
        score_data = {
            "username": request.username,
            "score": request.score,
            "level": request.level,
            "coins": request.coins,
            "date": request.date,
            "user_id": request.user_id,
            "game": "dragon_jump_v2"
        }

        success = await _save_brain(score_data)

        if success:
            logger.info(f"Score saved: {request.username} - {request.score}")
            return JSONResponse({
                "success": True,
                "message": "Score saved!"
            })
        else:
            raise HTTPException(status_code=500, detail="Save failed")

    except Exception as e:
        logger.error(f"Submit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dragon/leaderboard")
async def get_leaderboard(limit: int = 20, chat_id: str = "global"):
    try:
        scores = await _load_brain(chat_id)

        # FIXED: Better deduplication - keep best score per user
        seen_users = {}
        for s in scores:
            user = s.get("username", "unknown")
            if user not in seen_users or s.get("score", 0) > seen_users[user].get("score", 0):
                seen_users[user] = s

        unique_scores = list(seen_users.values())
        unique_scores.sort(key=lambda x: x.get("score", 0), reverse=True)

        return {
            "success": True,
            "scores": unique_scores[:limit],
            "total_entries": len(scores),
            "unique_players": len(unique_scores)
        }

    except Exception as e:
        logger.error(f"Leaderboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dragon/stats")
async def get_stats():
    try:
        scores = await _load_brain()

        if not scores:
            return {
                "total_games": 0,
                "unique_players": 0,
                "highest_score": 0,
                "average_score": 0,
                "highest_level": 1
            }

        unique_players = len(set(s.get("username") for s in scores))
        highest_score = max(s.get("score", 0) for s in scores)
        highest_level = max(s.get("level", 1) for s in scores)
        average_score = sum(s.get("score", 0) for s in scores) // len(scores)

        return {
            "total_games": len(scores),
            "unique_players": unique_players,
            "highest_score": highest_score,
            "average_score": average_score,
            "highest_level": highest_level
        }

    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/dragon/health")
async def health_check():
    return {
        "status": "ok",
        "game": "dragon_jump_v2",
        "brain_available": BRAIN_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }
