"""WhatsApp Cloud API intake (PRD: "PWA or WhatsApp webhook", OQ-1). Optional.

Citizens report exactly as in the PWA - a voice note, a photo and/or a short
text, plus a shared location - but WhatsApp delivers them as separate
messages. Each sender therefore has a short-lived draft (table
``wa_sessions``, expires after 30 minutes). As soon as a draft has a location
and some evidence, its media is downloaded, checked against the PWA's limits
and run through the normal :func:`~app.services.intake.ingest` pipeline; the
citizen gets the ticket back as a reply.

Privacy (PRD phone-masking NFR): phone numbers are never stored or logged. A
sender is known only by ``wa:`` + a salted SHA-256 of the number, which is
also the report's ``reporter_id``. WhatsApp message ids embed the sender's
number, so they are hashed too before being kept for de-duplication.

Network calls go through :class:`GraphClient` (standard library only). Tests
swap it via ``app.state.whatsapp_client`` or by monkeypatching
:func:`build_client`.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import io
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from ..ai.audio import probe_duration_s
from ..ai.base import Media
from ..config import Settings
from ..domain import CATEGORY_LABELS, Category
from ..store import Store
from .common import now_utc, parse_iso, to_iso
from .intake import DuplicateSubmission, IntakeResult, LowConfidence, NotCivicIssue, ingest
from .present import present_cluster

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com"
USER_AGENT = "CivicPulse/0.1 (WhatsApp intake)"
MB = 1024 * 1024
JSON_LIMIT = 64 * 1024  # Graph API JSON responses are tiny

SESSION_TTL = timedelta(minutes=30)
SEEN_TTL = timedelta(days=7)  # Meta retries undelivered webhooks for up to 7 days
PROMPT_QUIET = timedelta(seconds=60)  # one "share your location" per burst of messages
MAX_TEXT_CHARS = 2000
MAX_REPLY_CHARS = 4096  # WhatsApp's limit for a text message
# Same checks as the PWA upload path (routers/api.py).
ALLOWED_IMAGE_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
AUDIO_TOLERANCE_S = 1.5
MEDIA_ID_RE = re.compile(r"[A-Za-z0-9_.\-]{1,128}")
WA_ID_RE = re.compile(r"\d{5,20}")


# --------------------------------------------------------------- Graph API --
class GraphError(Exception):
    """A Cloud API call failed (network, HTTP status or unexpected response)."""


class MediaTooLarge(GraphError):
    """The media is bigger than the client's download cap."""


class WhatsAppClient(Protocol):
    """What the intake needs from the Cloud API (see :class:`GraphClient`)."""

    def fetch_media(self, media_id: str) -> tuple[bytes, str]: ...

    def send_text(self, to: str, body: str) -> bool: ...


_LONG_DIGITS = re.compile(r"\d{7,}")


def _redact(text: str) -> str:
    """Mask long digit runs (phone numbers) before anything reaches the logs."""
    return _LONG_DIGITS.sub("\u2026", text)


def _graph_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        err = json.loads(exc.read(8192) or b"{}").get("error") or {}
        detail = f" ({err.get('code')}) {err.get('message') or ''}".rstrip() if err else ""
    except Exception:  # noqa: BLE001 - the error body only decorates a log line
        detail = ""
    return _redact(detail[:300])


