# shellgame_mini_app.py – Cyberpunk Shell Game Mini-App für Telegram
#
# v2: Level/XP-System, Achievements, adaptive KI-Schwierigkeit,
#     Daily Challenge, Coach-Tipps. Bleibt bewusst als Single-File-App
#     im Stil der übrigen mini_apps im Projekt (kein Multiplayer/Redis/
#     Docker-Overhead – dafür fehlt hier die Infrastruktur und der Bedarf).
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import date
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

# ── Persistenz ────────────────────────────────────────────────────────────────
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

# ── Achievement-Definitionen ─────────────────────────────────────────────────
ACHIEVEMENTS = {
    "first_win":    {"label": "🥉 Erster Sieg",        "check": lambda p: p["wins"] >= 1},
    "wins_10":      {"label": "🥈 10 Siege",            "check": lambda p: p["wins"] >= 10},
    "wins_100":     {"label": "🥇 100 Siege",           "check": lambda p: p["wins"] >= 100},
    "streak_5":     {"label": "🔥 5 Siege in Folge",    "check": lambda p: p["best_streak"] >= 5},
    "streak_20":    {"label": "👑 Shell Master (20er-Streak)", "check": lambda p: p["best_streak"] >= 20},
    "quick_draw":   {"label": "⚡ Unter 1 Sekunde entschieden", "check": lambda p: (p.get("fastest_win_ms") or 99999) < 1000},
    "level_10":     {"label": "🌟 Level 10 erreicht",   "check": lambda p: p["level"] >= 10},
    "high_roller":  {"label": "💎 500 Credits in einer Runde gewonnen", "check": lambda p: p.get("biggest_win", 0) >= 500},
}

# ── Level/XP ──────────────────────────────────────────────────────────────────
def xp_for_level(level: int) -> int:
    """XP-Bedarf, um von `level` auf `level+1` zu kommen."""
    return 100 + (level - 1) * 40


def apply_xp(profile: dict, xp_gain: int) -> None:
    profile["xp"] = profile.get("xp", 0) + xp_gain
    while profile["xp"] >= xp_for_level(profile.get("level", 1)):
        profile["xp"] -= xp_for_level(profile["level"])
        profile["level"] = profile.get("level", 1) + 1
        profile["coins"] = profile.get("coins", 0) + 50  # Level-Up Bonus


# ── Default-Profil ───────────────────────────────────────────────────────────
def default_profile() -> dict:
    return {
        "balance": 1000,
        "highscore": 0,
        "xp": 0,
        "level": 1,
        "coins": 0,
        "wins": 0,
        "losses": 0,
        "total_games": 0,
        "streak": 0,
        "best_streak": 0,
        "fastest_win_ms": None,
        "biggest_win": 0,
        "achievements": [],
        "daily": {"date": None, "wins": 0, "losses": 0, "claimed": False},
        # letzte 10 Ergebnisse für die adaptive KI: 1 = gewonnen, 0 = verloren
        "recent_results": [],
        "recent_reaction_ms": [],
    }


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


def _get_profile(scores: dict, name: str) -> dict:
    profile = scores.get(name)
    if profile is None:
        profile = default_profile()
    else:
        # Fehlende Felder (Bestandsspieler / altes Schema) auffüllen
        merged = default_profile()
        merged.update(profile)
        profile = merged
    _reset_daily_if_needed(profile)
    scores[name] = profile
    return profile


def _reset_daily_if_needed(profile: dict) -> None:
    today = date.today().isoformat()
    if profile["daily"].get("date") != today:
        profile["daily"] = {"date": today, "wins": 0, "losses": 0, "claimed": False}


DAILY_TARGET_WINS = 5
DAILY_MAX_LOSSES = 2
DAILY_REWARD_COINS = 500


