# super_skill_app.py – Super-Skill.md Generator (Konsolidiert v3.0)
# Nutzt offizielles groq.AsyncGroq SDK (kein custom httpx)
# Kein @router.get("/") – HTML wird von main.py serviert

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# KONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
FALLBACK_MODEL = "llama3-70b-8192"

PROJECT_DIR = Path(__file__).parent


def _resolve_skills_dir() -> Path:
    candidates: List[Path] = []

    custom = (os.getenv("SUPERSKILL_DIR") or "").strip()
    if custom:
        candidates.append(Path(custom))

    data_dir = (os.getenv("DATA_DIR") or "").strip()
    if data_dir:
        candidates.append(Path(data_dir) / "superskill_skills")

    candidates.extend(
        [
            Path("/data/superskill_skills"),
            Path("/tmp/superskill_skills"),
            PROJECT_DIR / ".superskill_skills",
        ]
    )

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            logger.info("✅ SuperSkill SKILLS_DIR aktiv: %s", candidate)
            return candidate
        except Exception as e:
            logger.warning("SKILLS_DIR nicht nutzbar (%s): %s", candidate, e)

    fallback = PROJECT_DIR
    logger.warning("⚠️ SuperSkill fallback auf Projektordner: %s", fallback)
    return fallback


SKILLS_DIR = _resolve_skills_dir()

# ═══════════════════════════════════════════════════════════════════════════════
# GROQ CLIENT (offizielles SDK, lazy init)
# ═══════════════════════════════════════════════════════════════════════════════

_groq_client = None

def get_groq():
    global _groq_client
    if _groq_client is None:
        try:
            import groq as _groq_sdk
            if not GROQ_API_KEY:
                raise RuntimeError("GROQ_API_KEY nicht gesetzt!")
            _groq_client = _groq_sdk.AsyncGroq(api_key=GROQ_API_KEY)
            logger.info("✅ SuperSkill Groq-Client initialisiert")
        except ImportError:
            raise RuntimeError("groq-Paket fehlt. pip install groq")
    return _groq_client


async def call_groq(messages: List[Dict], max_tokens: int = 8000, stream: bool = False):
    """Groq-Call mit Fallback auf llama3-70b bei Fehler."""
    client = get_groq()

    for model in [GROQ_MODEL, FALLBACK_MODEL]:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=stream,
            )
            if stream:
                return resp          # async generator
            content = resp.choices[0].message.content
            if not content or len(content) < 50:
                raise ValueError(f"Zu kurze Antwort ({len(content or '')} Zeichen)")
            logger.info(f"✅ Groq OK mit {model} ({len(content)} Zeichen)")
            return content
        except Exception as e:
            logger.warning(f"Groq-Fehler mit {model}: {e}")
            if model == FALLBACK_MODEL:
                raise

    raise RuntimeError("Beide Groq-Modelle fehlgeschlagen")


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

POWERSKILL_SYSTEM = """Du bist der "Perfect PowerSkill Creator" (v3.0) — ein Meta-Skill für die Erstellung
professioneller, deterministischer PowerSkill.md Dateien auf Enterprise-Niveau.

REGELN:
1. Jede PowerSkill.md MUSS alle 17 Pflichtabschnitte enthalten
2. YAML-Frontmatter ist Pflicht (title, version, last_updated, author, purpose, tags, compatibility)
3. Output: Deterministisch, modular, versioniert, AI-Native
4. Sprache: Primär Deutsch, Fachbegriffe Englisch
5. Mindestens 1 konkretes Input/Output-Beispiel
6. Anti-Patterns müssen explizit benannt werden
7. Qualitäts-Checkliste am Ende jeder Erstellung
8. Semantic Versioning (MAJOR.MINOR.PATCH)
9. Mermaid-Diagramme für Workflows
10. Kompetenzmatrix mit Level/Stand/Stärken

STRUKTUR (17 Pflichtabschnitte):
1. YAML-Frontmatter
2. One-Liner (max 2 Sätze)
3. Inhaltsverzeichnis
4. Ziel & Zweck (Problem + Value Proposition)
5. Anwendungsbereiche (Primär/Sekundär/Nicht geeignet)
6. Aktivierung (exakter Prompt-Text)
7. Skill-Anatomie (Dateistruktur)
8. Kompetenzmatrix
9. Bestandteile (State-of-the-Art 2026)
10. Workflows (mit Mermaid)
11. Core Principles (5-8 Prinzipien)
12. Output-Format-Regeln
13. Beispiele (Input/Output)
14. Anti-Patterns
15. Qualitäts-Checkliste
16. Kombinierbarkeit
17. Versionshistorie

OUTPUT-REGELN:
- Min 400 Zeilen, Optimal 400-700, Max 800
- Professionell, präzise, hohe Dichte
- Tabellen für Matrizen, Code-Blöcke für Aktivierungstexte
"""

