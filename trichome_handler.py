# trichome_handler.py – Trichom-Scanner Telegram Handler
from telegram import Update
from telegram.ext import ContextTypes
from trichome_analyzer import handle_trichome_analysis
import base64
import logging

logger = logging.getLogger(__name__)

# Trichome session state
_trichome_sessions: dict = {}


async def cmd_trichome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ /trichome – Cannabis Trichom-Scanner öffnen """
    chat_id = str(update.effective_chat.id)

    # Extrahiere Pflanzenalter wenn angegeben
    plant_age = None
    if context.args and context.args[0].isdigit():
        plant_age = int(context.args[0])

    from trichome_analyzer import cmd_trichome_handler
    await cmd_trichome_handler(update, context)


async def handle_trichome_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Behandelt eingehende Fotos für Trichom-Analyse."""
    from trichome_analyzer import handle_trichome_photo as analyze_photo

    chat_id = str(update.effective_chat.id)

    # Prüfe ob Trichom-Session aktiv ist
    session = _trichome_sessions.get(chat_id, {})
    plant_age = session.get("plant_age")

    try:
        # Hole Lightmeter-Daten aus der letzten Messung (falls vorhanden)
        light_data = None
        try:
            from brain import load_all_entries
            entries = await load_all_entries(chat_id)
            # Suche letzte Lightmeter-Messung
            for entry in entries[:5]:
                if "lux" in str(entry.get("metadata", "")):
                    try:
                        import json
                        meta = json.loads(entry.get("metadata", "{}"))
                        if "ppfd" in str(meta):
                            light_data = meta
                            break
                    except Exception:
                        pass
        except Exception:
            pass

        await analyze_photo(
            update=update,
            context=context,
            plant_age_days=plant_age,
            light_data=light_data
        )
    except Exception as e:
        logger.exception("Trichome photo handling error")
        await update.message.reply_text(
            f"❌ Analyse-Fehler: {str(e)[:200]}\n\n"
            "Bitte ein schärferes Foto senden."
        )
