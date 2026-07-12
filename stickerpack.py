# stickerpack.py â€“ Stickerpack Creator mit Auto-Resize, Telegram API Fix & BG-Removal
import asyncio
import logging
import os
import time
from io import BytesIO
from typing import Dict, Tuple

from PIL import Image
from telegram import InputSticker, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import StickerFormat
from telegram.error import BadRequest
from telegram.ext import ContextTypes, filters

from bot_utils import download_telegram_file_to_temp

logger = logging.getLogger(__name__)

# Telegram Sticker Limits
STICKER_MAX_SIZE = 512  # Pixel
STICKER_MAX_FILESIZE_KB = 512
STICKER_MAX_FILESIZE_BYTES = STICKER_MAX_FILESIZE_KB * 1024
MAX_STICKERS_PER_PACK = 120
DEFAULT_STICKER_EMOJI = "\U0001F600"
BG_REMOVAL_TIMEOUT_SEC = int(os.getenv("BG_REMOVAL_TIMEOUT_SEC", "12"))
BG_FALLBACK_TIMEOUT_SEC = int(os.getenv("BG_FALLBACK_TIMEOUT_SEC", "5"))

_pending_packs: Dict[str, dict] = {}

# Zwischenspeicher fÃ¼r Bilder die auf BG-Entscheidung warten
# Format: { chat_id: { "temp_path": str, "suffix": str, "emoji": str } }
_pending_images: Dict[str, dict] = {}


def has_active_sticker_session(chat_id: str) -> bool:
    return chat_id in _pending_packs


def _is_probable_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F1E6 <= cp <= 0x1F1FF  # Flags (regional indicators)
        or 0x1F300 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x26FF
        or 0x2700 <= cp <= 0x27BF
    )


def _is_valid_emoji_token(token: str) -> bool:
    if not token:
        return False

    has_base = False
    for ch in token:
        cp = ord(ch)
        if _is_probable_emoji_char(ch):
            has_base = True
            continue
        # ZWJ + variation selectors + keycap + skin tones.
        if ch in ("\u200d", "\ufe0f", "\ufe0e", "\u20e3"):
            continue
        if 0x1F3FB <= cp <= 0x1F3FF:
            continue
        return False

    return has_base


def _sanitize_sticker_emoji(raw: str) -> str:
    """
    Telegram erwartet ein gueltiges Emoji pro Sticker.
    Falls Caption ungueltig ist, nutzen wir ein sicheres Standard-Emoji.
    """
    if not raw:
        return DEFAULT_STICKER_EMOJI

    text = raw.strip()
    if not text:
        return DEFAULT_STICKER_EMOJI

    token = text.split()[0][:16]
    if _is_valid_emoji_token(token):
        return token

    for ch in text:
        if _is_probable_emoji_char(ch):
            return ch

    return DEFAULT_STICKER_EMOJI


