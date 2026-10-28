from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.ai.base import Media
from app.domain import ClusterStatus, Verdict
from app.schemas import EvidenceFlags, Extraction, VerificationResult
from app.services import closure
from app.services.accountability import ward_scorecard
from app.services.common import now_utc, to_iso
from app.services.intake import DuplicateSubmission, ingest
from app.services.notify import Notifier
from app.store import MIGRATIONS, SCHEMA, Store

ORR = (12.92620, 77.68160)
DUP = dict(duplicate_window_s=300, duplicate_radius_m=1000)  # the API's defaults (PRD: 5 min / 1 km)


def ex(category="pothole", severity=3, **kw) -> Extraction:
    base = dict(is_civic_issue=True, transcript="", transcript_english="x", language="en", category=category,
                severity=severity, title=f"{category} test", description="d", hazards=[], evidence=EvidenceFlags(), confidence=0.9)
    base.update(kw)
    return Extraction(**base)


def verdict(v: Verdict = Verdict.VERIFIED) -> VerificationResult:
    ok = v == Verdict.VERIFIED
    return VerificationResult(same_location=True, same_location_confidence=0.9, issue_resolved=ok, resolution_confidence=0.9,
                              fix_quality="proper" if ok else "none", verdict=v, explanation="model says so")


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
    other = submit(store, ai, uploads, *ORR, ex(category="garbage_dump"))
    assert not far.merged and far.cluster["id"] != r1.cluster["id"]
    assert not other.merged and other.cluster["id"] != r1.cluster["id"]


def test_merge_radius_is_the_prds_50_m(store, ai, uploads):
    r1 = submit(store, ai, uploads, *ORR, ex())
    near = submit(store, ai, uploads, ORR[0] + 0.0004, ORR[1], ex())  # ~44 m
    assert near.merged and near.cluster["id"] == r1.cluster["id"]
    beyond = submit(store, ai, uploads, ORR[0] - 0.00052, ORR[1], ex(category="waterlogging"))  # waterlogging too: no wider radius
    submit(store, ai, uploads, ORR[0] - 0.00052 - 0.0005, ORR[1], ex(category="waterlogging"))  # ~56 m from it
    assert len({c["id"] for c in store.all_clusters() if c["category"] == "waterlogging"}) == 2
    assert not beyond.merged


def test_heuristic_text_report_end_to_end(store, ai, uploads):
    r = submit(store, ai, uploads, *ORR, None, text="ORR service lane alli dodda gundi ide near Ecospace, BWSSB pipeline work")
    assert r.cluster["category"] == "pothole"
    assert r.cluster["agency"] == "BWSSB"
    assert r.cluster["secondary_agency"] == "GBA_ROADS"
    assert 0 < r.cluster["routing_confidence"] <= 1
    assert r.report["secondary_agency"] == "GBA_ROADS" and r.report["routing_confidence"] == r.cluster["routing_confidence"]
    assert r.cluster["ward"] == "Bellandur"
    assert r.report["language"] == "kn-en"
    assert r.ai_mode == "heuristic"


def test_same_citizen_reporting_twice_counts_as_one_reporter(store, ai, uploads):
    r1 = submit(store, ai, uploads, *ORR, ex(), reporter_id="u1")
    submit(store, ai, uploads, ORR[0] + 0.0001, ORR[1], ex(), reporter_id="u1")
    submit(store, ai, uploads, ORR[0] + 0.0001, ORR[1], ex(), reporter_id="u2")
    submit(store, ai, uploads, ORR[0] + 0.0001, ORR[1], ex())  # anonymous reports count individually
    c = store.get_cluster(r1.cluster["id"])
    assert (c["report_count"], c["reporter_count"]) == (4, 3)
    unique = next(x for x in c["score_breakdown_json"]["components"] if x["component"] == "unique_reporters")
    assert unique["reason"] == "3 independent citizens (4 reports)"


