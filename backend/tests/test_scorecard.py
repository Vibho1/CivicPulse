"""Accountability Index, grades, top problem and the closure funnel."""

from __future__ import annotations

from datetime import timedelta

from app.services.accountability import GRADE_BANDS, accountability_index, closure_funnel, grade_for, top_problem
from app.services.common import now_utc, to_iso


def test_index_weights_and_grades():
    perfect, grade, breakdown = accountability_index(closures=5, verified_closure_rate=100.0, sla_breach_rate=0.0, repeat_failure_rate=0.0, disputed_closure_rate=0.0)
    assert perfect == 100.0 and grade == "A"
    assert [b["component"] for b in breakdown] == ["verification", "sla", "repeat", "integrity"]
    assert sum(b["points"] for b in breakdown) == 100.0

    worst, grade, _ = accountability_index(closures=2, verified_closure_rate=0.0, sla_breach_rate=100.0, repeat_failure_rate=100.0, disputed_closure_rate=100.0)
    assert worst == 0.0 and grade == "F"

    # Verification is the heaviest signal: a ward that closes everything unverified cannot pass.
    paper, grade, _ = accountability_index(closures=4, verified_closure_rate=0.0, sla_breach_rate=0.0, repeat_failure_rate=0.0, disputed_closure_rate=0.0)
    assert paper == 60.0 and grade == "C"

    # No closures yet: verification is neutral (50) rather than zero.
    fresh, grade, breakdown = accountability_index(closures=0, verified_closure_rate=None, sla_breach_rate=None, repeat_failure_rate=None, disputed_closure_rate=None)
    assert fresh == 80.0 and grade == "B"
    assert breakdown[0]["reason"].startswith("no closures")


def test_grade_bands_are_monotonic():
    floors = [f for f, _ in GRADE_BANDS]
    assert floors == sorted(floors, reverse=True)
    assert [grade_for(x) for x in (100, 85, 84.9, 70, 55, 40, 39.9, 0)] == ["A", "A", "B", "B", "C", "D", "F", "F"]


def _cluster(**kw):
    now = now_utc()
    base = dict(
        id="CP-X", title="t", status="open", category="pothole", agency="GBA_ROADS", report_count=1, impact_score=50.0,
        created_at=to_iso(now - timedelta(days=2)), sla_due_at=to_iso(now + timedelta(days=1)), resolved_at=None,
        after_photo_path=None, repeat_failure=0, previous_cluster_id=None, verification_verdict=None,
    )
    base.update(kw)
    return base


def test_top_problem_prefers_disputed_then_repeat_then_overdue():
    now = now_utc()
    overdue = _cluster(id="A", status="open", sla_due_at=to_iso(now - timedelta(hours=30)), impact_score=90)
    repeat = _cluster(id="B", status="open", repeat_failure=1, impact_score=40)
    disputed = _cluster(id="C", status="closure_disputed", resolved_at=to_iso(now - timedelta(days=1)), impact_score=10)
    verified = _cluster(id="D", status="resolved_verified", resolved_at=to_iso(now - timedelta(days=1)))
    assert top_problem([overdue, repeat, verified], now)["kind"] == "repeat_failure"
    assert top_problem([overdue, repeat, disputed, verified], now)["cluster_id"] == "C"
    tp = top_problem([overdue, verified], now)
    assert tp["kind"] == "overdue" and 29 < tp["hours_overdue"] < 31
    assert top_problem([verified], now) is None
    # Within the same kind, the higher impact score wins.
    assert top_problem([_cluster(id="lo", impact_score=10), _cluster(id="hi", impact_score=70)], now)["cluster_id"] == "hi"


def test_closure_funnel_counts():
    now = now_utc()
    cs = [
        _cluster(id="1", report_count=4),
        _cluster(id="2", status="resolved_verified", resolved_at=to_iso(now), after_photo_path="a.jpg", report_count=2),
        _cluster(id="3", status="closure_disputed", resolved_at=to_iso(now), after_photo_path="b.jpg"),
        _cluster(id="4", status="resolved_pending_verification", resolved_at=to_iso(now), after_photo_path=None),
    ]
    f = closure_funnel(cs)
    assert f == {
        "reports": 8, "issues": 4, "duplicates_merged_pct": 50.0, "closed": 3, "ai_checked": 2, "no_proof": 1,
        "citizen_verified": 1, "awaiting_proof": 1, "disputed": 1, "unverified_closure_rate": 66.7,
    }


def test_scorecard_exposes_grades_rank_and_funnel(client):
    client.post("/api/admin/seed")
    sc = client.get("/api/wards/scorecard").json()
    rows = sc["wards"]
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert rows == sorted(rows, key=lambda r: (r["accountability_index"], -r["closure_disputed"], -r["sla_breached_open"], r["ward"]))
    for r in rows:
        assert r["grade"] in "ABCDF" and 0 <= r["accountability_index"] <= 100
        assert isinstance(r["low_data"], bool)
        assert len(r["index_breakdown"]) == 4
    kor = next(r for r in rows if r["ward"] == "Koramangala")
    assert kor["grade"] == "F" and kor["top_problem"]["kind"] == "disputed"
    hsr = next(r for r in rows if r["ward"] == "HSR Layout")
    assert hsr["top_problem"]["kind"] == "repeat_failure"
    city = sc["city"]
    assert sum(city["grade_distribution"].values()) == len(rows)
    f = city["funnel"]
    assert f["reports"] == city["reports"] and f["issues"] == city["clusters"] and f["closed"] == city["closures"]
    assert f["citizen_verified"] + f["awaiting_proof"] + f["disputed"] == f["closed"]
    assert f["ai_checked"] + f["no_proof"] == f["closed"]
    assert f["unverified_closure_rate"] == city["unverified_closure_rate"]
