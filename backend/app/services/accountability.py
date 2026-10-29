"""Escalation drafting (email / X post / RTI), escalation packages and ward scorecards."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime

from ..ai import ResilientAI, templates
from ..domain import AGENCY_INFO, AGENCY_PRD_CODE, CATEGORY_LABELS, STATUS_LABELS, Agency, Category, ClusterStatus, Verdict, severity_level
from ..geo import Ward, load_wards
from ..privacy import mask_phones
from ..store import Store
from .common import hours_between, is_sla_breached, new_id, now_iso, now_utc, parse_iso, to_iso

CHANNELS = ("email", "x", "rti")
MAX_WARD_ITEMS = 25

UNRESOLVED_STATUSES = {ClusterStatus.OPEN.value, ClusterStatus.IN_PROGRESS.value, ClusterStatus.CLOSURE_DISPUTED.value}
ACTIVE_STATUSES = UNRESOLVED_STATUSES | {ClusterStatus.RESOLVED_PENDING_VERIFICATION.value}


class NothingToEscalate(Exception):
    pass


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _photo_urls(store: Store, cluster: dict, base_url: str, limit: int = 3) -> tuple[list[str], list[str]]:
    """Absolute links to the citizens' before photos and the official / citizen after photos."""
    before: list[str] = []
    if cluster.get("primary_photo_path"):
        before.append(cluster["primary_photo_path"])
    for r in store.reports_for_cluster(cluster["id"]):
        if r.get("photo_path") and r["photo_path"] not in before:
            before.append(r["photo_path"])
    after: list[str] = []
    for v in reversed(store.verifications_for_cluster(cluster["id"])):
        if v.get("photo_path") and v["photo_path"] not in after:
            after.append(v["photo_path"])
    if cluster.get("after_photo_path") and cluster["after_photo_path"] not in after:
        after.insert(0, cluster["after_photo_path"])
    return (
        [_url(base_url, f"/uploads/{p}") for p in before[:limit]],
        [_url(base_url, f"/uploads/{p}") for p in after[:limit]],
    )


def failure_reason(cluster: dict, verifications: list[dict], now: datetime) -> str:
    """One line on why this issue needs escalating (PRD: 'failure reasons')."""
    status = ClusterStatus(cluster["status"])
    days = max(0, (now - parse_iso(cluster["created_at"])).days)
    last = verifications[-1] if verifications else None
    if status == ClusterStatus.CLOSURE_DISPUTED and last:
        reason = f"Closure not verified ({Verdict(last['verdict']).value.replace('_', ' ').lower()}): {last['explanation']}"
    elif status == ClusterStatus.CLOSURE_DISPUTED:
        reason = "A citizen reported the issue again after the official closure."
    elif status == ClusterStatus.RESOLVED_PENDING_VERIFICATION:
        reason = f"Closed on paper on {str(cluster.get('resolved_at'))[:10]} but not yet confirmed by any citizen photo."
    elif status == ClusterStatus.RESOLVED_VERIFIED:
        reason = "Fixed and verified by a citizen photo."
    elif is_sla_breached(cluster, now):
        reason = f"Still unresolved {days} days after the first report; the {cluster['sla_hours']} h service target was breached."
    else:
        reason = f"Unresolved for {days} days."
    if cluster.get("repeat_failure") and cluster.get("previous_cluster_id"):
        reason += f" Repeat failure: the same spot was verified fixed as {cluster['previous_cluster_id']} and failed again."
    return reason


