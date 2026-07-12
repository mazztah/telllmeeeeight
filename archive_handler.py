# archive_handler.py – Telegram Commands für Archive.org Integration (Render-Ready)
import logging
import os
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

from archive_org_module import get_archive_client, build_archive_agent_tools
from bot_utils import fit_telegram_text, create_background_task

logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
# Render-kompatible URL – nutzt die gleiche Domain wie der Bot
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

if RENDER_EXTERNAL_URL:
    BASE_URL = RENDER_EXTERNAL_URL.rstrip("/")
elif WEBHOOK_URL:
    BASE_URL = WEBHOOK_URL.rstrip("/")
else:
    BASE_URL = "https://telllmeeesevn.onrender.com"

ARCHIVE_MINI_APP_URL = f"{BASE_URL}/archive"


# ── Commands ─────────────────────────────────────────────────────────────────
async def cmd_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Öffnet die Archive.org Workspace Mini App."""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📚 Archive.org Workspace öffnen",
            web_app=WebAppInfo(url=ARCHIVE_MINI_APP_URL)
        )
    ], [
        InlineKeyboardButton(
            "🔍 Schnellsuche",
            switch_inline_query_current_chat="/archivesearch "
        )
    ]])

    await update.message.reply_text(
        "📚 **Internet Archive Workspace**\n\n"
        "Öffne den Workspace für:\n"
        "• 🔍 Suche nach Millionen von Büchern & Medien\n"
        "• ⬇️ Direkte Downloads im Chat\n"
        "• ⬆️ Upload eigener Dateien\n"
        "• 📋 Metadaten & Datei-Explorer\n"
        "• 🤖 LLM-Agent für komplexe Anfragen\n\n"
        "Deine S3-Keys sind konfiguriert und bereit!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def cmd_archivesearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direkte Suche via Telegram Command mit Download-Buttons."""
    chat_id = str(update.effective_chat.id)
    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text(
            "🔍 **Archive.org Suche**\n\n"
            "Nutzung: `/archivesearch <Begriff>`\n\n"
            "Beispiele:\n"
            "• `/archivesearch python programming`\n"
            "• `/archivesearch old radio 1950s`\n"
            "• `/archivesearch nasa apollo images`\n"
            "• `/archivesearch epub science fiction`",
            parse_mode="Markdown"
        )
        return

    loading = await update.message.reply_text(f"🔍 Suche nach '{query}'...")
    client = get_archive_client()

    try:
        result = await client.search(query, rows=10)

        if not result["success"]:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Fehler: {result.get('error')}"
            )
            return

        if not result["items"]:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text="Keine Ergebnisse gefunden."
            )
            return

        lines = [f"🔍 **{result['total']} Ergebnisse** für '{query}':\n"]
        keyboard_rows = []

        for i, item in enumerate(result["items"][:5]):
            lines.append(
                f"\n📚 *{item['title'][:60]}*\n"
                f"   ID: `{item['identifier']}`\n"
                f"   👤 {item['creator']} | 📅 {item['date']}\n"
                f"   ⬇️ {item['downloads']} Downloads | Typ: {item['mediatype']}"
            )

            keyboard_rows.append([
                InlineKeyboardButton(
                    f"⬇️ {item['title'][:30]}...",
                    url=f"https://archive.org/download/{item['identifier']}"
                )
            ])

        keyboard_rows.append([
            InlineKeyboardButton(
                "📚 Im Workspace öffnen",
                web_app=WebAppInfo(url=ARCHIVE_MINI_APP_URL)
            )
        ])

        text = "\n".join(lines)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=fit_telegram_text(text),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Archive Search Fehler: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler: {str(e)[:200]}"
        )

