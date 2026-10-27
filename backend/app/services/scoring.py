"""Civic impact score (0-100) with an explainable breakdown.

Components:
  corroboration  how many independent citizens reported it (log-scaled)
  severity       worst severity across reports
  context        sensitive surroundings: schools, hospitals, arterial roads, junctions
  hazard         risk flags: two-wheeler skids, live wires, open drains, night visibility
  sla            how far past the service target the issue is
  repeat         failed again inside the repeat-failure window
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

from ..domain import ClusterStatus, Hazard
from ..geo import ContextHit
from ..schemas import ScoreBreakdown, ScoreComponent
from .common import now_utc, parse_iso

CONTEXT_POINTS = {
    "school": (8, "school zone"),
    "hospital": (7, "hospital access"),
    "arterial_road": (6, "arterial road"),
    "junction": (4, "busy junction"),
    "bus_stand": (3, "bus stand footfall"),
    "metro_station": (3, "metro station footfall"),
    "metro_construction": (2, "metro work zone"),
}

HAZARD_POINTS = {
    Hazard.LIVE_WIRE: (10, "live wire"),
    Hazard.OPEN_DRAIN: (8, "open drain / manhole"),
    Hazard.TWO_WHEELER_SKID_RISK: (7, "two-wheeler skid risk"),
    Hazard.WATERLOGGING: (4, "waterlogging"),
    Hazard.PEDESTRIAN_RISK: (4, "pedestrian risk"),
    Hazard.HEALTH_HAZARD: (4, "health hazard"),
    Hazard.NIGHT_VISIBILITY: (3, "poor night visibility"),
    Hazard.BLOCKING_TRAFFIC: (3, "blocking traffic"),
}

# Hazard flags that duplicate context data when the model spots them itself.
HAZARD_AS_CONTEXT = {
    Hazard.NEAR_SCHOOL: "school",
    Hazard.NEAR_HOSPITAL: "hospital",
    Hazard.ARTERIAL_ROAD: "arterial_road",
    Hazard.JUNCTION: "junction",
    Hazard.BUS_STOP: "bus_stand",
}

UNRESOLVED = {ClusterStatus.OPEN, ClusterStatus.IN_PROGRESS, ClusterStatus.CLOSURE_DISPUTED}


def compute_score(
    *,
    report_count: int,
    max_severity: int,
    hazards: Iterable[str],
    context: list[ContextHit],
    created_at: str,
    sla_due_at: str,
    status: ClusterStatus,
    repeat_failure: bool,
    now: datetime | None = None,
) -> ScoreBreakdown:
    now = now or now_utc()
    comps: list[ScoreComponent] = []

    n = max(1, report_count)
    comps.append(ScoreComponent(component="corroboration", points=round(min(30.0, 10 * math.log2(1 + n)), 1), reason=f"{n} independent report{'s' if n != 1 else ''}"))

    sev = max(1, min(5, max_severity))
    comps.append(ScoreComponent(component="severity", points=round(sev / 5 * 30, 1), reason=f"max severity {sev}/5"))

    # Context: merge GIS hits with model flags, count each type once.
    seen: dict[str, str] = {}
    for h in context:
        if h.type in CONTEXT_POINTS and h.type not in seen:
            seen[h.type] = f"{h.name} ({h.distance_m} m)"
    hz = {Hazard(x) for x in hazards if x in Hazard._value2member_map_}
    for flag, ctx_type in HAZARD_AS_CONTEXT.items():
        if flag in hz and ctx_type not in seen:
            seen[ctx_type] = "reported by citizen"
    ctx_pts = 0.0
    ctx_reasons = []
    for ctx_type, label in seen.items():
        pts, what = CONTEXT_POINTS[ctx_type]
        ctx_pts += pts
        ctx_reasons.append(f"{what}: {label}")
    comps.append(ScoreComponent(component="context", points=min(20.0, ctx_pts), reason="; ".join(ctx_reasons) or "no sensitive zones nearby"))

    hz_pts = 0.0
    hz_reasons = []
    for flag, (pts, what) in HAZARD_POINTS.items():
        if flag in hz:
            hz_pts += pts
            hz_reasons.append(what)
    comps.append(ScoreComponent(component="hazard", points=min(15.0, hz_pts), reason=", ".join(hz_reasons) or "no acute hazard flags"))

    sla_pts, sla_reason = 0.0, "within service target"
    if status in UNRESOLVED:
        start, due = parse_iso(created_at), parse_iso(sla_due_at)
        span = max((due - start).total_seconds(), 1.0)
        frac = (now - start).total_seconds() / span
        if frac >= 1:
            overdue_h = (now - due).total_seconds() / 3600
            sla_pts, sla_reason = 10.0, f"SLA breached by {overdue_h / 24:.1f} days" if overdue_h >= 24 else f"SLA breached by {overdue_h:.0f} h"
        elif frac >= 0.5:
            sla_pts, sla_reason = 5.0, "past 50% of service target"
    comps.append(ScoreComponent(component="sla", points=sla_pts, reason=sla_reason))

    if repeat_failure:
        comps.append(ScoreComponent(component="repeat_failure", points=10.0, reason="failed again inside the repeat-failure window (possible warranty claim)"))

    total = round(min(100.0, sum(c.points for c in comps)), 1)
    return ScoreBreakdown(total=total, components=comps)
