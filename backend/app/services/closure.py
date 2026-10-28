"""Closure lifecycle: status changes, official resolution, AI closure check,
citizen verification and dispute handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ai import ResilientAI
from ..ai.base import Media
from ..domain import CATEGORY_LABELS, VERIFY_GPS_RADIUS_M, Category, ClusterStatus, Verdict
from ..geo import blur_regions, extract_exif_gps, haversine_m, normalise_photo
from ..schemas import VerificationResult
from ..store import Store
from .common import new_id, now_iso
from .intake import rescore
from .notify import Notifier, request_verification

RESOLVABLE = {ClusterStatus.OPEN, ClusterStatus.IN_PROGRESS, ClusterStatus.CLOSURE_DISPUTED}
VERIFIABLE = {ClusterStatus.RESOLVED_PENDING_VERIFICATION, ClusterStatus.CLOSURE_DISPUTED}


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class GpsCheck:
    """Where a proof photo was taken, relative to the issue."""

    source: str | None = None  # "exif" (embedded in the photo) | "device" (sent by the client) | None
    distance_m: float | None = None
    ok: bool | None = None  # None: no location evidence either way


def gps_check(
    cluster: dict,
    photo_bytes: bytes,
    lat: float | None = None,
    lng: float | None = None,
    accuracy: float | None = None,
    photo_gps: tuple[float, float] | None = None,
) -> GpsCheck:
    """Is the photo's capture location within VERIFY_GPS_RADIUS_M of the issue?

    EXIF GPS (recorded with the photo) wins: embedded in the upload, or read from
    the original file by the client before it re-encoded the photo (``photo_gps``).
    The client-reported device position is a fallback for photos without GPS
    metadata; its accuracy radius (capped at the limit) is allowed as slack.
    """
    gps = extract_exif_gps(photo_bytes) or photo_gps
    source, slack = "exif", 0.0
    if gps is None:
        if lat is None or lng is None:
            return GpsCheck()
        gps, source = (lat, lng), "device"
        slack = min(max(accuracy or 0.0, 0.0), float(VERIFY_GPS_RADIUS_M))
    d = haversine_m(cluster["lat"], cluster["lng"], gps[0], gps[1])
    return GpsCheck(source, round(d, 1), d - slack <= VERIFY_GPS_RADIUS_M)


def _gps_cue(check: GpsCheck) -> str:
    where = "embedded GPS" if check.source == "exif" else "device location"
    return f"photo {where} {check.distance_m:.0f} m from the reported spot"


def gps_mismatch_result(check: GpsCheck) -> VerificationResult:
    """A photo taken too far away cannot show this issue, whatever it depicts."""
    where = "embedded GPS" if check.source == "exif" else "device location"
    return VerificationResult(
        same_location=False,
        same_location_confidence=0.0,
        issue_resolved=False,
        resolution_confidence=0.0,
        fix_quality="unknown",
        verdict=Verdict.UNVERIFIED_DIFFERENT_LOCATION,
        explanation=(
            f"The photo's {where} is {check.distance_m:.0f} m from the reported spot (limit {VERIFY_GPS_RADIUS_M} m), "
            "so it cannot show this issue. Retake the photo at the spot."
        ),
        matched_cues=[],
        mismatch_cues=[_gps_cue(check)],
    )


def with_gps_cue(result: VerificationResult, check: GpsCheck) -> VerificationResult:
    if check.ok:
        return result.model_copy(update={"matched_cues": [_gps_cue(check), *result.matched_cues]})
    return result


def location_match(result: VerificationResult, check: GpsCheck) -> bool:
    """PRD ``location_match``: landmarks/road geometry (vision) and GPS agree it is the same spot."""
    if check.ok is False:
        return False
    if result.same_location:
        return True
    # Vision could not judge (e.g. offline mode) but the photo's GPS puts it on the spot.
    return bool(check.ok) and Verdict(result.verdict) == Verdict.INCONCLUSIVE


def _event(store: Store, cluster_id: str, type_: str, actor: str, note: str, payload: dict | None = None, ts: str | None = None) -> None:
    store.insert_event(dict(id=new_id("E"), cluster_id=cluster_id, created_at=ts or now_iso(), type=type_, actor=actor, note=note, payload_json=payload or {}))


def set_status(store: Store, cluster: dict, status: ClusterStatus, note: str | None, actor: str, ts: str | None = None) -> dict:
    current = ClusterStatus(cluster["status"])
    if status not in (ClusterStatus.OPEN, ClusterStatus.IN_PROGRESS):
        raise InvalidTransition("Use /resolve or /verify for closure transitions")
    if current == ClusterStatus.RESOLVED_VERIFIED:
        raise InvalidTransition("A verified closure cannot be reopened manually; file a new report instead")
    ts = ts or now_iso()
    store.update_cluster(cluster["id"], status=status.value, updated_at=ts)
    cluster.update(status=status.value, updated_at=ts)
    # Any closure claim is withdrawn, so outstanding proof requests are moot.
    store.expire_notifications(cluster["id"])
    _event(store, cluster["id"], "status_changed", actor, note or f"Status set to {status.value}", {"from": current.value, "to": status.value}, ts)
    return rescore(store, cluster)


def _before_photos(store: Store, cluster: dict, uploads_dir: Path, limit: int = 2) -> tuple[list[Media], list[str]]:
    paths: list[str] = []
    if cluster.get("primary_photo_path"):
        paths.append(cluster["primary_photo_path"])
    for r in store.reports_for_cluster(cluster["id"]):
        if r.get("photo_path") and r["photo_path"] not in paths:
            paths.append(r["photo_path"])
        if len(paths) >= limit:
            break
    media = []
    for p in paths[:limit]:
        f = uploads_dir / p
        if f.exists():
            media.append(Media(f.read_bytes(), "image/jpeg", p))
    return media, paths[:limit]


def _context_text(cluster: dict) -> str:
    cat = CATEGORY_LABELS[Category(cluster["category"])]
    return (
        f"{cluster['title']} - {cat}, severity {cluster['max_severity']}/5, {cluster['report_count']} reports, "
        f"{cluster['ward']} ward, landmark: {cluster.get('landmark') or 'n/a'}. {cluster.get('description') or ''}"
    )


def _store_verification(
    store: Store,
    cluster: dict,
    kind: str,
    actor: str,
    photo_path: str | None,
    before_paths: list[str],
    result: VerificationResult,
    ai_mode: str,
    note: str | None,
    ts: str,
    check: GpsCheck | None = None,
) -> dict:
    check = check or GpsCheck()
    v = dict(
        id=new_id("V"),
        cluster_id=cluster["id"],
        created_at=ts,
        kind=kind,
        actor=actor,
        photo_path=photo_path,
        before_photo_paths_json=before_paths,
        verdict=result.verdict.value if isinstance(result.verdict, Verdict) else str(result.verdict),
        same_location=int(result.same_location),
        issue_resolved=int(result.issue_resolved),
        fix_quality=result.fix_quality,
        same_location_confidence=result.same_location_confidence,
        resolution_confidence=result.resolution_confidence,
        explanation=result.explanation,
        raw_json=result.model_dump(mode="json"),
        ai_mode=ai_mode,
        note=note,
        location_match=int(location_match(result, check)),
        gps_distance_m=check.distance_m,
        gps_source=check.source,
    )
    store.insert_verification(v)
    return v


def no_proof_result() -> VerificationResult:
    return VerificationResult(
        same_location=False,
        same_location_confidence=0.0,
        issue_resolved=False,
        resolution_confidence=0.0,
        fix_quality="unknown",
        verdict=Verdict.NO_PROOF_PROVIDED,
        explanation="Closed without an after-repair photo. Nearby citizens have been asked for a fresh photo.",
    )


def _store_proof_photo(uploads_dir: Path, name: str, data: bytes, result: VerificationResult) -> str:
    """Write a proof photo, blurring faces / number plates the verifier spotted (PRD privacy NFR)."""
    if result.after_sensitive_regions:
        data, _ = blur_regions(data, result.after_sensitive_regions)
    (uploads_dir / name).write_bytes(data)
    return name


def resolve(
    store: Store,
    ai: ResilientAI,
    cluster: dict,
    *,
    uploads_dir: Path,
    after_photo: Media | None,
    note: str | None,
    actor: str,
    ts: str | None = None,
    result_override: VerificationResult | None = None,
    capture_lat: float | None = None,
    capture_lng: float | None = None,
    capture_accuracy: float | None = None,
    photo_gps: tuple[float, float] | None = None,
    notifier: Notifier | None = None,
) -> tuple[dict, dict]:
    """Official marks the issue resolved. Runs the closure check if a photo is given,
    then asks the issue's reporters (and citizens nearby) for a fresh photo."""
    current = ClusterStatus(cluster["status"])
    if current not in RESOLVABLE:
        raise InvalidTransition(f"Cannot resolve a cluster in status {current.value}")
    ts = ts or now_iso()
    after_path = None
    check = GpsCheck()
    before_media, before_paths = _before_photos(store, cluster, uploads_dir)

    if after_photo is None:
        result, ai_mode = no_proof_result(), "rule"
    else:
        check = gps_check(cluster, after_photo.data, capture_lat, capture_lng, capture_accuracy, photo_gps)
        data, mime = normalise_photo(after_photo.data)
        if check.ok is False:
            # Taken too far away to show this spot: no need to ask the model.
            result, ai_mode = gps_mismatch_result(check), "rule"
        elif result_override is not None:
            result, ai_mode = result_override, "seed"
        elif not before_media:
            result, ai_mode = VerificationResult(
                same_location=False, same_location_confidence=0.0, issue_resolved=False, resolution_confidence=0.0,
                fix_quality="unknown", verdict=Verdict.INCONCLUSIVE,
                explanation="No before-photo on record to compare against; awaiting citizen confirmation.",
            ), "rule"
        else:
            result, ai_mode = ai.verify(before_media, Media(data, mime, "after"), _context_text(cluster))
        result = with_gps_cue(result, check)
        after_path = _store_proof_photo(uploads_dir, f"{cluster['id']}-after-{ts[:19].replace(':', '').replace('-', '')}.jpg", data, result)

    verdict = Verdict(result.verdict)
    if verdict in (Verdict.UNVERIFIED_DIFFERENT_LOCATION, Verdict.UNVERIFIED_NOT_FIXED, Verdict.UNVERIFIED_COSMETIC):
        new_status = ClusterStatus.CLOSURE_DISPUTED
    else:
        new_status = ClusterStatus.RESOLVED_PENDING_VERIFICATION

    updates = dict(
        status=new_status.value,
        updated_at=ts,
        resolved_at=ts,
        resolved_by=actor,
        resolution_note=note,
        after_photo_path=after_path,
        verification_verdict=verdict.value,
        closure_count=(cluster.get("closure_count") or 0) + 1,
    )
    store.update_cluster(cluster["id"], **updates)
    cluster.update(updates)
    verification = _store_verification(store, cluster, "official_closure", actor, after_path, before_paths, result, ai_mode, note, ts, check)
    _event(store, cluster["id"], "resolved", actor, note or "Marked resolved by official", {"after_photo": after_path}, ts)
    _event(
        store, cluster["id"], "closure_check", "ai" if ai_mode.startswith("gemini") else ai_mode,
        f"Closure check: {verdict.value}. {result.explanation}",
        {"verdict": verdict.value, "fix_quality": result.fix_quality, "ai_mode": ai_mode, "gps_distance_m": check.distance_m, "gps_source": check.source},
        ts,
    )
    # Replace any earlier round of requests with a fresh one for this closure.
    store.expire_notifications(cluster["id"])
    request_verification(store, cluster, verdict=verdict.value, ts=ts, notifier=notifier)
    cluster = rescore(store, cluster)
    return cluster, verification


