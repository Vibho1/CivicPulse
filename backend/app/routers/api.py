"""HTTP API for CivicPulse."""

from __future__ import annotations

import io
import logging
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from ..ai import ResilientAI
from ..ai.audio import probe_duration_s
from ..ai.base import Media
from ..config import Settings
from ..domain import (
    CATEGORY_LABELS,
    CORROBORATE_MAX_M,
    EMERGENCY_MESSAGE,
    EMERGENCY_NUMBER,
    VERIFY_GPS_RADIUS_M,
    Category,
    ClusterStatus,
    agency_from_code,
    meta,
)
from ..geo import haversine_m, load_wards
from ..schemas import EscalationPackageRequest, EscalationRequest, ExternalRefUpdate, Extraction, NotificationsRead, StatusUpdate
from ..services import closure
from ..services.accountability import (
    NothingToEscalate,
    cluster_package,
    draft_escalation,
    find_ward,
    record_external_ref,
    ward_package,
    ward_scorecard,
)
from ..services.common import is_sla_breached, now_iso
from ..services.credibility import reporter_credibility
from ..services.intake import DuplicateSubmission, LowConfidence, NotCivicIssue, ingest, refresh_scores, rescore
from ..services.present import present_cluster, present_event, present_notification, present_report, present_verification
from ..store import Store

log = logging.getLogger(__name__)
router = APIRouter()

DEMO_LOCATIONS = [
    {"name": "ORR service lane, Bellandur (Ecospace)", "lat": 12.9262, "lng": 77.6816},
    {"name": "Koramangala 5th Block (Sony World)", "lat": 12.9345, "lng": 77.6231},
    {"name": "Indiranagar 100 Ft Road", "lat": 12.9719, "lng": 77.6412},
    {"name": "HSR Layout 27th Main", "lat": 12.9116, "lng": 77.6389},
    {"name": "Silk Board Junction", "lat": 12.9172, "lng": 77.6229},
    {"name": "Malleshwaram 8th Cross", "lat": 13.0031, "lng": 77.5643},
    {"name": "Whitefield (ITPL Main Road)", "lat": 12.9698, "lng": 77.7500},
]


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_ai(request: Request) -> ResilientAI:
    return request.app.state.ai


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


MB = 1024 * 1024
MAX_UPLOAD_BYTES = 15 * MB
# PRD: JPEG, PNG or WebP. MPO is how Pillow labels multi-picture JPEGs from some phone cameras.
ALLOWED_IMAGE_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
# MediaRecorder stops on a timer tick, so a "30 s" note can run slightly over.
AUDIO_TOLERANCE_S = 1.5
SYSTEM_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,31}$")


def _media(upload: UploadFile | None, default_mime: str, max_bytes: int = MAX_UPLOAD_BYTES, what: str = "File") -> Media | None:
    if upload is None:
        return None
    data = upload.file.read(max_bytes + 1)
    if not data:
        return None
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"{what} too large (max {max_bytes // MB} MB)")
    return Media(data, upload.content_type or default_mime, upload.filename or "")


def _image(upload: UploadFile | None, settings: Settings) -> Media | None:
    """Read an uploaded photo, enforcing the size cap and the JPEG/PNG/WebP formats."""
    m = _media(upload, "image/jpeg", settings.max_image_mb * MB, "Photo")
    if m is None:
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(m.data)) as im:
            fmt = (im.format or "").upper()
    except Exception:  # noqa: BLE001 - anything Pillow cannot open is rejected below
        fmt = ""
    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(status_code=415, detail="Unsupported image. Upload a JPEG, PNG or WebP photo.")
    return m


def _audio(upload: UploadFile | None, settings: Settings) -> Media | None:
    """Read an uploaded voice note, enforcing the size cap and the duration limit."""
    m = _media(upload, "audio/webm", settings.max_audio_mb * MB, "Voice note")
    if m is None or settings.max_audio_s <= 0:
        return m
    duration = probe_duration_s(m)
    if duration is not None and duration > settings.max_audio_s + AUDIO_TOLERANCE_S:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "audio_too_long",
                "message": f"The voice note is {duration:.0f} s long; please keep it under {settings.max_audio_s} s.",
                "max_audio_s": settings.max_audio_s,
            },
        )
    return m


def _check_coords(lat: float | None, lng: float | None) -> None:
    if (lat is None) != (lng is None) or (lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180)):  # type: ignore[operator]
        raise HTTPException(status_code=422, detail="Invalid coordinates")


