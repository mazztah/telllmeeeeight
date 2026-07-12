import asyncio
import logging
import os
import random
import re
import tempfile
import textwrap
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

MOVIEPY_AVAILABLE = False
MOVIEPY_IMPORT_ERROR = ""
MOVIEPY_RUNTIME_COMPATIBLE = False

try:
    # MoviePy v1.x
    from moviepy.editor import (  # type: ignore
        CompositeVideoClip,
        ImageClip,
        TextClip,
        concatenate_videoclips,
    )
    MOVIEPY_AVAILABLE = True
except Exception as exc_editor:
    MOVIEPY_IMPORT_ERROR = f"moviepy.editor import failed: {exc_editor}"
    try:
        # MoviePy v2.x often exposes symbols at top-level
        from moviepy import (  # type: ignore
            CompositeVideoClip,
            ImageClip,
            TextClip,
            concatenate_videoclips,
        )
        MOVIEPY_AVAILABLE = True
    except Exception as exc_top_level:
        MOVIEPY_IMPORT_ERROR = (
            f"{MOVIEPY_IMPORT_ERROR} | moviepy top-level import failed: {exc_top_level}"
        )

if MOVIEPY_AVAILABLE:
    MOVIEPY_RUNTIME_COMPATIBLE = hasattr(ImageClip, "set_duration") and hasattr(ImageClip, "resize")
    if not MOVIEPY_RUNTIME_COMPATIBLE:
        extra = "moviepy API not compatible with this renderer (missing set_duration/resize)"
        MOVIEPY_IMPORT_ERROR = f"{MOVIEPY_IMPORT_ERROR} | {extra}".strip(" |")

logger = logging.getLogger(__name__)

EFFECTS = {
    "bounce": "Huepfen",
    "zoom": "Dynamischer Zoom",
    "pulse": "Pulsieren",
    "spin": "Drehen",
    "wave": "Welle",
    "glitch": "Glitch",
    "fireworks": "Feuerwerk",
    "blackhole": "Blackhole",
    "mirror": "Mirror",
    "pixelate": "Pixelate",
    "portal": "Portal",
    "shockwave": "Shockwave",
    "ghost": "Ghost",
    "fractal": "Fractal",
}

SPEED_CONFIG = {
    "slow": {"fps": 20, "multiplier": 0.7},
    "normal": {"fps": 30, "multiplier": 1.0},
    "fast": {"fps": 40, "multiplier": 1.4},
}

_PENDING_GIF_SESSIONS: Dict[str, Dict[str, Any]] = {}
MAX_GIF_IMAGES = 12
_RESAMPLING = getattr(Image, "Resampling", Image)
RESAMPLE_LANCZOS = _RESAMPLING.LANCZOS
RESAMPLE_BICUBIC = _RESAMPLING.BICUBIC
RESAMPLE_NEAREST = _RESAMPLING.NEAREST


def _sanitize_duration(value: float) -> float:
    return max(1.0, min(12.0, value))


def _cleanup_paths(paths: List[str]) -> None:
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except Exception:
            logger.debug("Temp file cleanup failed: %s", path)


def _reset_session(chat_id: str) -> None:
    session = _PENDING_GIF_SESSIONS.pop(chat_id, None)
    if not session:
        return
    _cleanup_paths(session.get("image_paths", []))


def has_active_gif_session(chat_id: str) -> bool:
    return chat_id in _PENDING_GIF_SESSIONS


def _pick_image_obj(message) -> Any:
    if not message:
        return None
    if message.photo:
        return message.photo[-1]
    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        return message.document
    return None


def _collect_direct_images(update: Update) -> List[Any]:
    message = update.message
    if not message:
        return []

    image_objs: List[Any] = []
    reply = message.reply_to_message
    if reply:
        ref = _pick_image_obj(reply)
        if ref:
            image_objs.append(ref)

    current = _pick_image_obj(message)
    if current:
        image_objs.append(current)

    return image_objs


def _temp_image_path(chat_id: str, idx: int) -> str:
    base = tempfile.gettempdir()
    return os.path.join(base, f"gif_{chat_id}_{int(time.time() * 1000)}_{idx}_{random.randint(1000, 9999)}.jpg")


