from __future__ import annotations

from datetime import timedelta

from app.domain import Agency, Category, ClusterStatus, Hazard
from app.geo import ContextHit
from app.schemas import EvidenceFlags, Extraction
from app.services.common import now_utc, sla_due, to_iso
from app.services.routing import route
from app.services.scoring import compute_score


def ex(**kw) -> Extraction:
    base = dict(
        is_civic_issue=True, transcript="", transcript_english="x", language="en", category=Category.POTHOLE,
        severity=3, title="t", description="d", hazards=[], evidence=EvidenceFlags(), confidence=0.8,
    )
    base.update(kw)
    return Extraction(**base)


def test_pothole_defaults_to_roads():
    agency, reason = route(ex(), [])
    assert agency == Agency.GBA_ROADS
    assert reason


def test_pothole_with_pipeline_trench_routes_to_bwssb():
    e = ex(evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline"))
    agency, reason = route(e, [])
    assert agency == Agency.BWSSB
    assert "BWSSB" in reason


def test_recent_digging_with_model_hint_routes_to_utility():
    e = ex(evidence=EvidenceFlags(recent_digging=True, utility_work_type="unknown"), suggested_agency=Agency.BESCOM, agency_reasoning="cable duct visible")
    assert route(e, [])[0] == Agency.BESCOM


def test_road_damage_in_metro_zone_routes_to_bmrcl():
    e = ex(category=Category.ROAD_DAMAGE)
    ctx = [ContextHit("Kadubeesanahalli Metro (under construction)", "metro_construction", 80)]
    assert route(e, ctx)[0] == Agency.BMRCL


def test_non_road_categories_are_deterministic():
    assert route(ex(category=Category.GARBAGE), [])[0] == Agency.GBA_SWM
    assert route(ex(category=Category.WATERLOGGING), [])[0] == Agency.GBA_SWD
    assert route(ex(category=Category.STREETLIGHT), [])[0] == Agency.GBA_ELECTRICAL
    assert route(ex(category=Category.POWER_HAZARD), [])[0] == Agency.BESCOM
    assert route(ex(category=Category.TRAFFIC_SIGNAL), [])[0] == Agency.TRAFFIC_POLICE
    # a wrong model suggestion does not override a deterministic category
    assert route(ex(category=Category.GARBAGE, suggested_agency=Agency.BMRCL), [])[0] == Agency.GBA_SWM


def _score(**kw):
    now = now_utc()
    created = to_iso(now - timedelta(hours=kw.pop("age_h", 1)))
    args = dict(report_count=1, max_severity=3, hazards=[], context=[], created_at=created,
                sla_due_at=sla_due(created, Category.POTHOLE), status=ClusterStatus.OPEN, repeat_failure=False, now=now)
    args.update(kw)
    return compute_score(**args)


def test_more_reports_and_severity_raise_score():
    assert _score(report_count=4).total > _score(report_count=1).total
    assert _score(max_severity=5).total > _score(max_severity=2).total


def test_context_and_hazards_add_points():
    base = _score().total
    with_ctx = _score(context=[ContextHit("School", "school", 100), ContextHit("ORR", "arterial_road", 20)]).total
    assert with_ctx - base == 14
    with_hz = _score(hazards=[Hazard.LIVE_WIRE.value, Hazard.OPEN_DRAIN.value]).total
    assert with_hz - base == 15  # capped at 15


def test_sla_breach_adds_ten_and_is_capped_at_100():
    fresh = _score(age_h=1)
    breached = _score(age_h=100)  # pothole SLA is 72h
    assert breached.total - fresh.total == 10
    assert any(c.component == "sla" and c.points == 10 for c in breached.components)
    maxed = _score(report_count=50, max_severity=5, age_h=500, repeat_failure=True,
                   hazards=[Hazard.LIVE_WIRE.value, Hazard.OPEN_DRAIN.value],
                   context=[ContextHit("S", "school", 10), ContextHit("H", "hospital", 10), ContextHit("R", "arterial_road", 10)])
    assert maxed.total == 100


def test_resolved_clusters_have_no_sla_pressure():
    s = _score(age_h=500, status=ClusterStatus.RESOLVED_VERIFIED)
    assert next(c for c in s.components if c.component == "sla").points == 0
