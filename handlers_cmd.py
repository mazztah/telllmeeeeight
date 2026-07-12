# handlers_cmd.py – Alle Command-Handler
import asyncio
import html
import base64
import logging
import os
import tempfile
import time


from io import BytesIO
from pydub import AudioSegment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from pathlib import Path

from bot_state import (
    application, awaiting_upload, edit_mode_active, full_brain_synced,
    last_edit_image_bytes, last_generated_code, last_workflow_bundle,
    master_prompts, pending_email_requests, pending_voice_clones,
    synced_brain, tts_enabled, video_tasks, youtube_results,
    safe_send_message, safe_edit_message,
)
from bot_ai import (
    build_prompt_history, generate_response, generate_voice, get_chat_history, _persist_chat_turn,
)

# ... bestehende Imports ...
from lyria_music import generate_lyria_music, format_music_caption
# WICHTIG: Hier generate_suno_music hinzufÃ¼gen, um den NameError zu fixen!
from suno_music import generate_suno_music, format_suno_caption
from free_music import generate_free_music # Unser neues Backup

from bot_utils import (
    build_agent_tools, create_background_task, download_telegram_file_to_temp,
    fit_telegram_text, get_command_payload, is_audio_document,
    normalize_target, parse_speak_command, parse_workflow_request,
    prepare_email_batch_preview, run_file_conversion_pipeline,
    run_text_conversion_pipeline, send_conversion_result,
)
from brain import (
    delete_entry, list_entries, load_entry, save_chat, save_file,
    set_master_prompt, test_connection,
)
from emgen import (
    cancel_batch, confirm_and_send_batch, finish_gmail_auth,
    gmail_backend_status, parse_email_batch_command, start_gmail_auth,
)
from guard import (
    can_process_text, check_rate_limit, describe_guard_status, toggle_privacy_mode,
)
from imgedi import edit_image, format_edit_caption
from imgrem import format_image_caption, generate_image
from codebrain import save_full_code_to_brain, search_code_brain
from vectorbrain import format_semantic_results, index_brain_entries, semantic_search
from social import format_social_pack
from voicecl import (
    backend_status, clone_voice_from_file, delete_cloned_voice,
    describe_cloned_voices, synthesize_with_cloned_voice,
)
from voice_distortion import list_effects, apply_effect, EFFECT_PRESETS

from workflow import (
    build_workflow_export, create_workflow_bundle, format_workflow_bundle,
)
from ytscript import (
    build_youtube_export_file, build_youtube_pdf,
    extract_youtube_url, format_youtube_result_for_user, get_youtube_script,
)
from textvideo import generate_text_to_video
from agent import run_agent_loop
from text_to_3d import text_to_3d
from handler_convert3d import cmd_convert3d
import webbrowser
import hashlib
from pathlib import Path
import os

logger = logging.getLogger(__name__)
_savecode_locks: dict[str, asyncio.Lock] = {}

PUBLIC_APP_BASE_URL = os.getenv(
    "PUBLIC_APP_BASE_URL",
    "https://telllmeeesevn.onrender.com"
).rstrip("/")

SCANNER_WEBAPP_URL = os.getenv(
    "SCANNER_WEBAPP_URL", 
    f"{PUBLIC_APP_BASE_URL}/scanner"
)

MOOOST_URL = os.getenv(
    "MOOOST_URL",
    "https://mooost.onrender.com"
)

# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _new_temp_path(suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        return temp.name


def convert_audio_reference_to_wav(source_path: str) -> tuple[str, list[str]]:
    cleanup = [source_path]
    if source_path.lower().endswith(".wav"):
        return source_path, cleanup
    wav_path = _new_temp_path(".wav")
    audio = AudioSegment.from_file(source_path)
    audio.export(wav_path, format="wav")
    cleanup.append(wav_path)
    return wav_path, cleanup


async def clone_voice_reference(chat_id: str, voice_name: str, source_path: str) -> tuple[bool, str]:
    prepared_path = source_path
    cleanup_paths = [source_path]
    try:
        prepared_path, cleanup_paths = convert_audio_reference_to_wav(source_path)
        return await clone_voice_from_file(chat_id, prepared_path, voice_name)
    finally:
        for p in cleanup_paths:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


def get_youtube_cache_key(chat_id: str, video_id: str) -> str:
    return f"{chat_id}:{video_id}"


def build_youtube_button_overview(cache_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Transcript als PDF", callback_data=f"ytpdf|t|{cache_key}"),
            InlineKeyboardButton("PDF Download", callback_data=f"ytpdf|td|{cache_key}"),
        ],
        [
            InlineKeyboardButton("Transcript + Summary PDF", callback_data=f"ytpdf|ts|{cache_key}"),
            InlineKeyboardButton("Summary PDF Download", callback_data=f"ytpdf|sd|{cache_key}"),
        ],
    ])


async def video_generation_wrapper(chat_id, prompt, img_url, loading_msg, context,
                                   duration=5, resolution="480P", aspect_ratio="9:16"):
    try:
        video_path, used_model = await generate_text_to_video(
            prompt=prompt or "energetic dynamic scene",
            img_url=img_url,
            duration=duration,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
        )
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)
        except Exception:
            pass

        if video_path and video_path.exists():
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_path, "rb"),
                caption=format_video_caption(prompt, used_model, duration, resolution, aspect_ratio),
                supports_streaming=True,
                parse_mode="Markdown",
            )
            video_path.unlink(missing_ok=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text="âŒ Video-Generierung fehlgeschlagen.")

    except asyncio.CancelledError:
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text="â›” Video abgebrochen.")
        except Exception:
            pass
    except Exception as e:
        logger.exception("video_generation_wrapper Fehler")
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=f"âŒ Fehler: {str(e)[:120]}")
        except Exception:
            pass
    finally:
        video_tasks.pop(chat_id, None)