def _photo_gps(photo_lat: float | None, photo_lng: float | None) -> tuple[float, float] | None:
    """GPS the client read from the original photo's EXIF (the PWA re-encodes photos, dropping EXIF)."""
    if photo_lat is None and photo_lng is None:
        return None
    if photo_lat is None or photo_lng is None or not (-90 <= photo_lat <= 90 and -180 <= photo_lng <= 180):
        raise HTTPException(status_code=422, detail="Invalid photo coordinates")
    return photo_lat, photo_lng


def _flag(value: str | None) -> bool | None:
    """'1' / 'true' -> True, '0' / 'false' -> False, missing -> None (unknown)."""
    if value is None or value == "":
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


def _base_url(request: Request, settings: Settings) -> str:
    """Absolute base for links in escalation drafts (PUBLIC_BASE_URL, else this request's host)."""
    return (settings.public_base_url or str(request.base_url)).rstrip("/")


def _duplicate(exc: DuplicateSubmission, settings: Settings, corroboration: bool = False) -> HTTPException:
    prev = exc.previous
    label = CATEGORY_LABELS[Category(prev["category"])].lower()
    elapsed = max(0, settings.duplicate_window_s - exc.retry_after_s)
    ago = "a moment ago" if elapsed < 60 else f"{elapsed // 60} min ago"
    if corroboration:
        message = f"You already backed a {label} report here {ago} ({prev['cluster_id']}). One confirmation per person is enough for now."
    else:
        message = (
            f"You already reported a {label} here {ago} ({prev['cluster_id']}). One report per person is enough \u2014 "
            "share the issue so neighbours can tap \u201cI see this too\u201d."
        )
    return HTTPException(
        status_code=429,
        detail={
            "code": "duplicate_submission",
            "message": message,
            "duplicate_of": {"report_id": prev["id"], "cluster_id": prev["cluster_id"], "created_at": prev["created_at"]},
            "retry_after_s": exc.retry_after_s,
        },
        headers={"Retry-After": str(exc.retry_after_s)},
    )


def _cluster_or_404(store: Store, cluster_id: str) -> dict:
    c = store.get_cluster(cluster_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    return c


def _detail(store: Store, c: dict) -> dict:
    prev = store.get_cluster(c["previous_cluster_id"]) if c.get("previous_cluster_id") else None
    cred: dict[str, float] = {}
    return {
        "cluster": present_cluster(c),
        "reports": [
            present_report(r, credibility=reporter_credibility(store, r.get("reporter_id"), cred)) for r in store.reports_for_cluster(c["id"])
        ],
        "verifications": [present_verification(v) for v in store.verifications_for_cluster(c["id"])],
        "events": [present_event(e) for e in store.events_for_cluster(c["id"])],
        "previous_cluster": present_cluster(prev) if prev else None,
    }


# ---------------------------------------------------------------- platform --
@router.get("/health")
def health(request: Request, ai: ResilientAI = Depends(get_ai), store: Store = Depends(get_store)):
    settings = request.app.state.settings
    return {
        "status": "ok",
        "ai_mode": ai.mode,
        "model": ai.model,
        "last_ai_error": ai.last_error,
        "counts": store.counts(),
        "demo_mode": settings.demo_mode,
        "features": {
            "whatsapp": bool(settings.whatsapp_verify_token),
            "public_audio": settings.public_audio,
            # Faces / plates are found by the model; the offline parser cannot detect them.
            "face_blur": ai.primary is not None,
        },
    }


@router.get("/meta")
def get_meta(settings: Settings = Depends(get_settings_dep)):
    m = meta()
    m["wards"] = [w.__dict__ for w in load_wards()]
    m["demo_locations"] = DEMO_LOCATIONS
    m["limits"] = {
        "max_image_mb": settings.max_image_mb,
        "max_audio_mb": settings.max_audio_mb,
        "max_audio_s": settings.max_audio_s,
        "duplicate_window_s": settings.duplicate_window_s,
        "duplicate_radius_m": settings.duplicate_radius_m,
        "verify_gps_radius_m": VERIFY_GPS_RADIUS_M,
        "corroborate_max_m": CORROBORATE_MAX_M,
    }
    return m


@router.get("/stats")
def stats(store: Store = Depends(get_store)):
    return ward_scorecard(store)["city"]


# ----------------------------------------------------------------- reports --
@router.post("/reports", status_code=201)
def create_report(
    request: Request,
    lat: float = Form(...),
    lng: float = Form(...),
    accuracy: float | None = Form(None),
    text: str | None = Form(None),
    reporter_id: str | None = Form(None),
    language_hint: str | None = Form(None),
    photo_exif: str | None = Form(None, description="'1' if the original photo file carried EXIF metadata, '0' if not"),
    photo_lat: float | None = Form(None, description="GPS latitude from the original photo's EXIF"),
    photo_lng: float | None = Form(None, description="GPS longitude from the original photo's EXIF"),
    audio: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
    settings: Settings = Depends(get_settings_dep),
):
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(status_code=422, detail="Invalid coordinates")
    photo_gps = _photo_gps(photo_lat, photo_lng)
    audio_m = _audio(audio, settings)
    photo_m = _image(photo, settings)
    if audio_m is None and photo_m is None and not (text or "").strip():
        raise HTTPException(status_code=422, detail="Provide a voice note, a photo or some text")
    try:
        res = ingest(
            store,
            ai,
            lat=lat,
            lng=lng,
            uploads_dir=settings.uploads_path,
            accuracy=accuracy,
            text=text,
            audio=audio_m,
            photo=photo_m,
            reporter_id=reporter_id,
            language_hint=language_hint,
            duplicate_window_s=settings.duplicate_window_s,
            duplicate_radius_m=settings.duplicate_radius_m,
            photo_exif=_flag(photo_exif),
            photo_gps=photo_gps,
        )
    except NotCivicIssue as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "not_civic_issue", "message": "This does not look like a civic issue.", "extraction": exc.extraction.model_dump(mode="json")},
        ) from exc
    except LowConfidence as exc:
        raise HTTPException(status_code=422, detail={"code": "low_confidence", "message": exc.reason, "extraction": exc.extraction.model_dump(mode="json")}) from exc
    except DuplicateSubmission as exc:
        raise _duplicate(exc, settings) from exc
    return {
        # The reporter gets their own voice note back even when voice notes are not public.
        "report": present_report(res.report, credibility=reporter_credibility(store, reporter_id), include_audio=True),
        "cluster": present_cluster(res.cluster),
        "merged": res.merged,
        "reopened": res.reopened,
        "repeat_failure": res.repeat_failure,
        "previous_cluster": present_cluster(res.previous_cluster) if res.previous_cluster else None,
        "extraction": present_report(res.report)["extraction"],
        "ai_mode": res.ai_mode,
        "location_warning": res.location_warning,
        "emergency": {"is_emergency": True, "number": EMERGENCY_NUMBER, "message": EMERGENCY_MESSAGE} if res.emergency else None,
    }


