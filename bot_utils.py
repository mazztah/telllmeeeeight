import asyncio
import base64
import json
import logging
import mimetypes
import os
import tempfile
from io import BytesIO
from typing import Tuple

from telegram import Update
from telegram.ext import ContextTypes

from bot_state import application
from brain import list_entries, load_entry, save_file
from codeinterpreter import run_code
from dv import extract_content
from guard import allow_email_batch
from parser import normalize_target, universal_convert, universal_convert_text
from search import format_search_results_for_prompt, web_search
from vectorbrain import format_semantic_results, semantic_search
from agent import AgentTool, run_agent_loop
from emgen import parse_email_list

logger = logging.getLogger(__name__)

# ── Background Task Helper ────────────────────────────────────────────────────
_background_tasks: set = set()


def create_background_task(coro):
    """asyncio-Task mit stabiler Referenz, damit GC ihn nicht abbricht."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def create_download_buffer(code: str, language: str, stem: str = 'generated') -> Tuple[BytesIO, str]:
    """Erstellt downloadbare Datei aus Code."""
    ext = {'python': 'py', 'html': 'html', 'javascript': 'js', 'css': 'css', 'json': 'json'}.get(language.lower(), 'txt')
    filename = f'{stem}.{ext}'
    buffer = BytesIO(code.encode('utf-8'))
    return buffer, filename


# ── Text & Format Helpers ─────────────────────────────────────────────────────
def fit_telegram_text(text: str, limit: int = 3900) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 20].rstrip() + "\n\n...[gekuerzt]"


def guess_mime_type(filename: str, default: str = "application/octet-stream") -> str:
    mime_type, _ = mimetypes.guess_type(filename or "")
    return mime_type or default


def sanitize_stem(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or "converted"))[0]
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return cleaned.strip("_") or "converted"


def ensure_buffer(data) -> BytesIO:
    if isinstance(data, BytesIO):
        data.seek(0)
        return data
    if isinstance(data, bytes):
        buffer = BytesIO(data)
        buffer.seek(0)
        return buffer
    raise TypeError("Output ist weder BytesIO noch bytes")


def parse_pipe_payload(raw_text: str) -> tuple[str, str] | tuple[None, None]:
    if "||" not in (raw_text or ""):
        return None, None
    left, right = raw_text.split("||", 1)
    return left.strip() or None, right.strip() or None


def parse_workflow_request(args: list[str]) -> tuple[str, bool, bool]:
    allow_image = False
    allow_video = False
    cleaned = []
    for arg in args:
        if arg.lower() == "--image":
            allow_image = True
        elif arg.lower() == "--video":
            allow_video = True
        else:
            cleaned.append(arg)
    return " ".join(cleaned).strip(), allow_image, allow_video


def parse_speak_command(args: list[str]) -> tuple[str | None, str | None]:
    raw = " ".join(args).strip()
    if not raw:
        return None, None
    if "|" in raw:
        voice_name, text = raw.split("|", 1)
        return voice_name.strip(), text.strip()
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        return None, None
    return parts[0].strip(), parts[1].strip()


def get_command_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    payload = " ".join(context.args).strip()
    if payload:
        return payload
    reply = update.message.reply_to_message if update.message else None
    if reply and reply.text:
        return reply.text.strip()
    if reply and reply.caption:
        return reply.caption.strip()
    return ""


def is_audio_document(document) -> bool:
    if not document:
        return False
    mime_type = (document.mime_type or "").lower()
    filename = (document.file_name or "").lower()
    return mime_type.startswith("audio/") or filename.endswith(
        (".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac", ".opus")
    )


async def download_telegram_file_to_temp(bot_file, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        await bot_file.download_to_drive(temp.name)
        return temp.name


def _new_temp_path(suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        return temp.name


def detect_convert_target_from_text(text: str) -> str | None:
    lowered = (text or "").lower()
    target_map = {
        "excel": ["zu excel", "to excel", "excel machen", "xlsx", "spreadsheet"],
        "csv": ["zu csv", "to csv", "csv machen"],
        "pdf": ["zu pdf", "to pdf", "pdf machen"],
        "docx": ["zu docx", "to word", "word machen", "zu word"],
        "mp3": ["zu mp3", "to mp3", "vorlesen", "sprachnachricht", "tts"],
        "chart": ["chart", "grafik", "diagramm"],
        "html": ["zu html", "to html"],
        "markdown": ["zu markdown", "to markdown", "zu md"],
        "text": ["zu txt", "to txt", "zu text", "plain text"],
        "json": ["zu json", "to json"],
        "py": ["zu py", "to py", "zu python", "python datei"],
    }
    for target, phrases in target_map.items():
        if any(phrase in lowered for phrase in phrases):
            return target
    return None


# ── Conversion Pipeline ───────────────────────────────────────────────────────
async def run_conversion_code_fallback(chat_id: str, target: str, source_text: str, source_name: str) -> dict:
    from gtts import gTTS
    import pandas as pd
    from dv import create_chart_from_df, create_docx_from_text, create_excel_from_data, create_pdf_from_text

    payload_b64 = base64.b64encode((source_text or "").encode("utf-8")).decode("ascii")
    safe_stem = sanitize_stem(source_name)
    normalized_target = normalize_target(target)

    code = f'''
source_text = base64.b64decode({payload_b64!r}).decode("utf-8")
target = {normalized_target!r}
stem = {safe_stem!r}
lines = [line for line in source_text.splitlines() if line.strip()]

if target == "pdf":
    buffer = create_pdf_from_text(source_text, title=f"{{stem}}.pdf")
    result_file = (buffer, f"{{stem}}.pdf")
elif target == "docx":
    buffer = create_docx_from_text(source_text, title=stem)
    result_file = (buffer, f"{{stem}}.docx")
elif target == "excel":
    rows = []
    for line in lines or [""]:
        if "\\t" in line: row = [c.strip() for c in line.split("\\t")]
        elif ";" in line:  row = [c.strip() for c in line.split(";")]
        elif "," in line:  row = [c.strip() for c in line.split(",")]
        else:              row = [line]
        rows.append(row)
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]
    cols = [f"col_{{i+1}}" for i in range(max_cols)]
    result_file = (create_excel_from_data(rows, cols, title=f"{{stem}}.xlsx"), f"{{stem}}.xlsx")
elif target == "csv":
    result_file = (BytesIO("\\n".join(lines or [source_text]).encode()), f"{{stem}}.csv")
elif target == "json":
    try: pj = json.loads(source_text)
    except Exception: pj = {{"content": source_text}}
    result_file = (BytesIO(json.dumps(pj, indent=2, ensure_ascii=False).encode()), f"{{stem}}.json")
elif target == "html":
    esc = source_text.replace("&","&amp;").replace("<","<").replace(">",">")
    result_file = (BytesIO(f"<!DOCTYPE html><html><body><pre>{{esc}}</pre></body></html>".encode()), f"{{stem}}.html")
elif target == "markdown":
    md = source_text if source_text.startswith("#") else f"# {{stem}}\\n\\n{{source_text}}"
    result_file = (BytesIO(md.encode()), f"{{stem}}.md")
elif target == "text":
    result_file = (BytesIO(source_text.encode()), f"{{stem}}.txt")
elif target == "py":
    result_file = (BytesIO(source_text.encode()), f"{{stem}}.py")
elif target == "mp3":
    tts = gTTS(text=(source_text[:4000] or "Leer"), lang="de", slow=False)
    buf = BytesIO(); tts.write_to_fp(buf); buf.seek(0)
    result_file = (buf, f"{{stem}}.mp3")
else:
    raise ValueError(f"Fallback unterstützt {{target}} nicht.")
result = f"Fallback-Konvertierung zu {{target}} erfolgreich."
'''
    res = await run_code(code, "python", chat_id=chat_id, save_to_brain=False)
    if res.get("success") and res.get("file"):
        buf, fname = res["file"]
        return {
            "success": True,
            "target": normalized_target,
            "output": ensure_buffer(buf),
            "filename": fname,
            "mime_type": guess_mime_type(fname),
            "message": f"Fallback für {target} OK",
        }
    return {
        "success": False,
        "target": normalized_target,
        "output": None,
        "filename": "",
        "mime_type": "application/octet-stream",
        "message": res.get("error") or f"Fallback für {target} fehlgeschlagen.",
    }


async def run_text_conversion_pipeline(chat_id, text, target, source_name, instruction=None):
    result = await universal_convert_text(text=text, target=target, source_name=source_name, instruction=instruction, chat_id=chat_id)
    if result.get("success"):
        return result
    return await run_conversion_code_fallback(chat_id, target, text, source_name)


async def run_file_conversion_pipeline(chat_id, file_path, target, source_name, instruction=None):
    result = await universal_convert(file_path=file_path, target=target, instruction=instruction, chat_id=chat_id)
    if result.get("success"):
        return result
    extracted_text = extract_content(file_path, max_chars=20000)
    return await run_conversion_code_fallback(chat_id, target, extracted_text, source_name)


async def send_conversion_result(chat_id: str, context: ContextTypes.DEFAULT_TYPE, conv_result: dict) -> str:
    output_buffer = ensure_buffer(conv_result["output"])
    filename = conv_result.get("filename") or "converted.bin"
    mime_type = conv_result.get("mime_type") or guess_mime_type(filename)
    message = conv_result.get("message", "Konvertierung fertig!")

    if mime_type.startswith("audio/") or filename.lower().endswith(".mp3"):
        await context.bot.send_audio(chat_id=chat_id, audio=output_buffer, filename=filename, caption=f"✅ {message}")
    else:
        await context.bot.send_document(chat_id=chat_id, document=output_buffer, filename=filename, caption=f"✅ {message}")

    return await save_file(chat_id, output_buffer.getvalue(), filename, mime_type)


async def prepare_email_batch_preview(file_path: str, chat_id: str, subject: str, body: str) -> dict:
    from emgen import prepare_email_batch
    recipients = parse_email_list(file_path)
    decision = allow_email_batch(chat_id, len(recipients), subject, body)
    if not decision.allowed:
        return {"success": False, "message": decision.message}
    return await prepare_email_batch(chat_id, file_path, subject, body)


# ── Agent Tools ───────────────────────────────────────────────────────────────
def build_agent_tools(chat_id: str) -> list[AgentTool]:
    async def tool_web_search(arguments: dict) -> str:
        query = (arguments.get("query") or "").strip()
        if not query:
            return "Leere Suchanfrage."
        result = await asyncio.to_thread(web_search, query, 6, "de", "de", None)
        return format_search_results_for_prompt(result)

    async def tool_semantic_brain(arguments: dict) -> str:
        query = (arguments.get("query") or "").strip()
        if not query:
            return "Leere Brain-Suche."
        results = await semantic_search(chat_id, query, top_k=4)
        return format_semantic_results(results)

    async def tool_list_brain(arguments: dict) -> str:
        limit = int(arguments.get("limit") or 6)
        return await list_entries(chat_id, limit=max(1, min(limit, 15)))

    async def tool_load_brain(arguments: dict) -> str:
        entry_id = str(arguments.get("entry_id") or "").strip()
        if not entry_id:
            return "entry_id fehlt."
        entry = await load_entry(chat_id, entry_id)
        if not entry:
            return "Eintrag nicht gefunden."
        import json as _json
        metadata = entry.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = _json.loads(metadata)
            except Exception:
                metadata = {}
        content = entry.get("content") or ""
        preview = metadata.get("extracted_preview") or content[:1200]
        return f'{entry.get("title")}\n\n{preview[:2000]}'

    async def tool_search_code_brain(arguments: dict) -> str:
        """Sucht im Code-Brain nach relevanten Code-Snippets."""
        query = (arguments.get("query") or "").strip()
        if not query:
            return "Leere Code-Suche."
        from codebrain import search_code_brain
        result_text = await search_code_brain(chat_id, query, top_k=5)
        if "Keine Brain-Einträge gefunden" in result_text or "Keine Code-Einträge" in result_text:
            return "Keine Code-Einträge im Brain gefunden. Tippe /savecode um den aktuellen Code zu speichern."
        return result_text

    async def tool_save_code_brain(arguments: dict) -> str:
        """Speichert den gesamten aktuellen Bot-Code ins Brain."""
        from codebrain import save_full_code_to_brain
        result = await save_full_code_to_brain(chat_id)
        return result

    return [
        AgentTool(
            name="web_search",
            description="Sucht aktuelle Web-Informationen.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=tool_web_search,
        ),
        AgentTool(
            name="semantic_brain_search",
            description="Findet semantisch passende Inhalte im Brain.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=tool_semantic_brain,
        ),
        AgentTool(
            name="list_brain_entries",
            description="Listet Brain-Einträge auf.",
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}},
            handler=tool_list_brain,
        ),
        AgentTool(
            name="load_brain_entry",
            description="Lädt einen Brain-Eintrag per ID.",
            parameters={"type": "object", "properties": {"entry_id": {"type": "string"}}, "required": ["entry_id"]},
            handler=tool_load_brain,
        ),
        # New 3D Tools for Superagent
        AgentTool(
            name="convert_3d",
            description="Konvertiert 3D-Dateien (GLB to PNG/OBJ/SVG). Gib file_path und target.",
            parameters={"type": "object", "properties": {"file_path": {"type": "string"}, "target": {"type": "string", "enum": ["png", "obj", "svg", "glb"]}}, "required": ["file_path", "target"]},
            handler=lambda args: "3D Convert ready - upload GLB first then call.",
        ),
        AgentTool(
            name="text_to_3d",
            description="Erstellt 3D-Modelle aus Text (/text3d 'red car'). Gib prompt.",
            parameters={"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]},
            handler=lambda args: "Text3D via Tripo/Meshy ready.",
        ),
        AgentTool(
            name="launch_dashboard",
            description="Öffnet Bot-Dashboard mit Parametern/Model/Prompts.",
            parameters={"type": "object"},
            handler=lambda args: "Dashboard: streamlit run dashboard.py --server.port 8501",
        ),
        AgentTool(
            name="search_code_brain",
            description="Sucht im gespeicherten Code-Brain nach Implementierungsdetails, Funktionen oder Bugs. Verwende dies wenn der User nach Code fragt.",
            parameters={"type": "object", "properties": {"query": {"type": "string", "description": "Suchbegriff wie 'polling_loop' oder 'voice_handler'"}}, "required": ["query"]},
            handler=tool_search_code_brain,
        ),
        AgentTool(
            name="save_code_brain",
            description="Speichert den gesamten aktuellen Bot-Code ins Brain. Verwende dies wenn der User den Code aktualisieren möchte.",
            parameters={"type": "object"},
            handler=tool_save_code_brain,
        ),
    ]
