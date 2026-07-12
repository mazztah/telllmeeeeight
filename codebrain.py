# codebrain.py – Vollständiger Code-Zugriff für SuperAgent & normalen Chat
import os
import fnmatch
import logging
from datetime import datetime
from pathlib import Path
from io import BytesIO
from typing import Optional

from brain import save_text, save_file, load_all_entries
from vectorbrain import semantic_search, format_semantic_results

logger = logging.getLogger(__name__)

# ── Konfiguration ────────────────────────────────────────────────────────────
CODE_IGNORE_PATTERNS = {
    "__pycache__", ".git", "venv", ".env", ".venv", 
    "node_modules", ".pytest_cache", ".mypy_cache",
    "*.pyc", "*.pyo", "*.zip", "*.tar", "*.gz",
    "*.mp3", "*.mp4", "*.wav", "*.ogg", "*.jpg", "*.png", "*.gif",
    "*.glb", "*.obj", "*.svg", "*.ttf", "*.woff", "*.woff2",
}

CODE_EXTENSIONS = {".py", ".md", ".txt", ".json", ".yml", ".yaml", ".html", ".css", ".js", ".toml"}

CODE_BRAIN_TITLE_PREFIX = "Full Bot Code"
CODE_BRAIN_FILE_NAME = "full_bot_code.md"
MAX_CODE_DUMP_CHARS = 3_000_000


def _should_ignore_file(file_path: Path) -> bool:
    """Prüft ob eine Datei ignoriert werden soll."""
    path_str = str(file_path)
    filename = file_path.name
    parts = set(file_path.parts)
    for pattern in CODE_IGNORE_PATTERNS:
        if "*" in pattern:
            if fnmatch.fnmatch(filename, pattern):
                return True
        else:
            if pattern in parts or pattern in path_str:
                return True
    return False


def _collect_code_files(root: Path = Path(".")) -> list[Path]:
    """Sammelt alle relevanten Code-Dateien."""
    files = []
    for ext in CODE_EXTENSIONS:
        for file_path in root.rglob(f"*{ext}"):
            if _should_ignore_file(file_path):
                continue
            try:
                # Nur lesbare Dateien mit Inhalt
                if file_path.stat().st_size > 0 and file_path.stat().st_size < 5_000_000:  # max 5MB
                    files.append(file_path)
            except OSError:
                continue
    # Sortieren für deterministische Ausgabe
    files.sort()
    return files


async def save_full_code_to_brain(chat_id: str) -> str:
    """
    Speichert den gesamten Bot-Code (außer sensiblen Dateien) ins Brain.
    Erstellt sowohl einen Text-Eintrag als auch eine Datei.
    """
    logger.info("Starte Code-Dump für Chat %s...", chat_id)
    
    root = Path(__file__).resolve().parent
    code_files = _collect_code_files(root)
    
    if not code_files:
        return "❌ Keine Code-Dateien gefunden."
    
    full_code = f"""# === FULL BOT CODE DUMP ===
# Generiert: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Dateien: {len(code_files)}
# Projekt: telllmeeedrei
# ============================================

"""
    
    success_count = 0
    error_count = 0
    
    for file_path in code_files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            rel_path = file_path.relative_to(root) if file_path.is_absolute() else file_path
            block = f"\n\n# === FILE: {rel_path} ===\n\n{content}\n"
            if len(full_code) + len(block) > MAX_CODE_DUMP_CHARS:
                full_code += "\n\n# === TRUNCATED ===\n# Code-Dump gekürzt (MAX_CODE_DUMP_CHARS erreicht)\n"
                break
            full_code += block
            success_count += 1
        except Exception as e:
            logger.warning("Konnte Datei %s nicht lesen: %s", file_path, e)
            error_count += 1
    
    full_code += f"\n\n# === END OF CODE DUMP ===\n# Erfolgreich: {success_count} | Fehler: {error_count}\n"
    
    # 1. Als Text-Eintrag speichern (für semantische Suche)
    title = f"{CODE_BRAIN_TITLE_PREFIX} {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    text_result = await save_text(chat_id, full_code, title=title)
    
    # 2. Als Datei speichern (für Download / Convert)
    buffer = BytesIO(full_code.encode("utf-8"))
    file_result = await save_file(chat_id, buffer.getvalue(), CODE_BRAIN_FILE_NAME, "text/markdown")
    
    logger.info("Code-Dump abgeschlossen: %s Dateien erfolgreich, %s Fehler", success_count, error_count)
    
    return (
        f"✅ **Gesamter Code gespeichert** ins Brain.\n"
        f"📁 Dateien: {success_count} erfolgreich | {error_count} Fehler\n"
        f"🏷️ Titel: `{title}`\n\n"
        f"💡 **Jetzt kannst du fragen:**\n"
        f"• „Erkläre mir die SuperAgent-Logik“\n"
        f"• „Debugge den polling_loop in main.py“\n"
        f"• „Wie funktioniert das Brain?“\n"
        f"• „Zeig mir den Code für Voice-Distortion“"
    )


