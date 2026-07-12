# brain.py – Persistent Brain | Supabase primär + SQLite Fallback
# ══════════════════════════════════════════════════════════════════
# Wenn Supabase-Egress erschöpft ist, schaltet brain.py automatisch
# auf eine lokale SQLite-Datenbank unter /data/brain.sqlite um.
# Schreiben/Lesen funktioniert damit weiterhin offline/lokal.
# ══════════════════════════════════════════════════════════════════

import os
import json
import logging
import base64
import asyncio
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Import aus dv.py für Content-Extraktion
from dv import extract_content

logger = logging.getLogger(__name__)

# ── Konfiguration ──────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")
TABLE_NAME = "brain_entries"

# Lokale SQLite-Datenbank
DB_PATH = Path(os.getenv("DATA_DIR", "/data")) / "brain.sqlite"
try:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError) as exc:
    DB_PATH = Path(__file__).resolve().parent / "data" / "brain.sqlite"
    logger.warning(
        "Brain-Datenverzeichnis nicht beschreibbar (%s) – verwende Fallback '%s'",
        exc, DB_PATH.parent,
    )
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Supabase Client (Singleton, lazy) ─────────────────────────────────────────

_supabase_client = None
_supabase_broken = False        # Wird True, wenn Supabase dauerhaft fehlschlägt
_supabase_broken_until = 0.0   # Unix-Timestamp: nach dieser Zeit erneut versuchen
_SUPABASE_RETRY_AFTER = 300    # 5 Minuten warten bevor erneuter Versuch
_SUPABASE_CALL_TIMEOUT = 6.0   # Maximale Wartezeit pro Supabase-Call (Sekunden)


def get_supabase():
    import time
    global _supabase_client, _supabase_broken, _supabase_broken_until
    if _supabase_broken:
        # Erneuter Versuch nach _SUPABASE_RETRY_AFTER Sekunden
        if time.time() < _supabase_broken_until:
            return None
        # Retry-Fenster: Flag zurücksetzen und nochmal probieren
        logger.info("🔄 Supabase-Retry nach Pause...")
        _supabase_broken = False
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    if _supabase_client is None:
        try:
            from supabase import create_client
            _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            logger.warning(f"Supabase init fehlgeschlagen: {e}")
            _supabase_broken = True
            return None
    return _supabase_client


def _mark_supabase_broken(e: Exception):
    """Markiert Supabase als nicht verfügbar und setzt einen Retry-Timer."""
    import time
    global _supabase_broken, _supabase_broken_until
    err_str = str(e).lower()

    # Alle bekannten Fehler die einen sofortigen Fallback rechtfertigen:
    # Quota/Billing: 402, 429, egress, exceeded
    # Server-Fehler: 5xx (500, 520, 521, 522), connection timeout
    # Statement-Fehler: 57014 (statement timeout)
    is_hard_failure = any(k in err_str for k in (
        "quota", "exceeded", "402", "429", "503", "rate limit", "egress",
        "522", "521", "520", "connection timed out", "timed out",
        "57014", "statement timeout", "500",
    ))

    if is_hard_failure:
        _supabase_broken = True
        _supabase_broken_until = time.time() + _SUPABASE_RETRY_AFTER
        retry_at = __import__("datetime").datetime.fromtimestamp(_supabase_broken_until).strftime("%H:%M:%S")
        logger.warning(f"⚠️ Supabase deaktiviert bis {retry_at} → SQLite aktiv. Fehler: {str(e)[:100]}")
    else:
        logger.warning(f"Supabase-Fehler (temporär?): {str(e)[:120]}")


def is_enabled() -> bool:
    """True wenn Supabase ODER SQLite verfügbar ist – immer True."""
    return True


def is_supabase_enabled() -> bool:
    import time
    return bool(SUPABASE_URL and SUPABASE_KEY and not _supabase_broken) or \
           (bool(SUPABASE_URL and SUPABASE_KEY) and time.time() >= _supabase_broken_until)


