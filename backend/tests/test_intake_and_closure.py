from __future__ import annotations

from datetime import timedelta

from app.ai.base import Media
from app.domain import ClusterStatus, Verdict
from app.schemas import EvidenceFlags, Extraction, VerificationResult
from app.services import closure
from app.services.common import now_utc, to_iso
from app.services.intake import ingest

ORR = (12.92620, 77.68160)


def ex(category="pothole", severity=3, **kw) -> Extraction:
    base = dict(is_civic_issue=True, transcript="", transcript_english="x", language="en", category=category,
                severity=severity, title=f"{category} test", description="d", hazards=[], evidence=EvidenceFlags(), confidence=0.9)
    base.update(kw)
    return Extraction(**base)


def submit(store, ai, uploads, lat, lng, extraction=None, when=None, photo=None, text=None, **kw):
    return ingest(store, ai, lat=lat, lng=lng, uploads_dir=uploads, extraction_override=extraction, created_at=when, photo=photo, text=text, **kw)


def test_nearby_same_category_reports_merge(store, ai, uploads):
    r1 = submit(store, ai, uploads, *ORR, ex())
    r2 = submit(store, ai, uploads, ORR[0] + 0.0002, ORR[1], ex(severity=5))  # ~22 m north
    assert r2.merged and r2.cluster["id"] == r1.cluster["id"]
    c = store.get_cluster(r1.cluster["id"])
    assert c["report_count"] == 2
    assert c["max_severity"] == 5
    assert c["impact_score"] > r1.cluster["impact_score"]
    assert len(store.reports_for_cluster(c["id"])) == 2


def test_far_or_different_category_creates_new_cluster(store, ai, uploads):
    r1 = submit(store, ai, uploads, *ORR, ex())
    far = submit(store, ai, uploads, ORR[0] + 0.002, ORR[1], ex())  # ~220 m
    other = submit(store, ai, uploads, *ORR, ex(category="garbage"))
    assert not far.merged and far.cluster["id"] != r1.cluster["id"]
    assert not other.merged and other.cluster["id"] != r1.cluster["id"]


def test_heuristic_text_report_end_to_end(store, ai, uploads):
    r = submit(store, ai, uploads, *ORR, None, text="ORR service lane alli dodda gundi ide near Ecospace, BWSSB pipeline work")
    assert r.cluster["category"] == "pothole"
    assert r.cluster["agency"] == "BWSSB"
    assert r.cluster["ward"] == "Bellandur"
    assert r.report["language"] == "kn-en"
    assert r.ai_mode == "heuristic"


def test_new_report_after_unverified_closure_disputes_it(store, ai, uploads, jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex())
    c, v = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=None, note=None, actor="eng")
    assert c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value
    assert v["verdict"] == Verdict.NO_PROOF_PROVIDED.value
    r2 = submit(store, ai, uploads, *ORR, ex())
    assert r2.merged and r2.reopened
    assert store.get_cluster(c["id"])["status"] == ClusterStatus.CLOSURE_DISPUTED.value


def test_repeat_failure_links_to_previous_verified_cluster(store, ai, uploads, jpeg):
    old_time = to_iso(now_utc() - timedelta(days=40))
    r1 = submit(store, ai, uploads, *ORR, ex(), when=old_time, photo=Media(jpeg, "image/jpeg"))
    c = store.get_cluster(r1.cluster["id"])
    ok = VerificationResult(same_location=True, same_location_confidence=0.9, issue_resolved=True, resolution_confidence=0.9,
                            fix_quality="proper", verdict=Verdict.VERIFIED, explanation="fixed")
    c, _ = closure.resolve(store, ai, c, uploads_dir=uploads, after_photo=Media(jpeg, "image/jpeg"), note=None, actor="eng",
                           ts=to_iso(now_utc() - timedelta(days=38)), result_override=ok)
    assert c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value
    c, _ = closure.citizen_verify(store, ai, c, uploads_dir=uploads, photo=Media(jpeg, "image/jpeg"), reporter_id="x", note=None,
                                  ts=to_iso(now_utc() - timedelta(days=37)), result_override=ok)
    assert c["status"] == ClusterStatus.RESOLVED_VERIFIED.value

    r2 = submit(store, ai, uploads, *ORR, ex())
    assert not r2.merged
    assert r2.repeat_failure and r2.previous_cluster["id"] == c["id"]
    new = store.get_cluster(r2.cluster["id"])
    assert new["repeat_failure"] == 1 and new["previous_cluster_id"] == c["id"]
    assert any(comp["component"] == "repeat_failure" for comp in new["score_breakdown_json"]["components"])


def test_fake_closure_is_disputed_and_cannot_be_reopened_manually(store, ai, uploads, jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), photo=Media(jpeg, "image/jpeg"))
    bad = VerificationResult(same_location=False, same_location_confidence=0.1, issue_resolved=False, resolution_confidence=0.1,
                             fix_quality="unknown", verdict=Verdict.UNVERIFIED_DIFFERENT_LOCATION, explanation="different wall")
    c, v = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=Media(jpeg, "image/jpeg"),
                           note="done", actor="eng", result_override=bad)
    assert c["status"] == ClusterStatus.CLOSURE_DISPUTED.value
    assert c["closure_count"] == 1
    # official can take it back to in-progress and try again
    c = closure.set_status(store, c, ClusterStatus.IN_PROGRESS, None, "eng")
    assert c["status"] == ClusterStatus.IN_PROGRESS.value
    types = [e["type"] for e in store.events_for_cluster(c["id"])]
    assert types == ["reported", "resolved", "closure_check", "status_changed"]
