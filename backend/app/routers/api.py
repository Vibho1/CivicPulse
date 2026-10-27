"""HTTP API for CivicPulse."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from ..ai import ResilientAI
from ..ai.base import Media
from ..domain import Category, ClusterStatus, meta
from ..geo import load_wards
from ..schemas import EscalationRequest, Extraction, StatusUpdate
from ..services import closure
from ..services.accountability import draft_escalation, ward_scorecard
from ..services.intake import LowConfidence, NotCivicIssue, ingest, refresh_scores, rescore
from ..services.present import present_cluster, present_event, present_report, present_verification
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


MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _media(upload: UploadFile | None, default_mime: str) -> Media | None:
    if upload is None:
        return None
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        return None
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    return Media(data, upload.content_type or default_mime, upload.filename or "")


def _cluster_or_404(store: Store, cluster_id: str) -> dict:
    c = store.get_cluster(cluster_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    return c


def _detail(store: Store, c: dict) -> dict:
    prev = store.get_cluster(c["previous_cluster_id"]) if c.get("previous_cluster_id") else None
    return {
        "cluster": present_cluster(c),
        "reports": [present_report(r) for r in store.reports_for_cluster(c["id"])],
        "verifications": [present_verification(v) for v in store.verifications_for_cluster(c["id"])],
        "events": [present_event(e) for e in store.events_for_cluster(c["id"])],
        "previous_cluster": present_cluster(prev) if prev else None,
    }


# ---------------------------------------------------------------- platform --
@router.get("/health")
def health(request: Request, ai: ResilientAI = Depends(get_ai), store: Store = Depends(get_store)):
    return {
        "status": "ok",
        "ai_mode": ai.mode,
        "model": ai.model,
        "last_ai_error": ai.last_error,
        "counts": store.counts(),
        "demo_mode": request.app.state.settings.demo_mode,
    }


@router.get("/meta")
def get_meta():
    m = meta()
    m["wards"] = [w.__dict__ for w in load_wards()]
    m["demo_locations"] = DEMO_LOCATIONS
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
    audio: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
):
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(status_code=422, detail="Invalid coordinates")
    audio_m = _media(audio, "audio/webm")
    photo_m = _media(photo, "image/jpeg")
    if audio_m is None and photo_m is None and not (text or "").strip():
        raise HTTPException(status_code=422, detail="Provide a voice note, a photo or some text")
    try:
        res = ingest(
            store,
            ai,
            lat=lat,
            lng=lng,
            uploads_dir=request.app.state.settings.uploads_path,
            accuracy=accuracy,
            text=text,
            audio=audio_m,
            photo=photo_m,
            reporter_id=reporter_id,
            language_hint=language_hint,
        )
    except NotCivicIssue as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "This does not look like a civic issue.", "extraction": exc.extraction.model_dump(mode="json")},
        ) from exc
    except LowConfidence as exc:
        raise HTTPException(status_code=422, detail={"message": exc.reason, "extraction": exc.extraction.model_dump(mode="json")}) from exc
    return {
        "report": present_report(res.report),
        "cluster": present_cluster(res.cluster),
        "merged": res.merged,
        "reopened": res.reopened,
        "repeat_failure": res.repeat_failure,
        "previous_cluster": present_cluster(res.previous_cluster) if res.previous_cluster else None,
        "extraction": res.extraction.model_dump(mode="json"),
        "ai_mode": res.ai_mode,
        "location_warning": res.location_warning,
    }


@router.get("/reports/{report_id}")
def get_report(report_id: str, store: Store = Depends(get_store)):
    r = store.get_report(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": present_report(r), "cluster": present_cluster(_cluster_or_404(store, r["cluster_id"]))}


# ---------------------------------------------------------------- clusters --
@router.get("/clusters")
def list_clusters(
    status: str | None = Query(None, description="Comma-separated statuses"),
    ward: str | None = None,
    category: str | None = None,
    agency: str | None = None,
    limit: int = Query(500, le=2000),
    store: Store = Depends(get_store),
):
    refresh_scores(store)
    return {"clusters": [present_cluster(c) for c in store.list_clusters(status, ward, category, agency, limit)]}


@router.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: str, store: Store = Depends(get_store)):
    return _detail(store, rescore(store, _cluster_or_404(store, cluster_id)))


@router.post("/clusters/{cluster_id}/corroborate", status_code=201)
def corroborate(
    cluster_id: str,
    request: Request,
    lat: float = Form(...),
    lng: float = Form(...),
    reporter_id: str | None = Form(None),
    text: str | None = Form(None),
    photo: UploadFile | None = File(None),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
):
    """One-tap "I see this too": adds a report to the cluster without a model call."""
    c = _cluster_or_404(store, cluster_id)
    if ClusterStatus(c["status"]) == ClusterStatus.RESOLVED_VERIFIED:
        raise HTTPException(status_code=409, detail="Issue is verified as fixed; please file a fresh report if it has reappeared")
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
    # Snap to the cluster location if the citizen is within the merge radius; else use their position.
    res = ingest(
        store,
        ai,
        lat=lat,
        lng=lng,
        uploads_dir=request.app.state.settings.uploads_path,
        text=text,
        photo=_media(photo, "image/jpeg"),
        reporter_id=reporter_id,
        is_corroboration=True,
        extraction_override=extraction,
        ai_mode_override="corroboration",
    )
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
    after_photo: UploadFile | None = File(None),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
):
    c = _cluster_or_404(store, cluster_id)
    try:
        c, verification = closure.resolve(
            store, ai, c,
            uploads_dir=request.app.state.settings.uploads_path,
            after_photo=_media(after_photo, "image/jpeg"),
            note=note,
            actor=actor or "official",
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
    photo: UploadFile = File(...),
    store: Store = Depends(get_store),
    ai: ResilientAI = Depends(get_ai),
):
    c = _cluster_or_404(store, cluster_id)
    photo_m = _media(photo, "image/jpeg")
    if photo_m is None:
        raise HTTPException(status_code=422, detail="A photo is required for verification")
    try:
        c, verification = closure.citizen_verify(
            store, ai, c,
            uploads_dir=request.app.state.settings.uploads_path,
            photo=photo_m,
            reporter_id=reporter_id,
            note=note,
        )
    except closure.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = _detail(store, c)
    out["verification"] = present_verification(verification)
    return out


@router.post("/clusters/{cluster_id}/escalate")
def escalate(cluster_id: str, body: EscalationRequest, store: Store = Depends(get_store), ai: ResilientAI = Depends(get_ai)):
    c = _cluster_or_404(store, cluster_id)
    return draft_escalation(store, ai, c, body.channel, body.requester_name)


# ------------------------------------------------------------------- wards --
@router.get("/wards/scorecard")
def scorecard(store: Store = Depends(get_store)):
    refresh_scores(store)
    return ward_scorecard(store)


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
