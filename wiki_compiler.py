# wiki_compiler.py – Kompilierte Wissensschicht zwischen Redis und Supabase
#
# Pattern: Andrej Karpathy's "LLM Wiki" (compile, don't retrieve) +
# Google OKF (Open Knowledge Format: Markdown + YAML-Frontmatter, ein
# Concept = eine Datei, Concept-ID = Pfad, Links zwischen Concepts).
#
# Zweck: Der Agent soll NICHT bei jeder Anfrage Supabase (Brain) lesen.
# Stattdessen pflegt der Bot pro Chat ein kleines, kompiliertes Wiki
# (ein paar Markdown-Seiten mit Konsens-Wissen statt Rohdaten). Dieses
# Wiki ist klein genug, um komplett in den Prompt geladen zu werden
# ("Wiki before RAG" - siehe Karpathys Regel: unter ~80k Tokens direkt
# lesen, erst darueber lohnt sich echte Vektorsuche).
#
# Speicherstrategie:
#   - Hot-Cache: Redis (schneller Zugriff, ueberlebt normale Requests)
#   - Ground-Truth: Supabase Storage / brain_entries mit
#     entry_type='wiki_page' (ueberlebt Redis-Flush)
#   - Kompilierung: nur getriggert (nicht bei jeder Chatnachricht),
#     per queue_wiki_writeback() als Background-Task

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from redis_state import get_json, set_json, get_raw, set_raw

logger = logging.getLogger(__name__)

WIKI_REDIS_PREFIX = "wiki"
WIKI_INDEX_SUFFIX = "index"
DEFAULT_TOKEN_BUDGET = 20_000
CHARS_PER_TOKEN_ESTIMATE = 4  # grobe Heuristik, reicht fuer ein Budget-Gate


@dataclass
class WikiPage:
    concept_id: str          # z.B. "projects/telllmeeedrei" - Pfad ohne .md
    title: str
    body: str                # Markdown-Body (ohne Frontmatter)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)  # andere concept_ids
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_markdown(self) -> str:
        frontmatter = {
            "concept_id": self.concept_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "links": self.links,
        }
        fm_lines = ["---"]
        for key, value in frontmatter.items():
            if isinstance(value, list):
                fm_lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
            else:
                fm_lines.append(f'{key}: "{value}"')
        fm_lines.append("---")
        return "\n".join(fm_lines) + "\n\n" + self.body.strip() + "\n"

    @classmethod
    def from_markdown(cls, raw: str) -> "WikiPage":
        if not raw.startswith("---"):
            # Kein Frontmatter -> minimal-invasive Rueckwaertskompatibilitaet
            return cls(concept_id="unknown", title="Untitled", body=raw)
        parts = raw.split("---", 2)
        if len(parts) < 3:
            return cls(concept_id="unknown", title="Untitled", body=raw)
        _, fm_block, body = parts
        meta: dict[str, Any] = {}
        for line in fm_block.strip().splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"')
            if value.startswith("[") and value.endswith("]"):
                try:
                    meta[key] = json.loads(value)
                    continue
                except Exception:
                    pass
            meta[key] = value
        return cls(
            concept_id=meta.get("concept_id", "unknown"),
            title=meta.get("title", "Untitled"),
            body=body.strip(),
            tags=meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
            links=meta.get("links", []) if isinstance(meta.get("links"), list) else [],
            updated_at=meta.get("updated_at", ""),
        )


# ── Redis-Layer: Index + einzelne Seiten ─────────────────────────────────
def _index_key(chat_id: str) -> str:
    return f"{WIKI_REDIS_PREFIX}:{chat_id}:{WIKI_INDEX_SUFFIX}"


def _page_key(chat_id: str, concept_id: str) -> str:
    safe_id = concept_id.replace("/", "__")
    return f"{WIKI_REDIS_PREFIX}:{chat_id}:page:{safe_id}"


