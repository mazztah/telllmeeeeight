"""
Space War - FastAPI Mini App Backend v2.3
FIXED: Exports 'app' (like other mini apps) for app.mount()
"""
import logging, json, os
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    from brain import load_all_entries, save_file
    BRAIN_AVAILABLE = True
except ImportError:
    BRAIN_AVAILABLE = False
    logger.warning("Brain not available - using file fallback")

class ScoreRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=30)
    score: int = Field(..., ge=0)
    level: int = Field(..., ge=1)
    coins: int = Field(default=0, ge=0)
    date: str = Field(default_factory=lambda: datetime.now().isoformat())
    user_id: int = Field(default=None)

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
SCORES_FILE = DATA_DIR / "spacewar_scores.json"

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
            if "spacewar_score" in entry.get("title", ""):
                try:
                    content = entry.get("content", "")
                    data = json.loads(content) if isinstance(content, str) else content
                    if isinstance(data, dict) and "score" in data:
                        scores.append(data)
                except:
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
        entry_id = f"spacewar_score_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{username}_{score}"
        await save_file(
            chat_id=chat_id,
            entry_id=entry_id,
            title=f"spacewar_score_{username}_{score}",
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

# Create the app (like other mini apps: voice_mini_app, scanner_mini_app, etc.)
app = FastAPI(title="Space War", description="Galactic Shooter", version="2.3.0")

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

# Read the standalone HTML file
HTML_FILE = TEMPLATES_DIR / "space_war.html"
HTML_CONTENT = ""
if HTML_FILE.exists():
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        HTML_CONTENT = f.read()
    logger.info(f"✅ Loaded space_war.html ({len(HTML_CONTENT)} chars)")
else:
    logger.error(f"❌ space_war.html NOT FOUND at {HTML_FILE}")

@app.get("/", response_class=HTMLResponse)
async def game_page():
    """Space War game page at /spacewar/ (mounted at root by main.py)"""
    if HTML_CONTENT:
        return HTMLResponse(
            content=HTML_CONTENT,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return HTMLResponse("<html><body><h1>Space War</h1><p>Upload space_war.html to templates/</p></body></html>")

@app.post("/api/score")
async def submit_score(request: ScoreRequest):
    try:
        score_data = {
            "username": request.username,
            "score": request.score,
            "level": request.level,
            "coins": request.coins,
            "date": request.date,
            "user_id": request.user_id,
            "game": "space_war"
        }
        success = await _save_brain(score_data)
        if success:
            logger.info(f"Score saved: {request.username} - {request.score}")
            return JSONResponse({"success": True, "message": "Score saved!"})
        raise HTTPException(status_code=500, detail="Save failed")
    except Exception as e:
        logger.error(f"Submit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 20, chat_id: str = "global"):
    try:
        scores = await _load_brain(chat_id)
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

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "game": "space_war",
        "version": "2.3.0",
        "html_loaded": len(HTML_CONTENT) > 0,
        "brain_available": BRAIN_AVAILABLE,
        "timestamp": datetime.now().isoformat()
    }

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response
