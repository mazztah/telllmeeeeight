# handlers_media.py – Photo, Voice, Audio, Document Handler
import logging
import os
import tempfile

from pydub import AudioSegment
from telegram import Update
from telegram.ext import ContextTypes

from bot_state import (
    awaiting_upload, edit_mode_active, last_edit_image_bytes,
    pending_distortion, pending_email_requests, pending_voice_clones, tts_enabled,
)
from bot_ai import generate_response, generate_voice, get_chat_history, transcribe_voice, strip_voice_tags, _persist_chat_turn
from bot_utils import (
    create_background_task, detect_convert_target_from_text,
    download_telegram_file_to_temp, fit_telegram_text, is_audio_document,
    prepare_email_batch_preview, run_file_conversion_pipeline, send_conversion_result,
)
from brain import save_file
from dv import extract_content
from emgen import parse_email_batch_command
from guard import can_process_text
from imgedi import edit_image, format_edit_caption
from vectorbrain import index_brain_entries
from vision import analyze_images
from voicecl import clone_voice_from_file
from voice_distortion import apply_effect
from handler_convert3d import handle_3d_document

logger = logging.getLogger(__name__)


# ==================== HELPER ====================

async def safe_delete_message(bot, chat_id: int, message_id: int):
    """Löscht eine Nachricht sicher, ohne bei Fehlern abzustürzen."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # Nachricht existiert nicht mehr oder wurde schon gelöscht


def _new_temp_path(suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        return temp.name


async def _clone_voice_reference(chat_id: str, voice_name: str, source_path: str) -> tuple[bool, str]:
    from pydub import AudioSegment
    cleanup = [source_path]
    prepared = source_path
    if not source_path.lower().endswith(".wav"):
        wav_path = _new_temp_path(".wav")
        AudioSegment.from_file(source_path).export(wav_path, format="wav")
        cleanup.append(wav_path)
        prepared = wav_path
    try:
        return await clone_voice_from_file(chat_id, prepared, voice_name)
    finally:
        for p in cleanup:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


async def _photo_to_base64(photo, context) -> str:
    """Lädt ein Telegram-Photo herunter und gibt eine Base64-Data-URL zurück."""
    file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    import base64
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


# ==================== HANDLER ====================

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    photo = update.message.photo[-1]

    if edit_mode_active.get(chat_id, False):
        loading = await update.message.reply_text("📸 Bild als Edit-Basis gespeichert...")
        file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await file.download_as_bytearray())
        last_edit_image_bytes[chat_id] = image_bytes
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text="✅ Bild als Basis gespeichert.")
        return

    from bot_state import vision_mode_active
    vision_state = vision_mode_active.pop(chat_id, None)
    if not vision_state:
        return

    loading_msg = await update.message.reply_text("👀 Analysiere Bild...")
    try:
        from bot_state import client
        image_url = await _photo_to_base64(photo, context)
        history = get_chat_history(chat_id)
        user_prompt = (update.message.caption or "").strip()
        if not user_prompt:
            user_prompt = vision_state.get("prompt", "Beschreibe das Bild.")
        reply = await analyze_images(client, chat_id, user_prompt, [image_url], history)
        _persist_chat_turn(chat_id, f"[Vision] {user_prompt}", reply)

        if tts_enabled.get(chat_id, False):
            audio = await generate_voice(reply)
            if audio:
                await context.bot.send_audio(chat_id=chat_id, audio=audio, filename="vision_answer.wav")
                await safe_delete_message(context.bot, chat_id, loading_msg.message_id)
                return
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=strip_voice_tags(reply))
    except Exception as exc:
        logger.exception("Vision-Analyse Fehler")
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=f"Bild-Analyse abgeschmiert 😭: {str(exc)[:200]}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    voice = update.message.voice
    if not voice:
        return

    loading_msg = await update.message.reply_text("Höre zu... 🎤")
    oga_path = wav_path = None

    try:
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp:
            await file.download_to_drive(temp.name)
            oga_path = temp.name

        # Voice Cloning
        pending_voice_name = pending_voice_clones.get(chat_id)
        if pending_voice_name:
            success, message = await _clone_voice_reference(chat_id, pending_voice_name, oga_path)
            if success:
                pending_voice_clones.pop(chat_id, None)
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=message)
            return

        # Voice Distortion
        active_effect = pending_distortion.get(chat_id)
        if active_effect:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=f"Verzerrte mit {active_effect}... 🔊")
            distorted = apply_effect(oga_path, active_effect)
            if distorted:
                await context.bot.send_voice(chat_id=chat_id, voice=distorted, caption=f"✨ {active_effect.replace('_', ' ').title()}")
                await safe_delete_message(context.bot, chat_id, loading_msg.message_id)
            else:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text="❌ Effekt konnte nicht angewendet werden.")
            return

        # Transkribieren
        wav_path = _new_temp_path(".wav")
        AudioSegment.from_file(oga_path, format="ogg").export(wav_path, format="wav")
        user_text = await transcribe_voice(wav_path, language="de")

        if not user_text or len(user_text.strip()) < 2:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text="Nix verstanden 😶")
            return

        from bot_state import stream_active
        if chat_id in stream_active and stream_active.get(chat_id, False):
            await safe_delete_message(context.bot, chat_id, loading_msg.message_id)
            reply_text = await generate_response(chat_id, user_text)
            from voicestream import stream_voice_response
            await stream_voice_response(chat_id=chat_id, text=reply_text, context=context)
            return

        decision = can_process_text(chat_id, user_text, action="chat")
        if not decision.allowed:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=decision.message)
            return

        reply_text = await generate_response(chat_id, user_text)

        if tts_enabled.get(chat_id, False):
            audio_bytes = await generate_voice(reply_text)
            if audio_bytes:
                await context.bot.send_audio(chat_id=chat_id, audio=audio_bytes, filename="response.wav")
            else:
                await context.bot.send_message(chat_id=chat_id, text=strip_voice_tags(reply_text))
        else:
            await context.bot.send_message(chat_id=chat_id, text=strip_voice_tags(reply_text))

        await safe_delete_message(context.bot, chat_id, loading_msg.message_id)

    except Exception:
        logger.exception("Voice Handler Fehler")
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text="Voice-Verarbeitung abgekackt 😵")
        except:
            pass
    finally:
        for path in [oga_path, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except:
                    pass


async def handle_audio_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    audio = update.message.audio
    if not audio:
        return

    caption_raw = (update.message.caption or "").strip()
    pending_voice_name = pending_voice_clones.get(chat_id)
    if not pending_voice_name and caption_raw.lower().startswith("/voiceclone"):
        pending_voice_name = caption_raw[len("/voiceclone"):].strip() or "MeineVoice"

    if not pending_voice_name:
        await update.message.reply_text("Audio erkannt. Für Voice-Cloning: /voiceclone <n> und dann Audio senden.")
        return

    loading = await update.message.reply_text("Speichere Audio als Voice-Referenz...")
    temp_path = None
    try:
        bot_file = await context.bot.get_file(audio.file_id)
        suffix = os.path.splitext(audio.file_name or ".mp3")[1] or ".mp3"
        temp_path = await download_telegram_file_to_temp(bot_file, suffix)
        success, message = await _clone_voice_reference(chat_id, pending_voice_name, temp_path)
        if success:
            pending_voice_clones.pop(chat_id, None)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=message)
    except Exception as exc:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"Audio-Referenz fehlgeschlagen: {str(exc)[:250]}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


async def handle_musik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from thesong import format_song_result, recognize_song
    chat_id = str(update.effective_chat.id)
    if not update.message.reply_to_message or not update.message.reply_to_message.voice:
        await update.message.reply_text("❌ Reply mit /musik auf eine Voice-Nachricht")
        return

    voice = update.message.reply_to_message.voice
    loading = await update.message.reply_text("🎤 AudD läuft... 🔍")
    oga_path = wav_path = None
    try:
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp:
            await file.download_to_drive(temp.name)
            oga_path = temp.name
        wav_path = _new_temp_path(".wav")
        AudioSegment.from_file(oga_path, format="ogg").export(wav_path, format="wav")
        song_result = await recognize_song(wav_path)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=format_song_result(song_result))
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"❌ Erkennung fehlgeschlagen: {str(e)[:100]}")
    finally:
        for path in [oga_path, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass


async def handle_humming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from thesong import format_song_result, recognize_humming
    chat_id = str(update.effective_chat.id)
    if not update.message.reply_to_message or not update.message.reply_to_message.voice:
        await update.message.reply_text("❌ Reply mit /humming auf eine Voice-Nachricht")
        return

    voice = update.message.reply_to_message.voice
    loading = await update.message.reply_text("🎤 Humming-Modus... 🔍")
    oga_path = wav_path = None
    try:
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp:
            await file.download_to_drive(temp.name)
            oga_path = temp.name
        wav_path = _new_temp_path(".wav")
        AudioSegment.from_file(oga_path, format="ogg").export(wav_path, format="wav")
        song_result = await recognize_humming(wav_path)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=format_song_result(song_result))
    except Exception as e:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"❌ Humming fehlgeschlagen: {str(e)[:100]}")
    finally:
        for path in [oga_path, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_3d_document(update, context):
        return

    chat_id = str(update.effective_chat.id)

    from bot_state import vision_mode_active
    vision_state = vision_mode_active.pop(chat_id, None)
    doc = update.message.document
    if vision_state and doc and doc.mime_type and doc.mime_type.startswith("image/"):
        loading_msg = await update.message.reply_text("👀 Analysiere Bild...")
        try:
            from bot_state import client
            file = await context.bot.get_file(doc.file_id)
            image_bytes = bytes(await file.download_as_bytearray())
            import base64
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            ext = (doc.mime_type.split("/")[-1] if "/" in doc.mime_type else "jpeg")
            image_url = f"data:image/{ext};base64,{b64}"
            history = get_chat_history(chat_id)
            user_prompt = (update.message.caption or "").strip()
            if not user_prompt:
                user_prompt = vision_state.get("prompt", "Beschreibe das Bild.")
            reply = await analyze_images(client, chat_id, user_prompt, [image_url], history)
            _persist_chat_turn(chat_id, f"[Vision] {user_prompt}", reply)

            if tts_enabled.get(chat_id, False):
                audio = await generate_voice(reply)
                if audio:
                    await context.bot.send_audio(chat_id=chat_id, audio=audio, filename="vision_answer.wav")
                    await safe_delete_message(context.bot, chat_id, loading_msg.message_id)
                    return
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=strip_voice_tags(reply))
            return
        except Exception as exc:
            logger.exception("Vision-Analyse Fehler (Dokument)")
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading_msg.message_id, text=f"Bild-Analyse abgeschmiert 😭: {str(exc)[:200]}")
            return

    doc = update.message.document
    if not doc:
        return

    caption_raw = (update.message.caption or "").strip()
    caption_lower = caption_raw.lower()
    upload_requested = chat_id in awaiting_upload or caption_lower.startswith("/upload")
    clean_caption = caption_raw[len("/upload"):].strip() if caption_lower.startswith("/upload") else caption_raw
    direct_voice_clone_name = caption_raw[len("/voiceclone"):].strip() or "MeineVoice" if caption_lower.startswith("/voiceclone") else None
    mail_subject, mail_body = parse_email_batch_command(caption_raw)

    loading = await update.message.reply_text("📂 Datei wird analysiert...")
    temp_path = None
    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = bytes(await file.download_as_bytearray())
        suffix = os.path.splitext(doc.file_name or ".bin")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            temp_path = tmp.name

        awaiting_upload.discard(chat_id)

        target_voice_name = direct_voice_clone_name or pending_voice_clones.get(chat_id)
        if target_voice_name:
            if not is_audio_document(doc):
                await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text="Für Voice-Cloning brauche ich eine Audio-Datei.")
                return
            success, message = await _clone_voice_reference(chat_id, target_voice_name, temp_path)
            if success:
                pending_voice_clones.pop(chat_id, None)
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=message)
            return

        email_request = None
        if mail_subject and mail_body:
            email_request = {"subject": mail_subject, "body": mail_body}
        elif chat_id in pending_email_requests:
            email_request = pending_email_requests[chat_id]

        if email_request:
            batch_result = await prepare_email_batch_preview(temp_path, chat_id, email_request["subject"], email_request["body"])
            if batch_result.get("success"):
                pending_email_requests.pop(chat_id, None)
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=loading.message_id,
                    text=fit_telegram_text(batch_result["message"]),
                    reply_markup=batch_result.get("keyboard"),
                )
            else:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=batch_result["message"])
            return

        original_save_result = await save_file(chat_id, file_bytes, doc.file_name or "unnamed_file", doc.mime_type)
        if "ID:" in original_save_result:
            create_background_task(index_brain_entries(chat_id, limit=40))
        summary = extract_content(temp_path)
        convert_target = detect_convert_target_from_text(clean_caption)

        if upload_requested and not clean_caption:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"✅ Datei gespeichert.\n{original_save_result}")
            return

        user_input = f"[DATEI: {doc.file_name} | MIME: {doc.mime_type}]\n{clean_caption}\n\n{summary}"
        reply = await generate_response(chat_id, user_input)

        if convert_target:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=loading.message_id, text=f"🔄 Konvertiere zu {convert_target.upper()}...")
            conv_result = await run_file_conversion_pipeline(
                chat_id=chat_id, file_path=temp_path, target=convert_target,
                source_name=doc.file_name or "uploaded_file", instruction=clean_caption,
            )
            if conv_result["success"] and conv_result.get("output"):
                conv_save = await send_conversion_result(chat_id, context, conv_result)
                if conv_save and conv_save != "Brain deaktiviert":
                    await context.bot.send_message(chat_id=chat_id, text=conv_save)
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"Konvertierung fehlgeschlagen: {conv_result.get('message')}")

        if tts_enabled.get(chat_id, False):
            audio = await generate_voice(reply)
            if audio:
                await context.bot.send_audio(chat_id=chat_id, audio=audio, filename="dv_reply.wav")
            else:
                await context.bot.send_message(chat_id=chat_id, text=strip_voice_tags(reply))
        else:
            await context.bot.send_message(chat_id=chat_id, text=strip_voice_tags(reply))

        if upload_requested:
            await context.bot.send_message(chat_id=chat_id, text=original_save_result)

        # === SICHERES LÖSCHEN (wichtigster Fix) ===
        await safe_delete_message(context.bot, chat_id, loading.message_id)

    except Exception as e:
        logger.exception("Document Handler Fehler")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=loading.message_id,
                text=f"Datei fehlgeschlagen: {str(e)[:150]} 💀"
            )
        except Exception:
            pass
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
