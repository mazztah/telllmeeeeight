#!/usr/bin/env python3
# main.py – Telllmeeedrei_BOT | KORRIGIERT: Stabile Version v3.0.2
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import logging
import asyncio
import tempfile
import base64
import httpx
from pathlib import Path
from io import BytesIO

# ── HTTPX Global Connection Limits (verhindert socket exhaustion auf  HF Free Tier) ──
HTTPX_LIMITS = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=100,
)
HTTPX_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=15.0,
    write=10.0,
    pool=10.0,
)
from datetime import datetime, timedelta
import re as _re
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError as TgNetworkError, TimedOut as TgTimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import groq

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "false").lower() in ("true", "1", "yes")
WEBHOOK_URL = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
PORT = int(os.getenv("PORT", "7860"))
HOST = os.getenv("HOST", "0.0.0.0")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")

OFFSET_FILE = Path("last_update_offset.txt")

def _load_offset() -> int:
    try:
        if OFFSET_FILE.exists():
            return int(OFFSET_FILE.read_text().strip())
    except Exception as e:
        logger.warning("Offset-Laden fehlgeschlagen: %s", e)
    return 0

def _save_offset(offset: int) -> None:
    try:
        OFFSET_FILE.write_text(str(offset))
    except Exception as e:
        logger.warning("Offset-Speicherung fehlgeschlagen: %s", e)

_groq_client: Optional[groq.AsyncGroq] = None

def get_groq_client() -> groq.AsyncGroq:
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY fehlt!")
        _groq_client = groq.AsyncGroq(api_key=GROQ_API_KEY)
        logger.info("Groq-Client initialisiert")
    return _groq_client

_telegram_app: Optional[Application] = None
_init_lock = asyncio.Lock()
_polling_task = None
_watchdog_task = None

# ═══════════════════════════════════════════════════════════════════════════════
# MINI-APP IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from voice_mini_app import app as voice_mini_app
except ImportError as e:
    logger.warning(f"voice_mini_app nicht verfuegbar: {e}")
    voice_mini_app = None

try:
    from scanner_mini_app import app as scanner_mini_app
except ImportError as e:
    logger.warning(f"scanner_mini_app nicht verfuegbar: {e}")
    scanner_mini_app = None

try:
    from lightmeter_mini_app import app as lightmeter_mini_app
except ImportError as e:
    logger.warning(f"lightmeter_mini_app nicht verfuegbar: {e}")
    lightmeter_mini_app = None

try:
    from archive_mini_app import app as archive_mini_app
except ImportError as e:
    logger.warning(f"archive_mini_app nicht verfuegbar: {e}")
    archive_mini_app = None

try:
    from papersearch_mini_app import app as papersearch_mini_app
except ImportError as e:
    logger.warning(f"papersearch_mini_app nicht verfuegbar: {e}")
    papersearch_mini_app = None

try:
    from dragon_mini_app import app as dragon_mini_app
except ImportError as e:
    logger.warning(f"dragon_mini_app nicht verfuegbar: {e}")
    dragon_mini_app = None

try:
    from space_war_mini_app import app as spacewar_mini_app
except ImportError as e:
    logger.warning(f"space_war_mini_app nicht verfuegbar: {e}")
    spacewar_mini_app = None

try:
    from chess_mini_app import app as chess_app
except ImportError as e:
    logger.warning(f"chess_mini_app nicht verfuegbar: {e}")
    chess_app = None

try:
    from sandbox_mini_app import app as sandbox_mini_app
except ImportError as e:
    logger.warning(f"sandbox_mini_app nicht verfuegbar: {e}")
    sandbox_mini_app = None

try:
    from trichome_mini_app import app as trichome_mini_app
except ImportError as e:
    logger.warning(f"trichome_mini_app nicht verfuegbar: {e}")
    trichome_mini_app = None

try:
    from plantid_mini_app import app as plantid_mini_app
except ImportError as e:
    logger.warning(f"plantid_mini_app nicht verfuegbar: {e}")
    plantid_mini_app = None

try:
    from shellgame_mini_app import app as shellgame_mini_app
except ImportError as e:
    logger.warning(f"shellgame_mini_app nicht verfuegbar: {e}")
    shellgame_mini_app = None

try:
    from diagnose_app import app as diagnose_app
except ImportError as e:
    logger.warning(f"diagnose_app nicht verfuegbar: {e}")
    diagnose_app = None

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLER IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from bot_state import (
        application as telegram_application,
        OWNER_CHAT_ID as BOT_OWNER_ID,
        safe_send_message,
    )
except ImportError as e:
    logger.warning(f"bot_state nicht verfuegbar: {e}")
    telegram_application = None
    BOT_OWNER_ID = OWNER_CHAT_ID
    async def safe_send_message(*args, **kwargs):
        return None

try:
    from handlers_cmd import (
        start, handle_upload, handle_edit_command, handle_vision_command,
        handle_vision_stop, toggle_voice_response, handle_imagine, handle_textvideo,
        handle_stop_video, handle_code, handle_yt_pdf_callback, handle_email_callback,
        handle_audit_callback, cmd_synchromaster, cmd_synchroall, cmd_synchdata,
        cmd_convert, cmd_textconvert, cmd_yt, cmd_testbrain, cmd_chat, cmd_listbrain,
        cmd_agent, cmd_workflow, cmd_social, cmd_brainindex, cmd_semantic,
        cmd_privacy, cmd_guard_status, cmd_audit, cmd_gmail_auth, cmd_gmail_code,
        cmd_mailbatch, cmd_voiceclone, cmd_myvoices, cmd_deletevoice, cmd_speak,
        cmd_robot, cmd_deepvoice, cmd_chipmunk, cmd_demon, cmd_telephone, cmd_echo,
        cmd_stopdistort, cmd_alien, cmd_underwater, cmd_radio, cmd_megaphone,
        cmd_whisper, cmd_monster, cmd_cyberpunk, cmd_cave, cmd_helium, cmd_reverse,
        cmd_startstream, cmd_endstream, cmd_livevoice, cmd_scanner, cmd_shellgame,
        handle_ttv26, cmd_lyria, cmd_suno, cmd_freebeat, cmd_convert3d, cmd_text_to_3d,
        cmd_readme, cmd_diagnose, cmd_savecode, cmd_jobqueen, cmd_mooost, cmd_landme,
        cmd_immotracker,
    )
except ImportError as e:
    logger.warning(f"handlers_cmd nicht verfuegbar: {e}")
    def start(*args, **kwargs): pass
    def handle_upload(*args, **kwargs): pass
    def handle_edit_command(*args, **kwargs): pass
    def handle_vision_command(*args, **kwargs): pass
    def handle_vision_stop(*args, **kwargs): pass
    def toggle_voice_response(*args, **kwargs): pass
    def handle_imagine(*args, **kwargs): pass
    def handle_textvideo(*args, **kwargs): pass
    def handle_stop_video(*args, **kwargs): pass
    def handle_code(*args, **kwargs): pass
    def handle_yt_pdf_callback(*args, **kwargs): pass
    def handle_email_callback(*args, **kwargs): pass
    def handle_audit_callback(*args, **kwargs): pass
    def cmd_synchromaster(*args, **kwargs): pass
    def cmd_synchroall(*args, **kwargs): pass
    def cmd_synchdata(*args, **kwargs): pass
    def cmd_convert(*args, **kwargs): pass
    def cmd_textconvert(*args, **kwargs): pass
    def cmd_yt(*args, **kwargs): pass
    def cmd_testbrain(*args, **kwargs): pass
    def cmd_chat(*args, **kwargs): pass
    def cmd_listbrain(*args, **kwargs): pass
    def cmd_agent(*args, **kwargs): pass
    def cmd_workflow(*args, **kwargs): pass
    def cmd_social(*args, **kwargs): pass
    def cmd_brainindex(*args, **kwargs): pass
    def cmd_semantic(*args, **kwargs): pass
    def cmd_privacy(*args, **kwargs): pass
    def cmd_guard_status(*args, **kwargs): pass
    def cmd_audit(*args, **kwargs): pass
    def cmd_gmail_auth(*args, **kwargs): pass
    def cmd_gmail_code(*args, **kwargs): pass
    def cmd_mailbatch(*args, **kwargs): pass
    def cmd_voiceclone(*args, **kwargs): pass
    def cmd_myvoices(*args, **kwargs): pass
    def cmd_deletevoice(*args, **kwargs): pass
    def cmd_speak(*args, **kwargs): pass
    def cmd_robot(*args, **kwargs): pass
    def cmd_deepvoice(*args, **kwargs): pass
    def cmd_chipmunk(*args, **kwargs): pass
    def cmd_demon(*args, **kwargs): pass
    def cmd_telephone(*args, **kwargs): pass
    def cmd_echo(*args, **kwargs): pass
    def cmd_stopdistort(*args, **kwargs): pass
    def cmd_alien(*args, **kwargs): pass
    def cmd_underwater(*args, **kwargs): pass
    def cmd_radio(*args, **kwargs): pass
    def cmd_megaphone(*args, **kwargs): pass
    def cmd_whisper(*args, **kwargs): pass
    def cmd_monster(*args, **kwargs): pass
    def cmd_cyberpunk(*args, **kwargs): pass
    def cmd_cave(*args, **kwargs): pass
    def cmd_helium(*args, **kwargs): pass
    def cmd_reverse(*args, **kwargs): pass
    def cmd_startstream(*args, **kwargs): pass
    def cmd_endstream(*args, **kwargs): pass
    def cmd_livevoice(*args, **kwargs): pass
    def cmd_scanner(*args, **kwargs): pass
    def cmd_shellgame(*args, **kwargs): pass
    def handle_ttv26(*args, **kwargs): pass
    def cmd_lyria(*args, **kwargs): pass
    def cmd_suno(*args, **kwargs): pass
    def cmd_freebeat(*args, **kwargs): pass
    def cmd_convert3d(*args, **kwargs): pass
    def cmd_text_to_3d(*args, **kwargs): pass
    def cmd_readme(*args, **kwargs): pass
    def cmd_diagnose(*args, **kwargs): pass
    def cmd_savecode(*args, **kwargs): pass
    def cmd_jobqueen(*args, **kwargs): pass
    def cmd_mooost(*args, **kwargs): pass
    def cmd_landme(*args, **kwargs): pass
    def cmd_immotracker(*args, **kwargs): pass

try:
    from trichome_handler import cmd_trichome
    from trichome_analyzer import trichome_callback
except ImportError as e:
    logger.warning(f"trichome_handler nicht verfuegbar: {e}")
    def cmd_trichome(*args, **kwargs): pass
    def trichome_callback(*args, **kwargs): pass

try:
    from plantid_handler import cmd_plantid, plantid_callback
except ImportError as e:
    logger.warning(f"plantid_handler nicht verfuegbar: {e}")
    def cmd_plantid(*args, **kwargs): pass
    def plantid_callback(*args, **kwargs): pass

try:
    from archive_handler import cmd_archive, cmd_archivesearch, cmd_archivedetails, cmd_archivedownload
except ImportError as e:
    logger.warning(f"archive_handler nicht verfuegbar: {e}")
    def cmd_archive(*args, **kwargs): pass
    def cmd_archivesearch(*args, **kwargs): pass
    def cmd_archivedetails(*args, **kwargs): pass
    def cmd_archivedownload(*args, **kwargs): pass

try:
    from papersearch_handler import cmd_papersearch, cmd_psworkspace, cmd_pschat, papersearch_callback
except ImportError as e:
    logger.warning(f"papersearch_handler nicht verfuegbar: {e}")
    def cmd_papersearch(*args, **kwargs): pass
    def cmd_psworkspace(*args, **kwargs): pass
    def cmd_pschat(*args, **kwargs): pass
    def papersearch_callback(*args, **kwargs): pass

try:
    from brain_web_handler import cmd_brainweb, brainweb_callback
except ImportError as e:
    logger.warning(f"brain_web_handler nicht verfuegbar: {e}")
    def cmd_brainweb(*args, **kwargs): pass
    def brainweb_callback(*args, **kwargs): pass

try:
    from dragon_handler import cmd_dragon, dragon_callback
except ImportError as e:
    logger.warning(f"dragon_handler nicht verfuegbar: {e}")
    def cmd_dragon(*args, **kwargs): pass
    def dragon_callback(*args, **kwargs): pass

try:
    from space_war_handler import cmd_spacewar, spacewar_callback
except ImportError as e:
    logger.warning(f"space_war_handler nicht verfuegbar: {e}")
    def cmd_spacewar(*args, **kwargs): pass
    def spacewar_callback(*args, **kwargs): pass

try:
    from chess_handler import cmd_chess, chess_callback
except ImportError as e:
    logger.warning(f"chess_handler nicht verfuegbar: {e}")
    def cmd_chess(*args, **kwargs): pass
    def chess_callback(*args, **kwargs): pass

try:
    from sandbox_handler import cmd_sandbox, cmd_runcode, cmd_codefile, cmd_py, cmd_htmlapp, sandbox_callback
except ImportError as e:
    logger.warning(f"sandbox_handler nicht verfuegbar: {e}")
    def cmd_sandbox(*args, **kwargs): pass
    def cmd_runcode(*args, **kwargs): pass
    def cmd_codefile(*args, **kwargs): pass
    def cmd_py(*args, **kwargs): pass
    def cmd_htmlapp(*args, **kwargs): pass
    def sandbox_callback(*args, **kwargs): pass

try:
    from lightmeter_handler import cmd_lightmeter, lightmeter_callback
except ImportError as e:
    logger.warning(f"lightmeter_handler nicht verfuegbar: {e}")
    def cmd_lightmeter(*args, **kwargs): pass
    def lightmeter_callback(*args, **kwargs): pass

try:
    from superagent import superagent_handler, superagent_callback
except ImportError as e:
    logger.warning(f"superagent nicht verfuegbar: {e}")
    def superagent_handler(*args, **kwargs): pass
    def superagent_callback(*args, **kwargs): pass

try:
    from openclaw import openclaw_handler, openclaw_callback
except ImportError as e:
    logger.warning(f"openclaw nicht verfuegbar: {e}")
    def openclaw_handler(*args, **kwargs): pass
    def openclaw_callback(*args, **kwargs): pass

try:
    from openclaw_cloud import openclaw_cloud_handler, openclaw_cloud_callback
except ImportError as e:
    logger.warning(f"openclaw_cloud nicht verfuegbar: {e}")
    def openclaw_cloud_handler(*args, **kwargs): pass
    def openclaw_cloud_callback(*args, **kwargs): pass

try:
    from claude_code import handle_claude_code
except ImportError as e:
    logger.warning(f"claude_code nicht verfuegbar: {e}")
    def handle_claude_code(*args, **kwargs): pass

try:
    from brainlist_handler import cmd_brainlist as brainlist_cmd, brain_callback as brain_cb
except ImportError as e:
    logger.warning(f"brainlist_handler nicht verfuegbar: {e}")
    def brainlist_cmd(*args, **kwargs): pass
    def brain_cb(*args, **kwargs): pass

try:
    from handlers_media import handle_photo, handle_voice, handle_audio_upload, handle_document, handle_musik, handle_humming