async def _supabase_call(fn):
    """Führt einen Supabase-Call mit Timeout aus. Gibt None zurück bei Fehler."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn),
            timeout=_SUPABASE_CALL_TIMEOUT
        )
    except asyncio.TimeoutError:
        raise Exception(f"connection timed out after {_SUPABASE_CALL_TIMEOUT}s")
    except Exception:
        raise


# ── SQLite Setup ───────────────────────────────────────────────────────────────

_sqlite_conn: Optional[sqlite3.Connection] = None


def get_sqlite() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _sqlite_conn.row_factory = sqlite3.Row
        _init_sqlite_schema()
        logger.info(f"✅ SQLite Brain geöffnet: {DB_PATH}")
    return _sqlite_conn


def _init_sqlite_schema():
    cur = _sqlite_conn.cursor()
    # WAL Mode für bessere Performance (lesen während schreiben)
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brain_entries (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            entry_type  TEXT NOT NULL DEFAULT 'text',
            title       TEXT,
            content     TEXT,
            metadata    TEXT DEFAULT '{}',
            created_at  TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON brain_entries(user_id)")
    _sqlite_conn.commit()


def _sqlite_row_to_dict(row) -> dict:
    return dict(row)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ── SQLite CRUD ────────────────────────────────────────────────────────────────

def _sqlite_insert(entry: dict) -> dict:
    conn = get_sqlite()
    entry.setdefault("id", _new_id())
    entry.setdefault("created_at", _now_iso())
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO brain_entries (id, user_id, entry_type, title, content, metadata, created_at)
        VALUES (:id, :user_id, :entry_type, :title, :content, :metadata, :created_at)
    """, entry)
    conn.commit()
    return entry


def _sqlite_select_all(user_id: str) -> list:
    conn = get_sqlite()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM brain_entries WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    )
    return [_sqlite_row_to_dict(r) for r in cur.fetchall()]


def _sqlite_select_one(user_id: str, entry_id: str) -> Optional[dict]:
    conn = get_sqlite()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM brain_entries WHERE id = ? AND user_id = ?",
        (entry_id, user_id)
    )
    row = cur.fetchone()
    return _sqlite_row_to_dict(row) if row else None


def _sqlite_delete(user_id: str, entry_id: str) -> bool:
    conn = get_sqlite()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM brain_entries WHERE id = ? AND user_id = ?",
        (entry_id, user_id)
    )
    conn.commit()
    return cur.rowcount > 0


def _sqlite_count(user_id: str) -> int:
    conn = get_sqlite()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM brain_entries WHERE user_id = ?", (user_id,))
    return cur.fetchone()[0]


# ── Verbindungstest ────────────────────────────────────────────────────────────

async def test_connection() -> str:
    # 1. SQLite primär (schnell, lokal, zuverlässig)
    try:
        conn = get_sqlite()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM brain_entries")
        count = cur.fetchone()[0]
        sqlite_ok = True
    except Exception as e:
        sqlite_ok = False
        count = 0

    # 2. Supabase als Hintergrund-Check (nicht blockierend)
    supa = get_supabase()
    if supa:
        try:
            response = await _supabase_call(
                lambda: supa.table(TABLE_NAME).select("*", count="exact", head=True).execute()
            )
            supa_count = response.count if response.count is not None else 0
            return f"✅ SQLite OK: {count} Einträge | Supabase: {supa_count} Einträge"
        except Exception as e:
            _mark_supabase_broken(e)
            return f"✅ SQLite OK: {count} Einträge | ⚠️ Supabase nicht verfügbar"

    return f"✅ SQLite OK: {count} Einträge | ⚠️ Supabase nicht konfiguriert"



# ── Chat & Text speichern ──────────────────────────────────────────────────────

async def save_chat(chat_id: str, history: List[Dict], title: Optional[str] = None) -> str:
    entry = {
        "user_id": str(chat_id),
        "entry_type": "chat",
        "title": title or f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": json.dumps(history, ensure_ascii=False),
        "metadata": json.dumps({"message_count": len(history)}),
    }

    # 1. SQLite primär (sofort, blockierungsfrei)
    try:
        saved = await asyncio.to_thread(_sqlite_insert, entry)
        sqlite_id = saved["id"]
    except Exception as e:
        logger.exception("Chat-Save SQLite Fehler")
        return f"❌ Speichern fehlgeschlagen: {e}"

    # 2. Supabase Hintergrund-Sync (nicht blockierend)
    supa = get_supabase()
    if supa:
        try:
            asyncio.create_task(_supabase_call(
                lambda: supa.table(TABLE_NAME).insert(entry).execute()
            ))
        except Exception as e:
            _mark_supabase_broken(e)

    return f"✅ Chat gespeichert\nID: {sqlite_id}\nTitel: {entry['title']}"