def escalation_context(
    store: Store, cluster: dict, requester_name: str | None, now: datetime | None = None, base_url: str = ""
) -> dict:
    now = now or now_utc()
    agency = Agency(cluster["agency"])
    info = AGENCY_INFO[agency]
    secondary = Agency(cluster["secondary_agency"]) if cluster.get("secondary_agency") else None
    created = parse_iso(cluster["created_at"])
    verifications = store.verifications_for_cluster(cluster["id"])
    if verifications:
        last = verifications[-1]
        vsum = f"{last['verdict']} ({last['kind'].replace('_', ' ')}): {last['explanation']}"
    else:
        vsum = "No closure attempted yet."
    before_urls, after_urls = _photo_urls(store, cluster, base_url)
    ward = next((w for w in load_wards() if w.name == cluster["ward"]), None)
    return {
        "cluster_id": cluster["id"],
        "title": mask_phones(cluster["title"]),
        "category_label": CATEGORY_LABELS[Category(cluster["category"])],
        "description": mask_phones(cluster.get("description") or ""),
        "location_text": f"{cluster['lat']:.5f}, {cluster['lng']:.5f}",
        "landmark": mask_phones(cluster.get("landmark") or ""),
        "ward": cluster["ward"],
        "ward_number": ward.number if ward else None,
        "zone": cluster.get("zone") or "",
        "agency": agency.value,
        "agency_code": AGENCY_PRD_CODE[agency],
        "agency_label": info["label"],
        "agency_short": info["short"],
        "agency_email_hint": info["email_hint"],
        "agency_x_handle": info["x_handle"],
        "agency_helpline": info["helpline"],
        "agency_reason": mask_phones(cluster.get("agency_reason") or ""),
        "secondary_agency": secondary.value if secondary else "",
        "secondary_agency_code": AGENCY_PRD_CODE[secondary] if secondary else "",
        "secondary_agency_label": AGENCY_INFO[secondary]["label"] if secondary else "",
        "secondary_agency_reason": cluster.get("secondary_agency_reason") or "",
        "routing_confidence": cluster.get("routing_confidence"),
        "created_at": cluster["created_at"][:10],
        "first_reported_at": cluster["created_at"],
        "resolved_at": cluster.get("resolved_at") or "",
        "days_open": max(0, (now - created).days),
        "report_count": cluster["report_count"],
        "reporter_count": cluster.get("reporter_count") or cluster["report_count"],
        "max_severity": cluster["max_severity"],
        "severity_level": severity_level(cluster["max_severity"]),
        "impact_score": cluster["impact_score"],
        "sla_hours": cluster["sla_hours"],
        "sla_due_at": cluster["sla_due_at"],
        "sla_breached": is_sla_breached(cluster, now),
        "status": cluster["status"],
        "status_label": STATUS_LABELS[ClusterStatus(cluster["status"])],
        "verification_summary": mask_phones(vsum),
        "failure_reason": mask_phones(failure_reason(cluster, verifications, now)),
        "repeat_failure": bool(cluster.get("repeat_failure")),
        "previous_cluster_id": cluster.get("previous_cluster_id"),
        "external_system": cluster.get("external_system") or "",
        "external_ref": cluster.get("external_ref") or "",
        "requester_name": requester_name or "A concerned resident",
        "public_url": _url(base_url, f"/clusters/{cluster['id']}") if base_url else "",
        "before_photo_urls": before_urls,
        "after_photo_urls": after_urls,
        "generated_on": now.date().isoformat(),
    }


def _log_escalation(store: Store, cluster_id: str, actor: str | None, note: str, payload: dict) -> None:
    store.insert_event(
        dict(id=new_id("E"), cluster_id=cluster_id, created_at=now_iso(), type="escalation_drafted", actor=actor or "citizen", note=note, payload_json=payload)
    )


def draft_escalation(
    store: Store, ai: ResilientAI, cluster: dict, channel: str, requester_name: str | None, *, use_ai: bool = True, base_url: str = ""
) -> dict:
    ctx = escalation_context(store, cluster, requester_name, base_url=base_url)
    if use_ai:
        draft, mode = ai.escalate(channel, ctx)
    else:
        draft, mode = templates.draft(channel, ctx), "template"
    _log_escalation(store, cluster["id"], requester_name, f"{channel.upper()} escalation drafted ({mode}).", {"channel": channel, "ai_mode": mode})
    return {"draft": draft.model_dump(), "ai_mode": mode, "context": ctx}


def _item(ctx: dict) -> dict:
    return {
        "id": ctx["cluster_id"],
        "title": ctx["title"],
        "status": ctx["status"],
        "status_label": ctx["status_label"],
        "agency": ctx["agency"],
        "agency_code": ctx["agency_code"],
        "agency_label": ctx["agency_label"],
        "failure_reason": ctx["failure_reason"],
        "sla_breached": ctx["sla_breached"],
        "url": ctx["public_url"],
    }