CHAT_SYSTEM = """Du bist der Groq Assistant im Super-Skill.md Generator.

Deine Aufgaben:
1. Hilf bei der Definition und Optimierung von Skill-Scopes
2. Erkläre die 17-Pflichtabschnitte-Struktur
3. Reviewe generierte Skills auf Qualität
4. Schlage Verbesserungen vor
5. Beantworte Fragen zu Prompt Engineering, Mermaid-Diagrammen und KI-Skill-Design

Regeln:
- Antworte präzise und strukturiert (Markdown)
- Mermaid-Syntax für Diagramme
- Sprache: Deutsch (außer Fachbegriffe)
"""

# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class SkillRequest(BaseModel):
    scope:     str       = Field(..., description="Was soll der Skill können?")
    audience:  str       = Field(default="Senior Engineer")
    depth:     str       = Field(default="Detailliert")
    model:     str       = Field(default="Claude 4")
    workflows: List[str] = Field(default=[])

class RefineRequest(BaseModel):
    feedback: str = Field(..., description="Verbesserungswunsch")

# In-memory Skill-Cache
_skills: Dict[str, Dict[str, Any]] = {}

# ═══════════════════════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ═══════════════════════════════════════════════════════════════════════════════

def _sanitize(name: str) -> str:
    return re.sub(r'\s+', '_', re.sub(r'[^\w\s-]', '', name))[:50].lower()

def _save(skill_id: str, content: str, title: str) -> Path:
    path = SKILLS_DIR / f"{_sanitize(title)}_{skill_id[:8]}.md"
    path.write_text(content, encoding="utf-8")
    return path

def _build_prompt(req: SkillRequest) -> str:
    wf = ", ".join(req.workflows) if req.workflows else "Erstellung, Optimierung"
    return f"""ERSTELLE EINE VOLLSTÄNDIGE POWERSKILL.MD DATEI

SCOPE-DEFINITION:
1. Was: {req.scope}
2. Wer: {req.audience}
3. Tiefe: {req.depth}
4. Modell: {req.model}
5. Workflows: {wf}

AUFGABE:
Generiere eine vollständige, professionelle PowerSkill.md Datei mit ALLEN 17 Pflichtabschnitten.
Die Datei muss sofort produktionsreif sein.

FORMAT:
- Markdown mit YAML-Frontmatter
- Mermaid-Diagramme für Workflows
- Tabellen für Kompetenzmatrix
- Code-Blöcke für Aktivierungstexte
- Anti-Patterns explizit benennen
- Qualitäts-Checkliste am Ende

BEGINNE JETZT MIT DER VOLLSTÄNDIGEN DATEI:"""

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER (KEIN @router.get("/") – verhindert Konflikt mit main.py)
# ═══════════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/superskill", tags=["superskill"])

# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/api/health")
async def health():
    groq_ok = "ok"
    try:
        get_groq()
    except Exception as e:
        groq_ok = f"error: {e}"
    return {
        "status": "ok",
        "groq": groq_ok,
        "model": GROQ_MODEL,
        "skills_memory": len(_skills),
        "skills_disk": len(list(SKILLS_DIR.glob("*.md"))),
        "timestamp": datetime.now().isoformat(),
    }

# ── Generate ──────────────────────────────────────────────────────────────────

@router.post("/api/generate-skill")
async def generate_skill(req: SkillRequest):
    logger.info(f"🚀 Skill-Generierung: scope='{req.scope[:60]}...'")

    if len(req.scope.strip()) < 10:
        return JSONResponse({"success": False, "error": "Scope zu kurz (min. 10 Zeichen)"}, status_code=400)

    try:
        messages = [
            {"role": "system", "content": POWERSKILL_SYSTEM},
            {"role": "user",   "content": _build_prompt(req)},
        ]
        content = await call_groq(messages, max_tokens=8000)

        skill_id = f"skill_{uuid.uuid4().hex[:12]}"
        title    = req.scope[:60].replace("\n", " ")

        # Titel aus YAML extrahieren falls vorhanden
        m = re.search(r'title:\s*(.+)', content)
        if m:
            title = m.group(1).strip().strip('"\'')

        path = _save(skill_id, content, title)

        skill_data = {
            "skill_id":     skill_id,
            "title":        title,
            "full_content": content,
            "filename":     path.name,
            "created":      datetime.now().isoformat(),
        }
        _skills[skill_id] = skill_data

        logger.info(f"✅ Skill generiert: {skill_id} ({len(content)} Zeichen)")
        return JSONResponse({"success": True, "skill": skill_data})

    except Exception as e:
        logger.exception("Skill-Generierung fehlgeschlagen")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# ── Refine ────────────────────────────────────────────────────────────────────