# â”€â”€ Commands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands = [
        "start",
        "upload",
        "synchromaster",
        "synchroall",
        "synchdata",
        "convert",
        "textconvert",
        "yt",
        "voicetoggle",
        "imagine",
        "img",
        "edit",
        "bearbeiten",
        "vision",
        "analyze",
        "beschreib",
        "musik",
        "humming",
        "summen",
        "testbrain",
        "chat",
        "listbrain",
        "brainlist",
        "agent",
        "superagent",
        "openclaw",
        "workflow",
        "social",
        "brainindex",
        "semantic",
        "privacy",
        "guard",
        "audit",
        "gmail_auth",
        "gmail_code",
        "mailbatch",
        "emailbatch",
        "voiceclone",
        "myvoices",
        "deletevoice",
        "speak",
        "textvideo",
        "stopvideo",
        "cancel",
        "savecode",
        "code",
        "clcode (aliases ok)",
        "standard",
        "startstream",
        "voicestream",
        "endstream",
        "stopstream",
        "livevoice",
        "scan",
        "qr",
        "ttv26",
        "lyria",
        "suno",
        "freebeat",
        "convert3d",
        "mesh",
        "3d",
        "robot",
        "deepvoice",
        "chipmunk",
        "demon",
        "telephone",
        "echo",
        "alien",
        "underwater",
        "radio",
        "megaphone",
        "whisper",
        "monster",
        "cyberpunk",
        "cave",
        "helium",
        "reverse",
        "sandbox",
        "runcode",
        "py",
        "htmlapp",
        "codefile",
        "stopdistort",
    ]

    command_lines = "\n".join(f"? <code>/{cmd}</code>" for cmd in commands)

    keyboard = [
        [
            InlineKeyboardButton(
                "📱 QR & Barcode Scanner öffnen",
                web_app=WebAppInfo(url=SCANNER_WEBAPP_URL),
            )
        ],
        [
            InlineKeyboardButton(
                "🚀 Mooost öffnen",
                web_app=WebAppInfo(url=MOOOST_URL),
            )
        ],
    ]
    row = []
    for cmd in commands:
        row.append(
            InlineKeyboardButton(
                f"/{cmd}",
                switch_inline_query_current_chat=f"/{cmd} ",
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    text = (
        "<b>Willkommen beim Multitool-Bot</b>\n"
        "Ich merke mir den Chat, speichere Dateien ins Brain und starte AI-Workflows direkt im Chat.\n\n"
        "<b>??? Voice Cloning &amp; Verzerrung</b>\n"
        "? <code>/voiceclone Name</code> -> Stimme klonen (Voice/Audio reply)\n"
        "? <code>/speak Name | Text</code> -> mit geklonter Stimme sprechen\n"
        "? <code>/myvoices</code> -> deine Stimmen\n"
        "? <code>/startstream</code> -> Live Voice Stream\n\n"
        "? <code>/robot</code>, <code>/deepvoice</code>, <code>/chipmunk</code>\n"
        "? <code>/demon</code>, <code>/telephone</code>, <code>/echo</code> -> Voice-Effekte\n"
        "? <code>/stopdistort</code> -> Effekt-Modus beenden\n"
        "\n"
        "💻 <b>Code Sandbox</b>\n"
        "? <code>/sandbox</code> -> Code Editor öffnen (Monaco)\n"
        "? <code>/runcode print(2+2)</code> -> Python direkt ausführen\n"
        "? <code>/py</code> -> Alias für /runcode\n"
        "? <code>/htmlapp</code> -> HTML Mini-App generieren\n"
        "? <code>/codefile</code> -> .py Datei ausführen (reply auf Datei)\n"
        "\n"
        "? <code>/upload</code> -> Datei ins Brain laden\n"
        "? <code>/chat</code> -> Chat speichern\n"
        "? <code>/listbrain</code> -> Brain-Eintraege anzeigen\n"
        "? <code>/brainlist</code> -> Brain UI mit Auswahl/Loeschen\n"
        "? <code>/semantic Suche</code> -> intelligente Suche\n\n"
        "<b>?? Konvertierung & YouTube</b>\n"
        "? <code>/convert ID to pdf</code> -> Datei umwandeln\n"
        "? <code>/textconvert pdf Hallo</code> -> Text konvertieren\n"
        "? <code>/yt Link</code> -> YouTube Transcript + PDF\n\n"
        "<b>?? Agents & Workflow</b>\n"
        "? <code>/superagent</code> -> Master-Agent\n"
        "? <code>/agent Aufgabe</code> -> normaler Agent\n"
        "? <code>/workflow Thema</code> -> Content-Plan\n"
        "? <code>/openclaw Aufgabe</code> -> Cloud-Agent\n\n"
        "<b>?? Code & Extras</b>\n"
        "? <code>/clcode Prompt</code> -> Claude Code\n"
        "? <code>/codeclaude Prompt</code> -> Claude Code Alias\n"
        "? <code>/codeclode Prompt</code> -> Claude Code Alias (Typo)\n"
        "? <code>/code python:</code> oder <code>/code html:</code>\n"
        "? <code>/privacy</code> -> Chat nicht speichern\n"
        "? <code>/audit</code> -> Bot Audit Report\n"
        "? <code>/livevoice</code> -> Live Voice WebApp\n\n"
        "? <code>/scan</code> oder <code>/qr</code> -> QR/Barcode Scanner\n\n"
        "<b>Alle registrierten Slash-Commands</b>\n"
        f"{command_lines}\n\n"
        "Quick-Access: Tippe einen Button, um den Command direkt einzusetzen."
    )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
async def cmd_mooost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Öffnet Mooost als Telegram WebApp inline."""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🚀 Mooost öffnen",
            web_app=WebAppInfo(url=MOOOST_URL),
        )
    ]])
    await update.message.reply_text(
        "Mooost starten:",
        reply_markup=keyboard,
    )


async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    doc = update.message.document
    if not doc and update.message.reply_to_message:
        doc = update.message.reply_to_message.document

    if not doc:
        awaiting_upload.add(chat_id)
        await update.message.reply_text("Schick mir jetzt eine Datei.")
        return

    loading = await update.message.reply_text("ðŸ“¤ Lade Datei ins Brain hoch...")
    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = bytes(await file.download_as_bytearray())
        result = await save_file(chat_id, file_bytes, doc.file_name or "unnamed_file", doc.mime_type)
        if "ID:" in result:
            create_background_task(index_brain_entries(chat_id, limit=40))
        awaiting_upload.discard(chat_id)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=result)
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Upload fehlgeschlagen: {str(e)[:100]}")


async def cmd_synchromaster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("âŒ /synchromaster <ID>")
        return
    new_prompt = await set_master_prompt(chat_id, context.args[0])
    if not new_prompt:
        await update.message.reply_text("âŒ Datei nicht gefunden oder keine gÃ¼ltige Datei.")
        return
    master_prompts[chat_id] = new_prompt
    await update.message.reply_text(f"âœ… Master-Systemprompt aus Datei `{context.args[0]}` aktiviert.")


async def cmd_synchroall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    full_brain_synced[chat_id] = True
    await update.message.reply_text("ðŸ”„ Full-Brain-Sync aktiviert.")


async def cmd_synchdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("âŒ /synchdata <ID>")
        return
    synced_brain.setdefault(chat_id, []).append(context.args[0])
    await update.message.reply_text(f"âœ… Datei ID `{context.args[0]}` dauerhaft synchronisiert.")


async def cmd_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if len(context.args) < 3 or context.args[1].lower() != "to":
        await update.message.reply_text("âŒ /convert <ID> to <format>\nBeispiel: /convert 123 to pdf")
        return

    entry_id = context.args[0]
    target = normalize_target(context.args[2])
    entry = await load_entry(chat_id, entry_id)
    if not entry or entry.get("entry_type") != "file":
        await update.message.reply_text("âŒ Datei nicht gefunden.")
        return

    loading = await update.message.reply_text(f"ðŸ”„ Konvertiere zu {target.upper()}...")
    tmp_path = None
    try:
        file_bytes = base64.b64decode(entry["content"])
        suffix = os.path.splitext(entry.get("title", ""))[1] or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        conv_result = await run_file_conversion_pipeline(
            chat_id=chat_id, file_path=tmp_path, target=target,
            source_name=entry.get("title", f"brain_{entry_id}"),
        )
        if conv_result["success"] and conv_result.get("output"):
            await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
            brain_result = await send_conversion_result(chat_id, context, conv_result)
            if brain_result and brain_result != "Brain deaktiviert":
                await context.bot.send_message(chat_id=chat_id, text=brain_result)
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=loading.message_id,
                text=f"âŒ Konvertierung fehlgeschlagen:\n{conv_result.get('message', 'Unbekannter Fehler')}",
            )
    except Exception as e:
        logger.exception("cmd_convert Fehler")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"âŒ Fehler: {str(e)[:150]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def cmd_textconvert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Nutzung: /textconvert <format> <text>")
        return

    target = normalize_target(context.args[0])
    inline_text = " ".join(context.args[1:]).strip()
    reply_text = ""
    if update.message.reply_to_message:
        reply_text = (update.message.reply_to_message.text or update.message.reply_to_message.caption or "").strip()

    source_text = inline_text or reply_text
    if not source_text:
        await update.message.reply_text("Bitte Text angeben oder auf eine Textnachricht antworten.")
        return

    loading = await update.message.reply_text(f"ðŸ›  Erstelle {target.upper()} aus Text...")
    try:
        conv_result = await run_text_conversion_pipeline(
            chat_id=chat_id, text=source_text, target=target,
            source_name=f"text_{chat_id}.{target}",
        )
        if conv_result.get("success") and conv_result.get("output"):
            await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
            brain_result = await send_conversion_result(chat_id, context, conv_result)
            if brain_result and brain_result != "Brain deaktiviert":
                await context.bot.send_message(chat_id=chat_id, text=brain_result)
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=loading.message_id,
                text=f"âŒ Fehlgeschlagen:\n{conv_result.get('message', 'Unbekannter Fehler')}",
            )
    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"âŒ Fehler: {str(exc)[:200]}")


async def handle_edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    # Vision-Modus zurücksetzen wenn Edit aktiviert wird
    from bot_state import vision_mode_active
    vision_mode_active.pop(chat_id, None)
    if edit_mode_active.get(chat_id, False):
        edit_mode_active.pop(chat_id, None)
        last_edit_image_bytes.pop(chat_id, None)
        await update.message.reply_text("âœ… Edit-Modus DEAKTIVIERT")
    else:
        edit_mode_active[chat_id] = True
        await update.message.reply_text("âœ… Edit-Modus AKTIV ðŸ–Œï¸\nSchick mir ein Bild als Basis.")


async def handle_vision_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    edit_mode_active.pop(chat_id, None)
    from bot_state import vision_mode_active
    # Nutze Caption oder Args als Prompt, sonst Default
    user_prompt = " ".join(context.args).strip() if context.args else ""
    if not user_prompt and update.message.caption:
        user_prompt = update.message.caption.strip()
    vision_mode_active[chat_id] = {
        "active": True,
        "prompt": user_prompt or (
            "Beschreibe das Bild detailliert. Falls Text darauf zu sehen ist, "
            "transkribiere ihn vollstaendig und korrekt. Beantworte dann eventuelle "
            "Fragen des Users zu dem Bild oder Text."
        ),
    }
    await update.message.reply_text("Vision-Modus AKTIV\nSchick mir jetzt ein Foto (oder Bild als Datei).")

async def handle_vision_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    from bot_state import vision_mode_active
    if vision_mode_active.pop(chat_id, None):
        await update.message.reply_text("Vision-Modus deaktiviert.")
    else:
        await update.message.reply_text("Vision-Modus war nicht aktiv.")


async def toggle_voice_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    tts_enabled[chat_id] = not tts_enabled.get(chat_id, False)
    status = "âœ… AN" if tts_enabled[chat_id] else "âŒ AUS"
    await update.message.reply_text(f"Sprachantworten jetzt {status}")


async def cmd_yt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    raw_text = " ".join(context.args).strip()
    if not raw_text and update.message.reply_to_message and update.message.reply_to_message.text:
        raw_text = update.message.reply_to_message.text.strip()

    youtube_url = extract_youtube_url(raw_text)
    if not youtube_url:
        await update.message.reply_text("Nutzung: /yt <youtube-link>")
        return

    loading = await update.message.reply_text("Lade YouTube-Daten...")
    try:
        yt_result = await get_youtube_script(youtube_url)
        if not yt_result.get("success"):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Fehler:\n{yt_result.get('error', '')[:250]}")
            return
        cache_key = get_youtube_cache_key(chat_id, yt_result["video_id"])
        youtube_results[cache_key] = yt_result
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=loading.message_id,
            text=format_youtube_result_for_user(yt_result),
            parse_mode="HTML", disable_web_page_preview=True,
            reply_markup=build_youtube_button_overview(cache_key),
        )
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"YouTube fehlgeschlagen:\n{str(e)[:250]}")


async def handle_yt_pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer("PDF wird erstellt...")
    try:
        _, action, cache_key = query.data.split("|", 2)
    except ValueError:
        await query.message.reply_text("UngÃ¼ltige Aktion.")
        return

    result = youtube_results.get(cache_key)
    if not result:
        await query.message.reply_text("YouTube-Daten nicht mehr im Speicher. Bitte /yt erneut senden.")
        return

    mode_map = {"t": "transcript", "td": "transcript_download", "ts": "combined", "sd": "summary_download"}
    mode = mode_map.get(action)
    if not mode:
        await query.message.reply_text("Unbekannte PDF-Aktion.")
        return

    try:
        pdf_buffer, filename, caption = build_youtube_pdf(result, mode)
        await query.message.reply_document(document=pdf_buffer, filename=filename, caption=caption)
    except Exception as e:
        await query.message.reply_text(f"PDF fehlgeschlagen:\n{str(e)[:250]}")


async def handle_imagine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prompt = update.message.text.replace("/imagine", "").replace("/img", "").strip()
    if not prompt:
        await update.message.reply_text("Schick mir /imagine <prompt>")
        return
    decision = can_process_text(chat_id, prompt, action="image")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return
    loading = await update.message.reply_text("âœ¨ FLUX.1-schnell lÃ¤uft...")
    image_bytes = await generate_image(prompt, width=1024, height=1024)
    if image_bytes:
        await context.bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=format_image_caption(prompt), parse_mode="Markdown")
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
    else:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text="âŒ FLUX gerade nicht erreichbar.")



from pathlib import Path

async def handle_textvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    # Bild finden (direkt oder Antwort auf Bild)
    reply_to = update.message.reply_to_message
    photo = None

    if reply_to and reply_to.photo:
        photo = reply_to.photo[-1]
    elif update.message.photo:
        photo = update.message.photo[-1]

    if not photo:
        await update.message.reply_text(
            "âŒ So funktioniert /textvideo:\n\n"
            "1. Schicke ein Bild\n"
            "2. Antworte direkt auf dieses Bild mit:\n"
            "/textvideo\n\n"
            "Optional mit Prompt:\n"
            "/textvideo Die Katze lÃ¤uft nach rechts"
        )
        return

    # Bild herunterladen
    file = await context.bot.get_file(photo.file_id)
    temp_image_path = f"temp_img_{chat_id}.jpg"
    await file.download_to_drive(temp_image_path)

    loading_msg = await update.message.reply_text("ðŸŽ¬ Erstelle Video aus deinem Bild...")

    try:
        video_path, used_model = await generate_text_to_video(
            prompt=" ".join(context.args).strip() or "smooth natural movement",
            img_url=temp_image_path,
            duration=5,
            resolution="720P",
            aspect_ratio="16:9"
        )

        await context.bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)

        if video_path and video_path.exists():
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_path, "rb"),
                caption=f"âœ… Video fertig mit {used_model}",
                supports_streaming=True
            )
            video_path.unlink(missing_ok=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text="âŒ Video konnte nicht erstellt werden.")

    except Exception as e:
        logger.error(f"handle_textvideo Fehler: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"âŒ Fehler: {str(e)[:150]}")

    finally:
        Path(temp_image_path).unlink(missing_ok=True)


async def handle_stop_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if chat_id in video_tasks and not video_tasks[chat_id].done():
        video_tasks[chat_id].cancel()
        await update.message.reply_text("â›” Video wird abgebrochen...")
        try:
            await asyncio.wait_for(video_tasks[chat_id], timeout=10.0)
        except Exception:
            pass
        video_tasks.pop(chat_id, None)
        await update.message.reply_text("âœ… Video abgebrochen.")
    else:
        await update.message.reply_text("Kein Video lÃ¤uft gerade.")


async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from codeinterpreter import run_code
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    if text.startswith("/code python:"):
        code, lang = text[13:].strip(), "python"
    elif text.startswith("/code html:"):
        code, lang = text[11:].strip(), "html"
    else:
        await update.message.reply_text("âŒ Nutzung:\n/code python: print('Hallo')\n/code html: <h1>Hallo</h1>")
        return

    loading = await update.message.reply_text("ðŸ§ª Code wird ausgefÃ¼hrt...")
    result = await run_code(code, lang, chat_id, save_to_brain=True)

    if result["success"]:
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        last_generated_code[chat_id] = {"language": lang, "code": code, "timestamp": time.time()}
        if result.get("plot"):
            await context.bot.send_photo(chat_id=chat_id, photo=result["plot"], caption="ðŸ“Š Plot")
        elif result.get("file"):
            buf, fname = result["file"]
            await context.bot.send_document(chat_id=chat_id, document=buf, filename=fname, caption="âœ… Datei fertig!")
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"**Output:**\n{result.get('output', 'Kein Output')}", parse_mode="Markdown")
    else:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"âŒ Fehler:\n{result.get('error', 'Unbekannt')}")


async def cmd_testbrain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await test_connection())




audit_report_cache: dict[str, str] = {}


def detect_known_issues() -> list[str]:
    issues: list[str] = []
    try:
        import inspect
        from brain import load_all_entries as _load_all_entries

        params = inspect.signature(_load_all_entries).parameters
        if "limit" not in params or "search" not in params:
            issues.append("/brainlist Fehler moeglich: load_all_entries akzeptiert kein limit/search.")
    except Exception:
        issues.append("/brainlist Check konnte nicht ausgefuehrt werden.")

    try:
        openclaw_code = Path(__file__).with_name("openclaw.py").read_text(encoding="utf-8", errors="ignore")
        if "Update.new_chat_message" in openclaw_code:
            issues.append("/openclaw Callback nutzt Update.new_chat_message (ungueltig in python-telegram-bot).")
        if "llama-4-scout-17b-instruct" in openclaw_code:
            issues.append("/openclaw Modellname ohne Provider-Praefix kann 404/model_not_found ausloesen.")
    except Exception:
        issues.append("/openclaw Check konnte nicht ausgefuehrt werden.")

    if not issues:
        issues.append("Keine offensichtlichen Known Issues aus Static-Checks erkannt.")
    return issues


async def build_audit_report(chat_id: str):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    env_checks = [
        ("TELEGRAM_BOT_TOKEN", bool(os.getenv("TELEGRAM_BOT_TOKEN"))),
        ("GROQ_API_KEY oder XAI_API_KEY", bool(os.getenv("GROQ_API_KEY") or os.getenv("XAI_API_KEY"))),
        ("ANTHROPIC_API_KEY", bool(os.getenv("ANTHROPIC_API_KEY"))),
    ]

    try:
        brain_status = await test_connection()
    except Exception as exc:
        brain_status = f"Brain-Check fehlgeschlagen: {str(exc)[:180]}"

    guard_status = describe_guard_status(chat_id).replace("\n", " | ")

    runtime_lines = [
        f"TTS aktiv (dieser Chat): {'JA' if tts_enabled.get(chat_id, False) else 'NEIN'}",
        f"Video-Task aktiv (dieser Chat): {'JA' if chat_id in video_tasks and not video_tasks[chat_id].done() else 'NEIN'}",
        f"Upload erwartet (dieser Chat): {'JA' if chat_id in awaiting_upload else 'NEIN'}",
        f"Voice-Clone pending (dieser Chat): {'JA' if chat_id in pending_voice_clones else 'NEIN'}",
        f"Mailbatch pending (dieser Chat): {'JA' if chat_id in pending_email_requests else 'NEIN'}",
        f"Chat-History Eintraege (dieser Chat): {len(get_chat_history(chat_id))}",
        f"Workflow Cache vorhanden: {'JA' if chat_id in last_workflow_bundle else 'NEIN'}",
        f"Code Cache vorhanden: {'JA' if chat_id in last_generated_code else 'NEIN'}",
    ]

    lines = [
        "BOT AUDIT REPORT",
        f"Generated: {now}",
        f"Chat ID: {chat_id}",
        "",
        "ENVIRONMENT",
    ]
    lines.extend(f"- {name}: {'OK' if ok else 'MISSING'}" for name, ok in env_checks)
    lines.extend([
        "",
        "BACKENDS",
        f"- Brain: {brain_status}",
        f"- Voice: {backend_status()}",
        f"- Gmail: {gmail_backend_status()}",
        f"- Guard: {guard_status}",
        "",
        "RUNTIME",
    ])
    lines.extend(f"- {entry}" for entry in runtime_lines)
    lines.extend([
        "",
        "KNOWN ISSUES",
    ])
    lines.extend(f"- {item}" for item in detect_known_issues())
    lines.extend([
        "",
        "Hinweis: /audit fuehrt den Check erneut aus.",
    ])
    return "\n".join(lines)


def build_audit_html(chat_id: str, report: str) -> str:
    safe_report = "<br>".join(
        html.escape(line) if line.strip() else "&nbsp;"
        for line in report.splitlines()
    )
    issues = detect_known_issues()
    issues_html = "".join(f"<li>{html.escape(issue)}</li>" for issue in issues)
    generated = time.strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Bot Audit</title>
<style>
:root {{
  --bg:#0d0f14; --surface:#161921; --surface2:#1e2230; --border:#2a2f3f;
  --text:#e8ecf4; --muted:#7a8099; --accent:#a78bfa; --ok:#34d399; --warn:#fbbf24;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px; background:var(--bg); color:var(--text); font-family:Arial,sans-serif; }}
.header {{ border-bottom:1px solid var(--border); padding-bottom:14px; margin-bottom:18px; }}
.header h1 {{ margin:0; font-size:28px; color:var(--accent); }}
.header p {{ margin:8px 0 0; color:var(--muted); }}
.grid {{ display:grid; gap:16px; grid-template-columns:1fr; }}
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:14px; }}
.card h2 {{ margin:0 0 8px; font-size:14px; text-transform:uppercase; letter-spacing:.06em; color:var(--accent); }}
pre {{ margin:0; white-space:pre-wrap; line-height:1.55; font-size:13px; color:var(--text); }}
ul {{ margin:0; padding-left:18px; color:var(--muted); }}
.badges {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
.badge {{ font-size:12px; padding:4px 8px; border-radius:6px; border:1px solid var(--border); background:var(--surface2); color:var(--muted); }}
.ok {{ color:var(--ok); }}
.warn {{ color:var(--warn); }}
</style>
</head>
<body>
  <div class="header">
    <h1>telllmeeedrei - Bot Audit</h1>
    <p>Generated: {html.escape(generated)} | Chat ID: {html.escape(chat_id)}</p>
    <div class="badges">
      <span class="badge ok">/audit aktiv</span>
      <span class="badge">Format: HTML</span>
      <span class="badge warn">Known Issues geprueft</span>
    </div>
  </div>

  <div class="grid">
    <section class="card">
      <h2>Audit Summary</h2>
      <pre>{safe_report}</pre>
    </section>

    <section class="card">
      <h2>Known Issues</h2>
      <ul>{issues_html}</ul>
    </section>
  </div>
</body>
</html>
"""


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    loading = await update.message.reply_text("Starte Audit...")
    try:
        report = await build_audit_report(chat_id)
        audit_report_cache[chat_id] = report

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Audit HTML oeffnen", callback_data="audit:html"),
                InlineKeyboardButton("Audit als TXT", callback_data="audit:download"),
            ],
        ])

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=fit_telegram_text(report),
            reply_markup=keyboard,
        )
    except Exception as exc:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"Audit fehlgeschlagen: {str(exc)[:250]}",
        )


