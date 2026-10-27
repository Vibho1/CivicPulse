"""Domain vocabulary for CivicPulse: categories, agencies, statuses, SLAs.

Everything here is deliberately plain data so it can be shared with the
frontend through ``GET /api/meta`` and tuned without touching logic.
"""

from __future__ import annotations

from enum import Enum


class Category(str, Enum):
    POTHOLE = "pothole"
    ROAD_DAMAGE = "road_damage"
    FOOTPATH_DAMAGE = "footpath_damage"
    STREETLIGHT = "streetlight"
    GARBAGE = "garbage"
    WATER_LEAK = "water_leak"
    SEWAGE_OVERFLOW = "sewage_overflow"
    OPEN_DRAIN_MANHOLE = "open_drain_manhole"
    WATERLOGGING = "waterlogging"
    FALLEN_TREE = "fallen_tree"
    POWER_HAZARD = "power_hazard"
    TRAFFIC_SIGNAL = "traffic_signal"
    OTHER = "other"


CATEGORY_LABELS: dict[Category, str] = {
    Category.POTHOLE: "Pothole",
    Category.ROAD_DAMAGE: "Road damage / cave-in",
    Category.FOOTPATH_DAMAGE: "Footpath damage",
    Category.STREETLIGHT: "Streetlight not working",
    Category.GARBAGE: "Garbage / black spot",
    Category.WATER_LEAK: "Water pipeline leak",
    Category.SEWAGE_OVERFLOW: "Sewage overflow",
    Category.OPEN_DRAIN_MANHOLE: "Open drain / manhole",
    Category.WATERLOGGING: "Waterlogging / flooding",
    Category.FALLEN_TREE: "Fallen tree / branch",
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


class ClusterStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    # Official marked it resolved; AI closure-check passed or no proof given yet.
    RESOLVED_PENDING_VERIFICATION = "resolved_pending_verification"
    # A citizen photo (or strong evidence) confirmed the fix.
    RESOLVED_VERIFIED = "resolved_verified"
    # AI / citizens flagged a fake, cosmetic or wrong-location closure.
    CLOSURE_DISPUTED = "closure_disputed"


STATUS_LABELS: dict[ClusterStatus, str] = {
    ClusterStatus.OPEN: "Open",
    ClusterStatus.IN_PROGRESS: "In progress",
    ClusterStatus.RESOLVED_PENDING_VERIFICATION: "Resolved - awaiting proof",
    ClusterStatus.RESOLVED_VERIFIED: "Resolved - verified",
    ClusterStatus.CLOSURE_DISPUTED: "Closure disputed",
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
# modelled on citizen-charter style timelines; shown to users as such.
SLA_HOURS: dict[Category, int] = {
    Category.POTHOLE: 72,
    Category.ROAD_DAMAGE: 168,
    Category.FOOTPATH_DAMAGE: 336,
    Category.STREETLIGHT: 48,
    Category.GARBAGE: 24,
    Category.WATER_LEAK: 24,
    Category.SEWAGE_OVERFLOW: 24,
    Category.OPEN_DRAIN_MANHOLE: 12,
    Category.WATERLOGGING: 24,
    Category.FALLEN_TREE: 12,
    Category.POWER_HAZARD: 6,
    Category.TRAFFIC_SIGNAL: 24,
    Category.OTHER: 168,
}

# Reports of the same category within this many metres are the same issue.
CLUSTER_RADIUS_M: dict[Category, int] = {
    Category.POTHOLE: 60,
    Category.ROAD_DAMAGE: 80,
    Category.FOOTPATH_DAMAGE: 60,
    Category.STREETLIGHT: 45,
    Category.GARBAGE: 90,
    Category.WATER_LEAK: 60,
    Category.SEWAGE_OVERFLOW: 90,
    Category.OPEN_DRAIN_MANHOLE: 40,
    Category.WATERLOGGING: 180,
    Category.FALLEN_TREE: 60,
    Category.POWER_HAZARD: 50,
    Category.TRAFFIC_SIGNAL: 60,
    Category.OTHER: 75,
}

# A verified fix that fails again within this window is a "repeat failure"
# (typically inside a contractor's defect-liability period).
REPEAT_FAILURE_WINDOW_DAYS = 180


def default_agency(category: Category) -> Agency:
    return {
        Category.POTHOLE: Agency.GBA_ROADS,
        Category.ROAD_DAMAGE: Agency.GBA_ROADS,
        Category.FOOTPATH_DAMAGE: Agency.GBA_ROADS,
        Category.STREETLIGHT: Agency.GBA_ELECTRICAL,
        Category.GARBAGE: Agency.GBA_SWM,
        Category.WATER_LEAK: Agency.BWSSB,
        Category.SEWAGE_OVERFLOW: Agency.BWSSB,
        Category.OPEN_DRAIN_MANHOLE: Agency.BWSSB,
        Category.WATERLOGGING: Agency.GBA_SWD,
        Category.FALLEN_TREE: Agency.GBA_FORESTRY,
        Category.POWER_HAZARD: Agency.BESCOM,
        Category.TRAFFIC_SIGNAL: Agency.TRAFFIC_POLICE,
        Category.OTHER: Agency.GBA_ROADS,
    }[category]


def meta() -> dict:
    """Vocabulary bundle for the frontend."""
    return {
        "categories": [
            {"id": c.value, "label": CATEGORY_LABELS[c], "sla_hours": SLA_HOURS[c]}
            for c in Category
        ],
        "agencies": [{"id": a.value, **AGENCY_INFO[a]} for a in Agency],
        "statuses": [{"id": s.value, "label": STATUS_LABELS[s]} for s in ClusterStatus],
        "verdicts": [v.value for v in Verdict],
        "hazards": [h.value for h in Hazard],
        "repeat_failure_window_days": REPEAT_FAILURE_WINDOW_DAYS,
    }
