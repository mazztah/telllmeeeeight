import base64
import contextlib
import io
import json
import logging
import time
import traceback
from io import BytesIO
from typing import Any, Dict, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image
from gtts import gTTS

from dv import create_chart_from_df, create_docx_from_text, create_excel_from_data, create_pdf_from_text

logger = logging.getLogger(__name__)

SAFE_GLOBALS = {
    "__builtins__": {
        "print": print,
        "range": range,
        "len": len,
        "sum": sum,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "str": str,
        "int": int,
        "float": float,
        "list": list,
        "dict": dict,
        "set": set,
        "tuple": tuple,
        "enumerate": enumerate,
        "zip": zip,
        "sorted": sorted,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
    },
    "BytesIO": BytesIO,
    "base64": base64,
    "json": json,
    "pd": pd,
    "plt": plt,
    "Image": Image,
    "gTTS": gTTS,
    "create_pdf_from_text": create_pdf_from_text,
    "create_docx_from_text": create_docx_from_text,
    "create_excel_from_data": create_excel_from_data,
    "create_chart_from_df": create_chart_from_df,
}


def _normalize_result_file(file_payload: Any) -> Tuple[BytesIO, str] | None:
    if not file_payload:
        return None

    buffer = None
    filename = None

    if isinstance(file_payload, tuple) and len(file_payload) >= 2:
        buffer, filename = file_payload[0], file_payload[1]
    elif isinstance(file_payload, dict):
        buffer = file_payload.get("buffer") or file_payload.get("bytes") or file_payload.get("content")
        filename = file_payload.get("filename") or file_payload.get("name")

    if not filename:
        return None

    if isinstance(buffer, bytes):
        buffer = BytesIO(buffer)
    elif isinstance(buffer, str):
        buffer = BytesIO(buffer.encode("utf-8"))

    if not hasattr(buffer, "read"):
        return None

    buffer.seek(0)
    return buffer, str(filename)


async def execute_python(code: str, chat_id: str = None) -> Dict[str, Any]:
    output_buffer = io.StringIO()
    error = None
    plot_bytes = None
    result = None
    result_file = None

    try:
        with contextlib.redirect_stdout(output_buffer):
            local_vars: Dict[str, Any] = {}
            exec(code, SAFE_GLOBALS.copy(), local_vars)

            if plt.get_fignums():
                buf = BytesIO()
                plt.savefig(buf, format="png", dpi=200, bbox_inches="tight")
                buf.seek(0)
                plot_bytes = buf
                plt.close("all")

            result = local_vars.get("result") or "✅ Code erfolgreich ausgeführt."
            result_file = _normalize_result_file(local_vars.get("result_file"))

    except Exception as exc:
        error = traceback.format_exc(limit=8)
        logger.error("CodeInterpreter Python Fehler: %s", exc)
    finally:
        plt.close("all")

    return {
        "success": error is None,
        "output": output_buffer.getvalue().strip(),
        "error": error,
        "plot": plot_bytes,
        "result": result,
        "file": result_file,
    }


def generate_html_file(html_code: str, title: str = "Mini App") -> Tuple[BytesIO, str]:
    full_html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body {{ margin:0; padding:20px; background:#2a0044; color:#ffccff; font-family:system-ui; }}
        canvas, button {{ margin:10px 0; }}
    </style>
</head>
<body>
    {html_code}
    <script>
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
    </script>
</body>
</html>"""

    buffer = BytesIO(full_html.encode("utf-8"))
    buffer.seek(0)
    return buffer, f"{title.lower().replace(' ', '_')}.html"


async def run_code(
    code: str,
    language: str = "python",
    chat_id: str = None,
    save_to_brain: bool = True,
) -> Dict:
    if language == "python":
        result = await execute_python(code, chat_id)
        return {
            **result,
            "language": "python",
        }

    if language == "html":
        buffer, filename = generate_html_file(code, "Mini_App")

        if save_to_brain and chat_id:
            try:
                from brain import save_text

                await save_text(chat_id, code, title=f"Mini-App {time.strftime('%H:%M')}")
                logger.info("HTML-Code für Chat %s ins Brain gespeichert", chat_id)
            except Exception as exc:
                logger.warning("Speichern ins Brain fehlgeschlagen: %s", exc)

        return {
            "success": True,
            "output": "✅ HTML Mini-App generiert",
            "error": None,
            "plot": None,
            "language": "html",
            "file": (buffer, filename),
        }

    return {
        "success": False,
        "error": "Unbekannte Sprache. Nur python oder html erlaubt.",
        "language": language,
        "plot": None,
        "file": None,
    }
