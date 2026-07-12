# sandbox_mini_app.py – Queen's Code Sandbox Mini App (V8 – DYNAMIC LAYOUT)
# FEATURES:
# - /api/parse  – Python-Code AST-Analyse
# - /api/permissions – Berechtigungs-Tracking
# - Verbesserte Brain-Integration (Vectoring, Metadata)
# - HTML-Live-Preview Support
# - Robusteres Error-Handling

import asyncio
import base64
import json
import logging
import os
import re
import time
import ast
from io import BytesIO
from typing import Any, Dict, Optional, List
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse

from sandbox_runner import (
    EXAMPLE_TEMPLATES,
    generate_html_app,
    get_example_templates,
    run_sandboxed_code,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Queen's Code Sandbox V8")

# ── Dynamische Pfade ─────────────────────────────────────────────────────────
def _find_project_root() -> Path:
    candidates = [
        Path("/data"),           # HF Persistent Storage
        Path.cwd(),
        Path(__file__).parent.resolve(),
        Path("/opt/render/project/src"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path.cwd()

PROJECT_ROOT = _find_project_root()
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "css").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "js").mkdir(parents=True, exist_ok=True)

from fastapi.staticfiles import StaticFiles

# Mountet statische Dateien für CSS/JS absolut innerhalb der Mini-App
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

logger.info("📁 Sandbox Pfade: ROOT=%s, TEMPLATES=%s, STATIC=%s",
            PROJECT_ROOT, TEMPLATES_DIR, STATIC_DIR)

# ── Groq/AI Config ────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("XAI_API_KEY") or ""
GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("SANDBOX_CHAT_MODEL", "llama-3.3-70b-versatile")

AI_SYSTEM_PROMPT = """Du bist ein intelligenter Code-Assistent (Llama-Modell) in der Queen's Code Sandbox.
Du hilfst beim Schreiben, Verstehen und Verbessern von Python- und HTML-Code.

Deine Stärken:
- Python (numpy, pandas, matplotlib, datetime, math, json, etc.)
- HTML/CSS/JavaScript für Telegram Mini-Apps
- Code erklären, debuggen, optimieren
- Neue Funktionen und Algorithmen vorschlagen
- Code-Fehler finden und korrigieren

WICHTIG:
1. Antworte immer auf Deutsch, präzise und hilfreich.
2. Wenn du Code schreibst oder korrigierst, nutze IMMER Markdown-Code-Blöcke:
   ```python
   # dein Code hier
   ```
3. Wenn der User "Code einfügen" oder "übernehmen" sagt, antworte mit dem kompletten Code in einem Block.
4. Du kannst den Code im Editor direkt bearbeiten – schreibe den vollständigen verbesserten Code.
5. Halte Antworten kurz und praxisorientiert – max. 300 Wörter, außer bei komplexen Fragen.
6. Erkläre WAS du geändert hast und WARUM.
"""

# ── Brain Integration Helpers ────────────────────────────────────────────────
async def _save_to_brain(chat_id: str, code: str, name: str, metadata: dict = None) -> dict:
    """Speichert Code ins Brain mit Vektor-Embedding und Metadaten."""
    try:
        from brain import save_text, get_brain
        # Speichere als Text
        result = await save_text(chat_id, code, title=f"Sandbox: {name}")

        # Versuche Vector-Embedding
        try:
            brain = await get_brain(chat_id)
            if brain and hasattr(brain, 'add'):
                doc_meta = metadata or {}
                doc_meta.update({
                    "source": "sandbox",
                    "type": "code",
                    "language": metadata.get("language", "python") if metadata else "python",
                    "timestamp": time.time(),
                    "title": f"Sandbox: {name}"
                })
                await brain.add(
                    texts=[code[:4000]],
                    metadatas=[doc_meta]
                )
                logger.info("🧠 Vector-Embedding für Sandbox-Code erstellt")
        except Exception as ve:
            logger.warning("Vector-Embedding nicht verfügbar: %s", ve)

        return {"success": True, "message": result, "brain_id": result}
    except ImportError:
        logger.warning("Brain-Modul nicht verfügbar")
        return {"success": False, "message": "Brain-Modul nicht geladen"}
    except Exception as e:
        logger.exception("Brain-Save Fehler")
        return {"success": False, "message": f"Fehler: {str(e)}"}


# ── Hilfsfunktion: HTML laden ─────────────────────────────────────────────────
def _load_template(name: str) -> str:
    """Robuste Template-Suche für Hugging Face Spaces"""
    candidates = [
        TEMPLATES_DIR / name,
        PROJECT_ROOT / "templates" / name,
        Path.cwd() / "templates" / name,
        Path("/data/templates") / name,
        Path(__file__).parent.parent / "templates" / name,
        Path("/home/user/app/templates") / name,
    ]

    for path in candidates:
        if path.exists() and path.is_file():
            logger.info(f"✅ Template geladen: {path}")
            return path.read_text(encoding="utf-8")

    logger.error(f"❌ Template {name} NICHT GEFUNDEN in allen Pfaden!")
    return _get_fallback_html()

def _get_fallback_html() -> str:
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
    <link rel="stylesheet" href="static/css/sandbox.css">
</head>
<body>
    <p style="color:red;padding:20px;">⚠️ Template-Datei fehlt. Bitte templates/sandbox.html erstellen.</p>
</body>
</html>"""


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def sandbox_home():
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


@app.post("/api/parse")
async def parse_code_endpoint(request: Request):
    """
    AST-basierter Python-Code-Parser + HTML Structure Parser.
    Body: { "code": str, "language": str (optional) }
    """
    try:
        data = await request.json()
        code = data.get("code", "").strip()
        language = data.get("language", "python")

        if not code:
            return JSONResponse({"error": "Kein Code angegeben"}, status_code=400)

        if language == "html":
            return _parse_html(code)

        # Python AST Parser
        try:
            tree = ast.parse(code)
        except SyntaxError as se:
            return JSONResponse({
                "error": f"Syntax-Fehler: {se.msg} (Zeile {se.lineno})"
            }, status_code=400)

        # Set parent references for context
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                setattr(child, '_parent', parent)

        elements = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    elements.append({
                        "type": "import",
                        "name": alias.name,
                        "line": node.lineno,
                        "detail": alias.asname or ""
                    })
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    elements.append({
                        "type": "import",
                        "name": f"{module}.{alias.name}" if module else alias.name,
                        "line": node.lineno,
                        "detail": alias.asname or ""
                    })
            elif isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = [arg.arg for arg in item.args.args]
                        methods.append({
                            "type": "function",
                            "name": item.name,
                            "line": item.lineno,
                            "detail": ", ".join(args)
                        })
                parent_classes = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        parent_classes.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        parent_classes.append(f"{b.value.id}.{b.attr}" if isinstance(b.value, ast.Name) else b.attr)

                elements.append({
                    "type": "class",
                    "name": node.name,
                    "line": node.lineno,
                    "detail": ", ".join(parent_classes),
                    "children": methods
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip methods inside classes (handled above)
                parent = getattr(node, '_parent', None)
                if isinstance(parent, ast.ClassDef):
                    continue
                args = [arg.arg for arg in node.args.args]
                # Include decorators
                decorators = []
                for d in node.decorator_list:
                    if isinstance(d, ast.Name):
                        decorators.append(d.id)
                    elif isinstance(d, ast.Call) and isinstance(d.func, ast.Name):
                        decorators.append(f"{d.id}()")

                detail = ", ".join(args)
                if decorators:
                    detail = f"@{', @'.join(decorators)} | {detail}"

                elements.append({
                    "type": "function",
                    "name": node.name,
                    "line": node.lineno,
                    "detail": detail
                })
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        value_preview = ""
                        if isinstance(node.value, ast.Constant):
                            value_preview = repr(node.value.value)[:40]
                        elif isinstance(node.value, ast.List):
                            value_preview = "[...]"
                        elif isinstance(node.value, ast.Dict):
                            value_preview = "{...}"
                        elif isinstance(node.value, ast.Call):
                            if isinstance(node.value.func, ast.Name):
                                value_preview = f"{node.value.func.name}()"
                            elif isinstance(node.value.func, ast.Attribute):
                                value_preview = f"...{node.value.func.attr}()"
                        else:
                            value_preview = ast.dump(node.value)[:40]

                        elements.append({
                            "type": "variable",
                            "name": target.id,
                            "line": node.lineno,
                            "detail": value_preview
                        })
            elif isinstance(node, ast.For):
                elements.append({
                    "type": "loop",
                    "name": f"for-loop (Zeile {node.lineno})",
                    "line": node.lineno,
                    "detail": ""
                })
            elif isinstance(node, ast.While):
                elements.append({
                    "type": "loop",
                    "name": f"while-loop (Zeile {node.lineno})",
                    "line": node.lineno,
                    "detail": ""
                })

        # Sort by line number
        elements.sort(key=lambda x: x["line"])

        return {
            "success": True,
            "elements": elements,
            "stats": {
                "imports": len([e for e in elements if e["type"] == "import"]),
                "classes": len([e for e in elements if e["type"] == "class"]),
                "functions": len([e for e in elements if e["type"] == "function"]),
                "variables": len([e for e in elements if e["type"] == "variable"]),
                "loops": len([e for e in elements if e["type"] == "loop"]),
            }
        }

    except Exception as e:
        logger.exception("Parse-Endpoint Fehler")
        return JSONResponse({"error": f"Parser-Fehler: {str(e)}"}, status_code=500)


def _parse_html(code: str) -> dict:
    """Einfacher HTML-Struktur-Parser."""
    import re
    elements = []
    tag_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*?>', re.MULTILINE)
    id_pattern = re.compile(r'\bid=["\']([^"\']+)["\']')
    class_pattern = re.compile(r'\bclass=["\']([^"\']+)["\']')

    seen = set()
    for match in tag_pattern.finditer(code):
        tag = match.group(1).lower()
        line = code[:match.start()].count('\n') + 1
        key = f"{tag}-{line}"
        if key in seen:
            continue
        seen.add(key)

        snippet = code[match.start():match.end() + 80]
        id_val = id_pattern.search(snippet)
        class_val = class_pattern.search(snippet)

        detail_parts = []
        if id_val:
            detail_parts.append(f"#{id_val.group(1)}")
        if class_val:
            classes = class_val.group(1).split()[:2]
            detail_parts.append('.' + '.'.join(classes))

        elements.append({
            "type": "tag",
            "name": tag,
            "line": line,
            "detail": " ".join(detail_parts)
        })

    # Group stats
    tag_counts = {}
    for e in elements:
        tag_counts[e["name"]] = tag_counts.get(e["name"], 0) + 1

    return {
        "success": True,
        "elements": elements[:100],  # Limit
        "stats": {
            "tags": len(elements),
            "unique_tags": len(tag_counts),
            "top_tags": sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        }
    }


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    try:
        data = await request.json()
        user_message = (data.get("message") or "").strip()
        current_code = (data.get("code") or "").strip()
        history: List[Dict] = data.get("history") or []
        chat_id = data.get("chat_id")

        if not user_message:
            return JSONResponse({"error": "Keine Nachricht"}, status_code=400)

        if not GROQ_API_KEY:
            return {
                "reply": "⚠️ Kein AI-API-Key konfiguriert. Bitte GROQ_API_KEY in den Umgebungsvariablen setzen.",
                "model": "offline"
            }

        messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}]

        for msg in history[-10:]:
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})

        user_content = user_message
        if current_code:
            lang = "python" if not current_code.strip().startswith("<") else "html"
            user_content = (
                f"Aktueller Code im Editor:\n```{lang}\n{current_code[:2000]}\n```\n\n"
                f"Frage: {user_message}"
            )

        messages.append({"role": "user", "content": user_content})

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                GROQ_BASE_URL,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_MODEL,
                    "messages": messages,
                    "max_tokens": 800,
                    "temperature": 0.7,
                },
            )

        if response.status_code != 200:
            logger.error("Groq API Fehler: %s %s", response.status_code, response.text[:200])
            return JSONResponse(
                {"error": f"AI-Fehler: {response.status_code}"},
                status_code=502,
            )

        resp_json = response.json()
        reply = resp_json["choices"][0]["message"]["content"]

        # Extrahiere Code-Blöcke für Auto-Einfügen-Feature
        extracted_code = None
        import re
        code_block_match = re.search(r'```(?:python|html)?\n([\s\S]*?)```', reply)
        if code_block_match:
            extracted_code = code_block_match.group(1).strip()

        # Speichere Chat-Turn im Brain für Kontinuität
        if chat_id:
            try:
                from brain import save_text
                await save_text(
                    str(chat_id),
                    f"Sandbox-KI-Chat\nNutzer: {user_message}\nKI: {reply[:500]}",
                    title="Sandbox KI-Chat"
                )
            except Exception:
                pass

        return {
            "reply": reply,
            "model": resp_json.get("model", GROQ_MODEL),
            "code": extracted_code,
        }

    except httpx.TimeoutException:
        return JSONResponse({"error": "AI-Antwort Timeout (30s). Bitte erneut versuchen."}, status_code=504)
    except Exception as e:
        logger.exception("Chat-Endpoint Fehler")
        return JSONResponse({"error": f"Fehler: {str(e)}"}, status_code=500)


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), chat_id: str = Form("sandbox")):
    try:
        content = await file.read()

        text_extensions = ['.py', '.txt', '.csv', '.json', '.html', '.js', '.css', '.md']
        file_ext = os.path.splitext(file.filename)[1].lower()

        if file_ext in text_extensions:
            try:
                code = content.decode('utf-8')
                # Speichere Upload auch im Brain
                try:
                    await _save_to_brain(
                        chat_id, code, file.filename,
                        metadata={"language": file_ext.lstrip('.'), "filename": file.filename}
                    )
                except Exception:
                    pass
                return {
                    "success": True,
                    "code": code,
                    "filename": file.filename,
                    "message": f"✅ {file.filename} geladen"
                }
            except UnicodeDecodeError:
                pass

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
        language = data.get("language", "python")

        if not chat_id:
            return {"success": False, "message": "Keine chat_id angegeben"}

        result = await _save_to_brain(
            chat_id, code, name,
            metadata={"language": language}
        )
        return result

    except Exception as e:
        logger.exception("Brain-Save Fehler")
        return {"success": False, "message": f"Fehler: {str(e)}"}


@app.post("/api/permissions")
async def permissions_endpoint(request: Request):
    """
    Trackt und validiert Sandbox-Berechtigungen.
    Body: { "chat_id": str, "permissions": ["file", "clipboard", "notifications"] }
    """
    try:
        data = await request.json()
        chat_id = data.get("chat_id", "sandbox")
        requested = data.get("permissions", [])

        # Hier könnte man Berechtigungen in einer DB speichern
        # Für jetzt: einfach validieren und bestätigen
        granted = []
        for perm in requested:
            if perm in ["file", "clipboard", "notifications", "brain", "vector"]:
                granted.append(perm)

        return {
            "success": True,
            "chat_id": chat_id,
            "granted": granted,
            "features": {
                "file_upload": True,
                "brain_save": True,
                "vector_search": True,
                "ai_chat": bool(GROQ_API_KEY),
                "code_execution": True,
                "html_preview": True,
                "ast_parser": True,
            }
        }
    except Exception as e:
        logger.exception("Permissions Fehler")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "sandbox": "ready",
        "version": "8.0.0-dynamic",
        "features": [
            "python", "html", "matplotlib", "pandas", "numpy",
            "file-upload", "ai-chat", "brain-integration",
            "vector-embedding", "html-preview", "ast-parser",
            "permissions", "drag-drop"
        ],
        "ai_chat": bool(GROQ_API_KEY),
        "ai_model": GROQ_MODEL,
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "templates": str(TEMPLATES_DIR),
            "static": str(STATIC_DIR),
        }
    }
