"""Deterministic escalation templates (used offline and as a Gemini fallback)."""

from __future__ import annotations

from ..schemas import EscalationDraft


def _fmt(ctx: dict) -> dict:
    """Fill in display-friendly defaults for the templates."""
    c = dict(ctx)
    c.setdefault("requester_name", "A concerned resident")
    c.setdefault("verification_summary", "No verified closure on record.")
    c.setdefault("landmark", "")
    c.setdefault("agency_x_handle", "")
    c.setdefault("agency_helpline", "")
    c["landmark_line"] = f" (near {c['landmark']})" if c.get("landmark") else ""
    return c


def email_draft(ctx: dict) -> EscalationDraft:
    c = _fmt(ctx)
    subject = (
        f"[{c['cluster_id']}] {c['title']} - {c['days_open']} days open, "
        f"SLA {'breached' if c['sla_breached'] else 'at risk'}"
    )
    body = (
        f"To: {c['agency_label']} ({c['agency_email_hint']}), {c['ward']} ward\n"
        f"Cc: Ward Committee, {c['ward']} | Zonal Commissioner\n\n"
        f"Subject: {subject}\n\n"
        f"Dear Sir/Madam,\n\n"
        f"This is to formally escalate a {c['category_label'].lower()} at {c['location_text']}{c['landmark_line']} "
        f"in {c['ward']} ward (CivicPulse ticket {c['cluster_id']}).\n\n"
        f"Facts on record:\n"
        f"  - First reported: {c['created_at']} ({c['days_open']} days ago)\n"
        f"  - Independent citizen reports: {c['report_count']}\n"
        f"  - Severity: {c['max_severity']}/5; civic impact score: {c['impact_score']}/100\n"
        f"  - Service target: {c['sla_hours']} hours; status: {'BREACHED' if c['sla_breached'] else 'approaching breach'}\n"
        f"  - Current status: {c['status_label']}\n"
        f"  - Closure verification: {c['verification_summary']}\n\n"
        f"{c['description']}\n\n"
        f"We request that (1) the defect be rectified within 48 hours, (2) a geo-tagged after-repair photo be "
        f"shared on closure, and (3) if the stretch is within a contractor's defect-liability period, the repair be "
        f"executed under that warranty rather than as fresh expenditure.\n\n"
        f"Photo evidence and the report timeline are attached / available at the CivicPulse link.\n\n"
        f"Regards,\n{c['requester_name']}\nResident, {c['ward']}\n"
        f"Helpline reference: {c['agency_helpline']}"
    )
    return EscalationDraft(channel="email", subject=subject, to=c["agency_email_hint"], body=body)


def x_draft(ctx: dict) -> EscalationDraft:
    c = _fmt(ctx)
    handle = c.get("agency_x_handle") or ""
    body = (
        f"{handle} {c['category_label']} at {c['location_text']}{c['landmark_line']}, {c['ward']} ward: "
        f"{c['report_count']} residents reported it {c['days_open']} days ago, still '{c['status_label']}'. "
        f"SLA {'breached' if c['sla_breached'] else 'expiring'}. Fix + share after-photo please. "
        f"#{c['cluster_id']} #CivicPulse #Bengaluru"
    )
    if len(body) > 280:
        body = body[:277] + "..."
    return EscalationDraft(channel="x", body=body)


def rti_draft(ctx: dict) -> EscalationDraft:
    c = _fmt(ctx)
    body = (
        f"To,\nThe Public Information Officer,\n{c['agency_label']}\nBengaluru\n\n"
        f"Subject: Application under Section 6(1) of the Right to Information Act, 2005\n\n"
        f"Sir/Madam,\n\n"
        f"I request the following information regarding the {c['category_label'].lower()} at "
        f"{c['location_text']}{c['landmark_line']}, {c['ward']} ward "
        f"(citizen ticket {c['cluster_id']}, first reported {c['created_at']}, {c['report_count']} reports):\n\n"
        f"1. Date on which the complaint was first registered in your grievance system and its reference number.\n"
        f"2. Name of the officer responsible for the stretch and the prescribed timeline for rectification.\n"
        f"3. Copies of work orders, bills and completion certificates for repairs at this location in the last 3 years.\n"
        f"4. Name of the contractor, contract value and the defect-liability period applicable to the stretch.\n"
        f"5. Inspection reports or geo-tagged photographs relied upon to close any complaint at this location.\n"
        f"6. Action taken, if any, against the contractor for premature failure of the work.\n\n"
        f"I am a citizen of India. The application fee of Rs. 10 is enclosed / paid online. "
        f"Please provide the information within 30 days as mandated.\n\n"
        f"Applicant: {c['requester_name']}\nAddress: ____________________\nDate: ____________\n"
    )
    return EscalationDraft(channel="rti", subject="RTI application - " + c["title"], to="Public Information Officer, " + c["agency_label"], body=body)


def draft(channel: str, ctx: dict) -> EscalationDraft:
    return {"email": email_draft, "x": x_draft, "rti": rti_draft}[channel](ctx)
