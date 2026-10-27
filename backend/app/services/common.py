"""Small shared helpers: ids, timestamps, SLA arithmetic."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from ..domain import SLA_HOURS, Category, ClusterStatus

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion


def new_id(prefix: str) -> str:
    return f"{prefix}-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_iso() -> str:
    return to_iso(now_utc())


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def sla_due(created_at: str, category: Category) -> str:
    return to_iso(parse_iso(created_at) + timedelta(hours=SLA_HOURS[category]))


def hours_between(a: str, b: str) -> float:
    return (parse_iso(b) - parse_iso(a)).total_seconds() / 3600.0


def is_sla_breached(cluster: dict, now: datetime | None = None) -> bool:
    """Breached if still unresolved past due, or resolved after the due time."""
    now = now or now_utc()
    due = parse_iso(cluster["sla_due_at"])
    status = ClusterStatus(cluster["status"])
    if status in (ClusterStatus.RESOLVED_VERIFIED, ClusterStatus.RESOLVED_PENDING_VERIFICATION):
        resolved_at = cluster.get("resolved_at")
        return bool(resolved_at) and parse_iso(resolved_at) > due
    return now > due