async def handle_audit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    if query.data not in {"audit:download", "audit:html"}:
        await query.answer()
        return

    chat_id = str(query.message.chat.id) if query.message else str(update.effective_chat.id)

    try:
        report = audit_report_cache.get(chat_id) or await build_audit_report(chat_id)
        audit_report_cache[chat_id] = report
        ts = time.strftime("%Y%m%d_%H%M%S")

        if query.data == "audit:html":
            html_doc = build_audit_html(chat_id, report)
            filename = f"bot_audit_{chat_id}_{ts}.html"
            buffer = BytesIO(html_doc.encode("utf-8"))
            caption = "Bot Audit HTML"
            await query.answer("Audit HTML wird gesendet...")
        else:
            filename = f"bot_audit_{chat_id}_{ts}.txt"
            buffer = BytesIO(report.encode("utf-8"))
            caption = "Bot Audit Report"
            await query.answer("Audit TXT wird gesendet...")

        buffer.name = filename
        buffer.seek(0)
        await query.message.reply_document(
            document=buffer,
            filename=filename,
            caption=caption,
        )
    except Exception as exc:
        await query.answer("Audit fehlgeschlagen", show_alert=True)
        if query.message:
            await query.message.reply_text(f"Audit-Download fehlgeschlagen: {str(exc)[:250]}")

