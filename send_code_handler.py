# send_code_handler.py – Finale stabile Version (Lock-Problem behoben)
import asyncio
import logging
import re
import zipfile
import fnmatch
from datetime import datetime
from io import BytesIO
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ── Konfiguration ─────────────────────────────────────────────────────────────

IGNORE = {
    "__pycache__", ".git", "venv", ".env", ".venv", "node_modules",
    "*.pyc", "*.pyo", "*.log", "*.tmp", "*.bak",
    "*.mp3", "*.mp4", "*.wav", "*.ogg", "*.jpg", "*.png", "*.gif", "*.glb",
}

EXTENSIONS = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".html", ".css", ".js", ".toml", ".sh"}
MAX_TOTAL_CHARS = 8_000_000

# Statt Lock pro Chat → einfaches Set (viel stabiler)
_running_sendcode: set[str] = set()


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _should_ignore(path: Path) -> bool:
    path_str = str(path)
    filename = path.name
    for pattern in IGNORE:
        if "*" in pattern:
            if fnmatch.fnmatch(filename, pattern):
                return True
        else:
            if pattern in path_str or pattern in path.parts:
                return True
    return False


def _collect_files(root: Path = Path(".")) -> list[Path]:
    files = []
    for ext in EXTENSIONS:
        for f in root.rglob(f"*{ext}"):
            if _should_ignore(f):
                continue
            try:
                if 0 < f.stat().st_size < 5_000_000:   # max 5MB pro Datei
                    files.append(f)
            except OSError:
                continue
    files.sort()
    return files


def _build_markdown(files: list[Path], root: Path = Path(".")) -> tuple[str, int, int]:
    ok, errors = 0, 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# === FULL BOT CODE DUMP ===",
        f"# Generiert: {now}",
        f"# Dateien: {len(files)}",
        "# ============================================\n",
    ]

    for f in files:
        try:
            rel = f.relative_to(root) if f.is_absolute() else f
            content = f.read_text(encoding="utf-8", errors="ignore")
            block = f"\n\n# === FILE: {rel} ===\n\n{content}\n"
            
            if sum(len(x) for x in lines) + len(block) > MAX_TOTAL_CHARS:
                lines.append("\n\n# === TRUNCATED (zu groß) ===\n")
                break
                
            lines.append(block)
            ok += 1
        except Exception as e:
            logger.warning("Konnte %s nicht lesen: %s", f, e)
            errors += 1

    lines.append(f"\n\n# === END OF CODE DUMP ===\n# Erfolgreich: {ok} | Fehler: {errors}\n")
    return "\n".join(lines), ok, errors


def parse_code_dump(md_content: str) -> dict[str, str]:
    """Extrahiert Dateien aus dem Markdown-Dump."""
    files = {}
    pattern = r"# === FILE: (.+?) ===\n\n(.*?)(?=# === FILE:|$)"
    matches = re.finditer(pattern, md_content, re.DOTALL)
    for match in matches:
        filepath = match.group(1).strip()
        content = match.group(2).strip()
        files[filepath] = content
    return files


def create_pdf_from_markdown(md_text: str, title: str = "Bot Code") -> BytesIO:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
    except ImportError:
        buffer = BytesIO(md_text.encode("utf-8"))
        buffer.name = f"{title.replace(' ', '_')}.txt"
        return buffer

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=18, spaceAfter=20, textColor=colors.darkblue)
    code_style = ParagraphStyle('Code', parent=styles['Normal'], fontName='Courier', fontSize=9, spaceAfter=12, leading=11)

    story = [Paragraph(f"<b>{title}</b>", title_style), Spacer(1, 12)]

    parts = md_text.split("# === FILE: ")
    for i, part in enumerate(parts):
        if i == 0: continue
        try:
            filename, content = part.split("===", 1)
            story.append(Paragraph(f"<b>FILE: {filename.strip()}</b>", styles['Heading2']))
            story.append(Spacer(1, 6))
            story.append(Paragraph(content.strip()[:8000], code_style))
            story.append(Spacer(1, 12))
        except:
            continue

    doc.build(story)
    buffer.seek(0)
    buffer.name = f"bot_code_full_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return buffer


def create_zip_from_files(files_dict: dict[str, str]) -> BytesIO:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for filepath, content in files_dict.items():
            zipf.writestr(str(filepath), content)
    
    buffer.seek(0)
    buffer.name = f"bot_code_complete_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    return buffer


# ── Command Handler ───────────────────────────────────────────────────────────