def cluster_package(store: Store, cluster: dict, requester_name: str | None, base_url: str = "") -> dict:
    """PRD escalation package for one issue: email + X post + RTI, instant, copy- and download-ready."""
    t0 = time.perf_counter()
    now = now_utc()
    ctx = escalation_context(store, cluster, requester_name, now=now, base_url=base_url)
    drafts = {ch: templates.draft(ch, ctx) for ch in CHANNELS}
    generated_at = to_iso(now)
    title = f"CivicPulse escalation package - {cluster['id']} ({cluster['ward']} ward) - {generated_at}"
    _log_escalation(store, cluster["id"], requester_name, "Escalation package (email, X post, RTI) generated.", {"channel": "package", "ai_mode": "template"})
    return {
        "scope": "cluster",
        "ward": cluster["ward"],
        "ward_number": ctx["ward_number"],
        "title": ctx["title"],
        "cluster_ids": [cluster["id"]],
        "clusters": [_item(ctx)],
        "drafts": {ch: d.model_dump() for ch, d in drafts.items()},
        "text": templates.package_text(title, drafts),
        "filename": f"civicpulse-escalation-{cluster['id']}-{now.date().isoformat()}.txt",
        "generated_at": generated_at,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000),
        "ai_mode": "template",
        "context": ctx,
    }


def find_ward(name: str) -> Ward | None:
    key = (name or "").strip().lower()
    return next((w for w in load_wards() if w.name.lower() == key or (w.number is not None and str(w.number) == key)), None)


def ward_label(ward: Ward) -> str:
    return f"Ward {ward.number} {ward.name}" if ward.number else f"{ward.name} ward"


def ward_package(store: Store, ward: Ward, requester_name: str | None, base_url: str = "") -> dict:
    """PRD escalation package for a ward: its Unverified closures plus SLA-breached open issues,
    grouped by responsible agency, as email + X post + RTI."""
    t0 = time.perf_counter()
    now = now_utc()
    cs = store.list_clusters(ward=ward.name, limit=5000)
    disputed = [c for c in cs if c["status"] == ClusterStatus.CLOSURE_DISPUTED.value]
    breached = [
        c for c in cs if c["status"] in (ClusterStatus.OPEN.value, ClusterStatus.IN_PROGRESS.value) and is_sla_breached(c, now)
    ]
    picked = sorted(disputed, key=lambda c: -c["impact_score"]) + sorted(breached, key=lambda c: -c["impact_score"])
    if not picked:
        raise NothingToEscalate(f"{ward_label(ward)} has no unverified closures or SLA-breached issues to escalate.")
    items = [escalation_context(store, c, requester_name, now=now, base_url=base_url) for c in picked[:MAX_WARD_ITEMS]]

    by_agency: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_agency[it["agency"]].append(it)
    agencies = sorted(
        (
            {
                "id": a,
                "code": AGENCY_PRD_CODE[Agency(a)],
                "label": AGENCY_INFO[Agency(a)]["label"],
                "x_handle": AGENCY_INFO[Agency(a)]["x_handle"],
                "email_hint": AGENCY_INFO[Agency(a)]["email_hint"],
                "count": len(group),
            }
            for a, group in by_agency.items()
        ),
        key=lambda a: -a["count"],
    )
    closures = [c for c in cs if c.get("resolved_at")]
    verified = [c for c in cs if c["status"] == ClusterStatus.RESOLVED_VERIFIED.value]
    rate = _pct(len(verified), len(closures))
    generated_at = to_iso(now)
    label = ward_label(ward)
    w = {
        "ward": ward.name,
        "ward_number": ward.number,
        "ward_label": label,
        "zone": ward.zone,
        "clusters": items,
        "agencies": agencies,
        "unverified": len(disputed),
        "breached": len(breached),
        "closures": len(closures),
        "verified_closure_rate": f"{rate:.0f}%" if rate is not None else "n/a",
        "repeat_failures": sum(1 for c in cs if c.get("repeat_failure")),
        "requester_name": requester_name or "A concerned resident",
        "generated_at": generated_at,
        "generated_on": now.date().isoformat(),
    }
    drafts = {"email": templates.ward_email_draft(w), "x": templates.ward_x_draft(w), "rti": templates.ward_rti_draft(w)}
    title = f"CivicPulse ward escalation package - {label} - {generated_at}"
    for it in items:
        _log_escalation(store, it["cluster_id"], requester_name, f"Included in the {label} escalation package.", {"channel": "ward_package", "ward": ward.name})
    return {
        "scope": "ward",
        "ward": ward.name,
        "ward_number": ward.number,
        "title": (
            f"{label}: {len(disputed)} unverified closure{'' if len(disputed) == 1 else 's'}, "
            f"{len(breached)} SLA-breached issue{'' if len(breached) == 1 else 's'}"
        ),
        "cluster_ids": [it["cluster_id"] for it in items],
        "clusters": [_item(it) for it in items],
        "drafts": {ch: d.model_dump() for ch, d in drafts.items()},
        "text": templates.package_text(title, drafts),
        "filename": f"civicpulse-escalation-{ward.name.lower().replace(' ', '-').replace('(', '').replace(')', '')}-{now.date().isoformat()}.txt",
        "generated_at": generated_at,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000),
        "ai_mode": "template",
    }


