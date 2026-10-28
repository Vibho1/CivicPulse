"""Agency routing: who actually owns this issue?

Rules first (deterministic, explainable), with the model's evidence flags used
to re-route road defects caused by utility trenches - the classic Bengaluru
"BWSSB dug it, BBMP has to resurface it" ping-pong.

Every decision names a primary owner, an optional secondary owner (e.g. the GBA
Roads wing that signs off resurfacing after a utility restores its trench) and
a 0-1 routing confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import AGENCY_INFO, Agency, Category, Hazard, default_agency
from ..geo import ContextHit
from ..schemas import Extraction

ROAD_CATEGORIES = {Category.POTHOLE, Category.ROAD_DAMAGE, Category.DAMAGED_FOOTPATH, Category.UNRESTORED_UTILITY_TRENCH}
WATER_CATEGORIES = {Category.WATER_LEAK, Category.SEWAGE_OVERFLOW, Category.OPEN_DRAIN_MANHOLE}

UTILITY_OWNER: dict[str, tuple[Agency, str]] = {
    "water_pipeline": (Agency.BWSSB, "Road cut from water-pipeline work: BWSSB must restore its trench (road-cut permit liability)."),
    "sewage": (Agency.BWSSB, "Road cut from sewage (UGD) work: BWSSB must restore its trench."),
    "power_cable": (Agency.BESCOM, "Road cut from power-cable trenching: BESCOM must restore the surface."),
    "metro": (Agency.BMRCL, "Damage inside/adjacent to Namma Metro construction: BMRCL is responsible until handover."),
    "telecom": (Agency.GBA_ROADS, "Telecom OFC road cut: GBA Roads (OFC cell) must enforce restoration by the permit holder."),
    "gas": (Agency.GBA_ROADS, "Gas-pipeline road cut: GBA Roads to enforce restoration by the permit holder (GAIL)."),
}

UTILITY_AGENCIES = {Agency.BWSSB, Agency.BESCOM, Agency.BMRCL}

# How far each rule can be trusted on its own, before blending in the model's
# overall extraction confidence and whether the model's suggestion agrees.
RULE_STRENGTH: dict[str, float] = {
    "utility_evidence": 0.92,  # pipe / cable / metro works visible at the defect
    "category_default": 0.9,  # the category -> owner mapping is unambiguous
    "metro_zone": 0.85,  # GIS: inside a metro construction zone
    "digging_model": 0.8,  # fresh digging and the model names the utility
    "supply_fault": 0.7,  # streetlight supply-side fault (model's call)
    "digging_unknown": 0.6,  # digging seen but owner unknown: GBA enforces
    "model_only": 0.55,  # uncategorised issue: the model's suggested owner
    "fallback": 0.35,  # uncategorised, no suggestion: GBA Roads by default
}


@dataclass(frozen=True)
class RouteDecision:
    agency: Agency
    reason: str
    confidence: float
    secondary_agency: Agency | None = None
    secondary_reason: str | None = None


def routing_confidence(rule: str, extraction: Extraction, agency: Agency) -> float:
    """0-1: rule strength x category certainty, nudged by model (dis)agreement."""
    certainty = max(0.0, min(1.0, extraction.confidence))
    conf = RULE_STRENGTH[rule] * (0.5 + 0.5 * certainty)
    if extraction.suggested_agency is not None:
        conf += 0.05 if extraction.suggested_agency == agency else -0.1
    return round(max(0.05, min(0.99, conf)), 2)


def secondary_owner(extraction: Extraction, primary: Agency) -> tuple[Agency | None, str | None]:
    """Agency that shares responsibility with the primary owner, if any."""
    cat = extraction.category
    hazards = {Hazard(h) for h in extraction.hazards}
    if primary in UTILITY_AGENCIES and cat in ROAD_CATEGORIES:
        if primary == Agency.BMRCL:
            return Agency.GBA_ROADS, "GBA Roads takes back surface maintenance once BMRCL restores and hands over the stretch."
        short = AGENCY_INFO[primary]["short"]
        return Agency.GBA_ROADS, f"GBA Roads signs off final resurfacing once {short} restores its road cut (road-cut permit condition)."
    if cat in WATER_CATEGORIES and primary == Agency.BWSSB and extraction.evidence.recent_digging:
        return Agency.GBA_ROADS, "GBA Roads restores the road surface after BWSSB completes the repair."
    if cat == Category.FALLEN_TREE and Hazard.LIVE_WIRE in hazards:
        return Agency.BESCOM, "BESCOM must isolate the supply before the tree is cleared (lines entangled)."
    if Hazard.BLOCKING_TRAFFIC in hazards and primary != Agency.TRAFFIC_POLICE:
        return Agency.TRAFFIC_POLICE, "Traffic Police manage diversion and road safety until the fix is done."
    return None, None


def route(extraction: Extraction, context: list[ContextHit]) -> RouteDecision:
    cat = extraction.category
    ev = extraction.evidence
    base = default_agency(cat)
    ai_agency = extraction.suggested_agency
    ai_reason = (extraction.agency_reasoning or "").strip()

    def decide(agency: Agency, reason: str, rule: str) -> RouteDecision:
        secondary, secondary_reason = secondary_owner(extraction, agency)
        return RouteDecision(agency, reason, routing_confidence(rule, extraction, agency), secondary, secondary_reason)

    if cat in ROAD_CATEGORIES:
        # A trench report is evidence of digging even when the model did not flag it.
        digging = ev.recent_digging or cat == Category.UNRESTORED_UTILITY_TRENCH
        if ev.utility_work_type in UTILITY_OWNER:
            agency, reason = UTILITY_OWNER[ev.utility_work_type]
            if ai_reason and ai_agency == agency:
                reason = f"{reason} Model: {ai_reason}"
            return decide(agency, reason, "utility_evidence")
        if digging and ai_agency in UTILITY_AGENCIES:
            return decide(ai_agency, ai_reason or f"Recent digging visible; {AGENCY_INFO[ai_agency]['short']} identified as the digging agency.", "digging_model")
        metro = next((h for h in context if h.type == "metro_construction" and h.distance_m <= 150), None)
        if metro and cat in (Category.ROAD_DAMAGE, Category.UNRESTORED_UTILITY_TRENCH):
            return decide(Agency.BMRCL, f"Within {metro.distance_m} m of {metro.name}; road damage in a metro work zone is BMRCL's to restore.", "metro_zone")
        if digging:
            return decide(base, "Recent digging visible but the utility is unknown: GBA Roads to identify the road-cut permit holder and enforce restoration.", "digging_unknown")
        reason = ai_reason if (ai_agency == base and ai_reason) else f"{extraction.category.value.replace('_', ' ').title()} on a public road: {AGENCY_INFO[base]['short']} ward engineer."
        return decide(base, reason, "category_default")

    if cat == Category.OTHER and ai_agency is not None:
        return decide(ai_agency, ai_reason or "Model-suggested owner for an uncategorised issue.", "model_only")

    if cat == Category.STREETLIGHT_OUTAGE and ai_agency == Agency.BESCOM:
        # Streetlight *supply* faults (dead phase/transformer) are BESCOM's; fixtures are the corporation's.
        return decide(Agency.BESCOM, ai_reason or "Supply-side fault (phase/transformer) rather than a fixture failure: BESCOM.", "supply_fault")

    reason = ai_reason if (ai_agency == base and ai_reason) else f"{AGENCY_INFO[base]['scope'].split(',')[0]}: {AGENCY_INFO[base]['short']}."
    return decide(base, reason, "fallback" if cat == Category.OTHER else "category_default")