@router.get("/reports/{report_id}")
def get_report(report_id: str, store: Store = Depends(get_store)):
    r = store.get_report(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    return {
        "report": present_report(r, credibility=reporter_credibility(store, r.get("reporter_id"))),
        "cluster": present_cluster(_cluster_or_404(store, r["cluster_id"])),
    }


# ---------------------------------------------------------------- clusters --
@router.get("/clusters")
def list_clusters(
    status: str | None = Query(None, description="Comma-separated statuses"),
    ward: str | None = None,
    category: str | None = None,
    agency: str | None = Query(None, description="Agency id (GBA_ROADS) or PRD code (BBMP_ROADS)"),
    sla_breached: bool | None = Query(None, description="Only clusters past (true) or within (false) their service target"),
    limit: int = Query(500, le=2000),
    store: Store = Depends(get_store),
):
    refresh_scores(store)
    if agency:
        resolved = agency_from_code(agency)
        agency = resolved.value if resolved else agency
    rows = store.list_clusters(status, ward, category, agency, 5000 if sla_breached is not None else limit)
    if sla_breached is not None:
        rows = [c for c in rows if is_sla_breached(c) == sla_breached][:limit]
    return {"clusters": [present_cluster(c) for c in rows]}


@router.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: str, store: Store = Depends(get_store)):
    return _detail(store, rescore(store, _cluster_or_404(store, cluster_id)))


