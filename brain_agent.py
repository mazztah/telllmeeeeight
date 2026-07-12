# brain_agent.py – Intelligenter Brain RAG-Agent
import asyncio
import logging
from typing import Optional

from bot_state import client as groq_client
from vectorbrain import semantic_search
from brain import load_all_entries

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3-70b-8192"
FALLBACK_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


async def brain_query_agent(chat_id: str, query: str, top_k: int = 8) -> dict:
    """
    Hauptfunktion: Semantische Suche + intelligenter LLM-Agent
    """
    if not query or not query.strip():
        return {"success": False, "answer": "Bitte stelle eine Frage."}

    try:
        # 1. Semantische Suche
        results = await semantic_search(chat_id, query, top_k=top_k)

        if not results:
            # Fallback: Alle Einträge laden und einfache Suche
            entries = await load_all_entries(chat_id)
            context = "\n\n".join([f"Titel: {e.get('title')}\n{e.get('content', '')[:800]}" 
                                 for e in entries[:10]])
        else:
            context = "\n\n".join([
                f"Titel: {r['title']}\nScore: {r['score']}\n{r['content'][:700]}" 
                for r in results
            ])

        # 2. System Prompt (sehr wichtig)
        system_prompt = """
Du bist ein hochkompetenter, hilfsbereiter Wissens-Assistent mit Zugriff auf das persönliche "Brain" des Users.
Antworte natürlich, präzise und freundlich auf Deutsch.
Nutze die bereitgestellten Brain-Einträge als primäre Wissensquelle.
Wenn etwas nicht im Brain steht, sage es ehrlich, ergänze aber mit allgemeinem Wissen.

Strukturiere deine Antwort bei längeren Themen gerne mit Aufzählungen oder Abschnitten.
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Brain-Kontext:\n{context}\n\nFrage: {query}"}
        ]

        # 3. LLM-Aufruf
        try:
            completion = groq_client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=messages,
                temperature=0.65,
                max_tokens=1600,
                top_p=0.95,
            )
        except Exception:
            completion = groq_client.chat.completions.create(
                model=FALLBACK_MODEL,
                messages=messages,
                temperature=0.65,
                max_tokens=1600,
                top_p=0.95,
            )

        answer = completion.choices[0].message.content.strip()

        return {
            "success": True,
            "answer": answer,
            "sources": len(results),
            "used_semantic_search": len(results) > 0
        }

    except Exception as e:
        logger.error(f"Brain Agent Fehler: {e}")
        return {
            "success": False,
            "answer": "Es gab ein technisches Problem bei der Brain-Abfrage. Bitte versuche es später erneut."
        }