class GraphClient:
    """Just enough of the WhatsApp Cloud API: download incoming media and send text replies."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str = "",
        graph_version: str = "v21.0",
        *,
        timeout_s: float = 10.0,
        max_media_bytes: int = 16 * MB,
        base_url: str = GRAPH_URL,
    ):
        self.access_token = (access_token or "").strip()
        self.phone_number_id = (phone_number_id or "").strip()
        self.graph_version = (graph_version or "v21.0").strip(" /")
        self.timeout_s = timeout_s
        self.max_media_bytes = max_media_bytes
        self.base_url = base_url.rstrip("/")

    def _url(self, *parts: str) -> str:
        return "/".join([self.base_url, self.graph_version, *(urllib.parse.quote(p, safe="") for p in parts)])

    def _call(self, req: urllib.request.Request, limit: int) -> tuple[bytes, str]:
        """One authenticated request -> (body, content type). Raises GraphError."""
        # Unredirected: the token is never forwarded if a media URL redirects elsewhere.
        req.add_unredirected_header("Authorization", f"Bearer {self.access_token}")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 - Graph API or a Graph-issued media URL
                body = resp.read(limit + 1)
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise GraphError(f"HTTP {exc.code}{_graph_error_detail(exc)}") from None
        except Exception as exc:  # noqa: BLE001 - network errors, timeouts, malformed URLs
            raise GraphError(_redact(f"{type(exc).__name__}: {exc}")) from None
        if len(body) > limit:
            raise MediaTooLarge(f"response larger than {limit} bytes")
        return body, ctype

    def _downloadable(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        # Plain HTTP only when the client itself points at a local test server.
        schemes = {"https", "http"} if self.base_url.startswith("http://") else {"https"}
        return parts.scheme in schemes and bool(parts.netloc)

    def fetch_media(self, media_id: str) -> tuple[bytes, str]:
        """Download an incoming photo or voice note as (bytes, mime type). Raises GraphError."""
        if not self.access_token:
            raise GraphError("WHATSAPP_ACCESS_TOKEN is not set")
        raw, _ = self._call(urllib.request.Request(self._url(media_id)), JSON_LIMIT)
        try:
            info = json.loads(raw)
            url, mime = str(info["url"]), str(info.get("mime_type") or "")
            size = int(info.get("file_size") or 0)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise GraphError("unexpected media metadata") from None
        if size > self.max_media_bytes:
            raise MediaTooLarge(f"media is {size} bytes")
        if not self._downloadable(url):
            raise GraphError("refusing a non-HTTPS media URL")
        # The media URL is short-lived (~5 min), so fetch it straight away.
        data, ctype = self._call(urllib.request.Request(url), self.max_media_bytes)
        return data, mime or ctype.split(";")[0].strip() or "application/octet-stream"

    def send_text(self, to: str, body: str) -> bool:
        """Send a text reply. Best effort: logs and returns False on any failure, never raises."""
        if not (self.access_token and self.phone_number_id):
            log.warning("WhatsApp reply not sent: set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID")
            return False
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body[:MAX_REPLY_CHARS]}}
        try:
            req = urllib.request.Request(
                self._url(self.phone_number_id, "messages"),
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            self._call(req, JSON_LIMIT)
        except Exception as exc:  # noqa: BLE001 - replies are best effort
            log.warning("WhatsApp reply failed: %s", _redact(str(exc)))
            return False
        return True


def build_client(settings: Settings) -> GraphClient:
    # The hard download cap sits above both per-type limits so those produce the friendly message.
    cap = (max(settings.max_image_mb, settings.max_audio_mb) + 1) * MB
    return GraphClient(
        settings.whatsapp_access_token,
        settings.whatsapp_phone_number_id,
        settings.whatsapp_graph_version,
        max_media_bytes=cap,
    )


def client_for(app: Any) -> WhatsAppClient:
    """The app's Cloud API client: ``app.state.whatsapp_client`` when set (tests), else one built from settings."""
    client = getattr(app.state, "whatsapp_client", None)
    return client if client is not None else build_client(app.state.settings)


# ----------------------------------------------------- webhook auth / identity --
def tokens_match(given: str | None, expected: str) -> bool:
    """Constant-time comparison of a shared secret (an empty secret never matches)."""
    return bool(expected) and hmac.compare_digest((given or "").encode(), expected.encode())


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Check Meta's ``X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the raw body>`` in constant time."""
    algo, _, given = (header or "").strip().partition("=")
    if algo.lower() != "sha256" or not given:
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), given.strip().lower().encode())


@functools.cache
def warn_unsigned() -> None:
    """Log once per process that webhook calls are not authenticated."""
    log.warning("WHATSAPP_APP_SECRET is not set: accepting unsigned WhatsApp webhook calls. Set it in production.")


def _salt(settings: Settings) -> str:
    return settings.whatsapp_app_secret or settings.whatsapp_verify_token


def sender_key(settings: Settings, phone: str) -> str:
    """Pseudonymous reporter id for a WhatsApp number: never the number itself (PRD phone masking)."""
    digits = re.sub(r"\D", "", phone or "")
    return "wa:" + hashlib.sha256((_salt(settings) + digits).encode()).hexdigest()[:16]