def record_external_ref(store: Store, cluster: dict, system: str, ref: str, actor: str, ts: str | None = None) -> dict:
    """Link the cluster to its ticket in an official channel (e.g. a Sahaaya complaint
    number obtained through assisted filing) so escalations and RTIs can cite it."""
    ts = ts or now_iso()
    updates = dict(external_system=system, external_ref=ref, external_ref_at=ts, updated_at=ts)
    store.update_cluster(cluster["id"], **updates)
    cluster.update(updates)
    store.insert_event(
        dict(
            id=new_id("E"),
            cluster_id=cluster["id"],
            created_at=ts,
            type="external_ref_recorded",
            actor=actor,
            note=f"Linked to official ticket: {system.upper()} #{ref}.",
            payload_json={"system": system, "ref": ref},
        )
    )
    return cluster


# --------------------------------------------------------------------------- #
# Ward scorecards
# --------------------------------------------------------------------------- #


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def _closure_stats(cs: list[dict]) -> tuple[list[dict], list[dict], float | None]:
    """Closures = clusters an official has claimed fixed (even if later reopened); unverified = not citizen-verified."""
    closures = [c for c in cs if c.get("resolved_at")]
    verified = [c for c in closures if c["status"] == ClusterStatus.RESOLVED_VERIFIED.value]
    return closures, verified, _pct(len(closures) - len(verified), len(closures))


# --------------------------------------------------------------------------- #
# Accountability Index (0-100) and letter grade per ward
# --------------------------------------------------------------------------- #

# Weights sum to 1. Verification carries the most weight because "closed on paper" is the
# failure mode CivicPulse exists to expose; SLA compliance is next; repeat failures and
# disputed closures are integrity signals.
INDEX_WEIGHTS = {"verification": 0.40, "sla": 0.30, "repeat": 0.15, "integrity": 0.15}
GRADE_BANDS = [(85.0, "A"), (70.0, "B"), (55.0, "C"), (40.0, "D"), (0.0, "F")]
LOW_DATA_CLOSURES = 3  # fewer closures than this -> grade is shown with a "low data" caveat
NEUTRAL_VERIFICATION = 50.0  # wards with no closures yet are neither rewarded nor punished


def grade_for(index: float) -> str:
    for floor, letter in GRADE_BANDS:
        if index >= floor:
            return letter
    return "F"


