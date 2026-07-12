# plantid_api.py – Plant Recognition API Clients
# PlantNet (free tier: 50 req/day) + Perenual (free tier: 100 req/day) + Wikipedia
import asyncio
import base64
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── API Keys ──────────────────────────────────────────────────────────────────
PLANTNET_API_KEY = os.getenv("PLANTNET_API_KEY", "")
PERENUAL_API_KEY = os.getenv("PERENUAL_API_KEY", "")

# ── Retry helper for Perenual ─────────────────────────────────────────────────
async def _perenual_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    params: dict = None,
    max_retries: int = 2,
    base_delay: float = 1.0,
) -> httpx.Response:
    """
    Führt einen Perenual-Request mit Retry bei 429 (Too Many Requests) aus.
    Exponentieller Backoff: 1s, 2s, ...
    """
    for attempt in range(max_retries + 1):
        try:
            if method.upper() == "GET":
                resp = await client.get(url, params=params)
            else:
                resp = await client.post(url, params=params)

            if resp.status_code == 429 and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning("Perenual 429 – Retry %d/%d nach %.1fs", attempt + 1, max_retries, delay)
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise
        except Exception:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            raise
    return resp  # letzter Versuch

# ── PlantNet ──────────────────────────────────────────────────────────────────
PLANTNET_BASE = "https://my-api.plantnet.org/v2/identify/all"


async def identify_plant(image_bytes: bytes, filename: str = "plant.jpg") -> dict:
    """
    Sendet ein Bild an PlantNet und gibt die Top-Ergebnissse zurück.
    Falls kein API-Key vorhanden → Demo-Modus mit simulierten Daten.
    """
    if not PLANTNET_API_KEY:
        logger.warning("Kein PLANTNET_API_KEY – Demo-Modus aktiv")
        return _demo_identify()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {"images": (filename, image_bytes, "image/jpeg")}
            params = {"api-key": PLANTNET_API_KEY, "include-related-images": "false"}
            resp = await client.post(PLANTNET_BASE, params=params, files=files)
            resp.raise_for_status()
            data = resp.json()
            return _parse_plantnet(data)
    except Exception as e:
        logger.error("PlantNet Fehler: %s", e)
        return {"success": False, "error": str(e), "results": []}


def _parse_plantnet(data: dict) -> dict:
    """Parst PlantNet JSON in ein einheitliches Format."""
    results = []
    for r in data.get("results", [])[:3]:
        species = r.get("species", {})
        results.append({
            "scientific_name": species.get("scientificNameWithoutAuthor", "Unbekannt"),
            "common_names": species.get("commonNames", []),
            "family": species.get("family", {}).get("scientificName", "—"),
            "genus": species.get("genus", {}).get("scientificName", "—"),
            "confidence": round(r.get("score", 0) * 100, 1),
            "gbif_id": species.get("gbif", {}).get("id"),
        })

    best = results[0] if results else None
    return {
        "success": True,
        "best_match": best,
        "all_results": results,
        "api": "plantnet",
    }


def _demo_identify() -> dict:
    """Demo-Daten wenn kein API-Key vorhanden ist."""
    return {
        "success": True,
        "demo_mode": True,
        "best_match": {
            "scientific_name": "Cannabis sativa L.",
            "common_names": ["Hanf", "Cannabis", "Marijuana"],
            "family": "Cannabaceae",
            "genus": "Cannabis",
            "confidence": 94.7,
        },
        "all_results": [
            {"scientific_name": "Cannabis sativa L.", "common_names": ["Hanf"], "family": "Cannabaceae", "genus": "Cannabis", "confidence": 94.7},
            {"scientific_name": "Humulus lupulus", "common_names": ["Hopfen"], "family": "Cannabaceae", "genus": "Humulus", "confidence": 31.2},
            {"scientific_name": "Celtis occidentalis", "common_names": ["Zürgelbaum"], "family": "Cannabaceae", "genus": "Celtis", "confidence": 12.5},
        ],
        "api": "demo",
    }