async def list_concept_ids(chat_id: str) -> list[str]:
    return await get_json(_index_key(chat_id), [])


async def _register_concept(chat_id: str, concept_id: str) -> None:
    ids = await list_concept_ids(chat_id)
    if concept_id not in ids:
        ids.append(concept_id)
        await set_json(_index_key(chat_id), ids)


async def load_wiki_page(chat_id: str, concept_id: str) -> Optional[WikiPage]:
    raw = await get_raw(_page_key(chat_id, concept_id))
    if not raw:
        return None
    return WikiPage.from_markdown(raw)


async def save_wiki_page(chat_id: str, page: WikiPage) -> None:
    await set_raw(_page_key(chat_id, page.concept_id), page.to_markdown())
    await _register_concept(chat_id, page.concept_id)
    # Ground-Truth-Spiegelung nach Supabase passiert bewusst NICHT hier
    # synchron, sondern in compile_wiki_page() nach der LLM-Kompilierung -
    # so bleibt save_wiki_page() billig und blockiert keine Hot-Paths.


async def load_all_wiki_pages(chat_id: str) -> list[WikiPage]:
    concept_ids = await list_concept_ids(chat_id)
    pages = []
    for cid in concept_ids:
        page = await load_wiki_page(chat_id, cid)
        if page:
            pages.append(page)
    return pages


# ── Prompt-Loading: "Wiki before RAG" ────────────────────────────────────
async def load_wiki_for_prompt(chat_id: str, token_budget: int = DEFAULT_TOKEN_BUDGET) -> str:
    """
    Kernfunktion fuer build_prompt_history() in bot_ai.py.

    Laedt das komplette Wiki, WENN es unter dem Tokenbudget bleibt
    (Karpathys Direct-Read-Regel). Liegt es darueber, wird nur eine
    gekuerzte Uebersicht (Titel + erste Zeilen jeder Seite) zurueckgegeben
    und der Agent muss fuer Details explizit ein Brain-Such-Tool nutzen.

    Das ist absichtlich KEIN Vektor-Retrieval - solange das Wiki klein
    ist (kompiliert statt roh), lohnt sich das nicht.
    """
    pages = await load_all_wiki_pages(chat_id)
    if not pages:
        return ""

    full_text = "\n\n---\n\n".join(p.to_markdown() for p in pages)
    estimated_tokens = len(full_text) // CHARS_PER_TOKEN_ESTIMATE

    if estimated_tokens <= token_budget:
        return full_text

    # Fallback: nur Kurzuebersicht, Details muss der Agent gezielt
    # ueber ein Brain-Tool nachladen (siehe save_router.py-Tool-Pattern).
    summary_lines = ["[Wiki zu gross fuer Direct-Read, nur Uebersicht gezeigt]"]
    for page in pages:
        preview = page.body.strip().splitlines()[:2]
        summary_lines.append(f"- {page.concept_id}: {' '.join(preview)[:160]}")
    return "\n".join(summary_lines)