def accountability_index(
    *,
    closures: int,
    verified_closure_rate: float | None,
    sla_breach_rate: float | None,
    repeat_failure_rate: float | None,
    disputed_closure_rate: float | None,
) -> tuple[float, str, list[dict]]:
    """Return (index, grade, breakdown). Every component is a 0-100 'goodness' value times its weight."""
    verification = verified_closure_rate if closures else NEUTRAL_VERIFICATION
    components = [
        ("verification", verification if verification is not None else NEUTRAL_VERIFICATION, "verified closures" if closures else "no closures yet (neutral)"),
        ("sla", 100.0 - (sla_breach_rate or 0.0), "issues within service target"),
        ("repeat", 100.0 - (repeat_failure_rate or 0.0), "fixes that did not fail again"),
        ("integrity", 100.0 - (disputed_closure_rate or 0.0), "closures not disputed by proof"),
    ]
    breakdown = []
    total = 0.0
    for name, value, reason in components:
        value = max(0.0, min(100.0, float(value)))
        points = round(value * INDEX_WEIGHTS[name], 1)
        total += points
        breakdown.append({"component": name, "weight": INDEX_WEIGHTS[name], "value": round(value, 1), "points": points, "reason": reason})
    total = round(min(100.0, total), 1)
    return total, grade_for(total), breakdown


# Which issue should headline a ward card. Lower rank = more urgent.
_PROBLEM_RANK = {"disputed": 0, "repeat_failure": 1, "overdue": 2, "open": 3, "awaiting_proof": 4}


def top_problem(cs: list[dict], now: datetime) -> dict | None:
    """The single issue a ward should be embarrassed about, with the facts needed to phrase it in any language."""
    candidates = []
    for c in cs:
        status = c["status"]
        if status == ClusterStatus.RESOLVED_VERIFIED.value:
            continue
        breached = is_sla_breached(c, now)
        if status == ClusterStatus.CLOSURE_DISPUTED.value:
            kind = "disputed"
        elif c.get("repeat_failure"):
            kind = "repeat_failure"
        elif status in (ClusterStatus.OPEN.value, ClusterStatus.IN_PROGRESS.value):
            kind = "overdue" if breached else "open"
        else:
            kind = "awaiting_proof"
        overdue_h = (now - parse_iso(c["sla_due_at"])).total_seconds() / 3600 if breached and status != ClusterStatus.RESOLVED_PENDING_VERIFICATION.value else 0.0
        candidates.append((_PROBLEM_RANK[kind], -float(c.get("impact_score") or 0), kind, overdue_h, c))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    _, _, kind, overdue_h, c = candidates[0]
    return {
        "cluster_id": c["id"],
        "title": c["title"],
        "kind": kind,
        "status": c["status"],
        "category": c["category"],
        "agency": c["agency"],
        "report_count": c["report_count"],
        "impact_score": c.get("impact_score"),
        "sla_breached": bool(overdue_h > 0),
        "hours_overdue": round(max(0.0, overdue_h), 1),
        "verification_verdict": c.get("verification_verdict"),
        "previous_cluster_id": c.get("previous_cluster_id"),
    }