@router.post("/api/refine-skill/{skill_id}")
async def refine_skill(skill_id: str, req: RefineRequest):
    logger.info(f"✨ Skill-Refinement: {skill_id}")

    skill = _skills.get(skill_id)
    if not skill:
        for p in SKILLS_DIR.glob("*.md"):
            if skill_id[:8] in p.name:
                skill = {"skill_id": skill_id, "title": p.stem, "full_content": p.read_text("utf-8")}
                break

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill {skill_id} nicht gefunden")

    try:
        messages = [
            {"role": "system", "content": POWERSKILL_SYSTEM},
            {"role": "user",   "content": f"Hier ist die aktuelle PowerSkill.md:\n\n{skill['full_content']}"},
            {"role": "user",   "content": f"Bitte verbessere basierend auf diesem Feedback:\n{req.feedback}\n\nGib die KOMPLETTE überarbeitete Datei aus."},
        ]
        content  = await call_groq(messages, max_tokens=8000)
        path     = _save(skill_id, content, skill["title"] + "_refined")

        skill.update({
            "full_content":        content,
            "filename":            path.name,
            "refined_at":          datetime.now().isoformat(),
            "refinement_feedback": req.feedback,
        })
        _skills[skill_id] = skill

        logger.info(f"✅ Skill verfeinert: {skill_id}")
        return JSONResponse({"success": True, "skill": skill})

    except Exception as e:
        logger.exception("Refinement fehlgeschlagen")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/api/list-skills")
async def list_skills():
    skills = []
    for sid, sk in _skills.items():
        skills.append({
            "skill_id":     sid,
            "title":        sk.get("title", "Unbenannt"),
            "filename":     sk.get("filename", f"{sid}.md"),
            "size":         len(sk.get("full_content", "")),
            "created":      sk.get("created", ""),
            "download_url": f"/superskill/api/download-skill/{sid}",
        })
    # Fallback: Disk-Dateien
    if not skills:
        for p in sorted(SKILLS_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
            skills.append({
                "skill_id":     f"disk_{p.stem}",
                "title":        p.stem.replace("_", " ").title(),
                "filename":     p.name,
                "size":         p.stat().st_size,
                "created":      datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                "download_url": f"/superskill/api/download-skill/disk_{p.stem}",
            })
    return {"skills": skills}

# ── Download ──────────────────────────────────────────────────────────────────

@router.get("/api/download-skill/{skill_id}")
async def download_skill(skill_id: str):
    skill = _skills.get(skill_id)
    if skill:
        fn = skill.get("filename", f"{_sanitize(skill['title'])}.md")
        return PlainTextResponse(
            content=skill["full_content"],
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'},
        )
    for p in SKILLS_DIR.glob("*.md"):
        if skill_id.replace("disk_", "") in p.stem or skill_id[:8] in p.name:
            return FileResponse(path=p, media_type="text/markdown", filename=p.name)
    raise HTTPException(status_code=404, detail=f"Skill {skill_id} nicht gefunden")

# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET CHAT
# ═══════════════════════════════════════════════════════════════════════════════

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    client_id = f"ws_{uuid.uuid4().hex[:8]}"
    logger.info(f"🔌 WebSocket verbunden: {client_id}")

    # Kontext-History pro Verbindung
    history: List[Dict] = [{"role": "system", "content": CHAT_SYSTEM}]

    try:
        while True:
            raw  = await websocket.receive_text()
            data = json.loads(raw)
            msg  = data.get("message", "").strip()

            if not msg:
                await websocket.send_json({"type": "error", "message": "Leere Nachricht"})
                continue

            logger.info(f"💬 {client_id}: {msg[:80]}")
            history.append({"role": "user", "content": msg})

            # Typing-Indicator
            await websocket.send_json({"type": "typing", "status": True})

            try:
                # Streaming-Antwort
                stream       = await call_groq(history[-12:], max_tokens=4000, stream=True)
                full_response = ""

                async for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full_response += delta
                        await websocket.send_json({"type": "stream", "chunk": delta})

                history.append({"role": "assistant", "content": full_response})
                await websocket.send_json({"type": "done", "full_response": full_response})

            except Exception as e:
                logger.error(f"Chat-Fehler ({client_id}): {e}")
                await websocket.send_json({"type": "error", "message": f"KI-Fehler: {str(e)}"})

            finally:
                await websocket.send_json({"type": "typing", "status": False})

    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket getrennt: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket-Fehler ({client_id}): {e}")
        try:
            await websocket.send_json({"type": "error", "message": f"Server-Fehler: {str(e)}"})
            await websocket.close()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_superskill(update, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    base_url = (
        os.getenv("WEBHOOK_URL") or
        os.getenv("RENDER_EXTERNAL_URL") or
        os.getenv("SPACE_HOST") or ""
    ).rstrip("/")

    # HF setzt SPACE_HOST oft ohne Protokoll.
    if base_url and not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"

    # Zusätzlicher Fallback für HF Spaces:
    if not base_url:
        space_id = os.getenv("SPACE_ID", "").strip()
        if space_id:
            # z.B. "user/space" -> "https://user-space.hf.space"
            normalized = space_id.replace("/", "-")
            base_url = f"https://{normalized}.hf.space"

    if base_url:
        url = f"{base_url}/superskill/"
        keyboard = [[InlineKeyboardButton("🚀 SuperSkill Generator öffnen", url=url)]]
        await update.message.reply_text(
            "⚡ *Super-Skill.md Generator*\n\n"
            "Erstelle professionelle PowerSkills mit Groq LLaMA-4.\n"
            "Klicke unten, um die WebApp zu öffnen:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(
            "⚡ *Super-Skill.md Generator*\n\n"
            "Öffne `/superskill/` direkt im Browser.",
            parse_mode="Markdown",
        )
