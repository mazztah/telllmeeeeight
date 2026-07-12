# handlers_chat.py – Text-Nachrichten, YouTube-Erkennung, Websuche
# ═══════════════════════════════════════════════════════════════════════════════
# ÄNDERUNGEN:
#   • send_chat_action("typing") vor allen langen Operationen (Groq, YouTube, Suche)
#   • Alle langen Calls mit asyncio.timeout(30) geschützt → kein ewiges Hängen
#   • safe_send_long statt safe_send_message für Groq-Antworten (automatische Chunks)
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot_state import (
    edit_mode_active,
    last_edit_image_bytes,
    tts_enabled,
    youtube_results,
    safe_send_message,
    safe_send_long,
    _send_typing,
)

from bot_ai import generate_response, generate_voice, strip_voice_tags
from bot_utils import fit_telegram_text
from guard import can_process_text
from imgedi import edit_image, format_edit_caption
from search import format_search_results_for_user, web_search
from ytscript import (
    build_youtube_export_file, extract_youtube_url,
    format_youtube_result_for_user, get_youtube_script,
)
from handlers_cmd import build_youtube_button_overview, get_youtube_cache_key

logger = logging.getLogger(__name__)

# Timeout-Konstanten (Sekunden)
_GROQ_TIMEOUT = 30
_YOUTUBE_TIMEOUT = 45
_SEARCH_TIMEOUT = 20
_IMAGE_EDIT_TIMEOUT = 60


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()
    if not text:
        return

    decision = can_process_text(chat_id, text, action="chat")
    if not decision.allowed:
        await safe_send_message(context.bot, chat_id, decision.message)
        return

    # ── Edit-Modus ─────────────────────────────────────────────────────────────
    if edit_mode_active.get(chat_id, False):
        if chat_id not in last_edit_image_bytes:
            await safe_send_message(context.bot, chat_id, "❌ Noch kein Bild als Basis vorhanden.")
            return

        loading = await update.message.reply_text("🖌️ Editiere dein Bild...")

        try:
            async with asyncio.timeout(_IMAGE_EDIT_TIMEOUT):
                edited = await edit_image(last_edit_image_bytes[chat_id], text)
        except asyncio.TimeoutError:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text="❌ Bild-Editing Timeout – bitte erneut versuchen.",
            )
            return
        except Exception as e:
            logger.exception("edit_image Fehler")
            edited = None

        if edited:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=edited,
                caption=format_edit_caption(text),
                parse_mode="Markdown",
            )
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=loading.message_id)
            except Exception:
                pass
        else:
            await safe_send_message(context.bot, chat_id, "❌ Editing fehlgeschlagen.")
        return

    # ── YouTube-Link ───────────────────────────────────────────────────────────
    youtube_url = extract_youtube_url(text)
    if youtube_url:
        # Sofortiges Feedback + Typing
        loading = await update.message.reply_text("🎬 YouTube erkannt … hole Transcript …")
        await _send_typing(context.bot, chat_id)

        try:
            async with asyncio.timeout(_YOUTUBE_TIMEOUT):
                yt_result = await get_youtube_script(youtube_url)

            if not yt_result.get("success"):
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=loading.message_id,
                    text=f"❌ YouTube fehlgeschlagen:\n{yt_result.get('error', '')[:250]}",
                )
                return

            cache_key = get_youtube_cache_key(chat_id, yt_result["video_id"])
            youtube_results[cache_key] = yt_result

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=format_youtube_result_for_user(yt_result),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=build_youtube_button_overview(cache_key),
            )

            export_file = build_youtube_export_file(yt_result)
            await context.bot.send_document(
                chat_id=chat_id,
                document=export_file,
                filename=getattr(export_file, "name", f"youtube_{yt_result['video_id']}.txt"),
                caption="📄 Transcript + Zusammenfassung + Beschreibung",
            )

        except asyncio.TimeoutError:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text="⏱️ YouTube-Verarbeitung Timeout – bitte erneut versuchen.",
            )
        except Exception as e:
            logger.exception("YouTube-Verarbeitung fehlgeschlagen")
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=loading.message_id,
                    text=f"❌ YouTube fehlgeschlagen:\n{str(e)[:250]}",
                )
            except Exception:
                pass
        return

    # ── Websuche (?query / !query) ─────────────────────────────────────────────
    if text.startswith(("?", "!")) and len(text) > 2:
        query = text[1:].strip()
        loading = await update.message.reply_text(f'🔍 Suche nach "{query}" …')
        await _send_typing(context.bot, chat_id)

        try:
            async with asyncio.timeout(_SEARCH_TIMEOUT):
                search_result = await asyncio.to_thread(web_search, query, 7, "de", "de", None)
            text_result = (
                format_search_results_for_user(search_result)
                if search_result.get("success")
                else "❌ Suche fehlgeschlagen."
            )
        except asyncio.TimeoutError:
            text_result = "⏱️ Suche Timeout – bitte erneut versuchen."
        except Exception as e:
            logger.exception("web_search Fehler")
            text_result = f"❌ Suche fehlgeschlagen: {str(e)[:200]}"

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=text_result,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            await safe_send_message(context.bot, chat_id, text_result)
        return

    # ── Normaler Chat (Groq) ────────────────────────────────────────────────────
    # Sofortiges Typing-Feedback bevor Groq antwortet
    await _send_typing(context.bot, chat_id)

    try:
        async with asyncio.timeout(_GROQ_TIMEOUT):
            reply = await generate_response(chat_id, text)
    except asyncio.TimeoutError:
        logger.warning(f"generate_response Timeout für {chat_id}")
        await safe_send_message(
            context.bot, chat_id,
            "⏱️ Antwort-Timeout – Groq braucht gerade zu lange. Bitte nochmal versuchen.",
        )
        return
    except Exception as e:
        logger.exception("generate_response Fehler")
        await safe_send_message(
            context.bot, chat_id,
            f"❌ Fehler bei der Antwort-Generierung: {str(e)[:200]}",
        )
        return

    # TTS
    if tts_enabled.get(chat_id, False):
        try:
            audio_bytes = await generate_voice(reply)
            if audio_bytes:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_bytes,
                    filename="response.wav",
                )
                return
        except Exception as e:
            logger.warning(f"TTS fehlgeschlagen: {e}")

    # Robuste Textnachricht – safe_send_long teilt automatisch bei > 4000 Zeichen
    await safe_send_long(context.bot, chat_id, strip_voice_tags(reply))