def _optimize_image_for_sticker(input_path: str) -> Tuple[str, bool, str]:
    """
    Optimiert Bild fÃ¼r Telegram Sticker:
    - Resize auf max 512x512 (beibehÃ¤lt Aspect Ratio via thumbnail)
    - Quadratischer Canvas fÃ¼r nicht-quadratische Bilder
    - Komprimierung bis <512KB (PNG -> WebP falls nÃ¶tig)
    """
    try:
        with Image.open(input_path) as img:
            # Konvertiere zu RGBA fÃ¼r Transparenz-UnterstÃ¼tzung
            if img.mode not in ('RGBA', 'RGB'):
                img = img.convert('RGBA')
            
            # Resize auf max 512x512 mit Lanczos (hochwertig)
            img.thumbnail((STICKER_MAX_SIZE, STICKER_MAX_SIZE), Image.Resampling.LANCZOS)
            
            # Quadratischen Canvas erstellen (Telegram empfiehlt 512x512)
            if img.size[0] != img.size[1]:
                max_dim = max(img.size)
                new_img = Image.new('RGBA', (max_dim, max_dim), (255, 255, 255, 0))
                offset = ((max_dim - img.size[0]) // 2, (max_dim - img.size[1]) // 2)
                new_img.paste(img, offset)
                img = new_img
            
            # Speichere als PNG zuerst
            output_path = input_path.rsplit('.', 1)[0] + '_optimized.png'
            
            # Versuche verschiedene QualitÃ¤tsstufen
            for quality in [95, 85, 75, 65]:
                img.save(output_path, 'PNG', optimize=True)
                file_size = os.path.getsize(output_path)
                
                if file_size <= STICKER_MAX_FILESIZE_BYTES:
                    return output_path, True, f"{img.size[0]}x{img.size[1]}px, {file_size/1024:.1f}KB"
                
                # Wenn PNG zu groÃŸ, versuche WebP (bessere Kompression)
                if quality <= 85:
                    webp_path = input_path.rsplit('.', 1)[0] + '_optimized.webp'
                    img.save(webp_path, 'WEBP', quality=quality, method=6)
                    webp_size = os.path.getsize(webp_path)
                    
                    if webp_size <= STICKER_MAX_FILESIZE_BYTES:
                        # LÃ¶sche zu groÃŸes PNG
                        if os.path.exists(output_path):
                            os.unlink(output_path)
                        return webp_path, True, f"{img.size[0]}x{img.size[1]}px (WebP), {webp_size/1024:.1f}KB"
            
            # Letzter Versuch mit maximaler Kompression
            img.save(output_path, 'PNG', optimize=True)
            final_size = os.path.getsize(output_path)
            
            if final_size <= STICKER_MAX_FILESIZE_BYTES:
                return output_path, True, f"{img.size[0]}x{img.size[1]}px, {final_size/1024:.1f}KB (hohe Kompression)"
            else:
                return output_path, False, f"Zu groÃŸ: {final_size/1024:.1f}KB (max {STICKER_MAX_FILESIZE_KB}KB)"
                
    except Exception as e:
        logger.exception("Fehler bei Bildoptimierung")
        return input_path, False, f"Fehler: {str(e)}"


def _remove_background(input_path: str) -> str:
    """
    Entfernt den Hintergrund eines Bildes mit rembg.
    Gibt den Pfad zur neuen PNG-Datei zurÃ¼ck.
    """
    from rembg import remove

    with open(input_path, 'rb') as f:
        input_data = f.read()

    output_data = remove(input_data)

    out_path = input_path.rsplit('.', 1)[0] + '_nobg.png'
    with open(out_path, 'wb') as f:
        f.write(output_data)

    return out_path


def _safe_unlink(path: str) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        logger.debug("Datei konnte nicht geloescht werden: %s", path)


def _has_usable_alpha(image_path: str) -> bool:
    """Prueft, ob das Ergebnisbild wirklich nutzbare Transparenz enthaelt."""
    with Image.open(image_path).convert('RGBA') as img:
        alpha = img.getchannel('A')
        min_alpha, _ = alpha.getextrema()
        if min_alpha >= 250:
            return False

        total = img.size[0] * img.size[1]
        transparent = 0
        opaque = 0
        for px in alpha.getdata():
            if px < 245:
                transparent += 1
            if px > 10:
                opaque += 1

        if transparent < max(50, int(total * 0.01)):
            return False
        if opaque < max(50, int(total * 0.02)):
            return False
        return True


def _remove_background_corner_color(input_path: str) -> str:
    """
    Fallback 1:
    Entfernt Pixel, die der gemittelten Eckfarbe aehnlich sind.
    """
    with Image.open(input_path).convert('RGBA') as src:
        img = src.copy()
        w, h = img.size
        px = img.load()

        corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
        bg_r = sum(c[0] for c in corners) // 4
        bg_g = sum(c[1] for c in corners) // 4
        bg_b = sum(c[2] for c in corners) // 4

        hard = 42 * 3
        soft = 72 * 3
        span = max(1, soft - hard)

        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                dist = abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b)
                if dist <= hard:
                    px[x, y] = (r, g, b, 0)
                elif dist <= soft:
                    keep = (dist - hard) / span
                    px[x, y] = (r, g, b, int(a * keep))

        out_path = input_path.rsplit('.', 1)[0] + '_nobg_corner.png'
        img.save(out_path, 'PNG')
        return out_path


