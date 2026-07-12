# papersearch_handler.py – Telegram Handler für Scientific Paper Search + AI Workspace
# Modul für den Telegrambot: Suche, Workspace, AI-Chat, Lesetipps

import asyncio
import json
import logging
import os
from urllib.parse import quote

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ── Konfiguration ──────────────────────────────────────────────────────────────
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_PAPER = "https://api.semanticscholar.org/graph/v1/paper/"
SEMANTIC_SCHOLAR_KEY = os.getenv("SEMANTIC_SCHOLAR_KEY", "")  # optional, erhöht Rate-Limit

BASE_URL = os.getenv(
    "PAPERSEARCH_BASE_URL",
    os.getenv("PUBLIC_APP_BASE_URL", "https://telllmeeesevn.onrender.com"),
).rstrip("/")

PAPERSEARCH_WEBAPP_URL = f"{BASE_URL}/papersearch"

# In-Memory Workspace pro Chat (persistenz optional über brain.py)
_workspace: dict[str, list[dict]] = {}  # chat_id -> list of paper dicts


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _get_workspace(chat_id: str) -> list[dict]:
    return _workspace.setdefault(chat_id, [])


def _add_to_workspace(chat_id: str, paper: dict) -> bool:
    ws = _get_workspace(chat_id)
    if any(p.get("paperId") == paper.get("paperId") for p in ws):
        return False  # Already exists
    ws.append(paper)
    return True


def _remove_from_workspace(chat_id: str, paper_id: str) -> bool:
    ws = _get_workspace(chat_id)
    before = len(ws)
    _workspace[chat_id] = [p for p in ws if p.get("paperId") != paper_id]
    return len(_workspace[chat_id]) < before


def _format_paper_for_telegram(paper: dict, idx: int = None) -> str:
    title = paper.get("title", "Kein Titel")
    year = paper.get("year", "?")
    authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:3])
    if len(paper.get("authors", [])) > 3:
        authors += " et al."
    abstract = paper.get("abstract", "")
    if abstract and len(abstract) > 200:
        abstract = abstract[:200] + "…"
    url = paper.get("url", "")
    cit = paper.get("citationCount", 0)

    prefix = f"{idx}. " if idx is not None else ""
    lines = [
        f"{prefix}📄 <b>{title}</b>",
        f"👤 {authors} | 📅 {year} | 🔗 {cit} Zitate",
    ]
    if abstract:
        lines.append(f"📝 {abstract}")
    if url:
        lines.append(f'🌐 <a href="{url}">Paper öffnen</a>')
    return "\n".join(lines)


