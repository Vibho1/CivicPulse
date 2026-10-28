"""Report intake: parse evidence -> route -> cluster -> score.

This is the heart of the MVP. ``ingest`` is used by the HTTP layer and by the
demo seeder (with a pre-computed extraction so seeding never needs the model).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from ..ai import ResilientAI
from ..ai.base import Media, ParseInput
from ..domain import (
    ACTIVE_STATUSES,
    CLUSTER_RADIUS_M,
    MIN_PARSE_CONFIDENCE,
    PHOTO_LOCATION_WARN_M,
    REPEAT_FAILURE_RADIUS_M,
    REPEAT_FAILURE_WINDOW_DAYS,
    SLA_HOURS,
    Category,
    ClusterStatus,
    Hazard,
)
from ..geo import (
    ContextHit,
    bbox_for_radius,
    blur_regions,
    extract_exif_gps,
    has_exif,
    haversine_m,
    location_context,
    nearest_ward,
    normalise_photo,
)
from ..schemas import Extraction
from ..store import Store
from .common import new_id, now_iso, now_utc, parse_iso, sla_due, to_iso
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

# Photo provenance flags (PRD anti-spam and privacy NFRs).
FLAG_EXIF_STRIPPED = "exif_stripped"  # no camera metadata: forwarded, downloaded or stock image?
FLAG_EXIF_FAR = "exif_location_far"  # the photo's own GPS is far from the reported spot
FLAG_STOCK = "stock_or_screenshot"  # the model thinks it is a stock image / screenshot
FLAG_BLURRED = "faces_or_plates_blurred"  # faces / number plates were blurred before storage

LOW_CONFIDENCE_MESSAGE = (
    "We couldn't tell what the problem is. Describe it in a few words (e.g. \u201cpothole near the bus stop\u201d) "
    "or add a clearer photo, then try again."
)


class NotCivicIssue(Exception):
    def __init__(self, extraction: Extraction):
        super().__init__("Submission does not look like a civic issue")
        self.extraction = extraction


class LowConfidence(Exception):
    def __init__(self, extraction: Extraction, reason: str):
        super().__init__(reason)
        self.extraction = extraction
        self.reason = reason


class DuplicateSubmission(Exception):
    """Same reporter, same category, close by, moments ago (anti-spam)."""

    def __init__(self, previous: dict, retry_after_s: int):
        super().__init__("Duplicate submission")
        self.previous = previous
        self.retry_after_s = retry_after_s


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
    emergency: bool = False


def context_hint(hits: list[ContextHit]) -> str:
    return "; ".join(f"{h.type.replace('_', ' ')}: {h.name} ({h.distance_m} m)" for h in hits[:5])


def find_match(store: Store, category: Category, lat: float, lng: float, now_iso_s: str) -> tuple[str, dict | None]:
    """Return ('merge', cluster) | ('repeat', previous_cluster) | ('new', None).

    PRD: a report merges into an active cluster of the same category within
    CLUSTER_RADIUS_M; otherwise, a Verified resolved cluster of the same category
    within REPEAT_FAILURE_RADIUS_M, fixed in the last REPEAT_FAILURE_WINDOW_DAYS,
    makes it a repeat failure.
    """
    cands = store.clusters_in_bbox(*bbox_for_radius(lat, lng, 2 * max(CLUSTER_RADIUS_M, REPEAT_FAILURE_RADIUS_M)))
    same = [c for c in cands if c["category"] == category.value]
    for c in same:
        c["_d"] = haversine_m(lat, lng, c["lat"], c["lng"])
    same.sort(key=lambda c: c["_d"])

    for c in same:
        if ClusterStatus(c["status"]) in ACTIVE_STATUSES and c["_d"] <= CLUSTER_RADIUS_M:
            return "merge", c

    now = parse_iso(now_iso_s)
    for c in same:
        fixed_at = c.get("verified_at") or c.get("resolved_at")
        if ClusterStatus(c["status"]) == ClusterStatus.RESOLVED_VERIFIED and c["_d"] <= REPEAT_FAILURE_RADIUS_M and fixed_at:
            age_days = (now - parse_iso(fixed_at)).days
            if 0 <= age_days <= REPEAT_FAILURE_WINDOW_DAYS:
                return "repeat", c
    return "new", None


def find_duplicate(
    store: Store, reporter_id: str | None, category: Category, lat: float, lng: float, ts: str, window_s: float, radius_m: float
) -> tuple[dict, int] | None:
    """The reporter's own earlier report of the same category within radius_m and window_s, if any.

    Returns (previous_report, seconds until a new submission would be accepted).
    """
    if not reporter_id or window_s <= 0 or radius_m <= 0:
        return None
    now = parse_iso(ts)
    since = to_iso(now - timedelta(seconds=window_s))
    for r in store.recent_reports_by_reporter(reporter_id, since, ts):
        if r["category"] == category.value and haversine_m(lat, lng, r["lat"], r["lng"]) <= radius_m:
            retry_after = max(1, int(window_s - (now - parse_iso(r["created_at"])).total_seconds()))
            return r, retry_after
    return None


def _save(uploads_dir: Path, name: str, data: bytes) -> str:
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / name).write_bytes(data)
    return name


def _reject(store: Store, reporter_id: str | None, code: str, ts: str) -> None:
    """Remember bounced submissions (no content) for the reporter's credibility score."""
    if reporter_id:
        store.insert_rejection(dict(id=new_id("X"), created_at=ts, reporter_id=reporter_id, code=code))