async def save_text(chat_id: str, text: str, title: Optional[str] = None) -> str:
    entry = {
        "user_id": str(chat_id),
        "entry_type": "safe_text",
        "title": title or f"Text {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": text,
        "metadata": json.dumps({"char_count": len(text)}),
    }

    # 1. SQLite primär
    try:
        saved = await asyncio.to_thread(_sqlite_insert, entry)
        sqlite_id = saved["id"]
    except Exception as e:
        logger.exception("Text-Save SQLite Fehler")
        return f"❌ Interner Fehler: {e}"

    # 2. Supabase Hintergrund-Sync
    supa = get_supabase()
    if supa:
        try:
            asyncio.create_task(_supabase_call(
                lambda: supa.table(TABLE_NAME).insert(entry).execute()
            ))
        except Exception as e:
            _mark_supabase_broken(e)

    return f"✅ Text gespeichert\nID: {sqlite_id}"


# ── Dateien ins Brain laden ────────────────────────────────────────────────────

async def save_file(chat_id: str, file_bytes: bytes, filename: str, mime_type: str = None) -> str:
    if not file_bytes:
        return "❌ Keine Datei-Daten übergeben"

    content_preview = extract_content_from_bytes(file_bytes, filename)

    entry = {
        "user_id": str(chat_id),
        "entry_type": "file",
        "title": filename or f"File {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": base64.b64encode(file_bytes).decode("utf-8"),
        "metadata": json.dumps({
            "mime_type": mime_type or "unknown",
            "filename": filename,
            "char_count": len(content_preview),
            "extracted_preview": content_preview[:2000],
        }),
    }

    # 1. SQLite primär
    try:
        saved = await asyncio.to_thread(_sqlite_insert, entry)
        sqlite_id = saved["id"]
    except Exception as e:
        logger.exception("File-Save SQLite Fehler")
        return f"❌ Speichern fehlgeschlagen: {e}"

    # 2. Supabase Hintergrund-Sync
    supa = get_supabase()
    if supa:
        try:
            asyncio.create_task(_supabase_call(
                lambda: supa.table(TABLE_NAME).insert(entry).execute()
            ))
        except Exception as e:
            _mark_supabase_broken(e)

    return f"✅ Datei **{filename}** ins Brain geladen\nID: `{sqlite_id}`"


def extract_content_from_bytes(file_bytes: bytes, filename: str) -> str:
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        return extract_content(tmp_path)
    except Exception:
        return ""
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Laden von Einträgen ────────────────────────────────────────────────────────

async def load_entry(chat_id: str, entry_id: str) -> Optional[dict]:
    # 1. SQLite primär (schnell, lokal)
    try:
        result = await asyncio.to_thread(_sqlite_select_one, str(chat_id), entry_id)
        if result:
            return result
    except Exception as e:
        logger.error(f"load_entry SQLite Fehler: {e}")

    # 2. Supabase Fallback (nur wenn SQLite nichts fand)
    supa = get_supabase()
    if supa:
        try:
            response = await _supabase_call(
                lambda: supa.table(TABLE_NAME).select("*")
                .eq("id", entry_id).eq("user_id", str(chat_id)).execute()
            )
            if response.data:
                return response.data[0]
        except Exception as e:
            _mark_supabase_broken(e)

    return None