async def _fetch_papers(query: str, limit: int = 5, sort: str = "relevance") -> list[dict]:
    """Holt Paper von Semantic Scholar."""
    params = {
        "query": query,
        "limit": limit,
        "fields": "paperId,title,year,abstract,authors,url,citationCount,externalIds",
    }
    if sort == "citations":
        params["sort"] = "citationCount"
    elif sort == "date":
        params["sort"] = "publicationDate"

    headers = {}
    if SEMANTIC_SCHOLAR_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(SEMANTIC_SCHOLAR_API, params=params, headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("data", [])


# ── /papersearch <query> ───────────────────────────────────────────────────────

async def cmd_papersearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/papersearch <query> – Sucht wissenschaftliche Paper und öffnet den Workspace."""
    chat_id = str(update.effective_chat.id)
    query = " ".join(context.args or []).strip()

    if not query:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🔬 Paper Workspace öffnen",
                web_app=WebAppInfo(url=PAPERSEARCH_WEBAPP_URL)
            )
        ]])
        await update.message.reply_text(
            "🔬 <b>Paper Search & Workspace</b>\n\n"
            "Nutzung: <code>/papersearch &lt;Suchbegriff&gt;</code>\n\n"
            "Oder öffne den interaktiven Workspace mit dem Button unten.\n"
            "Dort kannst du suchen, Paper zum Workspace hinzufügen und "
            "mit der KI darüber chatten.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return

    loading = await update.message.reply_text("🔍 Suche läuft…")

    papers = await _fetch_papers(query, limit=5)
    if not papers:
        await loading.edit_text("❌ Keine Ergebnisse gefunden.")
        return

    # Zeige Ergebnisse mit Buttons
    text_parts = [f"🔬 <b>Suchergebnisse für:</b> <i>{query}</i>\n"]
    keyboard_rows = []

    for i, p in enumerate(papers, 1):
        text_parts.append(_format_paper_for_telegram(p, i))
        text_parts.append("")
        pid = p.get("paperId", "")
        if pid:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"➕ #{i} zum Workspace", callback_data=f"ps:add:{pid}"
                ),
            ])

    keyboard_rows.append([
        InlineKeyboardButton(
            "🖥️ Workspace öffnen",
            web_app=WebAppInfo(url=f"{PAPERSEARCH_WEBAPP_URL}?q={quote(query)}")
        )
    ])
    keyboard_rows.append([
        InlineKeyboardButton("💬 KI fragen", callback_data=f"ps:ask:{query[:60]}")
    ])

    full_text = "\n".join(text_parts)[:4000]
    await loading.edit_text(
        full_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
        disable_web_page_preview=True,
    )

    # Speichere Suchergebnisse temporär für den Workspace
    context.chat_data["ps_last_results"] = papers
    context.chat_data["ps_last_query"] = query


# ── /psworkspace – Zeigt aktuellen Workspace ──────────────────────────────────

async def cmd_psworkspace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/psworkspace – Zeigt den aktuellen Paper-Workspace."""
    chat_id = str(update.effective_chat.id)
    ws = _get_workspace(chat_id)

    if not ws:
        await update.message.reply_text(
            "📂 Dein Workspace ist leer.\n"
            "Nutze /papersearch und füge Paper per Button hinzu.",
            parse_mode="HTML",
        )
        return

    text_parts = [f"📂 <b>Dein Paper Workspace</b> ({len(ws)} Paper)\n"]
    keyboard_rows = []

    for i, p in enumerate(ws, 1):
        text_parts.append(_format_paper_for_telegram(p, i))
        text_parts.append("")
        pid = p.get("paperId", "")
        if pid:
            keyboard_rows.append([
                InlineKeyboardButton(f"🗑️ #{i} entfernen", callback_data=f"ps:rm:{pid}")
            ])

    keyboard_rows.append([
        InlineKeyboardButton(
            "🖥️ Workspace öffnen",
            web_app=WebAppInfo(url=PAPERSEARCH_WEBAPP_URL)
        )
    ])
    keyboard_rows.append([
        InlineKeyboardButton("🤖 KI über Workspace befragen", callback_data="ps:chat:workspace")
    ])
    keyboard_rows.append([
        InlineKeyboardButton("📤 Zusammenfassung senden", callback_data="ps:summary:all")
    ])

    await update.message.reply_text(
        "\n".join(text_parts)[:4000],
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
        disable_web_page_preview=True,
    )


# ── /pschat <frage> – KI chattet über Workspace-Inhalt ───────────────────────

async def cmd_pschat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pschat <frage> – Fragt die KI über den Workspace-Inhalt."""
    chat_id = str(update.effective_chat.id)
    question = " ".join(context.args or []).strip()

    if not question:
        await update.message.reply_text(
            "Nutzung: <code>/pschat &lt;Deine Frage über die Paper&gt;</code>",
            parse_mode="HTML",
        )
        return

    ws = _get_workspace(chat_id)
    if not ws:
        await update.message.reply_text(
            "📂 Workspace ist leer! Füge zuerst Paper hinzu mit /papersearch.",
        )
        return

    loading = await update.message.reply_text("🤖 KI analysiert deinen Workspace…")
    result = await _ai_workspace_chat(chat_id, question, ws)
    await loading.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)


# ── Callback Handler ──────────────────────────────────────────────────────────

async def papersearch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verarbeitet alle ps:* Callbacks."""
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    data = query.data or ""

    # ── Zum Workspace hinzufügen ─────────────────────────────────────────────
    if data.startswith("ps:add:"):
        paper_id = data[len("ps:add:"):]
        # Suche paper in letzten Ergebnissen
        last = context.chat_data.get("ps_last_results", [])
        paper = next((p for p in last if p.get("paperId") == paper_id), None)

        if not paper:
            # Lade Paper direkt von API
            paper = await _fetch_paper_details(paper_id)

        if paper and _add_to_workspace(chat_id, paper):
            ws_count = len(_get_workspace(chat_id))
            await query.answer(f"✅ Paper zum Workspace hinzugefügt! ({ws_count} gesamt)", show_alert=False)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Paper hinzugefügt: <b>{paper.get('title', 'Unbekannt')}</b>\n"
                     f"Workspace enthält jetzt {ws_count} Paper. "
                     f"Nutze /psworkspace zum Anzeigen.",
                parse_mode="HTML",
            )
        else:
            await query.answer("ℹ️ Paper bereits im Workspace.", show_alert=False)

    # ── Aus Workspace entfernen ──────────────────────────────────────────────
    elif data.startswith("ps:rm:"):
        paper_id = data[len("ps:rm:"):]
        removed = _remove_from_workspace(chat_id, paper_id)
        if removed:
            await query.answer("🗑️ Entfernt!", show_alert=False)
            # Workspace neu anzeigen
            await cmd_psworkspace(update, context)
        else:
            await query.answer("Nicht gefunden.", show_alert=True)

    # ── KI fragen nach letzter Suche ─────────────────────────────────────────
    elif data.startswith("ps:ask:"):
        search_query = data[len("ps:ask:"):]
        last = context.chat_data.get("ps_last_results", [])
        if not last:
            await query.answer("Keine Suchergebnisse vorhanden.", show_alert=True)
            return
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="🤖 KI analysiert…")
        result = await _ai_workspace_chat(
            chat_id,
            f"Was sind die wichtigsten Erkenntnisse zu: {search_query}? "
            "Gib Lesetipps und weiterführende Suchvorschläge.",
            last
        )
        await loading_msg.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)

    # ── KI über gesamten Workspace ───────────────────────────────────────────
    elif data == "ps:chat:workspace":
        ws = _get_workspace(chat_id)
        if not ws:
            await query.answer("Workspace leer!", show_alert=True)
            return
        await context.bot.send_message(
            chat_id=chat_id,
            text="💬 Was möchtest du über deinen Workspace wissen?\n"
                 "Nutze <code>/pschat &lt;deine Frage&gt;</code>",
            parse_mode="HTML",
        )

    # ── Zusammenfassung senden ───────────────────────────────────────────────
    elif data == "ps:summary:all":
        ws = _get_workspace(chat_id)
        if not ws:
            await query.answer("Workspace leer!", show_alert=True)
            return
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="📝 Erstelle Zusammenfassung…")
        result = await _ai_workspace_chat(
            chat_id,
            "Erstelle eine strukturierte Zusammenfassung aller Paper im Workspace. "
            "Hebe die wichtigsten Erkenntnisse hervor, zeige Verbindungen auf, "
            "und gib 3 weiterführende Suchvorschläge.",
            ws
        )
        await loading_msg.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)


