import logging
import httpx
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

OPENCLAW_URL = "http://127.0.0.1:18789"   # ← Dein Port

async def cmd_openclaw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text(
            "🦞 **OpenClaw Streaming**\n\n"
            "Nutze: `/openclaw Deine Frage oder Aufgabe`"
        )
        return

    # Lade-Nachricht
    msg = await update.message.reply_text("🦞 OpenClaw denkt und streamt...")

    full_text = ""
    message_id = msg.message_id

    models_to_try = ["meta-llama/llama-4-scout-17b-16e-instruct", "llama3-70b-8192", "codex/gpt-5.2"]

    success = False
    for model_name in models_to_try:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{OPENCLAW_URL}/api/chat/stream",
                    json={
                        "message": query,
                        "model": model_name,
                        "temperature": 0.7,
                        "max_tokens": 6000,
                        "stream": True
                    }
                ) as response:

                    full_text = ""
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if line.startswith("data: "):
                            chunk = line[6:].strip()
                            if chunk == "[DONE]" or not chunk:
                                continue

                            try:
                                # Einfache Chunk-Verarbeitung
                                if "content" in chunk or "delta" in chunk:
                                    import json
                                    data = json.loads(chunk) if chunk.startswith("{") else {"content": chunk}
                                    text = data.get("content") or data.get("delta", "")

                                    if text:
                                        full_text += text
                                        # Live Update (alle ~300 Zeichen)
                                        if len(full_text) % 280 < 50:
                                            try:
                                                await context.bot.edit_message_text(
                                                    chat_id=chat_id,
                                                    message_id=message_id,
                                                    text=full_text + " ▌"
                                                )
                                            except:
                                                pass
                            except:
                                continue
                    success = True
                    logger.info(f"OpenClaw success with model: {model_name}")
                    break
        except Exception as model_exc:
            logger.warning(f"Model {model_name} failed: {model_exc}")
            continue

    if success:
        # Finale Nachricht
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=full_text or "Keine Antwort erhalten."
        )
    else:
        logger.error(f"All OpenClaw models failed")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="❌ OpenClaw konnte nicht erreicht werden.\n\nAlle Modelle fehlgeschlagen."
        )