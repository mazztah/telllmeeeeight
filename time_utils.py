# time_utils.py – Zentrale Datum/Uhrzeit-Quelle fuer ALLE Bots/Agents
#
# Warum dieses Modul existiert:
# Der normale Telegram-Chat (bot_ai.py) lief bisher ueber das Modell
# "groq/compound", das bei Groq server-seitig eingebaute Tools (u.a.
# Websuche) hat - daher konnte er sich zufaellig ein korrektes Datum
# "erschummeln". /agent und /superagent (agent.py:run_agent_loop) laufen
# ueber qwen/llama/gpt-Modelle OHNE eingebaute Live-Tools, und nirgends
# im Code wurde dem Modell das aktuelle Datum/die Uhrzeit mitgeteilt.
#
# Loesung: EINE Funktion, die vor jedem LLM-Call einen frischen, exakten
# Zeitstempel als System-Message injiziert. Das ist zuverlässiger als
# "hoffen", dass das Modell selbst auf die Idee kommt, ein Tool
# aufzurufen - und funktioniert unabhängig vom verwendeten Modell.

from __future__ import annotations

import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9, sollte hier nicht vorkommen
    ZoneInfo = None  # type: ignore

# Standard-Zeitzone fuer den Bot. Ueber ENV BOT_TIMEZONE ueberschreibbar,
# falls der Bot mal fuer eine andere Region laeuft.
DEFAULT_TIMEZONE = os.getenv("BOT_TIMEZONE", "Europe/Berlin")

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def now_local(tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def format_datetime_de(dt: datetime) -> str:
    weekday = _WEEKDAYS_DE[dt.weekday()]
    month = _MONTHS_DE[dt.month - 1]
    return f"{weekday}, {dt.day}. {month} {dt.year}, {dt.strftime('%H:%M')} Uhr"


def current_datetime_context(tz_name: str = DEFAULT_TIMEZONE) -> str:
    """
    Liefert einen fertigen System-Prompt-Satz mit dem exakten, aktuellen
    Datum/Uhrzeit. IMMER frisch berechnet - nie gecacht, nie Teil der
    persistierten Chat-History (siehe bot_ai.py/agent.py: wird bei jedem
    Aufruf neu an die Nachrichtenliste angehaengt, aber nicht mit
    gespeichert).
    """
    dt = now_local(tz_name)
    return (
        f"[AKTUELLES DATUM & UHRZEIT] Heute ist {format_datetime_de(dt)} "
        f"({tz_name}, ISO: {dt.isoformat(timespec='minutes')}). "
        f"Nutze IMMER diesen Wert, wenn nach Datum, Uhrzeit, Wochentag oder "
        f"'heute'/'jetzt' gefragt wird - rate NIEMALS und verlasse dich NICHT "
        f"auf dein Trainings-Wissen dafuer."
    )


def current_datetime_tool_result(tz_name: str = DEFAULT_TIMEZONE) -> str:
    """Fuer das explizite get_current_datetime-Agent-Tool (bot_utils.py) -
    falls ein Modell trotz System-Kontext lieber aktiv nachfragt."""
    dt = now_local(tz_name)
    return (
        f"{format_datetime_de(dt)} ({tz_name}). "
        f"ISO 8601: {dt.isoformat(timespec='seconds')}"
    )
