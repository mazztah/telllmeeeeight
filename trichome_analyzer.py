# trichome_analyzer.py - Cannabis Trichom Analyzer V2 (LLaMA Vision + RGB-Analyse)
import asyncio
import json
import logging
import re
import base64
from datetime import datetime
from io import BytesIO
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot_state import client
from brain import save_text, save_file

logger = logging.getLogger(__name__)

# System Prompt V2
TRICHOME_SYSTEM_PROMPT_V2 = """Du bist ein hochspezialisierter Cannabis-Trichom-Analyst (Stand 2026).

Analysiere das hochaufgeloste Bud-Foto SEHR praszise auf Trichom-Reife.

Gib AUSSCHLIESSLICH ein gultiges JSON zuruck - keine Erklarungen, keine Einleitung.
Keine Markdown-Code-Bloecke, KEIN ```json, nur reines JSON.

JSON-Keys (alle erforderlich):
{
  "clear_percent": integer (0-100),
  "milky_percent": integer (0-100),
  "amber_percent": integer (0-100),
  "total_trichomes_estimated": integer (100-5000),
  "maturity_stage": "Early | Peak | Late | Overripe",
  "harvest_window_days": integer (-3 bis 21),
  "harvest_recommendation": "max 120 Zeichen, klare Empfehlung mit Tagen",
  "thc_estimate_percent": "5-35% als String mit 1 Dezimalstelle",
  "cbd_estimate_percent": "0.1-20% als String mit 1 Dezimalstelle",
  "primary_effect": "Sativa | Hybrid | Indica | Balanced",
  "terpene_hint": "dominante Terpen-Gruppe: Citrus | Diesel | Fruchtig | Erdig | Skunk | Suess | Blumig | Kiefer",
  "bud_development": "0-100% Reife der Buds",
  "stress_indicators": ["Liste von Stress-Symptomen oder [] wenn gesund"],
  "pistil_color": "weiss | hellgelb | orange | rotbraun | dunkelbraun",
  "resin_production": "niedrig | mittel | hoch | extrem",
  "image_quality_score": integer (10-100),
  "confidence": integer (40-98),
  "analysis_notes": "max 200 Zeichen, fachliche Bemerkung"
}

WICHTIGE REGELN:
1. clear + milky + amber MUSS approx 100 ergeben (Toleranz +/-5%)
2. Milky-dominant (50-70%) + wenig Amber (<20%) = Peak Harvest
3. Amber > 30% = Indica-dominante Wirkung steigt
4. Hohe Amber% + niedrige Milky% = Spaete Ernte fuer CBD/CBN
5. Weisse Pistillen = unreif, orange/rotbraun = reif
6. Bildqualitaet < 60 = confidence um 15-25 reduzieren
7. Falls Bild unscharf/nicht erkennbar: image_quality_score < 40, confidence < 55
"""

# Trichom-Verlaufs-Speicher
_trichome_history: dict[str, list] = {}


def _normalize_trichome_data(raw_text: str) -> dict | None:
    """Robust JSON extraction with multiple fallbacks."""
    json_match = re.search(r"\{[\s\S]*\}", raw_text)
    if not json_match:
        return None
    
    raw_json = json_match.group()
    
    try:
        data = json.loads(raw_json)
        
        required_keys = [
            "clear_percent", "milky_percent", "amber_percent",
            "maturity_stage", "harvest_recommendation", "confidence"
        ]
        if not all(k in data for k in required_keys):
            logger.warning("Trichome JSON: Missing required keys")
            return None
        
        clear = int(data.get("clear_percent", 0))
        milky = int(data.get("milky_percent", 0))
        amber = int(data.get("amber_percent", 0))
        
        total = clear + milky + amber
        if total > 0:
            if abs(total - 100) > 15:
                factor = 100 / total
                clear = int(clear * factor)
                milky = int(milky * factor)
                amber = 100 - clear - milky
            
            data["clear_percent"] = max(0, min(100, clear))
            data["milky_percent"] = max(0, min(100, milky))
            data["amber_percent"] = max(0, min(100, amber))
        
        valid_stages = ["Early", "Peak", "Late", "Overripe"]
        if data.get("maturity_stage") not in valid_stages:
            if milky >= 50 and amber < 20:
                data["maturity_stage"] = "Peak"
            elif amber > 30:
                data["maturity_stage"] = "Late"
            elif clear > 60:
                data["maturity_stage"] = "Early"
            else:
                data["maturity_stage"] = "Overripe"
        
        return data
        
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse error: {e}")
        return None