# ── Perenual ──────────────────────────────────────────────────────────────────
PERENUAL_BASE = "https://perenual.com/api"


async def get_plant_details(scientific_name: str) -> Optional[dict]:
    """
    Holt umfassende Pflanzen-Details von Perenual anhand des wissenschaftlichen Namens.
    Free tier: 100 requests/day, key required.
    """
    if not PERENUAL_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1. Suche nach Pflanze (mit Retry bei 429)
            search_url = f"{PERENUAL_BASE}/species-list"
            search_params = {"key": PERENUAL_API_KEY, "q": scientific_name}
            resp = await _perenual_request(client, "GET", search_url, search_params)
            search_data = resp.json()

            if not search_data.get("data"):
                return None

            plant_id = search_data["data"][0].get("id")
            if not plant_id:
                return None

            # Kurze Pause zwischen Search + Details um Rate-Limit zu entlasten
            await asyncio.sleep(0.5)

            # 2. Details holen (mit Retry bei 429)
            detail_url = f"{PERENUAL_BASE}/species/details/{plant_id}"
            detail_resp = await _perenual_request(client, "GET", detail_url, {"key": PERENUAL_API_KEY})
            d = detail_resp.json()

            # Helper to safely get list values
            def _list(val):
                if isinstance(val, list):
                    return val
                if val:
                    return [val]
                return []

            return {
                # Basic info
                "common_name": d.get("common_name", "—"),
                "scientific_name": d.get("scientific_name", scientific_name),
                "other_names": _list(d.get("other_name")),
                "family": d.get("family", "—"),
                "description": (d.get("description", "") or "")[:800],
                "image_url": d.get("default_image", {}).get("original_url", ""),

                # Care basics
                "watering": d.get("watering", "—"),
                "sunlight": _list(d.get("sunlight")),
                "care_level": d.get("care_level", "—"),
                "maintenance": d.get("maintenance", "—"),
                "cycle": d.get("cycle", "—"),

                # Extended plant data
                "growth_rate": d.get("growth_rate", "—"),
                "type": d.get("type", "—"),
                "dimension": d.get("dimension", "—"),
                "hardiness": d.get("hardiness", {}),
                "indoor": d.get("indoor", False),
                "attracts": _list(d.get("attracts")),
                "propagation": _list(d.get("propagation")),

                # Leaf & appearance
                "leaf_color": _list(d.get("leaf_color")),
                "flowering_season": d.get("flowering_season", "—"),
                "flowering_color": d.get("flowering_color", "—"),
                "cones": d.get("cones", False),
                "fruits": d.get("fruits", False),

                # Edible / medicinal
                "edible_fruit": d.get("edible_fruit", False),
                "edible_leaf": d.get("edible_leaf", False),
                "medicinal": d.get("medicinal", False),
                "cuisine": d.get("cuisine", False),

                # Tolerance & flags
                "drought_tolerant": d.get("drought_tolerant", False),
                "salt_tolerant": d.get("salt_tolerant", False),
                "thorny": d.get("thorny", False),
                "invasive": d.get("invasive", False),
                "rare": d.get("rare", False),

                # Maintenance details
                "pruning_month": _list(d.get("pruning_month")),
                "pruning_count": d.get("pruning_count", {}),
                "harvest_season": d.get("harvest_season", "—"),
                "harvest_method": d.get("harvest_method", "—"),

                # Poison info
                "poisonous_to_pets": d.get("poisonous_to_pets", False),
                "poisonous_to_humans": d.get("poisonous_to_humans", False),
            }
    except Exception as e:
        logger.error("Perenual Details Fehler: %s", e)
        return None