# ── KI-Chat Hilfsfunktion ─────────────────────────────────────────────────────

async def _ai_workspace_chat(chat_id: str, question: str, papers: list[dict]) -> str:
    """Generiert eine KI-Antwort über den Workspace-Inhalt via Groq."""
    try:
        from bot_state import client as groq_client

        # Baue Kontext aus den Paper-Daten
        paper_contexts = []
        for i, p in enumerate(papers[:8], 1):
            title = p.get("title", "?")
            year = p.get("year", "?")
            authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
            abstract = p.get("abstract", "")[:500] if p.get("abstract") else "Kein Abstract"
            citations = p.get("citationCount", 0)
            paper_contexts.append(
                f"[Paper {i}]\nTitel: {title}\nJahr: {year}\nAutoren: {authors}\n"
                f"Zitate: {citations}\nAbstract: {abstract}"
            )

        context_str = "\n\n".join(paper_contexts)

        system_prompt = (
            "Du bist ein wissenschaftlicher Assistent, der bei der Analyse von Forschungspapieren hilft. "
            "Du antwortest präzise, strukturiert und auf Deutsch. "
            "Du gibst immer konkrete Lesetipps und weiterführende Suchbegriffe wenn relevant. "
            "Nutze HTML-Formatierung für Telegram: <b>fett</b>, <i>kursiv</i>, <code>code</code>. "
            "Keine Markdown-Syntax. Halte Antworten unter 3000 Zeichen."
        )

        user_message = (
            f"Workspace-Inhalt ({len(papers)} Paper):\n\n{context_str}\n\n"
            f"Frage: {question}"
        )

        response = await asyncio.to_thread(
            lambda: groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.7,
            )
        )

        answer = response.choices[0].message.content or "Keine Antwort erhalten."

        # Füge immer einen Footer mit Suchvorschlägen hinzu falls nicht vorhanden
        if "suchvorschlag" not in answer.lower() and "suchen" not in answer.lower():
            answer += "\n\n💡 <i>Tipp: Nutze /papersearch für weitere Suchen.</i>"

        return answer[:4000]

    except Exception as e:
        logger.exception("Fehler in _ai_workspace_chat")
        return f"❌ KI-Fehler: {str(e)[:200]}"


async def _fetch_paper_details(paper_id: str) -> dict | None:
    """Holt Paper-Details von Semantic Scholar."""
    try:
        params = {"fields": "paperId,title,year,abstract,authors,url,citationCount"}
        headers = {}
        if SEMANTIC_SCHOLAR_KEY:
            headers["x-api-key"] = SEMANTIC_SCHOLAR_KEY
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SEMANTIC_SCHOLAR_PAPER}{paper_id}",
                params=params,
                headers=headers,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        logger.exception("Fehler beim Laden von Paper-Details")
    return None
