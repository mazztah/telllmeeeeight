# bot_state.py – FIXED: Kürzere Cooldowns, bessere Timeouts, Telegram-Responsive
# ═══════════════════════════════════════════════════════════════════════════════
# ÄNDERUNGEN:
#   ✅ Cooldown von 25s → 3s reduziert (nur bei echten Netzwerk-Fehlern)
#   ✅ Bei Timeouts: KEIN Blockieren, sofort erneut versuchen
#   ✅ Max 1 Attempt (schneller Fail-Fast statt 3x Blockieren)
#   ✅ httpx-Fallback nur bei Non-Timeout-Fehlern
# ═══════════════════════════════════════════════════════════════════════════════

import os
import logging
import asyncio
from pathlib import Path
from collections import defaultdict

import httpx
from telegram.request import HTTPXRequest
from telegram.ext import Application

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Environment
# ═══════════════════════════════════════════════════════════════════════════════

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except (PermissionError, OSError) as exc:
    # "/data" ist nur auf Plattformen mit gemountetem Persistent Storage
    # beschreibbar (z.B. HF Spaces). Auf Render & Co. ohne Disk existiert
    # "/data" nicht und kann vom non-root User nicht angelegt werden ->
    # Fallback auf einen lokalen Ordner neben dem Code.
    fallback_dir = Path(__file__).resolve().parent / "data"
    logger.warning(
        "DATA_DIR '%s' nicht beschreibbar (%s) – verwende Fallback '%s'",
        DATA_DIR, exc, fallback_dir,
    )
    DATA_DIR = fallback_dir
    DATA_DIR.mkdir(parents=True, exist_ok=True)

# Damit andere Module (brain.py, main.py), die DATA_DIR ebenfalls per
# os.getenv("DATA_DIR", "/data") berechnen, denselben Pfad verwenden.
os.environ["DATA_DIR"] = str(DATA_DIR)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("XAI_API_KEY")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN fehlt!")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY oder XAI_API_KEY fehlt!")

# ═══════════════════════════════════════════════════════════════════════════════
# SSL – einfach & sicher
# ═══════════════════════════════════════════════════════════════════════════════

def _find_ca_bundle():
    try:
        import certifi
        return certifi.where()
    except ImportError:
        pass
    for path in [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]:
        if os.path.exists(path):
            return path
    return None

_CA_BUNDLE = _find_ca_bundle()
if _CA_BUNDLE:
    os.environ.setdefault("SSL_CERT_FILE", _CA_BUNDLE)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _CA_BUNDLE)

# ═══════════════════════════════════════════════════════════════════════════════
# HTTPX-Einstellungen für HF Free Tier
# ═══════════════════════════════════════════════════════════════════════════════

_HF_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
_HF_LIMITS = httpx.Limits(max_connections=5, max_keepalive_connections=2)

# ═══════════════════════════════════════════════════════════════════════════════
# Groq Client – LAZY
# ═══════════════════════════════════════════════════════════════════════════════

_groq_client_instance = None

def get_groq_client():
    global _groq_client_instance
    if _groq_client_instance is None:
        from groq import Groq
        _groq_client_instance = Groq(
            api_key=GROQ_API_KEY,
            http_client=httpx.Client(timeout=_HF_TIMEOUT, limits=_HF_LIMITS, http2=False),
        )
        logger.info("✅ Groq Client initialisiert")
    return _groq_client_instance


class _LazyGroqClient:
    """Proxy-Objekt: verhält sich wie der echte Groq-Client."""
    def __getattr__(self, name):
        return getattr(get_groq_client(), name)

client = _LazyGroqClient()

# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Application
# ═══════════════════════════════════════════════════════════════════════════════

class RobustHTTPXRequest(HTTPXRequest):
    """Schlanker HTTP-Handler für HF Spaces."""
    def __init__(self):
        super().__init__(
            connect_timeout=8.0,
            read_timeout=12.0,
            write_timeout=10.0,
            pool_timeout=6.0,
            connection_pool_size=20,
        )


_application = None

def get_application():
    global _application
    if _application is None:
        _req = RobustHTTPXRequest()
        _application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .request(_req)
            .updater(None)
            .concurrent_updates(True)
            .build()
        )
        logger.info("✅ Telegram Application initialisiert")
    return _application

# Sofort initialisieren
application = get_application()

# ═══════════════════════════════════════════════════════════════════════════════
# Globale States
# ═══════════════════════════════════════════════════════════════════════════════

chat_histories: dict = {}
tts_enabled: dict = {}
edit_mode_active: dict = {}
last_edit_image_bytes: dict = {}
master_prompts: dict = {}
synced_brain: dict = {}
full_brain_synced: dict = {}
video_tasks: dict = {}
youtube_results: dict = {}
last_generated_code: dict = {}
awaiting_upload: set = set()
pending_voice_clones: dict = {}
pending_email_requests: dict = {}
pending_distortion: dict = {}
last_workflow_bundle: dict = {}
stream_active: dict = {}
vision_mode_active: dict = {}
selected_brain_deletes: dict = {}

