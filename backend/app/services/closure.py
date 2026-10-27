"""Closure lifecycle: status changes, official resolution, AI closure check,
citizen verification and dispute handling."""

from __future__ import annotations

from pathlib import Path

from ..ai import ResilientAI
from ..ai.base import Media
from ..domain import CATEGORY_LABELS, Category, ClusterStatus, Verdict
from ..geo import normalise_photo
from ..schemas import VerificationResult
from ..store import Store
from .common import new_id, now_iso
from .intake import rescore

RESOLVABLE = {ClusterStatus.OPEN, ClusterStatus.IN_PROGRESS, ClusterStatus.CLOSURE_DISPUTED}
VERIFIABLE = {ClusterStatus.RESOLVED_PENDING_VERIFICATION, ClusterStatus.CLOSURE_DISPUTED}


class InvalidTransition(Exception):
    pass


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


def _store_verification(store: Store, cluster: dict, kind: str, actor: str, photo_path: str | None, before_paths: list[str], result: VerificationResult, ai_mode: str, note: str | None, ts: str) -> dict:
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
) -> tuple[dict, dict]:
    """Official marks the issue resolved. Runs the AI closure check if a photo is given."""
    current = ClusterStatus(cluster["status"])
    if current not in RESOLVABLE:
        raise InvalidTransition(f"Cannot resolve a cluster in status {current.value}")
    ts = ts or now_iso()
    after_path = None
    before_media, before_paths = _before_photos(store, cluster, uploads_dir)

    if after_photo is None:
        result, ai_mode = no_proof_result(), "rule"
    else:
        data, mime = normalise_photo(after_photo.data)
        after_path = f"{cluster['id']}-after-{ts[:19].replace(':', '').replace('-', '')}.jpg"
        (uploads_dir / after_path).write_bytes(data)
        if result_override is not None:
            result, ai_mode = result_override, "seed"
        elif not before_media:
            result, ai_mode = VerificationResult(
                same_location=False, same_location_confidence=0.0, issue_resolved=False, resolution_confidence=0.0,
                fix_quality="unknown", verdict=Verdict.INCONCLUSIVE,
                explanation="No before-photo on record to compare against; awaiting citizen confirmation.",
            ), "rule"
        else:
            result, ai_mode = ai.verify(before_media, Media(data, mime, "after"), _context_text(cluster))

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
    verification = _store_verification(store, cluster, "official_closure", actor, after_path, before_paths, result, ai_mode, note, ts)
    _event(store, cluster["id"], "resolved", actor, note or "Marked resolved by official", {"after_photo": after_path}, ts)
    _event(
        store, cluster["id"], "closure_check", "ai" if ai_mode.startswith("gemini") else ai_mode,
        f"Closure check: {verdict.value}. {result.explanation}",
        {"verdict": verdict.value, "fix_quality": result.fix_quality, "ai_mode": ai_mode}, ts,
    )
    cluster = rescore(store, cluster)
    return cluster, verification


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
) -> tuple[dict, dict]:
    """A citizen submits a fresh photo after an official closure."""
    current = ClusterStatus(cluster["status"])
    if current not in VERIFIABLE:
        raise InvalidTransition(f"Citizen verification only applies to closed-but-unverified issues (status {current.value})")
    ts = ts or now_iso()
    data, mime = normalise_photo(photo.data)
    path = f"{cluster['id']}-verify-{ts[:19].replace(':', '').replace('-', '')}.jpg"
    (uploads_dir / path).write_bytes(data)
    before_media, before_paths = _before_photos(store, cluster, uploads_dir)
    if result_override is not None:
        result, ai_mode = result_override, "seed"
    elif before_media:
        result, ai_mode = ai.verify(before_media, Media(data, mime, "citizen"), _context_text(cluster))
    else:
        result, ai_mode = VerificationResult(
            same_location=True, same_location_confidence=0.0, issue_resolved=False, resolution_confidence=0.0,
            fix_quality="unknown", verdict=Verdict.INCONCLUSIVE, explanation="No before-photo to compare with.",
        ), "rule"

    verdict = Verdict(result.verdict)
    new_status = current
    if verdict == Verdict.VERIFIED:
        new_status = ClusterStatus.RESOLVED_VERIFIED
    elif verdict in (Verdict.UNVERIFIED_NOT_FIXED, Verdict.UNVERIFIED_COSMETIC):
        new_status = ClusterStatus.CLOSURE_DISPUTED

    updates = dict(status=new_status.value, updated_at=ts, verification_verdict=verdict.value)
    if new_status == ClusterStatus.RESOLVED_VERIFIED:
        updates["verified_at"] = ts
    store.update_cluster(cluster["id"], **updates)
    cluster.update(updates)
    verification = _store_verification(store, cluster, "citizen", reporter_id or "citizen", path, before_paths, result, ai_mode, note, ts)
    _event(
        store, cluster["id"], "citizen_verification", reporter_id or "citizen",
        f"Citizen proof photo: {verdict.value}. {result.explanation}",
        {"verdict": verdict.value, "ai_mode": ai_mode, "status": new_status.value}, ts,
    )
    cluster = rescore(store, cluster)
    return cluster, verification