async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    history = get_chat_history(chat_id)
    if len(history) < 3:
        await update.message.reply_text("Chat zu kurz zum Speichern.")
        return
    reply = await save_chat(chat_id, history)
    if "ID:" in reply:
        create_background_task(index_brain_entries(chat_id, limit=40))
    await update.message.reply_text(reply)


async def cmd_listbrain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(await list_entries(chat_id, limit=10))


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    request_text = get_command_payload(update, context)
    if not request_text:
        await update.message.reply_text("Nutzung: /agent <auftrag>")
        return
    decision = can_process_text(chat_id, request_text, action="agent")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return
    loading = await update.message.reply_text("Agent arbeitet...")
    try:
        history = await build_prompt_history(chat_id)
        from bot_state import client as _client
        result = await run_agent_loop(client=_client, history=history, user_message=request_text, tools=build_agent_tools(chat_id))
        content = fit_telegram_text(result.get("content") or "Kein Agent-Output.")
        used_tools = result.get("used_tools") or []
        if used_tools:
            content += f"\n\nTools: {', '.join(used_tools)}"
        _persist_chat_turn(chat_id, f"/agent {request_text}", content)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=content)
    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Agent fehlgeschlagen: {str(exc)[:250]}")


async def cmd_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    request_text, allow_image, allow_video = parse_workflow_request(context.args)
    if not request_text:
        request_text = get_command_payload(update, context)

    if not request_text:
        await update.message.reply_text("Nutzung: /workflow [--image] [--video] <briefing>")
        return
    decision = can_process_text(chat_id, request_text, action="workflow")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

    loading = await update.message.reply_text("Baue Workflow, Script, Shotlist und Social-Pack...")
    try:
        from bot_state import client as _client
        history = await build_prompt_history(chat_id)
        bundle = await create_workflow_bundle(_client, history, request_text)
        last_workflow_bundle[chat_id] = bundle

        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=fit_telegram_text(format_workflow_bundle(bundle)))
        await context.bot.send_message(chat_id=chat_id, text=fit_telegram_text(format_social_pack(bundle.get("social_pack") or {})))

        export_buffer = build_workflow_export(bundle)
        await context.bot.send_document(chat_id=chat_id, document=export_buffer, filename=getattr(export_buffer, "name", "workflow.json"), caption="Workflow-Export")

        if allow_image:
            img_loading = await update.message.reply_text("Renderiere Keyvisual...")
            image_bytes = await generate_image(bundle.get("image_prompt") or request_text, width=1024, height=1024)
            if image_bytes:
                await context.bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=format_image_caption(bundle.get("image_prompt") or request_text), parse_mode="Markdown")
                await context.bot.delete_message(chat_id=chat_id, message_id=img_loading.message_id)
            else:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=img_loading.message_id, text="Bild konnte nicht gerendert werden.")

        if allow_video:
            if chat_id in video_tasks and not video_tasks[chat_id].done():
                await context.bot.send_message(chat_id=chat_id, text="Es lÃ¤uft schon ein Video.")
            else:
                video_loading = await update.message.reply_text("Starte Workflow-Video...")
                task = asyncio.create_task(video_generation_wrapper(
                    chat_id=chat_id, prompt=bundle.get("video_prompt") or request_text, img_url=None,
                    loading_msg=video_loading, context=context, duration=8, resolution="720P", aspect_ratio="9:16",
                ))
                video_tasks[chat_id] = task

    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Workflow fehlgeschlagen: {str(exc)[:250]}")


