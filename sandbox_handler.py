# sandbox_handler.py – Telegram Handler für Code Sandbox (V8)
# INTEGRATION: Brain, Vectoring, Permissions, HTML-Preview

import asyncio
import base64
import json
import logging
import os
import time
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

from bot_state import application, last_generated_code
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
PUBLIC_APP_BASE_URL = os.getenv(
    "PUBLIC_APP_BASE_URL",
    "https://telllmeeesevn.onrender.com"
).rstrip("/")

SANDBOX_WEBAPP_URL = os.getenv(
    "SANDBOX_WEBAPP_URL", 
    f"{PUBLIC_APP_BASE_URL}/sandbox"
)


# ── HTML-Escape Helfer ────────────────────────────────────────────────────────
def _esc(text: str) -> str:
    """Escape HTML-Sonderzeichen für Telegram HTML-Parse-Mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _pre(text: str, max_chars: int = 3000) -> str:
    """Code-Block für Telegram HTML-Mode."""
    return f"<pre>{_esc(fit_telegram_text(text, max_chars))}</pre>"


def _code(text: str) -> str:
    """Inline-Code für Telegram HTML-Mode."""
    return f"<code>{_esc(text)}</code>"


def _b(text: str) -> str:
    """Fett für Telegram HTML-Mode."""
    return f"<b>{_esc(text)}</b>"


# ── /sandbox – Öffnet die Code Sandbox Mini App ──────────────────────────────
async def cmd_sandbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    decision = can_process_text(chat_id, "sandbox", action="sandbox")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

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
        [
            InlineKeyboardButton("🔍 Parser", callback_data="sandbox:template:hello"),
            InlineKeyboardButton("🌐 HTML-Preview", callback_data="sandbox:template:mini_app"),
        ],
    ])

    text = (
        "👑 <b>Queen's Code Sandbox V8</b>\n\n"
        "Der ultimative Code-Editor direkt im Browser:\n\n"
        "• 🐍 <b>Python</b> mit numpy, pandas, matplotlib\n"
        "• 🌐 <b>HTML</b> Mini-Apps für Telegram\n"
        "• 📊 Live-Plots &amp; Datei-Export\n"
        "• 🌐 HTML-Live-Preview im Browser\n"
        "• 🔍 Python AST-Parser\n"
        "• 💾 Direkt ins Brain speichern (mit Vektor-Embedding)\n"
        "• 📤 Ergebnisse teilen\n"
        "• 🤖 KI-Assistent für Code-Fragen\n"
        "• 🔐 Berechtigungs-Management\n\n"
        "<b>Tastenkürzel:</b>\n"
        "• <code>Ctrl+Enter</code> = Ausführen\n"
        "• <code>Ctrl+S</code> = Speichern\n"
        "• <code>⚖️</code> = Bereiche ausgleichen"
    )

    if preset_code:
        text += f"\n\n💡 <i>Preset-Code geladen ({len(preset_code)} Zeichen)</i>"

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# ── /runcode – Führt Code direkt im Chat aus ─────────────────────────────────
async def cmd_runcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    code = " ".join(context.args or []).strip()

    if not code:
        await update.message.reply_text(
            "👑 <b>/runcode</b>\n\n"
            "Führt Python-Code direkt aus.\n\n"
            "<b>Beispiele:</b>\n\n"
            "<code>/runcode print(2+2)</code>\n\n"
            "<code>/runcode import numpy as np; print(np.random.rand(3,3))</code>\n\n"
            "<code>/runcode x = [i**2 for i in range(10)]; print(x)</code>\n\n"
            "Für komplexeren Code: /sandbox",
            parse_mode="HTML",
        )
        return

    decision = can_process_text(chat_id, code, action="sandbox")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

    loading = await update.message.reply_text("🧪 Führe Code aus...")

    try:
        result = await run_sandboxed_code(code, chat_id=chat_id, timeout=15)
        lines = []

        if result["success"]:
            lines.append(f"✅ <b>Erfolg</b> ({result['execution_time']}s)")
            if result["output"]:
                lines.append(_pre(result["output"], 3500))
            if result["result"] and str(result["result"]) != "✅ Code erfolgreich ausgeführt.":
                lines.append(f"📤 <b>Result:</b> {_code(str(result['result'])[:500])}")
        else:
            lines.append("❌ <b>Fehler</b>")
            if result["error"]:
                lines.append(_pre(result["error"], 3000))

        reply_text = "\n\n".join(lines)

        if result.get("plot"):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=result["plot"],
                caption="📊 Generierter Plot",
            )

        if result.get("file"):
            buf, fname = result["file"]
            await context.bot.send_document(
                chat_id=chat_id,
                document=buf,
                filename=fname,
                caption=f"📁 {_esc(fname)}",
            )

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=reply_text,
            parse_mode="HTML",
        )

        _persist_chat_turn(chat_id, f"/runcode {code[:100]}", f"Sandbox: {result['success']}")

        # Speichere auch im Brain
        try:
            from brain import save_text
            await save_text(chat_id, code, title="Sandbox /runcode")
        except Exception:
            pass

        last_generated_code[chat_id] = {
            "language": "python",
            "code": code,
            "timestamp": time.time(),
        }

    except Exception as exc:
        logger.exception("runcode Fehler")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Sandbox-Fehler:\n{_pre(str(exc)[:500])}",
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Sandbox-Fehler: {_esc(str(exc)[:300])}",
                parse_mode="HTML",
            )


# ── /codefile – Führt eine Python-Datei aus ──────────────────────────────────
async def cmd_codefile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text(
            "❌ Nutzung: Antworte auf eine <code>.py</code> Datei mit <code>/codefile</code>",
            parse_mode="HTML",
        )
        return

    doc = reply.document
    if not doc.file_name or not doc.file_name.endswith(".py"):
        await update.message.reply_text(
            "❌ Nur <code>.py</code> Dateien werden unterstützt.",
            parse_mode="HTML",
        )
        return

    loading = await update.message.reply_text(
        f"📂 Lade {_esc(doc.file_name)}..."
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        code_bytes = bytes(await file.download_as_bytearray())
        code = code_bytes.decode("utf-8", errors="ignore")

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"🧪 Führe <code>{_esc(doc.file_name)}</code> aus...",
            parse_mode="HTML",
        )

        result = await run_sandboxed_code(code, chat_id=chat_id)
        lines = [f"📂 <b>{_esc(doc.file_name)}</b> ({result['execution_time']}s)"]

        if result["success"]:
            lines.append("✅ Erfolg")
            if result["output"]:
                lines.append(_pre(result["output"], 3000))
        else:
            lines.append("❌ Fehler")
            if result["error"]:
                lines.append(_pre(result["error"], 2500))

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text="\n\n".join(lines),
            parse_mode="HTML",
        )

        if result.get("plot"):
            await context.bot.send_photo(chat_id=chat_id, photo=result["plot"], caption="📊 Plot")
        if result.get("file"):
            buf, fname = result["file"]
            await context.bot.send_document(chat_id=chat_id, document=buf, filename=fname)

        # Speichere im Brain
        try:
            from brain import save_text
            await save_text(chat_id, code, title=f"Sandbox: {doc.file_name}")
        except Exception:
            pass

    except Exception as exc:
        logger.exception("codefile Fehler")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Fehler: {_esc(str(exc)[:200])}",
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Fehler: {_esc(str(exc)[:200])}",
                parse_mode="HTML",
            )


# ── /py – Kurzform für /runcode ─────────────────────────────────────────────
async def cmd_py(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_runcode(update, context)


# ── /htmlapp – Generiert eine HTML Mini-App ─────────────────────────────────
async def cmd_htmlapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    html_code = " ".join(context.args or []).strip()

    if not html_code:
        await update.message.reply_text(
            "🌐 <b>/htmlapp</b>\n\n"
            "Generiert eine HTML Mini-App.\n\n"
            "<b>Beispiel:</b>\n\n"
            '<code>/htmlapp &lt;h1 style="color:#a78bfa"&gt;Hallo&lt;/h1&gt;</code>\n\n'
            "Für komplexere Apps: /sandbox → Sprache auf HTML stellen.",
            parse_mode="HTML",
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
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Fehler: {_esc(str(exc)[:200])}",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ── /parsecode – AST-Analyse direkt im Chat ─────────────────────────────────
async def cmd_parsecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parsed Python-Code und zeigt die Struktur an."""
    chat_id = str(update.effective_chat.id)
    code = " ".join(context.args or "").strip()

    if not code:
        # Versuche, den letzten gespeicherten Code zu parsen
        if chat_id in last_generated_code:
            code = last_generated_code[chat_id]["code"]
        else:
            await update.message.reply_text(
                "🔍 <b>/parsecode</b>\n\n"
                "Analysiert Python-Code-Struktur.\n\n"
                "<code>/parsecode def hello(): print('Hallo')</code>\n\n"
                "Oder nutze /sandbox für den visuellen Parser.",
                parse_mode="HTML",
            )
            return

    try:
        import ast
        tree = ast.parse(code)

        elements = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    elements.append(f"📦 import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    elements.append(f"📦 from {module} import {alias.name}")
            elif isinstance(node, ast.ClassDef):
                elements.append(f"🏛️ class {node.name}")
            elif isinstance(node, ast.FunctionDef):
                elements.append(f"⚙️ def {node.name}()")

        if not elements:
            await update.message.reply_text("🔍 Keine Struktur-Elemente erkannt.", parse_mode="HTML")
            return

        text = "🔍 <b>Code-Analyse</b>\n\n" + "\n".join(_code(e) for e in elements[:30])
        await update.message.reply_text(text, parse_mode="HTML")

    except SyntaxError as se:
        await update.message.reply_text(
            f"❌ Syntax-Fehler: {_esc(str(se))}",
            parse_mode="HTML"
        )


# ── Callback Handler ──────────────────────────────────────────────────────────
async def sandbox_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "👑 In Sandbox öffnen",
                web_app=WebAppInfo(url=SANDBOX_WEBAPP_URL)
            )],
        ])

        await query.edit_message_text(
            f"📋 <b>Template: {_esc(template_key)}</b>\n\n"
            f"<pre><code class=\"language-python\">{_esc(fit_telegram_text(code, 3500))}</code></pre>\n\n"
            "Tippe den Button, um in der Sandbox zu bearbeiten.",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

        last_generated_code[chat_id] = {
            "language": "python",
            "code": code,
            "timestamp": time.time(),
        }
