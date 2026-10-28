from __future__ import annotations

import io
import shutil
import subprocess
import wave

import pytest


def _wav(seconds: float, rate: int = 8000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(b"\x80" * int(seconds * rate))
    return out.getvalue()


def _image(fmt: str) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (16, 12), (100, 100, 100)).save(out, format=fmt)
    return out.getvalue()


def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["ai_mode"] == "heuristic"
    assert h["features"] == {"whatsapp": False, "public_audio": False, "face_blur": False}
    m = client.get("/api/meta").json()
    prd = {"pothole", "unrestored_utility_trench", "streetlight_outage", "garbage_dump", "waterlogging", "damaged_footpath", "fallen_tree"}
    assert {c["id"] for c in m["categories"] if c["prd"]} == prd
    assert {a["code"] for a in m["agencies"]} >= {"BBMP_ROADS", "BBMP_SWM", "BBMP_ELECTRICAL", "BWSSB", "BESCOM", "BMRCL", "BTP"}
    assert m["score_weights"] == {"unique_reporters": 35, "severity": 30, "context": 20, "days_elapsed": 15}
    assert (m["cluster_radius_m"], m["repeat_failure_radius_m"], m["repeat_failure_window_days"]) == (50, 25, 180)
    assert any(w["name"] == "Bellandur" and w["number"] == 150 for w in m["wards"])
    assert m["demo_locations"]
    assert m["limits"] == {
        "max_image_mb": 10, "max_audio_mb": 10, "max_audio_s": 30,
        "duplicate_window_s": 300, "duplicate_radius_m": 1000, "verify_gps_radius_m": 50, "corroborate_max_m": 250,
    }


