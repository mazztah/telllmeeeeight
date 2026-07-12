# openclaw.py - Cloud-based OpenClaw Agent (stable)
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot_state import client as groq_client, tts_enabled
from bot_ai import build_prompt_history, generate_voice, strip_voice_tags
from agent import run_agent_loop
from bot_utils import build_agent_tools

logger = logging.getLogger(__name__)

MODEL_CANDIDATES = [
    "openai/gpt-oss-120b"
]

PRESET_PROMPTS = {
    "trip": "Plane ein romantisches Wochenende in Berlin unter 500 Euro.",
    "brain": "Suche in meinem Brain nach Notizen zum Voice Cloning.",
    "code": "Hilf mir beim Debuggen meines Python Webhook Codes.",
}


def _extract_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args_text = " ".join(getattr(context, "args", []) or []).strip()
    if args_text:
        return args_text

    message = getattr(update, "message", None)
    text = (getattr(message, "text", "") or "").strip()
    if text.startswith("/openclaw"):
        return text[len("/openclaw") :].strip()
    return text


async def _run_openclaw_task(chat_id: str, prompt: str) -> dict:
    history = await build_prompt_history(chat_id)
    tools = build_agent_tools(chat_id)

    last_model_error = None
    for model_name in MODEL_CANDIDATES:
        try:
            return await run_agent_loop(
                client=groq_client,
                history=history,
                user_message=prompt,
                tools=tools,
                model=model_name,
                max_steps=8,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "model_not_found" in msg or "does not exist" in msg or "404" in msg:
                last_model_error = exc
                logger.warning("OpenClaw Modell nicht verfuegbar (%s): %s", model_name, exc)
                continue
            if "insufficient_quota" in msg:
                logger.warning("Groq Quota exhausted for %s", model_name)
                continue
            raise

    if last_model_error:
        raise last_model_error
    raise RuntimeError("Kein OpenClaw Modell verfuegbar.")


async def openclaw_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prompt = _extract_prompt(update, context)

    if not prompt:
        keyboard = [
            [InlineKeyboardButton("Plan Trip", callback_data="openclaw:trip")],
            [InlineKeyboardButton("Brain Search", callback_data="openclaw:brain")],
            [InlineKeyboardButton("Code Help", callback_data="openclaw:code")],
        ]
        await update.message.reply_text(
            "OpenClaw Agent\nWaehle einen Vorschlag oder nutze /openclaw <task>",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    loading = await update.message.reply_text("OpenClaw reasoning...")
    try:
        result = await _run_openclaw_task(chat_id, prompt)
        content = (result or {}).get("content") or "Kein Output."
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        if tts_enabled.get(chat_id, False):
            audio = await generate_voice(content, voice="hannah")
            if audio:
                await context.bot.send_audio(chat_id=chat_id, audio=audio, filename="openclaw.wav")
                return
        await context.bot.send_message(chat_id=chat_id, text=f"OpenClaw:\n\n{strip_voice_tags(content)}")
    except Exception as exc:
        logger.error("OpenClaw error: %s", exc)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"OpenClaw failed (tools retrying): {str(exc)[:250]}",
        )


async def openclaw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()
    payload = (query.data or "").split(":", 1)
    key = payload[1] if len(payload) == 2 else ""
    prompt = PRESET_PROMPTS.get(key)

    if not prompt:
        if query.message:
            await query.message.reply_text("Unbekannte OpenClaw-Aktion.")
        return

    chat_id = str(query.message.chat.id)
    loading = await query.message.reply_text("OpenClaw reasoning...")
    try:
        result = await _run_openclaw_task(chat_id, prompt)
        content = (result or {}).get("content") or "Kein Output."
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        if tts_enabled.get(chat_id, False):
            audio = await generate_voice(content, voice="hannah")
            if audio:
                await context.bot.send_audio(chat_id=chat_id, audio=audio, filename="openclaw.wav")
                return
        await query.message.reply_text(f"OpenClaw:\n\n{strip_voice_tags(content)}")
    except Exception as exc:
        logger.error("OpenClaw callback error: %s", exc)
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"OpenClaw failed (tools retrying): {str(exc)[:250]}",
        )

