"""Domain vocabulary for CivicPulse: categories, agencies, statuses, SLAs.

Everything here is deliberately plain data so it can be shared with the
frontend through ``GET /api/meta`` and tuned without touching logic.
"""

from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    # The PRD's parser enum ...
    POTHOLE = "pothole"
    UNRESTORED_UTILITY_TRENCH = "unrestored_utility_trench"
    STREETLIGHT_OUTAGE = "streetlight_outage"
    GARBAGE_DUMP = "garbage_dump"
    WATERLOGGING = "waterlogging"
    DAMAGED_FOOTPATH = "damaged_footpath"
    FALLEN_TREE = "fallen_tree"
    # ... plus Bengaluru issues the PRD's agencies own (BWSSB, BESCOM, BTP) but its enum leaves out.
    ROAD_DAMAGE = "road_damage"
    WATER_LEAK = "water_leak"
    SEWAGE_OVERFLOW = "sewage_overflow"
    OPEN_DRAIN_MANHOLE = "open_drain_manhole"
    POWER_HAZARD = "power_hazard"
    TRAFFIC_SIGNAL = "traffic_signal"
    OTHER = "other"


PRD_CATEGORIES = {
    Category.POTHOLE,
    Category.UNRESTORED_UTILITY_TRENCH,
    Category.STREETLIGHT_OUTAGE,
    Category.GARBAGE_DUMP,
    Category.WATERLOGGING,
    Category.DAMAGED_FOOTPATH,
    Category.FALLEN_TREE,
}

# Category ids used before the PRD names were adopted (migrated in the database).
LEGACY_CATEGORY_IDS = {
    "streetlight": Category.STREETLIGHT_OUTAGE.value,
    "garbage": Category.GARBAGE_DUMP.value,
    "footpath_damage": Category.DAMAGED_FOOTPATH.value,
}

CATEGORY_LABELS: dict[Category, str] = {
    Category.POTHOLE: "Pothole",
    Category.UNRESTORED_UTILITY_TRENCH: "Unrestored utility trench",
    Category.STREETLIGHT_OUTAGE: "Streetlight outage",
    Category.GARBAGE_DUMP: "Garbage dump / black spot",
    Category.WATERLOGGING: "Waterlogging / flooding",
    Category.DAMAGED_FOOTPATH: "Damaged footpath",
    Category.FALLEN_TREE: "Fallen tree / branch",
    Category.ROAD_DAMAGE: "Road damage / cave-in",
    Category.WATER_LEAK: "Water pipeline leak",
    Category.SEWAGE_OVERFLOW: "Sewage overflow",
    Category.OPEN_DRAIN_MANHOLE: "Open drain / manhole",
    Category.POWER_HAZARD: "Dangling wire / electrical hazard",
    Category.TRAFFIC_SIGNAL: "Traffic signal / signage",
    Category.OTHER: "Other",
}


class Agency(str, Enum):
    """Likely owner of an issue. GBA = Greater Bengaluru Authority (ex-BBMP)."""

    GBA_ROADS = "GBA_ROADS"
    GBA_SWM = "GBA_SWM"
    GBA_SWD = "GBA_SWD"
    GBA_ELECTRICAL = "GBA_ELECTRICAL"
    GBA_FORESTRY = "GBA_FORESTRY"
    BWSSB = "BWSSB"
    BESCOM = "BESCOM"
    BMRCL = "BMRCL"
    TRAFFIC_POLICE = "TRAFFIC_POLICE"


# The PRD names the corporation wings BBMP_* and the traffic police BTP. BBMP became the
# Greater Bengaluru Authority in 2025, so ids stay GBA_* and the PRD codes are aliases.
AGENCY_PRD_CODE: dict[Agency, str] = {
    Agency.GBA_ROADS: "BBMP_ROADS",
    Agency.GBA_SWM: "BBMP_SWM",
    Agency.GBA_SWD: "BBMP_SWD",
    Agency.GBA_ELECTRICAL: "BBMP_ELECTRICAL",
    Agency.GBA_FORESTRY: "BBMP_FORESTRY",
    Agency.BWSSB: "BWSSB",
    Agency.BESCOM: "BESCOM",
    Agency.BMRCL: "BMRCL",
    Agency.TRAFFIC_POLICE: "BTP",
}


