import asyncio
import csv
import json
import logging
import os
from io import BytesIO, StringIO

import pandas as pd
import PyPDF2
from docx import Document
from gtts import gTTS

from dv import (
    create_chart_from_df,
    create_docx_from_text,
    create_excel_from_data,
    create_pdf_from_text,
    extract_content,
    get_mime,
)

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 40000
MAX_TTS_CHARS = 4500

TARGET_ALIASES = {
    "txt": "text",
    "text": "text",
    "pdf": "pdf",
    "docx": "docx",
    "word": "docx",
    "excel": "excel",
    "xlsx": "excel",
    "sheet": "excel",
    "csv": "csv",
    "json": "json",
    "html": "html",
    "htm": "html",
    "markdown": "markdown",
    "md": "markdown",
    "mp3": "mp3",
    "audio": "mp3",
    "chart": "chart",
    "diagramm": "chart",
    "grafik": "chart",
    "py": "py",
    "python": "py",
}


def normalize_target(target: str | None) -> str:
    raw = (target or "").strip().lower()
    return TARGET_ALIASES.get(raw, raw)


def _safe_stem(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename or "converted"))[0].strip()
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return cleaned.strip("_") or "converted"


def _truncate_text(text: str, max_chars: int = MAX_SOURCE_CHARS) -> tuple[str, bool]:
    content = text or ""
    if len(content) <= max_chars:
        return content, False
    return content[:max_chars], True


def _read_text_file(file_path: str, max_chars: int = MAX_SOURCE_CHARS) -> tuple[str, bool]:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
        payload = handle.read(max_chars + 1)
    return _truncate_text(payload, max_chars=max_chars)


def _read_docx(file_path: str, max_chars: int = MAX_SOURCE_CHARS) -> tuple[str, bool]:
    doc = Document(file_path)
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
    return _truncate_text(text, max_chars=max_chars)