def _dimensions(extraction: Extraction) -> dict | None:
    dims = extraction.estimated_dimensions_cm
    if dims is None or all(v is None for v in (dims.length, dims.width, dims.depth)):
        return None
    return dims.model_dump()


def rescore(store: Store, cluster: dict, now=None) -> dict:
    """Recompute the impact score for a cluster dict (returns it updated). Writes only on change."""
    ctx = [ContextHit(**h) for h in (cluster.get("context_json") or [])]
    breakdown = compute_score(
        report_count=cluster["report_count"],
        reporter_count=cluster.get("reporter_count"),
        max_severity=cluster["max_severity"],
        hazards=cluster.get("hazards_json") or [],
        context=ctx,
        created_at=cluster["created_at"],
        sla_due_at=cluster["sla_due_at"],
        status=ClusterStatus(cluster["status"]),
        resolved_at=cluster.get("resolved_at"),
        now=now,
    )
    dumped = breakdown.model_dump()
    if cluster.get("impact_score") != breakdown.total or cluster.get("score_breakdown_json") != dumped:
        store.update_cluster(cluster["id"], impact_score=breakdown.total, score_breakdown_json=dumped)
    cluster["impact_score"] = breakdown.total
    cluster["score_breakdown_json"] = dumped
    return cluster