def _message_key(settings: Settings, message_id: str) -> str:
    # WhatsApp message ids ("wamid.<base64>") embed the sender's number: keep only a salted hash.
    return hashlib.sha256(f"{_salt(settings)}|{message_id}".encode()).hexdigest()[:32]


# ------------------------------------------------------------------ drafts --
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS wa_sessions (
        sender TEXT PRIMARY KEY,          -- 'wa:' + salted SHA-256 of the phone number, never the number
        updated_at TEXT NOT NULL,
        text TEXT,
        photo_media_id TEXT,
        audio_media_id TEXT,
        lat REAL,
        lng REAL,
        prompted_at TEXT                  -- when we last asked for the location
    )""",
    "CREATE INDEX IF NOT EXISTS idx_wa_sessions_updated ON wa_sessions(updated_at)",
    # Salted hashes of message ids already handled (Meta may deliver a webhook more than once).
    "CREATE TABLE IF NOT EXISTS wa_seen_messages (id TEXT PRIMARY KEY, seen_at TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_wa_seen_messages_seen ON wa_seen_messages(seen_at)",
)


@dataclass
class Draft:
    """A sender's report in progress."""

    sender: str
    text: str = ""
    photo_media_id: str | None = None
    audio_media_id: str | None = None
    lat: float | None = None
    lng: float | None = None
    prompted_at: str | None = None

    @property
    def location(self) -> tuple[float, float] | None:
        return (self.lat, self.lng) if self.lat is not None and self.lng is not None else None

    @property
    def has_evidence(self) -> bool:
        return bool(self.text.strip() or self.photo_media_id or self.audio_media_id)

    def add_text(self, more: str) -> None:
        more = more.strip()
        if more:
            self.text = f"{self.text}\n{more}".strip()[:MAX_TEXT_CHARS]

    def clear_evidence(self) -> None:
        self.text, self.photo_media_id, self.audio_media_id, self.prompted_at = "", None, None, None


def ensure_schema(store: Store) -> None:
    with store._lock, store.conn:
        for statement in SCHEMA:
            store.conn.execute(statement)


def purge_expired(store: Store, now: datetime) -> None:
    with store._lock, store.conn:
        store.conn.execute("DELETE FROM wa_sessions WHERE updated_at < ?", [to_iso(now - SESSION_TTL)])
        store.conn.execute("DELETE FROM wa_seen_messages WHERE seen_at < ?", [to_iso(now - SEEN_TTL)])


def load_draft(store: Store, sender: str, now: datetime) -> Draft:
    with store._lock:
        row = store.conn.execute(
            "SELECT updated_at, text, photo_media_id, audio_media_id, lat, lng, prompted_at FROM wa_sessions WHERE sender = ?",
            [sender],
        ).fetchone()
    if row is None:
        return Draft(sender)
    updated_at, text, photo, audio, lat, lng, prompted_at = row
    if parse_iso(updated_at) < now - SESSION_TTL:
        return Draft(sender)  # expired: start over
    return Draft(sender, text or "", photo, audio, lat, lng, prompted_at)


def save_draft(store: Store, draft: Draft, now: datetime) -> None:
    with store._lock, store.conn:
        store.conn.execute(
            "INSERT OR REPLACE INTO wa_sessions (sender, updated_at, text, photo_media_id, audio_media_id, lat, lng, prompted_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [draft.sender, to_iso(now), draft.text or None, draft.photo_media_id, draft.audio_media_id, draft.lat, draft.lng, draft.prompted_at],
        )


def delete_draft(store: Store, sender: str) -> None:
    with store._lock, store.conn:
        store.conn.execute("DELETE FROM wa_sessions WHERE sender = ?", [sender])


def _first_delivery(store: Store, message_key: str, now: datetime) -> bool:
    with store._lock, store.conn:
        cur = store.conn.execute("INSERT OR IGNORE INTO wa_seen_messages (id, seen_at) VALUES (?, ?)", [message_key, to_iso(now)])
    return cur.rowcount == 1


