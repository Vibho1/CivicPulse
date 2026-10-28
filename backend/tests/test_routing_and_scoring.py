from __future__ import annotations

from datetime import timedelta

from app.domain import (
    AGENCY_PRD_CODE,
    SCORE_WEIGHTS,
    Agency,
    Category,
    ClusterStatus,
    Hazard,
    agency_from_code,
    repair_quality,
    severity_level,
)
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
    d = route(ex(), [])
    assert d.agency == Agency.GBA_ROADS
    assert d.reason
    assert d.secondary_agency is None
    assert 0.0 < d.confidence < 1.0


def test_pothole_with_pipeline_trench_routes_to_bwssb():
    e = ex(evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline"))
    d = route(e, [])
    assert d.agency == Agency.BWSSB
    assert "BWSSB" in d.reason


def test_pipeline_trench_names_gba_roads_as_secondary_resurfacing_owner():
    # PRD REQ-ROUTE-AGENCY acceptance: BWSSB primary, roads wing secondary, rationale cites the pipeline.
    e = ex(
        evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline"),
        suggested_agency=Agency.BWSSB, agency_reasoning="Blue water pipe visible at the trench edge.", confidence=0.92,
    )
    d = route(e, [])
    assert d.agency == Agency.BWSSB
    assert d.secondary_agency == Agency.GBA_ROADS
    assert "resurfacing" in (d.secondary_reason or "")
    assert "pipeline" in d.reason.lower()
    assert d.confidence >= 0.9


def test_recent_digging_with_model_hint_routes_to_utility():
    e = ex(evidence=EvidenceFlags(recent_digging=True, utility_work_type="unknown"), suggested_agency=Agency.BESCOM, agency_reasoning="cable duct visible")
    d = route(e, [])
    assert d.agency == Agency.BESCOM
    assert d.secondary_agency == Agency.GBA_ROADS


def test_road_damage_in_metro_zone_routes_to_bmrcl():
    e = ex(category=Category.ROAD_DAMAGE)
    ctx = [ContextHit("Kadubeesanahalli Metro (under construction)", "metro_construction", 80)]
    d = route(e, ctx)
    assert d.agency == Agency.BMRCL
    assert d.secondary_agency == Agency.GBA_ROADS


def test_non_road_categories_are_deterministic():
    assert route(ex(category=Category.GARBAGE_DUMP), []).agency == Agency.GBA_SWM
    assert route(ex(category=Category.WATERLOGGING), []).agency == Agency.GBA_SWD
    assert route(ex(category=Category.STREETLIGHT_OUTAGE), []).agency == Agency.GBA_ELECTRICAL
    assert route(ex(category=Category.POWER_HAZARD), []).agency == Agency.BESCOM
    assert route(ex(category=Category.TRAFFIC_SIGNAL), []).agency == Agency.TRAFFIC_POLICE
    # a wrong model suggestion does not override a deterministic category
    assert route(ex(category=Category.GARBAGE_DUMP, suggested_agency=Agency.BMRCL), []).agency == Agency.GBA_SWM


def test_unrestored_utility_trench_goes_to_the_digging_utility():
    # PRD: pipeline excavation -> BWSSB primary, roads wing (BBMP_ROADS) secondary for resurfacing
    trench = route(ex(category=Category.UNRESTORED_UTILITY_TRENCH, evidence=EvidenceFlags(utility_work_type="water_pipeline")), [])
    assert (trench.agency, trench.secondary_agency) == (Agency.BWSSB, Agency.GBA_ROADS)
    # unknown digger: GBA Roads enforces the road-cut permit even if the model did not flag digging
    unknown = route(ex(category=Category.UNRESTORED_UTILITY_TRENCH), [])
    assert unknown.agency == Agency.GBA_ROADS and "permit" in unknown.reason


def test_secondary_owners_for_shared_responsibility():
    tree = route(ex(category=Category.FALLEN_TREE, hazards=[Hazard.LIVE_WIRE, Hazard.BLOCKING_TRAFFIC]), [])
    assert (tree.agency, tree.secondary_agency) == (Agency.GBA_FORESTRY, Agency.BESCOM)
    flood = route(ex(category=Category.WATERLOGGING, hazards=[Hazard.BLOCKING_TRAFFIC]), [])
    assert (flood.agency, flood.secondary_agency) == (Agency.GBA_SWD, Agency.TRAFFIC_POLICE)
    leak = route(ex(category=Category.WATER_LEAK, evidence=EvidenceFlags(recent_digging=True)), [])
    assert (leak.agency, leak.secondary_agency) == (Agency.BWSSB, Agency.GBA_ROADS)
    assert route(ex(category=Category.TRAFFIC_SIGNAL, hazards=[Hazard.BLOCKING_TRAFFIC]), []).secondary_agency is None


def test_routing_confidence_reflects_evidence_and_model_agreement():
    trench = ex(evidence=EvidenceFlags(recent_digging=True, utility_work_type="water_pipeline"), confidence=0.9)
    agree = route(trench.model_copy(update={"suggested_agency": Agency.BWSSB}), []).confidence
    disagree = route(trench.model_copy(update={"suggested_agency": Agency.GBA_ROADS}), []).confidence
    assert agree > disagree
    unknown = route(ex(category=Category.OTHER, confidence=0.2), [])
    assert unknown.agency == Agency.GBA_ROADS and unknown.confidence < 0.5
    assert all(0.0 <= d.confidence <= 1.0 for d in (route(trench, []), unknown))


def test_prd_vocabulary_mappers():
    assert [severity_level(s) for s in (1, 2, 3, 4, 5)] == ["low", "low", "medium", "high", "critical"]
    assert repair_quality("VERIFIED", "proper") == "verified_complete"
    assert repair_quality("UNVERIFIED_COSMETIC", "cosmetic") == "temporary_or_partial"
    assert repair_quality("UNVERIFIED_NOT_FIXED", "none") == "unrepaired"
    assert repair_quality("UNVERIFIED_NOT_FIXED", "partial") == "temporary_or_partial"
    assert repair_quality("UNVERIFIED_DIFFERENT_LOCATION", "unknown") == "mismatched_location"
    assert repair_quality("INCONCLUSIVE") is None and repair_quality("NO_PROOF_PROVIDED") is None


def test_prd_agency_codes_are_aliases():
    assert AGENCY_PRD_CODE[Agency.GBA_ROADS] == "BBMP_ROADS" and AGENCY_PRD_CODE[Agency.TRAFFIC_POLICE] == "BTP"
    assert agency_from_code("BBMP_SWM") == Agency.GBA_SWM
    assert agency_from_code("btp") == Agency.TRAFFIC_POLICE
    assert agency_from_code("GBA_ROADS") == Agency.GBA_ROADS
    assert agency_from_code("NOPE") is None


def _score(**kw):
    now = now_utc()
    created = to_iso(now - timedelta(hours=kw.pop("age_h", 1)))
    args = dict(report_count=1, max_severity=3, hazards=[], context=[], created_at=created,
                sla_due_at=sla_due(created, Category.POTHOLE), status=ClusterStatus.OPEN, now=now)
    args.update(kw)
    return compute_score(**args)


def _points(score, component):
    return next(c.points for c in score.components if c.component == component)


def test_score_uses_the_prd_components_and_weights():
    s = _score()
    assert [c.component for c in s.components] == list(SCORE_WEIGHTS)
    assert SCORE_WEIGHTS == {"unique_reporters": 35, "severity": 30, "context": 20, "days_elapsed": 15}
    maxed = _score(reporter_count=12, report_count=12, max_severity=5, age_h=24 * 40,
                   context=[ContextHit("S", "school", 10), ContextHit("H", "hospital", 10), ContextHit("R", "arterial_road", 10)])
    assert {c.component: c.points for c in maxed.components} == SCORE_WEIGHTS
    assert maxed.total == 100


def test_more_reports_and_severity_raise_score():
    assert _score(report_count=4).total > _score(report_count=1).total
    assert _score(max_severity=5).total > _score(max_severity=2).total
    assert [_points(_score(max_severity=s), "severity") for s in (2, 3, 4, 5)] == [7.5, 15.0, 22.5, 30.0]


def test_corroboration_counts_unique_citizens_not_repeat_reports():
    spammed = _score(report_count=6, reporter_count=1)
    genuine = _score(report_count=6, reporter_count=6)
    assert spammed.total < genuine.total
    assert spammed.total == _score(report_count=1, reporter_count=1).total
    reason = next(c.reason for c in spammed.components if c.component == "unique_reporters")
    assert reason == "1 independent citizen (6 reports)"
    assert _points(_score(reporter_count=10, report_count=10), "unique_reporters") == 35


def test_context_counts_road_hierarchy_and_places_within_200_m():
    base = _points(_score(), "context")
    assert base == 0
    near = _score(context=[ContextHit("School", "school", 150), ContextHit("ORR", "arterial_road", 20)])
    assert _points(near, "context") == 15  # arterial 10 + school 5
    far = _score(context=[ContextHit("School", "school", 260)])
    assert _points(far, "context") == 0  # beyond the PRD's 200 m
    transit = _score(context=[ContextHit("Bus", "bus_stand", 50), ContextHit("Metro", "metro_station", 90)])
    assert _points(transit, "context") == 4  # transit hubs count once
    # hazard flags do not add points any more (PRD formula), except the ones that describe context
    assert _score(hazards=[Hazard.LIVE_WIRE.value]).total == _score().total
    assert _points(_score(hazards=[Hazard.NEAR_SCHOOL.value]), "context") == 5


def test_days_elapsed_grows_linearly_and_notes_sla_breach():
    fresh = _score(age_h=1)
    breached = _score(age_h=24 * 15)  # pothole SLA is 72 h
    assert _points(breached, "days_elapsed") == 7.5
    assert "SLA breached" in next(c.reason for c in breached.components if c.component == "days_elapsed")
    assert _points(fresh, "days_elapsed") < 0.1
    assert _points(_score(age_h=24 * 90), "days_elapsed") == 15


def test_days_elapsed_clock_stops_at_the_official_closure():
    now = now_utc()
    created = to_iso(now - timedelta(days=20))
    closed = to_iso(now - timedelta(days=14))
    s = _score(created_at=created, sla_due_at=sla_due(created, Category.POTHOLE), status=ClusterStatus.RESOLVED_VERIFIED, resolved_at=closed)
    assert _points(s, "days_elapsed") == 3.0  # 6 days of 30
    assert "clock stopped" in next(c.reason for c in s.components if c.component == "days_elapsed")
