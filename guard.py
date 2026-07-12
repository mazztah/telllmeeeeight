import re
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class GuardDecision:
    allowed: bool
    message: str
    retry_after: int = 0
    severity: str = "ok"


_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = {}
_BUCKET_LAST_SEEN: dict[tuple[str, str], float] = {}
_PRIVACY_MODE: set[str] = set()
_LAST_BUCKET_SWEEP = 0.0

DEFAULT_LIMITS = {
    "chat": (10, 30),
    "agent": (4, 60),
    "workflow": (3, 120),
    "image": (3, 60),
"mesh": (2, 300),  # 3D mesh heavy, 2 per 5min (test)
    "text3d": (2, 300),

    "video": (2, 120),
    "email_batch": (2, 1800),
}


SUSPICIOUS_PATTERNS = [
    (re.compile(r"\b(phish(?:ing)?|credential harvest|token stealer|malware)\b", re.IGNORECASE), "Das sieht nach Missbrauch oder Phishing aus."),
    (re.compile(r"\b(mass ?mail|bulk ?email|spam blast|cold email list)\b", re.IGNORECASE), "Massenuploads ohne saubere Prüfung blocke ich lieber."),
]


def _get_limit(action: str) -> tuple[int, int]:
    return DEFAULT_LIMITS.get(action, (6, 60))


def _prune_bucket(bucket: deque[float], now: float, window: int) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def _cleanup_buckets(now: float) -> None:
    global _LAST_BUCKET_SWEEP
    if now - _LAST_BUCKET_SWEEP < 120:
        return

    _LAST_BUCKET_SWEEP = now
    stale_keys = []
    for key, bucket in list(_RATE_BUCKETS.items()):
        _, action = key
        _, window = _get_limit(action)
        _prune_bucket(bucket, now, window)
        last_seen = _BUCKET_LAST_SEEN.get(key, 0.0)
        if not bucket and now - last_seen > max(window * 4, 600):
            stale_keys.append(key)

    for key in stale_keys:
        _RATE_BUCKETS.pop(key, None)
        _BUCKET_LAST_SEEN.pop(key, None)


def check_rate_limit(chat_id: str, action: str = "chat", limit: int | None = None, window_seconds: int | None = None) -> GuardDecision:
    if not chat_id:
        return GuardDecision(True, "")

    max_calls, window = _get_limit(action)
    max_calls = limit or max_calls
    window = window_seconds or window

    bucket_key = (str(chat_id), action)
    now = time.time()
    _cleanup_buckets(now)

    bucket = _RATE_BUCKETS.setdefault(bucket_key, deque())
    _BUCKET_LAST_SEEN[bucket_key] = now

    _prune_bucket(bucket, now, window)

    if len(bucket) >= max_calls:
        retry_after = max(1, int(window - (now - bucket[0])))
        return GuardDecision(
            allowed=False,
            message=f"Zu viele {action}-Anfragen gerade. Versuch es in {retry_after}s nochmal.",
            retry_after=retry_after,
            severity="rate_limit",
        )

    bucket.append(now)
    return GuardDecision(True, "")


def moderate_text(text: str) -> GuardDecision:
    content = (text or "").strip()
    if not content:
        return GuardDecision(True, "")

    if len(content) > 14000:
        return GuardDecision(False, "Die Nachricht ist zu lang. Schick mir lieber einen kleineren Block oder eine Datei.", severity="too_long")

    for pattern, message in SUSPICIOUS_PATTERNS:
        if pattern.search(content):
            return GuardDecision(False, message, severity="policy")

    return GuardDecision(True, "")


def can_process_text(chat_id: str, text: str, action: str = "chat") -> GuardDecision:
    rate = check_rate_limit(chat_id, action=action)
    if not rate.allowed:
        return rate
    return moderate_text(text)


def allow_email_batch(chat_id: str, recipient_count: int, subject: str, body: str) -> GuardDecision:
    rate = check_rate_limit(chat_id, action="email_batch")
    if not rate.allowed:
        return rate

    if recipient_count <= 0:
        return GuardDecision(False, "Keine Empfänger gefunden.", severity="validation")
    if recipient_count > 200:
        return GuardDecision(False, "Ich limitiere Batch-Mails aktuell auf 200 Empfänger pro Lauf.", severity="validation")

    content_decision = moderate_text(f"{subject}\n{body}")
    if not content_decision.allowed:
        return content_decision

    lowered = f"{subject}\n{body}".lower()
    spam_signals = ["garantiert reich", "100% gewinn", "jetzt sofort kaufen", "bonus nur heute"]
    if any(signal in lowered for signal in spam_signals):
        return GuardDecision(False, "Die Mail wirkt wie Spam-Marketing. Biiitte textlich nochmal sauberer formulieren.", severity="quality")

    return GuardDecision(True, "")


def toggle_privacy_mode(chat_id: str) -> bool:
    normalized = str(chat_id)
    if normalized in _PRIVACY_MODE:
        _PRIVACY_MODE.remove(normalized)
        return False
    _PRIVACY_MODE.add(normalized)
    return True


def is_privacy_mode_enabled(chat_id: str) -> bool:
    return str(chat_id) in _PRIVACY_MODE


def describe_guard_status(chat_id: str) -> str:
    privacy = "AN" if is_privacy_mode_enabled(chat_id) else "AUS"
    return (
        "Guard-Status\n"
        f"Privacy-Mode: {privacy}\n"
        "Rate-Limits aktiv fuer Chat, Agent, Workflows, Bild, Video und Email-Batches."
    )