# ----------------------------------------------------------------- replies --
EMERGENCY_MESSAGE = "\U0001f6a8 If anyone is hurt or in immediate danger, call 112 now. CivicPulse does not dispatch emergency services."
LOCATION_HOWTO = "tap \U0001f4ce (or + on iPhone) \u2192 Location \u2192 Send your current location"
ASK_EVIDENCE = "\U0001f4cd Location saved. Now send a voice note, a photo or a short description of the problem and I'll file the report."
UNSUPPORTED = (
    "Sorry, I can only read voice notes, photos, text and shared locations (live location isn't supported). "
    "Please send one of those."
)
CANCELLED = "\U0001f5d1\ufe0f Draft discarded. Send a voice note, photo or text whenever you want to report a problem."
THANKS = "\U0001f64f You're welcome! Send a voice note, photo or text any time to report another problem."
BAD_LOCATION = f"That location didn't come through. Please share it again: {LOCATION_HOWTO}."
NOT_CIVIC = (
    "\U0001f914 This doesn't look like a civic problem I can file. Please send a clearer photo or describe it "
    "(e.g. \u201cdeep pothole near the bus stop\u201d). Your location is saved."
)
LOW_CONFIDENCE = (
    "\U0001f914 I couldn't tell what the problem is. Please send a clearer photo or a short description "
    "(e.g. \u201cgarbage dumped at the school gate\u201d). Your location is saved."
)
FAILED = "Sorry, something went wrong on our side and the report wasn't filed. Please try again in a few minutes."

HELP_WORDS = {"hi", "hii", "hello", "helo", "hey", "help", "start", "menu", "info", "namaste", "namaskar", "namaskara"}
CANCEL_WORDS = {"cancel", "reset", "stop", "clear", "discard"}
THANKS_WORDS = {
    "thanks", "thank you", "thankyou", "thx", "ty", "ok", "okay", "k", "dhanyavada", "dhanyavadagalu", "shukriya",
    "\U0001f44d", "\U0001f64f", "\U0001f44c",
}
SILENT_TYPES = {"reaction", "system", "ephemeral"}


def welcome_text(settings: Settings) -> str:
    limit = f" (up to {settings.max_audio_s} s)" if settings.max_audio_s > 0 else ""
    return (
        "\U0001f44b Namaskara! This is CivicPulse: report a civic problem in Bengaluru and follow it until the fix is verified.\n\n"
        f"1\ufe0f\u20e3 Send a voice note in any language{limit}, a photo or a short description.\n"
        f"2\ufe0f\u20e3 Share the location: {LOCATION_HOWTO}.\n\n"
        "I'll route it to the responsible agency and reply with a tracking ID. Send \u201ccancel\u201d to start over.\n"
        "\U0001f6a8 Emergency? Call 112."
    )


def cluster_link(settings: Settings, cluster_id: str) -> str | None:
    base = settings.public_base_url.strip().rstrip("/")
    return f"{base}/clusters/{cluster_id}" if base else None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _join(items: list[str]) -> str:
    if not items:
        return "message"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _ask_location_text(draft: Draft) -> str:
    got = [name for name, have in (("voice note", draft.audio_media_id), ("photo", draft.photo_media_id), ("description", draft.text.strip())) if have]
    return f"\U0001f44d Got your {_join(got)}. Now share where it is: {LOCATION_HOWTO}."


def _is_emergency(extraction: Any) -> bool:
    return bool(getattr(extraction, "is_emergency", False))


def ticket_text(res: IntakeResult, settings: Settings) -> str:
    """Reply for a filed report: ticket ID, new or merged, category, severity, agencies, link."""
    cluster = res.cluster
    cid = cluster["id"]
    lines = [EMERGENCY_MESSAGE, ""] if getattr(res, "emergency", False) or _is_emergency(res.extraction) else []
    try:
        c = present_cluster(cluster)
        if res.merged:
            reports = _plural(int(c.get("report_count") or 1), "report")
            citizens = _plural(int(c.get("reporter_count") or 1), "citizen")
            lines.append(f"\u2705 Added to an existing issue: *{cid}* (now {reports} from {citizens})")
        else:
            lines.append(f"\u2705 Report filed: *{cid}* (new issue)")
        lines.append(f"Category: {c.get('category_label') or cluster.get('category')}")
        lines.append(f"Severity: {str(c.get('severity_level') or cluster.get('max_severity')).capitalize()}")
        lines.append(f"Responsible: {c.get('agency_label') or cluster.get('agency')}")
        if c.get("secondary_agency_label"):
            lines.append(f"Also responsible: {c['secondary_agency_label']}")
    except Exception:  # noqa: BLE001 - the report is filed; never lose the ticket ID over formatting
        log.exception("WhatsApp: could not format the reply for %s", cid)
        lines.append(f"\u2705 Report filed: *{cid}*")
    if getattr(res, "reopened", False):
        lines.append("\u26a0\ufe0f This issue had been marked resolved; your report disputes that closure.")
    if getattr(res, "repeat_failure", False):
        lines.append("\u26a0\ufe0f This spot was fixed before and has failed again, so it is flagged as a repeat failure.")
    link = cluster_link(settings, cid)
    lines.append(f"Track it: {link}" if link else f"Keep the ID {cid} to follow up.")
    return "\n".join(lines)


