# sandbox_handler.py – Telegram Handler für Code Sandbox
import asyncio
import base64
import json
import logging
import os
import time
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

from bot_state import (
    application, last_generated_code, 
)
from bot_ai import generate_response, _persist_chat_turn
from bot_utils import fit_telegram_text, create_background_task
from guard import can_process_text
from sandbox_runner import (
    generate_html_app,
    get_example_templates,
    run_sandboxed_code,
)

logger = logging.getLogger(__name__)

# ── Konstanten ─────────────────────────────────────────────────────────────────
SANDBOX_BASE_URL = os.getenv(
    "SANDBOX_BASE_URL",
    os.getenv("PUBLIC_APP_BASE_URL", "https://telllmeeesevn.onrender.com"),
).rstrip("/")

SANDBOX_WEBAPP_URL = f"{SANDBOX_BASE_URL}/sandbox"


# ── /sandbox – Öffnet die Code Sandbox Mini App ──────────────────────────────
async def cmd_sandbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /sandbox – Öffnet den Queen's Code Editor im Browser/Mini App

    Nutzung:
    /sandbox              → Öffnet leeren Editor
    /sandbox <code>       → Öffnet Editor mit vorgegebenem Code
    """
    chat_id = str(update.effective_chat.id)

    # Prüfe Rate Limit
    decision = can_process_text(chat_id, "sandbox", action="sandbox")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

    # Optionaler Code aus Args
    preset_code = " ".join(context.args or []).strip()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "👑 Queen's Code Sandbox öffnen",
            web_app=WebAppInfo(url=SANDBOX_WEBAPP_URL)
        )],
        [
            InlineKeyboardButton("📊 Plot-Beispiel", callback_data="sandbox:template:plot"),
            InlineKeyboardButton("📋 DataFrame", callback_data="sandbox:template:dataframe"),
        ],
        [
            InlineKeyboardButton("🎨 Mini-App", callback_data="sandbox:template:mini_app"),
            InlineKeyboardButton("📈 Chart", callback_data="sandbox:template:chart"),
        ],
    ])

    text = (
        "👑 **Queen's Code Sandbox**

"
        "Der ultimative Code-Editor direkt im Browser:
"
        "• 🐍 **Python** mit numpy, pandas, matplotlib
"
        "• 🌐 **HTML** Mini-Apps für Telegram
"
        "• 📊 Live-Plots & Datei-Export
"
        "• 💾 Direkt ins Brain speichern
"
        "• 📤 Ergebnisse teilen

"
        "**Tastenkürzel:**
"
        "• `Ctrl+Enter` = Ausführen
"
        "• `Ctrl+S` = Speichern

"
    )

    if preset_code:
        text += f"💡 *Preset-Code geladen ({len(preset_code)} Zeichen)*"
        # Speichere preset_code temporär für die Mini App
        # (In Produktion: Redis/Session-Store)

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


# ── /runcode – Führt Code direkt im Chat aus ─────────────────────────────────
async def cmd_runcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /runcode <python-code> – Führt Python-Code direkt aus

    Beispiele:
    /runcode print(2+2)
    /runcode import numpy as np; print(np.random.randint(1,100,5))
    """
    chat_id = str(update.effective_chat.id)
    code = " ".join(context.args or []).strip()

    if not code:
        await update.message.reply_text(
            "👑 **/runcode**

"
            "Führt Python-Code direkt aus.

"
            "**Beispiele:**
"
            "`/runcode print(2+2)`
"
            "`/runcode import numpy as np; print(np.random.rand(3,3))`
"
            "`/runcode x = [i**2 for i in range(10)]; print(x)`

"
            "Für komplexeren Code: `/sandbox`",
            parse_mode="Markdown",
        )
        return

    # Rate Limit
    decision = can_process_text(chat_id, code, action="sandbox")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

    loading = await update.message.reply_text("🧪 Führe Code aus...")

    try:
        result = await run_sandboxed_code(code, chat_id=chat_id, timeout=15)

        # Ergebnis formatieren
        lines = []

        if result["success"]:
            lines.append(f"✅ **Erfolg** ({result['execution_time']}s)")

            if result["output"]:
                lines.append(f"```
{fit_telegram_text(result['output'], 3500)}
```")

            if result["result"] and str(result["result"]) != "✅ Code erfolgreich ausgeführt.":
                lines.append(f"📤 **Result:** `{str(result['result'])[:500]}`")
        else:
            lines.append("❌ **Fehler**")
            if result["error"]:
                error_text = fit_telegram_text(result["error"], 3000)
                lines.append(f"```
{error_text}
```")

        reply_text = "\n\n".join(lines)

        # Plot senden
        if result.get("plot"):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=result["plot"],
                caption="📊 Generierter Plot",
            )

        # Datei senden
        if result.get("file"):
            buf, fname = result["file"]
            await context.bot.send_document(
                chat_id=chat_id,
                document=buf,
                filename=fname,
                caption=f"📁 {fname}",
            )

        # Text senden
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=reply_text,
            parse_mode="Markdown",
        )

        # In Chat-History speichern
        _persist_chat_turn(chat_id, f"/runcode {code[:100]}", f"Sandbox: {result['success']}")

        # Code im Cache speichern
        last_generated_code[chat_id] = {
            "language": "python",
            "code": code,
            "timestamp": time.time(),
        }

    except Exception as exc:
        logger.exception("runcode Fehler")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Sandbox-Fehler:
```
{str(exc)[:500]}
```",
            parse_mode="Markdown",
        )


# ── /codefile – Führt eine Python-Datei aus ──────────────────────────────────
async def cmd_codefile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /codefile – Führt eine hochgeladene Python-Datei aus (reply auf .py Datei)
    """
    chat_id = str(update.effective_chat.id)

    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text(
            "❌ Nutzung: Antworte auf eine `.py` Datei mit `/codefile`"
        )
        return

    doc = reply.document
    if not doc.file_name or not doc.file_name.endswith(".py"):
        await update.message.reply_text("❌ Nur `.py` Dateien werden unterstützt.")
        return

    loading = await update.message.reply_text(f"📂 Lade `{doc.file_name}`...")

    try:
        file = await context.bot.get_file(doc.file_id)
        code_bytes = bytes(await file.download_as_bytearray())
        code = code_bytes.decode("utf-8", errors="ignore")

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"🧪 Führe `{doc.file_name}` aus...",
        )

        result = await run_sandboxed_code(code, chat_id=chat_id)

        lines = [f"📂 **{doc.file_name}** ({result['execution_time']}s)"]

        if result["success"]:
            lines.append("✅ Erfolg")
            if result["output"]:
                lines.append(f"```
{fit_telegram_text(result['output'], 3000)}
```")
        else:
            lines.append("❌ Fehler")
            if result["error"]:
                lines.append(f"```
{fit_telegram_text(result['error'], 2500)}
```")

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text="\n\n".join(lines),
            parse_mode="Markdown",
        )

        # Plot/Datei senden
        if result.get("plot"):
            await context.bot.send_photo(chat_id=chat_id, photo=result["plot"], caption="📊 Plot")
        if result.get("file"):
            buf, fname = result["file"]
            await context.bot.send_document(chat_id=chat_id, document=buf, filename=fname)

    except Exception as exc:
        logger.exception("codefile Fehler")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler: {str(exc)[:200]}",
        )


# ── /py – Kurzform für /runcode ─────────────────────────────────────────────
async def cmd_py(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/py ist ein Alias für /runcode"""
    await cmd_runcode(update, context)


# ── /htmlapp – Generiert eine HTML Mini-App ─────────────────────────────────
async def cmd_htmlapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /htmlapp <html-code> – Generiert eine HTML Mini-App

    Beispiel:
    /htmlapp <h1>Hallo Welt</h1><button>Klick mich</button>
    """
    chat_id = str(update.effective_chat.id)
    html_code = " ".join(context.args or []).strip()

    if not html_code:
        await update.message.reply_text(
            "🌐 **/htmlapp**

"
            "Generiert eine HTML Mini-App.

"
            "**Beispiel:**
"
            "`/htmlapp <h1 style=\"color:#a78bfa\">Hallo</h1>`

"
            "Für komplexere Apps: `/sandbox` und Sprache auf HTML stellen.",
            parse_mode="Markdown",
        )
        return

    loading = await update.message.reply_text("🌐 Generiere Mini-App...")

    try:
        buffer, filename = generate_html_app(html_code, "Mini App")

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text="✅ Mini-App generiert!",
        )

        await context.bot.send_document(
            chat_id=chat_id,
            document=buffer,
            filename=filename,
            caption="🌐 HTML Mini-App",
        )

    except Exception as exc:
        logger.exception("htmlapp Fehler")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler: {str(exc)[:200]}",
        )