# JobQueen Workspace State (persistent während der Server-Session)
# Browser: wir kumulieren Jobs über mehrere Suchläufe, damit Excel kumuliert.
jobqueen_state: dict = {}

# JobQueen Job-Index Default-Struktur (pro chat_id)
# - jobs_index: URL-or-ID dedupe -> Job-Objekt
# - query_history: zuletzt genutzte Queries (für UI/Debug)
# Hinweis: jobqueen_state selbst ist global in-memory; es bleibt nur während der Server/Workspace-Session persistent.

MAX_CHAT_MESSAGES = 40




# ═══════════════════════════════════════════════════════════════════════════════
# TIMEOUT KONSTANTEN
# ═══════════════════════════════════════════════════════════════════════════════

_TYPING_CONNECT_TIMEOUT = 2.0
_TYPING_READ_TIMEOUT = 2.5
_TYPING_WRITE_TIMEOUT = 2.5
_TYPING_POOL_TIMEOUT = 2.0

_SEND_CONNECT_TIMEOUT = 6.0
_SEND_READ_TIMEOUT = 15.0
_SEND_WRITE_TIMEOUT = 15.0
_SEND_POOL_TIMEOUT = 8.0

_EDIT_CONNECT_TIMEOUT = 6.0
_EDIT_READ_TIMEOUT = 15.0
_EDIT_WRITE_TIMEOUT = 15.0
_EDIT_POOL_TIMEOUT = 8.0

_FALLBACK_TIMEOUT = httpx.Timeout(connect=3.5, read=7.0, write=7.0, pool=3.0)
_FALLBACK_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=0)

# ═══════════════════════════════════════════════════════════════════════════════
# COOLDOWN SYSTEM – DEUTLICH REDUZIERT
# ═══════════════════════════════════════════════════════════════════════════════
# WICHTIG: Nur 3 Sekunden + nur für echte Fehler, NICHT für Timeouts
_SAFE_SEND_COOLDOWN_SECONDS = float(os.getenv("SAFE_SEND_COOLDOWN_SECONDS", "3"))
_safe_send_cooldown_until: dict[str, float] = defaultdict(float)
_safe_send_last_cooldown_log: dict[str, float] = defaultdict(float)

_SAFE_SEND_HTTPX_FALLBACK = str(os.getenv("SAFE_SEND_HTTPX_FALLBACK", "0")).strip().lower() in {"1", "true", "yes", "on"}
_SAFE_SEND_MAX_ATTEMPTS = 1  # Nur 1 Versuch! Schneller Fail-Fast statt Blockieren

_fallback_client = None

def _get_fallback_client() -> httpx.AsyncClient:
    global _fallback_client
    if _fallback_client is None:
        _fallback_client = httpx.AsyncClient(
            timeout=_FALLBACK_TIMEOUT,
            limits=_FALLBACK_LIMITS,
            http2=False,
            headers={"Connection": "close"},
        )
    return _fallback_client