async def cmd_archivedetails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zeigt Details für ein Archive.org Item mit Download-Buttons."""
    chat_id = str(update.effective_chat.id)
    identifier = " ".join(context.args).strip()

    if not identifier:
        await update.message.reply_text(
            "📋 **Item-Details**\n\n"
            "Nutzung: `/archivedetails <Item-ID>`\n\n"
            "Beispiel: `/archivedetails python_cookbook_2013`\n"
            "Die Item-ID findest du in der URL: archive.org/details/[ID]",
            parse_mode="Markdown"
        )
        return

    loading = await update.message.reply_text(f"📋 Lade Details für {identifier}...")
    client = get_archive_client()

    try:
        result = await client.get_metadata(identifier)

        if not result["success"]:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Fehler: {result.get('error')}"
            )
            return

        keyboard_rows = []
        files_text = []

        for f in result["files"][:8]:
            size_mb = int(f['size']) / (1024 * 1024) if f['size'] else 0
            files_text.append(f"  • `{f['name']}` ({f['format']}, {size_mb:.1f} MB)")

            keyboard_rows.append([
                InlineKeyboardButton(
                    f"⬇️ {f['name'][:25]}... ({f['format']})",
                    url=f"https://archive.org/download/{identifier}/{f['name']}"
                )
            ])

        # Komplett ohne problematische f-strings
        title = result.get('title', 'Unbekannt')
        text = f"📋 **{title}**\n\n"
        text += f"ID: `{result.get('identifier', identifier)}`\n"
        text += f"👤 Ersteller: {result.get('creator', 'Unbekannt')}\n"
        text += f"📅 Datum: {result.get('date', 'Unbekannt')}\n"
        text += f"📊 Typ: {result.get('mediatype', 'Unbekannt')}\n"
        text += f"⬇️ Downloads: {result.get('downloads', 0)}\n"
        text += f"📁 Dateien: {result.get('files_count', 0)}\n\n"
        text += "**Verfügbare Dateien:**\n"
        text += "\n".join(files_text) + "\n\n"
        text += f"[🔗 Auf Archive.org öffnen](https://archive.org/details/{identifier})"

        keyboard_rows.append([
            InlineKeyboardButton(
                "📚 Im Workspace öffnen",
                web_app=WebAppInfo(url=ARCHIVE_MINI_APP_URL)
            )
        ])

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=fit_telegram_text(text),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Archive Details Fehler: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler: {str(e)[:200]}"
        )

async def cmd_archivedownload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lädt eine spezifische Datei herunter und sendet sie direkt im Chat."""
    chat_id = str(update.effective_chat.id)

    if len(context.args) < 2:
        await update.message.reply_text(
            "⬇️ **Direkter Download**\n\n"
            "Nutzung: `/archivedownload <Item-ID> <Dateiname>`\n\n"
            "Beispiel:\n"
            "`/archivedownload python_cookbook_2013 python_cookbook.pdf`\n\n"
            "Tipp: Nutze `/archivedetails <ID>` um verfügbare Dateien zu sehen.",
            parse_mode="Markdown"
        )
        return

    identifier = context.args[0]
    filename = " ".join(context.args[1:])

    loading = await update.message.reply_text(
        f"⬇️ Lade `{filename}` aus `{identifier}`..."
    )

    client = get_archive_client()

    try:
        file_bytes = await client.download_file(identifier, filename)

        if not file_bytes:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Datei nicht gefunden oder Download fehlgeschlagen.\n\n"
                     f"Prüfe mit `/archivedetails {identifier}` die verfügbaren Dateien."
            )
            return

        # Lösche Lade-Nachricht
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)

        # Sende Datei
        buffer = BytesIO(file_bytes)
        buffer.name = filename

        # Bestimme Sende-Methode basierend auf Dateityp
        lower_name = filename.lower()
        if any(lower_name.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=buffer,
                caption=f"📷 `{filename}` aus `{identifier}`"
            )
        elif any(lower_name.endswith(ext) for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']):
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=buffer,
                filename=filename,
                caption=f"🎵 `{filename}` aus `{identifier}`"
            )
        elif any(lower_name.endswith(ext) for ext in ['.mp4', '.avi', '.mkv', '.mov']):
            await context.bot.send_video(
                chat_id=chat_id,
                video=buffer,
                filename=filename,
                caption=f"🎬 `{filename}` aus `{identifier}`",
                supports_streaming=True
            )
        else:
            await context.bot.send_document(
                chat_id=chat_id,
                document=buffer,
                filename=filename,
                caption=f"📄 `{filename}` aus `{identifier}` ({len(file_bytes)} Bytes)"
            )

    except Exception as e:
        logger.error(f"Archive Download Fehler: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Download fehlgeschlagen: {str(e)[:200]}"
        )


# ── Agent Integration ────────────────────────────────────────────────────────
def register_archive_tools():
    """Registriert Archive.org Tools für den LLM-Agenten."""
    return build_archive_agent_tools()