async def cmd_social(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    request_text = get_command_payload(update, context)

    if not request_text and chat_id in last_workflow_bundle:
        social_pack = last_workflow_bundle[chat_id].get("social_pack") or {}
        await update.message.reply_text(fit_telegram_text(format_social_pack(social_pack)))
        return

    if not request_text:
        await update.message.reply_text("Nutzung: /social <briefing>")
        return

    loading = await update.message.reply_text("Erstelle Social-Pack...")
    try:
        from bot_state import client as _client
        history = await build_prompt_history(chat_id)
        bundle = await create_workflow_bundle(_client, history, request_text)
        last_workflow_bundle[chat_id] = bundle
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=fit_telegram_text(format_social_pack(bundle.get("social_pack") or {})))
    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Social-Pack fehlgeschlagen: {str(exc)[:250]}")


async def cmd_brainindex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    loading = await update.message.reply_text("Indexiere Brain...")
    result = await index_brain_entries(chat_id, limit=60)
    await context.bot.edit_message_text(
        chat_id=chat_id, message_id=loading.message_id,
        text=f"{result.get('message', 'Fertig.')}\nIndexed: {result.get('indexed', 0)} | Persisted: {result.get('persisted', 0)}",
    )


async def cmd_semantic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    query = get_command_payload(update, context)
    if not query:
        await update.message.reply_text("Nutzung: /semantic <frage>")
        return
    loading = await update.message.reply_text("Suche semantisch im Brain...")
    results = await semantic_search(chat_id, query, top_k=5)
    await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=fit_telegram_text(format_semantic_results(results)))


async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    enabled = toggle_privacy_mode(chat_id)
    await update.message.reply_text(f"Privacy-Mode ist jetzt {'AN' if enabled else 'AUS'}.")


async def cmd_guard_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(describe_guard_status(str(update.effective_chat.id)))


async def cmd_gmail_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(fit_telegram_text(await start_gmail_auth(chat_id)))


async def cmd_gmail_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    payload = get_command_payload(update, context)
    if not payload:
        await update.message.reply_text("Nutzung: /gmail_code <oauth-code>")
        return
    await update.message.reply_text(fit_telegram_text(await finish_gmail_auth(chat_id, payload)))


async def cmd_mailbatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subject, body = parse_email_batch_command(update.message.text or "")
    if not subject or not body:
        await update.message.reply_text("Nutzung: /mailbatch Betreff || Mailtext")
        return

    reply_doc = update.message.reply_to_message.document if update.message.reply_to_message else None
    if reply_doc:
        loading = await update.message.reply_text("Pruefe Liste und baue Email-Vorschau...")
        temp_path = None
        try:
            bot_file = await context.bot.get_file(reply_doc.file_id)
            suffix = os.path.splitext(reply_doc.file_name or ".txt")[1] or ".txt"
            temp_path = await download_telegram_file_to_temp(bot_file, suffix)
            result = await prepare_email_batch_preview(temp_path, chat_id, subject, body)
            if not result.get("success"):
                await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=result["message"])
                return
            pending_email_requests.pop(chat_id, None)
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=loading.message_id,
                text=fit_telegram_text(result["message"]), reply_markup=result.get("keyboard"),
            )
        except Exception as exc:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Mailbatch fehlgeschlagen: {str(exc)[:250]}")
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
        return

    pending_email_requests[chat_id] = {"subject": subject, "body": body}
    await update.message.reply_text("Sende jetzt die Empfaengerliste als Excel, CSV, PDF oder TXT.")


async def handle_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    chat_id = str(query.message.chat.id) if query.message else str(update.effective_chat.id)

    if query.data == "email|confirm":
        reply = await confirm_and_send_batch(chat_id)
    elif query.data == "email|cancel":
        reply = cancel_batch(chat_id)
    else:
        reply = "Unbekannte Email-Aktion."

    try:
        await query.edit_message_text(fit_telegram_text(reply))
    except Exception:
        await query.message.reply_text(fit_telegram_text(reply))


async def cmd_voiceclone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    voice_name = " ".join(context.args).strip() or "MeineVoice"
    reply = update.message.reply_to_message

    if not reply:
        pending_voice_clones[chat_id] = voice_name
        await update.message.reply_text(f"Voice-Clone vorbereitet fÃ¼r '{voice_name}'. {backend_status()}. Schick eine Voice oder Audio-Datei.")
        return

    loading = await update.message.reply_text("Analysiere Referenz...")
    temp_path = None
    try:
        if reply.voice:
            bot_file = await context.bot.get_file(reply.voice.file_id)
            temp_path = await download_telegram_file_to_temp(bot_file, ".ogg")
        elif reply.audio:
            suffix = os.path.splitext(reply.audio.file_name or ".mp3")[1] or ".mp3"
            bot_file = await context.bot.get_file(reply.audio.file_id)
            temp_path = await download_telegram_file_to_temp(bot_file, suffix)
        elif reply.document and is_audio_document(reply.document):
            suffix = os.path.splitext(reply.document.file_name or ".bin")[1] or ".bin"
            bot_file = await context.bot.get_file(reply.document.file_id)
            temp_path = await download_telegram_file_to_temp(bot_file, suffix)
        else:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text="Bitte auf Voice oder Audio-Datei antworten.")
            return

        success, message = await clone_voice_reference(chat_id, voice_name, temp_path)
        if success:
            pending_voice_clones.pop(chat_id, None)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=message)
    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Voice-Clone fehlgeschlagen: {str(exc)[:250]}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


