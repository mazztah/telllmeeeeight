# plantid_mini_app.py – Queen's Plant-ID Scanner Mini-App (schlank, Template extern)
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import base64
import json
import logging

from plantid_api import full_plant_analysis
from plantid_agent import fetch_care_tips_from_web, chat_with_plant_agent

logger = logging.getLogger(__name__)

app = FastAPI(title="Queen's Plant-ID Scanner 🌿")

# ── Statische Dateien servieren (CSS, JS) ───────────────────────────────────
STATIC_DIR = Path(__file__).with_name("static")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Template laden ───────────────────────────────────────────────────────────
TEMPLATE_PATH = Path(__file__).with_name("templates") / "plantid.html"
if not TEMPLATE_PATH.exists():
    # Fallback wenn wir aus einem anderen CWD laufen
    TEMPLATE_PATH = Path("templates/plantid.html")

HTML_TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8") if TEMPLATE_PATH.exists() else "<!-- Template fehlt -->"


@app.get("/", response_class=HTMLResponse)
async def plantid_page(request: Request):
    return HTMLResponse(HTML_TEMPLATE)


@app.post("/api/analyze")
async def plantid_analyze(request: Request):
    """Empfängt Base64-Bild und gibt vollständige Analyse zurück."""
    try:
        body = await request.json()
        image_base64 = body.get("image_base64")

        if not image_base64:
            return JSONResponse({"success": False, "error": "image_base64 required"})

        image_bytes = base64.b64decode(image_base64)
        result = await full_plant_analysis(image_bytes, filename="plant.jpg")
        return JSONResponse(result)

    except Exception as e:
        logger.exception("Plant-ID Analyse-Fehler in Mini-App")
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/api/search-care")
async def plantid_search_care(request: Request):
    """Web-Suche nach Pflegehinweisen für die erkannte Pflanze."""
    try:
        body = await request.json()
        plant_name = body.get("plant_name", "").strip()

        if not plant_name:
            return JSONResponse({"success": False, "error": "plant_name required"})

        result = await fetch_care_tips_from_web(plant_name)
        return JSONResponse(result)

    except Exception as e:
        logger.exception("Plant-ID Pflegehinweis-Suche-Fehler")
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/api/chat")
async def plantid_chat(request: Request):
    """Chat mit dem Plant-Agenten über die aktuelle Analyse."""
    try:
        body = await request.json()
        question = body.get("message", "").strip()
        plant_context = body.get("plant_context", {})
        history = body.get("history", [])

        if not question:
            return JSONResponse({"success": False, "error": "message required"})

        result = await chat_with_plant_agent(question, plant_context, history)
        return JSONResponse(result)

    except Exception as e:
        logger.exception("Plant-ID Chat-Fehler")
        return JSONResponse({"success": False, "error": str(e)})
