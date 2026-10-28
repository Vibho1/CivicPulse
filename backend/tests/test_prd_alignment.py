"""PRD alignment: acceptance criteria and the fixes from the PRD review (no network, no credentials)."""

from __future__ import annotations

import gzip
import io
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai import ResilientAI
from app.ai.heuristic import HeuristicAI
from app.ai.templates import X_MAX_CHARS
from app.config import Settings
from app.domain import Verdict
from app.main import create_app
from app.schemas import SensitiveRegion, VerificationResult
from app.store import Store

ORR = (12.9262, 77.6816)


def offset(lat: float, lng: float, d: float, bearing: float) -> tuple[float, float]:
    r = 6371000.0
    b, la, lo = math.radians(bearing), math.radians(lat), math.radians(lng)
    la2 = math.asin(math.sin(la) * math.cos(d / r) + math.cos(la) * math.sin(d / r) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d / r) * math.cos(la), math.cos(d / r) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


class StubAI(HeuristicAI):
    """Heuristic parsing plus scripted 'model' answers for vision-only behaviour."""

    name = "stub"

    def __init__(self):
        self.verdict = Verdict.VERIFIED
        self.regions: list[SensitiveRegion] = []
        self.stock = False

    def parse_report(self, inp):
        ex = super().parse_report(inp)
        if inp.text and "selfie" in inp.text.lower():
            ex = ex.model_copy(update={"is_civic_issue": False})
        ev = ex.evidence.model_copy(update={"stock_or_screenshot": self.stock})
        return ex.model_copy(update={"sensitive_regions": list(self.regions), "evidence": ev})

    def verify_fix(self, before, after, context):
        v = self.verdict
        return VerificationResult(
            same_location=v != Verdict.UNVERIFIED_DIFFERENT_LOCATION, same_location_confidence=0.9,
            issue_resolved=v == Verdict.VERIFIED, resolution_confidence=0.9,
            fix_quality="proper" if v == Verdict.VERIFIED else "none", verdict=v, explanation=f"stub {v.value}",
        )


@pytest.fixture()
def stub() -> StubAI:
    return StubAI()


@pytest.fixture()
def sclient(tmp_path: Path, stub: StubAI):
    settings = Settings(
        gemini_api_key="", database_path=str(tmp_path / "t.db"), uploads_dir=str(tmp_path / "uploads"),
        frontend_dist=str(tmp_path / "no-dist"), demo_mode=True,
    )
    store = Store(":memory:")
    app = create_app(settings=settings, store=store, ai=ResilientAI(stub, HeuristicAI()))
    with TestClient(app) as c:
        yield c
    store.close()


def _report(c, lat, lng, text, reporter, photo: bytes | None = None, **extra):
    files = {"photo": ("p.jpg", photo, "image/jpeg")} if photo is not None else None
    return c.post("/api/reports", data={"lat": lat, "lng": lng, "text": text, "reporter_id": reporter, **extra}, files=files)


