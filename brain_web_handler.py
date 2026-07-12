# brain_web_handler.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
import logging
import asyncio

logger = logging.getLogger(__name__)

# Import aus vectorbrain
try:
    from vectorbrain import index_brain_entries
    VECTORBRAIN_AVAILABLE = True
except ImportError:
    logger.warning("vectorbrain.py konnte nicht importiert werden")
    VECTORBRAIN_AVAILABLE = False


async def cmd_brainweb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Haupt-Command für Brain Web Interface"""
    try:
        keyboard = [
            [
                InlineKeyboardButton(
                    "🌐 Brain Dashboard öffnen",
                    url="https://telllmeeesevn.onrender.com/brain"
                )
            ],
            [
                InlineKeyboardButton("🔄 Brain Indexieren", callback_data="brainweb:index"),
                InlineKeyboardButton("📋 Liste", callback_data="brainweb:list"),
            ]
        ]

        await update.message.reply_text(
            "🧠 **Brain Corporate Dashboard**\n\n"
            "• Web-Interface mit Dateiübersicht + KI-Workspace\n"
            "• Semantische Suche (Vector Search)\n"
            "• Direkter Download von Dateien",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"cmd_brainweb Fehler: {e}")
        await update.message.reply_text(
            "🧠 Brain Web Interface:\n"
            "https://telllmeeesevn.onrender.com/brain"
        )


async def brainweb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback für Indexieren & Co."""
    query = update.callback_query
    chat_id = str(query.message.chat.id)
    await query.answer()

    if query.data == "brainweb:index":
        if not VECTORBRAIN_AVAILABLE:
            await query.edit_message_text("❌ VectorBrain Modul nicht verfügbar.")
            return

        await query.edit_message_text("🔄 **Brain Indexierung gestartet...**\nDies kann 10–30 Sekunden dauern.")

        try:
            result = await index_brain_entries(chat_id, limit=50)
            
            success_msg = (
                f"✅ **Brain Indexierung abgeschlossen**\n\n"
                f"{result.get('message', '')}\n"
                f"Indexed: {result.get('indexed', 0)} | Persisted: {result.get('persisted', 0)}"
            )
            await query.edit_message_text(success_msg)
            
        except Exception as e:
            logger.error(f"Indexierungsfehler: {e}")
            await query.edit_message_text(f"❌ Fehler bei der Indexierung:\n{str(e)[:200]}")

    elif query.data == "brainweb:list":
        await query.edit_message_text("📋 Verwende /listbrain oder /brainlist für die Übersicht.")
    
    else:
        await query.edit_message_text("Brain Web Interface bereit.")