async def cmd_send_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if chat_id in _running_sendcode:
        await update.message.reply_text("⏳ **/sendcode läuft bereits** für diesen Chat.\nBitte warte einen Moment...")
        return

    _running_sendcode.add(chat_id)
    status_msg = await update.message.reply_text(
        "🔍 **Code-Dump wird erstellt...**\n"
        "Dies kann 15–45 Sekunden dauern (je nach Anzahl der Dateien)."
    )

    try:
        root = Path(__file__).resolve().parent
        files = _collect_files(root)

        if not files:
            await status_msg.edit_text("❌ Keine passenden Dateien gefunden.")
            return

        md_content, ok, errors = _build_markdown(files, root)
        
        md_buffer = BytesIO(md_content.encode("utf-8"))
        md_buffer.name = f"bot_code_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

        await status_msg.delete()

        sent_msg = await update.message.reply_document(
            document=md_buffer,
            filename=md_buffer.name,
            caption=f"📄 **Full Bot Code Dump**\n{ok} Dateien | ~{len(md_content)//1024:,} KB",
            parse_mode="Markdown"
        )

        # Weitere Export-Optionen
        keyboard = [
            [
                InlineKeyboardButton("📄 Als PDF", callback_data="sendcode:pdf"),
                InlineKeyboardButton("📦 Als ZIP", callback_data="sendcode:zip"),
            ],
            [
                InlineKeyboardButton("📁 Alle Einzeldateien", callback_data="sendcode:files")
            ]
        ]

        await sent_msg.reply_text(
            "🔽 **Weitere Export-Optionen:**",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        context.bot_data[f"sendcode_md_{chat_id}"] = md_content

    except Exception as e:
        logger.exception("sendcode Fehler")
        try:
            await status_msg.edit_text(f"❌ Fehler beim Code-Dump:\n{str(e)[:300]}")
        except:
            await update.message.reply_text("❌ Fehler beim Erstellen des Code-Dumps.")
    finally:
        _running_sendcode.discard(chat_id)   # WICHTIG!


# ── Callback Handler ──────────────────────────────────────────────────────────

async def sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat_id)
    action = query.data.split(":")[1]

    md_content = context.bot_data.get(f"sendcode_md_{chat_id}")
    if not md_content:
        await query.edit_message_text("❌ Code-Dump nicht mehr verfügbar. Bitte `/sendcode` neu ausführen.")
        return

    if action == "pdf":
        await query.edit_message_text("📄 Generiere PDF...")
        pdf_buffer = create_pdf_from_markdown(md_content)
        await query.message.reply_document(
            document=pdf_buffer,
            filename=pdf_buffer.name,
            caption="✅ Vollständiger Bot-Code als PDF"
        )
        await query.edit_message_text("✅ PDF gesendet!")

    elif action == "zip":
        await query.edit_message_text("📦 Erstelle ZIP-Archiv...")
        extracted = parse_code_dump(md_content)
        zip_buffer = create_zip_from_files(extracted)
        
        await query.message.reply_document(
            document=zip_buffer,
            filename=zip_buffer.name,
            caption=f"✅ {len(extracted)} Dateien als ZIP"
        )
        await query.edit_message_text("✅ ZIP gesendet!")

    elif action == "files":
        await query.edit_message_text("📤 Sende Einzeldateien (kann etwas dauern)...")
        extracted = parse_code_dump(md_content)
        sent_count = 0

        for filepath, content in extracted.items():
            try:
                preview = content[:600].replace("`", "'").replace("*", "•")
                if len(content) > 600:
                    preview += "\n\n... (Datei fortgesetzt)"

                buffer = BytesIO(content.encode("utf-8"))
                buffer.name = Path(filepath).name

                await query.message.reply_document(
                    document=buffer,
                    filename=buffer.name,
                    caption=f"📁 {filepath}\n\n{preview}"[:1020],
                )
                sent_count += 1
                if sent_count % 4 == 0:
                    await asyncio.sleep(0.8)
            except Exception as e:
                logger.warning("Fehler beim Senden %s: %s", filepath, e)

        await query.message.reply_text(f"✅ **{sent_count} Einzeldateien** gesendet!")
        await query.edit_message_text("✅ Einzeldateien-Export abgeschlossen.")


# In main.py registrieren (falls noch nicht geschehen):
# from send_code_handler import cmd_send_code, sendcode_callback
# application.add_handler(CommandHandler("sendcode", cmd_send_code))
# application.add_handler(CallbackQueryHandler(sendcode_callback, pattern="^sendcode:"))