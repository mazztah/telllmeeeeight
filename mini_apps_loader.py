"""
mini_apps_loader.py – Zentrale Verwaltung aller Mini-Apps & Spiele
═══════════════════════════════════════════════════════════════════
Ausgelagert aus main.py um:
  • Startzeit auf HF Spaces zu reduzieren (schwere Imports: OpenGL, matplotlib)
  • main.py schlanker und wartbarer zu machen
  • Einzelne Apps können unabhängig deaktiviert/aktiviert werden

Nutzung in main.py:
    from mini_apps_loader import mount_mini_apps
    mount_mini_apps(app)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# LAZY IMPORTS – jede App wird einzeln mit try/except geladen
# Fehler in einer App blockieren NICHT den Bot-Start.
# ═══════════════════════════════════════════════════════════════════════════════

def _try_import(module_name: str, attr: str = "app"):
    """Importiert ein Mini-App-Modul sicher. Gibt None zurück bei Fehler."""
    try:
        mod = __import__(module_name)
        return getattr(mod, attr, None)
    except ImportError as e:
        logger.warning(f"⚠️  {module_name} nicht verfügbar: {e}")
    except Exception as e:
        logger.error(f"❌ {module_name} Import-Fehler: {e}")
    return None


# ─── Kern-Apps (höhere Priorität) ─────────────────────────────────────────────
diagnose_app      = _try_import("diagnose_app")
scanner_mini_app  = _try_import("scanner_mini_app")
sandbox_mini_app  = _try_import("sandbox_mini_app")

# ─── Feature-Apps ─────────────────────────────────────────────────────────────
voice_mini_app    = _try_import("voice_mini_app")
lightmeter_mini_app = _try_import("lightmeter_mini_app")
trichome_mini_app = _try_import("trichome_mini_app")
plantid_mini_app  = _try_import("plantid_mini_app")
archive_mini_app  = _try_import("archive_mini_app")
papersearch_mini_app = _try_import("papersearch_mini_app")

# ─── Spiele / Entertainment ────────────────────────────────────────────────────
shellgame_mini_app = _try_import("shellgame_mini_app")
dragon_mini_app   = _try_import("dragon_mini_app")
spacewar_mini_app = _try_import("space_war_mini_app")   # Modulname ≠ Routen-Name
chess_app         = _try_import("chess_mini_app")


# ═══════════════════════════════════════════════════════════════════════════════
# MOUNT-TABELLE
# ═══════════════════════════════════════════════════════════════════════════════

# Format: (route_prefix, app_instance, log_name)
_APPS: list[tuple[str, Optional[object], str]] = [
    # Kern
    ("/diagnose",    diagnose_app,         "diagnose_app"),
    ("/scanner",     scanner_mini_app,     "scanner_mini_app"),
    ("/sandbox",     sandbox_mini_app,     "sandbox_mini_app"),
    # Features
    ("/voice",       voice_mini_app,       "voice_mini_app"),
    ("/lightmeter",  lightmeter_mini_app,  "lightmeter_mini_app"),
    ("/trichome",    trichome_mini_app,    "trichome_mini_app"),
    ("/plantid",     plantid_mini_app,     "plantid_mini_app"),
    ("/archive",     archive_mini_app,     "archive_mini_app"),
    ("/papersearch", papersearch_mini_app, "papersearch_mini_app"),
    # Spiele
    ("/shellgame",   shellgame_mini_app,   "shellgame_mini_app"),
    ("/dragon",      dragon_mini_app,      "dragon_mini_app"),
    ("/spacewar",    spacewar_mini_app,    "spacewar_mini_app"),
    ("/chess",       chess_app,            "chess_mini_app"),
]


def mount_mini_apps(fastapi_app) -> int:
    """
    Mountet alle verfügbaren Mini-Apps auf die FastAPI-Instanz.
    Gibt die Anzahl erfolgreich gemounteter Apps zurück.
    """
    mounted = 0
    for route, mini_app, name in _APPS:
        if mini_app is None:
            continue
        try:
            fastapi_app.mount(route, mini_app)
            logger.info(f"{name} mounted")
            mounted += 1
        except Exception as e:
            logger.warning(f"Mount {name} fehlgeschlagen: {e}")

    logger.info(f"✅ Mini-Apps: {mounted}/{len(_APPS)} erfolgreich gemountet")
    return mounted


def get_loaded_apps() -> dict:
    """Gibt ein Dict {name: bool} zurück – nützlich für /health Endpoint."""
    return {
        name.replace("_mini_app", "").replace("_app", ""): (app is not None)
        for _, app, name in _APPS
    }