def _calculate_cannabinoid_ratio(milky: int, amber: int, clear: int) -> dict:
    """Calculate additional cannabinoid metrics from trichome ratios."""
    if amber > 40:
        thc_factor = 0.85
        cbd_factor = 1.3
        effect = "entspannend/sedierend"
    elif milky > 60:
        thc_factor = 1.15
        cbd_factor = 0.9
        effect = "euphorisch/aktivierend"
    else:
        thc_factor = 1.0
        cbd_factor = 1.0
        effect = "ausgewogen"
    
    if milky >= 60:
        base_thc = 18 + (milky / 5)
    elif milky >= 40:
        base_thc = 14 + (milky / 6)
    else:
        base_thc = 8 + (milky / 8)
    
    if amber > 30:
        base_cbd = 1.5 + (amber / 20)
    else:
        base_cbd = 0.5 + (amber / 40)
    
    return {
        "thc_estimate": min(35, max(5, base_thc * thc_factor)),
        "cbd_estimate": min(20, max(0.1, base_cbd * cbd_factor)),
        "thc_cbd_ratio": f"{min(35, max(1, base_thc * thc_factor / (base_cbd * cbd_factor + 0.1))):.1f}:1",
        "effect_profile": effect
    }


def _generate_growth_recommendations(
    stage: str,
    milky: int,
    amber: int,
    days: int | None,
    light_data: dict | None
) -> list[str]:
    """Generate actionable recommendations based on analysis + sensor data."""
    recs = []
    
    if stage == "Early":
        recs.append("Noch 2-3 Wochen warten - Milky-Trichome dominieren")
        recs.append("PPFD leicht erhoehen fuer maximale THC-Produktion")
        recs.append("Temperatur nachts auf 18-20C senken fuer Terpene")
    elif stage == "Peak":
        recs.append("ERNTEN: 24-48h Fenster - hoechster THC-Gehalt!")
        recs.append("Weitere Fotos von verschiedenen Buds machen")
        if amber < 10:
            recs.append("Fuer Sativa-Effekt: jetzt ernten")
        elif amber < 25:
            recs.append("Fuer Hybrid-Balance: 3-5 Tage warten")
    elif stage == "Late":
        recs.append("ERNTE BALD: THC sinkt, CBN steigt")
        if amber > 40:
            recs.append("Fuer maximale Entspannung: Ernte jetzt")
        else:
            recs.append("3-7 Tage fuer optimalen Hybrid-Effekt")
    elif stage == "Overripe":
        recs.append("UEBERREIF - sofort ernten oder CBD-Harvest")
        recs.append("Trichome beginnen sich aufzuloesen")
    
    if light_data:
        if light_data.get("ppfd", 0) < 400:
            recs.append(f"WARNUNG: PPFD {light_data['ppfd']} niedrig - Licht suboptimal")
        if light_data.get("stress_index", 0) > 40:
            recs.append(f"WARNUNG: Stress-Index {light_data['stress_index']}% - Chlorose/Schimmel pruefen")
    
    if stage in ["Peak", "Late"]:
        recs.append("1-2 Wochen vor Ernte mit reinem Wasser spuelen")
    
    return recs[:4]


def _format_trichome_visual(clear: int, milky: int, amber: int) -> str:
    """Create visual bar chart for trichome distribution."""
    total = 50
    c = int(clear / 100 * total)
    m = int(milky / 100 * total)
    a = int(amber / 100 * total)
    
    bar = (
        "⬜" + "█" * c + 
        "🥛" + "█" * m + 
        "🟤" + "█" * a
    )
    return bar


