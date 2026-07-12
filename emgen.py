import base64
import logging
import os
import re
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pandas as pd
from PyPDF2 import PdfReader
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    GMAIL_LIBS_AVAILABLE = True
except Exception:
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None
    HttpError = Exception
    GMAIL_LIBS_AVAILABLE = False

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]
GOOGLE_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", "http://localhost")
CREDENTIALS_PATH = Path(os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json"))
TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", "token_gmail.json"))
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}")

gmail_service = None
pending_oauth_states: dict[str, str] = {}
pending_email_batches: dict[str, dict[str, Any]] = {}


def gmail_backend_status() -> str:
    if GMAIL_LIBS_AVAILABLE:
        return "Gmail API bereit"
    return "Gmail API Bibliotheken fehlen"


def parse_email_batch_command(text: str) -> tuple[str | None, str | None]:
    raw = (text or "").strip()
    for command in ("/mailbatch", "/emailbatch"):
        if raw.lower().startswith(command):
            raw = raw[len(command) :].strip()
            break

    if "||" not in raw:
        return None, None

    subject, body = raw.split("||", 1)
    subject = subject.strip()
    body = body.strip()
    if not subject or not body:
        return None, None
    return subject, body


def _extract_auth_code(payload: str) -> tuple[str | None, str | None]:
    raw = (payload or "").strip()
    if not raw:
        return None, None

    if raw.startswith("http://") or raw.startswith("https://"):
        match = re.search(r"[?&]code=([^&]+)", raw)
        state_match = re.search(r"[?&]state=([^&]+)", raw)
        code = unquote(match.group(1)) if match else None
        state = unquote(state_match.group(1)) if state_match else None
        return code, state

    return unquote(raw), None


def _ensure_credentials_file() -> tuple[bool, str]:
    if not GMAIL_LIBS_AVAILABLE:
        return False, "Die Gmail-API-Bibliotheken fehlen. Bitte requirements.txt installieren."
    if CREDENTIALS_PATH.exists():
        return True, ""
    return False, f"Die Datei '{CREDENTIALS_PATH}' fehlt. Lade den Desktop-App OAuth Client als credentials.json hoch."


def load_gmail_service() -> bool:
    global gmail_service
    if not GMAIL_LIBS_AVAILABLE or not TOKEN_PATH.exists():
        return False

    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    except Exception as exc:
        logger.warning("Gespeicherter Gmail-Token konnte nicht geladen werden: %s", exc)
        return False

    try:
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            else:
                return False

        gmail_service = build("gmail", "v1", credentials=creds)
        return True
    except Exception as exc:
        logger.warning("Gmail-Service konnte nicht geladen werden: %s", exc)
        return False


async def start_gmail_auth(chat_id: str) -> str:
    ok, error = _ensure_credentials_file()
    if not ok:
        return error
    if load_gmail_service():
        return "Gmail ist bereits autorisiert und einsatzbereit."

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    pending_oauth_states[str(chat_id)] = state
    return (
        "Gmail-Autorisierung gestartet.\n"
        "1. Oeffne den Link im Browser.\n"
        "2. Melde dich an und bestaetige den Zugriff.\n"
        "3. Kopiere danach die komplette Redirect-URL oder nur den Code und sende ihn mit /gmail_code.\n\n"
        f"{auth_url}"
    )


async def finish_gmail_auth(chat_id: str, auth_payload: str) -> str:
    expected_state = pending_oauth_states.get(str(chat_id))
    ok, error = _ensure_credentials_file()
    if not ok:
        return error

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    code, returned_state = _extract_auth_code(auth_payload)
    if not code:
        return "Ich konnte aus deiner Nachricht keinen OAuth-Code lesen."

    if expected_state and returned_state and expected_state != returned_state:
        return "Der OAuth-State passt nicht zur gestarteten Session. Bitte /gmail_auth neu starten."

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        pending_oauth_states.pop(str(chat_id), None)

        global gmail_service
        gmail_service = build("gmail", "v1", credentials=creds)
        return "Gmail ist jetzt autorisiert und einsatzbereit."
    except Exception as exc:
        logger.exception("Gmail-Auth fehlgeschlagen")
        return f"Gmail-Auth fehlgeschlagen: {str(exc)[:240]}"


def _service():
    global gmail_service
    if gmail_service is None and not load_gmail_service():
        return None
    return gmail_service


def _is_valid_email(email: str) -> bool:
    return bool(email and EMAIL_REGEX.fullmatch(email.strip()))