def _parse_gif_args(args: List[str]) -> Dict[str, Any]:
    effect = "bounce"
    custom_text: Optional[str] = None
    text_position = "bottom"
    speed = "normal"
    duration = 4.0
    roast_mode = False

    work = list(args or [])

    if work and work[0].lower() in EFFECTS:
        effect = work.pop(0).lower()
    elif work and work[0].lower() == "multi":
        work.pop(0)

    raw = " ".join(work).strip()
    if raw:
        if re.search(r"\b(roasting|rosting|roast)\b", raw, re.IGNORECASE):
            roast_mode = True
            raw = re.sub(r"\b(roasting|rosting|roast)\b", "", raw, flags=re.IGNORECASE).strip()

        speed_match = re.search(r"\b(slow|normal|fast)\b", raw, re.IGNORECASE)
        if speed_match:
            speed = speed_match.group(1).lower()
            raw = re.sub(r"\b(slow|normal|fast)\b", "", raw, flags=re.IGNORECASE).strip()

        pos_match = re.search(r"\b(top|center|middle|bottom)\b", raw, re.IGNORECASE)
        if pos_match:
            text_position = pos_match.group(1).lower().replace("middle", "center")
            raw = re.sub(r"\b(top|center|middle|bottom)\b", "", raw, flags=re.IGNORECASE).strip()

        dur_match = re.search(r"(\d+\.?\d*)$", raw)
        if dur_match:
            duration = float(dur_match.group(1))
            raw = raw[:dur_match.start()].strip()

        text_match = re.search(r'"([^"]+)"', raw)
        if text_match:
            custom_text = text_match.group(1).strip()
            raw = raw.replace(text_match.group(0), "").strip()

        if not custom_text and raw:
            custom_text = raw

    duration = _sanitize_duration(duration)

    return {
        "effect": effect,
        "custom_text": custom_text,
        "text_position": text_position,
        "speed": speed,
        "duration": duration,
        "roast_mode": roast_mode,
    }


def _generate_roast_text(image_path: str) -> str:
    """
    Generiert einen milden, bildbezogenen Roast-Text aus einfachen Bildmerkmalen.
    """
    with Image.open(image_path).convert("RGB") as img:
        w, h = img.size
        sample = img.resize((64, 64))
        stat = ImageStat.Stat(sample)
        avg_r, avg_g, avg_b = stat.mean
        brightness = (avg_r * 299 + avg_g * 587 + avg_b * 114) / 1000

    if brightness < 70:
        light_desc = "so dunkel, dass selbst mein WLAN die Orientierung verliert"
    elif brightness < 150:
        light_desc = "wie der Mittelweg zwischen Kunst und Verwirrung"
    else:
        light_desc = "heller als deine Ausrede, warum das nicht cringe sein soll"

    if avg_r >= avg_g and avg_r >= avg_b:
        color_desc = "rot-lastig"
    elif avg_g >= avg_r and avg_g >= avg_b:
        color_desc = "gruen-lastig"
    else:
        color_desc = "blau-lastig"

    if w > h * 1.25:
        frame_desc = "Breitbild-Drama"
    elif h > w * 1.25:
        frame_desc = "Portrait-Modus mit Hauptcharakter-Syndrom"
    else:
        frame_desc = "quadratisch wie eine mutige Design-Entscheidung"

    options = [
        f"{frame_desc}, {color_desc}, und trotzdem {light_desc}.",
        f"Dieses Bild ist {color_desc} und {light_desc}. Legend of Overconfidence.",
        f"{frame_desc}: stylisch geplant, chaotisch geliefert - aber ich respektiere den Mut.",
    ]
    return random.choice(options)


async def _download_image_objs(chat_id: str, context: ContextTypes.DEFAULT_TYPE, image_objs: List[Any]) -> List[str]:
    paths: List[str] = []
    for idx, obj in enumerate(image_objs):
        bot_file = await context.bot.get_file(obj.file_id)
        path = _temp_image_path(chat_id, idx)
        await bot_file.download_to_drive(path)
        paths.append(path)
    return paths