async def load_all_entries(chat_id: str) -> list:
    # 1. SQLite primär (immer schnell, immer verfügbar)
    try:
        return await asyncio.to_thread(_sqlite_select_all, str(chat_id))
    except Exception as e:
        logger.error(f"load_all_entries SQLite Fehler: {e}")

    # 2. Supabase Fallback (nur wenn SQLite komplett fehlschlägt)
    supa = get_supabase()
    if supa:
        try:
            response = await _supabase_call(
                lambda: supa.table(TABLE_NAME).select("*")
                .eq("user_id", str(chat_id))
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []
        except Exception as e:
            _mark_supabase_broken(e)
            logger.warning(f"load_all_entries Supabase fehlgeschlagen: {str(e)[:80]}")

    return []


# ── List & Delete ──────────────────────────────────────────────────────────────

async def list_entries(chat_id: str, limit: int = 10) -> str:
    entries = []

    # 1. SQLite primär
    try:
        all_rows = await asyncio.to_thread(_sqlite_select_all, str(chat_id))
        entries = all_rows[:limit]
    except Exception as e:
        return f"❌ Fehler beim Abrufen: {e}"

    # 2. Supabase Fallback (nur wenn SQLite leer)
    if not entries:
        supa = get_supabase()
        if supa:
            try:
                response = await _supabase_call(
                    lambda: supa.table(TABLE_NAME)
                    .select("id, entry_type, title, created_at, metadata")
                    .eq("user_id", str(chat_id))
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                entries = response.data or []
            except Exception as e:
                _mark_supabase_broken(e)

    if not entries:
        return "Keine Einträge vorhanden."

    source = "SQLite (primär)" if entries else "Supabase (Fallback)"
    lines = [f"🧠 Brain-Einträge ({source}):"]
    for row in entries:
        etype = row.get("entry_type", "?")
        label = {"chat": "Chat", "safe_text": "Text", "file": "Datei"}.get(etype, etype)
        created = (row.get("created_at") or "—")[:19].replace("T", " ")
        meta = json.loads(row.get("metadata") or "{}")
        count = meta.get("message_count") or meta.get("char_count") or meta.get("filename", "—")
        title_short = (row.get("title") or "ohne Titel")[:55]
        lines.append(f"• {label} | {row['id']} | {title_short} | {created} | {count}")

    return "\n".join(lines)


async def delete_entry(chat_id: str, entry_id: str) -> str:
    # 1. SQLite primär
    try:
        deleted = await asyncio.to_thread(_sqlite_delete, str(chat_id), entry_id)
        if deleted:
            sqlite_ok = True
        else:
            sqlite_ok = False
    except Exception as e:
        sqlite_ok = False

    # 2. Supabase Hintergrund-Sync
    supa = get_supabase()
    if supa:
        try:
            asyncio.create_task(_supabase_call(
                lambda: supa.table(TABLE_NAME).delete()
                .eq("id", entry_id).eq("user_id", str(chat_id)).execute()
            ))
        except Exception as e:
            _mark_supabase_broken(e)

    if sqlite_ok:
        return f"✅ Eintrag **{entry_id}** gelöscht"
    return "❌ Eintrag nicht gefunden."


# ── Status & Master-Prompt ─────────────────────────────────────────────────────

async def get_brain_status() -> dict:
    import time
    sqlite_ok = False
    entry_count = 0

    # 1. SQLite primär
    try:
        conn = get_sqlite()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM brain_entries")
        entry_count = cur.fetchone()[0]
        sqlite_ok = True
    except Exception:
        entry_count = -1

    # 2. Supabase Status (nicht blockierend)
    supa = get_supabase()
    supa_ok = False
    if supa:
        try:
            response = await _supabase_call(
                lambda: supa.table(TABLE_NAME).select("*", count="exact", head=True).execute()
            )
            supa_ok = True
        except Exception as e:
            _mark_supabase_broken(e)

    retry_in = max(0, int(_supabase_broken_until - time.time())) if _supabase_broken else 0

    return {
        "enabled": True,
        "backend": "sqlite (primär)" if sqlite_ok else "supabase (Fallback)",
        "sqlite_available": sqlite_ok,
        "supabase_available": supa_ok,
        "supabase_broken_flag": _supabase_broken,
        "supabase_retry_in_seconds": retry_in,
        "sqlite_path": str(DB_PATH),
        "entry_count": entry_count,
        "table": TABLE_NAME,
    }


async def set_master_prompt(chat_id: str, entry_id: str) -> Optional[str]:
    entry = await load_entry(chat_id, entry_id)
    if not entry or entry.get("entry_type") != "file":
        return None
    try:
        decoded = base64.b64decode(entry["content"])
        return decoded.decode("utf-8", errors="ignore")[:8000]
    except Exception as e:
        logger.error(f"set_master_prompt Fehler: {e}")
        return None