def duplicate_text(exc: DuplicateSubmission, settings: Settings) -> str:
    prev = exc.previous
    cluster_id = prev.get("cluster_id") or "?"
    try:
        label = CATEGORY_LABELS[Category(prev["category"])].lower()
    except (KeyError, ValueError):
        label = "issue"
    elapsed = max(0, int(settings.duplicate_window_s - exc.retry_after_s))
    ago = "a moment ago" if elapsed < 60 else f"{elapsed // 60} min ago"
    lines = [f"\u2139\ufe0f You already reported this {label} {ago} ({cluster_id}). One report per person is enough."]
    link = cluster_link(settings, cluster_id)
    if link:
        lines.append(f"Share it so neighbours can tap \u201cI see this too\u201d: {link}")
    return "\n".join(lines)


def _reply(client: WhatsAppClient, to: str, body: str) -> None:
    try:
        client.send_text(to, body)
    except Exception as exc:  # noqa: BLE001 - a misbehaving client must not break intake
        log.warning("WhatsApp reply raised %s", type(exc).__name__)


# ------------------------------------------------------------------- media --
class _MediaProblem(Exception):
    """User-facing reason a photo / voice note was not accepted."""


def _download(client: WhatsAppClient, media_id: str, what: str, icon: str, max_mb: int) -> tuple[bytes, str]:
    too_big = _MediaProblem(f"{icon} That {what} is too large (max {max_mb} MB). Please send a smaller one.")
    failed = _MediaProblem(f"{icon} I couldn't download your {what}. Please send it again.")
    try:
        data, mime = client.fetch_media(media_id)
    except MediaTooLarge:
        raise too_big from None
    except Exception as exc:  # noqa: BLE001 - any client failure means "please resend"
        log.warning("WhatsApp %s download failed: %s", what, _redact(str(exc)))
        raise failed from None
    if not data:
        raise failed
    if len(data) > max_mb * MB:
        raise too_big
    return data, mime


def _image_format(data: bytes) -> str:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return (im.format or "").upper()
    except Exception:  # noqa: BLE001 - anything Pillow cannot open is rejected
        return ""


def _fetch_photo(client: WhatsAppClient, media_id: str, settings: Settings) -> Media:
    data, mime = _download(client, media_id, "photo", "\U0001f4f7", settings.max_image_mb)
    if _image_format(data) not in ALLOWED_IMAGE_FORMATS:
        raise _MediaProblem("\U0001f4f7 I couldn't read that image. Please send a JPEG, PNG or WebP photo.")
    return Media(data, mime or "image/jpeg", "whatsapp-photo")


def _fetch_audio(client: WhatsAppClient, media_id: str, settings: Settings) -> Media:
    data, mime = _download(client, media_id, "voice note", "\U0001f399\ufe0f", settings.max_audio_mb)
    audio = Media(data, mime or "audio/ogg", "whatsapp-voice-note")  # voice notes are audio/ogg (opus)
    if settings.max_audio_s > 0:
        duration = probe_duration_s(audio)
        if duration is not None and duration > settings.max_audio_s + AUDIO_TOLERANCE_S:
            raise _MediaProblem(
                f"\U0001f399\ufe0f Your voice note is {duration:.0f} s long; please keep it under {settings.max_audio_s} s and send it again."
            )
    return audio


