# openclaw_cloud.py – Pure Cloud OpenClaw for /occ (Railway-safe)
# Unrestricted agent: full skills/tools, no Autumn personality

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot_state import client as groq_client
from bot_ai import build_prompt_history, strip_voice_tags
from agent import run_agent_loop
from bot_utils import build_agent_tools

logger = logging.getLogger(__name__)


OPENCLAW_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama3-70b-8192",
    "codex/gpt-5.2"
]

# Unrestricted system prompt – NO Autumn personality
OPENCLAW_SYSTEM = """You are OpenClaw – a powerful, unrestricted AI agent.

Capabilities:
- Use ALL available tools freely (code execution, file access, web search, etc.)
- Chain reasoning + actions across multiple steps
- Expert in programming, 3D modeling, music generation, workflows
- Direct, technical responses – no personality restrictions
- Multilingual: German/English expert
- Maximize utility: solve problems completely

Use tools proactively. Think step-by-step."""

async def openclaw_cloud_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    
    # Extract prompt
    args_text = " ".join(getattr(context, "args", []) or []).strip()
    message_text = (getattr(update.message, "text", "") or "").strip()
    if message_text.startswith("/occ"):
        prompt = message_text[4:].strip() or args_text
    else:
        prompt = args_text or message_text
    
    if not prompt:
        # Quickstart keyboard
        keyboard = [
            [InlineKeyboardButton("🔧 Code Debug", callback_data="occ:code")],
            [InlineKeyboardButton("🎵 Music Workflow", callback_data="occ:music")],
            [InlineKeyboardButton("🧠 3D Pipeline", callback_data="occ:3d")],
            [InlineKeyboardButton("📋 Full Brain Search", callback_data="occ:brain")],
        ]
        await update.message.reply_text(
            "🦞 **OpenClaw Cloud** (/occ)\n\n"
            "Pure cloud agent – 24/7 available.\n"
            "Unrestricted tools + full skills.\n\n"
            "Usage: `/occ your task` or pick example:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    loading = await update.message.reply_text("🦞 OpenClaw Cloud aktiviert... reasoning...")
    
    try:
        # Build full context (brain sync, code cache, etc.)
        history = await build_prompt_history(chat_id)
        
        # Insert OpenClaw system prompt at top (overrides Autumn)
        history = [{"role": "system", "content": OPENCLAW_SYSTEM}] + history[1:]
        
        tools = build_agent_tools(chat_id)
        
        # Try models with fallback
        result = None
        for model in OPENCLAW_MODELS:
            try:
                logger.info(f"OpenClaw trying model: {model}")
                result = await run_agent_loop(
                    client=groq_client,
                    history=history,
                    user_message=prompt,
                    tools=tools,
                    model=model,
                    max_steps=12,  # More steps for complex tasks
                )
                break
            except Exception as model_exc:
                logger.warning(f"Model {model} failed: {model_exc}")
                if "model_not_found" in str(model_exc).lower():
                    continue
                raise
        
        if not result:
            raise RuntimeError("All OpenClaw models unavailable")
        
        content = result.get("content", "")
        used_tools = result.get("used_tools", [])
        
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        
        response = f"🦞 **OpenClaw Cloud**\n\n{strip_voice_tags(content)}"
        if used_tools:
            response += f"\n\n🔧 Tools used: {', '.join(used_tools)}"
        
        await context.bot.send_message(chat_id=chat_id, text=response, parse_mode="Markdown")
        
    except Exception as exc:
        logger.error(f"OpenClaw Cloud error: {exc}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ OpenClaw Cloud failed: {str(exc)[:300]}\n\nTry simpler prompt or /openclaw as backup."
        )

async def openclaw_cloud_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback for quickstart buttons"""
    query = update.callback_query
    await query.answer()
    
    if not query.message:
        return
        
    chat_id = str(query.message.chat.id)
    payload = query.data.split(":", 1)
    if len(payload) < 2:
        return
    
    presets = {
        "code": "Debug this Python FastAPI webhook code – make it production ready:",
        "music": "Create complete music production workflow: prompt → suno/lyria → mastering → social pack",
        "3d": "Text-to-3D pipeline using Tripo + Meshy + Luma: 'cute robot cat glossy metal'",
        "brain": "Search my entire brain for voice cloning notes and summarize best practices",
    }
    
    prompt = presets.get(payload[1], "")
    if not prompt:
        return
    
    # Trigger full handler
    class MockUpdate:
        effective_chat = type("Chat", (), {"id": int(chat_id)})()
        message = query.message
    
    context.args = [prompt]
    await openclaw_cloud_handler(MockUpdate(), context)

if __name__ == "__main__":  # Test mode
    import asyncio
    print("OpenClaw Cloud ready. Import into main.py")