def test_duplicate_submission_from_same_reporter_is_rejected(store, ai, uploads, jpeg):
    t0 = now_utc()
    first = submit(store, ai, uploads, *ORR, ex(), when=to_iso(t0 - timedelta(minutes=2)), reporter_id="u1", **DUP)
    with pytest.raises(DuplicateSubmission) as err:  # same person, same issue type, ~330 m away, 2 min later
        submit(store, ai, uploads, ORR[0] + 0.003, ORR[1], ex(), when=to_iso(t0), reporter_id="u1", photo=Media(jpeg, "image/jpeg"), **DUP)
    assert err.value.previous["id"] == first.report["id"]
    assert 170 <= err.value.retry_after_s <= 180
    assert list(uploads.iterdir()) == []  # a rejected upload is never written to disk
    assert len(store.reports_for_cluster(first.cluster["id"])) == 1

    # not duplicates: another issue type, another citizen, >1 km away, or after the window
    submit(store, ai, uploads, *ORR, ex(category="garbage_dump"), when=to_iso(t0), reporter_id="u1", **DUP)
    submit(store, ai, uploads, *ORR, ex(), when=to_iso(t0), reporter_id="u2", **DUP)
    submit(store, ai, uploads, ORR[0] + 0.02, ORR[1], ex(), when=to_iso(t0), reporter_id="u1", **DUP)  # ~2.2 km
    submit(store, ai, uploads, *ORR, ex(), when=to_iso(t0 + timedelta(minutes=4)), reporter_id="u1", **DUP)
    # the guard is opt-in: seeds and internal callers pass no window
    submit(store, ai, uploads, *ORR, ex(), when=to_iso(t0 + timedelta(minutes=4, seconds=5)), reporter_id="u1")


def test_new_report_after_unverified_closure_disputes_it(store, ai, uploads, jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), reporter_id="u1")
    c, v = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=None, note=None, actor="eng")
    assert c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value
    assert v["verdict"] == Verdict.NO_PROOF_PROVIDED.value
    assert store.unread_count("u1") == 1  # asked for a proof photo
    r2 = submit(store, ai, uploads, *ORR, ex(), reporter_id="u1")
    assert r2.merged and r2.reopened
    assert store.get_cluster(c["id"])["status"] == ClusterStatus.CLOSURE_DISPUTED.value
    assert store.unread_count("u1") == 0  # re-reporting answered the request


def _verified_cluster(store, ai, uploads, jpeg, at=ORR):
    r1 = submit(store, ai, uploads, *at, ex(), when=to_iso(now_utc() - timedelta(days=40)), photo=Media(jpeg, "image/jpeg"))
    c = store.get_cluster(r1.cluster["id"])
    ok = verdict()
    c, _ = closure.resolve(store, ai, c, uploads_dir=uploads, after_photo=Media(jpeg, "image/jpeg"), note=None, actor="eng",
                           ts=to_iso(now_utc() - timedelta(days=38)), result_override=ok)
    assert c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value
    c, _ = closure.citizen_verify(store, ai, c, uploads_dir=uploads, photo=Media(jpeg, "image/jpeg"), reporter_id="x", note=None,
                                  ts=to_iso(now_utc() - timedelta(days=37)), result_override=ok)
    assert c["status"] == ClusterStatus.RESOLVED_VERIFIED.value
    return c


def test_repeat_failure_links_to_previous_verified_cluster(store, ai, uploads, jpeg):
    c = _verified_cluster(store, ai, uploads, jpeg)
    r2 = submit(store, ai, uploads, ORR[0] + 0.00015, ORR[1], ex())  # ~17 m
    assert not r2.merged
    assert r2.repeat_failure and r2.previous_cluster["id"] == c["id"]
    new = store.get_cluster(r2.cluster["id"])
    assert new["repeat_failure"] == 1 and new["previous_cluster_id"] == c["id"]
    assert "recurring" in new["hazards_json"]
    assert any(e["type"] == "repeat_failure_flagged" for e in store.events_for_cluster(new["id"]))


