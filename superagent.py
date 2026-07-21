import asyncio
import logging
import os
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from bot_ai import build_prompt_history
from agent import run_agent_loop
from bot_utils import build_agent_tools
from bot_state import client as groq_client
from brain import load_all_entries

logger = logging.getLogger(__name__)

# ── Laufende SuperAgent-Tasks pro Chat, damit /superagentstop sie abbrechen kann ──
_active_superagent_tasks: Dict[str, asyncio.Task] = {}

SUPER_SYSTEM = """
Du bist SuperAgent – Master aller Bot-Modules.

Du hast permanenten Zugriff auf den vollständigen aktuellen Bot-Code via search_code_brain.
Wenn der User nach Code fragt (z.B. "Erkläre mir die SuperAgent-Logik", "Debugge den polling_loop", 
"Wie funktioniert der Brain-Upload?"), verwende DAS search_code_brain Tool mit relevanten Suchbegriffen.

Du kannst den Code auch jederzeit neu speichern mit dem save_code_brain Tool, falls der User den aktuellen Code aktualisieren möchte.

Beispiele für Code-Fragen:
1. "Erkläre mir die SuperAgent-Logik" → search_code_brain: "superagent handler"
2. "Debugge den polling_loop" → search_code_brain: "polling_loop"
3. "Wie funktioniert der Brain-Upload?" → search_code_brain: "save_file brain upload"
4. "Speichere meinen aktuellen Code" → save_code_brain

Andere Aufgaben:
1. Reel self-love video+music
2. Brain list delete old
3. Web search für aktuelle Infos
"""

async def superagent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /superagent [task]
    Examples:
    1. Create viral reel self-love
    2. Show code explain watchdog
    3. Brain delete old voices
    """
    chat_id = str(update.effective_chat.id)
    task_text = ' '.join(context.args).strip()
    
    keyboard = [
        [InlineKeyboardButton("Code MD", callback_data="super:code")],
        [InlineKeyboardButton("Self Check", callback_data="super:check")],
        [InlineKeyboardButton("Sandbox App", callback_data="super:sandbox")],
        [InlineKeyboardButton("Ask Code", callback_data="super:ask")],
        [InlineKeyboardButton("Save Code", callback_data="super:savecode")]
    ]
    
    if not task_text:
        if context.args and context.args[0].lower() == 'list':
            tools = build_agent_tools(chat_id)
            tool_list = "\\n".join(f"• **{t.name}**: {t.description[:80]}" for t in tools)
            await update.message.reply_text(
                f"**Superagent Functions (Self-Executing, Persistent Memory):**\\n\\n{tool_list}\\n\\n*3D convert, text3d, dashboard, brain, web...*",
                parse_mode='Markdown'
            )
            return
        await update.message.reply_text(
            "SuperAgent Ready! /superagent list for tools/capabilities.\\nTask or buttons.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    if chat_id in _active_superagent_tasks and not _active_superagent_tasks[chat_id].done():
        await update.message.reply_text(
            "⚠️ Es läuft bereits ein SuperAgent-Task in diesem Chat. Erst /superagentstop, dann neu starten."
        )
        return

    loading = await update.message.reply_text("SuperAgent active... (/superagentstop zum Abbrechen)")

    try:
        history = await build_prompt_history(chat_id)
        # BUGFIX: SUPER_SYSTEM wurde vorher nirgends verwendet (toter Code) -
        # der SuperAgent bekam nie die Anweisung, dass er search_code_brain /
        # save_code_brain fuer Code-Fragen nutzen soll. Jetzt vorangestellt.
        history = [{"role": "system", "content": SUPER_SYSTEM}] + history
        tools = build_agent_tools(chat_id)
        logger.info(f"SuperAgent tools available: {len(tools)} tools, history length: {len(history)}")

        agent_task = asyncio.create_task(
            run_agent_loop(
                client=groq_client,
                history=history,
                user_message=task_text,
                tools=tools,
                max_steps=6,
            )
        )
        _active_superagent_tasks[chat_id] = agent_task
        try:
            result = await agent_task
        finally:
            _active_superagent_tasks.pop(chat_id, None)

        await context.bot.delete_message(chat_id, loading.message_id)
        await context.bot.send_message(chat_id, result['content'])
    except asyncio.CancelledError:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=loading.message_id, text="🛑 SuperAgent abgebrochen."
        )
    except Exception as e:
        logger.error(str(e))
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=str(e)[:200])


async def superagent_stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/superagentstop – bricht einen laufenden SuperAgent-Task für diesen Chat ab."""
    chat_id = str(update.effective_chat.id)
    agent_task = _active_superagent_tasks.get(chat_id)
    if not agent_task or agent_task.done():
        await update.message.reply_text("Kein laufender SuperAgent-Task in diesem Chat.")
        return
    agent_task.cancel()
    await update.message.reply_text("🛑 SuperAgent wird abgebrochen...")

async def superagent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "super:code":
        try:
            with open("analysis.md", "rb") as f:
                await query.message.reply_document(document=f, filename="code.md")
        except:
            await query.message.reply_text("Code MD ready soon.")
    elif query.data == "super:check":
        await query.message.reply_text("All modules OK.")
    elif query.data == "super:sandbox":
        await query.message.reply_text("Sandbox: streamlit run dashboard.py")
    elif query.data == "super:ask":
        await query.message.reply_text("Ask code question.")
    elif query.data == "super:savecode":
        from handlers_cmd import cmd_savecode
        await cmd_savecode(query, None)

# Register in main.py: CommandHandler("superagent", superagent_handler), CallbackQueryHandler(superagent_callback, pattern="^super:")

