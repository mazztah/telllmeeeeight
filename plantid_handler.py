# plantid_handler.py – Telegram Handler für /plantid
import base64
import logging
import os
from io import BytesIO

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from plantid_api import full_plant_analysis

logger = logging.getLogger(__name__)

# ── Session-Tracking für Plant-ID Uploads ─────────────────────────────────────
_plantid_sessions: set = set()


def _get_webapp_url() -> str:
    """Ermittelt die öffentliche URL der Plant-ID Mini-App."""
    return os.getenv("PUBLIC_APP_BASE_URL", "https://telllmeeesevn.onrender.com").rstrip("/") + "/plantid"


def _format_result(data: dict) -> str:
    """Formatiert das Analyse-Ergebnis als Telegram-Text."""
    if not data.get("success"):
        return f"❌ **Fehler:** {data.get('error', 'Unbekannt')}"

    id_data = data.get("identification", {})
    best = id_data.get("best_match", {})
    care = data.get("care", {})
    wiki = data.get("wikipedia", {})

    name = best.get("scientific_name", "Unbekannt")
    common = best.get("common_names", [])
    confidence = best.get("confidence", 0)
    family = best.get("family", "—")
    genus = best.get("genus", "—")

    lines = [
        f"🌿 **Pflanzen-Erkennung**",
        f"",
        f"📛 **Wissenschaftlich:** `{name}`",
    ]
    if common:
        lines.append(f"🏷️ **Bekannt als:** {', '.join(common[:3])}")
    lines.append(f"")
    lines.append(f"🎯 **Konfidenz:** {confidence}%")
    lines.append(f"🔬 **Familie:** {family}")
    lines.append(f"🧬 **Gattung:** {genus}")

    if data.get("demo_mode"):
        lines.append(f"")
        lines.append(f"⚠️ *Demo-Modus – kein API-Key konfiguriert*")

    if care:
        lines.append(f"")
        lines.append(f"💧 **Gießen:** {care.get('watering', '—')}")
        sun = care.get("sunlight", [])
        if sun:
            lines.append(f"☀️ **Licht:** {', '.join(sun) if isinstance(sun, list) else sun}")
        lines.append(f"📊 **Schwierigkeit:** {care.get('care_level', '—')}")
        if care.get("poisonous_to_pets") or care.get("poisonous_to_humans"):
            lines.append(f"☠️ **Giftig:** {'Haustiere' if care.get('poisonous_to_pets') else ''} {'Menschen' if care.get('poisonous_to_humans') else ''}")

    if wiki and wiki.get("extract"):
        lines.append(f"")
        lines.append(f"📖 **Wikipedia:**")
        lines.append(f"{wiki['extract'][:400]}…")
        if wiki.get("wiki_url"):
            lines.append(f"[Mehr lesen]({wiki['wiki_url']})")

    return "\n".join(lines)


async def cmd_plantid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /plantid – Öffnet die Plant-ID Mini-App oder analysiert ein direkt mitgesendetes Foto.
    """
    chat_id = str(update.effective_chat.id)

    # Wenn ein Foto direkt mit /plantid mitgeschickt wurde
    if update.message and update.message.photo:
        await _analyze_photo_message(update, context)
        return

    # Mini-App Button mit direkter Render-URL
    webapp_url = _get_webapp_url()
    keyboard = [
        [InlineKeyboardButton("🌿 Plant-ID Scanner öffnen", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("📸 Foto direkt senden", callback_data="plantid:upload")],
    ]

    await update.message.reply_text(
        text=(
            "🌿 **Plant-ID Erkennung**\n\n"
            "Identifiziere jede Pflanze per Kamera oder Foto-Upload!\n\n"
            "✅ **Wie es funktioniert:**\n"
            "• 📸 Foto einer Pflanze senden\n"
            "• 🤖 KI analysiert Art, Familie & Gattung\n"
            "• 💧 Pflege-Tipps (Gießen, Licht, Giftigkeit)\n"
            "• 📖 Wikipedia-Infos direkt im Chat\n\n"
            "*Unterstützt von PlantNet + Perenual + Wikipedia*"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def plantid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Behandelt Callback-Queries für Plant-ID."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "plantid:upload":
        chat_id = str(update.effective_chat.id)
        _plantid_sessions.add(chat_id)
        await query.edit_message_text(
            text=(
                "📸 **Sende jetzt ein Foto!**\n\n"
                "Tipps für beste Ergebnisse:\n"
                "• 🌞 Gutes Tageslicht\n"
                "• 🍃 Blätter & Blüten sichtbar\n"
                "• 📏 Nahaufnahme (20-50cm)\n"
                "• 🚫 Kein Blitz\n\n"
                "Sende das Foto einfach in den Chat!"
            ),
            parse_mode="Markdown",
        )


async def _analyze_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analysiert ein Foto, das direkt im Chat gesendet wurde."""
    message = update.message
    photo = message.photo[-1]  # Höchste Auflösung
    chat_id = str(update.effective_chat.id)

    status_msg = await message.reply_text("🌿 Analysiere Pflanze… Bitte warten.")

    try:
        # Foto herunterladen
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_bytes = bytes(image_bytes)

        # Analyse
        result = await full_plant_analysis(image_bytes, filename="plant.jpg")

        # Ergebnis senden
        text = _format_result(result)
        await status_msg.edit_text(text=text, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        logger.exception("Plant-ID Analyse-Fehler")
        await status_msg.edit_text(
            text=f"❌ **Analyse-Fehler:**\n`{str(e)[:300]}`\n\nBitte versuche es mit einem anderen Foto.",
            parse_mode="Markdown",
        )
    finally:
        # Session aufräumen
        _plantid_sessions.discard(chat_id)


async def handle_plantid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Standalone Handler für Fotos im Plant-ID Kontext.
    """
    await _analyze_photo_message(update, context)


def has_active_plantid_session(chat_id: str) -> bool:
    """Prüft ob eine Plant-ID Upload-Session aktiv ist."""
    return chat_id in _plantid_sessions

