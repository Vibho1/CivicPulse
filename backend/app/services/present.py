"""Presenters: turn storage rows into API-friendly JSON.

Everything here is public output, so it applies the PRD privacy rules: phone
numbers in free text are masked, citizens appear under a stable pseudonym (their
device id would otherwise let anyone read their proof-request inbox), and voice
notes are only linked when PUBLIC_AUDIO is on.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from ..config import get_settings
from ..domain import (
    AGENCY_INFO,
    AGENCY_PRD_CODE,
    CATEGORY_LABELS,
    STATUS_LABELS,
    Agency,
    Category,
    ClusterStatus,
    repair_quality,
    severity_level,
)
from ..privacy import mask_deep, mask_fields
from .common import is_sla_breached, now_utc, parse_iso

CLUSTER_TEXT = ("title", "description", "landmark", "resolution_note", "agency_reason", "secondary_agency_reason")
REPORT_TEXT = (
    "text", "transcript", "transcript_english", "description", "title", "landmark", "size_estimate",
    "agency_reason", "secondary_agency_reason", "extraction", "parsed",
)
# Timeline events whose actor is a citizen (shown under a pseudonym).
CITIZEN_EVENT_TYPES = {"reported", "merged", "corroborated", "citizen_verification", "escalation_drafted", "external_ref_recorded"}
NON_PERSON_ACTORS = {"citizen", "system", "ai", "rule", "seed", "official"}


def media_url(name: str | None) -> str | None:
    if not name:
        return None
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/uploads/{name}"


def pseudonym(reporter_id: str | None) -> str | None:
    """Stable public alias for a reporter id ('citizen-1a2b3c')."""
    if not reporter_id or reporter_id in NON_PERSON_ACTORS:
        return reporter_id
    return "citizen-" + hashlib.sha256(reporter_id.encode("utf-8")).hexdigest()[:6]


def present_cluster(c: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    cat = Category(c["category"])
    status = ClusterStatus(c["status"])
    agency = Agency(c["agency"])
    secondary = Agency(c["secondary_agency"]) if c.get("secondary_agency") else None
    out = {k: v for k, v in c.items() if not k.endswith("_json") and k != "_d"}
    out.update(
        {
            "category_label": CATEGORY_LABELS[cat],
            "status_label": STATUS_LABELS[status],
            "agency_label": AGENCY_INFO[agency]["label"],
            "agency_short": AGENCY_INFO[agency]["short"],
            "agency_code": AGENCY_PRD_CODE[agency],
            "agency_info": AGENCY_INFO[agency],
            "secondary_agency_label": AGENCY_INFO[secondary]["label"] if secondary else None,
            "secondary_agency_short": AGENCY_INFO[secondary]["short"] if secondary else None,
            "secondary_agency_code": AGENCY_PRD_CODE[secondary] if secondary else None,
            "secondary_agency_info": AGENCY_INFO[secondary] if secondary else None,
            "reporter_count": c.get("reporter_count") or c["report_count"],
            "severity_level": severity_level(c["max_severity"]),
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
    return mask_fields(out, CLUSTER_TEXT)


def parsed_view(r: dict[str, Any]) -> dict[str, Any]:
    """The PRD's parser output shape for a report."""
    return {
        "category": r["category"],
        "severity": severity_level(r["severity"]),
        "estimated_dimensions_cm": r.get("dimensions_json") or None,
        "extracted_landmark": r.get("landmark"),
        "transcription": r.get("transcript") or "",
        "language": r.get("language"),
    }


def present_report(r: dict[str, Any], *, credibility: float | None = None, include_audio: bool = False) -> dict[str, Any]:
    out = {k: v for k, v in r.items() if not k.endswith("_json") and k not in ("audio_path", "reporter_id")}
    audio_public = include_audio or get_settings().public_audio
    out.update(
        {
            "reporter_id": pseudonym(r.get("reporter_id")),
            "category_label": CATEGORY_LABELS[Category(r["category"])],
            "severity_level": severity_level(r["severity"]),
            "agency_code": AGENCY_PRD_CODE[Agency(r["agency"])] if r.get("agency") else None,
            "hazards": r.get("hazards_json") or [],
            "evidence": r.get("evidence_json") or {},
            "extraction": r.get("raw_extraction_json"),
            "parsed": parsed_view(r),
            "exif_gps": r.get("exif_gps_json"),
            "photo_flags": r.get("photo_flags_json") or [],
            "privacy_blurred": int(r.get("privacy_blurred") or 0),
            "reporter_credibility": credibility,
            "is_corroboration": bool(r.get("is_corroboration")),
            "photo_url": media_url(r.get("photo_path")),
            "audio_url": media_url(r.get("audio_path")) if audio_public else None,
        }
    )
    return mask_fields(out, REPORT_TEXT)


def present_verification(v: dict[str, Any]) -> dict[str, Any]:
    out = {k: v2 for k, v2 in v.items() if not k.endswith("_json")}
    out.update(
        {
            "actor": pseudonym(v.get("actor")) if v.get("kind") == "citizen" else v.get("actor"),
            "same_location": bool(v.get("same_location")),
            "issue_resolved": bool(v.get("issue_resolved")),
            # Rows written before the GPS check existed fall back to the vision verdict.
            "location_match": bool(v["location_match"]) if v.get("location_match") is not None else bool(v.get("same_location")),
            "repair_quality": repair_quality(v["verdict"], v.get("fix_quality")),
            # PRD name for the verifier's plain-language explanation.
            "verification_summary": v.get("explanation"),
            "photo_url": media_url(v.get("photo_path")),
            "before_photo_urls": [media_url(p) for p in (v.get("before_photo_paths_json") or [])],
            "details": v.get("raw_json") or {},
        }
    )
    return mask_fields(out, ("note", "explanation", "verification_summary", "details"))


def present_event(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in e.items() if not k.endswith("_json")}
    out["payload"] = e.get("payload_json") or {}
    if e.get("type") in CITIZEN_EVENT_TYPES:
        out["actor"] = pseudonym(e.get("actor"))
    out["note"] = mask_deep(e.get("note"))
    return out


def present_notification(n: dict[str, Any], cluster: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {k: v for k, v in n.items() if not k.endswith("_json")}
    out["payload"] = n.get("payload_json") or {}
    out["message"] = mask_deep(n.get("message"))
    out["cluster"] = (
        {
            "id": cluster["id"],
            "title": mask_deep(cluster["title"]),
            "status": cluster["status"],
            "status_label": STATUS_LABELS[ClusterStatus(cluster["status"])],
            "category_label": CATEGORY_LABELS[Category(cluster["category"])],
            "ward": cluster["ward"],
        }
        if cluster
        else None
    )
    return out