async def cmd_myvoices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(describe_cloned_voices(str(update.effective_chat.id)))


async def cmd_deletevoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    voice_name = get_command_payload(update, context)
    if not voice_name:
        await update.message.reply_text("Nutzung: /deletevoice <name>")
        return
    await update.message.reply_text(delete_cloned_voice(chat_id, voice_name))


async def cmd_speak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    voice_name, text = parse_speak_command(context.args)
    if not voice_name or not text:
        await update.message.reply_text("Nutzung: /speak <voice> <text>")
        return

    loading = await update.message.reply_text(f"'{voice_name}' spricht...")
    try:
        audio_buffer, warning = await synthesize_with_cloned_voice(chat_id, voice_name, text, language="de")
        if not audio_buffer:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=warning or "Voice-Ausgabe fehlgeschlagen.")
            return
        await context.bot.send_audio(chat_id=chat_id, audio=audio_buffer, filename=f"{voice_name}.wav", caption=f"{voice_name}: {text[:180]}")
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        if warning:
            await context.bot.send_message(chat_id=chat_id, text=warning)
    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Sprechen fehlgeschlagen: {str(exc)[:250]}")


# ====================== VOICE DISTORTION ======================
from bot_state import pending_distortion

async def _activate_distortion(update: Update, effect_name: str):
    """Aktiviert einen Distortion-Effekt für diesen Chat (Modus A)."""
    chat_id = str(update.effective_chat.id)
    pending_distortion[chat_id] = effect_name
    preset = EFFECT_PRESETS.get(effect_name, {})
    desc = preset.get("description", effect_name)
    await update.message.reply_text(
        f"{desc}\n\n"
        f"✅ Effekt aktiviert! Schick mir jetzt eine Voice-Nachricht.\n"
        f"Ich antworte automatisch mit dem verzerrten Effekt.\n"
        f"Tippe /stopdistort zum Beenden."
    )


async def cmd_robot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "robot")


async def cmd_deepvoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "deep_voice")


async def cmd_chipmunk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "chipmunk")


async def cmd_demon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "demon")


async def cmd_telephone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "telephone")


async def cmd_echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "echo_chamber")


async def cmd_alien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "alien")


async def cmd_underwater(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "underwater")


async def cmd_radio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "radio")


async def cmd_megaphone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "megaphone")


async def cmd_whisper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "whisper")


async def cmd_monster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "monster")


async def cmd_cyberpunk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "cyberpunk")


async def cmd_cave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "cave")


async def cmd_helium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "helium")


async def cmd_reverse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _activate_distortion(update, "reverse")


async def cmd_stopdistort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if pending_distortion.pop(chat_id, None):
        await update.message.reply_text("🛑 Voice-Effekt-Modus beendet.")
    else:
        await update.message.reply_text("Kein aktiver Voice-Effekt.")


async def cmd_scanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Öffnet die QR-/Barcode-Scanner Mini App."""
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "📱 QR & Barcode Scanner öffnen",
            web_app=WebAppInfo(url=SCANNER_WEBAPP_URL),
        )
    ]])

    await update.message.reply_text(
        "🔍 **Scanner bereit**\n\n"
        "• QR-Codes & Barcodes scannen\n"
        "• Produkte automatisch erkennen\n"
        "• Live-Kamera nutzen\n\n"
        "Tippe auf den Button unten, um den Scanner zu starten:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )




async def cmd_shellgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oeffnet die Neon Shell Game 2077 Mini App."""
    game_url = f"{PUBLIC_APP_BASE_URL}/shellgame"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎰 Neon Shell Game 2077 öffnen",
            web_app=WebAppInfo(url=game_url),
        )
    ]])
    await update.message.reply_text(
        "🎰 **NEON SHELL GAME 2077**\n\n"
        "Willkommen im Cyber-Casino, Choom!\n"
        "Finde die Datenkugel unter den Hütchen und multipliziere deine Credits.\n\n"
        "• Start: 1000 Credits\n"
        "• Gewinn: 3x Einsatz\n"
        "• Vorsicht vor dem Dealer... er betrügt!",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
async def cmd_livevoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ã–ffnet die echte Live Voice Mini App"""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "ðŸŽ™ï¸ Queen Live Voice Ã¶ffnen",
            web_app=WebAppInfo(
                url="https://telllmeeesevn.onrender.com/livevoice"
            )
        )
    ]])
    
    await update.message.reply_text(
        "ðŸ’– **Queen Live Voice Chat** ist bereit!\n\n"
        "DrÃ¼cke auf den Button, um den echten Voice-Chat zu Ã¶ffnen.\n"
        "Mikrofon bleibt aktiv â€“ einfach sprechen.",
        reply_markup=keyboard
    )


# ====================== TEXT TO VIDEO 26 (ttv26) ======================
async def handle_ttv26(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.message.reply_text(
            "âŒ Nutzung:\n"
            "/ttv26 <dein Prompt>\n\n"
            "Beispiele:\n"
            "/ttv26 Eine Katze springt elegant Ã¼ber eine Wiese bei Sonnenuntergang\n"
            "/ttv26 Ein roter Sportwagen fÃ¤hrt nachts durch eine neonbeleuchtete Stadt"
        )
        return

    loading_msg = await update.message.reply_text(f"ðŸŽ¬ Generiere Video...\nPrompt: {prompt[:100]}...")

    try:
        from ttv26 import generate_text_to_video

        video_path, used_model = await generate_text_to_video(
            prompt=prompt,
            duration=5,
            resolution="720P",
            aspect_ratio="16:9"
        )

        await context.bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)

        if video_path and video_path.exists():
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_path, "rb"),
                caption=f"âœ… Video fertig mit {used_model}",
                supports_streaming=True
            )
            video_path.unlink(missing_ok=True)
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="âŒ Video konnte nicht erstellt werden.\n"
                     "Dashscope hat den Prompt wahrscheinlich blockiert (Content Filter)."
            )

    except Exception as e:
        logger.error(f"handle_ttv26 Fehler: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_msg.message_id,
                text=f"âŒ Fehler bei der Video-Generierung:\n{str(e)[:200]}"
            )
        except:
            await context.bot.send_message(chat_id=chat_id, text="âŒ Video-Generierung fehlgeschlagen.")

    finally:
        # Falls es eine globale Task-Variable gibt, zurÃ¼cksetzen
        from ttv26 import active_task_id, active_task_lock
        async with active_task_lock:
            active_task_id = None


# ====================== VOICESTREAM ======================
async def cmd_startstream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    voice_name = " ".join(context.args).strip() or None

    from bot_state import stream_active
    from voicestream import start_live_voice_mode

    # Stream aktivieren
    stream_active[chat_id] = True

    msg = await start_live_voice_mode(chat_id, voice_name, context=context)
    await update.message.reply_text(msg)


async def cmd_endstream(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    from bot_state import stream_active

    if chat_id in stream_active:
        stream_active.pop(chat_id)
        await update.message.reply_text("ðŸŽ™ï¸ **Live Voice Stream beendet.**\nDu bist wieder im normalen Modus.")
    else:
        await update.message.reply_text("âŒ Es lÃ¤uft gerade kein Voice Stream.")






async def cmd_lyria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /lyria <Prompt> – Generiert Musik mit Google Lyria 3 (offizielle API)
    Unterstützt Pro-Modell (länger + bessere Qualität) und gibt Lyrics zurück.
    """
    prompt = " ".join(context.args).strip()

    # Standard-Prompt, falls keiner angegeben wurde
    if not prompt:
        prompt = "upbeat futuristic techno instrumental, energetic club beat"

    # Status-Nachricht
    status_msg = await update.message.reply_text(
        "🎵 **Lyria 3** wird gestartet...\n"
        "Generiere Musik – das kann 15–40 Sekunden dauern ⏳",
        parse_mode="Markdown"
    )

    # Pro-Modell für bessere Qualität (kann bei Fehlschlag auf Clip umschalten)
    use_pro = True
    audio, lyrics = await generate_lyria_music(prompt, use_pro=use_pro)

    # Fallback: Wenn Pro-Modell fehlschlägt, versuchen wir das schnellere Clip-Modell
    if not audio and use_pro:
        await status_msg.edit_text(
            "⚠️ Lyria Pro hat nicht funktioniert – versuche Clip-Modell..."
        )
        use_pro = False
        audio, lyrics = await generate_lyria_music(prompt, use_pro=use_pro)

    if audio:
        # Schöne Caption mit Lyrics (falls vorhanden)
        caption = format_music_caption(prompt, lyrics)

        try:
            await status_msg.edit_text("✅ Musik generiert! Wird gesendet...")
        except Exception:
            pass  # Nachricht ggf. schon gelöscht

        await update.message.reply_audio(
            audio=audio,
            filename="lyria_pro.wav" if use_pro else "lyria_clip.mp3",
            caption=caption,
            parse_mode="Markdown"
        )

        # Optional: kurze Erfolgsmeldung
        await update.message.reply_text(
            f"🎧 **Lyria 3 {'Pro' if use_pro else 'Clip'}** fertig!\n"
            f"Prompt: `{prompt[:100]}`",
            parse_mode="Markdown"
        )

    else:
        # Fehlermeldung mit hilfreichen Hinweisen
        await status_msg.edit_text(
            "❌ **Lyria-Generierung fehlgeschlagen**\n\n"
            "Mögliche Gründe:\n"
            "• `GEMINI_API_KEY` fehlt oder ist ungültig\n"
            "• Der Prompt wurde vom Safety-Filter blockiert\n"
            "• Rate-Limit oder temporärer Ausfall von Google\n"
            "• Zu langer oder zu komplexer Prompt\n\n"
            "Tipps:\n"
            "• Versuche einen einfacheren Prompt (z. B. nur Genre + Stimmung)\n"
            "• Verwende `/suno` als Alternative\n"
            "• Prüfe ob der API-Key in Railway korrekt gesetzt ist"
        )

async def cmd_suno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_prompt = " ".join(context.args).strip()

    if not user_prompt:
        await update.message.reply_text(
            "ðŸŽµ **Suno v4.5 Music AI**\n\n"
            "Schreib /suno gefolgt von deiner Musik-Idee.\n"
            "Beispiel: `/suno Hard techno bass drop with industrial synths`"
        )
        return

    # User-Feedback
    loading = await update.message.reply_text(
        "ðŸŽ¸ **Suno v4.5 komponiert...**\n"
        "Das dauert ca. 1-2 Minuten. Bitte hab einen Moment Geduld! â³"
    )

    try:
        # Aufruf der neuen MP3-Logik
        audio_buffer = await generate_suno_music(user_prompt)

        if audio_buffer:
            # Lade-Nachricht lÃ¶schen
            await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
            
            # MP3 direkt senden
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_buffer,
                filename="suno_v45_track.mp3",
                caption=format_suno_caption(user_prompt),
                parse_mode="Markdown"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text="âŒ **Fehler:** Suno konnte den Song nicht rechtzeitig generieren oder die API ist Ã¼berlastet."
            )
            
    except Exception as e:
        logger.error(f"Fehler im cmd_suno: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text="âŒ Ein technischer Fehler ist aufgetreten."
        )