def _check_daily(profile: dict) -> dict:
    d = profile["daily"]
    completed = d["wins"] >= DAILY_TARGET_WINS and d["losses"] <= DAILY_MAX_LOSSES
    reward_granted = False
    if completed and not d["claimed"]:
        profile["coins"] = profile.get("coins", 0) + DAILY_REWARD_COINS
        d["claimed"] = True
        reward_granted = True
    return {
        "wins": d["wins"],
        "losses": d["losses"],
        "target_wins": DAILY_TARGET_WINS,
        "max_losses": DAILY_MAX_LOSSES,
        "completed": completed,
        "reward_granted": reward_granted,
        "reward_coins": DAILY_REWARD_COINS,
    }


def _new_achievements(profile: dict) -> list:
    unlocked = []
    have = set(profile.get("achievements", []))
    for key, meta in ACHIEVEMENTS.items():
        if key not in have and meta["check"](profile):
            have.add(key)
            unlocked.append({"key": key, "label": meta["label"]})
    profile["achievements"] = sorted(have)
    return unlocked


def _adaptive_suggestion(profile: dict) -> dict:
    """
    Simple adaptive-difficulty Heuristik:
    - hohe Trefferquote + schnelle Reaktion -> Spiel wird schwerer (mehr Mischungen, höheres Tempo)
    - niedrige Trefferquote -> Spiel wird etwas leichter
    Rein additiv zur manuell gewählten Schwierigkeit im Frontend.
    """
    results = profile.get("recent_results", [])[-10:]
    reactions = profile.get("recent_reaction_ms", [])[-10:]

    if not results:
        return {"shuffle_delta": 0, "speed_factor": 1.0, "tip": None}

    win_rate = sum(results) / len(results)
    avg_reaction = sum(reactions) / len(reactions) if reactions else 2000

    shuffle_delta = 0
    speed_factor = 1.0
    tip = None

    if win_rate >= 0.7 and len(results) >= 5:
        shuffle_delta = 2
        speed_factor = 1.15
        tip = "Starke Trefferquote! Ich misch's schneller."
    elif win_rate <= 0.3 and len(results) >= 5:
        shuffle_delta = -1
        speed_factor = 0.9
        tip = "Du siehst den Ball noch nicht sicher – etwas ruhiger."

    if reactions and avg_reaction < 600:
        tip = "Du klickst oft sehr früh. Warte einen Moment länger, bevor du zugreifst."
    elif reactions and avg_reaction > 3500:
        tip = "Vertrau deinem ersten Eindruck – du zögerst zu lange."

    return {"shuffle_delta": shuffle_delta, "speed_factor": round(speed_factor, 2), "tip": tip}


def _public_profile(name: str, profile: dict) -> dict:
    return {
        "name": name,
        "balance": profile["balance"],
        "highscore": profile["highscore"],
        "xp": profile["xp"],
        "level": profile["level"],
        "xp_to_next": xp_for_level(profile["level"]),
        "coins": profile["coins"],
        "wins": profile["wins"],
        "losses": profile["losses"],
        "total_games": profile["total_games"],
        "streak": profile["streak"],
        "best_streak": profile["best_streak"],
        "achievements": profile["achievements"],
        "daily": _check_daily(profile),
    }


# ── Routen ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def shellgame_page(request: Request):
    """Liefert die Shellgame HTML-Seite."""
    return HTMLResponse(HTML_TEMPLATE)


