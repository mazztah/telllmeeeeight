# redis_state.py – Persistenter Session-/State-Layer
#
# Ersetzt die In-Memory-Dicts aus bot_state.py (chat_histories, video_tasks,
# synced_brain, full_brain_synced, jobqueen_state, guard-Rate-Limits, ...),
# die aktuell bei jedem Redeploy/Sleep (Render/Railway Free Tier) verloren
# gehen.
#
# Nutzt einen kostenlosen/günstigen Redis (z.B. Upstash, Railway Redis,
# Render Key-Value) über REDIS_URL. Fällt bei fehlendem REDIS_URL auf ein
# reines In-Memory-Dict zurück, damit lokale Entwicklung ohne Redis
# weiterhin funktioniert.

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "").strip()
DEFAULT_TTL_SECONDS = int(os.getenv("REDIS_DEFAULT_TTL", str(60 * 60 * 24 * 365 * 10)))  # 10 Jahre für Persistenz

# ── Backend-Auswahl ──────────────────────────────────────────────────────
_redis_client = None
_fallback_store: dict[str, str] = {}  # nur falls kein Redis konfiguriert ist


def _get_client():
    global _redis_client
    if _redis_client is not None or not REDIS_URL:
        return _redis_client
    try:
        import redis.asyncio as redis  # type: ignore

        pool = redis.ConnectionPool.from_url(
            REDIS_URL, decode_responses=True, max_connections=20
        )
        _redis_client = redis.Redis(connection_pool=pool)
        logger.info("Redis-State aktiv: %s", REDIS_URL.split("@")[-1])
    except Exception as exc:
        logger.warning(
            "REDIS_URL gesetzt, aber redis-Paket/Verbindung fehlgeschlagen (%s). "
            "Falle auf In-Memory-Fallback zurueck - State ueberlebt KEINE Redeploys!",
            exc,
        )
        _redis_client = None
    return _redis_client


def is_persistent() -> bool:
    """True wenn ein echter Redis-Backend aktiv ist (nicht der In-Memory-Fallback)."""
    return _get_client() is not None


# ── Low-Level: get/set/delete ────────────────────────────────────────────
async def get_raw(key: str) -> Optional[str]:
    client = _get_client()
    if client is not None:
        try:
            return await client.get(key)
        except Exception as exc:
            logger.warning("Redis GET fehlgeschlagen fuer %s: %s", key, exc)
            return _fallback_store.get(key)
    return _fallback_store.get(key)


async def set_raw(key: str, value: str, ttl: int | None = DEFAULT_TTL_SECONDS) -> None:
    client = _get_client()
    if client is not None:
        try:
            await client.set(key, value, ex=ttl)
            return
        except Exception as exc:
            logger.warning("Redis SET fehlgeschlagen fuer %s: %s", key, exc)
    _fallback_store[key] = value


async def delete_key(key: str) -> None:
    client = _get_client()
    if client is not None:
        try:
            await client.delete(key)
        except Exception as exc:
            logger.warning("Redis DEL fehlgeschlagen fuer %s: %s", key, exc)
    _fallback_store.pop(key, None)


# ── JSON-Helper (fuer Dicts/Listen wie chat_histories, video_tasks, ...) ─
async def get_json(key: str, default: Any = None) -> Any:
    raw = await get_raw(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


async def set_json(key: str, value: Any, ttl: int | None = DEFAULT_TTL_SECONDS) -> None:
    await set_raw(key, json.dumps(value, ensure_ascii=False), ttl=ttl)


# ── Namespaced Helper fuer die konkreten bot_state-Dicts ────────────────
# Diese Funktionen sind 1:1-Ersatz fuer die bisherigen In-Memory-Zugriffe,
# damit der Umbau in handlers_*.py minimal-invasiv bleibt.

async def get_chat_history(chat_id: str) -> list:
    return await get_json(f"chat:{chat_id}:history", [])


async def save_chat_history(chat_id: str, history: list) -> None:
    await set_json(f"chat:{chat_id}:history", history)


async def get_flag(namespace: str, chat_id: str, default: Any = None) -> Any:
    """Generischer Ersatz fuer simple dict[chat_id] = value Zugriffe,
    z.B. tts_enabled, full_brain_synced, edit_mode_active, stream_active."""
    return await get_json(f"{namespace}:{chat_id}", default)


async def set_flag(namespace: str, chat_id: str, value: Any, ttl: int | None = DEFAULT_TTL_SECONDS) -> None:
    await set_json(f"{namespace}:{chat_id}", value, ttl=ttl)


async def get_synced_brain_ids(chat_id: str) -> list[str]:
    return await get_json(f"synced_brain:{chat_id}", [])


async def set_synced_brain_ids(chat_id: str, entry_ids: list[str]) -> None:
    await set_json(f"synced_brain:{chat_id}", entry_ids)


# ── Rate-Limit-Buckets (Ersatz fuer guard.py _RATE_BUCKETS) ─────────────
# guard.py haelt Rate-Limits aktuell rein in-memory (_RATE_BUCKETS als
# module-level dict[tuple, deque]). Bei Redeploy sind alle Limits weg,
# d.h. Abuse-Schutz startet bei 0. Fuer Produktions-Deployments sollte
# das ueber Redis INCR + EXPIRE laufen statt ueber lokale deques:

async def rate_limit_hit(chat_id: str, action: str, window_seconds: int) -> int:
    """Erhoeht den Zaehler fuer (chat_id, action) und setzt bei Bedarf ein
    TTL-Fenster. Gibt die aktuelle Anzahl im Fenster zurueck."""
    client = _get_client()
    key = f"ratelimit:{action}:{chat_id}"
    if client is not None:
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window_seconds)
            return int(count)
        except Exception as exc:
            logger.warning("Redis rate_limit_hit fehlgeschlagen: %s", exc)
    # Fallback: kein echtes Sliding-Window, aber wenigstens kein Crash
    current = int(_fallback_store.get(key, "0") or "0") + 1
    _fallback_store[key] = str(current)
    return current