async def search_code_brain(chat_id: str, query: str, top_k: int = 5) -> str:
    """
    Semantische Suche speziell im Code-Brain.
    Sucht nach Einträgen mit 'Full Bot Code' im Titel.
    """
    if not query.strip():
        return "❌ Leere Suchanfrage."
    
    # Zuerst normale semantische Suche
    results = await semantic_search(chat_id, query, top_k=top_k * 2)
    
    # Filtere auf Code-Einträge
    code_results = [
        r for r in results 
        if CODE_BRAIN_TITLE_PREFIX.lower() in (r.get("title") or "").lower()
        or "full_bot_code" in (r.get("title") or "").lower()
    ]
    
    # Wenn keine Code-Einträge gefunden, gib normale Ergebnisse zurück
    if not code_results:
        if results:
            return (
                f"⚠️ Keine spezifischen Code-Einträge gefunden.\n"
                f"Hier sind allgemeine Brain-Treffer:\n\n"
                f"{format_semantic_results(results[:top_k])}"
            )
        return (
            f"❌ Keine Brain-Einträge gefunden.\n\n"
            f"Tippe zuerst `/savecode` um den aktuellen Code ins Brain zu laden."
        )
    
    return format_semantic_results(code_results[:top_k])


async def get_code_context_for_prompt(chat_id: str, query: Optional[str] = None, max_chars: int = 8000) -> str:
    """
    Lädt den gesamten Code-Dump oder relevante Snippets für den LLM-Prompt.
    Wird in build_prompt_history eingebunden.
    """
    try:
        entries = await load_all_entries(chat_id)
        
        # Suche nach dem neuesten Code-Dump
        code_entries = [
            e for e in entries 
            if CODE_BRAIN_TITLE_PREFIX.lower() in (e.get("title") or "").lower()
            or "full_bot_code" in (e.get("title") or "").lower()
        ]
        
        if not code_entries:
            return ""
        
        # Neuesten Eintrag nehmen
        code_entries.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        latest = code_entries[0]
        content = latest.get("content", "")
        
        if not content:
            return ""
        
        # Wenn Query vorhanden, versuche relevanten Teil zu extrahieren
        if query and len(content) > max_chars:
            # Einfache Keyword-Suche im Code
            query_lower = query.lower()
            lines = content.split("\n")
            
            # Finde relevante Zeilen
            relevant_indices = set()
            for i, line in enumerate(lines):
                if any(kw in line.lower() for kw in query_lower.split()):
                    # Kontext: 5 Zeilen vorher und 10 Zeilen nachher
                    for j in range(max(0, i - 5), min(len(lines), i + 10)):
                        relevant_indices.add(j)
            
            if relevant_indices:
                # Sortiere und füge Lücken-Marker hinzu
                sorted_indices = sorted(relevant_indices)
                snippet_lines = []
                last_idx = -2
                for idx in sorted_indices:
                    if idx > last_idx + 1:
                        snippet_lines.append("\n# ... [Code gekürzt] ...\n")
                    snippet_lines.append(lines[idx])
                    last_idx = idx
                
                snippet = "\n".join(snippet_lines)
                if len(snippet) > max_chars:
                    snippet = snippet[:max_chars - 50] + "\n# ... [weiter gekürzt] ..."
                
                return (
                    f"[AKTUELLER BOT-CODE – RELEVANTER AUSSCHNITT]\n"
                    f"Titel: {latest.get('title', 'Unknown')}\n"
                    f"Suchbegriff: {query}\n\n"
                    f"{snippet}\n\n"
                    f"[Ende Code-Ausschnitt]"
                )
        
        # Vollständiger Code (gekürzt auf max_chars)
        if len(content) > max_chars:
            content = content[:max_chars - 50] + "\n\n# ... [Rest des Codes gekürzt – nutze /savecode für vollständigen Dump] ..."
        
        return (
            f"[AKTUELLER BOT-CODE – VOLLSTÄNDIG (gekürzt)]\n"
            f"Titel: {latest.get('title', 'Unknown')}\n"
            f"ID: {latest.get('id', 'Unknown')}\n\n"
            f"{content}\n\n"
            f"[Ende Code]"
        )
        
    except Exception as e:
        logger.error("Fehler beim Laden des Code-Kontexts: %s", e)
        return ""


async def auto_save_code_on_startup(chat_id: str) -> None:
    """
    Optional: Speichert den Code automatisch beim Bot-Startup.
    Wird in main.py aufgerufen wenn OWNER_CHAT_ID gesetzt ist.
    """
    try:
        result = await save_full_code_to_brain(chat_id)
        logger.info("Auto-Save Code on Startup: %s", result[:100])
    except Exception as e:
        logger.error("Auto-Save Code fehlgeschlagen: %s", e)