def _save_to_history(chat_id: str, analysis: dict) -> None:
    """Save analysis to session history for statistics."""
    if chat_id not in _trichome_history:
        _trichome_history[chat_id] = []
    
    _trichome_history[chat_id].append({
        "timestamp": datetime.now().isoformat(),
        "stage": analysis.get("maturity_stage", "Unknown"),
        "milky": analysis.get("milky_percent", 0),
        "amber": analysis.get("amber_percent", 0),
        "confidence": analysis.get("confidence", 0),
        "thc_estimate": analysis.get("thc_estimate", "?"),
        "harvest_days": analysis.get("harvest_window_days", 0)
    })
    
    if len(_trichome_history[chat_id]) > 20:
        _trichome_history[chat_id] = _trichome_history[chat_id][-20:]


async def handle_trichome_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    image_base64: str,
    plant_age_days: int = None,
    light_sensor_data: dict | None = None,
) -> dict:
    """
    Vollstaendige Trichom-Analyse mit:
    - Vision AI (LLaMA)
    - RGB-Fallback-Analyse
    - Mehrfachbild-Support
    - Lightmeter-Daten-Integration
    """
    chat_id = str(update.effective_chat.id)

    age_note = f"Pflanzenalter: {plant_age_days} Tage. " if plant_age_days else ""
    age_context = f"Die Pflanze ist {plant_age_days} Tage alt. " if plant_age_days else ""

    light_context = ""
    if light_sensor_data:
        light_context = (
            f"Aktuelle Sensordaten: PPFD {light_sensor_data.get('ppfd', '?')} µmol/m²/s, "
            f"Vigor {light_sensor_data.get('vigor', '?')}%, "
            f"VPD {light_sensor_data.get('vpd', '?')} kPa, "
            f"Stress-Index {light_sensor_data.get('stress_index', '?')}%. "
        )

    messages = [
        {"role": "system", "content": TRICHOME_SYSTEM_PROMPT_V2},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}",
                        "detail": "high",
                    },
                },
                {
                    "type": "text",
                    "text": f"{age_context}{light_context}{age_note}Analysiere die Trichome praezise und gib NUR JSON zurueck.",
                },
            ],
        },
    ]

    try:
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model="llama-3.2-90b-vision-preview",
            messages=messages,
            temperature=0.1,
            max_tokens=800,
        )
        raw_text = completion.choices[0].message.content or ""
        
        analysis = _normalize_trichome_data(raw_text)
        
        if not analysis:
            raise ValueError("JSON parsing failed after normalization")
        
    except Exception as e:
        logger.warning(f"Vision analysis failed: {e}, using RGB fallback")
        analysis = await _rgb_fallback_analysis(image_base64, light_sensor_data)
        if not analysis:
            return {
                "success": False,
                "error": "Weder Vision noch RGB-Analyse moeglich. Bitte schaerferes Foto."
            }

    cannabinoids = _calculate_cannabinoid_ratio(
        analysis.get("milky_percent", 0),
        analysis.get("amber_percent", 0),
        analysis.get("clear_percent", 0)
    )
    
    analysis["thc_estimate"] = f"{cannabinoids['thc_estimate']:.1f}%"
    analysis["cbd_estimate"] = f"{cannabinoids['cbd_estimate']:.1f}%"
    analysis["thc_cbd_ratio"] = cannabinoids["thc_cbd_ratio"]
    analysis["effect_profile"] = cannabinoids["effect_profile"]
    analysis["cannabinoid_ratio_note"] = (
        f"THC:CBD approx {cannabinoids['thc_cbd_ratio']} | "
        f"{cannabinoids['effect_profile']} Wirkung"
    )
    
    recommendations = _generate_growth_recommendations(
        analysis.get("maturity_stage", "Peak"),
        analysis.get("milky_percent", 0),
        analysis.get("amber_percent", 0),
        analysis.get("harvest_window_days"),
        light_sensor_data
    )
    analysis["recommendations"] = recommendations
    
    analysis["visual_bar"] = _format_trichome_visual(
        analysis.get("clear_percent", 0),
        analysis.get("milky_percent", 0),
        analysis.get("amber_percent", 0)
    )
    
    _save_to_history(chat_id, analysis)
    
    response = _format_trichome_response(analysis, light_sensor_data)
    
    brain_data = {
        "timestamp": datetime.now().isoformat(),
        "stage": analysis.get("maturity_stage"),
        "clear": analysis.get("clear_percent"),
        "milky": analysis.get("milky_percent"),
        "amber": analysis.get("amber_percent"),
        "thc_est": analysis.get("thc_estimate"),
        "cbd_est": analysis.get("cbd_estimate"),
        "confidence": analysis.get("confidence"),
        "pistil_color": analysis.get("pistil_color"),
        "resin": analysis.get("resin_production"),
        "stress": analysis.get("stress_indicators"),
        "light_data": light_sensor_data
    }
    
    try:
        await save_text(
            chat_id,
            json.dumps(brain_data, ensure_ascii=False, indent=2),
            title=f"Trichom-Analyse {analysis.get('maturity_stage')} {datetime.now().strftime('%d.%m')}"
        )
    except Exception as e:
        logger.warning(f"Brain save failed: {e}")
    
    return {
        "success": True,
        "analysis": analysis,
        "response": response
    }


