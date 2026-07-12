import asyncio
import hashlib
import json
import logging
import math
import os
import re
from collections import Counter
from typing import Any

from brain import get_supabase, is_enabled, load_all_entries

logger = logging.getLogger(__name__)

VECTOR_TABLE_NAME = os.getenv("VECTOR_TABLE_NAME", "brain_vectors")
LOCAL_VECTOR_DIMENSIONS = int(os.getenv("VECTOR_DIMENSIONS", "384"))
VECTOR_EMBEDDING_PROVIDER = os.getenv("VECTOR_EMBEDDING_PROVIDER", "auto").lower()
VECTOR_EMBEDDING_MODEL = os.getenv(
    "VECTOR_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

try:
    from sentence_transformers import SentenceTransformer

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except Exception:
    SentenceTransformer = None
    SENTENCE_TRANSFORMERS_AVAILABLE = False

_embedder = None


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[0-9A-Za-zÀ-ÿ_/-]{2,}", (text or "").lower())


def _local_embed_text(text: str, dimensions: int = LOCAL_VECTOR_DIMENSIONS) -> list[float]:
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * dimensions

    vector = [0.0] * dimensions
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1.0 if digest[2] % 2 else -1.0
        weight = 1.0 + min(len(token), 12) / 12.0
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _should_use_sentence_transformers() -> bool:
    if VECTOR_EMBEDDING_PROVIDER == "local":
        return False
    return SENTENCE_TRANSFORMERS_AVAILABLE


def _get_embedder():
    global _embedder
    if not _should_use_sentence_transformers():
        return None

    if _embedder is None:
        try:
            _embedder = SentenceTransformer(VECTOR_EMBEDDING_MODEL)
            logger.info("Sentence-Transformer fuer VectorBrain geladen: %s", VECTOR_EMBEDDING_MODEL)
        except Exception as exc:
            logger.warning("Sentence-Transformer konnte nicht geladen werden, nutze lokalen Fallback: %s", exc)
            _embedder = False

    return _embedder if _embedder not in (None, False) else None


def _embed_with_sentence_transformers(text: str) -> list[float] | None:
    model = _get_embedder()
    if model is None:
        return None

    try:
        vector = model.encode(text or "", normalize_embeddings=True)
        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        return [float(value) for value in vector]
    except Exception as exc:
        logger.warning("Sentence-Transformer Encoding fehlgeschlagen, nutze lokalen Fallback: %s", exc)
        return None


def embed_text(text: str) -> list[float]:
    embedded = _embed_with_sentence_transformers(_normalize(text))
    if embedded:
        return embedded
    return _local_embed_text(text)


async def embed_text_async(text: str) -> list[float]:
    return await asyncio.to_thread(embed_text, text)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _lexical_score(query: str, content: str) -> float:
    query_tokens = _tokenize(query)
    content_tokens = _tokenize(content)
    if not query_tokens or not content_tokens:
        return 0.0

    content_counter = Counter(content_tokens)
    overlap = sum(min(content_counter[token], 1) for token in set(query_tokens))
    return overlap / max(1, len(set(query_tokens)))


def _serialize_metadata(metadata: Any) -> dict:
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _entry_to_text(entry: dict) -> str:
    metadata = _serialize_metadata(entry.get("metadata"))
    preview = metadata.get("extracted_preview", "")
    title = entry.get("title") or ""
    content = entry.get("content") or ""
    if entry.get("entry_type") == "chat":
        content = content[:6000]
    return _normalize(f"{title}\n{preview}\n{content}")


async def _vector_record(chat_id: str, entry: dict) -> dict:
    text = _entry_to_text(entry)
    return {
        "user_id": str(chat_id),
        "entry_id": str(entry.get("id")),
        "title": entry.get("title") or "Ohne Titel",
        "content": text[:12000],
        "metadata": _serialize_metadata(entry.get("metadata")),
        "embedding": await embed_text_async(text),
    }


async def index_brain_entries(chat_id: str, limit: int = 40) -> dict:
    entries = await load_all_entries(chat_id)
    if not entries:
        return {"success": False, "indexed": 0, "persisted": 0, "message": "Keine Brain-Eintraege zum Indexieren gefunden."}

    prepared = []
    for entry in entries[: max(1, limit)]:
        prepared.append(await _vector_record(chat_id, entry))

    persisted = 0

    if is_enabled():
        try:
            client = get_supabase()
            client.table(VECTOR_TABLE_NAME).upsert(prepared, on_conflict="user_id,entry_id").execute()
            persisted = len(prepared)
        except Exception as exc:
            logger.warning("Vector-Index konnte nicht in Supabase gespeichert werden: %s", exc)

    provider = "sentence-transformers" if _should_use_sentence_transformers() and _get_embedder() else "local"
    return {
        "success": True,
        "indexed": len(prepared),
        "persisted": persisted,
        "message": f"{len(prepared)} Brain-Eintraege wurden semantisch vorbereitet ({provider}).",
    }


async def _load_persisted_vectors(chat_id: str) -> list[dict]:
    if not is_enabled():
        return []
    try:
        client = get_supabase()
        response = (
            client.table(VECTOR_TABLE_NAME)
            .select("entry_id, title, content, metadata, embedding")
            .eq("user_id", str(chat_id))
            .limit(200)
            .execute()
        )
        return response.data or []
    except Exception as exc:
        logger.warning("Persistierter Vector-Load fehlgeschlagen: %s", exc)
        return []


def _coerce_embedding(raw_embedding: Any) -> list[float]:
    if isinstance(raw_embedding, list):
        return [float(value) for value in raw_embedding]
    if isinstance(raw_embedding, str):
        try:
            parsed = json.loads(raw_embedding)
            if isinstance(parsed, list):
                return [float(value) for value in parsed]
        except Exception:
            return []
    return []


async def semantic_search(chat_id: str, query: str, top_k: int = 5) -> list[dict]:
    query_vector = await embed_text_async(query)
    candidates = await _load_persisted_vectors(chat_id)

    if not candidates:
        entries = await load_all_entries(chat_id)
        candidates = [await _vector_record(chat_id, entry) for entry in entries[:80]]

    scored: list[dict] = []
    for row in candidates:
        content = (row.get("content") or "").strip()
        if not content:
            continue

        embedding = _coerce_embedding(row.get("embedding")) or row.get("embedding")
        if not isinstance(embedding, list):
            continue
        if len(embedding) != len(query_vector):
            embedding = await embed_text_async(content)

        vector_score = cosine_similarity(query_vector, embedding)
        lexical_score = _lexical_score(query, content)
        score = (vector_score * 0.82) + (lexical_score * 0.18)
        if score <= 0.04:
            continue

        scored.append(
            {
                "entry_id": row.get("entry_id"),
                "title": row.get("title") or "Ohne Titel",
                "content": content,
                "metadata": _serialize_metadata(row.get("metadata")),
                "score": round(score, 4),
                "vector_score": round(vector_score, 4),
                "lexical_score": round(lexical_score, 4),
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[: max(1, top_k)]


def format_semantic_results(results: list[dict]) -> str:
    if not results:
        return "Keine semantisch passenden Brain-Treffer gefunden."

    lines = ["Semantische Brain-Treffer:"]
    for index, item in enumerate(results, start=1):
        snippet = item["content"][:220].replace("\n", " ")
        if len(item["content"]) > 220:
            snippet += "..."
        lines.append(
            f"{index}. ID: {item.get('entry_id')} | Score: {item['score']} | Vector: {item['vector_score']} | Lexical: {item['lexical_score']}\n"
            f"{item['title']}\n{snippet}"
        )
    return "\n\n".join(lines)
