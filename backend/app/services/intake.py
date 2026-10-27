"""Report intake: parse evidence -> route -> cluster -> score.

This is the heart of the MVP. ``ingest`` is used by the HTTP layer and by the
demo seeder (with a pre-computed extraction so seeding never needs the model).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..ai import ResilientAI
from ..ai.base import Media, ParseInput
from ..domain import (
    ACTIVE_STATUSES,
    CLUSTER_RADIUS_M,
    REPEAT_FAILURE_WINDOW_DAYS,
    SLA_HOURS,
    Category,
    ClusterStatus,
    Hazard,
)
from ..geo import (
    ContextHit,
    bbox_for_radius,
    extract_exif_gps,
    haversine_m,
    location_context,
    nearest_ward,
    normalise_photo,
)
from ..schemas import Extraction
from ..store import Store
from .common import new_id, now_iso, now_utc, parse_iso, sla_due
from .routing import route
from .scoring import compute_score

log = logging.getLogger(__name__)

AUDIO_EXT = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/aac": "aac",
}


class NotCivicIssue(Exception):
    def __init__(self, extraction: Extraction):
        super().__init__("Submission does not look like a civic issue")
        self.extraction = extraction


class LowConfidence(Exception):
    def __init__(self, extraction: Extraction, reason: str):
        super().__init__(reason)
        self.extraction = extraction
        self.reason = reason


@dataclass
class IntakeResult:
    report: dict
    cluster: dict
    merged: bool
    repeat_failure: bool
    extraction: Extraction
    ai_mode: str
    previous_cluster: dict | None
    reopened: bool = False
    location_warning: str | None = None


def context_hint(hits: list[ContextHit]) -> str:
    return "; ".join(f"{h.type.replace('_', ' ')}: {h.name} ({h.distance_m} m)" for h in hits[:5])


def find_match(store: Store, category: Category, lat: float, lng: float, now_iso_s: str) -> tuple[str, dict | None]:
    """Return ('merge', cluster) | ('repeat', previous_cluster) | ('new', None)."""
    radius = CLUSTER_RADIUS_M[category]
    cands = store.clusters_in_bbox(*bbox_for_radius(lat, lng, max(radius * 2, 250)))
    same = [c for c in cands if c["category"] == category.value]
    for c in same:
        c["_d"] = haversine_m(lat, lng, c["lat"], c["lng"])
    same.sort(key=lambda c: c["_d"])

    for c in same:
        if ClusterStatus(c["status"]) in ACTIVE_STATUSES and c["_d"] <= radius:
            return "merge", c

    now = parse_iso(now_iso_s)
    for c in same:
        if ClusterStatus(c["status"]) == ClusterStatus.RESOLVED_VERIFIED and c["_d"] <= radius * 1.5 and c.get("resolved_at"):
            age_days = (now - parse_iso(c["resolved_at"])).days
            if 0 <= age_days <= REPEAT_FAILURE_WINDOW_DAYS:
                return "repeat", c
    return "new", None


def _save(uploads_dir: Path, name: str, data: bytes) -> str:
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / name).write_bytes(data)
    return name


def rescore(store: Store, cluster: dict, now=None) -> dict:
    """Recompute and persist the impact score for a cluster dict (returns updated dict)."""
    ctx = [ContextHit(**h) for h in (cluster.get("context_json") or [])]
    breakdown = compute_score(
        report_count=cluster["report_count"],
        max_severity=cluster["max_severity"],
        hazards=cluster.get("hazards_json") or [],
        context=ctx,
        created_at=cluster["created_at"],
        sla_due_at=cluster["sla_due_at"],
        status=ClusterStatus(cluster["status"]),
        repeat_failure=bool(cluster.get("repeat_failure")),
        now=now,
    )
    cluster["impact_score"] = breakdown.total
    cluster["score_breakdown_json"] = breakdown.model_dump()
    store.update_cluster(cluster["id"], impact_score=breakdown.total, score_breakdown_json=breakdown.model_dump())
    return cluster


def refresh_scores(store: Store, now=None) -> int:
    """Rescore every cluster (SLA pressure changes with time). Cheap at city scale."""
    now = now or now_utc()
    n = 0
    for c in store.all_clusters():
        rescore(store, c, now=now)
        n += 1
    return n


def ingest(
    store: Store,
    ai: ResilientAI,
    *,
    lat: float,
    lng: float,
    uploads_dir: Path,
    accuracy: float | None = None,
    text: str | None = None,
    audio: Media | None = None,
    photo: Media | None = None,
    reporter_id: str | None = None,
    language_hint: str | None = None,
    is_corroboration: bool = False,
    extraction_override: Extraction | None = None,
    ai_mode_override: str | None = None,
    created_at: str | None = None,
    strict: bool = True,
) -> IntakeResult:
    ts = created_at or now_iso()
    report_id = new_id("R")
    ward = nearest_ward(lat, lng)
    ctx_hits = location_context(lat, lng)

    # ---- media handling -------------------------------------------------
    photo_path = audio_path = None
    exif_info = None
    location_warning = None
    if photo is not None:
        gps = extract_exif_gps(photo.data)
        norm_bytes, norm_mime = normalise_photo(photo.data)
        photo = Media(norm_bytes, norm_mime, "photo")
        photo_path = _save(uploads_dir, f"{report_id}.jpg", norm_bytes)
        if gps:
            dist = haversine_m(lat, lng, gps[0], gps[1])
            exif_info = {"lat": gps[0], "lng": gps[1], "distance_m": round(dist)}
            if dist > 500:
                location_warning = f"Photo EXIF location is {dist / 1000:.1f} km from the reported spot"
    if audio is not None:
        ext = AUDIO_EXT.get(audio.mime_type.split(";")[0].strip().lower(), "bin")
        audio_path = _save(uploads_dir, f"{report_id}.{ext}", audio.data)

    # ---- AI extraction ---------------------------------------------------
    if extraction_override is not None:
        extraction, ai_mode = extraction_override, (ai_mode_override or "seed")
    else:
        extraction, ai_mode = ai.parse(
            ParseInput(
                text=text,
                audio=audio,
                photo=photo,
                lat=lat,
                lng=lng,
                ward=ward.name,
                context_hint=context_hint(ctx_hits),
                language_hint=language_hint,
            )
        )
    if strict and not extraction.is_civic_issue:
        raise NotCivicIssue(extraction)

    agency, agency_reason = route(extraction, ctx_hits)
    category = extraction.category
    hazards = [h.value if isinstance(h, Hazard) else str(h) for h in extraction.hazards]
    if extraction.evidence.recent_digging and Hazard.RECENT_DIGGING.value not in hazards:
        hazards.append(Hazard.RECENT_DIGGING.value)

    # ---- clustering -----------------------------------------------------
    kind, match = find_match(store, category, lat, lng, ts)
    merged = kind == "merge"
    repeat = kind == "repeat"
    previous = match if repeat else None
    reopened = False

    if merged:
        cluster = match  # type: ignore[assignment]
        n = cluster["report_count"] + 1
        # Running centroid so the pin settles on the true spot.
        new_lat = (cluster["lat"] * cluster["report_count"] + lat) / n
        new_lng = (cluster["lng"] * cluster["report_count"] + lng) / n
        merged_hazards = sorted(set(cluster.get("hazards_json") or []) | set(hazards))
        updates = dict(
            report_count=n,
            lat=new_lat,
            lng=new_lng,
            max_severity=max(cluster["max_severity"], extraction.severity),
            hazards_json=merged_hazards,
            updated_at=ts,
        )
        if not cluster.get("primary_photo_path") and photo_path:
            updates["primary_photo_path"] = photo_path
        if not cluster.get("landmark") and extraction.landmark:
            updates["landmark"] = extraction.landmark
        # A fresh report against an unverified closure means it is not fixed.
        if ClusterStatus(cluster["status"]) == ClusterStatus.RESOLVED_PENDING_VERIFICATION:
            updates["status"] = ClusterStatus.CLOSURE_DISPUTED.value
            reopened = True
        store.update_cluster(cluster["id"], **updates)
        cluster.update(updates)
        store.insert_event(
            dict(
                id=new_id("E"),
                cluster_id=cluster["id"],
                created_at=ts,
                type="corroborated" if is_corroboration else "merged",
                actor=reporter_id or "citizen",
                note=f"Report {report_id} merged ({match['_d']:.0f} m away). Now {n} reports.",
                payload_json={"report_id": report_id, "distance_m": round(match["_d"])},
            )
        )
        if reopened:
            store.insert_event(
                dict(
                    id=new_id("E"),
                    cluster_id=cluster["id"],
                    created_at=ts,
                    type="reopened",
                    actor="system",
                    note="New citizen report after official closure - closure disputed.",
                    payload_json={"report_id": report_id},
                )
            )
    else:
        cluster_id = new_id("CP")
        cluster = dict(
            id=cluster_id,
            created_at=ts,
            updated_at=ts,
            category=category.value,
            status=ClusterStatus.OPEN.value,
            lat=lat,
            lng=lng,
            ward=ward.name,
            zone=ward.zone,
            title=extraction.title,
            description=extraction.description,
            landmark=extraction.landmark,
            agency=agency.value,
            agency_reason=agency_reason,
            report_count=1,
            max_severity=extraction.severity,
            impact_score=0.0,
            score_breakdown_json=None,
            sla_hours=SLA_HOURS[category],
            sla_due_at=sla_due(ts, category),
            repeat_failure=1 if repeat else 0,
            previous_cluster_id=previous["id"] if previous else None,
            primary_photo_path=photo_path,
            hazards_json=sorted(set(hazards) | ({Hazard.RECURRING.value} if repeat else set())),
            context_json=[h.__dict__ for h in ctx_hits],
            closure_count=0,
            first_report_id=report_id,
        )
        store.insert_cluster(cluster)
        store.insert_event(
            dict(
                id=new_id("E"),
                cluster_id=cluster_id,
                created_at=ts,
                type="reported",
                actor=reporter_id or "citizen",
                note=f"First report {report_id} ({ai_mode}). Routed to {agency.value}: {agency_reason}",
                payload_json={"report_id": report_id, "agency": agency.value},
            )
        )
        if repeat and previous:
            store.insert_event(
                dict(
                    id=new_id("E"),
                    cluster_id=cluster_id,
                    created_at=ts,
                    type="repeat_failure_flagged",
                    actor="system",
                    note=f"Same issue was marked fixed as {previous['id']} on {previous['resolved_at'][:10]} - failed within {REPEAT_FAILURE_WINDOW_DAYS} days.",
                    payload_json={"previous_cluster_id": previous["id"]},
                )
            )

    cluster = rescore(store, cluster, now=parse_iso(ts) if created_at else now_utc())

    report = dict(
        id=report_id,
        cluster_id=cluster["id"],
        created_at=ts,
        lat=lat,
        lng=lng,
        accuracy=accuracy,
        reporter_id=reporter_id,
        text=text,
        transcript=extraction.transcript,
        transcript_english=extraction.transcript_english,
        language=extraction.language,
        category=category.value,
        severity=extraction.severity,
        title=extraction.title,
        description=extraction.description,
        landmark=extraction.landmark,
        size_estimate=extraction.size_estimate,
        hazards_json=hazards,
        evidence_json=extraction.evidence.model_dump(),
        agency=agency.value,
        agency_reason=agency_reason,
        audio_path=audio_path,
        photo_path=photo_path,
        ai_mode=ai_mode,
        confidence=extraction.confidence,
        raw_extraction_json=extraction.model_dump(mode="json"),
        ward=ward.name,
        exif_gps_json=exif_info,
        is_corroboration=1 if is_corroboration else 0,
    )
    store.insert_report(report)
    cluster.pop("_d", None)
    return IntakeResult(
        report=report,
        cluster=cluster,
        merged=merged,
        repeat_failure=repeat,
        extraction=extraction,
        ai_mode=ai_mode,
        previous_cluster=previous,
        reopened=reopened,
        location_warning=location_warning,
    )
