# 3d_svg_handler.py – SVG → animiertes 3D
from telegram import Update
from telegram.ext import ContextTypes

async def cmd_svg3d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "🧊 **SVG → 3D + Animation**\n\n"
        "Schick mir eine SVG-Datei oder nutze:\n"
        "/svg3d <Beschreibung>\n\n"
        "→ Wird automatisch in GLB mit Animation umgewandelt (3dsvg)."
    )