# Dieser Code ersetzt die cmd_freebeat Funktion in handlers_cmd.py
# (beide doppelten Versionen ersetzen durch diese eine)

async def cmd_freebeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /freebeat <prompt> – Kostenlose KI-Musik via HuggingFace MusicGen.
    Handhabt Cold-Start automatisch mit Live-Status-Updates.
    """
    chat_id = str(update.effective_chat.id)
    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.message.reply_text(
            "🎵 **Kostenlose KI-Musik (MusicGen)**\n\n"
            "Nutzung: `/freebeat <Musik-Idee>`\n\n"
            "Beispiele:\n"
            "• `/freebeat lofi chill beats study music`\n"
            "• `/freebeat upbeat electronic dance floor`\n"
            "• `/freebeat dark ambient cinematic`\n\n"
            "⚠️ Kann 1-3 Minuten dauern wenn das Modell schläft!",
            parse_mode="Markdown"
        )
        return

    loading = await update.message.reply_text(
        "🎹 **MusicGen startet...**\n"
        "Das Modell wacht auf – das kann 1-3 Min dauern. ⏳\n"
        "Ich schreib dir wenn es fertig ist!"
    )

    # Status alle 30s updaten damit Telegram nicht denkt der Bot ist tot
    async def update_status():
        messages = [
            "🎹 Modell lädt... (ca. 1-3 Min) ⏳",
            "🎼 Noch am Komponieren... fast fertig! 🎵",
            "🎧 KI generiert deine Musik... gleich! ✨",
            "⏳ Dauert etwas länger heute... bleib dran! 🌟",
        ]
        i = 0
        while True:
            await asyncio.sleep(30)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=loading.message_id,
                    text=f"{messages[i % len(messages)]}\n\n**Prompt:** {prompt[:80]}",
                    parse_mode="Markdown"
                )
                i += 1
            except Exception:
                break  # Nachricht schon gelöscht oder Fehler

    # Status-Task parallel starten
    status_task = asyncio.create_task(update_status())

    try:
        audio_buffer = await generate_free_music(prompt)
    finally:
        status_task.cancel()  # Status-Updates stoppen

    if audio_buffer:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
        except Exception:
            pass

        await context.bot.send_audio(
            chat_id=chat_id,
            audio=audio_buffer,
            filename="musicgen_track.wav",
            caption=(
                f"✨ **Kostenlose KI-Musik fertig!**\n\n"
                f"**Prompt:** {prompt[:180]}\n"
                f"• Model: MusicGen-Small (Meta/HuggingFace)\n"
                f"• 100% kostenlos 🎵"
            ),
            parse_mode="Markdown"
        )
    else:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=(
                "❌ **MusicGen hat leider nicht geantwortet.**\n\n"
                "Das passiert wenn:\n"
                "• HuggingFace Free Tier überlastet ist\n"
                "• Das Modell nicht rechtzeitig aufgewacht ist\n\n"
                "Einfach nochmal `/freebeat " + prompt[:60] + "` probieren!"
            ),
            parse_mode="Markdown"
        )


# ====================== TEXT TO 3D COMMAND ======================
async def cmd_text_to_3d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    prompt = " ".join(context.args).strip()

    if not prompt:
        await update.message.reply_text(
            "Nutzung: /3d <Beschreibung>\n"
            "Beispiel: /3d a cute robot cat with glossy metal"
        )
        return

    decision = check_rate_limit(chat_id, "text3d")
    if not decision.allowed:
        await update.message.reply_text(decision.message)
        return

    loading = await update.message.reply_text(
        "Generiere 3D-Modell...\n"
        "Kaskade: Tripo -> Meshy -> Luma -> TRELLIS"
    )

    try:
        glb_bytes, model_url, service = await text_to_3d.generate(prompt, chat_id)

        if glb_bytes:
            safe_name = "".join(ch for ch in prompt[:32] if ch.isalnum() or ch in (" ", "-", "_")).strip()
            filename = f"{safe_name or 'text_to_3d_model'}.glb"
            glb_bytes.name = filename
            glb_bytes.seek(0)

            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
            except Exception:
                pass

            await context.bot.send_document(
                chat_id=chat_id,
                document=glb_bytes,
                filename=filename,
                caption=(
                    f"3D-Modell fertig via {service}\n"
                    f"Prompt: {prompt[:220]}"
                ),
            )
            if model_url:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Quelle: {model_url}",
                )
            return

        if model_url:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=(
                    f"3D-Modell erstellt via {service}, konnte aber nicht direkt als Datei geladen werden.\n"
                    f"Download: {model_url}"
                ),
            )
            return

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=(
                "Kein Dienst hat erfolgreich geliefert.\n"
                "Bitte pruefe TRIPO_API_KEY und/oder MESHY_API_KEY in Railway und versuche es erneut."
            ),
        )
    except Exception as exc:
        logger.exception("cmd_text_to_3d failed")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"Fehler bei /3d: {str(exc)[:220]}",
        )


# ====================== README COMMAND ======================
async def cmd_readme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sendet die komplette README als HTML-Dokument"""
    chat_id = str(update.effective_chat.id)

    # Mögliche Dateinamen (mit und ohne Leerzeichen/Klammern)
    possible_names = [
        "Readme (1).html",
        "Readme.html",
        "readme.html",
        "README.html",
        "documentation.html"
    ]

    readme_path = None
    for name in possible_names:
        path = os.path.join(os.path.dirname(__file__), name)
        if os.path.exists(path):
            readme_path = path
            break

    if not readme_path:
        await update.message.reply_text(
            "❌ README-Datei nicht gefunden.\n\n"
            "Aktueller Ordner enthält folgende Dateien:\n"
            f"{os.listdir(os.path.dirname(__file__))}\n\n"
            "Bitte benenne deine Datei um in **README.html** (ohne Leerzeichen und Klammern)."
        )
        return

    loading = await update.message.reply_text("📤 Sende vollständige Dokumentation...")

    try:
        with open(readme_path, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="telllmeeedrei_Dokumentation.html",
                caption=(
                    "📖 **telllmeeedrei – Vollständige Bot-Dokumentation**\n\n"
                    "Features • Commands • Architektur • Audit • Quickstart\n"
                    "Einfach herunterladen und im Browser öffnen."
                ),
                parse_mode="Markdown"
            )
        await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
    except Exception as e:
        logger.error(f"README send error: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler beim Senden:\n{str(e)[:180]}"
        )