@router.post("/clusters/{cluster_id}/corroborate", status_code=201)
def corroborate(
    cluster_id: str,
    request: Request,
    lat: float = Form(...),
    lng: float = Form(...),
    accuracy: float | None = Form(None),
    reporter_id: str | None = Form(None),
    text: str | None = Form(None),
    photo: UploadFile | None = File(None),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
    settings: Settings = Depends(get_settings_dep),
):
    """One-tap "I see this too": adds a report to the tapped cluster without a model call."""
    c = _cluster_or_404(store, cluster_id)
    if ClusterStatus(c["status"]) == ClusterStatus.RESOLVED_VERIFIED:
        raise HTTPException(status_code=409, detail="Issue is verified as fixed; please file a fresh report if it has reappeared")
    _check_coords(lat, lng)
    distance = haversine_m(lat, lng, c["lat"], c["lng"])
    slack = min(max(accuracy or 0.0, 0.0), float(CORROBORATE_MAX_M))
    if distance - slack > CORROBORATE_MAX_M:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "too_far",
                "message": (
                    f"You seem to be {distance / 1000:.1f} km from this issue. \u201cI see this too\u201d is for people at the spot "
                    f"(within {CORROBORATE_MAX_M} m); file a new report if you see a similar problem where you are."
                ),
                "distance_m": round(distance),
                "max_distance_m": CORROBORATE_MAX_M,
            },
        )
    extraction = Extraction(
        is_civic_issue=True,
        transcript="",
        transcript_english=text or "Corroboration: issue still present.",
        language="en",
        category=Category(c["category"]),
        severity=c["max_severity"],
        title=c["title"],
        description=text or f"Corroborated by another citizen: {c['title']}",
        landmark=c.get("landmark"),
        hazards=[],
        suggested_agency=None,
        agency_reasoning="corroboration",
        confidence=1.0,
    )
    # Pinned to the issue the citizen tapped (snapped to its location so the pin does not drift).
    try:
        res = ingest(
            store,
            ai,
            lat=c["lat"],
            lng=c["lng"],
            accuracy=accuracy,
            uploads_dir=settings.uploads_path,
            text=text,
            photo=_image(photo, settings),
            reporter_id=reporter_id,
            is_corroboration=True,
            extraction_override=extraction,
            ai_mode_override="corroboration",
            duplicate_window_s=settings.duplicate_window_s,
            duplicate_radius_m=settings.duplicate_radius_m,
            target_cluster=c,
            citizen_distance_m=distance,
        )
    except DuplicateSubmission as exc:
        raise _duplicate(exc, settings, corroboration=True) from exc
    return {"cluster": present_cluster(res.cluster), "merged": res.merged, "report": present_report(res.report)}


@router.post("/clusters/{cluster_id}/status")
def update_status(cluster_id: str, body: StatusUpdate, store: Store = Depends(get_store)):
    c = _cluster_or_404(store, cluster_id)
    try:
        c = closure.set_status(store, c, ClusterStatus(body.status), body.note, body.actor or "official")
    except closure.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _detail(store, c)


@router.post("/clusters/{cluster_id}/resolve")
def resolve_cluster(
    cluster_id: str,
    request: Request,
    note: str | None = Form(None),
    actor: str | None = Form("ward-engineer"),
    lat: float | None = Form(None, description="Device position when the after-photo was taken (used only if the photo has no GPS)"),
    lng: float | None = Form(None),
    accuracy: float | None = Form(None),
    photo_exif: str | None = Form(None, description="'1' if the original photo file carried EXIF metadata"),
    photo_lat: float | None = Form(None, description="GPS latitude from the original photo's EXIF"),
    photo_lng: float | None = Form(None, description="GPS longitude from the original photo's EXIF"),
    after_photo: UploadFile | None = File(None),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
    settings: Settings = Depends(get_settings_dep),
):
    c = _cluster_or_404(store, cluster_id)
    _check_coords(lat, lng)
    photo_gps = _photo_gps(photo_lat, photo_lng)
    try:
        c, verification = closure.resolve(
            store, ai, c,
            uploads_dir=settings.uploads_path,
            after_photo=_image(after_photo, settings),
            note=note,
            actor=actor or "official",
            capture_lat=lat,
            capture_lng=lng,
            capture_accuracy=accuracy,
            photo_gps=photo_gps,
            notifier=request.app.state.notifier,
        )
    except closure.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = _detail(store, c)
    out["verification"] = present_verification(verification)
    return out


@router.post("/clusters/{cluster_id}/verify")
def verify_cluster(
    cluster_id: str,
    request: Request,
    reporter_id: str | None = Form(None),
    note: str | None = Form(None),
    lat: float | None = Form(None, description="Device position when the proof photo was taken (used only if the photo has no GPS)"),
    lng: float | None = Form(None),
    accuracy: float | None = Form(None),
    photo_exif: str | None = Form(None, description="'1' if the original photo file carried EXIF metadata"),
    photo_lat: float | None = Form(None, description="GPS latitude from the original photo's EXIF"),
    photo_lng: float | None = Form(None, description="GPS longitude from the original photo's EXIF"),
    photo: UploadFile = File(...),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
    settings: Settings = Depends(get_settings_dep),
):
    c = _cluster_or_404(store, cluster_id)
    _check_coords(lat, lng)
    photo_gps = _photo_gps(photo_lat, photo_lng)
    photo_m = _image(photo, settings)
    if photo_m is None:
        raise HTTPException(status_code=422, detail="A photo is required for verification")
    try:
        c, verification = closure.citizen_verify(
            store, ai, c,
            uploads_dir=settings.uploads_path,
            photo=photo_m,
            reporter_id=reporter_id,
            note=note,
            capture_lat=lat,
            capture_lng=lng,
            capture_accuracy=accuracy,
            photo_gps=photo_gps,
        )
    except closure.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = _detail(store, c)
    out["verification"] = present_verification(verification)
    return out


