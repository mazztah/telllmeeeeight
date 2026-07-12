# plantid_agent.py – Web-Suche + LLM-Agent für Plant-ID Pflegehinweise & Chat
import asyncio
import json
import logging
from typing import Optional

from bot_state import client as groq_client
from search import web_search, format_search_results_for_prompt

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3-70b-8192"
FALLBACK_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


async def fetch_care_tips_from_web(plant_name: str) -> dict:
    """
    Sucht im Web nach Pflegehinweisen für die Pflanze und lässt ein LLM
    die Ergebnisse strukturiert aufbereiten.
    """
    if not plant_name or plant_name == "Unbekannt":
        return {"success": False, "error": "Kein Pflanzenname vorhanden."}

    queries = [
        f"{plant_name} Pflegehinweise Wasser Gießen Temperatur",
        f"{plant_name} Licht Standort Schatten Sonne Pflege",
        f"{plant_name} Geheimtipps Expertenpflege düngen umtopfen",
    ]

    all_search_texts = []
    for q in queries:
        try:
            result = await asyncio.to_thread(web_search, q, 5, "de", "de", None)
            if result.get("success"):
                all_search_texts.append(format_search_results_for_prompt(result))
            else:
                logger.warning("Web-Suche fehlgeschlagen für '%s': %s", q, result.get("error"))
        except Exception as e:
            logger.error("Fehler bei Web-Suche '%s': %s", q, e)

    if not all_search_texts:
        return {"success": False, "error": "Web-Suche lieferte keine Ergebnisse."}

    combined_search = "\n\n---\n\n".join(all_search_texts)

    system_prompt = (
        "Du bist ein Pflanzenpflege-Experte. Extrahiere aus den folgenden "
        "Web-Suchergebnissen präzise, strukturierte Pflegehinweise für die Pflanze. "
        "Antworte AUSSCHLIESSLICH in Markdown mit folgenden Abschnitten:\n\n"
        "## 💧 Wasser & Gießen\n"
        "## 🌡️ Temperatur & Klima\n"
        "## ☀️ Licht & Standort\n"
        "## 🌑 Schatten & Winterquartier\n"
        "## 💡 Geheimtipps & Besonderheiten\n\n"
        "Verwasse keine Informationen. Wenn etwas unbekannt ist, schreibe 'Keine spezifischen Angaben gefunden'. "
        "Antworte auf Deutsch."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Pflanze: {plant_name}\n\n{combined_search}"},
    ]

    try:
        completion = groq_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=1500,
            top_p=0.9,
        )
        markdown = completion.choices[0].message.content.strip()
        return {"success": True, "markdown": markdown, "plant_name": plant_name}
    except Exception as e:
        logger.error("LLM-Pflegehinweis-Fehler: %s", e)
        # Fallback-Modell versuchen
        try:
            completion = groq_client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=0.4,
                max_tokens=1500,
                top_p=0.9,
            )
            markdown = completion.choices[0].message.content.strip()
            return {"success": True, "markdown": markdown, "plant_name": plant_name}
        except Exception as e2:
            logger.error("Fallback-LLM-Fehler: %s", e2)
            return {"success": False, "error": f"KI-Aufbereitung fehlgeschlagen: {e2}"}


async def chat_with_plant_agent(
    question: str,
    plant_context: dict,
    history: Optional[list] = None,
) -> dict:
    """
    Beantwortet eine User-Frage zum Kontext der aktuellen Pflanzenanalyse.
    """
    if not question or not question.strip():
        return {"success": False, "error": "Leere Frage."}

    history = history or []

    # Kontext aufbereiten
    ident = plant_context.get("identification", {})
    best = ident.get("best_match", {})
    details = plant_context.get("details", {})
    wiki = plant_context.get("wikipedia", {})
    diseases = plant_context.get("diseases", [])

    context_lines = [
        f"Erkannte Pflanze: {best.get('scientific_name', 'Unbekannt')}",
        f"Konfidenz: {best.get('confidence', 0)}%",
        f"Familie: {best.get('family', '—')}",
        f"Gattung: {best.get('genus', '—')}",
    ]
    if best.get("common_names"):
        context_lines.append(f"Bekannte Namen: {', '.join(best['common_names'][:3])}")

    if details:
        context_lines.append(f"Gießen: {details.get('watering', '—')}")
        sun = details.get("sunlight", [])
        if sun:
            context_lines.append(f"Licht: {', '.join(sun) if isinstance(sun, list) else sun}")
        context_lines.append(f"Pflege-Schwierigkeit: {details.get('care_level', '—')}")
        context_lines.append(f"Zyklus: {details.get('cycle', '—')}")
        if details.get("poisonous_to_pets"):
            context_lines.append("⚠️ Giftig für Haustiere")
        if details.get("poisonous_to_humans"):
            context_lines.append("⚠️ Giftig für Menschen")

    if wiki and wiki.get("extract"):
        context_lines.append(f"Wikipedia-Info: {wiki['extract'][:300]}…")

    if diseases:
        context_lines.append(f"Bekannte Krankheiten/Schädlinge: {', '.join(d['name'] for d in diseases[:3] if d.get('name'))}")

    system_prompt = (
        "Du bist ein freundlicher Pflanzen-Experten-Assistent. Du beantwortest Fragen "
        "zu einer spezifischen Pflanze basierend auf der aktuellen KI-Analyse. "
        "Antworte präzise, hilfreich und auf Deutsch. Wenn du etwas nicht weißt, sag es ehrlich. "
        "Halte dich an die bereitgestellten Analyse-Daten, ergänze aber gerne allgemeines Pflanzenwissen."
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.append({
        "role": "system",
        "content": "AKTUELLE PFLANZEN-ANALYSE:\n" + "\n".join(context_lines),
    })

    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

    messages.append({"role": "user", "content": question})

    try:
        completion = groq_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1200,
            top_p=0.9,
        )
        reply = completion.choices[0].message.content.strip()
        return {"success": True, "reply": reply}
    except Exception as e:
        logger.error("Plant-Agent Chat-Fehler: %s", e)
        try:
            completion = groq_client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1200,
                top_p=0.9,
            )
            reply = completion.choices[0].message.content.strip()
            return {"success": True, "reply": reply}
        except Exception as e2:
            logger.error("Fallback Chat-Fehler: %s", e2)
            return {"success": False, "error": f"Chat-Antwort fehlgeschlagen: {e2}"}