def closure_funnel(all_cs: list[dict]) -> dict:
    """Reports -> issues -> closed -> AI-checked -> citizen-verified, plus where the drop-off went."""
    reports = sum(c["report_count"] for c in all_cs)
    issues = len(all_cs)
    closures = [c for c in all_cs if c.get("resolved_at")]
    ai_checked = [c for c in closures if c.get("after_photo_path")]
    verified = [c for c in closures if c["status"] == ClusterStatus.RESOLVED_VERIFIED.value]
    disputed = [c for c in closures if c["status"] == ClusterStatus.CLOSURE_DISPUTED.value]
    awaiting = [c for c in closures if c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value]
    return {
        "reports": reports,
        "issues": issues,
        "duplicates_merged_pct": _pct(reports - issues, reports),
        "closed": len(closures),
        "ai_checked": len(ai_checked),
        "no_proof": len(closures) - len(ai_checked),
        "citizen_verified": len(verified),
        "awaiting_proof": len(awaiting),
        "disputed": len(disputed),
        "unverified_closure_rate": _pct(len(closures) - len(verified), len(closures)),
    }


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
        closures, verified, unverified_rate = _closure_stats(cs)
        disputed = [c for c in cs if c["status"] == ClusterStatus.CLOSURE_DISPUTED.value]
        pending = [c for c in cs if c["status"] == ClusterStatus.RESOLVED_PENDING_VERIFICATION.value]
        unresolved = [c for c in cs if c["status"] in UNRESOLVED_STATUSES]
        breached = [c for c in cs if is_sla_breached(c, now)]
        repeats = [c for c in cs if c.get("repeat_failure")]
        res_hours = [hours_between(c["created_at"], c["verified_at"] or c["resolved_at"]) for c in verified if c.get("resolved_at")]
        close_hours = [hours_between(c["created_at"], c["resolved_at"]) for c in closures]
        verified_rate = _pct(len(verified), len(closures))
        disputed_rate = _pct(len(disputed), len(closures))
        sla_breach_rate = _pct(len(breached), len(cs))
        repeat_rate = _pct(len(repeats), len(cs))
        index, grade, index_breakdown = accountability_index(
            closures=len(closures),
            verified_closure_rate=verified_rate,
            sla_breach_rate=sla_breach_rate,
            repeat_failure_rate=repeat_rate,
            disputed_closure_rate=disputed_rate,
        )
        rows.append(
            {
                "ward": ward.name,
                "number": ward.number,
                "zone": ward.zone,
                "lat": ward.lat,
                "lng": ward.lng,
                "total": len(cs),
                "active": sum(1 for c in cs if c["status"] in ACTIVE_STATUSES),
                "reports": sum(c["report_count"] for c in cs),
                "open": status[ClusterStatus.OPEN.value],
                "in_progress": status[ClusterStatus.IN_PROGRESS.value],
                "resolved_pending_verification": len(pending),
                "resolved_verified": len(verified),
                "closure_disputed": len(disputed),
                "closures": len(closures),
                "verified_closure_rate": verified_rate,
                "unverified_closure_rate": unverified_rate,
                "disputed_closure_rate": disputed_rate,
                "avg_hours_to_close": round(sum(close_hours) / len(close_hours), 1) if close_hours else None,
                "avg_hours_to_verified_fix": round(sum(res_hours) / len(res_hours), 1) if res_hours else None,
                "sla_breach_rate": sla_breach_rate,
                "sla_compliance_rate": round(100.0 - sla_breach_rate, 1) if sla_breach_rate is not None else None,
                "sla_breached_open": sum(1 for c in unresolved if is_sla_breached(c, now)),
                "repeat_failure_rate": repeat_rate,
                "avg_open_impact": round(sum(c["impact_score"] for c in unresolved) / len(unresolved), 1) if unresolved else 0.0,
                "top_agency": max((c["agency"] for c in cs), key=lambda a: sum(1 for c in cs if c["agency"] == a)),
                # Accountability grade (see accountability_index) and what to say about the ward.
                "accountability_index": index,
                "grade": grade,
                "low_data": len(closures) < LOW_DATA_CLOSURES,
                "index_breakdown": index_breakdown,
                "top_problem": top_problem(cs, now),
            }
        )

    # Worst first: lowest index, then most disputed closures, then most SLA-breached open issues.
    rows.sort(key=lambda r: (r["accountability_index"], -r["closure_disputed"], -r["sla_breached_open"], r["ward"]))
    for rank, r in enumerate(rows, 1):
        r["rank"] = rank
    all_cs = [c for cs in by_ward.values() for c in cs]
    closures, verified, unverified_rate = _closure_stats(all_cs)
    unresolved = [c for c in all_cs if c["status"] in UNRESOLVED_STATUSES]
    grades = defaultdict(int)
    for r in rows:
        grades[r["grade"]] += 1
    city = {
        "clusters": len(all_cs),
        "active": sum(1 for c in all_cs if c["status"] in ACTIVE_STATUSES),
        "reports": sum(c["report_count"] for c in all_cs),
        "unresolved": len(unresolved),
        "closures": len(closures),
        "verified_closure_rate": _pct(len(verified), len(closures)),
        "unverified_closure_rate": unverified_rate,
        "sla_breached_open": sum(1 for c in unresolved if is_sla_breached(c, now)),
        "repeat_failures": sum(1 for c in all_cs if c.get("repeat_failure")),
        "funnel": closure_funnel(all_cs),
        "grade_distribution": {g: grades.get(g, 0) for g in "ABCDF"},
        "median_index": (sorted(r["accountability_index"] for r in rows)[len(rows) // 2] if rows else None),
        "generated_at": now_s,
    }
    return {"city": city, "wards": rows}
