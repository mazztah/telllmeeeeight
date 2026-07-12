# sandbox_mini_app.py – Queen's Code Sandbox Mini App (V6 – REFACTORED)
# - HTML/CSS/JS in separate Dateien
# - Dynamische Pfade (funktioniert lokal UND auf Render)
# - Kein Import-Crash mehr

import asyncio
import json
import logging
import os
import re
import time
from io import BytesIO
from typing import Any, Dict, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sandbox_runner import (
    EXAMPLE_TEMPLATES,
    generate_html_app,
    get_example_templates,
    run_sandboxed_code,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Queen's Code Sandbox V6")

# ── Dynamische Pfade ─────────────────────────────────────────────────────────
# Strategie: Versuche mehrere mögliche Pfade (lokal, Render, etc.)

def _find_project_root() -> Path:
    """Findet das Projekt-Root-Verzeichnis."""
    # 1. Aktuelles Verzeichnis (wo main.py läuft)
    cwd = Path.cwd()

    # 2. Verzeichnis dieser Datei
    this_file_dir = Path(__file__).parent.resolve()

    # 3. Render-spezifisch: /opt/render/project/src/
    render_dir = Path("/opt/render/project/src")

    # Prüfe welches Verzeichnis main.py enthält oder existiert
    for candidate in [cwd, this_file_dir, render_dir]:
        if candidate.exists():
            return candidate

    return cwd  # Fallback


PROJECT_ROOT = _find_project_root()
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

# Sicherstellen dass die Verzeichnisse existieren
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "js").mkdir(parents=True, exist_ok=True)

logger.info("📁 Sandbox Pfade: ROOT=%s, TEMPLATES=%s, STATIC=%s", 
            PROJECT_ROOT, TEMPLATES_DIR, STATIC_DIR)

# ── Static Files Mount ───────────────────────────────────────────────────────
# Wichtig: Mount muss VOR den Routes passieren
app.mount("/sandbox/static", StaticFiles(directory=str(STATIC_DIR)), name="sandbox_static")

# ── Hilfsfunktion: HTML laden ─────────────────────────────────────────────────
def _load_template(name: str) -> str:
    """Lädt ein Template aus dem templates-Verzeichnis."""
    template_path = TEMPLATES_DIR / name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    logger.warning("Template nicht gefunden: %s", template_path)
    return _get_fallback_html()


def _get_fallback_html() -> str:
    """Fallback HTML wenn Template-Dateien fehlen."""
    return """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Queen's Code Sandbox</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/ace.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/mode-python.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/mode-html.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/ace/1.32.0/theme-monokai.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/sandbox/static/css/sandbox.css">
</head>
<body>
    <div id="app">
        <div id="header">
            <h1><span>👑</span> Queen's Code Sandbox</h1>
            <div class="header-btns">
                <button class="btn btn-secondary btn-sm" id="btn-examples">📚</button>
                <button class="btn btn-secondary btn-sm" id="btn-clear">🗑️</button>
                <button class="btn btn-run" id="btn-run">
                    <span>▶️</span> <span id="run-text">Ausführen</span>
                </button>
            </div>
        </div>
        <div id="toolbar">
            <div class="toolbar-group">
                <select id="lang-select">
                    <option value="python">🐍 Python</option>
                    <option value="html">🌐 HTML</option>
                </select>
            </div>
            <div class="toolbar-sep"></div>
            <div class="toolbar-group">
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="hello">👋 Hallo</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="plot">📊 Plot</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="dataframe">📋 Data</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="chart">📈 Chart</button>
                <button class="btn btn-secondary btn-sm btn-tpl" data-tpl="mini_app">🎨 App</button>
            </div>
            <div class="toolbar-sep"></div>
            <div class="toolbar-group">
                <button class="btn btn-secondary btn-sm" id="btn-save">💾</button>
                <button class="btn btn-gold btn-sm" id="btn-share">📤</button>
            </div>
        </div>
        <div id="workspace">
            <div id="editor-wrap">
                <div id="editor-container"></div>
            </div>
            <div id="output-wrap">
                <div id="collapse-bar">
                    <span class="collapse-icon">🔽</span>
                    <span id="collapse-text">Terminal minimieren</span>
                </div>
                <div class="output-inner">
                    <div id="output-tabs">
                        <button class="output-tab active" data-pane="terminal">🖥️ Terminal</button>
                        <button class="output-tab" data-pane="plot">📊 Plot</button>
                        <button class="output-tab" data-pane="file">📁 Datei</button>
                    </div>
                    <div id="terminal" class="output-pane active"></div>
                    <div id="plot-pane" class="output-pane"></div>
                    <div id="file-pane" class="output-pane">
                        <div class="upload-area" id="upload-area">
                            <input type="file" id="file-input" accept=".py,.txt,.csv,.json,.html,.js,.css">
                            <div style="font-size: 2rem; margin-bottom: 8px;">📁</div>
                            <div style="font-weight: 600; margin-bottom: 4px;">Datei hochladen</div>
                            <div style="font-size: 0.78rem;">Tippe zum Auswählen</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div id="status-bar">
            <div class="status-item">
                <div class="status-dot" id="status-dot"></div>
                <span id="status-text">Bereit</span>
            </div>
            <div class="status-item">
                <span id="cursor-pos">Ln 1, Col 1</span>
            </div>
            <div class="status-item">
                <span id="exec-time"></span>
            </div>
        </div>
    </div>
    <div id="modal-overlay">
        <div class="modal-box">
            <div class="modal-header">
                <h2>📚 Code-Beispiele</h2>
                <button class="modal-close" id="modal-close">×</button>
            </div>
            <div class="modal-body" id="modal-body"></div>
        </div>
    </div>
    <div id="toast"></div>
    <script src="/sandbox/static/js/sandbox.js"></script>
</body>
</html>"""


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def sandbox_home():
    """Liefert die Sandbox HTML-Seite."""
    html = _load_template("sandbox.html")
    return HTMLResponse(html)


