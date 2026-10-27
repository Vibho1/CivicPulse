from __future__ import annotations


def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["ai_mode"] == "heuristic"
    m = client.get("/api/meta").json()
    assert {c["id"] for c in m["categories"]} >= {"pothole", "garbage", "streetlight"}
    assert any(w["name"] == "Bellandur" for w in m["wards"])
    assert m["demo_locations"]


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
    assert detail["cluster"]["impact_score"] > score0
    assert len(detail["reports"]) == 4

    # 3. official moves it to in progress, then resolves with a photo (offline -> inconclusive -> pending)
    s = client.post(f"/api/clusters/{cid}/status", json={"status": "in_progress", "note": "crew assigned"})
    assert s.status_code == 200 and s.json()["cluster"]["status"] == "in_progress"
    res = client.post(f"/api/clusters/{cid}/resolve", data={"note": "filled"}, files={"after_photo": ("a.jpg", jpeg, "image/jpeg")})
    assert res.status_code == 200, res.text
    assert res.json()["cluster"]["status"] == "resolved_pending_verification"
    assert res.json()["verification"]["verdict"] == "INCONCLUSIVE"

    # 4. citizen verification photo (offline -> inconclusive, status unchanged)
    v = client.post(f"/api/clusters/{cid}/verify", data={"reporter_id": "u1"}, files={"photo": ("v.jpg", jpeg, "image/jpeg")})
    assert v.status_code == 200, v.text
    assert v.json()["cluster"]["status"] == "resolved_pending_verification"
    assert len(v.json()["verifications"]) == 2

    # 5. escalation drafts
    for channel in ("email", "x", "rti"):
        e = client.post(f"/api/clusters/{cid}/escalate", json={"channel": channel, "requester_name": "Bellandur RWA"})
        assert e.status_code == 200, e.text
        d = e.json()["draft"]
        assert d["channel"] == channel and cid in d["body"]
        if channel == "x":
            assert len(d["body"]) <= 280

    # 6. lists, scorecard, stats
    lst = client.get("/api/clusters", params={"ward": "Bellandur"}).json()["clusters"]
    assert [c["id"] for c in lst] == [cid]
    sc = client.get("/api/wards/scorecard").json()
    ward = next(w for w in sc["wards"] if w["ward"] == "Bellandur")
    assert ward["closures"] == 1 and ward["resolved_pending_verification"] == 1
    assert sc["city"]["unverified_closure_rate"] == 100.0
    assert client.get("/api/stats").json()["clusters"] == 1


def test_validation_errors(client):
    assert client.post("/api/reports", data={"lat": 12.9, "lng": 77.6}).status_code == 422
    assert client.post("/api/reports", data={"lat": 123, "lng": 77.6, "text": "pothole"}).status_code == 422
    assert client.get("/api/clusters/CP-NOPE").status_code == 404
    assert client.post("/api/clusters/CP-NOPE/status", json={"status": "in_progress"}).status_code == 404


def test_resolve_requires_resolvable_status(client):
    r = client.post("/api/reports", data={"lat": 12.9345, "lng": 77.6231, "text": "street light not working near Sony World"}).json()
    cid = r["cluster"]["id"]
    assert r["cluster"]["agency"] == "GBA_ELECTRICAL"
    assert client.post(f"/api/clusters/{cid}/resolve", data={}).status_code == 200
    # already closed -> cannot resolve again
    assert client.post(f"/api/clusters/{cid}/resolve", data={}).status_code == 409


def test_seed_endpoint_builds_the_demo_story(client):
    s = client.post("/api/admin/seed").json()
    assert s["status"] == "seeded" and s["clusters"] >= 15
    hi = s["highlights"]
    orr = client.get(f"/api/clusters/{hi['orr_pothole']}").json()
    assert orr["cluster"]["report_count"] == 4
    assert orr["cluster"]["agency"] == "BWSSB"
    assert orr["cluster"]["status"] == "in_progress"
    assert orr["cluster"]["sla_breached"] is True
    assert {r["language"] for r in orr["reports"]} == {"kn-en", "en", "kn", "hi-en"}
    assert orr["cluster"]["impact_score"] >= 80

    kor = client.get(f"/api/clusters/{hi['koramangala_fake_closure']}").json()
    assert kor["cluster"]["status"] == "closure_disputed"
    assert kor["verifications"][-1]["verdict"] == "UNVERIFIED_DIFFERENT_LOCATION"

    rep = client.get(f"/api/clusters/{hi['agara_repeat_failure']}").json()
    assert rep["cluster"]["repeat_failure"] is True
    assert rep["previous_cluster"]["status"] == "resolved_verified"

    sc = client.get("/api/wards/scorecard").json()
    assert sc["city"]["closures"] >= 7
    assert 0 < sc["city"]["unverified_closure_rate"] < 100
    hsr = next(w for w in sc["wards"] if w["ward"] == "HSR Layout")
    assert hsr["repeat_failure_rate"] > 0

    # seeding twice resets cleanly
    s2 = client.post("/api/admin/seed").json()
    assert s2["counts"]["reports"] == s["counts"]["reports"]
