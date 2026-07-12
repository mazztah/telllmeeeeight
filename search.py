import html
import logging
import os
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)


def _get_serpapi_key() -> str | None:
    return os.getenv("SERPAPI_KEY")


def has_valid_serpapi_key() -> bool:
    """Prueft, ob ein plausibler API-Key vorhanden ist."""
    api_key = _get_serpapi_key()
    return bool(api_key and len(api_key) >= 20)


def web_search(
    query: str,
    num_results: int = 8,
    country: str = "de",
    language: str = "de",
    location: Optional[str] = None,
) -> Dict:
    """
    Fuehrt eine Google-Suche ueber SerpApi durch und gibt ein einheitliches
    Dictionary mit immer vorhandenen Schluesseln zurueck.
    """
    api_key = _get_serpapi_key()
    if not has_valid_serpapi_key():
        return {
            "success": False,
            "error": "Kein gueltiger SERPAPI_KEY im Environment gesetzt",
            "query": query,
            "results": [],
            "answer_box": None,
            "knowledge_graph": None,
            "total_results": 0,
        }

    params = {
        "engine": "google",
        "q": (query or "").strip(),
        "num": min(max(num_results, 3), 15),
        "hl": language,
        "gl": country,
        "location": location or ("Germany" if country == "de" else "United States"),
        "api_key": api_key,
    }

    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=12)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in (data.get("organic_results") or [])[:num_results]:
            snippet = item.get("snippet") or item.get("rich_snippet", {}).get("snippet", "")
            results.append(
                {
                    "title": item.get("title", "-"),
                    "link": item.get("link", item.get("redirect_link", item.get("displayed_link", "-"))),
                    "snippet": (snippet or "").strip(),
                    "date": item.get("date", ""),
                    "position": item.get("position", 0),
                }
            )

        return {
            "success": True,
            "query": query,
            "results": results,
            "answer_box": data.get("answer_box"),
            "knowledge_graph": data.get("knowledge_graph"),
            "total_results": data.get("search_information", {}).get("total_results", len(results)),
        }

    except requests.Timeout:
        logger.warning("SerpApi Timeout fuer Query: %s", query)
        return _error_result(query, "Timeout - SerpApi antwortet nicht schnell genug")
    except requests.HTTPError as http_err:
        status = http_err.response.status_code if http_err.response else 0
        msg = http_err.response.text[:300] if http_err.response else str(http_err)
        if status == 403:
            error_text = "403 Forbidden - API-Key ungueltig, abgelaufen oder Kontingent aufgebraucht"
        elif status == 429:
            error_text = "429 Too Many Requests - Rate-Limit erreicht"
        else:
            error_text = f"HTTP {status} - {msg}"
        logger.error("SerpApi Fehler %s fuer Query %s: %s", status, query, error_text)
        return _error_result(query, error_text)
    except Exception as exc:
        logger.exception("SerpApi unerwarteter Fehler fuer Query: %s", query)
        return _error_result(query, f"Interner Fehler: {str(exc)[:240]}")


def _error_result(query: str, error_msg: str) -> Dict:
    return {
        "success": False,
        "error": error_msg,
        "query": query,
        "results": [],
        "answer_box": None,
        "knowledge_graph": None,
        "total_results": 0,
    }


def format_search_results_for_prompt(result_dict: Dict) -> str:
    """Formatiert Suchergebnisse fuer Prompts kompakt und strukturiert."""
    if not result_dict.get("success"):
        return f"Web-Suche fehlgeschlagen: {result_dict.get('error', 'unbekannter Fehler')}\n"

    lines = [f'Web-Suchergebnisse fuer: "{result_dict["query"]}"\n']

    if ab := result_dict.get("answer_box"):
        if answer := ab.get("answer") or ab.get("snippet"):
            lines.append(f"Direkte Antwort / Featured Snippet:\n{answer}\n")
        if title := ab.get("title"):
            lines.append(f"Quelle: {title} - {ab.get('link') or ab.get('url', '')}\n")

    if kg := result_dict.get("knowledge_graph"):
        if name := kg.get("title") or kg.get("name"):
            lines.append(f"Knowledge Graph: {name}")
            if desc := kg.get("description"):
                lines.append(f"Beschreibung: {desc}")
            lines.append("")

    for index, result in enumerate(result_dict["results"], start=1):
        lines.append(f"{index}. {result['title']}")
        if result["snippet"]:
            lines.append(result["snippet"])
        lines.append(result["link"])
        if result["date"]:
            lines.append(f"({result['date']})")
        lines.append("")

    return "\n".join(lines).strip()


def format_search_results_for_user(result_dict: Dict, max_snippet: int = 220) -> str:
    """Formatiert Suchergebnisse sicher fuer Telegram-HTML."""
    if not result_dict.get("success"):
        safe_error = html.escape(str(result_dict.get("error", "?"))[:180])
        return f"🔍 Suche leider fehlgeschlagen:\n{safe_error}"

    safe_query = html.escape(str(result_dict.get("query") or ""))
    lines = [f"<b>🔍 Suche:</b> <code>{safe_query}</code>\n"]

    if ab := result_dict.get("answer_box"):
        lines.append("<b>💡 Direkt Antwort:</b>")
        if answer := ab.get("answer") or ab.get("snippet"):
            safe_answer = html.escape(str(answer[:500]))
            suffix = "…" if len(answer) > 500 else ""
            lines.append(f"<i>{safe_answer}{suffix}</i>")
        if src := ab.get("displayed_link") or ab.get("link"):
            safe_src = html.escape(str(src), quote=True)
            safe_label = html.escape(str(src).split("//")[-1][:70])
            lines.append(f'<a href="{safe_src}">{safe_label}</a>')
        lines.append("")

    icons = ["🌸", "⚡", "💎", "🔥", "✨"]
    for index, result in enumerate(result_dict["results"], start=1):
        snippet = (result["snippet"] or "")[:max_snippet].replace("\n", " ").strip()
        if len(result["snippet"]) > max_snippet:
            snippet += "…"

        title = (result["title"] or "")[:85]
        if len(result["title"]) > 75:
            title = title[:72] + "…"

        safe_title = html.escape(title)
        safe_snippet = html.escape(snippet)
        safe_link = html.escape(str(result["link"]), quote=True)
        icon = icons[(index - 1) % len(icons)]

        lines.append(f"<b>{index}. {icon} {safe_title}</b>")
        if snippet:
            lines.append(f"   <i>{safe_snippet}</i>")
        lines.append(f'   <a href="{safe_link}">→ mehr / Karte</a>\n')

    lines.append("━━━━━━━━━━━━━━━━━━━")
    lines.append("<code>gesourced • Aura +1000 • wyld 🍜</code>")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_query = "beste koreanische Ramen Berlin 2026"
    result = web_search(test_query, num_results=6, country="de", language="de")
    print("=== Fuer User (HTML) ===")
    print(format_search_results_for_user(result))
    print("\n" + ("=" * 70) + "\n")
    print("=== Fuer Prompt ===")
    print(format_search_results_for_prompt(result))