def _remove_background_light_bg(input_path: str) -> str:
    """
    Fallback 2:
    Entfernt sehr helle, entsaettigte Hintergruende (weiss/hellgrau).
    """
    with Image.open(input_path).convert('RGBA') as src:
        img = src.copy()
        w, h = img.size
        px = img.load()

        corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
        lumas = [int((c[0] * 299 + c[1] * 587 + c[2] * 114) / 1000) for c in corners]
        bg_luma = sum(lumas) // len(lumas)
        if bg_luma < 145:
            raise ValueError("Heller Hintergrund nicht erkannt")

        hard = min(252, max(220, bg_luma + 8))
        soft = min(255, hard + 22)
        span = max(1, soft - hard)

        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                luma = int((r * 299 + g * 587 + b * 114) / 1000)
                sat = max(r, g, b) - min(r, g, b)
                if luma >= hard and sat <= 35:
                    px[x, y] = (r, g, b, 0)
                elif luma >= hard - 8 and sat <= 45:
                    fade = min(1.0, max(0.0, (luma - (hard - 8)) / span))
                    px[x, y] = (r, g, b, int(a * (1.0 - fade)))

        out_path = input_path.rsplit('.', 1)[0] + '_nobg_light.png'
        img.save(out_path, 'PNG')
        return out_path


async def _remove_background_with_fallbacks(input_path: str) -> Tuple[str, str]:
    """
    3-stufiger BG-Removal:
    1) rembg
    2) Eckfarben-Heuristik
    3) Heller-Hintergrund-Heuristik
    Falls alles fehlschlaegt: Originalbild verwenden.
    """
    methods = [
        ("rembg", _remove_background, BG_REMOVAL_TIMEOUT_SEC),
        ("fallback-1 (eckfarbe)", _remove_background_corner_color, BG_FALLBACK_TIMEOUT_SEC),
        ("fallback-2 (heller-bg)", _remove_background_light_bg, BG_FALLBACK_TIMEOUT_SEC),
    ]

    for method_name, method_fn, timeout_sec in methods:
        candidate_path = None
        try:
            candidate_path = await asyncio.wait_for(
                asyncio.to_thread(method_fn, input_path),
                timeout=timeout_sec,
            )
            if not candidate_path or not os.path.exists(candidate_path):
                raise RuntimeError("Keine Ausgabedatei erzeugt")

            usable = await asyncio.to_thread(_has_usable_alpha, candidate_path)
            if not usable:
                raise RuntimeError("Ergebnis ohne brauchbare Transparenz")

            return candidate_path, method_name
        except Exception as exc:
            logger.warning(
                "BG-Removal %s fehlgeschlagen (%s): %s",
                method_name,
                type(exc).__name__,
                exc,
            )
            if candidate_path and candidate_path != input_path:
                _safe_unlink(candidate_path)

    return input_path, "fallback-3 (original)"


async def _safe_edit_query_message(query, text: str) -> None:
    try:
        await query.edit_message_text(text)
    except BadRequest as exc:
        logger.info("Callback-Nachricht konnte nicht editiert werden: %s", exc)


async def _finalize_sticker_image(chat_id: str, temp_path: str, emoji: str, context, loading_message):
    """
    Optimiert und fÃ¼gt ein Bild dem laufenden Pack hinzu.
    Wird sowohl von BG-Callback als auch direkt (kein BG) gerufen.
    """
    pack_data = _pending_packs.get(chat_id)
    if not pack_data:
        return

    try:
        optimized_path, success, msg = _optimize_image_for_sticker(temp_path)

        # Cleanup Original (falls abweichend)
        if optimized_path != temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass

        if not success:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_message.message_id,
                text=f"âŒ {msg}\n\nVersuche ein kleineres Bild."
            )
            if os.path.exists(optimized_path):
                os.unlink(optimized_path)
            return

        pack_data["stickers"].append((optimized_path, emoji))
        pack_data["count"] += 1
        remaining = MAX_STICKERS_PER_PACK - pack_data["count"]

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_message.message_id,
            text=f"âœ… Bild {pack_data['count']} ({emoji})\n"
                 f"_{msg}_\n"
                 f"({remaining} frei) â†’ Mehr senden oder `/done`",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Fehler in _finalize_sticker_image: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_message.message_id,
            text="âŒ Fehler beim Verarbeiten. Nutze JPG/PNG <10MB."
        )