def _fetch_evidence(draft: Draft, settings: Settings, client: WhatsAppClient) -> tuple[Media | None, Media | None, list[str]]:
    """Download and check the draft's media. A rejected item is dropped from the draft."""
    photo = audio = None
    problems: list[str] = []
    if draft.photo_media_id:
        try:
            photo = _fetch_photo(client, draft.photo_media_id, settings)
        except _MediaProblem as exc:
            problems.append(str(exc))
            draft.photo_media_id = None
    if draft.audio_media_id:
        try:
            audio = _fetch_audio(client, draft.audio_media_id, settings)
        except _MediaProblem as exc:
            problems.append(str(exc))
            draft.audio_media_id = None
    return photo, audio, problems


# -------------------------------------------------------------- processing --
# Drafts are read-modify-write, so messages from one sender are handled one at a time.
# The service runs as a single instance (SQLite), so in-process lock striping is enough.
_LOCKS = tuple(threading.Lock() for _ in range(64))


def _lock_for(sender: str) -> threading.Lock:
    return _LOCKS[hash(sender) % len(_LOCKS)]


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _command(text: str) -> str:
    """Normalise a short message for keyword matching ("Hi!" -> "hi")."""
    return re.sub(r"[\s!.?,]+", " ", text.lower()).strip()


def _coords(location: Any) -> tuple[float, float] | None:
    loc = _obj(location)
    try:
        lat, lng = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None  # also rejects NaN / inf


def _message_values(payload: dict, settings: Settings) -> Iterator[dict]:
    """The ``value`` objects of a webhook delivery that carry messages for our number."""
    if payload.get("object", "whatsapp_business_account") != "whatsapp_business_account":
        return
    for entry in _list(payload.get("entry")):
        for raw_change in _list(_obj(entry).get("changes")):
            change = _obj(raw_change)
            value = _obj(change.get("value"))
            if change.get("field", "messages") != "messages" or not value.get("messages"):
                continue  # e.g. delivery receipts ("statuses")
            number_id = str(_obj(value.get("metadata")).get("phone_number_id") or "")
            if settings.whatsapp_phone_number_id and number_id and number_id != settings.whatsapp_phone_number_id:
                log.info("WhatsApp: ignoring messages addressed to another business number")
                continue
            yield value


def process_payload(
    payload: dict,
    *,
    settings: Settings,
    store: Store,
    ai: Any,
    client: WhatsAppClient,
    now: datetime | None = None,
) -> int:
    """Handle one webhook delivery (runs as a background task). Returns the number of messages handled; never raises."""
    now = now or now_utc()
    try:
        ensure_schema(store)
        purge_expired(store, now)
        values = list(_message_values(payload, settings))
    except Exception:  # noqa: BLE001
        log.exception("WhatsApp: could not process a webhook delivery")
        return 0
    handled = 0
    for value in values:
        for msg in _list(value.get("messages")):
            if not isinstance(msg, dict):
                continue
            try:
                if _handle_message(msg, settings=settings, store=store, ai=ai, client=client, now=now):
                    handled += 1
            except Exception:  # noqa: BLE001 - one bad message must not stop the rest
                log.exception("WhatsApp: failed to handle a %.20r message", msg.get("type"))
    return handled