async def cmd_diagnose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /diagnose – Öffnet das System-Diagnose Dashboard
    Zeigt Status aller Module, APIs und Konfigurationen
    """
    chat_id = str(update.effective_chat.id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔍 System-Diagnose öffnen", 
            web_app=WebAppInfo(url="https://telllmeeesevn.onrender.com/diagnose")
        )],
        [InlineKeyboardButton("📊 Schnell-Check (Text)", callback_data="diagnose:quick")]
    ])
    
    await update.message.reply_text(
        "🤖 **System-Diagnose**\n\n"
        "Überprüfe alle Module, APIs und Konfigurationen:\n"
        "• API-Key Status\n"
        "• Datenbank-Verbindung\n"
        "• 3D-Converter Provider\n"
        "• KI-Modell Erreichbarkeit\n"
        "• File-System Permissions\n\n"
        "Klicke den Button für das vollständige Dashboard!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def diagnose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback für Schnell-Check ohne Web-App"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "diagnose:quick":
        from test_suite import run_diagnostics
        
        loading = await query.message.reply_text("🧪 Führe Diagnose durch...")
        
        try:
            results = await run_diagnostics()
            
            status_emoji = "✅" if results["overall_status"] == "healthy" else "⚠️"
            text = (
                f"{status_emoji} **Diagnose Ergebnis**\n\n"
                f"• Tests: {results['passed']}/{results['total_tests']} bestanden\n"
                f"• Dauer: {results['duration']}\n"
                f"• Zeit: {results['timestamp'][:10]}\n\n"
            )
            
            # Zeige Fehler
            failures = [r for r in results["results"] if not r["ok"]]
            if failures:
                text += "**Fehler:**\n"
                for f in failures[:5]:  # Max 5 Fehler anzeigen
                    text += f"• {f['category']}/{f['name']}: {f['message'][:50]}\n"
            
            await context.bot.edit_message_text(
                chat_id=loading.chat_id,
                message_id=loading.message_id,
                text=text,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            await context.bot.edit_message_text(
                chat_id=loading.chat_id,
                message_id=loading.message_id,
                text=f"❌ Fehler bei Diagnose: {str(e)[:200]}"
            )


async def cmd_jobqueen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Öffnet JobQueen Landing- oder Starterseite als WebApp."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "👑 JobQueen Workspace öffnen",
            web_app=WebAppInfo(url=f"{PUBLIC_APP_BASE_URL}/starter")
        )],
        [InlineKeyboardButton(
            "🌐 Landing Page",
            web_app=WebAppInfo(url=f"{PUBLIC_APP_BASE_URL}/landing")
        )],
    ])
    await update.message.reply_text(
        "👑 <b>JobQueen – KI-Jobsuche</b>\n\n"
        "Durchsucht 20+ Jobbörsen gleichzeitig.\n"
        "CV-Analyse, Anschreiben, Excel-Export.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def cmd_landme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Öffnet die reine Filip Makarczyk Landing Page (dedizierter Service)"""
    LANDINGPAGE_URL = "https://landingpagefm.onrender.com/"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📄 Landingpage öffnen",
                web_app=WebAppInfo(url=LANDINGPAGE_URL)
            )
        ],
        [
            InlineKeyboardButton(
                "🔗 Im Browser öffnen",
                url=LANDINGPAGE_URL
            )
        ]
    ])

    await update.message.reply_text(
        "🌟 <b>Filip Makarczyk</b> – Hybrid Property Management &amp; KI-Experte\n\n"
        "Hier ist die aktuelle Landingpage:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def cmd_immotracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Öffnet das KI-Immo-Terminal (immoticker) als WebApp-Popup."""
    IMMOTICKER_URL = "https://immoticker.onrender.com/"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 KI-Immo-Terminal öffnen",
                web_app=WebAppInfo(url=IMMOTICKER_URL)
            )
        ],
        [
            InlineKeyboardButton(
                "🔗 Im Browser öffnen",
                url=IMMOTICKER_URL
            )
        ]
    ])

    await update.message.reply_text(
        "📊 <b>KI-Immo-Terminal</b>\n\n"
        "154 validierte RSS-Quellen zu KI &amp; Immobilien (USA/DE) plus Top-Magazinen, "
        "inkl. KI-Chat &amp; LinkedIn-Generator.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


# ====================== SAVE CODE COMMAND ======================
async def cmd_savecode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /savecode – Speichert den gesamten aktuellen Bot-Code ins Brain.
    Ermöglicht 24/7 Code-Zugriff für SuperAgent und normalen Chat.
    """
    chat_id = str(update.effective_chat.id)

    lock = _savecode_locks.setdefault(chat_id, asyncio.Lock())
    if lock.locked():
        await safe_send_message(
            context.bot,
            chat_id,
            "⏳ /savecode läuft bereits. Bitte kurz warten.",
        )
        return
    await lock.acquire()
    try:
        loading = await update.message.reply_text(
            "💾 Scanne und speichere gesamten Code ins Brain...\n"
            "Das kann ein paar Sekunden dauern ⏳",
            connect_timeout=4.0,
            read_timeout=8.0,
            write_timeout=8.0,
            pool_timeout=4.0,
        )

        result = await save_full_code_to_brain(chat_id)

        # Indexiere Brain für semantische Suche
        from bot_utils import create_background_task
        from vectorbrain import index_brain_entries
        create_background_task(index_brain_entries(chat_id, limit=60))

        await safe_edit_message(
            context.bot,
            chat_id=chat_id,
            message_id=loading.message_id,
            text=result,
        )
    except Exception as exc:
        logger.exception("cmd_savecode Fehler")
        try:
            await safe_send_message(
                context.bot,
                chat_id,
                f"❌ Fehler beim Speichern des Codes:\n{str(exc)[:250]}",
            )
        except Exception:
            pass
    finally:
        if lock.locked():
            lock.release()