async def cmd_stickerpack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Startet Stickerpack-Erstellung"""
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "ðŸ“¦ **Stickerpack Creator**\n\n"
            "Nutze: `/stickerpack <Titel>`\n"
            "Beispiel: `/stickerpack Meine coolen Bilder`\n\n"
            f"ðŸ“‹ **Limits:**\n"
            f"â€¢ Max {MAX_STICKERS_PER_PACK} Sticker\n"
            f"â€¢ Auto-Resize auf {STICKER_MAX_SIZE}x{STICKER_MAX_SIZE}px\n"
            f"â€¢ Auto-Kompression auf <{STICKER_MAX_FILESIZE_KB}KB\n"
            f"â€¢ Formate: JPG, PNG, WebP\n"
            f"â€¢ Optional: Hintergrund automatisch entfernen\n\n"
            "Sende Bilder â†’ `/done` wenn fertig",
            parse_mode="Markdown"
        )
        return

    title = " ".join(context.args).strip()
    
    if len(title) > 64:
        await update.message.reply_text("âŒ Titel max 64 Zeichen.")
        return
    
    bot_username = context.bot.username or "bot"
    timestamp = int(time.time())
    pack_name = f"pack_{chat_id[:8]}_{timestamp}_by_{bot_username}"
    
    _pending_packs[chat_id] = {
        "title": title,
        "name": pack_name,
        "stickers": [],
        "user_id": user_id,
        "count": 0
    }

    await update.message.reply_text(
        f"âœ… **Pack gestartet:** _{title}_\n"
        f"ðŸ–¼ï¸ Sende Bilder (Emoji als Caption optional)\n"
        f"âœ… `/done` wenn fertig",
        parse_mode="Markdown"
    )


async def collect_sticker_for_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sammelt Bilder und fragt nach Hintergrund-Entfernung"""
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in _pending_packs:
        return
    
    pack_data = _pending_packs[chat_id]
    
    # 120 Sticker Limit prÃ¼fen
    if pack_data["count"] >= MAX_STICKERS_PER_PACK:
        await update.message.reply_text(
            f"âš ï¸ **Limit erreicht!** ({MAX_STICKERS_PER_PACK}/120)\n"
            "Nutze `/done` um zu erstellen."
        )
        return
    
    # Datei ermitteln
    file_obj = None
    emoji = DEFAULT_STICKER_EMOJI
    
    if update.message.photo:
        file_obj = update.message.photo[-1]
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
        file_obj = update.message.document
    else:
        return
    
    # Emoji aus Caption
    if update.message.caption:
        emoji = _sanitize_sticker_emoji(update.message.caption)
    
    loading = await update.message.reply_text("â³ Bild wird geladen...")
    
    try:
        # Download
        bot_file = await context.bot.get_file(file_obj.file_id)
        suffix = ".jpg" if update.message.photo else (os.path.splitext(getattr(file_obj, 'file_name', '.jpg'))[1] or ".jpg")
        temp_path = await download_telegram_file_to_temp(bot_file, suffix)

        # â”€â”€ NEU: Bild zwischenspeichern, Nutzer fragen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        _pending_images[chat_id] = {
            "temp_path": temp_path,
            "emoji": emoji,
            "loading_message_id": loading.message_id,
        }

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("âœ‚ï¸ Ja, Hintergrund entfernen", callback_data=f"bg_remove:{chat_id}"),
                InlineKeyboardButton("âž¡ï¸ Nein, so lassen",           callback_data=f"bg_keep:{chat_id}"),
            ]
        ])

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text="ðŸ–¼ï¸ Bild empfangen!\nSoll der Hintergrund entfernt werden?",
            reply_markup=keyboard,
        )
        # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    except Exception as e:
        logger.error(f"Fehler beim Download: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text="âŒ Fehler beim Verarbeiten. Nutze JPG/PNG <10MB."
        )