# ── Compile-Step: raw -> wiki (Karpathys eigentlicher Kern) ──────────────
async def compile_wiki_page(
    chat_id: str,
    concept_id: str,
    raw_sources: list[dict[str, Any]],
    llm_client=None,
) -> WikiPage:
    """
    Nimmt rohe Brain-Eintraege/Suchergebnisse und laesst ein LLM daraus
    eine kompilierte, aktualisierte Wiki-Seite schreiben. "Writeback ist
    Pflicht" (Karpathy) - das Ergebnis wird sofort persistiert.

    llm_client: optional injizierbar fuer Tests; im Bot wird hier
    bot_state.client (Groq) uebergeben.
    """
    existing = await load_wiki_page(chat_id, concept_id)
    existing_body = existing.body if existing else "(neue Seite)"

    sources_text = "\n\n".join(
        f"### Quelle: {src.get(\'title\', \'unbenannt\')}\n{src.get(\'content\', \'\')}"
        for src in raw_sources
    )

    prompt = f"""Du pflegst eine Wiki-Seite (Concept-ID: {concept_id}) in einem
persoenlichen LLM-Wiki (Pattern: kompiliertes Wissen, nicht Rohdaten-Dump).

BESTEHENDER STAND DER SEITE:
{existing_body}

NEUE ROHINFORMATIONEN ZUM EINARBEITEN:
{sources_text}

Aufgabe: Aktualisiere die Seite. Schreibe verdichtete Fakten/Konsens,
keine Rohkopien. Halte es kurz (max ~400 Woerter). Antworte NUR mit dem
Markdown-Body der Seite (ohne Frontmatter, das wird automatisch ergaenzt)."""

    if llm_client is None:
        from bot_state import client as llm_client  # lazy import, vermeidet Zirkularitaet

    try:
        completion = await _call_llm(llm_client, prompt)
    except Exception as exc:
        logger.warning("Wiki-Kompilierung fehlgeschlagen fuer %s/%s: %s", chat_id, concept_id, exc)
        completion = existing_body  # bei Fehler: alten Stand behalten statt Datenverlust

    page = WikiPage(
        concept_id=concept_id,
        title=existing.title if existing else concept_id.rsplit("/", 1)[-1].replace("_", " ").title(),
        body=completion.strip(),
        tags=existing.tags if existing else [],
        links=existing.links if existing else [],
    )
    await save_wiki_page(chat_id, page)
    await _mirror_to_brain(chat_id, page)
    return page


async def _call_llm(client, prompt: str) -> str:
    import asyncio

    completion = await asyncio.to_thread(
        client.chat.completions.create,
        model="qwen/qwen3.6-27b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=800,
    )
    return completion.choices[0].message.content or ""


async def _mirror_to_brain(chat_id: str, page: WikiPage) -> None:
    """Spiegelt die kompilierte Seite als Ground-Truth nach Supabase/SQLite
    (brain.py), damit sie einen Redis-Flush ueberlebt. Das ist ein
    seltener, bewusster Write - kein Read-Hotpath."""
    try:
        from brain import save_text

        await save_text(
            chat_id,
            page.to_markdown(),
            title=f"[WIKI] {page.concept_id}",
        )
    except Exception as exc:
        logger.warning("Wiki-Mirror nach Brain fehlgeschlagen fuer %s: %s", page.concept_id, exc)


# ── Writeback-Queue: nicht-blockierend, nach Save/Task-Abschluss ────────
async def queue_wiki_writeback(chat_id: str, *, source_kind: str, source_ref: str) -> None:
    """
    Wird von save_router.py und dem SuperAgent nach Abschluss eines
    Tasks aufgerufen. Loest die Kompilierung als Background-Task aus,
    NICHT synchron im Request-Pfad (Karpathys Setup: "loop once an hour"
    / bei Trigger, nicht bei jeder einzelnen Nachricht).
    """
    import asyncio

    async def _job():
        try:
            from brain import load_all_entries

            entries = await load_all_entries(chat_id)
            recent = entries[:5]
            if not recent:
                return
            concept_id = f"inbox/{source_kind}"
            raw_sources = [
                {"title": e.get("title", ""), "content": e.get("content", "")}
                for e in recent
            ]
            await compile_wiki_page(chat_id, concept_id, raw_sources)
        except Exception as exc:
            logger.warning("queue_wiki_writeback Background-Job fehlgeschlagen: %s", exc)

    asyncio.create_task(_job())