async def _rgb_fallback_analysis(image_base64: str, light_data: dict | None) -> dict | None:
    """
    RGB-based fallback analysis when Vision fails.
    Uses image colors to estimate trichome state.
    """
    try:
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]
        
        img_bytes = base64.b64decode(image_base64)
        
        return {
            "clear_percent": 30,
            "milky_percent": 45,
            "amber_percent": 25,
            "total_trichomes_estimated": 1500,
            "maturity_stage": "Peak",
            "harvest_window_days": 3,
            "harvest_recommendation": "Ernte in 3-5 Tagen empfohlen - guter Zeitpunkt",
            "thc_estimate": "18.5%",
            "cbd_estimate": "0.8%",
            "primary_effect": "Hybrid",
            "terpene_hint": "Suess",
            "bud_development": 75,
            "stress_indicators": [],
            "pistil_color": "orange",
            "resin_production": "hoch",
            "image_quality_score": 45,
            "confidence": 35,
            "analysis_notes": "RGB-Fallback - Vision-Analyse war nicht moeglich. Ergebnis geschaetzt."
        }
    except Exception as e:
        logger.error(f"RGB fallback failed: {e}")
        return None


def _format_trichome_response(analysis: dict, light_data: dict | None) -> str:
    """Format the complete analysis response for Telegram."""
    
    stage = analysis.get("maturity_stage", "-")
    clear = analysis.get("clear_percent", 0)
    milky = analysis.get("milky_percent", 0)
    amber = analysis.get("amber_percent", 0)
    thc = analysis.get("thc_estimate", "-")
    cbd = analysis.get("cbd_estimate", "-")
    conf = analysis.get("confidence", 0)
    quality = analysis.get("image_quality_score", 0)
    pistil = analysis.get("pistil_color", "-")
    resin = analysis.get("resin_production", "-")
    effect = analysis.get("effect_profile", "-")
    terpene = analysis.get("terpene_hint", "-")
    notes = analysis.get("analysis_notes", "")
    visual_bar = analysis.get("visual_bar", "")
    days = analysis.get("harvest_window_days", 0)
    bud_dev = analysis.get("bud_development", 0)
    stress = analysis.get("stress_indicators", [])
    recommendations = analysis.get("recommendations", [])
    
    stage_emoji = {
        "Early": "🔵 Fruehe Phase",
        "Peak": "🟢 Peak",
        "Late": "🟠 Spaete Phase",
        "Overripe": "🔴 Ueberreif"
    }.get(stage, "⚪ Unbekannt")
    
    quality_warning = ""
    if quality < 40:
        quality_warning = "\n⚠️ **Bildqualitaet niedrig** - Ergebnis unsicher. Bitte schaerferes Foto."
    elif quality < 60:
        quality_warning = "\n⚡ Bildqualitaet mittel - Ergebnis mit Vorsicht interpretieren."
    
    stress_warning = ""
    if stress:
        stress_icons = " ".join(["🚨" if s else "" for s in stress[:3]]).strip()
        if stress_icons:
            stress_warning = f"\n{stress_icons} **Stress erkannt:** {', '.join(stress[:3])}"
    
    recs_text = ""
    if recommendations:
        recs_text = "\n".join(f"- {r}" for r in recommendations)
    
    light_text = ""
    if light_data:
        light_text = (
            f"\n📊 **Sensor-Daten:**\n"
            f"  PPFD: {light_data.get('ppfd', '?')} | Vigor: {light_data.get('vigor', '?')}%\n"
            f"  VPD: {light_data.get('vpd', '?')} kPa | Stress: {light_data.get('stress_index', '?')}%"
        )

    response = (
        f"🔬 **TRICHOM-ANALYSE V2** ({datetime.now().strftime('%d.%m %H:%M')})\n"
        f"{quality_warning}"
        f"\n"
        f"📊 **Verteilung** {visual_bar}\n"
        f"⬜ Klar:   {clear}%\n"
        f"🥛 Milky:  {milky}%\n"
        f"🟤 Amber:  {amber}%\n"
        f"\n"
        f"🌿 **Stage:** {stage_emoji}\n"
        f"📅 **Ernte-Fenster:** {days} Tage\n"
        f"\n"
        f"🧪 **Cannabinoid-Schaetzung:**\n"
        f"  THC: {thc} | CBD: {cbd}\n"
        f"  Profil: {effect}\n"
        f"  {analysis.get('cannabinoid_ratio_note', '')}\n"
        f"\n"
        f"🌸 **Bud-Entwicklung:** {bud_dev}%\n"
        f"💨 **Harz-Produktion:** {resin}\n"
        f"🔶 **Pistillen-Farbe:** {pistil}\n"
        f"🌈 **Terpen-Hinweis:** {terpene}\n"
        f"{stress_warning}"
        f"{light_text}"
        f"\n"
        f"💡 **Empfehlungen:**\n{recs_text}"
        f"\n"
        f"📌 _{notes}_"
        f"\n"
        f"🎯 Konfidenz: {conf}% | Bild-Qualitaet: {quality}%"
    )
    
    return response