except ImportError as e:
    logger.warning(f"handlers_media nicht verfuegbar: {e}")
    def handle_photo(*args, **kwargs): pass
    def handle_voice(*args, **kwargs): pass
    def handle_audio_upload(*args, **kwargs): pass
    def handle_document(*args, **kwargs): pass
    def handle_musik(*args, **kwargs): pass
    def handle_humming(*args, **kwargs): pass

try:
    from handlers_chat import handle_message
except ImportError as e:
    logger.warning(f"handlers_chat nicht verfuegbar: {e}")
    def handle_message(*args, **kwargs): pass

try:
    from stickerpack import cmd_stickerpack, collect_sticker_for_pack, finish_stickerpack, handle_bg_callback, has_active_sticker_session
except ImportError as e:
    logger.warning(f"stickerpack nicht verfuegbar: {e}")
    def cmd_stickerpack(*args, **kwargs): pass
    def collect_sticker_for_pack(*args, **kwargs): pass
    def finish_stickerpack(*args, **kwargs): pass
    def handle_bg_callback(*args, **kwargs): pass
    def has_active_sticker_session(*args, **kwargs): return False

try:
    from gif_handler import handle_gif_command, collect_gif_for_session, finish_gif_session, cancel_gif_session, has_active_gif_session
except ImportError as e:
    logger.warning(f"gif_handler nicht verfuegbar: {e}")
    def handle_gif_command(*args, **kwargs): pass
    def collect_gif_for_session(*args, **kwargs): pass
    def finish_gif_session(*args, **kwargs): pass
    def cancel_gif_session(*args, **kwargs): pass
    def has_active_gif_session(*args, **kwargs): return False

try:
    from instantmesh import mesh_handler
except ImportError as e:
    logger.warning(f"instantmesh nicht verfuegbar: {e}")
    mesh_handler = None

try:
    from brain import (
        is_enabled as brain_enabled,
        save_chat, save_text, save_file, load_all_entries, load_entry,
        list_entries, delete_entry, set_master_prompt, test_connection as test_brain_connection,
        get_brain_status,
    )
except ImportError as e:
    logger.warning(f"brain nicht verfuegbar: {e}")
    brain_enabled = lambda: False
    async def save_chat(*args, **kwargs): return "Brain nicht verfuegbar"
    async def save_text(*args, **kwargs): return "Brain nicht verfuegbar"
    async def save_file(*args, **kwargs): return "Brain nicht verfuegbar"
    async def load_all_entries(*args, **kwargs): return []
    async def load_entry(*args, **kwargs): return None
    async def list_entries(*args, **kwargs): return "Brain nicht verfuegbar"
    async def delete_entry(*args, **kwargs): return "Brain nicht verfuegbar"
    async def set_master_prompt(*args, **kwargs): return None
    async def test_brain_connection(*args, **kwargs): return "Brain nicht konfiguriert"
    async def get_brain_status(*args, **kwargs): return {}

try:
    from brain_agent import brain_query_agent
except ImportError as e:
    logger.warning(f"brain_agent nicht verfuegbar: {e}")
    async def brain_query_agent(*args, **kwargs): return {"success": False, "answer": "Agent nicht verfuegbar"}

try:
    from super_skill_app import router as superskill_router, cmd_superskill
except Exception as e:
    logger.warning(f"super_skill_app nicht verfuegbar: {e}")
    from fastapi import APIRouter
    superskill_router = APIRouter(prefix="/superskill")
    def cmd_superskill(*args, **kwargs): pass

class _GifSessionFilter(filters.BaseFilter):
    def check_update(self, update):
        if not getattr(update, "message", None):
            return False
        chat_id = str(update.effective_chat.id) if update.effective_chat else None
        return has_active_gif_session(chat_id) if chat_id else False

class _StickerSessionFilter(filters.BaseFilter):
    def check_update(self, update):
        if not getattr(update, "message", None):
            return False
        chat_id = str(update.effective_chat.id) if update.effective_chat else None
        return has_active_sticker_session(chat_id) if chat_id else False

gif_active = _GifSessionFilter()
sticker_active = _StickerSessionFilter()

# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM HANDLER REGISTRIERUNG
# ═══════════════════════════════════════════════════════════════════════════════

if telegram_application:
    application = telegram_application
else:
    application = Application.builder().token(TELEGRAM_TOKEN).build() if TELEGRAM_TOKEN else None

if application:
    async def _mesh_unavailable(update, context):
        if getattr(update, "message", None):
            await update.message.reply_text("Mesh nicht verfuegbar")

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("upload", handle_upload))
    application.add_handler(CommandHandler("synchromaster", cmd_synchromaster))
    application.add_handler(CommandHandler("synchroall", cmd_synchroall))
    application.add_handler(CommandHandler("synchdata", cmd_synchdata))
    application.add_handler(CommandHandler("convert", cmd_convert))
    application.add_handler(CommandHandler("textconvert", cmd_textconvert))
    application.add_handler(CommandHandler("yt", cmd_yt))
    application.add_handler(CommandHandler("voicetoggle", toggle_voice_response))
    application.add_handler(CommandHandler("imagine", handle_imagine))
    application.add_handler(CommandHandler("img", handle_imagine))
    application.add_handler(CommandHandler("edit", handle_edit_command))
    application.add_handler(CommandHandler("bearbeiten", handle_edit_command))
    application.add_handler(CommandHandler("vision", handle_vision_command))
    application.add_handler(CommandHandler("analyze", handle_vision_command))
    application.add_handler(CommandHandler("beschreib", handle_vision_command))
    application.add_handler(CommandHandler("visionstop", handle_vision_stop))
    application.add_handler(CommandHandler("musik", handle_musik))
    application.add_handler(CommandHandler("humming", handle_humming))
    application.add_handler(CommandHandler("summen", handle_humming))
    application.add_handler(CommandHandler("testbrain", cmd_testbrain))
    application.add_handler(CommandHandler("chat", cmd_chat))
    application.add_handler(CommandHandler("listbrain", cmd_listbrain))
    application.add_handler(CommandHandler("agent", cmd_agent))
    application.add_handler(CommandHandler("workflow", cmd_workflow))
    application.add_handler(CommandHandler("social", cmd_social))
    application.add_handler(CommandHandler("brainindex", cmd_brainindex))
    application.add_handler(CommandHandler("semantic", cmd_semantic))
    application.add_handler(CommandHandler("privacy", cmd_privacy))
    application.add_handler(CommandHandler("guard", cmd_guard_status))
    application.add_handler(CommandHandler(["audit", "standard"], cmd_audit))
    application.add_handler(CommandHandler("gmail_auth", cmd_gmail_auth))
    application.add_handler(CommandHandler("gmail_code", cmd_gmail_code))
    application.add_handler(CommandHandler("mailbatch", cmd_mailbatch))
    application.add_handler(CommandHandler("emailbatch", cmd_mailbatch))
    application.add_handler(CommandHandler("voiceclone", cmd_voiceclone))
    application.add_handler(CommandHandler("myvoices", cmd_myvoices))
    application.add_handler(CommandHandler("deletevoice", cmd_deletevoice))
    application.add_handler(CommandHandler("speak", cmd_speak))
    application.add_handler(CommandHandler("robot", cmd_robot))
    application.add_handler(CommandHandler("deepvoice", cmd_deepvoice))
    application.add_handler(CommandHandler("chipmunk", cmd_chipmunk))
    application.add_handler(CommandHandler("demon", cmd_demon))
    application.add_handler(CommandHandler("telephone", cmd_telephone))
    application.add_handler(CommandHandler("echo", cmd_echo))
    application.add_handler(CommandHandler("alien", cmd_alien))
    application.add_handler(CommandHandler("underwater", cmd_underwater))
    application.add_handler(CommandHandler("radio", cmd_radio))
    application.add_handler(CommandHandler("megaphone", cmd_megaphone))
    application.add_handler(CommandHandler("whisper", cmd_whisper))
    application.add_handler(CommandHandler("monster", cmd_monster))
    application.add_handler(CommandHandler("cyberpunk", cmd_cyberpunk))
    application.add_handler(CommandHandler("cave", cmd_cave))
    application.add_handler(CommandHandler("helium", cmd_helium))
    application.add_handler(CommandHandler("reverse", cmd_reverse))
    application.add_handler(CommandHandler("stopdistort", cmd_stopdistort))
    application.add_handler(CommandHandler("textvideo", handle_textvideo))
    application.add_handler(CommandHandler("stopvideo", handle_stop_video))
    application.add_handler(CommandHandler("cancel", handle_stop_video))
    application.add_handler(CommandHandler("code", handle_code))
    application.add_handler(CommandHandler("startstream", cmd_startstream))
    application.add_handler(CommandHandler("voicestream", cmd_startstream))
    application.add_handler(CommandHandler("endstream", cmd_endstream))
    application.add_handler(CommandHandler("stopstream", cmd_endstream))
    application.add_handler(CommandHandler("livevoice", cmd_livevoice))
    application.add_handler(CommandHandler(["scan", "qr"], cmd_scanner))
    application.add_handler(CommandHandler("ttv26", handle_ttv26))
    application.add_handler(CommandHandler("lyria", cmd_lyria))
    application.add_handler(CommandHandler("suno", cmd_suno))
    application.add_handler(CommandHandler("freebeat", cmd_freebeat))
    application.add_handler(CommandHandler("superagent", superagent_handler))
    application.add_handler(CommandHandler("openclaw", openclaw_handler))
    application.add_handler(CommandHandler("occ", openclaw_cloud_handler))
    application.add_handler(CommandHandler("cloud", openclaw_cloud_handler))
    application.add_handler(CommandHandler(["clcode", "codeclaude", "codeclode"], handle_claude_code))
    application.add_handler(CommandHandler("brainlist", brainlist_cmd))
    application.add_handler(CommandHandler("mesh", mesh_handler) if mesh_handler else CommandHandler("mesh", _mesh_unavailable))
    application.add_handler(CommandHandler(["3d", "text3d", "instant3d"], cmd_text_to_3d))
    application.add_handler(CommandHandler("convert3d", cmd_convert3d))
    application.add_handler(CommandHandler("readme", cmd_readme))
    application.add_handler(CommandHandler("diagnose", cmd_diagnose))
    application.add_handler(CommandHandler("savecode", cmd_savecode))
    application.add_handler(CommandHandler("gif", handle_gif_command))
    application.add_handler(CommandHandler("gifdone", finish_gif_session))
    application.add_handler(CommandHandler("gifcancel", cancel_gif_session))
    application.add_handler(CommandHandler("stickerpack", cmd_stickerpack))
    application.add_handler(CommandHandler("done", finish_stickerpack))
    application.add_handler(CommandHandler("lightmeter", cmd_lightmeter))
    application.add_handler(CommandHandler("trichome", cmd_trichome))
    application.add_handler(CommandHandler("plantid", cmd_plantid))
    application.add_handler(CommandHandler("pflanze", cmd_plantid))
    application.add_handler(CommandHandler("shellgame", cmd_shellgame))
    application.add_handler(CommandHandler("archive", cmd_archive))
    application.add_handler(CommandHandler("archivesearch", cmd_archivesearch))
    application.add_handler(CommandHandler("archivedetails", cmd_archivedetails))
    application.add_handler(CommandHandler("archivedownload", cmd_archivedownload))
    application.add_handler(CommandHandler("papersearch", cmd_papersearch))
    application.add_handler(CommandHandler("psworkspace", cmd_psworkspace))
    application.add_handler(CommandHandler("pschat", cmd_pschat))
    application.add_handler(CommandHandler(["brain", "brainweb", "braindashboard"], cmd_brainweb))
    application.add_handler(CommandHandler("dragon", cmd_dragon))
    application.add_handler(CommandHandler("spacewar", cmd_spacewar))
    application.add_handler(CommandHandler("chess", cmd_chess))
    application.add_handler(CommandHandler("superskill", cmd_superskill))
    application.add_handler(CommandHandler("sandbox", cmd_sandbox))
    application.add_handler(CommandHandler("runcode", cmd_runcode))
    application.add_handler(CommandHandler("codefile", cmd_codefile))
    application.add_handler(CommandHandler("py", cmd_py))
    application.add_handler(CommandHandler("htmlapp", cmd_htmlapp))

    # direkt dahinter einfügen:
    application.add_handler(CommandHandler("jobqueen", cmd_jobqueen))
    application.add_handler(CommandHandler("jobs", cmd_jobqueen))
    application.add_handler(CommandHandler("mooost", cmd_mooost)) 
    application.add_handler(CommandHandler("landme", cmd_landme))
    application.add_handler(CommandHandler("immotracker", cmd_immotracker))

    # === NEU: Sendcode Handler (mit PDF, ZIP, Einzeldateien) ===
    from send_code_handler import cmd_send_code, sendcode_callback
    application.add_handler(CommandHandler("sendcode", cmd_send_code))
    application.add_handler(CallbackQueryHandler(sendcode_callback, pattern=r"^sendcode:"))

    application.add_handler(CallbackQueryHandler(handle_yt_pdf_callback, pattern=r"^ytpdf\|"))
    application.add_handler(CallbackQueryHandler(handle_email_callback, pattern=r"^email\|"))
    application.add_handler(CallbackQueryHandler(handle_audit_callback, pattern=r"^audit:"))
    application.add_handler(CallbackQueryHandler(superagent_callback, pattern=r"^super:"))
    application.add_handler(CallbackQueryHandler(openclaw_callback, pattern=r"^openclaw:"))
    application.add_handler(CallbackQueryHandler(openclaw_cloud_callback, pattern=r"^occ:"))
    application.add_handler(CallbackQueryHandler(brain_cb, pattern=r"^brain:"))
    application.add_handler(CallbackQueryHandler(papersearch_callback, pattern=r"^ps:"))
    application.add_handler(CallbackQueryHandler(brainweb_callback, pattern=r"^brainweb:"))
    application.add_handler(CallbackQueryHandler(dragon_callback, pattern=r"^dragon:"))
    application.add_handler(CallbackQueryHandler(spacewar_callback, pattern=r"^spacewar:"))
    application.add_handler(CallbackQueryHandler(chess_callback, pattern=r"^chess:"))
    application.add_handler(CallbackQueryHandler(sandbox_callback, pattern=r"^sandbox:"))
    application.add_handler(CallbackQueryHandler(lightmeter_callback, pattern=r"^lightmeter:"))
    application.add_handler(CallbackQueryHandler(trichome_callback, pattern=r"^trichome:"))
    application.add_handler(CallbackQueryHandler(plantid_callback, pattern=r"^plantid:"))
    application.add_handler(CallbackQueryHandler(handle_bg_callback, pattern=r"^bg_(remove|keep):"))
        # Sendcode Callbacks (PDF, ZIP, Einzeldateien)
    

    application.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND & gif_active, collect_gif_for_session), group=-1)
    application.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND & sticker_active, collect_sticker_for_pack))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.AUDIO, handle_audio_upload))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))


        # Send Code – sicher gekapselt
    try:
        from send_code_handler import cmd_send_code
        application.add_handler(CommandHandler("sendcode", cmd_send_code))
        logger.info("✅ send_code_handler geladen")
    except Exception as e:
        logger.warning("⚠️ send_code_handler nicht geladen: %s", e)

    async def global_error_handler(update, context):
        err = context.error
        logger.warning(f"Handler-Fehler abgefangen: {type(err).__name__}: {err}")

        # Bei reinen Netzwerk-Timeouts keine zusätzliche User-Nachricht erzeugen:
        # das verhindert Timeout-Feedback-Schleifen.
        timeoutish = isinstance(err, (asyncio.TimeoutError, TgTimedOut, TgNetworkError))
        if err is not None and not timeoutish:
            err_text = str(err).lower()
            if "timed out" in err_text or "timeout" in err_text or "network" in err_text:
                timeoutish = True
        if timeoutish:
            return

        if update and hasattr(update, "effective_chat") and update.effective_chat:
            try:
                await safe_send_message(
                    context.bot,
                    str(update.effective_chat.id),
                    "Kurze Verbindungsstoerung bitte nochmal versuchen.",
                )
            except Exception:
                pass

    application.add_error_handler(global_error_handler)
    logger.info("Alle Telegram-Handler registriert")