def test_full_citizen_to_closure_flow(client, jpeg):
    # 1. citizen files a text+photo report
    r = client.post(
        "/api/reports",
        data={"lat": 12.9262, "lng": 77.6816, "text": "Dodda gundi near Ecospace gate on the service lane, BWSSB pipeline work left open", "reporter_id": "u1"},
        files={"photo": ("p.jpg", jpeg, "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    cid = body["cluster"]["id"]
    assert body["merged"] is False
    assert body["cluster"]["agency"] == "BWSSB"
    assert body["cluster"]["secondary_agency"] == "GBA_ROADS"
    assert body["cluster"]["secondary_agency_label"].startswith("GBA Roads")
    assert "resurfacing" in body["cluster"]["secondary_agency_reason"]
    assert 0 < body["cluster"]["routing_confidence"] <= 1
    assert body["cluster"]["severity_level"] in {"low", "medium", "high", "critical"}
    assert body["cluster"]["reporter_count"] == 1
    assert body["cluster"]["ward"] == "Bellandur"
    assert body["report"]["photo_url"].endswith(".jpg")
    assert client.get(body["report"]["photo_url"]).status_code == 200

    # 2. three more citizens corroborate -> same cluster, higher score
    score0 = body["cluster"]["impact_score"]
    for i in range(3):
        c = client.post(f"/api/clusters/{cid}/corroborate", data={"lat": 12.92621, "lng": 77.68161, "reporter_id": f"u{i + 2}"})
        assert c.status_code == 201 and c.json()["merged"] is True
    detail = client.get(f"/api/clusters/{cid}").json()
    assert detail["cluster"]["report_count"] == 4
    assert detail["cluster"]["reporter_count"] == 4
    assert detail["cluster"]["impact_score"] > score0
    assert len(detail["reports"]) == 4

    # 3. official moves it to in progress, then resolves with a photo (offline -> inconclusive -> pending)
    s = client.post(f"/api/clusters/{cid}/status", json={"status": "in_progress", "note": "crew assigned"})
    assert s.status_code == 200 and s.json()["cluster"]["status"] == "in_progress"
    res = client.post(f"/api/clusters/{cid}/resolve", data={"note": "filled"}, files={"after_photo": ("a.jpg", jpeg, "image/jpeg")})
    assert res.status_code == 200, res.text
    assert res.json()["cluster"]["status"] == "resolved_pending_verification"
    v = res.json()["verification"]
    assert v["verdict"] == "INCONCLUSIVE"
    assert v["location_match"] is False and v["gps_source"] is None and v["repair_quality"] is None
    assert "verification_requested" in [e["type"] for e in res.json()["events"]]

    # 3b. every reporter was asked for a proof photo (in-app inbox)
    for who in ("u1", "u2", "u3", "u4"):
        inbox = client.get("/api/notifications", params={"recipient": who}).json()
        assert inbox["unread"] == 1
        n = inbox["notifications"][0]
        assert n["kind"] == "verification_request" and n["cluster"]["id"] == cid and n["status"] == "unread"
    marked = client.post("/api/notifications/read", json={"recipient": "u4"}).json()
    assert marked == {"updated": 1, "unread": 0}
    assert client.get("/api/notifications", params={"recipient": "u4"}).json()["notifications"] == []
    assert len(client.get("/api/notifications", params={"recipient": "u4", "include_read": True}).json()["notifications"]) == 1

    # 4. citizen verification photo (offline -> inconclusive, status unchanged); their request is closed
    v = client.post(f"/api/clusters/{cid}/verify", data={"reporter_id": "u1"}, files={"photo": ("v.jpg", jpeg, "image/jpeg")})
    assert v.status_code == 200, v.text
    assert v.json()["cluster"]["status"] == "resolved_pending_verification"
    assert len(v.json()["verifications"]) == 2
    assert client.get("/api/notifications", params={"recipient": "u1"}).json()["unread"] == 0

    # 5. escalation drafts
    for channel in ("email", "x", "rti"):
        e = client.post(f"/api/clusters/{cid}/escalate", json={"channel": channel, "requester_name": "Bellandur RWA"})
        assert e.status_code == 200, e.text
        d = e.json()["draft"]
        assert d["channel"] == channel and cid in d["body"]
        if channel == "x":
            assert len(d["body"]) <= 280
        if channel == "email":
            assert "GBA Roads" in d["body"]  # secondary owner is copied in

    # 6. lists, scorecard, stats
    lst = client.get("/api/clusters", params={"ward": "Bellandur"}).json()["clusters"]
    assert [c["id"] for c in lst] == [cid]
    sc = client.get("/api/wards/scorecard").json()
    ward = next(w for w in sc["wards"] if w["ward"] == "Bellandur")
    assert ward["closures"] == 1 and ward["resolved_pending_verification"] == 1
    assert sc["city"]["unverified_closure_rate"] == 100.0
    assert client.get("/api/stats").json()["clusters"] == 1


def test_closure_photo_taken_elsewhere_is_disputed(client, jpeg, gps_jpeg):
    # PRD REQ-VERIFY-CLOSURE: after-photo coordinates > 50 m away -> location_match false, unverified closure
    r = client.post("/api/reports", data={"lat": 12.9262, "lng": 77.6816, "text": "pothole on the ORR service lane", "reporter_id": "c1"},
                    files={"photo": ("p.jpg", jpeg, "image/jpeg")}).json()
    cid = r["cluster"]["id"]
    res = client.post(f"/api/clusters/{cid}/resolve", data={"note": "fixed"}, files={"after_photo": ("a.jpg", gps_jpeg(12.9334, 77.6816), "image/jpeg")})
    assert res.status_code == 200, res.text
    assert res.json()["cluster"]["status"] == "closure_disputed"
    v = res.json()["verification"]
    assert v["verdict"] == "UNVERIFIED_DIFFERENT_LOCATION" and v["location_match"] is False
    assert v["gps_source"] == "exif" and v["gps_distance_m"] > 50
    assert v["repair_quality"] == "mismatched_location"
    ward = next(w for w in client.get("/api/wards/scorecard").json()["wards"] if w["ward"] == "Bellandur")
    assert ward["closure_disputed"] == 1 and ward["unverified_closure_rate"] == 100.0
    inbox = client.get("/api/notifications", params={"recipient": "c1"}).json()
    assert inbox["unread"] == 1 and "flagged" in inbox["notifications"][0]["message"]


def test_duplicate_submissions_from_the_same_reporter_are_rejected(client):
    data = {"lat": 12.9345, "lng": 77.6231, "text": "street light not working near Sony World", "reporter_id": "dup-1"}
    assert client.post("/api/reports", data=data).status_code == 201
    again = client.post("/api/reports", data={**data, "lat": 12.9360})  # ~170 m away, moments later
    assert again.status_code == 429
    detail = again.json()["detail"]
    assert detail["code"] == "duplicate_submission" and detail["duplicate_of"]["cluster_id"].startswith("CP-")
    assert 0 < int(again.headers["Retry-After"]) <= 300 and detail["retry_after_s"] == int(again.headers["Retry-After"])
    plus_one = client.post(f"/api/clusters/{detail['duplicate_of']['cluster_id']}/corroborate", data={"lat": 12.9345, "lng": 77.6231, "reporter_id": "dup-1"})
    assert plus_one.status_code == 429 and plus_one.json()["detail"]["code"] == "duplicate_submission"
    # another citizen, or a different kind of issue, is fine
    assert client.post("/api/reports", data={**data, "reporter_id": "dup-2"}).status_code == 201
    assert client.post("/api/reports", data={**data, "text": "garbage dumped at the corner, stinks"}).status_code == 201


def test_upload_formats_and_limits(client, jpeg):
    base = {"lat": 12.9262, "lng": 77.6816, "text": "pothole on the service lane"}
    assert client.post("/api/reports", data=base, files={"photo": ("x.jpg", b"not an image at all", "image/jpeg")}).status_code == 415
    assert client.post("/api/reports", data=base, files={"photo": ("x.gif", _image("GIF"), "image/gif")}).status_code == 415
    assert client.post("/api/reports", data=base, files={"photo": ("x.png", _image("PNG"), "image/png")}).status_code == 201
    assert client.post("/api/reports", data=base, files={"photo": ("x.webp", _image("WEBP"), "image/webp")}).status_code == 201
    big = jpeg + b"\0" * (10 * 1024 * 1024)
    assert client.post("/api/reports", data=base, files={"photo": ("big.jpg", big, "image/jpeg")}).status_code == 413

    too_long = client.post("/api/reports", data=base, files={"audio": ("n.wav", _wav(32), "audio/wav")})
    assert too_long.status_code == 422
    assert too_long.json()["detail"]["code"] == "audio_too_long" and too_long.json()["detail"]["max_audio_s"] == 30
    assert client.post("/api/reports", data=base, files={"audio": ("n.wav", _wav(30.5), "audio/wav")}).status_code == 201  # timer slack
    assert client.post("/api/reports", data=base, files={"audio": ("n.wav", _wav(10), "audio/wav")}).status_code == 201


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg/ffprobe")
def test_browser_webm_without_duration_header_is_measured(client, tmp_path):
    # MediaRecorder WebM has no duration header (like ffmpeg's live mode); the packet timestamps still give it away.
    out = tmp_path / "note.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "35", "-c:a", "libopus", "-f", "webm", "-live", "1", str(out)], check=True)
    r = client.post("/api/reports", data={"lat": 12.9262, "lng": 77.6816}, files={"audio": ("note.webm", out.read_bytes(), "audio/webm;codecs=opus")})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "audio_too_long"


def test_external_ref_links_the_official_ticket(client):
    cid = client.post("/api/reports", data={"lat": 12.9262, "lng": 77.6816, "text": "pothole near Ecospace gate"}).json()["cluster"]["id"]
    r = client.post(f"/api/clusters/{cid}/external-ref", json={"ref": " SAH-2026-0042 ", "actor": "bellandur-rwa"})
    assert r.status_code == 200, r.text
    c = r.json()["cluster"]
    assert (c["external_system"], c["external_ref"]) == ("sahaaya", "SAH-2026-0042") and c["external_ref_at"]
    assert r.json()["events"][-1]["type"] == "external_ref_recorded"
    rti = client.post(f"/api/clusters/{cid}/escalate", json={"channel": "rti"}).json()["draft"]["body"]
    assert "SAHAAYA #SAH-2026-0042" in rti
    assert client.post(f"/api/clusters/{cid}/external-ref", json={"ref": "   "}).status_code == 422
    assert client.post(f"/api/clusters/{cid}/external-ref", json={"system": "bad system!", "ref": "1"}).status_code == 422
    assert client.post("/api/clusters/CP-NOPE/external-ref", json={"ref": "1"}).status_code == 404


def test_validation_errors(client):
    assert client.post("/api/reports", data={"lat": 12.9, "lng": 77.6}).status_code == 422
    assert client.post("/api/reports", data={"lat": 123, "lng": 77.6, "text": "pothole"}).status_code == 422
    assert client.get("/api/clusters/CP-NOPE").status_code == 404
    assert client.post("/api/clusters/CP-NOPE/status", json={"status": "in_progress"}).status_code == 404
    assert client.get("/api/notifications").status_code == 422  # recipient is required


def test_resolve_requires_resolvable_status(client):
    r = client.post("/api/reports", data={"lat": 12.9345, "lng": 77.6231, "text": "street light not working near Sony World"}).json()
    cid = r["cluster"]["id"]
    assert r["cluster"]["agency"] == "GBA_ELECTRICAL"
    assert client.post(f"/api/clusters/{cid}/resolve", data={"lat": 12.9345}).status_code == 422  # lng missing
    assert client.post(f"/api/clusters/{cid}/resolve", data={}).status_code == 200
    # already closed -> cannot resolve again
    assert client.post(f"/api/clusters/{cid}/resolve", data={}).status_code == 409


def test_seed_endpoint_builds_the_demo_story(client):
    s = client.post("/api/admin/seed").json()
    assert s["status"] == "seeded" and s["clusters"] >= 15
    hi = s["highlights"]
    orr = client.get(f"/api/clusters/{hi['orr_pothole']}").json()
    assert orr["cluster"]["report_count"] == 4
    assert orr["cluster"]["reporter_count"] == 4
    assert orr["cluster"]["agency"] == "BWSSB"
    assert orr["cluster"]["secondary_agency"] == "GBA_ROADS"
    assert orr["cluster"]["routing_confidence"] >= 0.9
    assert orr["cluster"]["severity_level"] == "critical"
    assert orr["cluster"]["status"] == "in_progress"
    assert orr["cluster"]["sla_breached"] is True
    assert {r["language"] for r in orr["reports"]} == {"kn-en", "en", "kn", "hi-en"}
    assert orr["cluster"]["impact_score"] >= 60
    assert {c["component"] for c in orr["cluster"]["score_breakdown"]["components"]} == {"unique_reporters", "severity", "context", "days_elapsed"}

    kor = client.get(f"/api/clusters/{hi['koramangala_fake_closure']}").json()
    assert kor["cluster"]["status"] == "closure_disputed"
    assert kor["cluster"]["status_label"] == "Unverified closure"
    assert kor["verifications"][-1]["verdict"] == "UNVERIFIED_DIFFERENT_LOCATION"
    assert kor["verifications"][-1]["repair_quality"] == "mismatched_location"
    assert client.get("/api/notifications", params={"recipient": "citizen-divya"}).json()["unread"] == 1

    rep = client.get(f"/api/clusters/{hi['agara_repeat_failure']}").json()
    assert rep["cluster"]["repeat_failure"] is True
    assert rep["previous_cluster"]["status"] == "resolved_verified"

    trench = client.get(f"/api/clusters/{hi['bellandur_trench']}").json()["cluster"]
    assert (trench["category"], trench["agency"], trench["secondary_agency"]) == ("unrestored_utility_trench", "BESCOM", "GBA_ROADS")
    assert (trench["agency_code"], trench["secondary_agency_code"]) == ("BESCOM", "BBMP_ROADS")
    assert trench["status"] == "closure_disputed" and trench["ward"] == "Bellandur"

    sc = client.get("/api/wards/scorecard").json()
    assert sc["city"]["closures"] >= 7
    assert 0 < sc["city"]["unverified_closure_rate"] < 100
    hsr = next(w for w in sc["wards"] if w["ward"] == "HSR Layout")
    assert hsr["repeat_failure_rate"] > 0
    bellandur = next(w for w in sc["wards"] if w["ward"] == "Bellandur")
    assert bellandur["number"] == 150 and bellandur["active"] >= 3 and bellandur["closure_disputed"] >= 1

    # seeding twice resets cleanly
    s2 = client.post("/api/admin/seed").json()
    assert s2["counts"]["reports"] == s["counts"]["reports"]