def _jpeg(size=(320, 240), color=(90, 90, 90)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


# ------------------------------------------------------------------ security --


def test_spa_fallback_cannot_escape_the_build_directory(tmp_path, store, ai):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    settings = Settings(gemini_api_key="", database_path=str(tmp_path / "t.db"), uploads_dir=str(tmp_path / "up"), frontend_dist=str(dist))
    with TestClient(create_app(settings=settings, store=store, ai=ai)) as c:
        for path in ("/..%2F..%2Fsecret.txt", "/%2E%2E/%2E%2E/secret.txt", "/..%2f..%2f..%2f..%2fetc%2fhostname"):
            r = c.get(path)
            assert r.status_code == 200 and "TOP-SECRET" not in r.text and r.text == "<html>spa</html>"
        assert c.get("/uploads/..%2F..%2Fsecret.txt").status_code == 404


def test_large_json_responses_are_gzipped(client):
    client.post("/api/admin/seed")
    r = client.get("/api/clusters", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert r.json()["clusters"]  # httpx decodes it transparently
    assert len(gzip.compress(r.content)) < len(r.content)


# ---------------------------------------------------------- 4.1 intake (PRD) --


def test_non_civic_submission_is_rejected_with_a_prompt(sclient, client):
    model = _report(sclient, *ORR, "my selfie at the mall", "u1", _jpeg())
    assert model.status_code == 422 and model.json()["detail"]["code"] == "not_civic_issue"
    offline = _report(client, *ORR, "hello, just testing this app", "u2")
    assert offline.status_code == 422 and offline.json()["detail"]["code"] == "low_confidence"
    photo_only = client.post("/api/reports", data={"lat": ORR[0], "lng": ORR[1], "reporter_id": "u3"}, files={"photo": ("p.jpg", _jpeg(), "image/jpeg")})
    assert photo_only.status_code == 422 and "Describe it" in photo_only.json()["detail"]["message"]


def test_report_returns_the_prd_parser_shape(client):
    r = _report(client, *ORR, "ORR service lane alli dodda gundi ide, about 30 cm deep and 1 m wide, two wheelers skid", "u1")
    assert r.status_code == 201, r.text
    parsed = r.json()["report"]["parsed"]
    assert parsed["category"] == "pothole" and parsed["severity"] == "high"
    assert parsed["estimated_dimensions_cm"] == {"length": None, "width": 100.0, "depth": 30.0}
    assert set(parsed) == {"category", "severity", "estimated_dimensions_cm", "extracted_landmark", "transcription", "language"}
    assert r.json()["report"]["agency_code"] in {"BBMP_ROADS", "BWSSB"}


def test_emergencies_are_redirected_to_112(client):
    r = _report(client, 12.95, 77.65, "Live wire fell on the road and is sparking, a man got electrocuted", "u1")
    assert r.status_code == 201
    em = r.json()["emergency"]
    assert em["is_emergency"] is True and em["number"] == "112" and "112" in em["message"]
    assert _report(client, 12.96, 77.66, "pothole near the bus stop", "u2").json()["emergency"] is None


# ----------------------------------------------------------- 4.3 clustering --


def test_ac3_three_reports_within_35_m_attach_and_rescore(client):
    base = (12.9352, 77.6245)
    first = _report(client, *base, "big pothole near Sony World signal", "A").json()["cluster"]
    for who, d, brg in (("B", 10, 0), ("C", 25, 120), ("D", 35, 240)):
        r = _report(client, *offset(*base, d, brg), "pothole here, very deep", who).json()
        assert r["merged"] and r["cluster"]["id"] == first["id"]
    c = client.get(f"/api/clusters/{first['id']}").json()["cluster"]
    assert (c["reporter_count"], c["report_count"]) == (4, 4)
    assert c["impact_score"] > first["impact_score"]


def test_i_see_this_too_attaches_to_the_tapped_issue(client):
    cid = _report(client, *ORR, "pothole near Ecospace gate", "u1").json()["cluster"]["id"]
    near = offset(*ORR, 180, 90)  # beyond the 50 m merge radius but at the spot
    r = client.post(f"/api/clusters/{cid}/corroborate", data={"lat": near[0], "lng": near[1], "reporter_id": "u2"})
    assert r.status_code == 201 and r.json()["merged"] is True and r.json()["cluster"]["id"] == cid
    c = client.get(f"/api/clusters/{cid}").json()
    assert c["cluster"]["report_count"] == 2
    assert abs(c["cluster"]["lat"] - ORR[0]) < 1e-9  # the pin does not drift towards the corroborator
    assert any("citizen 180 m away" in e["note"] for e in c["events"])
    far = offset(*ORR, 2000, 0)
    tf = client.post(f"/api/clusters/{cid}/corroborate", data={"lat": far[0], "lng": far[1], "reporter_id": "u3"})
    assert tf.status_code == 422 and tf.json()["detail"]["code"] == "too_far" and tf.json()["detail"]["max_distance_m"] == 250
    assert len(client.get("/api/clusters").json()["clusters"]) == 1  # no stray duplicate cluster
    # a coarse fix (large accuracy radius) is given the benefit of the doubt
    loose = offset(*ORR, 400, 0)
    assert client.post(f"/api/clusters/{cid}/corroborate", data={"lat": loose[0], "lng": loose[1], "accuracy": 200, "reporter_id": "u4"}).status_code == 201


# --------------------------------------------------------- 4.4 verification --


def test_ac4_citizen_after_photo_of_another_spot_is_an_unverified_closure(sclient, stub, gps_jpeg):
    cid = _report(sclient, *ORR, "pothole near Ecospace gate", "u1", _jpeg()).json()["cluster"]["id"]
    res = sclient.post(f"/api/clusters/{cid}/resolve", data={"note": "fixed"}, files={"after_photo": ("a.jpg", gps_jpeg(*ORR), "image/jpeg")})
    assert res.json()["cluster"]["status"] == "resolved_pending_verification"
    stub.verdict = Verdict.UNVERIFIED_DIFFERENT_LOCATION
    v = sclient.post(f"/api/clusters/{cid}/verify", data={"reporter_id": "u1"}, files={"photo": ("v.jpg", _jpeg(color=(10, 200, 10)), "image/jpeg")}).json()
    assert (v["verification"]["location_match"], v["verification"]["repair_quality"]) == (False, "mismatched_location")
    assert v["verification"]["verification_summary"]
    assert v["cluster"]["status"] == "closure_disputed" and v["cluster"]["status_label"] == "Unverified closure"


def test_client_read_exif_gps_is_used_for_the_closure_check(sclient):
    cid = _report(sclient, *ORR, "pothole near Ecospace gate", "u1", _jpeg()).json()["cluster"]["id"]
    far = offset(*ORR, 400, 90)
    # the PWA re-encodes photos (EXIF gone) and sends the original's GPS alongside
    res = sclient.post(
        f"/api/clusters/{cid}/resolve", data={"note": "fixed", "photo_exif": "1", "photo_lat": far[0], "photo_lng": far[1]},
        files={"after_photo": ("a.jpg", _jpeg(), "image/jpeg")},
    ).json()
    assert res["cluster"]["status"] == "closure_disputed"
    assert res["verification"]["gps_source"] == "exif" and res["verification"]["gps_distance_m"] > 350


# ------------------------------------------------------ privacy and anti-spam --


def test_photo_provenance_flags(sclient, stub, gps_jpeg):
    stripped = _report(sclient, *ORR, "pothole near Ecospace gate", "u1", _jpeg(), photo_exif="0").json()["report"]
    assert stripped["photo_flags"] == ["exif_stripped"]
    camera = _report(sclient, 12.9500, 77.6500, "garbage dump at the corner", "u2", _jpeg(), photo_exif="1").json()["report"]
    assert camera["photo_flags"] == []
    far = offset(12.9600, 77.6600, 3000, 0)
    moved = _report(sclient, 12.9600, 77.6600, "streetlight not working", "u3", _jpeg(), photo_exif="1", photo_lat=far[0], photo_lng=far[1]).json()
    assert "exif_location_far" in moved["report"]["photo_flags"] and moved["location_warning"]
    stub.stock = True
    stock = _report(sclient, 12.9700, 77.6700, "fallen tree blocking road", "u4", gps_jpeg(12.9700, 77.6700)).json()["report"]
    assert stock["photo_flags"] == ["stock_or_screenshot"]


def test_faces_and_plates_are_blurred_before_storage(sclient, stub):
    from PIL import Image

    stub.regions = [SensitiveRegion(kind="license_plate", box_2d=[400, 400, 600, 600])]
    noisy = Image.effect_noise((320, 240), 100).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, format="JPEG", quality=95)
    r = _report(sclient, *ORR, "pothole near Ecospace gate", "u1", buf.getvalue(), photo_exif="1").json()["report"]
    assert r["privacy_blurred"] == 1 and "faces_or_plates_blurred" in r["photo_flags"]
    stored = Image.open(io.BytesIO(sclient.get(r["photo_url"]).content)).convert("L")
    inside = [stored.getpixel((x, 120)) for x in range(135, 185)]
    outside = [stored.getpixel((x, 20)) for x in range(135, 185)]
    assert max(inside) - min(inside) < max(outside) - min(outside)


def test_phone_numbers_and_reporter_ids_never_leave_the_api(client):
    r = _report(client, 12.96, 77.66, "garbage dump near Forum mall, call me on 9876543210 or +91 98765 43210", "device-abc-123")
    assert r.status_code == 201
    cid = r.json()["cluster"]["id"]
    body = client.get(f"/api/clusters/{cid}").text
    assert "9876543210" not in body and "98765 43210" not in body and "98******10" in body
    assert "device-abc-123" not in body and "citizen-" in body
    pkg = client.post(f"/api/clusters/{cid}/escalation-package", json={}).text
    assert "9876543210" not in pkg


def test_voice_notes_are_private_by_default(client):
    from tests.test_api import _wav

    r = client.post("/api/reports", data={"lat": ORR[0], "lng": ORR[1], "text": "pothole near Ecospace gate", "reporter_id": "u1"},
                    files={"audio": ("n.wav", _wav(3), "audio/wav")})
    assert r.status_code == 201
    own = r.json()["report"]
    assert own["audio_url"] and "-" in own["audio_url"].rsplit("/", 1)[1]  # unguessable file name
    public = client.get(f"/api/clusters/{r.json()['cluster']['id']}").json()["reports"][0]
    assert public["audio_url"] is None and "audio_path" not in public


def test_reporter_credibility_moves_with_evidence(client):
    first = _report(client, *ORR, "pothole near Ecospace gate", "honest").json()["report"]
    assert first["reporter_credibility"] == 0.6
    cid = first["cluster_id"]
    client.post(f"/api/clusters/{cid}/corroborate", data={"lat": ORR[0], "lng": ORR[1], "reporter_id": "neighbour"})
    honest = next(r for r in client.get(f"/api/clusters/{cid}").json()["reports"] if not r["is_corroboration"])
    assert honest["reporter_credibility"] > 0.6  # independently confirmed
    for i in range(3):
        assert _report(client, 12.9 + i / 100, 77.6, f"blah blah {i}", "spammer").status_code == 422
    spam = _report(client, 12.99, 77.70, "pothole on the main road", "spammer").json()["report"]
    assert spam["reporter_credibility"] < 0.4


# ------------------------------------------------------------ 4.5 dashboard --


def test_cluster_escalation_package_has_every_prd_field(client, jpeg, gps_jpeg):
    long_landmark = "Outer Ring Road service lane opposite the Ecospace Business Park main gate next to the bus stop"
    r = _report(client, *ORR, f"huge pothole near {long_landmark}", "u1", jpeg).json()
    cid = r["cluster"]["id"]
    client.post(f"/api/clusters/{cid}/resolve", data={"note": "done"}, files={"after_photo": ("a.jpg", gps_jpeg(*offset(*ORR, 400, 90)), "image/jpeg")})
    pkg = client.post(f"/api/clusters/{cid}/escalation-package", json={"requester_name": "Bellandur RWA"}).json()
    assert pkg["elapsed_ms"] < 3000 and pkg["ai_mode"] == "template" and pkg["cluster_ids"] == [cid]
    c = client.get(f"/api/clusters/{cid}").json()["cluster"]
    for channel, d in pkg["drafts"].items():
        text = f"{d.get('subject') or ''} {d['body']}"
        assert cid in text and "Bellandur" in text, channel
        assert "BBMP_ROADS" in text or "BWSSB" in text, channel
        if channel == "x":
            assert len(d["body"]) <= X_MAX_CHARS
            continue
        assert f"{c['lat']:.5f}" in text and c["created_at"] in text, channel
        assert "/uploads/" in text and f"/clusters/{cid}" in text, channel  # before/after photo links + issue page
        assert "400 m" in text, channel  # the failure reason
    assert pkg["filename"].endswith(".txt") and "RTI APPLICATION" in pkg["text"] and "Section 6(1)" in pkg["text"]
    # the per-channel endpoint never returns an over-long X post either
    x = client.post(f"/api/clusters/{cid}/escalate", json={"channel": "x", "ai": False}).json()
    assert x["ai_mode"] == "template" and len(x["draft"]["body"]) <= X_MAX_CHARS and cid in x["draft"]["body"]


def test_ward_escalation_package_for_ward_150_bellandur(client):
    client.post("/api/admin/seed")
    pkg = client.post("/api/wards/150/escalation-package", json={"requester_name": "Bellandur RWA"}).json()
    assert pkg["scope"] == "ward" and pkg["ward"] == "Bellandur" and pkg["ward_number"] == 150
    assert pkg["elapsed_ms"] < 3000 and len(pkg["cluster_ids"]) >= 2
    assert any(c["status"] == "closure_disputed" for c in pkg["clusters"])
    for channel, d in pkg["drafts"].items():
        text = f"{d.get('subject') or ''} {d['body']}"
        assert "Ward 150 Bellandur" in text, channel
        assert pkg["cluster_ids"][0] in text, channel
        if channel == "x":
            assert len(d["body"]) <= X_MAX_CHARS
        else:
            assert all(cid in text for cid in pkg["cluster_ids"]), channel
            assert all(item["failure_reason"][:30] in text for item in pkg["clusters"]), channel
            assert "BESCOM" in text, channel
    by_name = client.post("/api/wards/bellandur/escalation-package", json={}).json()
    assert by_name["cluster_ids"] == pkg["cluster_ids"]
    assert client.post("/api/wards/Atlantis/escalation-package", json={}).status_code == 404
    quiet = client.post("/api/wards/Yelahanka/escalation-package", json={})
    assert quiet.status_code == 409 and quiet.json()["detail"]["code"] == "nothing_to_escalate"


def test_filters_for_sla_breached_and_prd_agency_codes(client):
    client.post("/api/admin/seed")
    breached = client.get("/api/clusters", params={"sla_breached": "true"}).json()["clusters"]
    assert breached and all(c["sla_breached"] for c in breached)
    roads = client.get("/api/clusters", params={"agency": "BBMP_ROADS"}).json()["clusters"]
    assert roads and all(c["agency"] == "GBA_ROADS" and c["agency_code"] == "BBMP_ROADS" for c in roads)


def test_scorecard_unverified_rate_is_consistent(client):
    client.post("/api/admin/seed")
    sc = client.get("/api/wards/scorecard").json()
    closures = sum(w["closures"] for w in sc["wards"])
    unverified = sum(w["closures"] - w["resolved_verified"] for w in sc["wards"])
    assert sc["city"]["closures"] == closures
    assert sc["city"]["unverified_closure_rate"] == round(100 * unverified / closures, 1)
    assert sc["city"]["active"] == sum(w["active"] for w in sc["wards"])


# -------------------------------------------------------------- Gemini setup --


def test_gemini3_uses_low_thinking_and_default_temperature():
    pytest.importorskip("google.genai")
    from app.ai.gemini import GeminiAI, escalation_problem
    from app.schemas import EscalationDraft, Extraction

    g3 = GeminiAI(api_key="test-key", model="gemini-3.8-flash", parse_timeout_s=15)
    cfg = g3._config("sys", Extraction, 0.2, fast=True, timeout_s=15)
    assert cfg.thinking_config.thinking_level.name == "MINIMAL" and cfg.temperature is None
    assert cfg.http_options.timeout == 15000
    assert g3._config("sys", Extraction, 0.1, fast=False).thinking_config.thinking_level.name == "LOW"
    g25 = GeminiAI(api_key="test-key", model="gemini-2.5-flash")
    cfg25 = g25._config("sys", Extraction, 0.2, fast=True)
    assert cfg25.thinking_config.thinking_budget == 0 and cfg25.temperature == 0.2

    ctx = {"cluster_id": "CP-ABC123", "public_url": "https://x/clusters/CP-ABC123"}
    assert escalation_problem(EscalationDraft(channel="x", body="a" * 300 + " CP-ABC123"), ctx)
    assert escalation_problem(EscalationDraft(channel="email", body="no ticket here"), ctx) == "ticket id missing"
    assert escalation_problem(EscalationDraft(channel="email", body="CP-ABC123 without link"), ctx) == "evidence link missing"
    assert escalation_problem(EscalationDraft(channel="x", body="short CP-ABC123 #CivicPulse"), ctx) is None