# ═══════════════════════════════════════════════════════════════════════════════
# KORRIGIERTE INITIALISIERUNG – PTB v20 OFFICIAL PATTERN + WATCHDOG
# ═══════════════════════════════════════════════════════════════════════════════

# WICHTIG: Bei HF Spaces ist set_webhook() oft langsam/timeouted.
# Das ist KEIN Fehler – der Webhook funktioniert trotzdem, da Telegram
# die URL bereits kennt (wenn sie vorher schon gesetzt war).
# Wir behandeln set_webhook-Timeouts daher als Warnung, nicht als Fehler.

async def _set_webhook_safe() -> bool:
    """Setzt den Webhook. Timeout bei HF Spaces ist normal und kein Fehler."""
    if not application or not WEBHOOK_URL:
        return False

    webhook_url = f"{WEBHOOK_URL}/webhook"

    for attempt in range(1, 4):
        try:
            await asyncio.wait_for(
                application.bot.set_webhook(
                    url=webhook_url,
                    allowed_updates=["message", "edited_message", "callback_query"],
                    drop_pending_updates=True,
                ),
                timeout=30.0,
            )
            logger.info(f"✅ Webhook gesetzt: {webhook_url}")
            return True
        except asyncio.TimeoutError:
            # HF Spaces Netzwerk ist langsam – das ist OK!
            logger.warning(f"⏱️ set_webhook Versuch {attempt}/3 timed out (HF Spaces – normal)")
            if attempt == 3:
                # Letzter Versuch: Trotzdem als OK werten, da Webhook meist schon funktioniert
                logger.info("   → Webhook war wahrscheinlich schon gesetzt. Fahre fort.")
                return True
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"❌ set_webhook Versuch {attempt}/3 fehlgeschlagen: {e}")
            if attempt < 3:
                await asyncio.sleep(2)
    return False


async def _delete_webhook_safe():
    """Löscht den Webhook (für Polling-Mode)."""
    if not application:
        return
    try:
        await asyncio.wait_for(
            application.bot.delete_webhook(drop_pending_updates=False),
            timeout=10.0,
        )
        logger.info("Webhook gelöscht")
    except Exception as e:
        logger.warning(f"Webhook löschen fehlgeschlagen (ignoriert): {e}")