def _is_timeout_like(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return True
    text = str(exc).lower()
    timeout_markers = ("timed out", "timeout", "read timed out", "pool timeout", "connect timeout")
    return any(marker in text for marker in timeout_markers)

# ═══════════════════════════════════════════════════════════════════════════════
# Typing Indicator
# ═══════════════════════════════════════════════════════════════════════════════

async def _send_typing(bot, chat_id: str):
    try:
        await asyncio.wait_for(
            bot.send_chat_action(
                chat_id=chat_id,
                action="typing",
                connect_timeout=_TYPING_CONNECT_TIMEOUT,
                read_timeout=_TYPING_READ_TIMEOUT,
                write_timeout=_TYPING_WRITE_TIMEOUT,
                pool_timeout=_TYPING_POOL_TIMEOUT,
            ),
            timeout=3.0,
        )
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
# httpx Fallback
# ═══════════════════════════════════════════════════════════════════════════════

async def _httpx_fallback(token: str, chat_id: str, text: str, parse_mode: str = None) -> bool:
    payload = {"chat_id": chat_id, "text": text[:4096]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    for attempt in range(1, 2):  # Nur 1 Versuch
        try:
            c = _get_fallback_client()
            r = await c.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
                timeout=7.0,
            )
            if r.status_code == 200:
                logger.info(f"✅ httpx-Fallback OK für {chat_id}")
                return True
            logger.error(f"httpx-Fallback {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"httpx-Fallback Exception für {chat_id}: {type(e).__name__} {e!r}")
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# safe_send_message – FIXED: Keine langen Blockaden mehr!
# ═══════════════════════════════════════════════════════════════════════════════

async def safe_send_message(bot, chat_id: str, text: str, **kwargs) -> object:
    """
    Robuste send_message – schnell & einfach:
    - Sofort typing-Indikator
    - 1x Versuch (kein 3x-Blockieren!)
    - Bei Timeout: Sofort Fehler, KEIN Cooldown
    - Bei anderen Fehlern: Kurzer 3s Cooldown + httpx-Fallback
    """
    token = bot.token
    text_trimmed = text[:4096] if text else "…"
    send_kwargs = dict(kwargs)
    send_kwargs.pop("safe_send_attempts", None)  # Ignoriert Custom Attempts
    send_kwargs.pop("allow_httpx_fallback", None)
    
    send_kwargs.setdefault("connect_timeout", _SEND_CONNECT_TIMEOUT)
    send_kwargs.setdefault("read_timeout", _SEND_READ_TIMEOUT)
    send_kwargs.setdefault("write_timeout", _SEND_WRITE_TIMEOUT)
    send_kwargs.setdefault("pool_timeout", _SEND_POOL_TIMEOUT)

    loop = asyncio.get_running_loop()
    now = loop.time()
    
    # Cooldown Check – nur bei echten Fehlern, NICHT bei Timeouts
    cooldown_until = _safe_send_cooldown_until.get(chat_id, 0.0)
    if cooldown_until > now:
        last_log = _safe_send_last_cooldown_log.get(chat_id, 0.0)
        if now - last_log > 10.0:  # Log nur alle 10s (nicht nervig)
            remain = max(0.0, cooldown_until - now)
            logger.info(f"safe_send cooldown aktiv für {chat_id} ({remain:.1f}s verbleibend)")
            _safe_send_last_cooldown_log[chat_id] = now
        return None

    await _send_typing(bot, chat_id)
    last_exception = None

    try:
        # NUR 1 Versuch!
        return await bot.send_message(chat_id=chat_id, text=text_trimmed, **send_kwargs)
    except Exception as e:
        last_exception = e
        is_timeout = _is_timeout_like(e)
        
        # 🔴 BEI TIMEOUT: KEIN COOLDOWN! Sofort Fehler. 
        # Erhöhtes Logging für Diagnose
        if is_timeout:
            logger.warning(f"send_message TIMEOUT für {chat_id} (read/write): {type(e).__name__}")
            return None
        
        # Bei anderen Fehlern: Kurzer Cooldown aktivieren
        logger.warning(f"send_message Fehler für {chat_id}: {type(e).__name__} {e!r}")
        _safe_send_cooldown_until[chat_id] = now + _SAFE_SEND_COOLDOWN_SECONDS
        
        # Non-retrybable Fehler → Abort
        non_retryable = (
            "chat not found",
            "bot was blocked",
            "forbidden",
            "can't parse entities",
            "message text is empty",
            "user is deactivated",
        )
        error_text = str(e).lower()
        if any(marker in error_text for marker in non_retryable):
            logger.warning(f"Non-retrybarer Fehler für {chat_id}: {error_text[:120]}")
            return None
        
        # httpx-Fallback versuchen (nur wenn aktiviert)
        if _SAFE_SEND_HTTPX_FALLBACK:
            logger.info(f"⚡ httpx-Fallback für {chat_id}")
            await _httpx_fallback(token, chat_id, text_trimmed, kwargs.get("parse_mode"))
        
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# safe_send_long – Chunked für lange Texte
# ═══════════════════════════════════════════════════════════════════════════════

async def safe_send_long(bot, chat_id: str, text: str, **kwargs) -> None:
    chunk_size = 4000
    if len(text) <= chunk_size:
        await safe_send_message(bot, chat_id, text, **kwargs)
        return
    parts = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    for i, part in enumerate(parts, 1):
        prefix = f"[{i}/{len(parts)}] " if len(parts) > 1 else ""
        await safe_send_message(bot, chat_id, prefix + part, **kwargs)
        if i < len(parts):
            await asyncio.sleep(0.2)  # Kleine Pause zwischen Chunks

# ═══════════════════════════════════════════════════════════════════════════════
# safe_edit_message
# ═══════════════════════════════════════════════════════════════════════════════

async def safe_edit_message(bot, chat_id: str, message_id: int, text: str, **kwargs) -> object:
    """Robustes edit_message_text mit kurzen Timeouts."""
    edit_kwargs = dict(kwargs)
    edit_kwargs.setdefault("connect_timeout", _EDIT_CONNECT_TIMEOUT)
    edit_kwargs.setdefault("read_timeout", _EDIT_READ_TIMEOUT)
    edit_kwargs.setdefault("write_timeout", _EDIT_WRITE_TIMEOUT)
    edit_kwargs.setdefault("pool_timeout", _EDIT_POOL_TIMEOUT)
    text_trimmed = text[:4096] if text else "…"

    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text_trimmed,
            **edit_kwargs,
        )
    except Exception as e:
        logger.debug(f"Edit fehlgeschlagen für {chat_id}:{message_id}: {type(e).__name__}")
        # Fallback: Neue Nachricht senden
        await safe_send_message(bot, chat_id, text_trimmed, parse_mode=kwargs.get("parse_mode"))
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# Graceful Shutdown
# ═══════════════════════════════════════════════════════════════════════════════

async def shutdown_application():
    try:
        global _fallback_client
        if _fallback_client is not None:
            await _fallback_client.aclose()
            _fallback_client = None
        if _application:
            await _application.shutdown()
        logger.info("✅ Bot shutdown abgeschlossen")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