def agency_from_code(code: str) -> Agency | None:
    """Agency for an id ('GBA_ROADS') or a PRD code ('BBMP_ROADS'); None if unknown."""
    code = (code or "").strip().upper()
    if code in Agency._value2member_map_:
        return Agency(code)
    return next((a for a, c in AGENCY_PRD_CODE.items() if c == code), None)


# Contact details are best-effort public helplines; verify before production use.
AGENCY_INFO: dict[Agency, dict[str, str]] = {
    Agency.GBA_ROADS: {
        "label": "GBA Roads & Infrastructure (ex-BBMP)",
        "short": "GBA Roads",
        "helpline": "1533",
        "x_handle": "@GBA_office",
        "email_hint": "Ward Assistant Executive Engineer (Roads)",
        "scope": "Potholes, road resurfacing, footpaths, road cuts restoration",
    },
    Agency.GBA_SWM: {
        "label": "GBA Solid Waste Management",
        "short": "GBA SWM",
        "helpline": "1533",
        "x_handle": "@GBA_office",
        "email_hint": "Ward SWM Junior Health Inspector",
        "scope": "Garbage black spots, missed collection, dumping",
    },
    Agency.GBA_SWD: {
        "label": "GBA Storm Water Drains",
        "short": "GBA SWD",
        "helpline": "1533",
        "x_handle": "@GBA_office",
        "email_hint": "SWD Executive Engineer (zone)",
        "scope": "Waterlogging, blocked storm drains, rajakaluve overflow",
    },
    Agency.GBA_ELECTRICAL: {
        "label": "GBA Electrical (Streetlights)",
        "short": "GBA Electrical",
        "helpline": "1533",
        "x_handle": "@GBA_office",
        "email_hint": "Ward Electrical AEE",
        "scope": "Streetlights, high-mast lights",
    },
    Agency.GBA_FORESTRY: {
        "label": "GBA Forest Cell",
        "short": "GBA Forest",
        "helpline": "1533",
        "x_handle": "@GBA_office",
        "email_hint": "Range Forest Officer (zone)",
        "scope": "Fallen trees, dangerous branches, tree pruning",
    },
    Agency.BWSSB: {
        "label": "BWSSB (Water Supply & Sewerage)",
        "short": "BWSSB",
        "helpline": "1916",
        "x_handle": "@bwssb_official",
        "email_hint": "Sub-division Assistant Executive Engineer",
        "scope": "Water leaks, sewage overflow, pipeline trenches and road cuts",
    },
    Agency.BESCOM: {
        "label": "BESCOM (Electricity)",
        "short": "BESCOM",
        "helpline": "1912",
        "x_handle": "@NammaBESCOM",
        "email_hint": "Sub-division AEE (Electrical)",
        "scope": "Dangling wires, transformers, poles, power cable trenches",
    },
    Agency.BMRCL: {
        "label": "BMRCL (Namma Metro)",
        "short": "BMRCL",
        "helpline": "080-2296-9300",
        "x_handle": "@OfficialBMRCL",
        "email_hint": "Chief PRO / Section Engineer",
        "scope": "Metro construction barricades, damaged roads under viaducts",
    },
    Agency.TRAFFIC_POLICE: {
        "label": "Bengaluru Traffic Police",
        "short": "Traffic Police",
        "helpline": "112",
        "x_handle": "@blrcitytraffic",
        "email_hint": "Traffic Police Inspector (local station)",
        "scope": "Signals, obstruction, dangerous parking, signage",
    },
}

for _agency, _info in AGENCY_INFO.items():
    _info["code"] = AGENCY_PRD_CODE[_agency]


class ClusterStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    # Official marked it resolved; AI closure-check passed or no proof given yet.
    RESOLVED_PENDING_VERIFICATION = "resolved_pending_verification"
    # A citizen photo (or strong evidence) confirmed the fix.
    RESOLVED_VERIFIED = "resolved_verified"
    # AI / citizens flagged a fake, cosmetic or wrong-location closure.
    CLOSURE_DISPUTED = "closure_disputed"


