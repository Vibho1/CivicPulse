"""Deterministic escalation templates (instant; used for the PRD escalation package,
offline, and as a Gemini fallback).

Every draft carries what the PRD asks for: cluster ID(s), ward, responsible agency
(with its PRD code), the failure reason, coordinates, ISO timestamps and links to
the before/after photos and the public issue page. X posts are always <= 280
characters and keep the ticket ID.
"""

from __future__ import annotations

from ..schemas import EscalationDraft

X_MAX_CHARS = 280


def _fmt(ctx: dict) -> dict:
    """Fill in display-friendly defaults for the templates."""
    c = dict(ctx)
    c.setdefault("requester_name", "A concerned resident")
    c.setdefault("verification_summary", "No verified closure on record.")
    c.setdefault("failure_reason", "")
    c.setdefault("landmark", "")
    c.setdefault("agency_x_handle", "")
    c.setdefault("agency_helpline", "")
    c.setdefault("agency_code", c.get("agency", ""))
    c.setdefault("reporter_count", c.get("report_count", 1))
    c.setdefault("first_reported_at", c.get("created_at", ""))
    c.setdefault("resolved_at", "")
    c.setdefault("public_url", "")
    c.setdefault("before_photo_urls", [])
    c.setdefault("after_photo_urls", [])
    c.setdefault("generated_on", "____________")
    c.setdefault("sla_due_at", "")
    c["landmark_line"] = f" (near {c['landmark']})" if c.get("landmark") else ""
    c["official_ref"] = f"{str(c.get('external_system') or 'official').upper()} #{c['external_ref']}" if c.get("external_ref") else ""
    c["agency_tag"] = f"{c['agency_label']} [{c['agency_code']}]" if c.get("agency_code") else c.get("agency_label", "")
    return c


def _evidence_lines(c: dict, indent: str = "  - ") -> str:
    before = ", ".join(c["before_photo_urls"]) or "none on record"
    after = ", ".join(c["after_photo_urls"]) or "none submitted"
    lines = [f"{indent}Before photos: {before}", f"{indent}After photos: {after}"]
    if c.get("public_url"):
        lines.insert(0, f"{indent}Issue page and full timeline: {c['public_url']}")
    return "\n".join(lines)