def test_repeat_failure_only_within_25_m(store, ai, uploads, jpeg):
    _verified_cluster(store, ai, uploads, jpeg)
    r2 = submit(store, ai, uploads, ORR[0] + 0.0003, ORR[1], ex())  # ~33 m: a different spot (PRD 25 m)
    assert not r2.repeat_failure and r2.previous_cluster is None


def test_fake_closure_is_disputed_and_cannot_be_reopened_manually(store, ai, uploads, jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), photo=Media(jpeg, "image/jpeg"), reporter_id="u1")
    bad = VerificationResult(same_location=False, same_location_confidence=0.1, issue_resolved=False, resolution_confidence=0.1,
                             fix_quality="unknown", verdict=Verdict.UNVERIFIED_DIFFERENT_LOCATION, explanation="different wall")
    c, v = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=Media(jpeg, "image/jpeg"),
                           note="done", actor="eng", result_override=bad)
    assert c["status"] == ClusterStatus.CLOSURE_DISPUTED.value
    assert c["closure_count"] == 1
    assert store.unread_count("u1") == 1
    # official can take it back to in-progress and try again; outstanding proof requests are withdrawn
    c = closure.set_status(store, c, ClusterStatus.IN_PROGRESS, None, "eng")
    assert c["status"] == ClusterStatus.IN_PROGRESS.value
    assert store.unread_count("u1") == 0
    types = [e["type"] for e in store.events_for_cluster(c["id"])]
    assert types == ["reported", "resolved", "closure_check", "verification_requested", "status_changed"]


# --------------------------------------------------------- GPS closure proof --


def test_after_photo_taken_far_away_disputes_the_closure(store, ai, uploads, jpeg, gps_jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), photo=Media(jpeg, "image/jpeg"))
    far = gps_jpeg(ORR[0] + 0.0072, ORR[1])  # ~800 m north
    # even if the model were fooled by a similar-looking street, GPS more than 50 m away decides
    c, v = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=Media(far, "image/jpeg"),
                           note="done", actor="eng", result_override=verdict())
    assert c["status"] == ClusterStatus.CLOSURE_DISPUTED.value
    assert v["verdict"] == Verdict.UNVERIFIED_DIFFERENT_LOCATION.value
    assert (v["location_match"], v["gps_source"], v["ai_mode"]) == (0, "exif", "rule")
    assert 750 < v["gps_distance_m"] < 850
    assert "limit 50 m" in v["explanation"]
    bellandur = next(w for w in ward_scorecard(store)["wards"] if w["ward"] == "Bellandur")
    assert bellandur["closure_disputed"] == 1 and bellandur["unverified_closure_rate"] == 100.0


def test_after_photo_on_the_spot_keeps_the_model_verdict(store, ai, uploads, jpeg, gps_jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), photo=Media(jpeg, "image/jpeg"))
    near = gps_jpeg(ORR[0] + 0.0002, ORR[1])  # ~22 m
    c, v = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=Media(near, "image/jpeg"),
                           note="done", actor="eng", result_override=verdict())
    assert c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value
    assert v["verdict"] == Verdict.VERIFIED.value and v["location_match"] == 1
    assert v["gps_distance_m"] < 50
    assert v["raw_json"]["matched_cues"][0].startswith("photo embedded GPS")


def test_gps_check_prefers_exif_and_allows_device_accuracy(store, ai, uploads, jpeg, gps_jpeg):
    cluster = store.get_cluster(submit(store, ai, uploads, *ORR, ex()).cluster["id"])
    assert closure.gps_check(cluster, jpeg) == closure.GpsCheck()  # no evidence either way
    # device position ~70 m away: fails alone, passes when its 30 m accuracy is allowed for
    assert closure.gps_check(cluster, jpeg, ORR[0] + 0.00063, ORR[1]).ok is False
    assert closure.gps_check(cluster, jpeg, ORR[0] + 0.00063, ORR[1], 30).ok is True
    # EXIF (where the photo was taken) beats where the phone is when uploading
    chk = closure.gps_check(cluster, gps_jpeg(ORR[0] + 0.0072, ORR[1]), *ORR, 5)
    assert chk.source == "exif" and chk.ok is False