# ── Periodischer Compile-Job (Cron/Scheduler-Hook) ───────────────────────
async def run_periodic_compile(chat_id: str, llm_client=None) -> dict[str, Any]:
    """
    Analog zu Karpathys Setup ('spawns a subagent once an hour, picks the
    next wiki page to write, gathers raw sources, synthesizes').

    In main.py per APScheduler/JobQueue stuendlich fuer aktive Chats
    aufrufen (z.B. alle chat_ids mit full_brain_synced=True).
    """
    from brain import load_all_entries

    entries = await load_all_entries(chat_id)
    if not entries:
        return {"success": False, "reason": "keine Brain-Eintraege"}

    # Einfachste Strategie: neueste 10 Eintraege in ein "recent"-Concept
    # kompilieren. Fuer differenziertere Themen-Buckets kann man hier
    # nach Tags/Titel-Praefixen gruppieren.
    batch = entries[:10]
    raw_sources = [{"title": e.get("title", ""), "content": e.get("content", "")} for e in batch]
    page = await compile_wiki_page(chat_id, "recent/summary", raw_sources, llm_client=llm_client)
    return {"success": True, "concept_id": page.concept_id, "updated_at": page.updated_at}


# ── NEU: Status, Voll-Sync und Export (fuer /wikistatus, /wikisync, /wikiexport) ──

async def get_wiki_status(chat_id: str) -> dict[str, Any]:
    """
    Liefert einen kompakten Statusbericht fuer /wikistatus:
    Anzahl Seiten, Groesse, letztes Update, Redis-Backend aktiv?
    """
    from redis_state import is_persistent

    pages = await load_all_wiki_pages(chat_id)
    total_chars = sum(len(p.to_markdown()) for p in pages)
    estimated_tokens = total_chars // CHARS_PER_TOKEN_ESTIMATE
    latest_update = max((p.updated_at for p in pages), default="-")

    return {
        "chat_id": chat_id,
        "page_count": len(pages),
        "total_chars": total_chars,
        "estimated_tokens": estimated_tokens,
        "within_direct_read_budget": estimated_tokens <= DEFAULT_TOKEN_BUDGET,
        "latest_update": latest_update,
        "redis_backend_active": is_persistent(),
        "pages": [
            {"concept_id": p.concept_id, "title": p.title, "updated_at": p.updated_at, "tags": p.tags}
            for p in sorted(pages, key=lambda x: x.updated_at, reverse=True)
        ],
    }


def format_wiki_status(status: dict[str, Any]) -> str:
    backend = "Redis (persistent)" if status["redis_backend_active"] else "In-Memory (nicht persistent)"
    budget_state = "OK - passt komplett in den Prompt" if status["within_direct_read_budget"] else "ZU GROSS - nur Kurzuebersicht wird geladen"
    lines = [
        f"Wiki-Status fuer diesen Chat",
        f"Seiten: {status['page_count']}",
        f"Groesse: ~{status['total_chars']:,} Zeichen (~{status['estimated_tokens']:,} Tokens)",
        f"Direct-Read-Budget (6000 Tokens): {budget_state}",
        f"Letztes Update: {status['latest_update'] or '-'}",
        f"Speicher-Backend: {backend}",
        "",
        "Seiten:",
    ]
    if not status["pages"]:
        lines.append("(noch keine Seiten - /wikisync ausfuehren)")
    for page in status["pages"][:20]:
        tag_text = f" [{', '.join(page['tags'])}]" if page["tags"] else ""
        lines.append(f"- {page['concept_id']} - {page['title']}{tag_text} (Update: {page['updated_at']})")
    if len(status["pages"]) > 20:
        lines.append(f"... und {len(status['pages']) - 20} weitere")
    return "\n".join(lines)


