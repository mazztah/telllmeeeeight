# chess_handler.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
import logging
import os

logger = logging.getLogger(__name__)

# Dynamische URL (funktioniert lokal + Render/Railway)
BASE_URL = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://telllmeeesevn.onrender.com"
CHESS_APP_URL = f"{BASE_URL.rstrip('/')}/chess"

async def cmd_chess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    
    keyboard = [
        [InlineKeyboardButton("♟️ Crystal Chess öffnen", web_app=WebAppInfo(url=CHESS_APP_URL))],
        [InlineKeyboardButton("🎮 Schnellstart vs Llama", callback_data="chess:quickstart")],
        [InlineKeyboardButton("📜 Regeln & Controls", callback_data="chess:help")]
    ]
    
    await update.message.reply_text(
        "👑 **Queen’s Crystal Chess**\n\n"
        "✨ Glossy 3D Glas-Schachbrett\n"
        "🌊 Watercolor hellblau + transparente Felder\n"
        "🧿 Haute Couture Designer-Figuren (lebendig animiert)\n"
        "🦙 Llama-4 als intelligenter Gegner\n"
        "🎥 Bouncing Move-Text + 360° Orbit Controls\n\n"
        "Tippe auf den Button und spiele!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def chess_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "chess:quickstart":
        await query.message.reply_text("♟️ Starte Mini-App und wähle 'New Game vs Llama'!")
    elif query.data == "chess:help":
        await query.message.reply_text(
            "🎮 **Controls**\n"
            "• Maus / Finger: Figuren ziehen\n"
            "• 1 Finger drag: Kamera drehen\n"
            "• 2 Finger: Zoom + Pan\n"
            "• Rechtsklick / Long-Press: Figur auswählen\n\n"
            "Llama denkt ein paar Sekunden – sei geduldig, sie ist kreativ 💎"
        )
