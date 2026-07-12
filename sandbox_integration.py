# sandbox_integration.py – Verbessertes Mounting für Hugging Face Spaces
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Importiere die Sandbox-Mini-App
from sandbox_mini_app import app as sandbox_app

def mount_sandbox(main_app: FastAPI):
    """
    Mountet die Sandbox mit robuster Static-File-Suche.
    """
    # Mögliche Pfade für static-Ordner
    static_candidates = [
        Path("/data/static"),
        Path.cwd() / "static",
        Path(__file__).parent / "static",
        Path("/home/user/app/static"),
        Path("/opt/render/project/src/static"),
    ]

    sandbox_static_dir = None

    for candidate in static_candidates:
        if candidate.exists():
            css_dir = candidate / "css"
            js_dir = candidate / "js"
            if css_dir.exists() and js_dir.exists():
                sandbox_static_dir = candidate
                logger.info(f"✅ Sandbox Static-Ordner gefunden: {candidate}")
                break

    # Static Files mounten
    if sandbox_static_dir:
        main_app.mount(
            "/sandbox/static",
            StaticFiles(directory=str(sandbox_static_dir)),
            name="sandbox_static"
        )
        logger.info(f"✅ Static Files gemountet aus: {sandbox_static_dir}")
    else:
        logger.error("❌ Kein static-Ordner mit css/js gefunden!")

    # Sandbox App mounten
    main_app.mount("/sandbox", sandbox_app, name="sandbox")
    logger.info("✅ Sandbox Mini-App unter /sandbox gemountet")

    return main_app