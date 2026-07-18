# claude_code_fixed.py – Modern Claude Code Module (Pydantic/Streaming/Tools)
from typing import Dict, Any
import os
import json
from pydantic import BaseModel, Field
from anthropic import Anthropic
from telegram import Update
from telegram.ext import ContextTypes
from bot_state import last_generated_code
from bot_utils import create_download_buffer
import logging

logger = logging.getLogger(__name__)

class CodeResult(BaseModel):
    code: str = Field(..., description="Full code")
    language: str = Field(default="python")
    explanation: str = Field(...)

client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

async def handle_claude_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clcode <prompt> – Claude code gen/edit.
    Examples:
    1. /clcode Create FastAPI webhook endpoint
    2. Reply on code /clcode Add auth middleware
    3. /clcode python: Build Discord bot
    """
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    
    if not (text.startswith('/clcode ') or text.startswith('/codeclaude ')):
        await update.message.reply_text('Usage:\\n/clcode <prompt>\\nReply on code for edits.')
        return
    
    prompt = text.split(' ', 1)[1] if ' ' in text[7:] else ''
    
    loading = await update.message.reply_text('🧠 Claude 4 coding...')
    
    existing_code = None
    if update.message.reply_to_message:
        existing_code = update.message.reply_to_message.text or ''
    
    try:
        system = 'Senior Engineer. Precise edits. JSON ONLY: ' + CodeResult.model_json_schema()
        
        msg = f'Prompt: {prompt}\\n{"Existing: " + existing_code if existing_code else ''}'
        
        resp = await client.messages.create(
            model='claude-3-5-sonnet-20240620',
            max_tokens=4000,
            system=system,
            messages=[{'role': 'user', 'content': msg}]
        )
        
        content = resp.content[0].text
        # Pydantic parse
        json_match = json.loads(content[content.find('{'):content.rfind('}')+1])
        result = CodeResult(**json_match)
        
        await context.bot.delete_message(chat_id, loading.message_id)
        
        preview = result.code[:1500] + '...' if len(result.code) > 1500 else result.code
        await context.bot.send_message(
            chat_id,
            f'**{result.explanation}**\\n\\n```{result.language}\\n{preview}\\n```',
            parse_mode='Markdown'
        )
        
        buffer, fn = create_download_buffer(result.code, result.language)
        await context.bot.send_document(chat_id, document=buffer, filename=fn, caption='💾 Download')
        
        last_generated_code[chat_id] = {'language': result.language, 'code': result.code}
        
    except Exception as e:
        logger.error('Claude code: %s', e)
        await context.bot.edit_message_text(chat_id, loading.message_id, f'❌ Claude error: {str(e)}')

# Replace old olko.py + handle_claude_code.py with this