def _fit(text: str, limit: int) -> str:
    """Shorten to ``limit`` characters at a word boundary, with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return cut + "\u2026"


def _first_sentence(text: str, limit: int = 110) -> str:
    s = (text or "").strip()
    for stop in (". ", "; "):
        if stop in s:
            s = s.split(stop, 1)[0]
    return _fit(s.rstrip("."), limit)


# --------------------------------------------------------------- one cluster --


def email_draft(ctx: dict) -> EscalationDraft:
    c = _fmt(ctx)
    subject = (
        f"[{c['cluster_id']}] {c['title']} - {c['ward']} ward, {c['status_label']}"
        f"{', SLA breached' if c['sla_breached'] else ''}"
    )
    cc = f"{c['secondary_agency_label']} [{c.get('secondary_agency_code') or ''}] | " if c.get("secondary_agency_label") else ""
    closure = f"claimed on {c['resolved_at']}" if c.get("resolved_at") else "no closure claimed yet"
    body = (
        f"To: {c['agency_tag']} ({c['agency_email_hint']}), {c['ward']} ward\n"
        f"Cc: {cc}Ward Committee, {c['ward']} | Zonal Commissioner\n\n"
        f"Subject: {subject}\n\n"
        f"Dear Sir/Madam,\n\n"
        f"This is to formally escalate a {c['category_label'].lower()} at {c['location_text']}{c['landmark_line']} "
        f"in {c['ward']} ward (CivicPulse ticket {c['cluster_id']}"
        f"{', official complaint ' + c['official_ref'] if c['official_ref'] else ''}).\n\n"
        f"Facts on record:\n"
        f"  - First reported: {c['first_reported_at']} ({c['days_open']} days ago)\n"
        f"  - Coordinates: {c['location_text']}\n"
        f"  - Responsible agency: {c['agency_tag']}\n"
        f"  - Independent citizens reporting: {c['reporter_count']} ({c['report_count']} reports)\n"
        f"  - Severity: {c.get('severity_level', '')} ({c['max_severity']}/5); civic impact score: {c['impact_score']}/100\n"
        f"  - Service target: {c['sla_hours']} hours{' (due ' + c['sla_due_at'] + ')' if c['sla_due_at'] else ''}; "
        f"status: {'BREACHED' if c['sla_breached'] else 'within target'}\n"
        f"  - Current status: {c['status_label']}; official closure {closure}\n"
        f"  - Failure reason: {c['failure_reason'] or 'not yet fixed'}\n"
        f"  - Closure verification: {c['verification_summary']}\n"
        + (f"  - Shared responsibility: {c['secondary_agency_reason']}\n" if c.get("secondary_agency_reason") else "")
        + f"\n{c['description']}\n\n"
        f"We request that (1) the defect be rectified within 48 hours, (2) a geo-tagged after-repair photo be "
        f"shared on closure, and (3) if the stretch is within a contractor's defect-liability period, the repair be "
        f"executed under that warranty rather than as fresh expenditure.\n\n"
        f"Evidence:\n{_evidence_lines(c)}\n\n"
        f"Regards,\n{c['requester_name']}\nResident, {c['ward']}\n"
        f"Helpline reference: {c['agency_helpline']}"
    )
    return EscalationDraft(channel="email", subject=subject, to=c["agency_email_hint"], body=body)


def x_draft(ctx: dict) -> EscalationDraft:
    c = _fmt(ctx)
    handle = c.get("agency_x_handle") or ""
    place = c["landmark"] or c["location_text"]
    reason = _first_sentence(c["failure_reason"] or f"still '{c['status_label']}'", 90)
    core = (
        f"{handle} [{c['agency_code']}] {c['category_label']} at {place}, {c['ward']} ward: {reason}. "
        f"{c['reporter_count']} residents reported it; first reported {str(c['first_reported_at'])[:10]}. "
        f"Fix + share a geo-tagged after-photo."
    ).strip()
    link = f" {c['public_url']}" if c.get("public_url") else ""
    tail = f" #{c['cluster_id']} #CivicPulse"
    room = X_MAX_CHARS - len(tail) - len(link)
    if room < 60:  # a very long link: drop it rather than the facts
        link, room = "", X_MAX_CHARS - len(tail)
    body = _fit(core, room) + link + tail
    return EscalationDraft(channel="x", body=body)


def rti_draft(ctx: dict) -> EscalationDraft:
    c = _fmt(ctx)
    official = f", official complaint {c['official_ref']}" if c["official_ref"] else ""
    closure = f" An official closure was claimed on {c['resolved_at']}." if c.get("resolved_at") else ""
    body = (
        f"To,\nThe Public Information Officer,\n{c['agency_label']}\nBengaluru\n\n"
        f"Subject: Application under Section 6(1) of the Right to Information Act, 2005\n\n"
        f"Sir/Madam,\n\n"
        f"I request the following information regarding the {c['category_label'].lower()} at "
        f"{c['location_text']}{c['landmark_line']}, {c['ward']} ward "
        f"(citizen ticket {c['cluster_id']}{official}; first reported {c['first_reported_at']}; "
        f"{c['report_count']} reports from {c['reporter_count']} citizens; responsible agency {c['agency_tag']}).\n"
        f"Recorded status: {c['status_label']}.{closure} Failure reason recorded: {c['failure_reason'] or 'not yet fixed'}\n\n"
        f"1. Date on which the complaint was first registered in your grievance system and its reference number.\n"
        f"2. Name of the officer responsible for the stretch and the prescribed timeline for rectification.\n"
        f"3. Copies of work orders, bills and completion certificates for repairs at this location in the last 3 years.\n"
        f"4. Name of the contractor, contract value and the defect-liability period applicable to the stretch.\n"
        f"5. Inspection reports or geo-tagged photographs relied upon to close any complaint at this location.\n"
        f"6. Action taken, if any, against the contractor for premature failure of the work.\n\n"
        f"Photographs and records relied upon by the applicant:\n{_evidence_lines(c)}\n\n"
        f"I am a citizen of India. The application fee of Rs. 10 is enclosed / paid online. "
        f"Please provide the information within 30 days as mandated.\n\n"
        f"Applicant: {c['requester_name']}\nAddress: ____________________\nDate: {c['generated_on']}\n"
    )
    return EscalationDraft(channel="rti", subject="RTI application - " + c["title"], to="Public Information Officer, " + c["agency_label"], body=body)


def draft(channel: str, ctx: dict) -> EscalationDraft:
    return {"email": email_draft, "x": x_draft, "rti": rti_draft}[channel](ctx)


# ------------------------------------------------------------------- a ward --


def _plural(n: int, one: str, many: str | None = None) -> str:
    """'1 unverified closure' / '2 unverified closures'."""
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _ward_items(w: dict) -> str:
    lines = []
    for i, it in enumerate(w["clusters"], 1):
        lines.append(
            f"{i}. {it['cluster_id']} - {it['title']} ({it['category_label']})\n"
            f"   Agency: {it['agency_label']} [{it['agency_code']}] | Status: {it['status_label']}"
            f"{' | SLA breached' if it.get('sla_breached') else ''}\n"
            f"   Failure reason: {it['failure_reason']}\n"
            f"   First reported {it['first_reported_at']} at {it['location_text']}"
            f"{' - closure claimed ' + it['resolved_at'] if it.get('resolved_at') else ''}\n"
            f"   Evidence: {it.get('public_url') or 'n/a'}"
            f"{' | before: ' + ', '.join(it['before_photo_urls']) if it.get('before_photo_urls') else ''}"
            f"{' | after: ' + ', '.join(it['after_photo_urls']) if it.get('after_photo_urls') else ''}"
        )
    return "\n".join(lines)


def ward_email_draft(w: dict) -> EscalationDraft:
    agencies = "; ".join(f"{a['label']} [{a['code']}] - {a['email_hint']} ({a['count']})" for a in w["agencies"])
    subject = (
        f"{w['ward_label']}: {_plural(w['unverified'], 'unverified closure')}, "
        f"{_plural(w['breached'], 'SLA-breached issue')} - action requested"
    )
    body = (
        f"To: Zonal Commissioner{', ' + w['zone'] + ' zone' if w.get('zone') else ''}; {agencies}\n"
        f"Cc: Ward Committee, {w['ward']}\n\n"
        f"Subject: {subject}\n\n"
        f"Dear Sir/Madam,\n\n"
        f"Citizens of {w['ward_label']} have recorded the following civic issues on CivicPulse that were closed "
        f"without verified proof of repair, or are past their service target. Each was checked against the citizens' "
        f"before photos and GPS.\n\n"
        f"{_ward_items(w)}\n\n"
        f"Ward record: {w['closures']} official closures, verified closure rate {w['verified_closure_rate']}, "
        f"repeat failures {w['repeat_failures']}.\n\n"
        f"We request (1) re-inspection and repair of each item within 7 days, (2) geo-tagged after-photos on closure, "
        f"and (3) defect-liability enforcement against contractors where the work failed early.\n\n"
        f"Regards,\n{w['requester_name']}\nResident, {w['ward']}\nGenerated {w['generated_at']}"
    )
    return EscalationDraft(channel="email", subject=subject, to="Zonal Commissioner; " + ", ".join(a["label"] for a in w["agencies"]), body=body)


def ward_x_draft(w: dict) -> EscalationDraft:
    handles = " ".join(dict.fromkeys(a["x_handle"] for a in w["agencies"] if a.get("x_handle")))
    codes = ", ".join(a["code"] for a in w["agencies"])
    tail = " #CivicPulse #Bengaluru"
    head = _fit(
        f"{handles} {w['ward_label']}: {_plural(w['unverified'], 'repair')} failed citizen verification, "
        f"{_plural(w['breached'], 'issue')} past SLA ({codes}).".strip(),
        160,
    )
    ids = [it["cluster_id"] for it in w["clusters"]]
    shown: list[str] = []
    for i, cid in enumerate(ids):
        left = len(ids) - (i + 1)
        trial = f"{head} {' '.join([*shown, cid])}{f' +{left} more' if left else ''}{tail}"
        if len(trial) > X_MAX_CHARS:
            break
        shown.append(cid)
    left = len(ids) - len(shown)
    more = f" +{left} more" if left else ""
    body = f"{head} {' '.join(shown)}{more}{tail}" if shown else f"{head}{more}{tail}"
    return EscalationDraft(channel="x", body=body)


def ward_rti_draft(w: dict) -> EscalationDraft:
    top = w["agencies"][0]
    body = (
        f"To,\nThe Public Information Officer,\n{top['label']}\nBengaluru\n\n"
        f"Subject: Application under Section 6(1) of the Right to Information Act, 2005\n\n"
        f"Sir/Madam,\n\n"
        f"I request the following information about the civic complaints listed below in {w['ward_label']}, "
        f"which citizens recorded as closed without verified repair or past their service target "
        f"(responsible agencies as recorded; please transfer under Section 6(3) where another authority holds the records):\n\n"
        f"{_ward_items(w)}\n\n"
        f"For each item:\n"
        f"1. The complaint registration date and reference number in your grievance system.\n"
        f"2. The officer responsible and the prescribed timeline for rectification.\n"
        f"3. Work orders, bills, measurement-book entries and completion certificates for the repair.\n"
        f"4. The contractor's name, contract value and the defect-liability period.\n"
        f"5. The inspection report or geo-tagged photographs relied upon to close the complaint.\n"
        f"6. Action taken against contractors for premature failure of the work.\n\n"
        f"I am a citizen of India. The application fee of Rs. 10 is enclosed / paid online. "
        f"Please provide the information within 30 days as mandated.\n\n"
        f"Applicant: {w['requester_name']}\nAddress: ____________________\nDate: {w['generated_on']}\n"
    )
    return EscalationDraft(channel="rti", subject=f"RTI application - civic complaints in {w['ward_label']}", to="Public Information Officer, " + top["label"], body=body)


def package_text(title: str, drafts: dict[str, EscalationDraft]) -> str:
    """All three drafts as one plain-text file (the downloadable escalation package)."""
    names = {"email": "EMAIL", "x": "X POST", "rti": "RTI APPLICATION (Section 6(1), RTI Act 2005)"}
    parts = [title, "=" * len(title)]
    for channel in ("email", "x", "rti"):
        d = drafts[channel]
        parts += ["", f"--- {names[channel]} ---"]
        if d.to:
            parts.append(f"To: {d.to}")
        if d.subject:
            parts.append(f"Subject: {d.subject}")
        parts += ["", d.body]
    return "\n".join(parts) + "\n"
