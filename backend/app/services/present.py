"""Presenters: turn storage rows into API-friendly JSON."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..config import get_settings
from ..domain import AGENCY_INFO, CATEGORY_LABELS, STATUS_LABELS, Agency, Category, ClusterStatus
from .common import is_sla_breached, now_utc, parse_iso


def media_url(name: str | None) -> str | None:
    if not name:
        return None
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/uploads/{name}"


def present_cluster(c: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    cat = Category(c["category"])
    status = ClusterStatus(c["status"])
    agency = Agency(c["agency"])
    out = {k: v for k, v in c.items() if not k.endswith("_json") and k != "_d"}
    out.update(
        {
            "category_label": CATEGORY_LABELS[cat],
            "status_label": STATUS_LABELS[status],
            "agency_label": AGENCY_INFO[agency]["label"],
            "agency_short": AGENCY_INFO[agency]["short"],
            "agency_info": AGENCY_INFO[agency],
            "hazards": c.get("hazards_json") or [],
            "score_breakdown": c.get("score_breakdown_json"),
            "context": c.get("context_json") or [],
            "repeat_failure": bool(c.get("repeat_failure")),
            "sla_breached": is_sla_breached(c, now),
            "hours_open": round((now - parse_iso(c["created_at"])).total_seconds() / 3600, 1),
            "hours_to_sla": round((parse_iso(c["sla_due_at"]) - now).total_seconds() / 3600, 1),
            "primary_photo_url": media_url(c.get("primary_photo_path")),
            "after_photo_url": media_url(c.get("after_photo_path")),
        }
    )
    return out


def present_report(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in r.items() if not k.endswith("_json")}
    out.update(
        {
            "category_label": CATEGORY_LABELS[Category(r["category"])],
            "hazards": r.get("hazards_json") or [],
            "evidence": r.get("evidence_json") or {},
            "extraction": r.get("raw_extraction_json"),
            "exif_gps": r.get("exif_gps_json"),
            "is_corroboration": bool(r.get("is_corroboration")),
            "photo_url": media_url(r.get("photo_path")),
            "audio_url": media_url(r.get("audio_path")),
        }
    )
    return out


def present_verification(v: dict[str, Any]) -> dict[str, Any]:
    out = {k: v2 for k, v2 in v.items() if not k.endswith("_json")}
    out.update(
        {
            "same_location": bool(v.get("same_location")),
            "issue_resolved": bool(v.get("issue_resolved")),
            "photo_url": media_url(v.get("photo_path")),
            "before_photo_urls": [media_url(p) for p in (v.get("before_photo_paths_json") or [])],
            "details": v.get("raw_json") or {},
        }
    )
    return out


def present_event(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in e.items() if not k.endswith("_json")}
    out["payload"] = e.get("payload_json") or {}
    return out