def test_citizen_proof_photo_from_elsewhere_marks_closure_unverified(store, ai, uploads, gps_jpeg):
    # PRD AC-4: Pending Verification + an after-photo that is not the spot -> Unverified Closure
    r1 = submit(store, ai, uploads, *ORR, ex())
    c, _ = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=None, note=None, actor="eng")
    c, v = closure.citizen_verify(store, ai, c, uploads_dir=uploads, photo=Media(gps_jpeg(ORR[0] + 0.0072, ORR[1]), "image/jpeg"),
                                  reporter_id="u9", note=None, result_override=verdict())
    assert v["verdict"] == Verdict.UNVERIFIED_DIFFERENT_LOCATION.value and v["location_match"] == 0
    assert c["status"] == ClusterStatus.CLOSURE_DISPUTED.value
    bellandur = next(w for w in ward_scorecard(store)["wards"] if w["ward"] == "Bellandur")
    assert bellandur["closure_disputed"] == 1


def test_citizen_photo_with_mismatched_landmarks_marks_closure_unverified(store, ai, uploads, jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), photo=Media(jpeg, "image/jpeg"))
    c, _ = closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=None, note=None, actor="eng")
    mismatch = VerificationResult(same_location=False, same_location_confidence=0.1, issue_resolved=False, resolution_confidence=0.1,
                                  fix_quality="unknown", verdict=Verdict.UNVERIFIED_DIFFERENT_LOCATION, explanation="different gate and wall")
    c, v = closure.citizen_verify(store, ai, c, uploads_dir=uploads, photo=Media(jpeg, "image/jpeg"), reporter_id="u9", note=None, result_override=mismatch)
    assert (v["location_match"], c["status"]) == (0, ClusterStatus.CLOSURE_DISPUTED.value)


# ------------------------------------------------------------ proof requests --


def test_resolution_asks_reporters_and_nearby_citizens_for_proof(store, ai, uploads, jpeg):
    r1 = submit(store, ai, uploads, *ORR, ex(), reporter_id="u1")
    submit(store, ai, uploads, ORR[0] + 0.0001, ORR[1], ex(), reporter_id="u2")
    submit(store, ai, uploads, ORR[0] + 0.0001, ORR[1], ex())  # anonymous: unreachable
    submit(store, ai, uploads, ORR[0] + 0.001, ORR[1], ex(category="garbage_dump"), reporter_id="u3")  # ~110 m away, other issue
    submit(store, ai, uploads, ORR[0] + 0.01, ORR[1], ex(category="garbage_dump"), reporter_id="u4")  # ~1.1 km away
    cid = r1.cluster["id"]
    c, _ = closure.resolve(store, ai, store.get_cluster(cid), uploads_dir=uploads, after_photo=None, note=None, actor="eng", notifier=Notifier())

    requests = store.notifications_for_cluster(cid)
    assert sorted(n["recipient"] for n in requests) == ["u1", "u2", "u3"]
    assert {n["recipient"]: n["payload_json"]["reason"] for n in requests} == {"u1": "reporter", "u2": "reporter", "u3": "nearby"}
    assert all(n["kind"] == "verification_request" and "resolved" in n["message"] for n in requests)
    event = [e for e in store.events_for_cluster(cid) if e["type"] == "verification_requested"][-1]
    assert event["payload_json"] == {"recipients": 3, "reporters": 2, "nearby": 1, "webhook": "disabled"}

    # the citizen who answers has their request closed; a verified fix withdraws the rest
    closure.citizen_verify(store, ai, c, uploads_dir=uploads, photo=Media(jpeg, "image/jpeg"), reporter_id="u2", note=None, result_override=verdict())
    assert {n["recipient"]: n["status"] for n in store.notifications_for_cluster(cid)} == {"u1": "expired", "u2": "read", "u3": "expired"}


