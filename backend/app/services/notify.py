"""Proof requests: when an official claims a fix, ask the people who reported
the issue - and citizens active nearby - for a fresh photo from the spot.

Delivery is an in-app inbox (``GET /api/notifications``) plus an optional
webhook (``NOTIFY_WEBHOOK_URL``) that a WhatsApp / SMS bridge can fan out.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import timedelta

from ..domain import AGENCY_INFO, VERIFY_REQUEST_LOOKBACK_DAYS, VERIFY_REQUEST_NEARBY_M, Agency, Verdict
from ..geo import bbox_for_radius, haversine_m
from ..privacy import mask_phones
from ..store import Store
from .common import new_id, now_iso, parse_iso, to_iso

log = logging.getLogger(__name__)

DISPUTED_VERDICTS = {Verdict.UNVERIFIED_DIFFERENT_LOCATION, Verdict.UNVERIFIED_NOT_FIXED, Verdict.UNVERIFIED_COSMETIC}


class Notifier:
    """Optional outbound channel. Without a webhook URL only the in-app inbox is used."""

    def __init__(self, webhook_url: str = "", timeout_s: float = 3.0):
        self.webhook_url = (webhook_url or "").strip()
        self.timeout_s = timeout_s

    def deliver(self, payload: dict) -> str:
        """POST one JSON payload; returns "sent", "disabled" or "failed: ...". Never raises."""
        if not self.webhook_url:
            return "disabled"
        req = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 - operator-configured URL
                return "sent" if 200 <= resp.status < 300 else f"failed: HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001 - delivery is best-effort
            log.warning("Notification webhook failed: %s", exc)
            return f"failed: {type(exc).__name__}"


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def nearby_reporters(store: Store, lat: float, lng: float, ts: str, exclude: set[str]) -> list[str]:
    """Citizens who reported anything close by recently (likely to pass the spot again)."""
    since = to_iso(parse_iso(ts) - timedelta(days=VERIFY_REQUEST_LOOKBACK_DAYS))
    found: set[str] = set()
    for r in store.reports_in_bbox(*bbox_for_radius(lat, lng, VERIFY_REQUEST_NEARBY_M), since=since, until=ts):
        rid = r.get("reporter_id")
        if rid and rid not in exclude and haversine_m(lat, lng, r["lat"], r["lng"]) <= VERIFY_REQUEST_NEARBY_M:
            found.add(rid)
    return sorted(found)


def request_verification(store: Store, cluster: dict, *, verdict: str, ts: str | None = None, notifier: Notifier | None = None) -> dict:
    """Queue "send a proof photo" requests after an official closure and log it on the timeline."""
    ts = ts or now_iso()
    reporters = sorted(store.reporter_ids_for_cluster(cluster["id"]))
    nearby = nearby_reporters(store, cluster["lat"], cluster["lng"], ts, set(reporters))
    agency = AGENCY_INFO[Agency(cluster["agency"])]["short"]
    title = mask_phones(cluster["title"])
    v = Verdict(verdict)
    if v in DISPUTED_VERDICTS:
        message = (
            f"{agency} marked \u201c{title}\u201d resolved, but the closure check flagged the after-photo "
            f"({v.value.replace('_', ' ').lower()}). A fresh photo from the spot settles it."
        )
    else:
        message = f"{agency} marked \u201c{title}\u201d resolved. Is it really fixed? Send a fresh photo from the spot."

    recipients = [(r, "reporter") for r in reporters] + [(r, "nearby") for r in nearby]
    for recipient, why in recipients:
        store.insert_notification(
            dict(
                id=new_id("N"),
                created_at=ts,
                cluster_id=cluster["id"],
                recipient=recipient,
                kind="verification_request",
                channel="in_app",
                message=message,
                status="unread",
                payload_json={"verdict": v.value, "reason": why},
            )
        )

    webhook = "disabled"
    if notifier is not None and recipients:
        webhook = notifier.deliver(
            {
                "type": "verification_request",
                "cluster_id": cluster["id"],
                "title": title,
                "ward": cluster["ward"],
                "lat": cluster["lat"],
                "lng": cluster["lng"],
                "agency": cluster["agency"],
                "verdict": v.value,
                "message": message,
                "recipients": [r for r, _ in recipients],
                "created_at": ts,
            }
        )

    if recipients:
        note = f"Asked {_count(len(reporters), 'reporter')} and {_count(len(nearby), 'nearby citizen')} for a fresh photo."
    else:
        note = "No reachable reporters on record; anyone nearby can submit a proof photo on this page."
    summary = {"recipients": len(recipients), "reporters": len(reporters), "nearby": len(nearby), "webhook": webhook}
    store.insert_event(
        dict(id=new_id("E"), cluster_id=cluster["id"], created_at=ts, type="verification_requested", actor="system", note=note, payload_json=summary)
    )
    return summary