def _read_pdf(file_path: str, max_chars: int = MAX_SOURCE_CHARS) -> tuple[str, bool]:
    with open(file_path, "rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return _truncate_text(text, max_chars=max_chars)


def _read_table_as_text(file_path: str, mime: str, max_chars: int = MAX_SOURCE_CHARS) -> tuple[str, bool]:
    if "excel" in mime or "spreadsheet" in mime:
        dataframe = pd.read_excel(file_path)
    else:
        dataframe = pd.read_csv(file_path)
    return _truncate_text(dataframe.to_csv(index=False), max_chars=max_chars)


def _extract_source_text(file_path: str, max_chars: int = MAX_SOURCE_CHARS) -> tuple[str, bool]:
    mime = get_mime(file_path)

    try:
        if mime.startswith("text/"):
            return _read_text_file(file_path, max_chars=max_chars)
        if mime == "application/json":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                data = json.load(handle)
            return _truncate_text(json.dumps(data, indent=2, ensure_ascii=False), max_chars=max_chars)
        if mime == "application/pdf":
            return _read_pdf(file_path, max_chars=max_chars)
        if "wordprocessingml" in mime or mime.endswith("document"):
            return _read_docx(file_path, max_chars=max_chars)
        if mime in ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"):
            return _read_table_as_text(file_path, mime, max_chars=max_chars)
    except Exception as exc:
        logger.warning("Direkte Textextraktion fehlgeschlagen: %s", exc)

    return _truncate_text(extract_content(file_path, max_chars=max_chars), max_chars=max_chars)


def file_to_text(file_path: str, max_chars: int = MAX_SOURCE_CHARS) -> str:
    text, _ = _extract_source_text(file_path, max_chars=max_chars)
    return text


def _tabular_rows_from_text(text: str) -> list[list[str]]:
    cleaned_lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not cleaned_lines:
        return [[""]]

    sample = "\n".join(cleaned_lines[:10])
    delimiter = None

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = None

    rows = []
    for line in cleaned_lines:
        if delimiter and delimiter in line:
            rows.append([cell.strip() for cell in line.split(delimiter)])
        elif "\t" in line:
            rows.append([cell.strip() for cell in line.split("\t")])
        elif ";" in line:
            rows.append([cell.strip() for cell in line.split(";")])
        elif "," in line:
            rows.append([cell.strip() for cell in line.split(",")])
        else:
            rows.append([line])

    max_cols = max(len(row) for row in rows) if rows else 1
    return [row + [""] * (max_cols - len(row)) for row in rows]


def _chart_dataframe_from_text(text: str) -> pd.DataFrame:
    rows = _tabular_rows_from_text(text)

    if len(rows) >= 2 and len(rows[0]) >= 2:
        values = []
        labels = []
        for index, row in enumerate(rows):
            label = row[0] or f"Wert {index + 1}"
            raw_value = row[1] if len(row) > 1 else ""
            try:
                values.append(float(str(raw_value).replace(",", ".")))
                labels.append(label)
            except Exception:
                continue

        if values:
            return pd.DataFrame({"label": labels, "value": values})

    values = []
    for token in (text or "").replace(";", " ").replace(",", " ").split():
        try:
            values.append(float(token.replace(",", ".")))
        except Exception:
            continue

    if not values:
        values = [len((text or "").strip() or " ")]

    return pd.DataFrame(
        {
            "label": [f"Wert {index + 1}" for index in range(len(values))],
            "value": values,
        }
    )


def _build_result(
    *,
    success: bool,
    target: str,
    output: BytesIO | None = None,
    message: str = "",
    filename: str = "",
    mime_type: str | None = None,
) -> dict:
    if output is not None:
        output.seek(0)
    return {
        "success": success,
        "target": target,
        "output": output,
        "message": message,
        "filename": filename,
        "mime_type": mime_type or "application/octet-stream",
    }


def convert_text_content(
    text: str,
    target: str,
    source_name: str = "clipboard.txt",
    instruction: str | None = None,
) -> dict:
    target = normalize_target(target)
    stem = _safe_stem(source_name)
    base_text = text or ""
    working_text = f"{instruction}\n\n{base_text}".strip() if instruction else base_text

    try:
        if target == "text":
            buffer = BytesIO(working_text.encode("utf-8"))
            return _build_result(True, target, buffer, "Text als TXT erstellt.", f"{stem}.txt", "text/plain")

        if target == "py":
            buffer = BytesIO(working_text.encode("utf-8"))
            return _build_result(True, target, buffer, "Text als Python-Datei erstellt.", f"{stem}.py", "text/x-python")

        if target == "markdown":
            markdown_text = working_text if working_text.startswith("#") else f"# {stem}\n\n{working_text}"
            buffer = BytesIO(markdown_text.encode("utf-8"))
            return _build_result(True, target, buffer, "Text als Markdown erstellt.", f"{stem}.md", "text/markdown")

        if target == "html":
            escaped = working_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_document = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                f"<title>{stem}</title></head><body><pre>{escaped}</pre></body></html>"
            )
            buffer = BytesIO(html_document.encode("utf-8"))
            return _build_result(True, target, buffer, "Text als HTML erstellt.", f"{stem}.html", "text/html")

        if target == "pdf":
            buffer = create_pdf_from_text(working_text, title=f"{stem}.pdf")
            return _build_result(True, target, buffer, "Text als PDF erstellt.", f"{stem}.pdf", "application/pdf")

        if target == "docx":
            buffer = create_docx_from_text(working_text, title=stem)
            return _build_result(
                True,
                target,
                buffer,
                "Text als DOCX erstellt.",
                f"{stem}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

        if target == "json":
            try:
                parsed = json.loads(base_text)
            except Exception:
                parsed = {"content": base_text}
            payload = json.dumps(parsed, indent=2, ensure_ascii=False)
            buffer = BytesIO(payload.encode("utf-8"))
            return _build_result(True, target, buffer, "JSON-Datei erstellt.", f"{stem}.json", "application/json")

        if target == "csv":
            rows = _tabular_rows_from_text(base_text)
            csv_buffer = StringIO()
            writer = csv.writer(csv_buffer)
            writer.writerows(rows)
            buffer = BytesIO(csv_buffer.getvalue().encode("utf-8"))
            return _build_result(True, target, buffer, "CSV-Datei erstellt.", f"{stem}.csv", "text/csv")

        if target == "excel":
            rows = _tabular_rows_from_text(base_text)
            columns = [f"col_{index + 1}" for index in range(len(rows[0]))]
            buffer = create_excel_from_data(rows, columns, title=f"{stem}.xlsx")
            return _build_result(
                True,
                target,
                buffer,
                "Excel-Datei erstellt.",
                f"{stem}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        if target == "chart":
            df = _chart_dataframe_from_text(base_text)
            buffer = create_chart_from_df(df, title=f"Chart aus {stem}")
            return _build_result(True, target, buffer, "Chart erstellt.", f"{stem}.png", "image/png")

        if target == "mp3":
            spoken_text = (working_text or "").strip() or "Leer"
            truncated = len(spoken_text) > MAX_TTS_CHARS
            tts = gTTS(text=spoken_text[:MAX_TTS_CHARS], lang="de", slow=False)
            buffer = BytesIO()
            tts.write_to_fp(buffer)
            buffer.seek(0)
            message = "MP3-Sprachausgabe erstellt."
            if truncated:
                message += f" Hinweis: Der Text wurde fuer TTS auf {MAX_TTS_CHARS} Zeichen begrenzt."
            return _build_result(True, target, buffer, message, f"{stem}.mp3", "audio/mpeg")

        return _build_result(False, target, message=f"Zielformat '{target}' wird noch nicht unterstuetzt.", filename="")

    except Exception as exc:
        logger.exception("convert_text_content Fehler")
        return _build_result(
            success=False,
            target=target,
            message=f"Fehler bei der Konvertierung: {str(exc)[:180]}",
            filename="",
        )


async def universal_convert(
    file_path: str,
    target: str,
    instruction: str = None,
    chat_id: str = None,
) -> dict:
    target = normalize_target(target)
    filename = os.path.basename(file_path)
    mime = get_mime(file_path)

    try:
        # Early mime/target check
        supported_mimes = ["text/", "application/pdf", "application/vnd.openxmlformats-officedocument", "text/csv", "application/json"]
        if not any(mime.startswith(s) for s in supported_mimes) and target != "chart":
            return _build_result(
                False, target, 
                message=f"Dateityp '{mime}' für '{target}' nicht optimal unterstützt. Probiere Text/PDF/DOCX/CSV.",
                filename=""
            )

        if target == "chart" and mime in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
        ):
            dataframe = pd.read_excel(file_path) if "excel" in mime else pd.read_csv(file_path)
            buffer = create_chart_from_df(dataframe, title=f"Chart aus {filename}")
            return _build_result(
                True,
                target,
                buffer,
                "Chart erstellt.",
                f"{_safe_stem(filename)}_chart.png",
                "image/png",
            )

        source_text, was_truncated = _extract_source_text(file_path, max_chars=MAX_SOURCE_CHARS)
        result = convert_text_content(
            text=source_text,
            target=target,
            source_name=filename,
            instruction=instruction,
        )

        if was_truncated:
            result["message"] = (
                f"{result.get('message', '').strip()} Hinweis: Die Quelle wurde auf {MAX_SOURCE_CHARS} Zeichen begrenzt."
            ).strip()

        return result

    except ValueError as exc:
        logger.warning(f"ValueError universal_convert {filename} -> {target}: {exc}")
        return _build_result(
            False, target,
            f"Ungültiges Format '{target}'. Unterstützt: text/py/md/html/pdf/docx/json/csv/excel/chart/mp3",
            ""
        )
    except ImportError as exc:
        logger.error(f"Import-Fehler {target}: {exc}")
        return _build_result(
            False, target, 
            f"Fehlende Library für '{target}' (z.B. python-docx für DOCX, openpyxl für Excel). pip install ...",
            ""
        )
    except Exception as exc:
        logger.exception(f"universal_convert({filename}->{target}): {exc}")
        error_detail = str(exc).lower()
        if "gtts" in error_detail:
            msg = "MP3 TTS: Kein Internet/gTTS-Limit. Text kürzen oder später versuchen."
        elif "pdf" in error_detail or "pypdf" in error_detail:
            msg = "PDF: PyPDF2-Fehler. Text zu lang oder beschädigt."
        elif "docx" in error_detail:
            msg = "DOCX: python-docx fehlt. pip install python-docx"
        elif "pandas" in error_detail or "openpyxl" in error_detail:
            msg = "Excel/CSV: pandas/openpyxl fehlt. pip install pandas openpyxl"
        elif "chart" in target.lower():
            msg = "Chart: Keine Daten gefunden. Tabellenformat prüfen."
        else:
            msg = f"Konvertierung '{target}' fehlgeschlagen: {str(exc)[:120]}"
        return _build_result(False, target, msg, "")


async def universal_convert_text(
    text: str,
    target: str,
    source_name: str = "clipboard.txt",
    instruction: str = None,
    chat_id: str = None,
) -> dict:
    return convert_text_content(text, target, source_name=source_name, instruction=instruction)


def convert_any_to_any(file_path: str, target: str) -> BytesIO | str:
    try:
        result = asyncio.run(universal_convert(file_path, target, chat_id=None))
        if result["success"] and isinstance(result["output"], BytesIO):
            return result["output"]
        return result["message"]
    except Exception:
        return "Konvertierung fehlgeschlagen."


def file_to_context(entry: dict) -> str:
    title = entry.get("title", "Unbenannte Datei")
    metadata = entry.get("metadata", {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    preview = metadata.get("extracted_preview", "") if isinstance(metadata, dict) else ""
    content = entry.get("content", "")[:2500]
    return f"[BRAIN FILE: {title} | ID: {entry.get('id')}]\nVorschau: {preview}\nInhalt-Auszug: {content}"