def refresh_scores(store: Store, now=None) -> int:
    """Rescore every cluster (days elapsed changes with time). Cheap at city scale; writes only changes."""
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
    duplicate_window_s: float = 0,
    duplicate_radius_m: float = 0,
    target_cluster: dict | None = None,
    citizen_distance_m: float | None = None,
    photo_exif: bool | None = None,
    photo_gps: tuple[float, float] | None = None,
    check_photo_provenance: bool = True,
    expect_exif: bool = True,
) -> IntakeResult:
    """File one report.

    ``target_cluster`` forces a merge into that (active) cluster - used by "I see this too".
    ``photo_exif`` / ``photo_gps`` describe the ORIGINAL photo file when the client had to
    re-encode it (the PWA resizes photos, which drops EXIF): whether it carried EXIF
    metadata and its embedded GPS position. EXIF found in the uploaded bytes always wins.
    ``expect_exif`` is False for channels that strip metadata for everyone (WhatsApp).
    """
    ts = created_at or now_iso()
    report_id = new_id("R")
    ward = nearest_ward(lat, lng)
    ctx_hits = location_context(lat, lng)

    # ---- media handling (in memory; written to disk only once accepted) --
    exif_info = None
    location_warning = None
    photo_flags: list[str] = []
    if photo is not None:
        embedded = has_exif(photo.data)
        gps = extract_exif_gps(photo.data) or photo_gps
        if check_photo_provenance and expect_exif and not (embedded or photo_exif):
            photo_flags.append(FLAG_EXIF_STRIPPED)
        norm_bytes, norm_mime = normalise_photo(photo.data)
        photo = Media(norm_bytes, norm_mime, "photo")
        if gps:
            dist = haversine_m(lat, lng, gps[0], gps[1])
            exif_info = {"lat": gps[0], "lng": gps[1], "distance_m": round(dist)}
            if dist > PHOTO_LOCATION_WARN_M:
                location_warning = f"Photo EXIF location is {dist / 1000:.1f} km from the reported spot"
                if check_photo_provenance:
                    photo_flags.append(FLAG_EXIF_FAR)

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
        _reject(store, reporter_id, "not_civic_issue", ts)
        raise NotCivicIssue(extraction)
    if strict and extraction.category == Category.OTHER and extraction.confidence < MIN_PARSE_CONFIDENCE:
        # Neither the words nor the photo say what is wrong: ask, rather than file a mystery ticket.
        _reject(store, reporter_id, "low_confidence", ts)
        raise LowConfidence(extraction, LOW_CONFIDENCE_MESSAGE)

    category = extraction.category
    duplicate = find_duplicate(store, reporter_id, category, lat, lng, ts, duplicate_window_s, duplicate_radius_m)
    if duplicate:
        raise DuplicateSubmission(*duplicate)

    privacy_blurred = 0
    if photo is not None:
        if check_photo_provenance and extraction.evidence.stock_or_screenshot:
            photo_flags.append(FLAG_STOCK)
        if extraction.sensitive_regions:
            # PRD privacy NFR: faces and number plates are blurred before public storage.
            blurred, privacy_blurred = blur_regions(photo.data, extraction.sensitive_regions)
            if privacy_blurred:
                photo = Media(blurred, "image/jpeg", "photo")
                photo_flags.append(FLAG_BLURRED)

    photo_path = _save(uploads_dir, f"{report_id}.jpg", photo.data) if photo is not None else None
    audio_path = None
    if audio is not None:
        ext = AUDIO_EXT.get(audio.mime_type.split(";")[0].strip().lower(), "bin")
        # Unguessable name: voice notes are only listed publicly when PUBLIC_AUDIO is on.
        audio_path = _save(uploads_dir, f"{report_id}-{secrets.token_hex(6)}.{ext}", audio.data)

    decision = route(extraction, ctx_hits)
    agency, agency_reason = decision.agency, decision.reason
    secondary = decision.secondary_agency.value if decision.secondary_agency else None
    hazards = [h.value if isinstance(h, Hazard) else str(h) for h in extraction.hazards]
    if extraction.evidence.recent_digging and Hazard.RECENT_DIGGING.value not in hazards:
        hazards.append(Hazard.RECENT_DIGGING.value)

    # ---- clustering -----------------------------------------------------
    if target_cluster is not None and ClusterStatus(target_cluster["status"]) in ACTIVE_STATUSES:
        # "I see this too" always backs the issue the citizen tapped.
        kind, match = "merge", dict(target_cluster, _d=haversine_m(lat, lng, target_cluster["lat"], target_cluster["lng"]))
    else:
        kind, match = find_match(store, category, lat, lng, ts)
    merged = kind == "merge"
    repeat = kind == "repeat"
    previous = match if repeat else None
    reopened = False

    if merged:
        cluster = match  # type: ignore[assignment]
        n = cluster["report_count"] + 1
        # Unique citizens behind the issue; anonymous reports count individually.
        reporters = len(store.reporter_keys(cluster["id"]) | {reporter_id or report_id})
        # Running centroid so the pin settles on the true spot.
        new_lat = (cluster["lat"] * cluster["report_count"] + lat) / n
        new_lng = (cluster["lng"] * cluster["report_count"] + lng) / n
        merged_hazards = sorted(set(cluster.get("hazards_json") or []) | set(hazards))
        updates = dict(
            report_count=n,
            reporter_count=reporters,
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
        if reporter_id:
            # Reporting it again answers any open "is it fixed?" request for this issue.
            store.mark_notifications_read(reporter_id, ts, cluster_id=cluster["id"])
        where = f"citizen {citizen_distance_m:.0f} m away" if citizen_distance_m is not None else f"{match['_d']:.0f} m away"
        store.insert_event(
            dict(
                id=new_id("E"),
                cluster_id=cluster["id"],
                created_at=ts,
                type="corroborated" if is_corroboration else "merged",
                actor=reporter_id or "citizen",
                note=f"Report {report_id} merged ({where}). Now {n} reports from {reporters} citizen{'s' if reporters != 1 else ''}.",
                payload_json={"report_id": report_id, "distance_m": round(citizen_distance_m if citizen_distance_m is not None else match["_d"])},
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
                    note="New citizen report after official closure - marked as an unverified closure.",
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
            secondary_agency=secondary,
            secondary_agency_reason=decision.secondary_reason,
            routing_confidence=decision.confidence,
            report_count=1,
            reporter_count=1,
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
        routed = f"Routed to {agency.value} ({decision.confidence:.0%} confidence): {agency_reason}"
        if secondary:
            routed += f" Also responsible: {secondary} - {decision.secondary_reason}"
        store.insert_event(
            dict(
                id=new_id("E"),
                cluster_id=cluster_id,
                created_at=ts,
                type="reported",
                actor=reporter_id or "citizen",
                note=f"First report {report_id} ({ai_mode}). {routed}",
                payload_json={"report_id": report_id, "agency": agency.value, "secondary_agency": secondary, "routing_confidence": decision.confidence},
            )
        )
        if repeat and previous:
            fixed_at = previous.get("verified_at") or previous["resolved_at"]
            store.insert_event(
                dict(
                    id=new_id("E"),
                    cluster_id=cluster_id,
                    created_at=ts,
                    type="repeat_failure_flagged",
                    actor="system",
                    note=(
                        f"Same issue was verified fixed as {previous['id']} on {fixed_at[:10]} "
                        f"({previous['_d']:.0f} m away) - failed within {REPEAT_FAILURE_WINDOW_DAYS} days."
                    ),
                    payload_json={"previous_cluster_id": previous["id"], "distance_m": round(previous["_d"])},
                )
            )

    if extraction.is_emergency:
        store.insert_event(
            dict(
                id=new_id("E"),
                cluster_id=cluster["id"],
                created_at=ts,
                type="emergency_flagged",
                actor="system",
                note=f"Report {report_id} describes an emergency: the citizen was told to call 112 (CivicPulse does not dispatch emergency services).",
                payload_json={"report_id": report_id},
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
        secondary_agency=secondary,
        secondary_agency_reason=decision.secondary_reason,
        routing_confidence=decision.confidence,
        audio_path=audio_path,
        photo_path=photo_path,
        ai_mode=ai_mode,
        confidence=extraction.confidence,
        raw_extraction_json=extraction.model_dump(mode="json"),
        ward=ward.name,
        exif_gps_json=exif_info,
        is_corroboration=1 if is_corroboration else 0,
        photo_flags_json=photo_flags,
        privacy_blurred=privacy_blurred,
        dimensions_json=_dimensions(extraction),
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
        emergency=bool(extraction.is_emergency),
    )