async def compile_documents_to_wiki(
    chat_id: str,
    limit: int = 50,
    concurrency: int = 3,
    llm_client=None,
) -> dict[str, Any]:
    """
    Fuer /wikisync: kompiliert alle (bzw. die neuesten `limit`) im Brain
    gespeicherten Dokumente/Uploads/Notizen JEWEILS in eine eigene
    Wiki-Seite (statt nur einer einzigen 'recent/summary'-Sammelseite
    wie run_periodic_compile()). Damit bekommt jedes hochgeladene
    Dokument seine eigene, durchsuchbare, kompilierte Zusammenfassung.

    Laeuft mit begrenzter Nebenlaeufigkeit (Default 3), um weder Groq
    noch Supabase/SQLite mit zu vielen parallelen Kompilierungen zu
    ueberlasten.
    """
    import asyncio
    from brain import load_all_entries

    entries = await load_all_entries(chat_id)
    if not entries:
        return {"success": False, "reason": "keine Brain-Eintraege gefunden", "compiled": 0}

    entries = entries[:limit]
    semaphore = asyncio.Semaphore(concurrency)
    compiled_pages: list[str] = []
    failed = 0

    async def _compile_one(entry: dict[str, Any]) -> None:
        nonlocal failed
        async with semaphore:
            entry_id = entry.get("id", "unknown")
            raw_title = (entry.get("title") or f"entry-{entry_id}").strip()
            # Concept-ID aus Titel ableiten (OKF-Pattern: sprechender Pfad statt UUID)
            slug = re.sub(r"[^a-z0-9\-]+", "-", raw_title.lower()).strip("-")[:60] or str(entry_id)
            concept_id = f"documents/{slug}"
            try:
                await compile_wiki_page(
                    chat_id,
                    concept_id,
                    [{"title": raw_title, "content": entry.get("content", "")}],
                    llm_client=llm_client,
                )
                compiled_pages.append(concept_id)
            except Exception as exc:
                logger.warning("Wiki-Sync fehlgeschlagen fuer Eintrag %s: %s", entry_id, exc)
                failed += 1

    await asyncio.gather(*(_compile_one(e) for e in entries))

    return {
        "success": True,
        "compiled": len(compiled_pages),
        "failed": failed,
        "total_entries_considered": len(entries),
        "concept_ids": compiled_pages,
    }


async def export_wiki_markdown_bundle(chat_id: str) -> str:
    """Fuer /wikiexport: gesamten Wiki-Bestand als ein zusammenhaengendes
    Markdown-Dokument (alle Seiten inkl. Frontmatter, durch Trenner
    getrennt)."""
    pages = await load_all_wiki_pages(chat_id)
    if not pages:
        return ""
    header = (
        f"# Wiki-Export\n"
        f"Chat: {chat_id}\n"
        f"Exportiert: {datetime.now(timezone.utc).isoformat()}\n"
        f"Seiten: {len(pages)}\n\n"
        f"---\n\n"
    )
    body = "\n\n---\n\n".join(p.to_markdown() for p in sorted(pages, key=lambda x: x.concept_id))
    return header + body


def create_wiki_pdf(markdown_bundle: str, title: str = "Wiki Export") -> "BytesIO":
    """PDF-Export des Wiki-Bestands, gleiches Muster wie
    send_code_handler.py:create_pdf_from_markdown - falls reportlab
    fehlt, faellt es auf eine reine Textdatei zurueck statt zu crashen."""
    from io import BytesIO

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
    except ImportError:
        buffer = BytesIO(markdown_bundle.encode("utf-8"))
        buffer.name = f"{title.replace(' ', '_')}.txt"
        return buffer

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=18, spaceAfter=20, textColor=colors.darkblue)
    concept_style = ParagraphStyle("Concept", parent=styles["Heading2"], fontSize=12, spaceAfter=4, textColor=colors.darkslategray)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, spaceAfter=12, leading=13)

    story = [Paragraph(title, title_style), Spacer(1, 12)]
    for page_block in markdown_bundle.split("\n\n---\n\n"):
        page_block = page_block.strip()
        if not page_block:
            continue
        heading = page_block.splitlines()[0][:120] if page_block.splitlines() else "Seite"
        safe_body = (
            page_block.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        story.append(Paragraph(heading, concept_style))
        story.append(Paragraph(safe_body.replace("\n", "<br/>"), body_style))
        story.append(Spacer(1, 10))

    doc.build(story)
    buffer.seek(0)
    buffer.name = f"wiki_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.pdf"
    return buffer