@router.post("/clusters/{cluster_id}/escalate")
def escalate(
    cluster_id: str,
    body: EscalationRequest,
    request: Request,
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
    settings: Settings = Depends(get_settings_dep),
):
    c = _cluster_or_404(store, cluster_id)
    return draft_escalation(store, ai, c, body.channel, body.requester_name, use_ai=body.ai, base_url=_base_url(request, settings))


@router.post("/clusters/{cluster_id}/escalation-package")
def escalation_package(
    cluster_id: str,
    body: EscalationPackageRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings_dep),
):
    """PRD escalation package (email + X post + RTI) for one issue, from templates in milliseconds."""
    c = _cluster_or_404(store, cluster_id)
    return cluster_package(store, rescore(store, c), body.requester_name, _base_url(request, settings))


@router.post("/clusters/{cluster_id}/external-ref")
def set_external_ref(cluster_id: str, body: ExternalRefUpdate, store: Store = Depends(get_store)):
    """Record the ticket number from an official channel (assisted filing, e.g. Sahaaya)."""
    c = _cluster_or_404(store, cluster_id)
    system, ref = body.system.strip().lower(), body.ref.strip()
    if not ref or not SYSTEM_RE.match(system):
        raise HTTPException(status_code=422, detail="Give the official system (e.g. 'sahaaya') and a non-empty ticket number")
    c = record_external_ref(store, c, system, ref, body.actor or "citizen")
    return _detail(store, c)


# ----------------------------------------------------------- notifications --
@router.get("/notifications")
def list_notifications(
    recipient: str = Query(..., min_length=1, max_length=128, description="Reporter id"),
    include_read: bool = False,
    limit: int = Query(50, ge=1, le=200),
    store: Store = Depends(get_store),
):
    """In-app inbox: proof-photo requests for a reporter."""
    rows = store.notifications_for(recipient, include_read, limit)
    clusters = {cid: store.get_cluster(cid) for cid in {n["cluster_id"] for n in rows}}
    return {
        "notifications": [present_notification(n, clusters.get(n["cluster_id"])) for n in rows],
        "unread": store.unread_count(recipient),
    }


@router.post("/notifications/read")
def mark_notifications_read(body: NotificationsRead, store: Store = Depends(get_store)):
    updated = store.mark_notifications_read(body.recipient, now_iso(), ids=body.ids)
    return {"updated": updated, "unread": store.unread_count(body.recipient)}


# ------------------------------------------------------------------- wards --
@router.get("/wards/scorecard")
def scorecard(store: Store = Depends(get_store)):
    refresh_scores(store)
    return ward_scorecard(store)


@router.post("/wards/{ward}/escalation-package")
def ward_escalation_package(
    ward: str,
    body: EscalationPackageRequest,
    request: Request,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings_dep),
):
    """PRD escalation package for a ward (name or number): its Unverified closures and SLA-breached issues."""
    w = find_ward(ward)
    if w is None:
        raise HTTPException(status_code=404, detail=f"Ward {ward} not found")
    refresh_scores(store)
    try:
        return ward_package(store, w, body.requester_name, _base_url(request, settings))
    except NothingToEscalate as exc:
        raise HTTPException(status_code=409, detail={"code": "nothing_to_escalate", "message": str(exc)}) from exc


# ------------------------------------------------------------------- admin --
@router.post("/admin/seed")
def seed(request: Request, reset: bool = True, store: Store = Depends(get_store)):
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=403, detail="Seeding is only available in demo mode")
    from ..demo import seed_demo

    summary = seed_demo(store, request.app.state.settings.uploads_path, reset=reset)
    return summary


@router.post("/admin/reset")
def reset(request: Request, store: Store = Depends(get_store)):
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=403, detail="Reset is only available in demo mode")
    store.reset()
    return {"status": "reset"}
