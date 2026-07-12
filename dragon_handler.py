"""
Dragon Jump v2.0 - Telegram Bot Handler
"""

import logging
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _get_base_url() -> str:
    import os
    webhook_url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if webhook_url:
        return webhook_url
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        return render_url
    hf_space = os.getenv("SPACE_ID", "")
    if hf_space:
        return f"https://{hf_space}.hf.space"
    port = os.getenv("PORT", "7860")
    return f"http://localhost:{port}"


async def cmd_dragon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    base_url = _get_base_url()
    mini_app_url = f"{base_url}/dragon"

    welcome_text = (
        "🐉 *Dragon Jump v2.0* - Street Life Edition!\n\n"
        "Hilf dem hellblauen Drachen durch die Stadt!\n"
        "Sammle Coins, kaufe Upgrades, ueberlebe!\n\n"
        "📊 *Features:*\n"
        "• Double Jump (2x in der Luft)\n"
        "• Coin System + Upgrade Shop\n"
        "• Street Life Hindernisse\n"
        "• Level-Up Animationen\n"
        "• Sound Effekte\n\n"
        "🎮 *Steuerung:*\n"
        "• Space / Touch = Springen\n"
        "• Doppel-Tap = Double Jump\n"
        "• Pfeil runter = Schnell fallen\n"
        "• Esc = Pause\n\n"
        "Spiele jetzt! 🔥"
    )

    keyboard = [
        [InlineKeyboardButton("🎮 Spielen", url=mini_app_url)],
        [InlineKeyboardButton("🏆 Bestenliste", callback_data="dragon:leaderboard")],
    ]

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    logger.info(f"Dragon Jump v2 gestartet fuer User {user.id}")


async def dragon_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "dragon:leaderboard":
        await _show_leaderboard(update, context)
    elif data.startswith("dragon:page:"):
        page = int(data.split(":")[-1])
        await _show_leaderboard(update, context, page=page)


async def _show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0, per_page=10):
    query = update.callback_query
    chat_id = update.effective_chat.id

    scores = await _load_scores(chat_id)

    if not scores:
        text = (
            "🏆 *Dragon Jump Bestenliste*\n\n"
            "Noch keine Eintraege!\n"
            "Spiele mit /dragon! 🐉"
        )
        keyboard = [[InlineKeyboardButton("🎮 Spielen", url=_get_base_url() + "/dragon")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    total_pages = (len(scores) + per_page - 1) // per_page
    start = page * per_page
    end = start + per_page
    page_scores = scores[start:end]

    text = f"🏆 *Bestenliste* (Seite {page + 1}/{total_pages})\n\n"

    medals = ["👑", "🥈", "🥉"]
    for i, entry in enumerate(page_scores):
        rank = start + i + 1
        medal = medals[i] if i < 3 and page == 0 else f"{rank}."
        date_str = "Unbekannt"
        if entry.get("date"):
            try:
                date_str = datetime.fromisoformat(entry["date"]).strftime("%d.%m.%Y")
            except:
                pass

        text += (
            f"{medal} *{entry.get('username', 'Unbekannt')}*\n"
            f"    📊 {entry['score']:,} | Lv.{entry.get('level', 1)} | 🪙{entry.get('coins', 0)} | {date_str}\n\n"
        )

    keyboard = []
    nav_row = []

    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"dragon:page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"dragon:page:{page + 1}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🎮 Spielen", url=_get_base_url() + "/dragon")])

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _load_scores(chat_id):
    try:
        from brain import load_all_entries
        entries = await load_all_entries(str(chat_id))
        scores = []

        for entry in entries:
            if "dragon_score" in entry.get("title", ""):
                try:
                    content = entry.get("content", "")
                    if isinstance(content, str):
                        data = json.loads(content)
                    else:
                        data = content

                    if isinstance(data, dict) and "score" in data:
                        scores.append(data)
                except Exception:
                    continue

        scores.sort(key=lambda x: x.get("score", 0), reverse=True)
        return scores

    except Exception as e:
        logger.error(f"Load error: {e}")
        return _load_scores_file()


def _load_scores_file():
    import os
    from pathlib import Path
    DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
    scores_file = DATA_DIR / "dragon_scores.json"

    if not scores_file.exists():
        return []
    try:
        with open(scores_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


async def save_dragon_score(chat_id, username, score, level, coins=0, user_id=None):
    try:
        score_data = {
            "username": username,
            "score": score,
            "level": level,
            "coins": coins,
            "date": datetime.now().isoformat(),
            "user_id": user_id,
            "game": "dragon_jump_v2"
        }

        try:
            from brain import save_file
            entry_id = f"dragon_score_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{username}_{score}"
            await save_file(
                chat_id=str(chat_id),
                entry_id=entry_id,
                title=f"dragon_score_{username}_{score}",
                content=json.dumps(score_data),
                filename=f"{entry_id}.json",
                mime_type="application/json"
            )
            return True
        except ImportError:
            pass

        _save_score_file(score_data)
        return True

    except Exception as e:
        logger.error(f"Save error: {e}")
        return False


def _save_score_file(score_data):
    import os
    from pathlib import Path
    DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    scores_file = DATA_DIR / "dragon_scores.json"

    scores = _load_scores_file()
    scores.append(score_data)
    scores.sort(key=lambda x: x.get("score", 0), reverse=True)
    scores = scores[:100]

    with open(scores_file, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)
