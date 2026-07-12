"""
Space War - Telegram Bot Handler v2.2
Uses /spacewar/ path explicitly
"""
import logging, json, os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

def _get_base_url():
    import os
    webhook_url = os.getenv("WEBHOOK_URL", "").rstrip("/")
    if webhook_url: return webhook_url
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url: return render_url
    hf_space = os.getenv("SPACE_ID", "")
    if hf_space: return f"https://{hf_space}.hf.space"
    port = os.getenv("PORT", "7860")
    return f"http://localhost:{port}"

async def cmd_spacewar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Space War Mini App"""
    chat_id = update.effective_chat.id
    user = update.effective_user
    base_url = _get_base_url()

    # IMPORTANT: Use /spacewar/ path!
    mini_app_url = f"{base_url}/spacewar/"

    welcome_text = (
        "🚀 *SPACE WAR* - Galactic Shooter!\n\n"
        "360° Weltraum-Action mit:\n"
        "• 10+ feindliche Schiffe\n"
        "• Boss alle 3 Level\n"
        "• Power-ups & Drohnen\n"
        "• Coin Shop\n\n"
        "🎮 *Steuerung (Android):*\n"
        "• Linker Joystick = Bewegen\n"
        "• Rechter Button = Schiessen\n"
        "• Automatisch optimiert für Mobile!\n\n"
        "Starte jetzt! 🔥"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 SPIELEN", web_app={"url": mini_app_url})],
        [InlineKeyboardButton("🏆 Bestenliste", callback_data="spacewar:leaderboard")],
    ]

    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    logger.info(f"Space War gestartet für User {user.id} | URL: {mini_app_url}")

async def spacewar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "spacewar:leaderboard":
        await _show_leaderboard(update, context)
    elif data.startswith("spacewar:page:"):
        page = int(data.split(":")[-1])
        await _show_leaderboard(update, context, page=page)

async def _show_leaderboard(update, context, page=0, per_page=10):
    query = update.callback_query
    chat_id = update.effective_chat.id
    scores = await _load_scores(chat_id)
    base_url = _get_base_url()
    mini_app_url = f"{base_url}/spacewar/"

    if not scores:
        text = "🏆 *Space War Bestenliste*\n\nNoch keine Einträge!\nSpiele mit /spacewar! 🚀"
        keyboard = [[InlineKeyboardButton("🚀 Spielen", web_app={"url": mini_app_url})]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    total_pages = (len(scores) + per_page - 1) // per_page
    start = page * per_page
    page_scores = scores[start:start + per_page]

    text = f"🏆 *Space War Bestenliste* (Seite {page + 1}/{total_pages})\n\n"
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
        text += f"{medal} *{entry.get('username', 'Unbekannt')}*\n    📊 {entry['score']:,} | Lv.{entry.get('level', 1)} | 🪙{entry.get('coins', 0)} | {date_str}\n\n"

    keyboard = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"spacewar:page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"spacewar:page:{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🚀 Spielen", web_app={"url": mini_app_url})])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def _load_scores(chat_id):
    try:
        from brain import load_all_entries
        entries = await load_all_entries(str(chat_id))
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
        logger.error(f"Load error: {e}")
        return _load_scores_file()

def _load_scores_file():
    import os
    from pathlib import Path
    DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
    scores_file = DATA_DIR / "spacewar_scores.json"
    if not scores_file.exists():
        return []
    try:
        with open(scores_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

async def save_spacewar_score(chat_id, username, score, level, coins=0, user_id=None):
    try:
        score_data = {
            "username": username,
            "score": score,
            "level": level,
            "coins": coins,
            "date": datetime.now().isoformat(),
            "user_id": user_id,
            "game": "space_war"
        }
        try:
            from brain import save_file
            entry_id = f"spacewar_score_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{username}_{score}"
            await save_file(
                chat_id=str(chat_id),
                entry_id=entry_id,
                title=f"spacewar_score_{username}_{score}",
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
    scores_file = DATA_DIR / "spacewar_scores.json"
    scores = _load_scores_file()
    scores.append(score_data)
    scores.sort(key=lambda x: x.get("score", 0), reverse=True)
    scores = scores[:100]
    with open(scores_file, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)
