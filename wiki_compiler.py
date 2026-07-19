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
        f"### Quelle: {src.get('title', 'unbenannt')}\n{src.get('content', '')[:1500]}"
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