async def handle_bg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    CallbackQueryHandler fÃ¼r Hintergrund-Entscheidung.
    Muss in main.py registriert werden:
        application.add_handler(CallbackQueryHandler(handle_bg_callback, pattern=r"^bg_(remove|keep):"))
    """
    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
    except BadRequest as exc:
        # Expired callback IDs can still carry useful payloads. Continue processing.
        if "Query is too old" in str(exc) or "query id is invalid" in str(exc):
            logger.info("Abgelaufene CallbackQuery erkannt, verarbeite trotzdem weiter")
        else:
            raise

    data = query.data  # z.B. "bg_remove:-100123456" oder "bg_keep:-100123456"
    action, chat_id = data.split(":", 1)

    pending = _pending_images.pop(chat_id, None)
    if not pending:
        await _safe_edit_query_message(query, "Kein Bild mehr vorhanden. Bitte erneut senden.")
        return

    temp_path = pending["temp_path"]
    emoji     = pending["emoji"]

    # Fake-Loading-Message-Objekt (edit via message aus callback)
    class _Msg:
        message_id = pending["loading_message_id"]

    loading_msg = _Msg()

    if action == "bg_remove":
        await _safe_edit_query_message(query, "Hintergrund wird entfernt...")
        no_bg_path, method = await _remove_background_with_fallbacks(temp_path)
        if no_bg_path != temp_path:
            _safe_unlink(temp_path)
            temp_path = no_bg_path
            await _safe_edit_query_message(query, f"Hintergrund entfernt ({method}). Optimiere Bild...")
        else:
            logger.warning("Alle BG-Removal Methoden fehlgeschlagen, nutze Originalbild")
            await _safe_edit_query_message(
                query,
                "Hintergrund konnte nicht entfernt werden (Fallback 3). Nutze Original und optimiere...",
            )
    else:
        await _safe_edit_query_message(query, "Optimiere Bild...")

    await _finalize_sticker_image(chat_id, temp_path, emoji, context, loading_msg)


async def finish_stickerpack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Erstellt das Pack - KORRIGIERT fÃ¼r python-telegram-bot v22+"""
    chat_id = str(update.effective_chat.id)
    
    if chat_id not in _pending_packs:
        await update.message.reply_text("Kein aktives Pack. Starte mit `/stickerpack <Titel>`")
        return
    
    pack_data = _pending_packs[chat_id]
    stickers_list = pack_data["stickers"]
    user_id = pack_data["user_id"]
    
    if not stickers_list:
        await update.message.reply_text("Keine Bilder. Vorgang abgebrochen.")
        del _pending_packs[chat_id]
        return
    
    loading = await update.message.reply_text(
        f"â³ Erstelle {len(stickers_list)} Sticker...\n(Kann eine Minute dauern)"
    )
    
    temp_files = [s[0] for s in stickers_list]
    added = 0
    
    try:
        # ERSTER STICKER (Pack erstellen)
        first_path, first_emoji = stickers_list[0]
        first_emoji = _sanitize_sticker_emoji(first_emoji)
        
        with open(first_path, 'rb') as f:
            upload = await context.bot.upload_sticker_file(
                user_id=user_id,
                sticker=f,
                sticker_format=StickerFormat.STATIC
            )
        
        await context.bot.create_new_sticker_set(
            user_id=user_id,
            name=pack_data["name"],
            title=pack_data["title"],
            stickers=[InputSticker(
                sticker=upload.file_id,
                emoji_list=[first_emoji],
                format=StickerFormat.STATIC
            )]
        )
        added = 1

        # Kurz warten bis Telegram das Pack propagiert hat (verhindert Stickerset_invalid)
        await asyncio.sleep(1)

        # RESTLICHE STICKER
        for path, emoji in stickers_list[1:]:
            try:
                emoji = _sanitize_sticker_emoji(emoji)
                with open(path, 'rb') as f:
                    upload = await context.bot.upload_sticker_file(
                        user_id=user_id,
                        sticker=f,
                        sticker_format=StickerFormat.STATIC
                    )
                
                await context.bot.add_sticker_to_set(
                    user_id=user_id,
                    name=pack_data["name"],
                    sticker=InputSticker(
                        sticker=upload.file_id,
                        emoji_list=[emoji],
                        format=StickerFormat.STATIC
                    )
                )
                added += 1
            except Exception as e:
                logger.warning(f"Sticker fehlgeschlagen: {e}")
                continue
        
        # Erfolg
        link = f"https://t.me/addstickers/{pack_data['name']}"
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"âœ… **Pack fertig!**\n\n"
                 f"ðŸŽ¨ **{pack_data['title']}**\n"
                 f"ðŸ“¦ {added} Sticker\n\n"
                 f"[ðŸ‘‰ Ã–ffnen]({link})",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.exception("Pack-Fehler")
        error_msg = str(e)
        if "Stickerpack title is already occupied" in error_msg:
            hint = "Ein Pack mit diesem Namen existiert bereits."
        elif "invalid file" in error_msg:
            hint = "Ein Bildformat wird nicht akzeptiert. Nutze JPG/PNG."
        else:
            hint = error_msg[:150]
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"âŒ Fehler: {hint}"
        )
    
    finally:
        for path in temp_files:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except:
                pass
        if chat_id in _pending_packs:
            del _pending_packs[chat_id]

