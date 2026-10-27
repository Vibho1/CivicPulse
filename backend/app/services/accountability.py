"""Escalation drafting (email / X post / RTI) and ward scorecards."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from ..ai import ResilientAI
from ..domain import AGENCY_INFO, CATEGORY_LABELS, STATUS_LABELS, Agency, Category, ClusterStatus
from ..geo import load_wards
from ..store import Store
from .common import hours_between, is_sla_breached, new_id, now_iso, now_utc, parse_iso


def escalation_context(store: Store, cluster: dict, requester_name: str | None, now: datetime | None = None) -> dict:
    now = now or now_utc()
    agency = Agency(cluster["agency"])
    info = AGENCY_INFO[agency]
    created = parse_iso(cluster["created_at"])
    verifications = store.verifications_for_cluster(cluster["id"])
    if verifications:
        last = verifications[-1]
        vsum = f"{last['verdict']} ({last['kind'].replace('_', ' ')}): {last['explanation']}"
    else:
        vsum = "No closure attempted yet."
    return {
        "cluster_id": cluster["id"],
        "title": cluster["title"],
        "category_label": CATEGORY_LABELS[Category(cluster["category"])],
        "description": cluster.get("description") or "",
        "location_text": f"{cluster['lat']:.5f}, {cluster['lng']:.5f}",
        "landmark": cluster.get("landmark") or "",
        "ward": cluster["ward"],
        "zone": cluster.get("zone") or "",
        "agency": agency.value,
        "agency_label": info["label"],
        "agency_email_hint": info["email_hint"],
        "agency_x_handle": info["x_handle"],
        "agency_helpline": info["helpline"],
        "agency_reason": cluster.get("agency_reason") or "",
        "created_at": cluster["created_at"][:10],
        "days_open": max(0, (now - created).days),
        "report_count": cluster["report_count"],
        "max_severity": cluster["max_severity"],
        "impact_score": cluster["impact_score"],
        "sla_hours": cluster["sla_hours"],
        "sla_breached": is_sla_breached(cluster, now),
        "status": cluster["status"],
        "status_label": STATUS_LABELS[ClusterStatus(cluster["status"])],
        "verification_summary": vsum,
        "repeat_failure": bool(cluster.get("repeat_failure")),
        "previous_cluster_id": cluster.get("previous_cluster_id"),
        "requester_name": requester_name or "A concerned resident",
    }


def draft_escalation(store: Store, ai: ResilientAI, cluster: dict, channel: str, requester_name: str | None) -> dict:
    ctx = escalation_context(store, cluster, requester_name)
    draft, mode = ai.escalate(channel, ctx)
    store.insert_event(
        dict(
            id=new_id("E"),
            cluster_id=cluster["id"],
            created_at=now_iso(),
            type="escalation_drafted",
            actor=requester_name or "citizen",
            note=f"{channel.upper()} escalation drafted ({mode}).",
            payload_json={"channel": channel, "ai_mode": mode},
        )
    )
    return {"draft": draft.model_dump(), "ai_mode": mode, "context": ctx}


# --------------------------------------------------------------------------- #
# Ward scorecards
# --------------------------------------------------------------------------- #


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def ward_scorecard(store: Store, now: datetime | None = None) -> dict:
    now = now or now_utc()
    now_s = now.isoformat()
    by_ward: dict[str, list[dict]] = defaultdict(list)
    for c in store.all_clusters():
        by_ward[c["ward"]].append(c)

    rows = []
    for ward in load_wards():
        cs = by_ward.get(ward.name, [])
        if not cs:
            continue
        status = defaultdict(int)
        for c in cs:
            status[c["status"]] += 1
        closures = [c for c in cs if c.get("resolved_at")]
        verified = [c for c in cs if c["status"] == ClusterStatus.RESOLVED_VERIFIED.value]
        disputed = [c for c in cs if c["status"] == ClusterStatus.CLOSURE_DISPUTED.value]
        pending = [c for c in cs if c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value]
        unresolved = [c for c in cs if c["status"] in (ClusterStatus.OPEN.value, ClusterStatus.IN_PROGRESS.value, ClusterStatus.CLOSURE_DISPUTED.value)]
        breached = [c for c in cs if is_sla_breached(c, now)]
        repeats = [c for c in cs if c.get("repeat_failure")]
        res_hours = [hours_between(c["created_at"], c["verified_at"] or c["resolved_at"]) for c in verified if c.get("resolved_at")]
        close_hours = [hours_between(c["created_at"], c["resolved_at"]) for c in closures]
        rows.append(
            {
                "ward": ward.name,
                "zone": ward.zone,
                "lat": ward.lat,
                "lng": ward.lng,
                "total": len(cs),
                "reports": sum(c["report_count"] for c in cs),
                "open": status[ClusterStatus.OPEN.value],
                "in_progress": status[ClusterStatus.IN_PROGRESS.value],
                "resolved_pending_verification": len(pending),
                "resolved_verified": len(verified),
                "closure_disputed": len(disputed),
                "closures": len(closures),
                "verified_closure_rate": _pct(len(verified), len(closures)),
                "unverified_closure_rate": _pct(len(pending) + len(disputed), len(closures)),
                "disputed_closure_rate": _pct(len(disputed), len(closures)),
                "avg_hours_to_close": round(sum(close_hours) / len(close_hours), 1) if close_hours else None,
                "avg_hours_to_verified_fix": round(sum(res_hours) / len(res_hours), 1) if res_hours else None,
                "sla_breach_rate": _pct(len(breached), len(cs)),
                "sla_breached_open": sum(1 for c in unresolved if is_sla_breached(c, now)),
                "repeat_failure_rate": _pct(len(repeats), len(cs)),
                "avg_open_impact": round(sum(c["impact_score"] for c in unresolved) / len(unresolved), 1) if unresolved else 0.0,
                "top_agency": max((c["agency"] for c in cs), key=lambda a: sum(1 for c in cs if c["agency"] == a)),
            }
        )

    rows.sort(key=lambda r: ((r["verified_closure_rate"] if r["verified_closure_rate"] is not None else -1), -r["sla_breach_rate"] if r["sla_breach_rate"] else 0))
    all_cs = [c for cs in by_ward.values() for c in cs]
    closures = [c for c in all_cs if c.get("resolved_at")]
    verified = [c for c in all_cs if c["status"] == ClusterStatus.RESOLVED_VERIFIED.value]
    unresolved = [c for c in all_cs if c["status"] in (ClusterStatus.OPEN.value, ClusterStatus.IN_PROGRESS.value, ClusterStatus.CLOSURE_DISPUTED.value)]
    city = {
        "clusters": len(all_cs),
        "reports": sum(c["report_count"] for c in all_cs),
        "unresolved": len(unresolved),
        "closures": len(closures),
        "verified_closure_rate": _pct(len(verified), len(closures)),
        "unverified_closure_rate": _pct(len(closures) - len(verified), len(closures)),
        "sla_breached_open": sum(1 for c in unresolved if is_sla_breached(c, now)),
        "repeat_failures": sum(1 for c in all_cs if c.get("repeat_failure")),
        "generated_at": now_s,
    }
    return {"city": city, "wards": rows}