def _handle_message(msg: dict, *, settings: Settings, store: Store, ai: Any, client: WhatsAppClient, now: datetime) -> bool:
    wa_id = str(msg.get("from") or "").strip()  # used only to reply; never stored or logged
    if not WA_ID_RE.fullmatch(wa_id):
        return False
    sender = sender_key(settings, wa_id)
    msg_id = str(msg.get("id") or "")
    if msg_id and not _first_delivery(store, _message_key(settings, msg_id), now):
        log.info("WhatsApp: ignoring a redelivered message from %s", sender)
        return False
    kind = str(msg.get("type") or "")
    log.info("WhatsApp: %.20r message from %s", kind, sender)
    if kind in SILENT_TYPES:
        return True
    if kind == "request_welcome":  # the citizen opened the chat for the first time
        _reply(client, wa_id, welcome_text(settings))
        return True

    with _lock_for(sender):
        draft = load_draft(store, sender, now)
        if kind == "text":
            body = str(_obj(msg.get("text")).get("body") or "").strip()
            word = _command(body)
            if word in CANCEL_WORDS:
                delete_draft(store, sender)
                _reply(client, wa_id, CANCELLED)
                return True
            if word in HELP_WORDS:
                _reply(client, wa_id, welcome_text(settings))
                return True
            if not body or word in THANKS_WORDS:
                if not (draft.has_evidence or draft.location):
                    _reply(client, wa_id, THANKS)
                return True  # mid-draft "ok" / "thanks": nothing to add
            draft.add_text(body)
        elif kind in ("image", "audio", "document"):
            media = _obj(msg.get(kind))
            media_id = str(media.get("id") or "")
            is_photo_file = kind != "document" or str(media.get("mime_type") or "").startswith("image/")
            if not (MEDIA_ID_RE.fullmatch(media_id) and is_photo_file):
                _reply(client, wa_id, UNSUPPORTED)
                return True
            if kind == "audio":
                draft.audio_media_id = media_id
            else:
                draft.photo_media_id = media_id  # the latest photo wins
            draft.add_text(str(media.get("caption") or ""))
        elif kind == "location":
            coords = _coords(msg.get("location"))
            if coords is None:
                _reply(client, wa_id, BAD_LOCATION)
                return True
            draft.lat, draft.lng = coords
        else:
            _reply(client, wa_id, UNSUPPORTED)
            return True
        _advance(draft, wa_id, settings=settings, store=store, ai=ai, client=client, now=now)
    return True


def _advance(draft: Draft, wa_id: str, *, settings: Settings, store: Store, ai: Any, client: WhatsAppClient, now: datetime) -> None:
    """File the draft if it is complete, otherwise save it and ask for what is missing."""
    location = draft.location
    if location and draft.has_evidence:
        _file_report(draft, location, wa_id, settings=settings, store=store, ai=ai, client=client, now=now)
    elif draft.has_evidence:
        ask = draft.prompted_at is None or now - parse_iso(draft.prompted_at) >= PROMPT_QUIET
        if ask:
            draft.prompted_at = to_iso(now)
        save_draft(store, draft, now)
        if ask:
            _reply(client, wa_id, _ask_location_text(draft))
    else:
        save_draft(store, draft, now)
        _reply(client, wa_id, ASK_EVIDENCE)


def _file_report(
    draft: Draft,
    location: tuple[float, float],
    wa_id: str,
    *,
    settings: Settings,
    store: Store,
    ai: Any,
    client: WhatsAppClient,
    now: datetime,
) -> None:
    photo, audio, problems = _fetch_evidence(draft, settings, client)
    if problems:
        save_draft(store, draft, now)  # the rejected media is dropped; location and the rest wait for a retry
        _reply(client, wa_id, "\n".join(problems))
        return
    try:
        res = ingest(
            store,
            ai,
            lat=location[0],
            lng=location[1],
            uploads_dir=settings.uploads_path,
            text=draft.text.strip() or None,
            audio=audio,
            photo=photo,
            reporter_id=draft.sender,
            duplicate_window_s=settings.duplicate_window_s,
            duplicate_radius_m=settings.duplicate_radius_m,
            # WhatsApp strips photo metadata for everyone, so missing EXIF says nothing here.
            expect_exif=False,
        )
    except DuplicateSubmission as exc:
        delete_draft(store, draft.sender)
        reply = duplicate_text(exc, settings)
    except (NotCivicIssue, LowConfidence) as exc:
        # Keep the location: a clearer photo or description is filed straight away.
        draft.clear_evidence()
        save_draft(store, draft, now)
        reply = NOT_CIVIC if isinstance(exc, NotCivicIssue) else LOW_CONFIDENCE
        reason = getattr(exc, "reason", "")
        if isinstance(exc, LowConfidence) and isinstance(reason, str) and reason.strip():
            reply += f"\n({reason.strip()[:200]})"
        if _is_emergency(exc.extraction):
            reply = f"{EMERGENCY_MESSAGE}\n\n{reply}"
    except Exception:  # noqa: BLE001
        log.exception("WhatsApp: filing a report from %s failed", draft.sender)
        draft.clear_evidence()
        save_draft(store, draft, now)
        reply = FAILED
    else:
        delete_draft(store, draft.sender)
        log.info("WhatsApp: report %s from %s filed on %s", res.report["id"], draft.sender, res.cluster["id"])
        reply = ticket_text(res, settings)
    _reply(client, wa_id, reply)