# ── Callback Handler ──────────────────────────────────────────────────────────
async def sandbox_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback für Sandbox-Buttons (Templates laden)."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    chat_id = str(query.message.chat.id)

    if query.data.startswith("sandbox:template:"):
        template_key = query.data.split(":")[2]
        templates = get_example_templates()

        if template_key not in templates:
            await query.edit_message_text("❌ Template nicht gefunden.")
            return

        code = templates[template_key]

        # Sende Code als Nachricht + Button zur Sandbox
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "👑 In Sandbox öffnen",
                web_app=WebAppInfo(url=SANDBOX_WEBAPP_URL)
            )],
        ])

        await query.edit_message_text(
            f"📋 **Template: {template_key}**

"
            f"```python
{fit_telegram_text(code, 3500)}
```

"
            f"Tippe den Button, um in der Sandbox zu bearbeiten.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

        # Speichere Code für später
        last_generated_code[chat_id] = {
            "language": "python",
            "code": code,
            "timestamp": time.time(),
        }


# ── Message Handler für Code-Sharing aus der Mini App ─────────────────────────
async def handle_sandbox_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Verarbeitet geteilten Code aus der Sandbox Mini App.
    Wird über WebAppData aufgerufen.
    """
    # Dies wird über die WebAppData-Integration in main.py gehandhabt
    pass