async def get_plant_diseases(scientific_name: str) -> Optional[list]:
    """
    Holt Krankheiten & Schädlinge von Perenual anhand des wissenschaftlichen Namens.
    Nutzt /pest-disease-list und filtert nach passenden Einträgen.
    """
    if not PERENUAL_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # Suche in der Pest-Disease-Liste (mit Retry bei 429)
            url = f"{PERENUAL_BASE}/pest-disease-list"
            params = {"key": PERENUAL_API_KEY, "q": scientific_name}
            resp = await _perenual_request(client, "GET", url, params)
            data = resp.json()

            if not data.get("data"):
                # Fallback: allgemeine Suche ohne q-Parameter, dann manuell filtern
                await asyncio.sleep(0.5)
                params = {"key": PERENUAL_API_KEY, "page": "1"}
                resp = await _perenual_request(client, "GET", url, params)
                data = resp.json()

            items = data.get("data", [])
            results = []
            for item in items[:5]:  # max 5 Ergebnisse
                results.append({
                    "name": item.get("common_name", "—"),
                    "scientific_name": item.get("scientific_name", "—"),
                    "description": (item.get("description", "") or "")[:400],
                    "solution": (item.get("solution", "") or "")[:400],
                    "host": item.get("host", "—"),
                    "image_url": item.get("default_image", {}).get("original_url", ""),
                })
            return results if results else None
    except Exception as e:
        logger.error("Perenual Disease Fehler: %s", e)
        return None


# ── Wikipedia ─────────────────────────────────────────────────────────────────
WIKI_API = "https://de.wikipedia.org/api/rest_v1/page/summary/"
WIKI_SEARCH = "https://de.wikipedia.org/w/api.php"


async def get_wiki_info(query: str) -> Optional[dict]:
    """Holt Zusammenfassung + Bild von Wikipedia (Deutsch)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Suche nach passendem Artikel
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 1,
                "origin": "*",
            }
            sresp = await client.get(
                WIKI_SEARCH,
                params=search_params,
                headers={"User-Agent": "QueensPlantID-Bot/1.0 (contact@example.com)"},
            )
            sresp.raise_for_status()
            sdata = sresp.json()

            if not sdata.get("query", {}).get("search"):
                return None

            title = sdata["query"]["search"][0]["title"]

            # 2. Summary holen
            resp = await client.get(
                f"{WIKI_API}{title}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "QueensPlantID-Bot/1.0 (contact@example.com)",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "title": data.get("title", title),
                "extract": data.get("extract", "")[:800],
                "image_url": data.get("thumbnail", {}).get("source", ""),
                "wiki_url": data.get("content_urls", {}).get("desktop", {}).get("page", f"https://de.wikipedia.org/wiki/{title}"),
            }
    except Exception as e:
        logger.error("Wikipedia Fehler: %s", e)
        return None


async def get_wiki_care_tips(query: str) -> Optional[dict]:
    """
    Versucht, Pflege-Abschnitte aus dem deutschen Wikipedia-Artikel zu extrahieren.
    Sucht nach Abschnitten wie 'Pflege', 'Kultur', 'Anbau', 'Standort', 'Verwendung'.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1. Suche nach passendem Artikel
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 1,
                "origin": "*",
            }
            sresp = await client.get(
                WIKI_SEARCH,
                params=search_params,
                headers={"User-Agent": "QueensPlantID-Bot/1.0 (contact@example.com)"},
            )
            sresp.raise_for_status()
            sdata = sresp.json()

            if not sdata.get("query", {}).get("search"):
                return None

            title = sdata["query"]["search"][0]["title"]

            # 2. Hole Abschnitts-Übersicht des Artikels
            sections_params = {
                "action": "parse",
                "page": title,
                "prop": "sections",
                "format": "json",
                "origin": "*",
            }
            sec_resp = await client.get(
                WIKI_SEARCH,
                params=sections_params,
                headers={"User-Agent": "QueensPlantID-Bot/1.0 (contact@example.com)"},
            )
            sec_resp.raise_for_status()
            sec_data = sec_resp.json()

            sections = sec_data.get("parse", {}).get("sections", [])
            care_sections = []
            care_keywords = ["pflege", "kultur", "anbau", "standort", "verwendung", "heilkunde", "giftigkeit", "beschreibung"]

            for sec in sections:
                line = sec.get("line", "").lower()
                if any(kw in line for kw in care_keywords):
                    care_sections.append(sec.get("index"))

            if not care_sections:
                return None

            # 3. Hole den vollständigen Text und extrahiere die relevanten Abschnitte
            text_params = {
                "action": "query",
                "prop": "extracts",
                "titles": title,
                "explaintext": True,
                "exsectionformat": "plain",
                "format": "json",
                "origin": "*",
            }
            text_resp = await client.get(
                WIKI_SEARCH,
                params=text_params,
                headers={"User-Agent": "QueensPlantID-Bot/1.0 (contact@example.com)"},
            )
            text_resp.raise_for_status()
            text_data = text_resp.json()

            pages = text_data.get("query", {}).get("pages", {})
            extract = ""
            for page in pages.values():
                extract = page.get("extract", "")
                break

            if not extract:
                return None

            # 4. Extrahiere Pflege-relevante Passagen
            # Wir splitten nach doppelten Zeilenumbrüchen (Absatz-Grenzen)
            paragraphs = [p.strip() for p in extract.split("\n\n") if p.strip()]
            care_paragraphs = []

            for para in paragraphs:
                para_lower = para.lower()
                # Absätze, die Pflege-Keywords enthalten und nicht zu kurz sind
                if any(kw in para_lower for kw in care_keywords) and len(para) > 40:
                    care_paragraphs.append(para)

            if not care_paragraphs:
                return None

            combined = "\n\n".join(care_paragraphs)[:1200]

            return {
                "title": f"Pflegehinweise: {title}",
                "extract": combined,
                "wiki_url": f"https://de.wikipedia.org/wiki/{title}",
            }
    except Exception as e:
        logger.error("Wikipedia Pflege-Tipps Fehler: %s", e)
        return None


