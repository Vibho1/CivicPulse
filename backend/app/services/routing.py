"""Agency routing: who actually owns this issue?

Rules first (deterministic, explainable), with the model's evidence flags used
to re-route road defects caused by utility trenches - the classic Bengaluru
"BWSSB dug it, BBMP has to resurface it" ping-pong.
"""

from __future__ import annotations

from ..domain import AGENCY_INFO, Agency, Category, default_agency
from ..geo import ContextHit
from ..schemas import Extraction

ROAD_CATEGORIES = {Category.POTHOLE, Category.ROAD_DAMAGE, Category.FOOTPATH_DAMAGE}

UTILITY_OWNER: dict[str, tuple[Agency, str]] = {
    "water_pipeline": (Agency.BWSSB, "Road cut from water-pipeline work: BWSSB must restore its trench (road-cut permit liability)."),
    "sewage": (Agency.BWSSB, "Road cut from sewage (UGD) work: BWSSB must restore its trench."),
    "power_cable": (Agency.BESCOM, "Road cut from power-cable trenching: BESCOM must restore the surface."),
    "metro": (Agency.BMRCL, "Damage inside/adjacent to Namma Metro construction: BMRCL is responsible until handover."),
    "telecom": (Agency.GBA_ROADS, "Telecom OFC road cut: GBA Roads (OFC cell) must enforce restoration by the permit holder."),
    "gas": (Agency.GBA_ROADS, "Gas-pipeline road cut: GBA Roads to enforce restoration by the permit holder (GAIL)."),
}

UTILITY_AGENCIES = {Agency.BWSSB, Agency.BESCOM, Agency.BMRCL}


def route(extraction: Extraction, context: list[ContextHit]) -> tuple[Agency, str]:
    cat = extraction.category
    ev = extraction.evidence
    base = default_agency(cat)
    ai_agency = extraction.suggested_agency
    ai_reason = (extraction.agency_reasoning or "").strip()

    if cat in ROAD_CATEGORIES:
        if ev.utility_work_type in UTILITY_OWNER:
            agency, reason = UTILITY_OWNER[ev.utility_work_type]
            if ai_reason and ai_agency == agency:
                reason = f"{reason} Model: {ai_reason}"
            return agency, reason
        if ev.recent_digging and ai_agency in UTILITY_AGENCIES:
            return ai_agency, ai_reason or f"Recent digging visible; {AGENCY_INFO[ai_agency]['short']} identified as the digging agency."
        metro = next((h for h in context if h.type == "metro_construction" and h.distance_m <= 150), None)
        if metro and cat == Category.ROAD_DAMAGE:
            return Agency.BMRCL, f"Within {metro.distance_m} m of {metro.name}; road damage in a metro work zone is BMRCL's to restore."
        if ev.recent_digging:
            return base, "Recent digging visible but the utility is unknown: GBA Roads to identify the road-cut permit holder and enforce restoration."
        return base, ai_reason if (ai_agency == base and ai_reason) else f"{extraction.category.value.replace('_', ' ').title()} on a public road: {AGENCY_INFO[base]['short']} ward engineer."

    if cat == Category.OTHER and ai_agency is not None:
        return ai_agency, ai_reason or "Model-suggested owner for an uncategorised issue."

    if cat == Category.STREETLIGHT and ai_agency == Agency.BESCOM:
        # Streetlight *supply* faults (dead phase/transformer) are BESCOM's; fixtures are the corporation's.
        return Agency.BESCOM, ai_reason or "Supply-side fault (phase/transformer) rather than a fixture failure: BESCOM."

    reason = ai_reason if (ai_agency == base and ai_reason) else f"{AGENCY_INFO[base]['scope'].split(',')[0]}: {AGENCY_INFO[base]['short']}."
    return base, reason