async def handle_gif_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not MOVIEPY_AVAILABLE or not MOVIEPY_RUNTIME_COMPATIBLE:
        logger.warning(
            "MoviePy fast renderer unavailable, using Pillow fallback: %s",
            MOVIEPY_IMPORT_ERROR or "unknown import error",
        )

    chat_id = str(update.effective_chat.id)
    cfg = _parse_gif_args(context.args)
    direct_images = _collect_direct_images(update)

    if direct_images:
        loading = await update.message.reply_text(
            f"GIF wird erstellt ({cfg['effect']}, {cfg['speed']})..."
        )
        image_paths: List[str] = []
        try:
            image_paths = await _download_image_objs(chat_id, context, direct_images)
            await _render_and_send_gif(
                chat_id=chat_id,
                context=context,
                image_paths=image_paths,
                effect=cfg["effect"],
                duration=cfg["duration"],
                text=cfg["custom_text"],
                text_position=cfg["text_position"],
                speed=cfg["speed"],
                roast_mode=cfg["roast_mode"],
                loading_message_id=loading.message_id,
            )
        finally:
            _cleanup_paths(image_paths)
        return

    _reset_session(chat_id)
    _PENDING_GIF_SESSIONS[chat_id] = {
        "effect": cfg["effect"],
        "duration": cfg["duration"],
        "text": cfg["custom_text"],
        "text_position": cfg["text_position"],
        "speed": cfg["speed"],
        "roast_mode": cfg["roast_mode"],
        "image_paths": [],
    }

    await update.message.reply_text(
        "GIF-Session gestartet.\n"
        "Sende jetzt mehrere Bilder (oder ein einzelnes).\n"
        "Dann: /gifdone\n"
        "Abbrechen: /gifcancel"
    )


async def collect_gif_for_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = str(update.effective_chat.id)
    session = _PENDING_GIF_SESSIONS.get(chat_id)
    if not session:
        return

    image_obj = _pick_image_obj(update.message)
    if not image_obj:
        return

    try:
        current_count = len(session["image_paths"])
        if current_count >= MAX_GIF_IMAGES:
            await update.message.reply_text(f"Maximal {MAX_GIF_IMAGES} Bilder erreicht. Nutze /gifdone.")
            raise ApplicationHandlerStop

        bot_file = await context.bot.get_file(image_obj.file_id)
        path = _temp_image_path(chat_id, current_count)
        await bot_file.download_to_drive(path)
        session["image_paths"].append(path)

        await update.message.reply_text(
            f"Bild gespeichert ({len(session['image_paths'])}/{MAX_GIF_IMAGES}). Nutze /gifdone wenn fertig."
        )
        raise ApplicationHandlerStop
    except ApplicationHandlerStop:
        raise
    except Exception as exc:
        logger.warning("GIF session image save failed: %s", exc)
        await update.message.reply_text("Bild konnte nicht gespeichert werden. Bitte erneut senden.")
        raise ApplicationHandlerStop


async def finish_gif_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = str(update.effective_chat.id)
    session = _PENDING_GIF_SESSIONS.get(chat_id)
    if not session:
        await update.message.reply_text("Keine aktive GIF-Session. Starte mit /gif.")
        return

    image_paths = list(session.get("image_paths", []))
    if not image_paths:
        await update.message.reply_text("Noch keine Bilder gespeichert. Sende Bilder oder nutze /gifcancel.")
        return

    loading = await update.message.reply_text(
        f"Erstelle GIF aus {len(image_paths)} Bild(ern) ({session['effect']}, {session['speed']})..."
    )

    try:
        await _render_and_send_gif(
            chat_id=chat_id,
            context=context,
            image_paths=image_paths,
            effect=session["effect"],
            duration=session["duration"],
            text=session["text"],
            text_position=session["text_position"],
            speed=session["speed"],
            roast_mode=session["roast_mode"],
            loading_message_id=loading.message_id,
        )
    finally:
        _reset_session(chat_id)


async def cancel_gif_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = str(update.effective_chat.id)
    if chat_id not in _PENDING_GIF_SESSIONS:
        await update.message.reply_text("Keine aktive GIF-Session gefunden.")
        return

    _reset_session(chat_id)
    await update.message.reply_text("GIF-Session abgebrochen und Dateien geloescht.")