# ── Kombinierte Funktion ──────────────────────────────────────────────────────
async def full_plant_analysis(image_bytes: bytes, filename: str = "plant.jpg") -> dict:
    """
    Kombiniert PlantNet + Perenual (Details + Diseases) + Wikipedia (Info + Care-Tips)
    zu einem umfassenden Ergebnis.
    """
    # 1. Identifikation
    id_result = await identify_plant(image_bytes, filename)
    if not id_result.get("success"):
        return id_result

    best = id_result.get("best_match")
    if not best:
        return {"success": False, "error": "Keine Übereinstimmung gefunden"}

    scientific = best.get("scientific_name", "")
    common = best.get("common_names", [""])[0] if best.get("common_names") else ""

    # 2. Seriell: Details, Krankheiten, Wikipedia Info, Wikipedia Pflege-Tipps
    # (vermeidet 429 Too Many Requests bei Perenual)
    details = None
    diseases = None
    wiki = None
    wiki_care = None

    try:
        details = await get_plant_details(scientific)
    except Exception as e:
        logger.error("Perenual Details Fehler: %s", e)
    await asyncio.sleep(1.5)

    try:
        diseases = await get_plant_diseases(scientific)
    except Exception as e:
        logger.error("Perenual Diseases Fehler: %s", e)
    await asyncio.sleep(1.5)

    try:
        wiki = await get_wiki_info(common or scientific)
    except Exception as e:
        logger.error("Wikipedia Info Fehler: %s", e)
    await asyncio.sleep(0.5)

    try:
        wiki_care = await get_wiki_care_tips(common or scientific)
    except Exception as e:
        logger.error("Wikipedia Care Fehler: %s", e)

    return {
        "success": True,
        "demo_mode": id_result.get("demo_mode", False),
        "identification": id_result,
        "details": details,
        "diseases": diseases,
        "wikipedia": wiki,
        "wikipedia_care": wiki_care,
    }

