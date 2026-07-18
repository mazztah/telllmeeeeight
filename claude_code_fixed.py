# claude_code_fixed.py – Modern Claude Code Module (Pydantic/Streaming/Tools)
from typing import Dict, Any
import os
import json
import asyncio
from pydantic import BaseModel, Field
from telegram import Update
from telegram.ext import ContextTypes
from bot_state import last_generated_code, client as groq_client
from bot_utils import create_download_buffer
import logging

logger = logging.getLogger(__name__)

class CodeResult(BaseModel):
    code: str = Field(..., description="Full code")
    language: str = Field(default="python")
    explanation: str = Field(...)

CODE_MODEL = "groq/compound"
CODE_MODEL_FALLBACK = "llama3-70b-8192"

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
    
    loading = await update.message.reply_text('🧠 groq/compound coding...')
    
    existing_code = None
    if update.message.reply_to_message:
        existing_code = update.message.reply_to_message.text or ''
    
    try:
        system = 'Senior Engineer. Precise edits. JSON ONLY: ' + CodeResult.model_json_schema()
        
        msg = f'Prompt: {prompt}\\n{"Existing: " + existing_code if existing_code else ''}'

        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': msg},
        ]

        try:
            resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=CODE_MODEL,
                max_tokens=4000,
                messages=messages,
            )
        except Exception as exc:
            logger.warning('Code-Agent Modell %s fehlgeschlagen: %s', CODE_MODEL, exc)
            resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=CODE_MODEL_FALLBACK,
                max_tokens=4000,
                messages=messages,
            )

        content = resp.choices[0].message.content
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