async def _send_startup_greeting():
    """Sendet eine Nachricht an den Owner beim Startup."""
    if not OWNER_CHAT_ID or not application:
        return
    try:
        await application.bot.send_message(
            chat_id=OWNER_CHAT_ID,
            text="🤖 Bot ist online!\nMode: Webhook\nVersion: 3.0.2\nSchreib /start für die Übersicht.",
        )
        logger.info(f"Startup-Greeting gesendet an {OWNER_CHAT_ID}")
    except Exception as e:
        logger.warning(f"Startup-Greeting fehlgeschlagen: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# WATCHDOG – Überwacht ob der Bot noch Updates verarbeitet
# ═══════════════════════════════════════════════════════════════════════════════

async def application_watchdog():
    """
    Überwacht die Bot-Gesundheit. 
    WICHTIG: Prüft NUR running + initialized. 
    bot._initialized ist bei PTB v20 NICHT zuverlässig und führt zu False-Positives.
    """
    await asyncio.sleep(20)
    logger.info("🔍 Application Watchdog gestartet")

    while True:
        try:
            if not application:
                logger.warning("Watchdog: Keine Application vorhanden")
                await asyncio.sleep(30)
                continue

            running = getattr(application, "_running", False)
            initialized = getattr(application, "_initialized", False)

            # Queue-Größe als Zusatzinfo (nicht als Kriterium)
            queue_size = "?"
            try:
                queue_size = application.update_queue.qsize()
            except Exception:
                pass

            logger.info(f"WATCHDOG | running={running} | initialized={initialized} | queue={queue_size}")

            # NUR restarten wenn Application wirklich tot
            if not running or not initialized:
                logger.error("⚠️ APPLICATION TOT – versuche Neustart...")
                try:
                    # Cleanup vor Neustart
                    try:
                        if getattr(application, "_running", False):
                            await application.stop()
                    except Exception:
                        pass
                    try:
                        if getattr(application, "_initialized", False):
                            await application.shutdown()
                    except Exception:
                        pass

                    # Frischer Start mit async with (offizielles PTB Pattern)
                    await application.initialize()
                    await application.start()
                    logger.info("✅ Application erfolgreich neu gestartet")

                    if USE_WEBHOOK and WEBHOOK_URL:
                        await _set_webhook_safe()

                except Exception as e:
                    logger.error(f"Neustart fehlgeschlagen: {e}")
            else:
                # Alle 2 Minuten: Prüfe ob Webhook noch da ist (nur Webhook-Mode)
                if USE_WEBHOOK and WEBHOOK_URL:
                    try:
                        info = await asyncio.wait_for(
                            application.bot.get_webhook_info(), 
                            timeout=10.0
                        )
                        if not info.url:
                            logger.warning("Webhook nicht mehr gesetzt – setze neu...")
                            await _set_webhook_safe()
                    except Exception:
                        pass  # Nicht kritisch

        except Exception as e:
            logger.error(f"Watchdog Fehler: {e}")

        await asyncio.sleep(25)


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK MODE INITIALISIERUNG
# ═══════════════════════════════════════════════════════════════════════════════

async def init_webhook_mode():
    """
    Initialisiert den Bot im Webhook-Mode.
    Nutzt das offizielle PTB v20 Pattern: initialize() → start() → set_webhook()
    """
    if not application:
        logger.error("init_webhook_mode: Keine Application vorhanden")
        return

    logger.info("🚀 Starte Webhook Mode Initialisierung...")

    try:
        # Offizielles PTB v20 Pattern
        await application.initialize()
        logger.info("✅ Application initialisiert")

        await application.start()
        logger.info("✅ Application gestartet")

        # Webhook setzen (Timeout ist bei HF Spaces normal)
        await _set_webhook_safe()

        # Startup-Greeting
        await _send_startup_greeting()

        logger.info("🎯 Webhook Mode vollständig initialisiert")

    except Exception as e:
        logger.error(f"❌ Webhook-Init fehlgeschlagen: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# POLLING MODE (FALLBACK)
# ═══════════════════════════════════════════════════════════════════════════════

async def _polling_inner():
    """Innere Polling-Schleife mit Fehlerbehandlung."""
    update_offset = _load_offset()
    consecutive_errors = 0
    max_consecutive_errors = 5

    logger.info(f"Polling-Loop gestartet (Offset: {update_offset})")
    while True:
        try:
            updates = await application.bot.get_updates(
                offset=update_offset,
                timeout=10,
                allowed_updates=["message", "edited_message", "callback_query"],
            )
            consecutive_errors = 0
            for update in updates:
                try:
                    await application.process_update(update)
                except Exception as e:
                    logger.error(f"Update-Verarbeitungsfehler: {e}")
                update_offset = update.update_id + 1
                _save_offset(update_offset)
            if not updates:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("Polling inner loop cancelled")
            _save_offset(update_offset)
            raise
        except (httpx.TimeoutException, asyncio.TimeoutError) as e:
            consecutive_errors += 1
            wait_time = min(2 ** consecutive_errors, 15)
            logger.warning(f"Polling-Timeout #{consecutive_errors}: {e} warte {wait_time}s")
            await asyncio.sleep(wait_time)
        except (httpx.ConnectError, httpx.NetworkError, ConnectionError) as e:
            consecutive_errors += 1
            wait_time = min(2 ** consecutive_errors, 15)
            logger.warning(f"Netzwerkfehler #{consecutive_errors}: {e} warte {wait_time}s")
            await asyncio.sleep(wait_time)
        except Exception as e:
            consecutive_errors += 1
            wait_time = min(2 ** consecutive_errors, 15)
            logger.error(f"Polling-Fehler #{consecutive_errors}: {e} warte {wait_time}s")
            await asyncio.sleep(wait_time)
        if consecutive_errors >= max_consecutive_errors:
            logger.error(f"Zu viele Fehler ({consecutive_errors}). Neustart in 30s...")
            await asyncio.sleep(60)
            consecutive_errors = 0


async def polling_loop():
    """Haupt-Polling-Loop."""
    logger.info("Starte Bot (Polling-Mode)...")

    try:
        await _delete_webhook_safe()
        await application.initialize()
        await application.start()
        logger.info("✅ Bot bereit für Polling")
        await _send_startup_greeting()
    except Exception as e:
        logger.error(f"Polling-Init fehlgeschlagen: {e}")
        return

    while True:
        try:
            await _polling_inner()
        except asyncio.CancelledError:
            logger.info("Polling gestoppt")
            break
        except Exception as e:
            logger.error(f"Polling-Loop abgestürzt: {e} Neustart in 10s")
            await asyncio.sleep(10)


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI LIFESPAN – OFFIZIELLES PTB v20 PATTERN
# ═══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _polling_task, _watchdog_task
    logger.info("🚀 FastAPI Lifespan Startup...")
    logger.info(f"USE_WEBHOOK: {USE_WEBHOOK}")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")

    if not application:
        logger.error("❌ Keine Telegram Application verfügbar!")
        yield
        return

    # Self-Keepalive starten (Render/Railway Free-Tier Wake-Up)
    try:
        asyncio.create_task(_self_keepalive())
        logger.info("✅ Self-Keepalive gestartet")
    except Exception as e:
        logger.warning(f"Self-Keepalive konnte nicht gestartet werden: {e}")

    # WATCHDOG starten (überwacht Bot-Gesundheit)
    _watchdog_task = asyncio.create_task(application_watchdog())
    logger.info("✅ Application Watchdog gestartet")

    if USE_WEBHOOK:
        if not WEBHOOK_URL:
            logger.error("USE_WEBHOOK=true aber WEBHOOK_URL fehlt!")
        else:
            asyncio.create_task(init_webhook_mode())
            logger.info("✅ Webhook-Init-Task gestartet (asynchron)")
            logger.info(f"   → Webhook URL: {WEBHOOK_URL}/webhook")
    else:
        _polling_task = asyncio.create_task(polling_loop())
        logger.info("✅ Polling-Task gestartet")

    yield

    logger.info("🛑 FastAPI Lifespan Shutdown...")

    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        try:
            await asyncio.wait_for(_watchdog_task, timeout=5.0)
        except Exception:
            pass

    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        try:
            await asyncio.wait_for(_polling_task, timeout=10.0)
        except Exception:
            pass

    if application:
        try:
            if getattr(application, "_running", False):
                await application.stop()
            if getattr(application, "_initialized", False):
                await application.shutdown()
            try:
                await application.bot.session.close()
            except Exception:
                pass
            logger.info("Bot sauber heruntergefahren")
        except Exception as e:
            logger.warning(f"Fehler beim Herunterfahren: {e}")

    logger.info("Shutdown abgeschlossen")



app = FastAPI(
    title="Telllmeeedrei_BOT",
    description="Telegram Bot mit 20+ Mini-Apps und Super-Skill Generator",
    version="3.0.2",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(superskill_router)

IS_HF_SPACE = os.getenv("SPACE_ID") is not None
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError) as exc:
    DATA_DIR = Path(__file__).resolve().parent / "data"
    logger.warning(
        "DATA_DIR nicht beschreibbar (%s) – verwende Fallback '%s'",
        exc, DATA_DIR,
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)

local_static = Path(__file__).parent / "static"
if local_static.exists() and local_static.is_dir() and any(local_static.iterdir()):
    static_dir = local_static
    logger.info(f"Static (local project): {static_dir}")
else:
    static_dir = DATA_DIR / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Static (DATA_DIR): {static_dir}")

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ═══════════════════════════════════════════════════════════════════════════════
# MINI-APP MOUNTS – Alle essenziellen Apps sofort mounten
# ═══════════════════════════════════════════════════════════════════════════════

if diagnose_app:
    app.mount("/diagnose", diagnose_app)
    logger.info("diagnose_app mounted")

if scanner_mini_app:
    app.mount("/scanner", scanner_mini_app)
    logger.info("scanner_mini_app mounted")

if sandbox_mini_app:
    app.mount("/sandbox", sandbox_mini_app)
    logger.info("sandbox_mini_app mounted")

# Optionale Mini-Apps (werden ebenfalls gemountet, aber sind leichtgewichtig)
_lazy_apps = {
    "voice": voice_mini_app,
    "lightmeter": lightmeter_mini_app,
    "trichome": trichome_mini_app,
    "plantid": plantid_mini_app,
    "shellgame": shellgame_mini_app,
    "archive": archive_mini_app,
    "papersearch": papersearch_mini_app,
    "dragon": dragon_mini_app,
    "spacewar": spacewar_mini_app,
    "chess": chess_app,
}

for name, mini_app in _lazy_apps.items():
    if mini_app:
        try:
            route = f"/{name}"
            app.mount(route, mini_app)
            logger.info(f"{name}_mini_app mounted")
        except Exception as e:
            logger.warning(f"Mount {name} fehlgeschlagen: {e}")


static_candidates = [
    Path("/data/static"),
    Path.cwd() / "static",
    Path(__file__).parent / "static",
    Path("/home/user/app/static"),
    Path("/home/user/app"),
    Path("/opt/render/project/src/static"),
]

sandbox_static_dir = None
for candidate in static_candidates:
    if not candidate.exists():
        continue
    css_path = candidate / "css" / "sandbox.css"
    js_path = candidate / "js" / "sandbox.js"
    if css_path.exists() and js_path.exists():
        sandbox_static_dir = candidate
        logger.info(f"Sandbox Static-Ordner GEFUNDEN: {candidate}")
        break
    elif candidate.exists():
        logger.info(f"Ordner gefunden, aber css/js fehlt: {candidate}")

if sandbox_static_dir:
    app.mount("/sandbox/static", StaticFiles(directory=str(sandbox_static_dir)), name="sandbox_static")
    logger.info(f"Sandbox Static Files gemountet")

app.mount("/brain-static", StaticFiles(directory=str(static_dir)), name="brain_static")


def _ensure_superskill_assets() -> None:
    """Stellt sicher, dass SuperSkill-Assets auch dann verfügbar sind, wenn sie im Repo-Root liegen."""
    src_root = Path(__file__).parent
    css_src = src_root / "super_skill.css"
    js_src = src_root / "super_skill.js"
    html_alt_src = src_root / "super_skill_workspace_alt.html"
    html_alt_src_2 = src_root / "super_skill_workspace (1).html"
    html_src = src_root / "super_skill_workspace.html"

    css_dst = static_dir / "css" / "super_skill.css"
    js_dst = static_dir / "js" / "super_skill.js"
    html_dst = static_dir / "super_skill_workspace.html"
    html_alt_dst = static_dir / "super_skill_workspace_alt.html"

    try:
        css_dst.parent.mkdir(parents=True, exist_ok=True)
        js_dst.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning("SuperSkill Asset-Ordner konnten nicht erstellt werden: %s", e)
        return

    for src, dst in [
        (css_src, css_dst),
        (js_src, js_dst),
        (html_alt_src, html_alt_dst),
        (html_alt_src_2, html_alt_dst),
    ]:
        try:
            if src.exists() and (not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime):
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info("SuperSkill Asset gespiegelt: %s -> %s", src.name, dst)
        except Exception as e:
            logger.warning("SuperSkill Asset-Spiegelung fehlgeschlagen (%s): %s", src.name, e)

    # Wenn es nur die alte HTML gibt, trotzdem in static bereitstellen.
    try:
        if not html_dst.exists() and html_src.exists():
            html_dst.write_text(html_src.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as e:
        logger.warning("SuperSkill HTML-Fallback konnte nicht gespiegelt werden: %s", e)


_ensure_superskill_assets()


def _read_superskill_html() -> Optional[str]:
    legacy_content = None
    candidates = [
        static_dir / "super_skill_workspace (1).html",
        static_dir / "super_skill_workspace_alt.html",
        Path("/home/user/app/static/super_skill_workspace_alt.html"),
        Path("/app/static/super_skill_workspace_alt.html"),
        Path("/home/user/app/static/super_skill_workspace (1).html"),
        Path("/app/static/super_skill_workspace (1).html"),
        static_dir / "super_skill_workspace.html",
        Path("/home/user/app/static/super_skill_workspace.html"),
        Path("/app/static/super_skill_workspace.html"),
        Path(__file__).parent / "super_skill_workspace_alt.html",
        Path(__file__).parent / "super_skill_workspace.html",
    ]
    for html_path in candidates:
        if not html_path.exists():
            continue
        try:
            content = html_path.read_text(encoding="utf-8")
            # Alte Frontend-Version (direkter Anthropic-Call) bevorzugt NICHT ausliefern.
            if "https://api.anthropic.com/v1/messages" in content:
                logger.warning("SuperSkill HTML %s nutzt Legacy-Frontend, suche modernere Variante...", html_path)
                if legacy_content is None:
                    legacy_content = content
                continue
            return content
        except Exception as e:
            logger.warning("SuperSkill HTML konnte nicht gelesen werden (%s): %s", html_path, e)
    return legacy_content

@app.get("/superskill", response_class=HTMLResponse)
@app.get("/superskill/", response_class=HTMLResponse)
async def superskill_page():
    html = _read_superskill_html()
    if html:
        return HTMLResponse(content=html)
    logger.error("super_skill_workspace.html nicht gefunden!")
    return HTMLResponse(
        content="<h1 style='color:red;text-align:center;margin-top:50px;'>SuperSkill-Workspace nicht gefunden</h1>",
        status_code=404
    )


@app.get("/brain", response_class=HTMLResponse)
@app.get("/brain/", response_class=HTMLResponse)
async def brain_dashboard():
    brain_file = static_dir / "brain.html"
    if brain_file.exists():
        return FileResponse(brain_file)
    return HTMLResponse("""
        <h1 style="color:red;text-align:center;margin-top:50px;">brain.html nicht gefunden</h1>
        <p style="text-align:center;">Bitte lade die Datei als <code>static/brain.html</code> hoch.</p>
    """, status_code=404)

@app.get("/landing", response_class=HTMLResponse)
@app.get("/landing/", response_class=HTMLResponse)
async def jobqueen_landing():
    f = Path(__file__).parent / "templates" / "landing.html"
    if f.exists():
        return HTMLResponse(f.read_text(encoding="utf-8"))
    return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:50px;'>landing.html fehlt in templates/</h1>", status_code=404)


@app.get("/landme", response_class=HTMLResponse)
@app.get("/landme/", response_class=HTMLResponse)
async def fm_landing_page():
    """Filip Makarczyk Hybrid Property Management & AI Expert Landing Page"""
    f = Path(__file__).parent / "templates" / "fm_landing.html"
    if f.exists():
        return HTMLResponse(f.read_text(encoding="utf-8"))
    return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:50px;'>fm_landing.html fehlt in templates/</h1>", status_code=404)


@app.get("/starter", response_class=HTMLResponse)
@app.get("/starter/", response_class=HTMLResponse)
async def jobqueen_starter():
    f = Path(__file__).parent / "templates" / "starter.html"
    if f.exists():
        return HTMLResponse(f.read_text(encoding="utf-8"))
    return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:50px;'>starter.html fehlt in templates/</h1>", status_code=404)



@app.get("/")
async def root():
    return {
        "status": "online",
        "bot": "Telllmeeedrei_BOT",
        "version": "3.0.2",
        "features": ["telegram", "superskill", "brain", "20+ mini-apps"],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/ping")
async def ping():
    return {"status": "alive"}


@app.get("/health")
async def health_check():
    brain_ok = brain_enabled()
    groq_ok = bool(GROQ_API_KEY)
    telegram_ok = bool(TELEGRAM_TOKEN)
    app_running = getattr(application, "_running", False) if application else False
    return {
        "status": "healthy" if all([brain_ok, groq_ok, telegram_ok, app_running]) else "degraded",
        "services": {
            "telegram": "ok" if telegram_ok else "missing_token",
            "groq": "ok" if groq_ok else "missing_key",
            "brain": "ok" if brain_ok else "disabled",
            "superskill": "ok",
            "bot_running": "ok" if app_running else "not_running",
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/status")
async def status():
    try:
        if application:
            webhook_info = await application.bot.get_webhook_info()
            webhook_url = webhook_info.url
        else:
            webhook_url = "no_app"
    except Exception:
        webhook_url = "error"
    return {
        "bot_mode": "webhook" if USE_WEBHOOK else "polling",
        "polling_task_running": _polling_task is not None and not _polling_task.done(),
        "watchdog_task_running": _watchdog_task is not None and not _watchdog_task.done(),
        "last_update_offset": _load_offset(),
        "webhook_set": bool(webhook_url),
        "webhook_url": webhook_url,
        "use_webhook_env": os.getenv("USE_WEBHOOK", "false"),
        "app_initialized": getattr(application, "_initialized", False) if application else False,
        "app_running": getattr(application, "_running", False) if application else False,
        "bot_initialized": getattr(application.bot, "_initialized", False) if application else False,
    }


@app.get("/dashboard")
async def dashboard_info():
    return {
        "dashboard": "streamlit run dashboard.py --server.port 8501 --server.headless true",
        "features": "100+ params, model/prompt edit, sandbox tester, superagent list",
        "streamlit": "Ready in requirements.txt"
    }


# ── Self-Keepalive (Render/Railway Free-Tier Wake-Up) ────────────────────────
async def _self_keepalive():
    """Pingt den eigenen /ping-Endpoint alle ~4 Minuten (Wake-Up Fix)."""
    await asyncio.sleep(30)

    port = int(os.getenv("PORT", "7860"))
    possible_urls = []
    if WEBHOOK_URL:
        possible_urls.append(f"{WEBHOOK_URL}/ping")
    if os.getenv("RENDER_EXTERNAL_URL"):
        possible_urls.append(f"{os.getenv('RENDER_EXTERNAL_URL').rstrip('/')}/ping")
    possible_urls.append(f"http://localhost:{port}/ping")

    logger.info("💓 Self-Keepalive startet mit URLs: %s", possible_urls)

    while True:
        success = False
        for url in possible_urls:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        success = True
                        break
            except Exception:
                continue

        if not success:
            logger.warning("⚠️ Self-Keepalive: Keine URL erreichbar")

        await asyncio.sleep(240)

# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINT – ROBUST MIT LOGGING
# ═══════════════════════════════════════════════════════════════════════════════


_pending_webhook_updates: list = []
_recent_webhook_update_ids: Dict[int, float] = {}
_recent_webhook_ttl_seconds = 15 * 60
_recent_webhook_max_ids = 5000
_recent_webhook_last_cleanup = 0.0


def _remember_update_id(update_id: Optional[int]) -> bool:
    global _recent_webhook_last_cleanup
    if update_id is None:
        return True
    now = asyncio.get_running_loop().time()
    expiry = now - _recent_webhook_ttl_seconds
    if (now - _recent_webhook_last_cleanup > 60.0) or (len(_recent_webhook_update_ids) > _recent_webhook_max_ids):
        stale_ids = [uid for uid, ts in _recent_webhook_update_ids.items() if ts < expiry]
        for uid in stale_ids:
            _recent_webhook_update_ids.pop(uid, None)
        _recent_webhook_last_cleanup = now
    if update_id in _recent_webhook_update_ids:
        return False
    _recent_webhook_update_ids[update_id] = now
    return True


async def _enqueue_telegram_update(data: dict):
    update_id = data.get("update_id")
    if isinstance(update_id, int) and not _remember_update_id(update_id):
        logger.info("Webhook Duplicate ignoriert (update_id=%s)", update_id)
        return
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)


async def _replay_pending_updates():
    if not _pending_webhook_updates:
        return
    logger.info(f"Replay {len(_pending_webhook_updates)} gepufferte Updates...")
    try:
        for data in list(_pending_webhook_updates):
            try:
                await _enqueue_telegram_update(data)
            except Exception as e:
                logger.warning(f"Replay Update Fehler: {e}")
    finally:
        _pending_webhook_updates.clear()


@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """Robuster Webhook Endpoint mit Logging und Buffer-Logik."""
    try:
        data = await request.json()
        update_id = data.get("update_id")

        logger.info(f"📥 Webhook erhalten | update_id={update_id}")

        if not application or not getattr(application, "_running", False):
            logger.warning(f"Bot noch nicht bereit → Update gepuffert (update_id={update_id})")
            _pending_webhook_updates.append(data)
            if len(_pending_webhook_updates) > 50:
                _pending_webhook_updates.pop(0)

            # Versuche Bot zu initialisieren falls noch nicht gestartet
            if application and not _init_lock.locked():
                async def _init_and_replay():
                    ok = await fast_init_bot()
                    if ok and USE_WEBHOOK and WEBHOOK_URL:
                        await _set_webhook()
                    await _replay_pending_updates()
                asyncio.create_task(_init_and_replay())

            return {"ok": True}

        # Update verarbeiten
        await _enqueue_telegram_update(data)
        logger.debug(f"✅ Update verarbeitet: update_id={update_id}")

        # Falls es gepufferte Updates gibt, diese auch abarbeiten
        if _pending_webhook_updates:
            asyncio.create_task(_replay_pending_updates())

        return {"ok": True}

    except Exception as e:
        logger.error(f"❌ Webhook-Verarbeitungsfehler: {e}", exc_info=True)
        return {"ok": True}  # Immer 200 zurückgeben!


# ── JobQueen Landing & Starter Pages ───────────────────────────────────────

# NOTE: JobQueen Web-Frontend (templates/landing.html, templates/starter.html)
# nutzt einen echten LLM-Chat über /api/jobqueen/chat.


# ─── Bundesagentur für Arbeit – Echte Stellensuche (kein eigener Key) ─────────

def _ba_parse_query(query: str, explicit_location: str = "") -> tuple[str, str]:
    """
    Trennt 'was' und 'wo' aus einer kombinierten Suchanfrage.
    Beispiel: 'Python Entwickler Berlin' → ('Python Entwickler', 'Berlin')
    Gibt (was, wo) zurück. explicit_location hat immer Vorrang.
    """
    if explicit_location:
        return query.strip(), explicit_location.strip()

    # Bekannte deutsche Städte / Bundesländer am Ende der Query
    known_cities = [
        "Berlin", "Hamburg", "München", "Köln", "Frankfurt", "Stuttgart", "Düsseldorf",
        "Leipzig", "Dortmund", "Essen", "Bremen", "Dresden", "Hannover", "Nürnberg",
        "Duisburg", "Bochum", "Wuppertal", "Bielefeld", "Bonn", "Münster", "Karlsruhe",
        "Mannheim", "Augsburg", "Wiesbaden", "Gelsenkirchen", "Mönchengladbach",
        "Braunschweig", "Kiel", "Chemnitz", "Aachen", "Halle", "Magdeburg", "Freiburg",
        "Krefeld", "Lübeck", "Oberhausen", "Erfurt", "Mainz", "Rostock", "Kassel",
        "Hagen", "Hamm", "Saarbrücken", "Mülheim", "Potsdam", "Ludwigshafen",
        "Oldenburg", "Osnabrück", "Leverkusen", "Solingen", "Heidelberg", "Darmstadt",
        "Regensburg", "Ingolstadt", "Würzburg", "Ulm", "Wolfsburg", "Heilbronn",
        "Pforzheim", "Göttingen", "Offenbach", "Bottrop", "Recklinghausen", "Bremerhaven",
        "Remscheid", "Fürth", "Reutlingen", "Koblenz", "Bergisch Gladbach", "Erlangen",
        "Moers", "Siegen", "Hildesheim", "Salzgitter", "Cottbus", "Kaiserslautern",
        "Trier", "Jena", "Gütersloh", "Gera", "Düren", "Iserlohn", "Schwerin",
        "Deutschland", "Remote", "Homeoffice", "bundesweit", "ganz Deutschland",
        # Österreich & Schweiz
        "Wien", "Graz", "Linz", "Salzburg", "Innsbruck", "Zürich", "Bern", "Basel",
        "Genf", "Lausanne",
    ]

    q_lower = query.strip().lower()
    for city in known_cities:
        city_lower = city.lower()
        # Am Ende der Query: "Python Berlin" oder "Python in Berlin"
        if q_lower.endswith(f" {city_lower}"):
            was = query[: -(len(city) + 1)].strip()
            return (was or query.strip()), city
        if q_lower.endswith(f" in {city_lower}"):
            was = query[: -(len(city) + 4)].strip()
            return (was or query.strip()), city

    # Kein Ort gefunden – gesamte Query als Berufsbezeichnung
    return query.strip(), ""


async def search_jobs_bundesagentur(query: str, location: str = "", count: int = 20) -> list[dict]:
    """
    Echte Stellenangebote der Bundesagentur für Arbeit.
    Nutzt öffentlichen API-Key (kein eigener Key nötig).
    Versucht zuerst X-API-Key, dann OAuth als Fallback.
    Deep-URL: https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}
    """
    was, wo = _ba_parse_query(query, explicit_location=location)
    logger.info("BA-API Suche: was='%s', wo='%s'", was, wo)

    # Endpunkte in Prioritätsreihenfolge
    ENDPOINTS = [
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/app/jobs",
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs",
    ]

    # Methode 1: Simpler öffentlicher API-Key (bevorzugt, kein OAuth nötig)
    headers_apikey = {
        "X-API-Key":  "jobboerse-jobsuche",
        "Accept":     "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    params: dict = {
        "was":        was,
        "size":       min(count, 25),
        "page":       1,
        "angebotsart": "1",
        "pav":        "false",
        "veroeffentlichtseit": 30,
    }
    if wo:
        params["wo"]      = wo
        params["umkreis"] = 50

    async with httpx.AsyncClient(timeout=20.0, limits=HTTPX_LIMITS) as client:
        # Versuche X-API-Key auf allen Endpunkten
        resp = None
        last_exc = None
        for endpoint in ENDPOINTS:
            try:
                r = await client.get(endpoint, params=params, headers=headers_apikey)
                if r.status_code == 200:
                    resp = r
                    logger.info("BA-API: Endpunkt OK: %s", endpoint)
                    break
                logger.debug("BA-API: %s → HTTP %d", endpoint, r.status_code)
            except Exception as exc:
                last_exc = exc
                logger.debug("BA-API: %s → %s", endpoint, exc)
                continue

        # Fallback: OAuth-Token
        if resp is None:
            logger.info("BA-API: X-API-Key fehlgeschlagen, versuche OAuth-Fallback")
            try:
                oauth_resp = await client.post(
                    "https://rest.arbeitsagentur.de/oauth/token",
                    data={
                        "client_id":     "c003a37f-024f-462a-b36d-b001be4cd24a",
                        "client_secret": "32a39620-32b3-4307-9aa1-511527befebb",
                        "grant_type":    "client_credentials",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                if oauth_resp.status_code == 200:
                    token = oauth_resp.json().get("access_token")
                    if token:
                        headers_oauth = {
                            "Authorization": f"Bearer {token}",
                            "Accept":        "application/json",
                            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        }
                        for endpoint in ENDPOINTS:
                            try:
                                r = await client.get(endpoint, params=params, headers=headers_oauth)
                                if r.status_code == 200:
                                    resp = r
                                    logger.info("BA-API OAuth-Fallback OK: %s", endpoint)
                                    break
                            except Exception:
                                continue
            except Exception as exc:
                logger.warning("BA-API OAuth-Fallback fehlgeschlagen: %s", exc)

        if resp is None:
            logger.warning("BA-API: Alle Endpunkte nicht erreichbar. Letzter Fehler: %s", last_exc)
            return []

    data = resp.json()
    jobs: list[dict] = []
    for item in (data.get("stellenangebote") or []):
        refnr = str(item.get("refnr") or "").strip()
        if not refnr:
            continue
        # Echte Deep-URL zur Stellenanzeige
        deep_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
        ort_info = item.get("arbeitsort") or {}
        plz  = ort_info.get("plz") or ""
        ort  = ort_info.get("ort") or ""
        location_str = f"{plz} {ort}".strip() if plz else ort
        pub_date = item.get("aktuelleVeroeffentlichungsdatum") or ""
        jobs.append({
            "id":                  refnr,
            "title":               (item.get("titel") or "").strip(),
            "company":             (item.get("arbeitgeber") or "").strip(),
            "location":            location_str,
            "url":                 deep_url,
            "description_snippet": (item.get("kurzbeschreibung") or "")[:400],
            "date":                pub_date,
            "source":              "Bundesagentur für Arbeit",
        })
    logger.info("BA-API: %d echte Stellen für '%s' in '%s'", len(jobs), was, wo or "DE")
    return jobs




# ─── Session-Storage für Excel-Downloads ──────────────────────────────────────
import uuid as _uuid
_excel_sessions: dict = {}   # token → bytes

def _trim_excel_sessions(max_entries: int = 20) -> None:
    while len(_excel_sessions) > max_entries:
        _excel_sessions.pop(next(iter(_excel_sessions)))


# ─── Plattform-Job-Suche ──────────────────────────────────────────────────────

# Mehrere realistische Browser-User-Agents zur Rotation (reduziert Blocking-Quote)
_SCRAPE_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

def _scrape_headers(extra: dict | None = None) -> dict:
    """Realistische, rotierende Browser-Header für Scraping-Requests."""
    import random as _random
    h = {
        "User-Agent":      _random.choice(_SCRAPE_USER_AGENTS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control":   "no-cache",
        "Pragma":          "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "none",
    }
    if extra:
        h.update(extra)
    return h


async def _scrape_get(url: str, *, headers: dict | None = None, timeout: float = 18.0,
                       retries: int = 2, source: str = ""):
    """
    GET mit Retry + Header-Rotation + ausführlichem Logging.
    Loggt bei Fehlschlag klar, WARUM es fehlschlug (Status, Blocking-Verdacht, Timeout),
    damit man in den Logs sofort Blocking von kaputtem Parsing unterscheiden kann.
    """
    last_status = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.get(url, headers=headers or _scrape_headers())
            last_status = r.status_code
            if r.status_code == 200:
                # Grobe Bot-Wall-Erkennung (Cloudflare/DataDome/Login-Redirect etc.)
                low = r.text[:2000].lower()
                if any(sig in low for sig in ("captcha", "access denied", "just a moment",
                                               "cf-browser-verification", "attention required",
                                               "verify you are human", "/authwall")):
                    logger.warning("%s: Bot-Schutz/Login-Wall erkannt trotz HTTP 200 (Versuch %d/%d) – %s",
                                   source, attempt, retries, url)
                else:
                    return r
            elif r.status_code in (403, 429, 999):
                logger.warning("%s: HTTP %d (Blocking wahrscheinlich, Versuch %d/%d) – %s",
                               source, r.status_code, attempt, retries, url)
            else:
                logger.warning("%s: HTTP %d (Versuch %d/%d) – %s", source, r.status_code, attempt, retries, url)
        except Exception as exc:
            logger.warning("%s: Request-Fehler (Versuch %d/%d): %s", source, attempt, retries, exc)
        if attempt < retries:
            await asyncio.sleep(0.8 * attempt)
    logger.warning("%s: alle %d Versuche fehlgeschlagen (letzter Status: %s)", source, retries, last_status)
    return None


def _extract_jobposting_jsonld(html: str, source_name: str, fallback_location: str, count: int) -> list[dict]:
    """
    Generischer Parser für eingebettete schema.org/JobPosting JSON-LD-Blöcke.
    Viele Jobbörsen (StepStone, Indeed, Jobvector, XING u.a.) betten diese für SEO
    ein, unabhängig vom JS-Rendering – deutlich robuster als Framework-spezifisches
    HTML-Scraping, weil sich das Layout ändern kann, das SEO-Markup aber selten.
    """
    import json as _json
    jobs: list[dict] = []
    for ld_str in _re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, _re.S):
        try:
            ld = _json.loads(ld_str.strip())
        except Exception:
            continue
        items = ld if isinstance(ld, list) else [ld]
        # @graph-Wrapper auflösen (z.B. { "@graph": [ {...}, {...} ] })
        flat: list = []
        for obj in items:
            if isinstance(obj, dict) and isinstance(obj.get("@graph"), list):
                flat.extend(obj["@graph"])
            else:
                flat.append(obj)
        for obj in flat:
            if not isinstance(obj, dict) or obj.get("@type") not in ("JobPosting", "JobListing"):
                continue
            title   = (obj.get("title") or obj.get("name") or "").strip()
            if not title:
                continue
            org     = obj.get("hiringOrganization") or {}
            company = (org.get("name") if isinstance(org, dict) else str(org)) or ""
            loc_obj = obj.get("jobLocation") or {}
            if isinstance(loc_obj, list):
                loc_obj = loc_obj[0] if loc_obj else {}
            loc_str = fallback_location
            if isinstance(loc_obj, dict):
                addr = loc_obj.get("address") or {}
                if isinstance(addr, dict):
                    loc_str = (addr.get("addressLocality") or addr.get("addressRegion")
                               or fallback_location)
            job_url  = obj.get("url") or obj.get("mainEntityOfPage") or ""
            if isinstance(job_url, dict):
                job_url = job_url.get("@id") or ""
            date_str = (obj.get("datePosted") or "")[:10]
            desc     = _re.sub(r"<[^>]+>", " ", str(obj.get("description") or "")).strip()[:400]
            jobs.append({
                "id":                  (job_url[-24:] if job_url else str(len(jobs))),
                "title":               title,
                "company":             company,
                "location":            loc_str,
                "url":                 job_url,
                "description_snippet": desc,
                "date":                date_str,
                "source":              source_name,
            })
            if len(jobs) >= count:
                return jobs
    return jobs


async def _search_indeed_rss(query: str, location: str, count: int) -> list[dict]:
    """
    Holt Jobs von Indeed Deutschland.

    Indeeds öffentliche RSS-Feeds waren in der Vergangenheit wiederholt zeitweise
    abgeschaltet/instabil (Indeed baut Feed-Zugriff aktiv zurück, siehe deren
    Umstellung auf ATS-Integrationen). Deshalb: RSS zuerst versuchen, bei leerem
    Ergebnis oder Fehler auf die normale Suchseite + JSON-LD zurückfallen.
    """
    from urllib.parse import quote_plus
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as _ET

    q   = quote_plus(query)
    loc = quote_plus(location) if location else ""
    rss_url = (f"https://de.indeed.com/rss?q={q}&sort=date&fromage=30&limit={min(count,25)}"
               + (f"&l={loc}" if loc else ""))

    jobs: list[dict] = []
    r = await _scrape_get(rss_url, headers=_scrape_headers({"Accept": "application/rss+xml, application/xml, text/xml, */*"}),
                           timeout=15.0, retries=2, source="Indeed RSS")
    if r is not None:
        try:
            root    = _ET.fromstring(r.text)
            channel = root.find("channel")
            for item in (channel.findall("item")[:count] if channel is not None else []):
                raw_title = (item.findtext("title") or "").strip()
                link      = (item.findtext("link")  or "").strip()
                desc_raw  = (item.findtext("description") or "").strip()
                pub_date  = (item.findtext("pubDate") or "").strip()
                src_el    = item.find("source")
                company   = (src_el.text or "").strip() if src_el is not None else ""

                title = raw_title
                if not company and " - " in raw_title:
                    parts   = raw_title.rsplit(" - ", 1)
                    title   = parts[0].strip()
                    company = parts[1].strip()

                parsed_date = ""
                if pub_date:
                    try:
                        parsed_date = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
                    except Exception:
                        parsed_date = pub_date

                desc = _re.sub(r"<[^>]+>", " ", desc_raw).strip()[:400]

                jobs.append({
                    "id":                  (link.split("jk=")[1][:16] if "jk=" in link else link[-20:]),
                    "title":               title,
                    "company":             company,
                    "location":            location or "Deutschland",
                    "url":                 link,
                    "description_snippet": desc,
                    "date":                parsed_date,
                    "source":              "Indeed",
                })
        except _ET.ParseError as exc:
            logger.warning("Indeed RSS: XML nicht parsebar (evtl. HTML-Fehlerseite statt Feed): %s", exc)

    if jobs:
        logger.info("Indeed via RSS: %d Jobs für '%s'", len(jobs), query)
        return jobs

    # ── Fallback: normale Suchseite (live verifiziert, funktioniert ohne Login) ──
    logger.info("Indeed RSS leer/nicht verfügbar – versuche Suchseite als Fallback für '%s'", query)
    search_url = f"https://de.indeed.com/jobs?q={q}" + (f"&l={loc}" if loc else "") + "&sort=date"
    r2 = await _scrape_get(search_url, headers=_scrape_headers({"Referer": "https://de.indeed.com/"}),
                            timeout=18.0, retries=2, source="Indeed Suchseite")
    if r2 is None:
        return []
    html2 = r2.text

    # 1) JSON-LD probieren (falls Indeed es mal einbettet)
    jobs = _extract_jobposting_jsonld(html2, "Indeed", location or "Deutschland", count)
    if jobs:
        logger.info("Indeed via JSON-LD-Fallback: %d Jobs für '%s'", len(jobs), query)
        return jobs

    # 2) HTML-Fallback: jede Jobkarte trägt stabil data-jk="<jobkey>" (seit Jahren
    #    unverändertes Indeed-Attribut, unabhängig vom sonstigen Markup/CSS).
    seen_jk: set[str] = set()
    for m in _re.finditer(r'data-jk="([a-f0-9]{10,20})"', html2):
        jk = m.group(1)
        if jk in seen_jk:
            continue
        seen_jk.add(jk)
        # Umfeld der Jobkarte durchsuchen (nächste ~2500 Zeichen nach dem Treffer)
        window = html2[m.start(): m.start() + 2500]

        title_m = (_re.search(r'jobTitle[^>]*>\s*<a[^>]*>\s*<span[^>]*>(?P<t>.*?)</span>', window, _re.S)
                   or _re.search(r'<h2[^>]*jobTitle[^>]*>.*?>(?P<t>[^<>]{4,120})<', window, _re.S)
                   or _re.search(r'aria-label="(?P<t>[^"]{4,120})"', window))
        title = _re.sub(r"<[^>]+>", "", title_m.group("t")).strip() if title_m else ""
        if not title:
            continue

        comp_m = _re.search(r'companyName[^>]*>(?:<[^>]+>)?\s*(?P<c>[^<>]{2,80})<', window, _re.S)
        company = comp_m.group("c").strip() if comp_m else ""

        loc_m = _re.search(r'companyLocation[^>]*>\s*(?P<l>[^<>]{2,80})<', window, _re.S)
        loc_str = loc_m.group("l").strip() if loc_m else (location or "Deutschland")

        snip_m = _re.search(r'(?:job-snippet|underShelfFooter)[^>]*>(?P<s>.*?)</(?:div|ul)>', window, _re.S)
        snippet = _re.sub(r"<[^>]+>", " ", snip_m.group("s")).strip()[:400] if snip_m else ""

        jobs.append({
            "id":                  jk,
            "title":               title,
            "company":             company,
            "location":            loc_str,
            "url":                 f"https://de.indeed.com/viewjob?jk={jk}",
            "description_snippet": snippet,
            "date":                "",
            "source":              "Indeed",
        })
        if len(jobs) >= count:
            break

    if jobs:
        logger.info("Indeed via HTML-Fallback (data-jk): %d Jobs für '%s'", len(jobs), query)
        return jobs

    low = html2.lower()
    if "captcha" in low or "cf-browser-verification" in low:
        logger.warning("Indeed: Bot-Schutz-Seite erhalten statt Ergebnissen für '%s'", query)
    else:
        logger.info("Indeed: Suchseite geladen, aber kein Treffer-Muster gefunden (Layout evtl. geändert) – '%s'",
                    query)
    return []


async def _search_stepstone(query: str, location: str, count: int) -> list[dict]:
    """
    Holt Jobs von StepStone.

    WICHTIG: Die alte URL-Struktur https://www.stepstone.de/work/{q}/{loc}.html
    existiert nicht mehr (StepStone hat auf https://www.stepstone.de/jobs/{suchbegriff}
    umgestellt, optional gefolgt von /in-{ort} für eine Ortsfilterung). Mit der alten
    URL bekam der alte Code vermutlich dauerhaft einen 404/Redirect und damit []
    zurück – das war der Hauptgrund, warum StepStone nie echte Treffer lieferte.

    Extraktion in zwei Stufen:
      1) schema.org/JobPosting JSON-LD (SEO-Markup, unabhängig vom UI-Framework)
      2) HTML-Regex-Fallback auf die serverseitig gerenderte Treffer-Liste
         (Job-Titel als <h2><a>, davor der Firmen-Link, Ort, "vor X Tage(n)")
    """
    from urllib.parse import quote_plus

    q   = quote_plus(query.strip())
    url = f"https://www.stepstone.de/jobs/{q}"
    if location:
        url += f"/in-{quote_plus(location.strip())}"

    r = await _scrape_get(url, headers=_scrape_headers({"Referer": "https://www.stepstone.de/"}),
                           timeout=18.0, retries=2, source="StepStone")
    if r is None:
        return []
    html = r.text

    # ── 1) JSON-LD (bevorzugt: stabile, strukturierte Daten) ──────────────────
    jobs = _extract_jobposting_jsonld(html, "StepStone", location or "Deutschland", count)
    for j in jobs:
        if j["url"] and not j["url"].startswith("http"):
            j["url"] = "https://www.stepstone.de" + j["url"]
    if jobs:
        logger.info("StepStone via JSON-LD: %d Jobs für '%s'", len(jobs), query)
        return jobs

    # ── 2) HTML-Fallback: Treffer-Karten direkt aus der Ergebnisliste ─────────
    # Muster (live verifiziert): Firmenlink, dann "## [Titel](.../stellenangebote--...html)",
    # danach Firmenname als Klartext, Ort, optional "vor X Tage(n)".
    pattern = (
        r'<h2[^>]*>\s*<a[^>]+href="(?P<url>/stellenangebote--[^"]+\.html)"[^>]*>'
        r'\s*(?P<title>.*?)\s*</a>\s*</h2>'
    )
    matches = list(_re.finditer(pattern, html, _re.S))
    for m in matches[:count]:
        job_url = "https://www.stepstone.de" + m.group("url")
        title   = _re.sub(r"<[^>]+>", "", m.group("title")).strip()
        if not title:
            continue
        # Firmenname/Ort liegen im HTML kurz nach dem Titel-Block; wir greifen uns
        # das nächste Textfragment nach dem Match als grobe Näherung.
        tail = html[m.end(): m.end() + 600]
        comp_m = _re.search(r'>([^<>]{2,80})</a>\s*(?:</div>|<span)', tail)
        company = comp_m.group(1).strip() if comp_m else ""
        date_m = _re.search(r'vor\s+(\d+)\s+(Tag|Tage|Woche|Wochen|Stunde|Stunden)', tail)
        rel_date = f"vor {date_m.group(1)} {date_m.group(2)}" if date_m else ""
        jobs.append({
            "id":                  m.group("url")[-24:],
            "title":               title,
            "company":             company,
            "location":            location or "Deutschland",
            "url":                 job_url,
            "description_snippet": "",
            "date":                rel_date,
            "source":              "StepStone",
        })

    if not jobs:
        low = html.lower()
        if "captcha" in low or "cf-browser-verification" in low:
            logger.warning("StepStone: Bot-Schutz-Seite erhalten statt Ergebnissen für '%s'", query)
        else:
            logger.info("StepStone: HTML erhalten, aber kein Treffer-Muster gefunden (Layout evtl. geändert) – '%s'",
                        query)
    else:
        logger.info("StepStone via HTML-Fallback: %d Jobs für '%s'", len(jobs), query)
    return jobs


async def _search_jobvector_rss(query: str, location: str, count: int) -> list[dict]:
    """Jobvector RSS-Feed."""
    from urllib.parse import quote_plus
    import xml.etree.ElementTree as _ET
    from email.utils import parsedate_to_datetime

    q   = quote_plus(query)
    loc = quote_plus(location) if location else ""
    url = f"https://www.jobvector.de/jobs/rss/?q={q}" + (f"&location={loc}" if loc else "")
    try:
        r = await _scrape_get(url, headers=_scrape_headers({"Accept": "application/rss+xml, */*"}),
                               timeout=12.0, retries=2, source="Jobvector RSS")
        if r is None:
            return []
        root    = _ET.fromstring(r.text)
        channel = root.find("channel")
        if channel is None:
            logger.info("Jobvector RSS: kein <channel> im Feed (evtl. leeres Suchergebnis) – '%s'", query)
            return []
        jobs: list[dict] = []
        for item in channel.findall("item")[:count]:
            title    = (item.findtext("title") or "").strip()
            link     = (item.findtext("link")  or "").strip()
            desc_raw = (item.findtext("description") or "").strip()
            pub      = (item.findtext("pubDate") or "").strip()
            company  = ""
            for ns in ["", "{http://purl.org/dc/elements/1.1/}"]:
                c = item.findtext(f"{ns}creator")
                if c:
                    company = c.strip()
                    break
            parsed_date = ""
            if pub:
                try:
                    parsed_date = parsedate_to_datetime(pub).strftime("%Y-%m-%d")
                except Exception:
                    parsed_date = pub
            desc = _re.sub(r"<[^>]+>", " ", desc_raw).strip()[:400]
            jobs.append({
                "id": link[-20:], "title": title, "company": company,
                "location": location or "Deutschland", "url": link,
                "description_snippet": desc, "date": parsed_date, "source": "Jobvector",
            })
        logger.info("Jobvector RSS: %d Jobs für '%s'", len(jobs), query)
        return jobs
    except Exception as exc:
        logger.warning("Jobvector RSS Fehler: %s", exc)
        return []



async def _search_linkedin(query: str, location: str, count: int) -> list[dict]:
    """
    LinkedIn-Jobs via öffentlicher Guest-API (kein Login nötig).
    Endpunkt: /jobs-guest/jobs/api/seeMoreJobPostings/search
    f_TPR=r2592000  → letzte 30 Tage
    """
    from urllib.parse import quote_plus
    q   = quote_plus(query)
    loc = quote_plus(location or "Deutschland")
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={q}&location={loc}"
        "&f_TPR=r2592000"           # 30 Tage
        f"&count={min(count, 25)}"
        "&start=0&sortBy=DD"
    )
    try:
        r = await _scrape_get(
            url,
            headers=_scrape_headers({
                "Accept":  "text/html,application/xhtml+xml,*/*;q=0.9",
                "Referer": "https://www.linkedin.com/jobs/search/",
            }),
            timeout=22.0, retries=2, source="LinkedIn",
        )
        if r is None:
            return []
        html = r.text

        # ── HTML-Karten parsen ──────────────────────────────────────────────
        # Jedes Job-Item: data-entity-urn → Stellenangebots-ID
        # Reihenfolge: URN / URL / Titel / Firma / Ort / Datum
        pattern = (
            r'data-entity-urn="urn:li:jobPosting:(\d+)"'
            r'.*?href="(https://www\.linkedin\.com/jobs/view/[^"?&]+)[^"]*"'
            r'.*?class="[^"]*base-search-card__title[^"]*"[^>]*>\s*(.*?)\s*</h3>'
            r'.*?class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*(.*?)\s*</h4>'
            r'.*?class="[^"]*job-search-card__location[^"]*"[^>]*>\s*(.*?)\s*</span>'
            r'.*?datetime="([^"]*)"'
        )
        matches = _re.findall(pattern, html, _re.S)

        # Fallback-Pattern (ältere Markup-Variante ohne data-entity-urn)
        if not matches:
            pattern2 = (
                r'href="(https://www\.linkedin\.com/jobs/view/[^"?&]+)[^"]*"[^>]*>'
                r'.*?class="[^"]*base-search-card__title[^"]*"[^>]*>\s*(.*?)\s*</h3>'
                r'.*?class="[^"]*base-search-card__subtitle[^"]*"[^>]*>\s*(.*?)\s*</h4>'
                r'.*?class="[^"]*job-search-card__location[^"]*"[^>]*>\s*(.*?)\s*</span>'
                r'.*?datetime="([^"]*)"'
            )
            matches2 = _re.findall(pattern2, html, _re.S)
            for i, (link, t, c, l, d) in enumerate(matches2[:count]):
                matches.append((str(i), link, t, c, l, d))

        jobs: list[dict] = []
        seen_ids: set[str] = set()
        for job_id, link, title_r, company_r, loc_r, date_str in matches[:count]:
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            title   = _re.sub(r"<[^>]+>", "", title_r).strip()
            company = _re.sub(r"<[^>]+>", "", company_r).strip()
            loc_str = _re.sub(r"<[^>]+>", "", loc_r).strip()
            if not title:
                continue
            jobs.append({
                "id":                  job_id,
                "title":               title,
                "company":             company,
                "location":            loc_str or location,
                "url":                 link,
                "description_snippet": "",
                "date":                date_str,
                "source":              "LinkedIn",
            })

        logger.info("LinkedIn: %d Jobs für '%s' in '%s'", len(jobs), query, location)
        return jobs
    except Exception as exc:
        logger.warning("LinkedIn Scraper Fehler: %s", exc)
        return []


async def _search_xing(query: str, location: str, count: int) -> list[dict]:
    """
    XING-Jobs via Suchseiten-Scraping.
    Versucht Next.js __NEXT_DATA__ sowie JSON-LD; Fallback: HTML-Pattern.
    """
    from urllib.parse import quote_plus
    import json as _json

    q   = quote_plus(query)
    loc = quote_plus(location or "")
    # Öffentliche (nicht-Login) Suchseite
    url = f"https://www.xing.com/jobs/search?keywords={q}&location={loc}&sort=date"
    try:
        r = await _scrape_get(
            url,
            headers=_scrape_headers({
                "Accept":  "text/html,application/xhtml+xml,*/*",
                "Referer": "https://www.xing.com/",
            }),
            timeout=22.0, retries=2, source="XING",
        )
        if r is None:
            return []
        html = r.text

        # Zusätzlich: JSON-LD als weitere Quelle probieren (wird unten nur genutzt,
        # falls __NEXT_DATA__ und die alte JSON-LD-Schleife nichts liefern)
        _jsonld_jobs = _extract_jobposting_jsonld(html, "XING", location or "Deutschland", count)

        # ── 1) __NEXT_DATA__ (Next.js SSR) ─────────────────────────────────
        nd_m = _re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, _re.S)
        if nd_m:
            try:
                nd    = _json.loads(nd_m.group(1))
                props = nd.get("props", {}).get("pageProps", {})
                # XING-spezifische Datenpfade durchsuchen
                candidates = [
                    props.get("searchResult", {}).get("results"),
                    props.get("jobs",         {}).get("collection"),
                    props.get("initialData",  {}).get("jobSearchResults", {}).get("edges"),
                    props.get("data",         {}).get("jobs"),
                ]
                for raw_list in candidates:
                    if not isinstance(raw_list, list) or not raw_list:
                        continue
                    jobs: list[dict] = []
                    for item in raw_list[:count]:
                        node = item.get("node", item) if isinstance(item, dict) else {}
                        if not isinstance(node, dict):
                            continue
                        date_raw = node.get("publishedAt") or node.get("activatedAt") or ""
                        parsed_date = ""
                        if date_raw:
                            try:
                                from datetime import datetime as _dt2
                                parsed_date = _dt2.fromisoformat(date_raw[:10]).strftime("%Y-%m-%d")
                            except Exception:
                                pass
                        title       = node.get("title") or node.get("name") or ""
                        co_obj      = node.get("company") or {}
                        company     = (co_obj.get("name") if isinstance(co_obj, dict) else str(co_obj)) or ""
                        loc_obj     = node.get("location") or {}
                        loc_str     = (loc_obj.get("city") or loc_obj.get("text") or location) if isinstance(loc_obj, dict) else location
                        job_url     = node.get("url") or node.get("slug") or ""
                        if job_url and not job_url.startswith("http"):
                            job_url = "https://www.xing.com" + job_url
                        desc        = str(node.get("description") or node.get("summary") or "")[:400]
                        if title:
                            jobs.append({
                                "id": str(node.get("id") or len(jobs)), "title": title,
                                "company": company, "location": loc_str,
                                "url": job_url, "description_snippet": desc,
                                "date": parsed_date, "source": "XING",
                            })
                    if jobs:
                        logger.info("XING via __NEXT_DATA__: %d Jobs für '%s'", len(jobs), query)
                        return jobs
            except (_json.JSONDecodeError, KeyError):
                pass

        # ── 2) JSON-LD (strukturierte Daten) ───────────────────────────────
        for ld_str in _re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, _re.S):
            try:
                ld = _json.loads(ld_str)
                items = ld if isinstance(ld, list) else [ld]
                jobs_ld: list[dict] = []
                for obj in items:
                    if obj.get("@type") not in ("JobPosting", "JobListing"):
                        continue
                    title   = obj.get("title") or obj.get("name") or ""
                    company = (obj.get("hiringOrganization") or {}).get("name") or ""
                    loc_obj = obj.get("jobLocation") or {}
                    if isinstance(loc_obj, dict):
                        addr    = loc_obj.get("address") or {}
                        loc_str = (addr.get("addressLocality") or addr.get("addressRegion") or location) if isinstance(addr, dict) else location
                    else:
                        loc_str = location
                    date_str  = obj.get("datePosted") or ""
                    job_url   = obj.get("url") or ""
                    desc      = str(obj.get("description") or "")[:400]
                    if title:
                        jobs_ld.append({
                            "id": job_url[-20:] or str(len(jobs_ld)), "title": title,
                            "company": company, "location": loc_str,
                            "url": job_url, "description_snippet": _re.sub(r"<[^>]+>","",desc).strip(),
                            "date": date_str, "source": "XING",
                        })
                if jobs_ld:
                    logger.info("XING via JSON-LD: %d Jobs für '%s'", len(jobs_ld), query)
                    return jobs_ld[:count]
            except (_json.JSONDecodeError, AttributeError):
                pass

        # ── 3) HTML-Fallback ───────────────────────────────────────────────
        # XING rendert z.T. Server-seitig Karten mit data-* Attributen
        html_jobs: list[dict] = []
        for m in _re.finditer(
            r'<[^>]+data-job-id="([^"]+)"[^>]*>.*?'
            r'class="[^"]*job-title[^"]*"[^>]*>(.*?)</.*?'
            r'class="[^"]*company-name[^"]*"[^>]*>(.*?)</.*?'
            r'href="(/jobs/[^"?]+)"',
            html, _re.S
        ):
            jid, t, c, slug = m.groups()
            html_jobs.append({
                "id": jid, "title": _re.sub(r"<[^>]+>","",t).strip(),
                "company": _re.sub(r"<[^>]+>","",c).strip(),
                "location": location, "url": "https://www.xing.com" + slug,
                "description_snippet": "", "date": "", "source": "XING",
            })
        if html_jobs:
            logger.info("XING via HTML: %d Jobs", len(html_jobs))
            return html_jobs[:count]

        if _jsonld_jobs:
            logger.info("XING via generischem JSON-LD-Fallback: %d Jobs für '%s'", len(_jsonld_jobs), query)
            return _jsonld_jobs

        logger.info("XING: Keine Daten extrahiert (Login evtl. nötig oder Bot-Schutz aktiv) – '%s'", query)
        return []
    except Exception as exc:
        logger.warning("XING Scraper Fehler: %s", exc)
        return []


async def search_jobs_platform(query: str, location: str = "", platform: str = "all", count: int = 25) -> list[dict]:
    """Holt Stellen von der gewünschten Plattform. Fallback: Bundesagentur (klar gekennzeichnet)."""
    if platform in ("Arbeitsagentur", "Bundesagentur"):
        jobs = await search_jobs_bundesagentur(query, location=location, count=count)
        for j in jobs:
            j["source"] = "Bundesagentur für Arbeit"
        return jobs

    # Plattform-spezifische Scraper
    if platform == "Indeed":
        jobs = await _search_indeed_rss(query, location, count)
        if jobs:
            return jobs

    if platform == "StepStone":
        jobs = await _search_stepstone(query, location, count)
        if jobs:
            return jobs

    if platform == "Jobvector":
        jobs = await _search_jobvector_rss(query, location, count)
        if jobs:
            return jobs

    if platform == "LinkedIn":
        jobs = await _search_linkedin(query, location, count)
        if jobs:
            return jobs

    if platform == "XING":
        jobs = await _search_xing(query, location, count)
        if jobs:
            return jobs

    # Monster, Absolventa, Yourfirm, Green Jobs → kein öffentlicher Zugang
    if platform in ("Monster", "Absolventa", "Yourfirm", "Green Jobs"):
        return []

    # Allgemeiner Fallback – KEIN falsches Umlabeln mehr auf die angefragte
    # Plattform. Es sind echte BA-Jobs, das bleibt auch im Feld "source" so
    # sichtbar; "is_fallback" markiert für die UI, dass es keine Live-Treffer
    # von {platform} waren.
    logger.info("%s: keine Live-Treffer, zeige Bundesagentur-Ersatzergebnisse für '%s'", platform, query)
    jobs = await search_jobs_bundesagentur(query, location=location, count=count)
    for j in jobs:
        j["source"]      = "Bundesagentur für Arbeit"
        j["is_fallback"] = True
        j["requested_platform"] = platform
    return jobs


@app.post("/api/jobqueen/platform-jobs")
async def jobqueen_platform_jobs(request: Request):
    """Plattform-spezifische Jobsuche."""
    try:
        body     = await request.json()
        query    = (body.get("query") or "").strip()
        location = (body.get("location") or "").strip()
        platform = (body.get("platform") or "all").strip()
        chat_id  = (body.get("chat_id") or "jobqueen").strip() or "jobqueen"
        if not query:
            return JSONResponse({"error": "query fehlt"}, status_code=400)

        jobs = await search_jobs_platform(query, location=location, platform=platform, count=25)

        from bot_state import jobqueen_state
        jobqueen_state.setdefault(chat_id, {})
        idx  = jobqueen_state[chat_id].setdefault("jobs_index", {})
        jobqueen_state[chat_id].setdefault("query_history", []).append(
            {"query": query, "platform": platform, "location": location, "at": datetime.now().isoformat()}
        )
        for jb in jobs:
            key = (jb.get("url") or jb.get("id") or f"p-{len(idx)}").strip()
            idx[key] = jb

        is_fallback = bool(jobs) and all(j.get("is_fallback") for j in jobs)
        return JSONResponse({
            "jobs":            jobs,
            "total":           len(jobs),
            "platform":        platform,
            "source":          "Bundesagentur für Arbeit" if is_fallback else platform,
            "is_fallback":     is_fallback,
            "no_api":          len(jobs) == 0,
        })

    except Exception as e:
        logger.error("jobqueen_platform_jobs Fehler: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


@app.post("/api/jobqueen/jobs")
async def jobqueen_jobs(request: Request):
    """JobQueen Jobs Endpoint (Adzuna). Returns JSON for dynamic Kacheln."""
    try:
        data = await request.json()
        query = (data.get("query") or "").strip()
        chat_id = (data.get("chat_id") or "jobqueen").strip() or "jobqueen"

        # Ensure jobqueen_state layout exists
        from bot_state import jobqueen_state
        jobqueen_state.setdefault(chat_id, {})
        jobqueen_state[chat_id].setdefault("jobs_index", {})  # url_or_id -> job
        jobqueen_state[chat_id].setdefault("query_history", [])

        if not query:
            return JSONResponse({"error": "query fehlt"}, status_code=400)

        # Adzuna config
        ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
        ADZUNA_API_KEY = os.getenv("ADZUNA_API_KEY")
        ADZUNA_BASE = os.getenv("ADZUNA_BASE_URL", "https://api.adzuna.com/v1")
        if not ADZUNA_APP_ID or not ADZUNA_API_KEY:
            # ── Bundesagentur für Arbeit API – echte Stellen, kein eigener Key nötig ──
            # Ort kann explizit im Body mitgeschickt werden ODER wird aus der Query geparst
            location_hint = (data.get("location") or "").strip()
            ba_jobs = await search_jobs_bundesagentur(query, location=location_hint, count=25)

            idx = jobqueen_state[chat_id].setdefault("jobs_index", {})
            _now = datetime.now().isoformat()
            jobqueen_state[chat_id].setdefault("query_history", []).append({"query": query, "at": _now})
            for jb in ba_jobs:
                key = jb.get("url") or jb.get("id") or f"ba-{len(idx)}"
                idx[key] = jb

            if ba_jobs:
                return JSONResponse({"jobs": ba_jobs, "total": len(ba_jobs), "source": "bundesagentur"})

            # BA-API nicht erreichbar → leere Liste zurückgeben, KEIN LLM-Fallback
            logger.error("BA-API nicht erreichbar. Gebe leere Liste zurück (kein LLM-Fallback).")
            return JSONResponse({
                "jobs": [],
                "total": 0,
                "source": "bundesagentur",
                "hint": "Bundesagentur-API momentan nicht erreichbar. Bitte Jobbörsen-Links nutzen oder es später erneut versuchen.",
            })

        # region: default UK if nothing else; user can override via request
        country = (data.get("country") or os.getenv("ADZUNA_COUNTRY") or "de").lower()
        # Adzuna uses language/country codes differently; allow full URL passthrough
        # We'll rely on country slug in path as most typical: /{country}/search/
        per_page = int(data.get("limit") or 20)
        page = int(data.get("page") or 1)

        # Optional filters
        location = (data.get("location") or "").strip()
        contract = (data.get("contract_type") or "").strip()
        work_type = (data.get("job_type") or "").strip()

        params: dict[str, Any] = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_API_KEY,
            "what": query,
            "results": per_page,
            "page": page,
        }
        if location:
            params["where"] = location
        if contract:
            params["contract_type"] = contract
        if work_type:
            params["job_type"] = work_type

        url = f"{ADZUNA_BASE}/{country}/search/1"
        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient(timeout=20.0, limits=HTTPX_LIMITS) as client:
            resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()

        raw_jobs = payload.get("results") or []
        jobs = []
        for j in raw_jobs[:per_page]:
            # Adzuna: id kann fehlen, dann fallback auf redirect_url/url
            job_id = j.get("id")
            if job_id is None:
                job_id = j.get("redirect_url") or j.get("url") or ""

            url = j.get("redirect_url") or j.get("url") or ""
            jid = str(job_id or "")

            # Adzuna: company und location kommen als dict {display_name: ...}
            _company_raw = j.get("company")
            company_str = (
                _company_raw.get("display_name") or ""
                if isinstance(_company_raw, dict)
                else (str(_company_raw) if _company_raw else "")
            )
            _location_raw = j.get("location")
            location_str = (
                _location_raw.get("display_name") or ""
                if isinstance(_location_raw, dict)
                else (str(_location_raw) if _location_raw else "")
            )
            job_obj = {
                "id": jid,
                "title": j.get("title") or "",
                "company": company_str,
                "location": location_str,
                "url": url,
                "description_snippet": (j.get("description") or "")[:300],
            }

            jobs.append(job_obj)

        # Persist + dedupe across multiple searches within session
        from bot_state import jobqueen_state as _jqs
        idx: dict = _jqs[chat_id].setdefault("jobs_index", {})
        _now = datetime.now().isoformat()
        _jqs[chat_id].setdefault("query_history", []).append({"query": query, "at": _now})

        for jb in jobs:
            url_key = (jb.get("url") or "").strip()
            id_key = (str(jb.get("id") or "").strip())
            key = url_key or id_key
            # If both url and id missing: create unique key to avoid overwriting others
            if not key:
                key = f"no-url-no-id-{len(idx)}"
            idx[key] = jb


        return JSONResponse({"jobs": jobs})

    except Exception as e:
        logger.error(f"jobqueen_jobs Fehler: {e}", exc_info=True)
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


@app.post("/api/jobqueen/excel")
async def jobqueen_excel(request: Request):
    """
    JobQueen Export – sendet Excel, PDF und Markdown DIREKT in den Telegram-Chat.
    Kein Browser-Download, kein Session-State, kein Cloud-Run-Multi-Instance-Problem.
    Erwartet tg_chat_id (echte Telegram User/Chat-ID) vom Frontend.
    """
    try:
        body         = await request.json()
        query        = (body.get("query") or "Jobsuche").strip()
        chat_id      = (body.get("chat_id") or "jobqueen").strip() or "jobqueen"
        tg_chat_id   = body.get("tg_chat_id")          # Echte Telegram-Chat-ID
        jobs_raw     = body.get("jobs")
        selected_ids = body.get("selected_ids")
        all_queries  = body.get("all_queries") or []

        from bot_state import jobqueen_state
        jobqueen_state.setdefault(chat_id, {})
        idx: dict = jobqueen_state[chat_id].setdefault("jobs_index", {})

        if isinstance(jobs_raw, list):
            for jb in jobs_raw:
                if isinstance(jb, dict):
                    key = (jb.get("url") or jb.get("id") or f"no-key-{len(idx)}").strip()
                    idx[key] = jb

        jobs_to_export = list(idx.values())
        if isinstance(selected_ids, list) and selected_ids:
            sel_set        = set(str(s) for s in selected_ids if s)
            jobs_to_export = [j for j in jobs_to_export
                              if (j.get("url") or j.get("id") or "") in sel_set]

        if not jobs_to_export:
            return JSONResponse(
                {"error": "Keine Jobs zum Exportieren. Bitte zuerst suchen und Jobs auswaehlen."},
                status_code=400)

        if not all_queries:
            all_queries = [q.get("query", "")
                           for q in (jobqueen_state[chat_id].get("query_history") or [])
                           if q.get("query")]

        from dv import create_jobqueen_excel, create_jobqueen_pdf, create_jobqueen_markdown

        ed    = datetime.now().strftime("%d.%m.%Y %H:%M")
        today = datetime.now().strftime("%Y-%m-%d")

        # ── Dateien generieren ──────────────────────────────────────────────
        excel_buf = create_jobqueen_excel(jobs=jobs_to_export, queries=all_queries, export_date=ed)
        pdf_buf   = create_jobqueen_pdf  (jobs=jobs_to_export, queries=all_queries, export_date=ed)
        md_text   = create_jobqueen_markdown(jobs=jobs_to_export, queries=all_queries, export_date=ed)
        md_buf    = BytesIO(md_text.encode("utf-8")); md_buf.seek(0)

        fname_base = f"JobQueen_Export_{today}"
        caption    = (f"JobQueen Export  |  {len(jobs_to_export)} Stelle(n)  |  {ed}\n"
                      f"Suchanfragen: {', '.join(set(all_queries))[:80] or '-'}")

        # ── Via Telegram-Bot senden (primäre Methode) ──────────────────────
        if tg_chat_id:
            try:
                from bot_state import application as _tg_app
                real_cid = int(str(tg_chat_id).strip())

                excel_buf.seek(0)
                await _tg_app.bot.send_document(
                    chat_id=real_cid,
                    document=excel_buf,
                    filename=f"{fname_base}.xlsx",
                    caption=f"📊 Excel:\n{caption}",
                )
                pdf_buf.seek(0)
                await _tg_app.bot.send_document(
                    chat_id=real_cid,
                    document=pdf_buf,
                    filename=f"{fname_base}.pdf",
                    caption=f"📄 PDF:\n{caption}",
                )
                md_buf.seek(0)
                await _tg_app.bot.send_document(
                    chat_id=real_cid,
                    document=md_buf,
                    filename=f"{fname_base}.md",
                    caption=f"📝 Markdown:\n{caption}",
                )
                logger.info("JobQueen Export: %d Jobs via Telegram an Chat %s gesendet",
                            len(jobs_to_export), real_cid)
                return JSONResponse({
                    "success":       True,
                    "method":        "telegram",
                    "telegram_sent": True,
                    "count":         len(jobs_to_export),
                    "message":       (f"{len(jobs_to_export)} Stellen als "
                                      f"Excel, PDF & Markdown in deinen Telegram-Chat gesendet!"),
                })
            except Exception as tg_err:
                # WICHTIG: Telegram-Fehler NICHT verschlucken. Ein Binary-Fallback waere
                # hier sinnlos, da blob-Downloads im Telegram-WebView ohnehin nicht
                # funktionieren – stattdessen klaren Grund an das Frontend zurueckgeben.
                logger.error("Telegram-Senden an chat_id=%s fehlgeschlagen: %s",
                             tg_chat_id, tg_err, exc_info=True)
                return JSONResponse({
                    "success":       False,
                    "telegram_sent": False,
                    "telegram_error": str(tg_err)[:300],
                    "count":          len(jobs_to_export),
                    "message":        "Telegram-Versand fehlgeschlagen.",
                })

        # ── Binary-Fallback NUR wenn gar keine tg_chat_id übermittelt wurde ──
        # (z.B. echter Test ausserhalb von Telegram in einem normalen Browser-Tab)
        logger.info("JobQueen Export: keine tg_chat_id vorhanden, sende Binary-Fallback")
        from starlette.responses import Response as _RawResponse
        excel_buf.seek(0)
        content = excel_buf.getvalue()
        return _RawResponse(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{fname_base}.xlsx"',
                "Content-Length":      str(len(content)),
                "X-Job-Count":         str(len(jobs_to_export)),
                "Cache-Control":       "no-cache, no-store",
                "Access-Control-Expose-Headers": "X-Job-Count",
            },
        )
    except Exception as e:
        logger.error("jobqueen_excel Fehler: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


@app.get("/api/jobqueen/excel/download/{token}")
async def jobqueen_excel_download(token: str):
    """Liefert eine vorbereitete Excel-Datei via GET (für Telegram-kompatibler Download)."""
    from starlette.responses import Response as _RawResponse
    session = _excel_sessions.get(token)
    if not session:
        return JSONResponse({"error": "Token abgelaufen oder ungültig. Bitte nochmals exportieren."}, status_code=404)
    content  = session["content"]
    filename = session.get("filename", "JobQueen_Export.xlsx")
    return _RawResponse(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(content)),
            "Cache-Control":       "no-cache",
        },
    )




@app.post("/api/jobqueen/coverletters")
async def jobqueen_coverletters(request: Request):
    """JobQueen Coverletter Endpoint (LLM + HTML tables for chat)."""
    try:
        data = await request.json()
        query = (data.get("query") or "").strip()
        chat_id = (data.get("chat_id") or "jobqueen").strip() or "jobqueen"
        profile = data.get("profile") or {}
        jobs = data.get("jobs") or []

        if not query:
            return JSONResponse({"error": "query fehlt"}, status_code=400)

        from bot_ai import generate_structured_json
        import re as _re_cl
        payload_hint = json.dumps({"profile": profile, "jobs": jobs[:8]}, ensure_ascii=False)
        _cl_system = (
            "Du bist ein professioneller Bewerbungsanschreiben-Generator. "
            "Antworte AUSSCHLIESSLICH mit gueltigem JSON, kein Fliesstext, keine Markdown-Codeblocks."
        )
        _cl_user = (
            "Erstelle Anschreiben als professionelles Bewerbungsanschreiben auf Deutsch. "
            "Gib exakt folgendes JSON-Schema zurueck (nur JSON, kein Fliesstext):\n"
            "{\n"
            '  "cover_letters": [\n'
            '    {"job_id":"...","subject":"...","body_html":"<p>...</p>..."}\n'
            "  ]\n"
            "}\n\n"
            "Regeln:\n"
            "- body_html darf HTML enthalten, inkl. <table> fuer Abschnitte.\n"
            "- Nutze Werte aus 'jobs' fuer Stellenbezug (Titel/Firma/Ort/Snippet).\n"
            "- Nutze Werte aus profile fuer Skills/Erfahrung (wenn vorhanden).\n"
            f"Nutzeranfrage: {query}\nJSON-Kontext: {payload_hint}"
        )

        reply = await generate_structured_json(_cl_system, _cl_user)
        parsed = {}
        if reply:
            cleaned_cl = _re_cl.sub(r'```(?:json)?\s*|\s*```', '', reply).strip()
            s = cleaned_cl.find('{')
            e = cleaned_cl.rfind('}')
            if s != -1 and e != -1:
                try:
                    parsed = json.loads(cleaned_cl[s:e + 1])
                except Exception:
                    parsed = {}
        return JSONResponse(parsed)
    except Exception as e:
        logger.error(f"jobqueen_coverletters Fehler: {e}", exc_info=True)
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


class CvAnalyzeRequest(BaseModel):
    chat_id: Optional[str] = None
    filename: Optional[str] = None


@app.post("/api/jobqueen/cv/excel")
async def jobqueen_cv_excel(request: Request):
    """Excel-Export der CV-Analyse. Erwartet JSON-Body: {chat_id, profile (optional)}."""
    try:
        data = await request.json()
        chat_id = (data.get("chat_id") or "jobqueen").strip() or "jobqueen"

        # Profil aus State holen ODER aus Request-Body
        profile = data.get("profile")
        if not profile:
            from bot_state import jobqueen_state as _jqs_cv
            profile = (_jqs_cv.get(chat_id) or {}).get("profile") or {}

        if not profile:
            return JSONResponse({"error": "Kein Profil gefunden. Bitte zuerst CV analysieren."}, status_code=400)

        from dv import create_cv_excel
        from starlette.responses import Response as _RawResp
        buf = create_cv_excel(profile)
        name = (profile.get("name") or "CV").replace(" ", "_")[:40]
        filename = f"JobQueen_CV_{name}.xlsx"
        return _RawResp(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error("CV-Excel Fehler: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)[:400]}, status_code=500)


@app.post("/api/jobqueen/cv/stream")
async def jobqueen_cv_stream(request: Request):
    """Streaming CV-Analyse via Server-Sent Events (SSE).
    Liefert Chunks als SSE-Events: {'chunk': str} während Analyse,
    {'done': True, 'profile': {...}} am Ende.
    """
    import re as _re_cvs
    try:
        form = await request.form()
        chat_id = (form.get("chat_id") or "jobqueen").strip() or "jobqueen"

        file = None
        for _k, _v in form.items():
            if hasattr(_v, "filename") and hasattr(_v, "read"):
                file = _v
                break
        if file is None:
            return JSONResponse({"error": "CV-Datei fehlt"}, status_code=400)

        filename = getattr(file, "filename", None) or (form.get("filename") or "cv")
        suffix = Path(filename).suffix.lower() or ".bin"
        content_bytes = await file.read()

        tmp_path = None
        extracted_text = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
                tmp.write(content_bytes)
            from dv import extract_content
            extracted_text = extract_content(tmp_path, max_chars=30000)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        from bot_ai import generate_structured_json_stream

        _cv_sys = (
            "Du bist ein praeziser Lebenslauf-Analysator. "
            "Antworte AUSSCHLIESSLICH mit gueltigem JSON. "
            "Kein Fliesstext, keine Markdown-Codeblocks, kein ```json. "
            "Starte direkt mit { und ende mit }."
        )
        _cv_usr = (
            "Analysiere diesen Lebenslauf und gib strukturiertes JSON zurueck.\n\n"
            'Schema: {"name": null, "skills": [], "languages": [], '
            '"experience_years": 0, "experience_months": 0, '
            '"experience_details": {"total_months": 0, "roles": [{"title": "", "company": "", "start": null, "end": null, "months": 0}]}, '
            '"strengths": [{"strength": "", "evidence": "", "relevance": ""}], '
            '"suggested_job_titles": [{"title": "", "reason": ""}], '
            '"missing_info_questions": []}\n\n'
            "Regeln: mind. 8 strengths mit konkretem Beleg, mind. 8 suggested_job_titles.\n\n"
            f"Datei: {filename}\n\nEXTRAHIERTER TEXT:\n{extracted_text[:25000]}"
        )

        async def _sse_gen():
            full_reply = ""
            try:
                async for tag, chunk in generate_structured_json_stream(_cv_sys, _cv_usr):
                    if tag == "text":
                        full_reply += chunk
                        yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                    elif tag == "done":
                        profile = {}
                        if full_reply:
                            cleaned = _re_cvs.sub(r'```(?:json)?\s*|\s*```', '', full_reply).strip()
                            s = cleaned.find('{')
                            e = cleaned.rfind('}')
                            if s != -1 and e != -1:
                                try:
                                    profile = json.loads(cleaned[s:e + 1])
                                except Exception as _jp:
                                    logger.warning("CV-Stream JSON-Parse: %s", _jp)
                        from bot_state import jobqueen_state as _jqs2
                        _jqs2.setdefault(chat_id, {})
                        _jqs2[chat_id]["profile"] = profile
                        _jqs2[chat_id]["profile_uploaded_filename"] = filename
                        _jqs2[chat_id]["profile_last_analyzed_at"] = datetime.now().isoformat()
                        yield f"data: {json.dumps({'done': True, 'profile': profile}, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error("CV-Stream Fehler: %s", exc, exc_info=True)
                yield f"data: {json.dumps({'error': str(exc)[:200]})}\n\n"

        return StreamingResponse(
            _sse_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        logger.error("jobqueen_cv_stream Fehler: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


@app.post("/api/jobqueen/cv/analyze")
async def jobqueen_cv_analyze(request: Request):
    """JobQueen CV Analyse: Upload via multipart (file + metadata) oder JSON-conform body.

    Frontend kann entweder:
    - multipart/form-data: file=<UploadFile>, chat_id=<str>
    - oder (Fallback) JSON mit base64 content (falls später implementiert)

    Speichert Ergebnis in bot_state.jobqueen_state[chat_id].profile
    """
    try:
        # multipart: FastAPI Request + form extraction
        form = await request.form()
        chat_id = (form.get("chat_id") or "jobqueen").strip() if form.get("chat_id") else "jobqueen"

        file = None
        # Starlette UploadFile im form
        for k, v in form.items():
            if hasattr(v, "filename") and hasattr(v, "read"):
                file = v
                break
        if file is None:
            return JSONResponse({"error": "CV-Datei fehlt"}, status_code=400)

        filename = getattr(file, "filename", None) or (form.get("filename") or "cv")
        suffix = Path(filename).suffix.lower() or ".bin"

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
                content = await file.read()
                tmp.write(content)

            from dv import extract_content
            extracted_text = extract_content(tmp_path, max_chars=30000)

            from bot_ai import generate_structured_json
            import re as _re_cv
            # System-Prompt als CV-Analysator (kein Sandy-Kontext, keine Chat-History)
            _cv_system = (
                "Du bist ein praeziser CV-Analysator. "
                "Analysiere Lebenslaeufe und gib AUSSCHLIESSLICH gueltiges JSON zurueck. "
                "Kein Fliesstext, keine Erklaerungen, keine Markdown-Codeblocks (kein ```json). "
                "Starte deine Antwort direkt mit { und beende sie mit }."
            )
            _cv_user = (
                "Analysiere folgenden Lebenslauf (deutsch oder gemischt) und gib ein STRIKT strukturiertes JSON zurueck. "
                "Kein Fliesstext ausserhalb des JSON.\n\n"
                "JSON-Schema:\n"
                "{\n"
                '  "name": string|null,\n'
                '  "skills": string[],\n'
                '  "languages": string[],\n'
                '  "experience_years": number,\n'
                '  "experience_months": number,\n'
                '  "experience_details": {"total_months": number, "roles": [{"title": string, "company": string, "start": string|null, "end": string|null, "months": number}]},\n'
                '  "strengths": [{"strength": string, "evidence": string, "relevance": string}],\n'
                '  "suggested_job_titles": [{"title": string, "reason": string}],\n'
                '  "missing_info_questions": string[]\n'
                "}\n\n"
                "Regeln:\n"
                "- Berechne Berufserfahrung korrekt: mehrere Rollen beruecksichtigen, Start/End-Daten nutzen.\n"
                "- strengths: mindestens 8 Eintraege, je mit konkretem Beleg aus dem Lebenslauf und Relevanz.\n"
                "- suggested_job_titles: mindestens 8 konkrete Jobtitel passend zu Skills + Erfahrung.\n"
                "- missing_info_questions: max 6 Fragen nur wenn noetig.\n\n"
                f"Lebenslauf Datei: {filename}\n\nEXTRAHIERTER TEXT:\n{extracted_text[:25000]}"
            )

            reply = await generate_structured_json(_cv_system, _cv_user)

            # Robustes JSON-Parsing: Markdown-Codeblocks entfernen, dann {…} extrahieren
            profile = {}
            if reply:
                cleaned_reply = _re_cv.sub(r'```(?:json)?\s*|\s*```', '', reply).strip()
                start = cleaned_reply.find('{')
                end = cleaned_reply.rfind('}')
                if start != -1 and end != -1 and end > start:
                    try:
                        profile = json.loads(cleaned_reply[start:end + 1])
                    except Exception as _je:
                        logger.warning("CV JSON-Parse Fehler: %s | Reply[:200]: %s", _je, cleaned_reply[:200])
                        profile = {}


            from bot_state import jobqueen_state
            jobqueen_state.setdefault(chat_id, {})
            jobqueen_state[chat_id]["profile"] = profile
            jobqueen_state[chat_id]["profile_uploaded_filename"] = filename
            jobqueen_state[chat_id]["profile_last_analyzed_at"] = datetime.now().isoformat()
            jobqueen_state[chat_id].setdefault("jobs", [])

            return JSONResponse({"success": True, "profile": profile})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"jobqueen_cv_analyze Fehler: {e}", exc_info=True)
        return JSONResponse({"error": str(e)[:500]}, status_code=500)


@app.post("/api/jobqueen/chat")
async def jobqueen_chat(request: Request):
    """JobQueen Chat Endpoint (Groq Llama-4 via bot_ai.generate_response)."""
    try:
        data = await request.json()
        message = (data.get("message") or "").strip()
        if not message:
            return JSONResponse({"reply": "Bitte gib eine Nachricht ein."}, status_code=400)

        # chat_id im Backend nutzt History; wir binden es an einen festen Namespace.
        chat_id = (data.get("chat_id") or "jobqueen").strip() or "jobqueen"

        # model wird im aktuellen bot_ai.generate_response intern als Fallback-Liste umgesetzt.
        # Falls du später model-Override implementierst, kann diese Variable im bot_ai verwendet werden.
        _ = data.get("model")

        # Echte LLM-Generierung:
        from bot_ai import generate_response
        reply = await generate_response(chat_id=chat_id, message=message)
        return JSONResponse({"reply": reply})

    except Exception as e:
        logger.error(f"JobQueen Chat Fehler: {e}", exc_info=True)
        return JSONResponse({"reply": "Entschuldigung, es gab einen technischen Fehler."}, status_code=500)


# (Doppelte /landing, /starter und / Routen entfernt – bereits oben definiert)



# ═══════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS (Brain etc.)
# ═══════════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    query: str
    chat_id: Optional[str] = None


def _resolve_chat_id(chat_id: Optional[str]) -> Optional[str]:
    if chat_id and str(chat_id).strip():
        return str(chat_id).strip()
    if BOT_OWNER_ID and str(BOT_OWNER_ID).strip():
        return str(BOT_OWNER_ID).strip()
    if OWNER_CHAT_ID and str(OWNER_CHAT_ID).strip():
        return str(OWNER_CHAT_ID).strip()
    return None


@app.get("/api/brain/entries")
async def api_brain_entries(chat_id: Optional[str] = None):
    resolved_chat_id = _resolve_chat_id(chat_id)
    if not resolved_chat_id:
        return []
    try:
        entries = await asyncio.wait_for(load_all_entries(resolved_chat_id), timeout=10.0)
        return [
            {
                "id": e.get("id"),
                "title": e.get("title"),
                "entry_type": e.get("entry_type"),
                "created_at": e.get("created_at")
            } for e in entries
        ]
    except asyncio.TimeoutError:
        logger.warning("Brain entries Timeout")
        return []
    except Exception as e:
        logger.error(f"API /brain/entries Fehler: {e}")
        return []



@app.post("/api/brain/query")
async def api_brain_query(request: QueryRequest):
    resolved_chat_id = _resolve_chat_id(request.chat_id)
    if not resolved_chat_id:
        return {"success": False, "answer": "chat_id fehlt. Bitte mitgeben oder OWNER_CHAT_ID setzen."}
    try:
        result = await asyncio.wait_for(
            brain_query_agent(resolved_chat_id, request.query),
            timeout=30.0
        )
        return result
    except asyncio.TimeoutError:
        return {"success": False, "answer": "Timeout beim Brain-Agent."}
    except Exception as e:
        logger.error(f"API /brain/query Fehler: {e}")
        return {"success": False, "answer": f"Interner Fehler: {str(e)}"}


@app.get("/api/brain/download/{entry_id}")
async def api_brain_download(entry_id: str, chat_id: Optional[str] = None):
    resolved_chat_id = _resolve_chat_id(chat_id)
    if not resolved_chat_id:
        return {"error": "chat_id fehlt. Bitte mitgeben oder OWNER_CHAT_ID setzen."}
    try:
        entry = await asyncio.wait_for(load_entry(resolved_chat_id, entry_id), timeout=10.0)
        if not entry or entry.get("entry_type") != "file":
            return {"error": "Datei nicht gefunden"}

        file_bytes = base64.b64decode(entry["content"])
        metadata = json.loads(entry.get("metadata", "{}"))
        filename = metadata.get("filename", f"brain_file_{entry_id}")

        return StreamingResponse(
            iter([file_bytes]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(file_bytes))
            }
        )
    except asyncio.TimeoutError:
        return {"error": "Timeout beim Laden"}
    except Exception as e:
        logger.error(f"Download Fehler fuer {entry_id}: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starte Server auf {HOST}:{PORT}")
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        workers=1,
        loop="asyncio",
        log_level="info",
    )