async def _render_and_send_gif(
    chat_id: str,
    context: ContextTypes.DEFAULT_TYPE,
    image_paths: List[str],
    effect: str,
    duration: float,
    text: Optional[str],
    text_position: str,
    speed: str,
    roast_mode: bool,
    loading_message_id: int,
):
    render_text = text
    if roast_mode and not render_text:
        try:
            render_text = await asyncio.to_thread(_generate_roast_text, image_paths[0])
        except Exception as exc:
            logger.warning("Roast text generation failed: %s", exc)

    gif_bytes = await _create_moviepy_gif(
        image_paths=image_paths,
        effect=effect,
        duration=duration,
        text=render_text,
        text_position=text_position,
        speed=speed,
    )

    if not gif_bytes:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_message_id,
            text="Konnte GIF nicht erstellen.",
        )
        return

    await context.bot.send_document(
        chat_id=chat_id,
        document=gif_bytes,
        filename=f"{effect}_{speed}_bot.gif",
        caption=(
            f"GIF fertig: {effect} ({speed})\n"
            f"Bilder: {len(image_paths)}\n"
            f"Text: {render_text or '-'}"
        ),
    )
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=loading_message_id,
        text="GIF erfolgreich erstellt.",
    )


def _apply_effect(clip, effect: str, multiplier: float):
    if effect == "bounce":
        return clip.resize(lambda t: 1 + 0.08 * abs((t * 2 * multiplier) % 2 - 1))
    if effect == "zoom":
        return clip.resize(lambda t: 1 + 0.25 * t * multiplier)
    if effect == "pulse":
        return clip.resize(lambda t: 1 + 0.18 * abs((t * 3 * multiplier) % 2 - 1))
    if effect == "spin":
        return clip.rotate(lambda t: t * 90 * multiplier)
    if effect == "wave":
        return clip.rotate(lambda t: 4 * (1 if int(t * 3) % 2 == 0 else -1))
    if effect == "glitch":
        return clip.resize(lambda t: 1 + 0.12 * abs((t * 10 * multiplier) % 2 - 1))
    if effect == "fireworks":
        return clip.resize(lambda t: 1 + 1.2 * (1 - t) ** 1.6 if t < 0.7 else 1.0)
    if effect == "blackhole":
        clip = clip.resize(lambda t: max(0.15, 2.0 - t * 3.0))
        return clip.rotate(lambda t: t * 120 * multiplier)
    if effect == "mirror":
        return clip.resize(lambda t: 1 + 0.4 * abs((t * 6 * multiplier) % 2 - 1))
    if effect == "pixelate":
        def pixel(_gf, t):
            factor = int(6 + 26 * (1 - t))
            return clip.resize(width=max(16, 512 // factor)).resize(width=512).get_frame(t)

        return clip.fl(pixel)
    if effect == "portal":
        return clip.resize(lambda t: 1.8 - 1.4 * t if t < 0.55 else 0.4 + 1.2 * (t - 0.55))
    if effect == "shockwave":
        return clip.resize(lambda t: 1 + 1.5 * (1 - abs(t - 0.5) * 2))
    if effect == "ghost":
        return clip.set_opacity(lambda t: 0.5 + 0.5 * abs((t * 5 * multiplier) % 2 - 1))
    if effect == "fractal":
        return clip.resize(lambda t: 1 + 2.2 * t if t < 0.5 else 3.2 - 2.2 * (t - 0.5))
    return clip


def _apply_text_overlay(clip, text: str, text_position: str):
    position = text_position if text_position in {"top", "center", "bottom"} else "bottom"

    for font_name in ("Arial-Bold", "Arial", "DejaVu-Sans"):
        try:
            shadow = TextClip(
                text,
                fontsize=52,
                color="black",
                font=font_name,
                stroke_color="black",
                stroke_width=6,
            ).set_position(("center", position)).set_opacity(0.7)

            main_text = TextClip(
                text,
                fontsize=52,
                color="white",
                font=font_name,
                stroke_color="#00ffff",
                stroke_width=3,
            ).set_position(("center", position))

            return CompositeVideoClip([clip, shadow, main_text])
        except Exception:
            continue

    logger.warning("Text overlay skipped: no usable font backend available")
    return clip


def _fit_image_to_square(image_path: str, size: int = 512) -> Image.Image:
    with Image.open(image_path) as src:
        src = ImageOps.exif_transpose(src)
        img = src.convert("RGB")
        img.thumbnail((size, size), RESAMPLE_LANCZOS)

    canvas = Image.new("RGB", (size, size), (8, 8, 8))
    x = (size - img.width) // 2
    y = (size - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def _scale_center(img: Image.Image, scale: float) -> Image.Image:
    w, h = img.size
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))
    resized = img.resize((nw, nh), RESAMPLE_LANCZOS)

    if scale >= 1.0:
        left = max(0, (nw - w) // 2)
        top = max(0, (nh - h) // 2)
        return resized.crop((left, top, left + w, top + h))

    canvas = Image.new("RGB", (w, h), (8, 8, 8))
    x = (w - nw) // 2
    y = (h - nh) // 2
    canvas.paste(resized, (x, y))
    return canvas


def _apply_effect_pil(base: Image.Image, effect: str, phase: float) -> Image.Image:
    pulse = abs((phase * 2) % 2 - 1)

    if effect == "bounce":
        return _scale_center(base, 1.0 + 0.08 * pulse)
    if effect == "zoom":
        return _scale_center(base, 1.0 + 0.22 * phase)
    if effect == "pulse":
        return _scale_center(base, 1.0 + 0.14 * pulse)
    if effect == "spin":
        return base.rotate(phase * 110.0, resample=RESAMPLE_BICUBIC)
    if effect == "wave":
        return base.rotate(5.0 if int(phase * 8) % 2 == 0 else -5.0, resample=RESAMPLE_BICUBIC)
    if effect == "glitch":
        shift = 6 if int(phase * 12) % 2 == 0 else -6
        r, g, b = base.split()
        r = ImageChops.offset(r, shift, 0)
        b = ImageChops.offset(b, -shift, 0)
        return Image.merge("RGB", (r, g, b))
    if effect == "fireworks":
        return _scale_center(base, 1.0 + 0.18 * (1 - phase))
    if effect == "blackhole":
        frame = _scale_center(base, max(0.55, 1.75 - 1.2 * phase))
        return frame.rotate(phase * 180.0, resample=RESAMPLE_BICUBIC)
    if effect == "mirror":
        return ImageOps.mirror(base) if int(phase * 10) % 2 == 0 else base.copy()
    if effect == "pixelate":
        factor = max(2, int(3 + 10 * phase))
        w, h = base.size
        small = base.resize((max(1, w // factor), max(1, h // factor)), RESAMPLE_NEAREST)
        return small.resize((w, h), RESAMPLE_NEAREST)
    if effect == "portal":
        return _scale_center(base, 1.7 - 1.2 * phase if phase < 0.55 else 0.5 + 1.0 * (phase - 0.55))
    if effect == "shockwave":
        return _scale_center(base, 1.0 + 0.55 * (1 - abs(phase - 0.5) * 2))
    if effect == "ghost":
        alpha = int(160 + 70 * pulse)
        fg = base.convert("RGBA")
        fg.putalpha(alpha)
        bg = Image.new("RGBA", base.size, (8, 8, 8, 255))
        bg.alpha_composite(fg)
        return bg.convert("RGB")
    if effect == "fractal":
        return _scale_center(base, 1.0 + 0.65 * (phase if phase < 0.5 else (1 - phase)))
    return base.copy()


def _draw_text_pil(frame: Image.Image, text: str, text_position: str) -> Image.Image:
    if not text:
        return frame

    out = frame.copy()
    draw = ImageDraw.Draw(out)

    font = None
    for font_name in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(font_name, 34)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    wrapped = "\n".join(textwrap.wrap(text[:240], width=28)[:4])
    if not wrapped:
        return out

    try:
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=4)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        lines = wrapped.split("\n")
        line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        tw = max((bbox[2] - bbox[0] for bbox in line_sizes), default=0)
        th = sum((bbox[3] - bbox[1] for bbox in line_sizes), default=0) + max(0, len(lines) - 1) * 4

    w, h = out.size
    x = max(8, (w - tw) // 2)
    if text_position == "top":
        y = 14
    elif text_position == "center":
        y = max(8, (h - th) // 2)
    else:
        y = max(8, h - th - 16)

    for ox, oy in ((-2, -2), (2, -2), (-2, 2), (2, 2)):
        draw.multiline_text((x + ox, y + oy), wrapped, font=font, fill=(0, 0, 0), align="center", spacing=4)
    draw.multiline_text((x, y), wrapped, font=font, fill=(255, 255, 255), align="center", spacing=4)

    return out


def _create_pil_gif_sync(
    image_paths: List[str],
    effect: str,
    duration: float,
    text: Optional[str],
    text_position: str,
    speed: str,
) -> Optional[BytesIO]:
    if not image_paths:
        return None

    try:
        config = SPEED_CONFIG.get(speed, SPEED_CONFIG["normal"])
        multiplier = config["multiplier"]
        effective_duration = _sanitize_duration(duration) / multiplier

        base_frames = [_fit_image_to_square(path, size=512) for path in image_paths]

        if len(base_frames) > 1:
            total_frames = max(len(base_frames) * 4, int(effective_duration * 14))
        else:
            total_frames = max(14, int(effective_duration * 18))
        total_frames = max(8, min(total_frames, 84))

        frame_duration_ms = max(45, int((effective_duration * 1000) / total_frames))

        frames: List[Image.Image] = []
        for i in range(total_frames):
            phase = i / max(1, total_frames - 1)
            src_idx = min(len(base_frames) - 1, int((i / total_frames) * len(base_frames)))
            frame = _apply_effect_pil(base_frames[src_idx], effect, phase)
            if text:
                frame = _draw_text_pil(frame, text, text_position)
            frames.append(frame.convert("P", palette=Image.ADAPTIVE, colors=256))

        if not frames:
            return None

        output = BytesIO()
        try:
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=frame_duration_ms,
                loop=0,
                optimize=False,
                disposal=2,
            )
        except TypeError:
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=frame_duration_ms,
                loop=0,
                optimize=False,
            )

        output.seek(0)
        output.name = f"{effect}_{speed}_bot.gif"
        return output
    except Exception as exc:
        logger.error("Pillow fallback render failed (%s): %s", effect, exc)
        return None


def _create_moviepy_gif_sync(
    image_paths: List[str],
    effect: str,
    duration: float,
    text: Optional[str],
    text_position: str,
    speed: str,
) -> Optional[BytesIO]:
    if not image_paths:
        return None

    if not MOVIEPY_AVAILABLE or not MOVIEPY_RUNTIME_COMPATIBLE:
        logger.info("MoviePy renderer unavailable/incompatible, using Pillow fallback GIF renderer")
        return _create_pil_gif_sync(image_paths, effect, duration, text, text_position, speed)

    config = SPEED_CONFIG.get(speed, SPEED_CONFIG["normal"])
    fps = config["fps"]
    multiplier = config["multiplier"]
    effective_duration = _sanitize_duration(duration) / multiplier
    if len(image_paths) >= 8:
        fps = min(fps, 22)

    clip = None
    subclips = []
    tmp_gif = os.path.join(
        tempfile.gettempdir(),
        f"render_{int(time.time() * 1000)}_{random.randint(1000, 9999)}.gif",
    )

    try:
        if len(image_paths) > 1:
            sub_dur = effective_duration / len(image_paths)
            subclips = [ImageClip(p).set_duration(sub_dur).resize(height=512) for p in image_paths]
            clip = concatenate_videoclips(subclips, method="compose")
        else:
            clip = ImageClip(image_paths[0]).set_duration(effective_duration).resize(height=512)

        clip = _apply_effect(clip, effect, multiplier)

        if text:
            clip = _apply_text_overlay(clip, text, text_position)

        try:
            clip.write_gif(
                tmp_gif,
                fps=fps,
                program="pillow",
                opt="OptimizePlus",
                fuzz=8,
            )
        except TypeError:
            # Some MoviePy versions don't support opt/fuzz on write_gif.
            clip.write_gif(
                tmp_gif,
                fps=fps,
                program="pillow",
            )

        with open(tmp_gif, "rb") as f:
            output = BytesIO(f.read())
        output.seek(0)
        output.name = f"{effect}_{speed}_bot.gif"
        return output

    except Exception as exc:
        logger.warning("MoviePy render failed (%s): %s. Switching to Pillow fallback.", effect, exc)
        return _create_pil_gif_sync(image_paths, effect, duration, text, text_position, speed)
    finally:
        try:
            if clip:
                clip.close()
        except Exception:
            pass

        for c in subclips:
            try:
                c.close()
            except Exception:
                pass

        try:
            if os.path.exists(tmp_gif):
                os.unlink(tmp_gif)
        except Exception:
            pass


async def _create_moviepy_gif(
    image_paths: List[str],
    effect: str,
    duration: float,
    text: Optional[str] = None,
    text_position: str = "bottom",
    speed: str = "normal",
) -> Optional[BytesIO]:
    return await asyncio.to_thread(
        _create_moviepy_gif_sync,
        image_paths,
        effect,
        duration,
        text,
        text_position,
        speed,
    )