@app.get("/api/templates")
async def get_templates():
    return {"templates": get_example_templates()}


@app.post("/api/run")
async def run_code_endpoint(request: Request):
    try:
        data = await request.json()
        code = data.get("code", "").strip()
        language = data.get("language", "python")
        chat_id = data.get("chat_id")

        if not code:
            return JSONResponse({"success": False, "error": "Kein Code angegeben"}, status_code=400)

        if language == "html":
            buffer, filename = generate_html_app(code, "Sandbox App")
            import base64
            return {
                "success": True,
                "output": "✅ HTML Mini-App generiert",
                "file": {
                    "name": filename,
                    "data": base64.b64encode(buffer.getvalue()).decode("utf-8"),
                },
                "plot": None,
                "error": None,
                "execution_time": 0.1,
            }

        result = await run_sandboxed_code(code, chat_id=chat_id)

        plot_b64 = None
        if result.get("plot"):
            import base64
            plot_b64 = base64.b64encode(result["plot"].getvalue()).decode("utf-8")

        file_data = None
        if result.get("file"):
            import base64
            buf, fname = result["file"]
            file_data = {
                "name": fname,
                "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
            }

        return {
            "success": result["success"],
            "output": result["output"],
            "error": result["error"],
            "plot": plot_b64,
            "file": file_data,
            "result": str(result["result"]) if result["result"] is not None else None,
            "execution_time": result["execution_time"],
        }

    except Exception as e:
        logger.exception("Sandbox API Fehler")
        return JSONResponse(
            {"success": False, "error": f"Server-Fehler: {str(e)}"},
            status_code=500,
        )


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), chat_id: str = Form("sandbox")):
    """Datei-Upload Endpoint – lädt Datei ins Editor oder Brain"""
    try:
        content = await file.read()

        # Wenn es eine Textdatei ist, gib den Code zurück
        text_extensions = ['.py', '.txt', '.csv', '.json', '.html', '.js', '.css', '.md']
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext in text_extensions:
            try:
                code = content.decode('utf-8')
                return {
                    "success": True,
                    "code": code,
                    "filename": file.filename,
                    "message": f"✅ {file.filename} geladen"
                }
            except UnicodeDecodeError:
                pass

        # Sonst speichere als Binärdatei
        import base64
        encoded = base64.b64encode(content).decode('utf-8')
        return {
            "success": True,
            "filename": file.filename,
            "data": encoded,
            "message": f"✅ {file.filename} hochgeladen"
        }

    except Exception as e:
        logger.exception("Upload Fehler")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.post("/api/save")
async def save_code_endpoint(request: Request):
    try:
        data = await request.json()
        code = data.get("code", "")
        name = data.get("name", "sandbox_code")
        chat_id = data.get("chat_id")

        if not chat_id:
            return {"success": False, "message": "Keine chat_id angegeben"}

        from brain import save_text
        result = await save_text(chat_id, code, title=f"Sandbox: {name}")

        return {"success": "ID:" in result, "message": result}

    except Exception as e:
        logger.exception("Brain-Save Fehler")
        return {"success": False, "message": f"Fehler: {str(e)}"}


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "sandbox": "ready",
        "version": "6.1.0-refactored",
        "features": ["python", "html", "matplotlib", "pandas", "numpy", "file-upload"],
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "templates": str(TEMPLATES_DIR),
            "static": str(STATIC_DIR),
        }
    }