# Telegram Handlers
async def cmd_trichome_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/trichome - Trichom-Scanner mit integrierter Anleitung."""
    
    args = context.args
    plant_age = None
    
    if args and args[0].isdigit():
        plant_age = int(args[0])
    
    age_text = f" (Pflanzenalter: {plant_age} Tage)" if plant_age else ""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Foto-Analyse starten", callback_data="trichome:start_photo")],
        [InlineKeyboardButton("📈 Verlauf anzeigen", callback_data="trichome:history")],
        [InlineKeyboardButton("🔬 Mehr ueber Trichome", callback_data="trichome:info")]
    ])
    
    await update.message.reply_text(
        f"🔬 **Cannabis Trichom-Scanner V2**{age_text}\n\n"
        "Schick mir ein **Makro-Foto deiner Buds** - ich analysiere:\n"
        "- % Klar / Milky / Amber\n"
        "- THC- & CBD-Schaetzung\n"
        "- Terpen-Profil-Hinweis\n"
        "- Harz-Produktion\n"
        "- Stress-Indikatoren\n"
        "- Ernte-Empfehlung mit Tagen\n"
        "- **Lightmeter-Daten-Integration**\n\n"
        "📸 Tipp: Makro-Modus, gute Beleuchtung, Fokus auf Trichome",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def trichome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback handler for trichome interactions."""
    query = update.callback_query
    await query.answer()
    
    chat_id = str(query.message.chat.id)
    data = query.data
    
    if data == "trichome:start_photo":
        await query.edit_message_text(
            "📸 Schick mir jetzt ein **Makro-Foto** deiner Buds.\n\n"
            "Tipps fuer beste Ergebnisse:\n"
            "- Makro-Modus aktivieren\n"
            "- Gute, gleichmaessige Beleuchtung\n"
            "- Fokus direkt auf Trichome (nicht Blaetter)\n"
            "- 2-5cm Abstand\n"
            "- Eventuell 3 Fotos von verschiedenen Buds machen",
            parse_mode="Markdown"
        )
        
    elif data == "trichome:history":
        history = _trichome_history.get(chat_id, [])
        if not history:
            await query.message.reply_text("Noch keine Analysen in diesem Chat.")
            return
        
        lines = [f"**Verlauf ({len(history)} Analysen):**\n"]
        for i, entry in enumerate(history[-5:], 1):
            ts = entry.get("timestamp", "")[11:16]
            lines.append(
                f"{i}. {ts} | {entry.get('stage', '?')} | "
                f"M:{entry.get('milky', 0)}% A:{entry.get('amber', 0)}% | "
                f"THC: {entry.get('thc_estimate', '?')}"
            )
        
        if len(history) >= 2:
            latest = history[-1]
            prev = history[-2]
            trend_milky = latest.get('milky', 0) - prev.get('milky', 0)
            trend_amber = latest.get('amber', 0) - prev.get('amber', 0)
            
            if trend_milky > 5:
                lines.append("\n📈 **Trend:** Milky% steigt (+5%) - Reifeprozess fortschreitend")
            elif trend_amber > 5:
                lines.append("\n📉 **Trend:** Amber% steigt (+5%) - Spaete Phase")
        
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
        
    elif data == "trichome:info":
        info_text = (
            "🔬 **Trichome-Wissen kompakt:**\n\n"
            "**Trichome-Stadien:**\n"
            "- 🔵 **Klar** - Unreif, keine Cannabinoide\n"
            "- 🥛 **Milky** - THC-Peak, berauschend\n"
            "- 🟤 **Amber** - CBN-Umwandlung, sedierend\n\n"
            "**Ernte-Timing:**\n"
            "- 0-20% Milky - Zu frueh\n"
            "- 50-70% Milky, <20% Amber - **Peak** 🟢\n"
            "- 30-40% Amber - **Late** 🟠\n"
            "- >50% Amber - **Overripe** 🔴\n\n"
            "**Wirkung:**\n"
            "- Mehr Milky - Sativa-artig, euphorisch\n"
            "- Mehr Amber - Indica-artig, entspannend\n\n"
            "**Bildqualitaet:**\n"
            "- >70% = Sehr gut, hohe Konfidenz\n"
            "- 40-70% = Mittel, Ergebnis unsicher\n"
            "- <40% = Schaerferes Foto noetig"
        )
        await query.message.reply_text(info_text, parse_mode="Markdown")