def parse_email_list(file_path: str) -> list[dict[str, str]]:
    lowered = file_path.lower()
    results: list[dict[str, str]] = []

    if lowered.endswith((".xlsx", ".xls")):
        dataframe = pd.read_excel(file_path, dtype=str)
    elif lowered.endswith(".csv"):
        dataframe = pd.read_csv(file_path, dtype=str, sep=None, engine="python")
    elif lowered.endswith(".tsv"):
        dataframe = pd.read_csv(file_path, dtype=str, sep="\t")
    elif lowered.endswith(".pdf"):
        reader = PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        emails = EMAIL_REGEX.findall(text)
        return [{"email": email, "name": ""} for email in sorted(set(emails))]
    else:
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        emails = EMAIL_REGEX.findall(text)
        return [{"email": email, "name": ""} for email in sorted(set(emails))]

    mail_column = None
    for candidate in ["email", "e-mail", "mail", "Email", "E-Mail"]:
        if candidate in dataframe.columns:
            mail_column = candidate
            break

    if mail_column:
        for _, row in dataframe.iterrows():
            email = str(row.get(mail_column, "")).strip()
            if not _is_valid_email(email):
                continue
            name = str(row.get("name") or row.get("Name") or row.get("Vorname") or "").strip()
            results.append({"email": email, "name": name})
    else:
        seen = set()
        for _, row in dataframe.iterrows():
            for cell in row.astype(str).tolist():
                normalized = cell.strip()
                if normalized in seen or not _is_valid_email(normalized):
                    continue
                seen.add(normalized)
                results.append({"email": normalized, "name": ""})

    unique: list[dict[str, str]] = []
    seen_emails = set()
    for item in results:
        email = item["email"].lower()
        if email in seen_emails:
            continue
        seen_emails.add(email)
        unique.append(item)
    return unique


def _render_body(body: str, recipient: dict[str, str]) -> str:
    rendered = body or ""
    for key, value in recipient.items():
        rendered = rendered.replace(f"{{{key}}}", value or "")
        rendered = rendered.replace(f"{{{key.lower()}}}", value or "")
        rendered = rendered.replace(f"{{{key.upper()}}}", value or "")
    return rendered


def create_mime_message(to_email: str, subject: str, body: str) -> dict[str, str]:
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def create_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Batch senden", callback_data="email|confirm")],
            [InlineKeyboardButton("Abbrechen", callback_data="email|cancel")],
        ]
    )


def _create_gmail_draft(subject: str, body: str, recipient: dict[str, str]) -> str | None:
    service = _service()
    if service is None:
        return None

    payload = {"message": create_mime_message(recipient["email"], subject, _render_body(body, recipient))}
    draft = service.users().drafts().create(userId="me", body=payload).execute()
    return draft.get("id")


async def prepare_email_batch(chat_id: str, file_path: str, subject: str, body: str) -> dict[str, Any]:
    recipients = parse_email_list(file_path)
    if not recipients:
        return {"success": False, "message": "Keine gueltigen Email-Adressen gefunden."}

    preview_recipient = recipients[0]
    preview_body = _render_body(body, preview_recipient)
    draft_id = _create_gmail_draft(subject, body, preview_recipient)

    pending_email_batches[str(chat_id)] = {
        "recipients": recipients,
        "subject": subject,
        "body": body,
        "source_file": file_path,
        "draft_id": draft_id,
    }

    draft_hint = f"Gmail-Draft-ID: {draft_id}" if draft_id else "Kein Gmail-Draft angelegt (wahrscheinlich noch nicht autorisiert)."
    preview_text = (
        f"Email-Batch vorbereitet\n"
        f"Empfaenger: {len(recipients)}\n"
        f"Betreff: {subject}\n"
        f"{draft_hint}\n\n"
        f"Vorschau fuer {preview_recipient['email']}:\n\n"
        f"{preview_body[:1200]}\n\n"
        f"Batch jetzt senden?"
    )

    return {
        "success": True,
        "message": preview_text,
        "keyboard": create_preview_keyboard(),
        "count": len(recipients),
    }


async def confirm_and_send_batch(chat_id: str) -> str:
    batch = pending_email_batches.get(str(chat_id))
    service = _service()
    if not batch:
        return "Kein wartender Email-Batch vorhanden."
    if service is None:
        return "Gmail ist noch nicht autorisiert. Bitte zuerst /gmail_auth ausfuehren."

    sent = 0
    failed = 0

    for recipient in batch["recipients"]:
        payload = create_mime_message(
            recipient["email"],
            batch["subject"],
            _render_body(batch["body"], recipient),
        )
        try:
            service.users().messages().send(userId="me", body=payload).execute()
            sent += 1
        except HttpError as exc:
            failed += 1
            logger.warning("Email an %s fehlgeschlagen: %s", recipient["email"], exc)

    pending_email_batches.pop(str(chat_id), None)
    return f"Batch abgeschlossen. Erfolgreich: {sent}, Fehler: {failed}."


def cancel_batch(chat_id: str) -> str:
    if pending_email_batches.pop(str(chat_id), None):
        return "Email-Batch abgebrochen."
    return "Kein wartender Email-Batch vorhanden."
