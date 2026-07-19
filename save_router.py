# save_router.py – Save-Intent-Handler fuer Text/Code/Fotos + Agent-Tool
#
# WICHTIG: Dokument-Uploads (PDF/Word/Excel/beliebige Datei) werden in
# diesem Repo bereits automatisch in handlers_media.py:handle_document()
# ueber brain.save_file() gespeichert - das ist unveraendert und bleibt
# so. Dieses Modul deckt die Luecken ab, die es bisher NICHT gab:
#
#   1. Text/Code, der direkt im Chat gepostet wird ("speichere das")
#      -> es gab keinen generischen Text-Save-Pfad ausserhalb von
#         /savecode (kompletter Code-Dump) und Datei-Upload.
#   2. Fotos ausserhalb von Edit-/Vision-Modus wurden bisher GAR NICHT
#      gespeichert (handle_photo() returned einfach, wenn kein
#      edit_mode/vision_mode aktiv war).
#   3. Ein Agent-Tool, damit SuperAgent/Agent auf natuerlichsprachliche
#      Save-Anfragen reagieren kann, ohne dass der User einen Command
#      tippen muss.

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from brain import save_file, save_text

logger = logging.getLogger(__name__)

# Bewusst spezifische Phrasen statt eines einzelnen "speicher"-Treffers,
# um False Positives zu vermeiden (z.B. "wo speichere ich meine Dateien"
# ist eine Frage, kein Save-Intent).
SAVE_INTENT_PATTERNS = [
    re.compile(r"\bspeicher[e]?\s+(das|dies|den\s+code|die\s+datei|das\s+oben)\b", re.IGNORECASE),
    re.compile(r"\bleg[e]?\s+das\s+(im\s+brain\s+)?ab\b", re.IGNORECASE),
    re.compile(r"\bmerk[e]?\s+dir\s+das\s*(dauerhaft)?\b", re.IGNORECASE),
    re.compile(r"\bins?\s+brain\s+(speichern|packen|laden)\b", re.IGNORECASE),
    re.compile(r"\bsave\s+(this|that|it)\s+(to\s+brain)?\b", re.IGNORECASE),
]


def looks_like_save_intent(text: str) -> bool:
    """Heuristik fuer normale Chatnachrichten - entscheidet, ob
    save_from_replied_text/Foto-Save ueberhaupt in Frage kommt."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in SAVE_INTENT_PATTERNS)


def _looks_like_code(text: str) -> bool:
    code_markers = ("def ", "class ", "import ", "```", "function ", "const ", "SELECT ", "<html", "#!/usr/bin")
    return any(marker in text for marker in code_markers)


def _guess_filename(text: str) -> str:
    if _looks_like_code(text):
        if "```python" in text or "def " in text or "import " in text:
            return "code_snippet.py"
        if "<html" in text.lower():
            return "snippet.html"
        return "code_snippet.txt"
    return "notiz.md"


async def save_text_intent(chat_id: str, text: str, *, filename: Optional[str] = None,
                            title: Optional[str] = None, trigger_wiki: bool = True) -> dict[str, Any]:
    """Zentraler Save-Pfad fuer Text/Code aus dem Chat (kein Datei-Upload)."""
    if not text or not text.strip():
        return {"success": False, "error": "Kein Text zum Speichern uebergeben."}

    resolved_filename = filename or _guess_filename(text)
    resolved_title = title or resolved_filename

    result_message = await save_text(chat_id, text, title=resolved_title)
    success = result_message.startswith("✅") or "ID:" in result_message

    if success and trigger_wiki:
        await _queue_wiki_writeback(chat_id, source_kind="text", source_ref=resolved_filename)

    return {
        "success": success,
        "filename": resolved_filename,
        "message": result_message,
    }


async def save_photo_intent(update, context) -> dict[str, Any]:
    """
    Speichert ein Foto ins Brain, wenn die Caption einen Save-Intent
    enthaelt. Wird aus handlers_media.py:handle_photo() aufgerufen,
    NACHDEM edit_mode_active/vision_mode_active bereits geprueft wurden
    (dort haben Fotos eine andere, bestehende Bedeutung).
    """
    chat_id = str(update.effective_chat.id)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    raw_bytes = bytes(await file.download_as_bytearray())
    caption = (update.message.caption or "").strip()
    filename = f"foto_{photo.file_id[:10]}.jpg"

    result_message = await save_file(chat_id, raw_bytes, filename, "image/jpeg")
    success = "✅" in result_message or "ID:" in result_message

    if success:
        await _queue_wiki_writeback(chat_id, source_kind="image", source_ref=caption or filename)

    return {"success": success, "filename": filename, "message": result_message}


async def save_from_replied_text(update, context) -> dict[str, Any]:
    """Fuer den Fall: User antwortet auf eine Nachricht/einen Code-Block
    mit 'speicher das' - haeufigster erwarteter Trigger-Fall."""
    chat_id = str(update.effective_chat.id)
    reply = update.message.reply_to_message
    if not reply or not (reply.text or reply.caption):
        return {"success": False, "error": "Keine Reply-Nachricht mit Text gefunden."}

    content = reply.text or reply.caption or ""
    return await save_text_intent(chat_id, content)


async def _queue_wiki_writeback(chat_id: str, *, source_kind: str, source_ref: str) -> None:
    """Nicht-blockierender Writeback-Trigger ins kompilierte Wiki
    (Karpathy/OKF-Pattern) - siehe wiki_compiler.py."""
    try:
        from wiki_compiler import queue_wiki_writeback
        await queue_wiki_writeback(chat_id, source_kind=source_kind, source_ref=source_ref)
    except Exception as exc:
        logger.debug("Wiki-Writeback uebersprungen (%s/%s): %s", chat_id, source_ref, exc)


# ── Agent-Tool-Definition ────────────────────────────────────────────────
def build_save_tool(chat_id: str):
    """Wird in bot_utils.py:build_agent_tools() eingehaengt, damit
    SuperAgent/Agent auf natuerlichsprachliche Save-Anfragen reagieren
    kann ('speichere folgenden Code als webscraper.py: ...')."""
    from agent import AgentTool

    async def _handler(arguments: dict[str, Any]) -> str:
        content = arguments.get("content", "")
        filename = arguments.get("filename")
        title = arguments.get("title")
        result = await save_text_intent(chat_id, content, filename=filename, title=title)
        if result["success"]:
            return f"Gespeichert als '{result['filename']}'."
        return f"Speichern fehlgeschlagen: {result.get('error') or result.get('message')}"

    return AgentTool(
        name="save_to_brain",
        description=(
            "Speichert Text, Code oder Notizen dauerhaft im Brain. Nutze "
            "dies wenn der User explizit sagt 'speichere das', 'leg das ab', "
            "'merk dir das dauerhaft'. Fuer Datei-Uploads (PDF/Bild/Word/Excel) "
            "passiert das Speichern automatisch beim Upload, dieses Tool ist "
            "nur fuer Chat-Text/Code noetig."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Der zu speichernde Text/Code."},
                "filename": {
                    "type": "string",
                    "description": "Optionaler Dateiname inkl. Endung, z.B. 'webscraper.py'. "
                                    "Wird sonst automatisch aus dem Inhalt geraten.",
                },
                "title": {"type": "string", "description": "Optionaler Titel fuer den Brain-Eintrag."},
            },
            "required": ["content"],
        },
        handler=_handler,
    )