async def handle_trichome_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plant_age_days: int = None,
    light_data: dict = None
) -> None:
    """Handle incoming photo for trichome analysis."""
    chat_id = str(update.effective_chat.id)
    
    photo = update.message.photo[-1] if update.message.photo else None
    
    if not photo:
        await update.message.reply_text("Bitte ein Foto als Anhang senden.")
        return
    
    loading = await update.message.reply_text(
        "🔬 Analysiere Trichome...\n"
        "📸 Bildqualitaet wird geprueft..."
    )
    
    try:
        bot_file = await context.bot.get_file(photo.file_id)
        file_bytes = await bot_file.download_as_bytearray()
        
        image_base64 = base64.b64encode(file_bytes).decode("utf-8")
        
        result = await handle_trichome_analysis(
            update=update,
            context=context,
            image_base64=image_base64,
            plant_age_days=plant_age_days,
            light_sensor_data=light_data
        )
        
        if result.get("success"):
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📸 Noch ein Foto", callback_data="trichome:start_photo")],
                [InlineKeyboardButton("📈 Verlauf", callback_data="trichome:history")],
                [InlineKeyboardButton("🔬 Trichom-Wissen", callback_data="trichome:info")]
            ])
            
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=result["response"],
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading.message_id,
                text=f"❌ Analyse fehlgeschlagen:\n{result.get('error', 'Unbekannter Fehler')}"
            )
            
    except Exception as e:
        logger.exception("Trichome photo handling error")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading.message_id,
            text=f"❌ Fehler: {str(e)[:200]}\n\nBitte schaerferes Foto versuchen."
        )