def test_webhook_receives_proof_requests_and_failures_do_not_break_closure(store, ai, uploads):
    received: list[dict] = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server API
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):  # silence test output
            pass

    server = HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        r1 = submit(store, ai, uploads, *ORR, ex(), reporter_id="u1")
        closure.resolve(store, ai, store.get_cluster(r1.cluster["id"]), uploads_dir=uploads, after_photo=None, note=None, actor="eng",
                        notifier=Notifier(f"http://127.0.0.1:{server.server_port}/hook"))
    finally:
        server.shutdown()
    assert received and received[0]["type"] == "verification_request" and received[0]["recipients"] == ["u1"]
    event = [e for e in store.events_for_cluster(r1.cluster["id"]) if e["type"] == "verification_requested"][-1]
    assert event["payload_json"]["webhook"] == "sent"

    r2 = submit(store, ai, uploads, 12.9719, 77.6412, ex(category="streetlight_outage"), reporter_id="u2")
    c, _ = closure.resolve(store, ai, store.get_cluster(r2.cluster["id"]), uploads_dir=uploads, after_photo=None, note=None, actor="eng",
                           notifier=Notifier("http://127.0.0.1:9/unreachable", timeout_s=0.5))
    assert c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value
    event = [e for e in store.events_for_cluster(c["id"]) if e["type"] == "verification_requested"][-1]
    assert event["payload_json"]["webhook"].startswith("failed")
    assert store.unread_count("u2") == 1  # the in-app inbox still works


# ---------------------------------------------------------------- migrations --


def test_existing_database_files_are_migrated_in_place(tmp_path):
    # Rebuild the pre-upgrade schema: today's schema minus every migrated column.
    added = {name for cols in MIGRATIONS.values() for name, _ in cols}
    old = "\n".join(line for line in SCHEMA.splitlines() if line.strip().split(" ")[0] not in added)
    old = re.sub(r",\s*\n\);", "\n);", old)  # drop the dangling comma left before ");"
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(old)
    conn.execute(
        "INSERT INTO clusters (id, created_at, updated_at, category, status, lat, lng, ward, title, agency, report_count, sla_hours, sla_due_at) "
        "VALUES ('CP-OLD', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', 'pothole', 'open', 12.9, 77.6, 'Bellandur', 't', 'GBA_ROADS', 3, 72, '2026-10-04T00:00:00Z')"
    )
    for rid, who in (("R-1", "a"), ("R-2", "a"), ("R-3", None)):
        conn.execute(
            "INSERT INTO reports (id, cluster_id, created_at, lat, lng, reporter_id, category, severity) VALUES (?, 'CP-OLD', '2026-10-01T00:00:00Z', 12.9, 77.6, ?, 'pothole', 3)",
            (rid, who),
        )
    # a cluster filed under a pre-PRD category id
    conn.execute(
        "INSERT INTO clusters (id, created_at, updated_at, category, status, lat, lng, ward, title, agency, report_count, sla_hours, sla_due_at) "
        "VALUES ('CP-LIGHT', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', 'streetlight', 'open', 12.95, 77.6, 'Koramangala', 't', 'GBA_ELECTRICAL', 1, 48, '2026-10-03T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO reports (id, cluster_id, created_at, lat, lng, reporter_id, category, severity) VALUES ('R-4', 'CP-LIGHT', '2026-10-01T00:00:00Z', 12.95, 77.6, 'b', 'streetlight', 2)"
    )
    conn.commit()
    conn.close()

    s = Store(db)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in s.conn.execute(f"PRAGMA table_info({table})")}
        assert {name for name, _ in cols} <= have
    assert s.get_cluster("CP-OLD")["reporter_count"] == 2  # backfilled: "a" once + one anonymous
    assert s.get_cluster("CP-LIGHT")["category"] == "streetlight_outage"
    assert s.get_report("R-4")["category"] == "streetlight_outage"
    s.close()
    Store(db).close()  # idempotent on the next start