@app.post("/api/save_score")
async def save_score(request: Request):
    """Legacy-Endpoint (Abwärtskompatibilität). Neue Clients nutzen /api/result."""
    try:
        body = await request.json()
        user_name = body.get("name", "").strip()
        balance = body.get("balance", 0)
        highscore = body.get("highscore", 0)

        if not user_name:
            return JSONResponse({"success": False, "error": "name required"})

        scores = _load_scores()
        profile = _get_profile(scores, user_name)
        profile["balance"] = balance
        profile["highscore"] = max(highscore, profile.get("highscore", 0))
        _save_scores(scores)

        return JSONResponse({"success": True, "highscore": profile["highscore"]})

    except Exception as e:
        logger.exception("Save-Score Fehler")
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/api/result")
async def submit_result(request: Request):
    """
    Vollständiges Rundenergebnis: aktualisiert Balance, XP/Level, Streak,
    Achievements, Daily Challenge und liefert eine adaptive Schwierigkeits-
    empfehlung + Coach-Tipp für die nächste Runde zurück.

    Erwarteter Body:
    {
      "name": str, "won": bool, "bet": int, "win_amount": int,
      "balance": int, "difficulty": str, "reaction_ms": int
    }
    """
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"success": False, "error": "name required"})

        won = bool(body.get("won"))
        bet = int(body.get("bet", 0))
        win_amount = int(body.get("win_amount", 0))
        balance = int(body.get("balance", 0))
        reaction_ms = body.get("reaction_ms")

        scores = _load_scores()
        profile = _get_profile(scores, name)

        profile["balance"] = balance
        profile["highscore"] = max(profile.get("highscore", 0), balance)
        profile["total_games"] = profile.get("total_games", 0) + 1

        if won:
            profile["wins"] += 1
            profile["streak"] = profile.get("streak", 0) + 1
            profile["best_streak"] = max(profile.get("best_streak", 0), profile["streak"])
            profile["biggest_win"] = max(profile.get("biggest_win", 0), win_amount)
            if isinstance(reaction_ms, (int, float)):
                if profile.get("fastest_win_ms") is None or reaction_ms < profile["fastest_win_ms"]:
                    profile["fastest_win_ms"] = reaction_ms
            apply_xp(profile, 20 + bet // 10)
            profile["daily"]["wins"] += 1
        else:
            profile["losses"] += 1
            profile["streak"] = 0
            apply_xp(profile, 5)
            profile["daily"]["losses"] += 1

        if isinstance(reaction_ms, (int, float)):
            profile.setdefault("recent_reaction_ms", []).append(reaction_ms)
            profile["recent_reaction_ms"] = profile["recent_reaction_ms"][-10:]
        profile.setdefault("recent_results", []).append(1 if won else 0)
        profile["recent_results"] = profile["recent_results"][-10:]

        unlocked = _new_achievements(profile)
        daily_status = _check_daily(profile)
        ai_suggestion = _adaptive_suggestion(profile)

        _save_scores(scores)

        return JSONResponse({
            "success": True,
            "profile": _public_profile(name, profile),
            "unlocked_achievements": unlocked,
            "daily": daily_status,
            "ai_suggestion": ai_suggestion,
        })

    except Exception as e:
        logger.exception("Result-Speicherung fehlgeschlagen")
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/profile")
async def get_profile(name: str):
    """Liefert das vollständige Profil eines Spielers (für Reload/Sync)."""
    try:
        scores = _load_scores()
        profile = _get_profile(scores, name.strip())
        _save_scores(scores)  # persistiert ggf. Daily-Reset
        return JSONResponse({"success": True, "profile": _public_profile(name.strip(), profile)})
    except Exception as e:
        logger.exception("Profil-Abruf fehlgeschlagen")
        return JSONResponse({"success": False, "error": str(e)})


@app.get("/api/leaderboard")
async def get_leaderboard():
    """Liefert das Top 10 Leaderboard."""
    try:
        scores = _load_scores()
        sorted_scores = sorted(
            scores.items(),
            key=lambda x: x[1].get("highscore", 0),
            reverse=True,
        )[:10]

        leaderboard = [
            {
                "name": name,
                "highscore": stats.get("highscore", 0),
                "balance": stats.get("balance", 0),
                "level": stats.get("level", 1),
                "wins": stats.get("wins", 0),
            }
            for name, stats in sorted_scores
        ]

        return JSONResponse({"success": True, "leaderboard": leaderboard})

    except Exception as e:
        logger.exception("Leaderboard Fehler")
        return JSONResponse({"success": False, "error": str(e)})
