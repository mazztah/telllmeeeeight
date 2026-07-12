from telegram import Update
from telegram.ext import ContextTypes
import time
import logging
logger = logging.getLogger(__name__)

async def handle_claude_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = (update.message.text or '').strip()
    
    if text.startswith('/clcode ') or text.startswith('/codeclaude '):
        prompt = text.replace('/clcode ', '').replace('/codeclaude ', '').strip()
    else:
        await update.message.reply_text(
            "❌ Nutzung:\n"
            "/clcode Erstelle Python Webscraper\n"
            "/clcode python: baue Flask App\n"
            "Reply auf Code/Datei: /clcode optimiere/analysiere"
        )
        return
    
    loading = await update.message.reply_text("🧠 Claude 3.5 Sonnet generiert Code... 💻")
    
    existing_code = None
    if update.message.reply_to_message and update.message.reply_to_message.text:
        existing_code = update.message.reply_to_message.text.strip()
    
    from olko import claude_code_handler
    try:
        result = await claude_code_handler(chat_id, prompt, existing_code)
        
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        
        if result['success']:
            code = result['code']
            lang = result.get('language', 'python')
            explanation = result.get('explanation', 'Code generiert.')
            
            last_generated_code[chat_id] = {'language': lang, 'code': code, 'timestamp': time.time()}
            
            preview = code[:2000] + '...' if len(code) > 2000 else code
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"**{explanation}** 🧠\n\n```{lang}\n{preview}\n```",
                parse_mode='Markdown'
            )
            
            buffer, filename = create_download_buffer(code, lang, 'claude')
            await context.bot.send_document(
                chat_id=chat_id,
                document=buffer,
                filename=filename,
                caption=f"💾 Download: {filename}"
            )
            
            if 'changes' in result:
                await context.bot.send_message(chat_id=chat_id, text=f"**Änderungen:** {result['changes']}", parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Claude-Fehler: {result.get('error', 'Unbekannt')}")
    except Exception as e:
        logger.exception("Claude Code Error")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ {str(e)[:200]}")