# Ids predate the PRD; labels use its vocabulary (Pending Verification, Verified Resolved, Unverified Closure).
STATUS_LABELS: dict[ClusterStatus, str] = {
    ClusterStatus.OPEN: "Open",
    ClusterStatus.IN_PROGRESS: "In progress",
    ClusterStatus.RESOLVED_PENDING_VERIFICATION: "Pending verification",
    ClusterStatus.RESOLVED_VERIFIED: "Verified resolved",
    ClusterStatus.CLOSURE_DISPUTED: "Unverified closure",
}

# Statuses that still accept new reports as corroboration.
ACTIVE_STATUSES = {
    ClusterStatus.OPEN,
    ClusterStatus.IN_PROGRESS,
    ClusterStatus.RESOLVED_PENDING_VERIFICATION,
    ClusterStatus.CLOSURE_DISPUTED,
}

CLOSED_STATUSES = {
    ClusterStatus.RESOLVED_PENDING_VERIFICATION,
    ClusterStatus.RESOLVED_VERIFIED,
    ClusterStatus.CLOSURE_DISPUTED,
}


class Verdict(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED_DIFFERENT_LOCATION = "UNVERIFIED_DIFFERENT_LOCATION"
    UNVERIFIED_NOT_FIXED = "UNVERIFIED_NOT_FIXED"
    UNVERIFIED_COSMETIC = "UNVERIFIED_COSMETIC"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_PROOF_PROVIDED = "NO_PROOF_PROVIDED"


class Hazard(str, Enum):
    TWO_WHEELER_SKID_RISK = "two_wheeler_skid_risk"
    PEDESTRIAN_RISK = "pedestrian_risk"
    WATERLOGGING = "waterlogging"
    NIGHT_VISIBILITY = "night_visibility"
    NEAR_SCHOOL = "near_school"
    NEAR_HOSPITAL = "near_hospital"
    ARTERIAL_ROAD = "arterial_road"
    JUNCTION = "junction"
    BUS_STOP = "bus_stop"
    OPEN_DRAIN = "open_drain"
    LIVE_WIRE = "live_wire"
    BLOCKING_TRAFFIC = "blocking_traffic"
    HEALTH_HAZARD = "health_hazard"
    RECENT_DIGGING = "recent_digging"
    RECURRING = "recurring"


# Service-level targets (hours) for an official closure. Tunable assumptions
# modelled on citizen-charter style timelines; shown to users as such (PRD OQ-4).
SLA_HOURS: dict[Category, int] = {
    Category.POTHOLE: 72,
    Category.UNRESTORED_UTILITY_TRENCH: 72,
    Category.STREETLIGHT_OUTAGE: 48,
    Category.GARBAGE_DUMP: 24,
    Category.WATERLOGGING: 24,
    Category.DAMAGED_FOOTPATH: 336,
    Category.FALLEN_TREE: 12,
    Category.ROAD_DAMAGE: 168,
    Category.WATER_LEAK: 24,
    Category.SEWAGE_OVERFLOW: 24,
    Category.OPEN_DRAIN_MANHOLE: 12,
    Category.POWER_HAZARD: 6,
    Category.TRAFFIC_SIGNAL: 24,
    Category.OTHER: 168,
}

# PRD: reports of the same category within 50 m are the same issue.
CLUSTER_RADIUS_M = 50

# PRD: a new report within 25 m of a Verified resolved cluster of the same category,
# within 180 days, is a "repeat failure" (typically inside a contractor's
# defect-liability period).
REPEAT_FAILURE_RADIUS_M = 25
REPEAT_FAILURE_WINDOW_DAYS = 180

# Closure proof: a photo whose GPS (EXIF, or the device position as a fallback)
# is farther than this from the issue cannot show the issue.
VERIFY_GPS_RADIUS_M = 50

# When an official claims a fix, everyone who reported the issue is asked for a
# fresh photo, plus citizens who reported anything this close in this window.
VERIFY_REQUEST_NEARBY_M = 200
VERIFY_REQUEST_LOOKBACK_DAYS = 30

# "I see this too" attaches to the tapped issue only if the citizen is this close.
CORROBORATE_MAX_M = 250

# Below this confidence an uncategorised ("other") report is bounced back with a prompt.
MIN_PARSE_CONFIDENCE = 0.3

# A photo whose EXIF position is this far from the pin is flagged.
PHOTO_LOCATION_WARN_M = 500

# PRD impact score: unique reporters 35 %, severity 30 %, road hierarchy and
# proximity (<= 200 m) to schools / hospitals / transit 20 %, days elapsed 15 %.
SCORE_WEIGHTS: dict[str, int] = {"unique_reporters": 35, "severity": 30, "context": 20, "days_elapsed": 15}
CONTEXT_PROXIMITY_M = 200
SCORE_REPORTERS_FOR_MAX = 10
SCORE_DAYS_FOR_MAX = 30

# CivicPulse does not dispatch emergency services (PRD non-goal); emergencies go to 112.
EMERGENCY_NUMBER = "112"
EMERGENCY_MESSAGE = (
    "If anyone is hurt or in immediate danger, call 112 now. CivicPulse does not dispatch emergency services."
)


def severity_level(severity: int) -> str:
    """PRD vocabulary (low / medium / high / critical) for the 1-5 severity scale."""
    if severity >= 5:
        return "critical"
    if severity == 4:
        return "high"
    if severity == 3:
        return "medium"
    return "low"


def repair_quality(verdict: str, fix_quality: str | None = None) -> str | None:
    """PRD ``repair_quality`` for a verification verdict (None when undecided)."""
    v = Verdict(verdict)
    if v == Verdict.VERIFIED:
        return "verified_complete"
    if v == Verdict.UNVERIFIED_DIFFERENT_LOCATION:
        return "mismatched_location"
    if v == Verdict.UNVERIFIED_COSMETIC:
        return "temporary_or_partial"
    if v == Verdict.UNVERIFIED_NOT_FIXED:
        return "temporary_or_partial" if fix_quality == "partial" else "unrepaired"
    return None


def default_agency(category: Category) -> Agency:
    return {
        Category.POTHOLE: Agency.GBA_ROADS,
        # Without evidence of which utility dug it, GBA Roads enforces the road-cut permit.
        Category.UNRESTORED_UTILITY_TRENCH: Agency.GBA_ROADS,
        Category.STREETLIGHT_OUTAGE: Agency.GBA_ELECTRICAL,
        Category.GARBAGE_DUMP: Agency.GBA_SWM,
        Category.WATERLOGGING: Agency.GBA_SWD,
        Category.DAMAGED_FOOTPATH: Agency.GBA_ROADS,
        Category.FALLEN_TREE: Agency.GBA_FORESTRY,
        Category.ROAD_DAMAGE: Agency.GBA_ROADS,
        Category.WATER_LEAK: Agency.BWSSB,
        Category.SEWAGE_OVERFLOW: Agency.BWSSB,
        Category.OPEN_DRAIN_MANHOLE: Agency.BWSSB,
        Category.POWER_HAZARD: Agency.BESCOM,
        Category.TRAFFIC_SIGNAL: Agency.TRAFFIC_POLICE,
        Category.OTHER: Agency.GBA_ROADS,
    }[category]


def meta() -> dict:
    """Vocabulary bundle for the frontend."""
    return {
        "categories": [
            {"id": c.value, "label": CATEGORY_LABELS[c], "sla_hours": SLA_HOURS[c], "prd": c in PRD_CATEGORIES}
            for c in Category
        ],
        "agencies": [{"id": a.value, **AGENCY_INFO[a]} for a in Agency],
        "statuses": [{"id": s.value, "label": STATUS_LABELS[s]} for s in ClusterStatus],
        "verdicts": [v.value for v in Verdict],
        "hazards": [h.value for h in Hazard],
        "score_weights": dict(SCORE_WEIGHTS),
        "cluster_radius_m": CLUSTER_RADIUS_M,
        "repeat_failure_radius_m": REPEAT_FAILURE_RADIUS_M,
        "repeat_failure_window_days": REPEAT_FAILURE_WINDOW_DAYS,
        "emergency_number": EMERGENCY_NUMBER,
    }
