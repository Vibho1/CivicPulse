"""Civic impact score (0-100) with the PRD weights and an explainable breakdown.

Components (PRD 4.3):
  unique_reporters  35  independent citizens (log-scaled, 10+ = full marks; repeats by one citizen count once)
  severity          30  worst severity across reports: low / medium / high / critical
  context           20  road hierarchy (arterial road, busy junction) and proximity (<= 200 m)
                        to schools, hospitals and transit hubs
  days_elapsed      15  days since the first report (full marks at 30 days; frozen once an
                        official claims a fix)

Hazard flags (live wire, open drain, ...) still drive severity, routing and the
escalation text; repeat failures are flagged separately. Neither adds points, so
the score stays exactly the PRD formula.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

from ..domain import (
    CONTEXT_PROXIMITY_M,
    SCORE_DAYS_FOR_MAX,
    SCORE_REPORTERS_FOR_MAX,
    SCORE_WEIGHTS,
    ClusterStatus,
    Hazard,
    severity_level,
)
from ..geo import ContextHit
from ..schemas import ScoreBreakdown, ScoreComponent
from .common import now_utc, parse_iso

# Road hierarchy: the busiest road type near the issue counts once.
ROAD_POINTS = {
    "arterial_road": (10, "arterial road"),
    "junction": (5, "busy junction"),
}

# Sensitive places within CONTEXT_PROXIMITY_M; transit hubs count once.
PROXIMITY_POINTS = {
    "school": (5, "school"),
    "hospital": (5, "hospital"),
    "bus_stand": (4, "transit hub"),
    "metro_station": (4, "transit hub"),
}

SEVERITY_SHARE = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}

# Hazard flags that duplicate context data when the model spots them itself.
HAZARD_AS_CONTEXT = {
    Hazard.NEAR_SCHOOL: "school",
    Hazard.NEAR_HOSPITAL: "hospital",
    Hazard.ARTERIAL_ROAD: "arterial_road",
    Hazard.JUNCTION: "junction",
    Hazard.BUS_STOP: "bus_stand",
}

UNRESOLVED = {ClusterStatus.OPEN, ClusterStatus.IN_PROGRESS, ClusterStatus.CLOSURE_DISPUTED}
CLOCK_STOPPED = {ClusterStatus.RESOLVED_PENDING_VERIFICATION, ClusterStatus.RESOLVED_VERIFIED}


def _context(context: list[ContextHit], hazards: set[Hazard], weight: float) -> ScoreComponent:
    seen: dict[str, str] = {}
    for h in context:
        if h.type in seen:
            continue
        if h.type in ROAD_POINTS or (h.type in PROXIMITY_POINTS and h.distance_m <= CONTEXT_PROXIMITY_M):
            seen[h.type] = f"{h.name} ({h.distance_m:.0f} m)"
    for flag, ctx_type in HAZARD_AS_CONTEXT.items():
        if flag in hazards and ctx_type not in seen:
            seen[ctx_type] = "reported by citizen"

    road = next((t for t in ROAD_POINTS if t in seen), None)
    pts = float(ROAD_POINTS[road][0]) if road else 0.0
    reasons = [f"{ROAD_POINTS[road][1]}: {seen[road]}" if road else "residential street"]
    transit_counted = False
    for t, (p, what) in PROXIMITY_POINTS.items():
        if t not in seen:
            continue
        if what == "transit hub":
            if transit_counted:
                continue
            transit_counted = True
        pts += p
        reasons.append(f"{what} within {CONTEXT_PROXIMITY_M} m: {seen[t]}")
    return ScoreComponent(component="context", points=round(min(weight, pts), 1), reason="; ".join(reasons))


def compute_score(
    *,
    report_count: int,
    max_severity: int,
    hazards: Iterable[str],
    context: list[ContextHit],
    created_at: str,
    sla_due_at: str,
    status: ClusterStatus,
    reporter_count: int | None = None,
    resolved_at: str | None = None,
    now: datetime | None = None,
) -> ScoreBreakdown:
    now = now or now_utc()
    w = SCORE_WEIGHTS
    comps: list[ScoreComponent] = []

    # Unique citizens, not raw reports: re-reporting the same issue does not inflate it.
    n = max(1, reporter_count if reporter_count is not None else report_count)
    share = min(1.0, math.log2(1 + n) / math.log2(1 + SCORE_REPORTERS_FOR_MAX))
    reason = f"{n} independent citizen{'s' if n != 1 else ''}" if reporter_count is not None else f"{n} independent report{'s' if n != 1 else ''}"
    if reporter_count is not None and report_count > n:
        reason += f" ({report_count} reports)"
    comps.append(ScoreComponent(component="unique_reporters", points=round(w["unique_reporters"] * share, 1), reason=reason))

    sev = max(1, min(5, max_severity))
    level = severity_level(sev)
    comps.append(ScoreComponent(component="severity", points=round(w["severity"] * SEVERITY_SHARE[level], 1), reason=f"{level} (worst report {sev}/5)"))

    hz = {Hazard(x) for x in hazards if x in Hazard._value2member_map_}
    comps.append(_context(context, hz, w["context"]))

    start = parse_iso(created_at)
    stopped = status in CLOCK_STOPPED and bool(resolved_at)
    end = parse_iso(resolved_at) if stopped else now  # type: ignore[arg-type]
    days = max(0.0, (end - start).total_seconds() / 86400)
    reason = f"{days:.1f} day{'s' if round(days, 1) != 1 else ''} since the first report"
    if stopped:
        reason += " (clock stopped at the official closure)"
    elif status in UNRESOLVED and now > parse_iso(sla_due_at):
        overdue_h = (now - parse_iso(sla_due_at)).total_seconds() / 3600
        reason += f"; SLA breached by {overdue_h / 24:.1f} days" if overdue_h >= 24 else f"; SLA breached by {overdue_h:.0f} h"
    comps.append(ScoreComponent(component="days_elapsed", points=round(w["days_elapsed"] * min(1.0, days / SCORE_DAYS_FOR_MAX), 1), reason=reason))

    total = round(min(100.0, sum(c.points for c in comps)), 1)
    return ScoreBreakdown(total=total, components=comps)
