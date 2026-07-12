# sticker_handler.py – Animierte Sticker für WhatsApp + Telegram
from sticker_convert import StickerConvert
from telegram import Update
from telegram.ext import ContextTypes
from bot_utils import create_background_task
from brain import save_file

async def cmd_stickerpack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    platform = "telegram" if "telegram" in " ".join(context.args or []).lower() else "whatsapp"

    loading = await update.message.reply_text(f"🎨 Erstelle animiertes Sticker-Pack für {platform.upper()}...")

    try:
        converter = StickerConvert()
        # Hier kannst du später Ordner oder mehrere Dateien übergeben
        result = await converter.create_pack(
            input_path=None,
            platform=platform,
            fps=15,
            quality=85
        )

        if result.success:
            await context.bot.send_document(
                chat_id=chat_id,
                document=result.file,
                filename=result.filename,
                caption=f"✅ Sticker-Pack für {platform.upper()} fertig!"
            )
            await save_file(chat_id, result.file.getvalue(), result.filename, "application/zip")
        else:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id,
                                               text="❌ Sticker-Pack konnte nicht erstellt werden.")
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id,
                                           text=f"Fehler: {str(e)[:200]}")