# PRD 4.4: a proof photo that does not match the spot, or shows the fix is
# temporary / missing, turns the official closure into an Unverified closure.
CITIZEN_DISPUTE_VERDICTS = {Verdict.UNVERIFIED_DIFFERENT_LOCATION, Verdict.UNVERIFIED_NOT_FIXED, Verdict.UNVERIFIED_COSMETIC}


def citizen_verify(
    store: Store,
    ai: ResilientAI,
    cluster: dict,
    *,
    uploads_dir: Path,
    photo: Media,
    reporter_id: str | None,
    note: str | None,
    ts: str | None = None,
    result_override: VerificationResult | None = None,
    capture_lat: float | None = None,
    capture_lng: float | None = None,
    capture_accuracy: float | None = None,
    photo_gps: tuple[float, float] | None = None,
) -> tuple[dict, dict]:
    """A citizen submits a fresh photo after an official closure."""
    current = ClusterStatus(cluster["status"])
    if current not in VERIFIABLE:
        raise InvalidTransition(f"Citizen verification only applies to closed-but-unverified issues (status {current.value})")
    ts = ts or now_iso()
    check = gps_check(cluster, photo.data, capture_lat, capture_lng, capture_accuracy, photo_gps)
    data, mime = normalise_photo(photo.data)
    before_media, before_paths = _before_photos(store, cluster, uploads_dir)
    if check.ok is False:
        result, ai_mode = gps_mismatch_result(check), "rule"
    elif result_override is not None:
        result, ai_mode = result_override, "seed"
    elif before_media:
        result, ai_mode = ai.verify(before_media, Media(data, mime, "citizen"), _context_text(cluster))
    else:
        result, ai_mode = VerificationResult(
            same_location=True, same_location_confidence=0.0, issue_resolved=False, resolution_confidence=0.0,
            fix_quality="unknown", verdict=Verdict.INCONCLUSIVE, explanation="No before-photo to compare with.",
        ), "rule"
    result = with_gps_cue(result, check)
    path = _store_proof_photo(uploads_dir, f"{cluster['id']}-verify-{ts[:19].replace(':', '').replace('-', '')}.jpg", data, result)

    verdict = Verdict(result.verdict)
    new_status = current
    if verdict == Verdict.VERIFIED:
        new_status = ClusterStatus.RESOLVED_VERIFIED
    elif verdict in CITIZEN_DISPUTE_VERDICTS:
        new_status = ClusterStatus.CLOSURE_DISPUTED

    updates = dict(status=new_status.value, updated_at=ts, verification_verdict=verdict.value)
    if new_status == ClusterStatus.RESOLVED_VERIFIED:
        updates["verified_at"] = ts
    store.update_cluster(cluster["id"], **updates)
    cluster.update(updates)
    verification = _store_verification(store, cluster, "citizen", reporter_id or "citizen", path, before_paths, result, ai_mode, note, ts, check)
    if reporter_id:
        store.mark_notifications_read(reporter_id, ts, cluster_id=cluster["id"])
    if new_status == ClusterStatus.RESOLVED_VERIFIED:
        store.expire_notifications(cluster["id"])
    _event(
        store, cluster["id"], "citizen_verification", reporter_id or "citizen",
        f"Citizen proof photo: {verdict.value}. {result.explanation}",
        {"verdict": verdict.value, "ai_mode": ai_mode, "status": new_status.value, "gps_distance_m": check.distance_m, "gps_source": check.source},
        ts,
    )
    cluster = rescore(store, cluster)
    return cluster, verification
