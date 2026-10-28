"""Privacy helpers for anything served publicly.

PRD NFR: phone numbers must be masked in all public interfaces. Citizens often
say or type a number ("call me on 98xxxxxxxx"); it is kept in storage for the
record but never returned by the API or put into escalation drafts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Indian mobile numbers (optional +91 / 0 prefix, optional separators) and
# Bengaluru landlines (080 + 8 digits).
_PHONE_RE = re.compile(
    r"(?<![\w+])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"
    r"|(?<![\w+])(?:\+?91[\s-]?)?0?80[\s-]?\d{4}[\s-]?\d{4}(?!\d)"
)


def _mask(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group())[-10:]
    return f"{digits[:2]}{'*' * (len(digits) - 4)}{digits[-2:]}"


def mask_phones(text: str | None) -> str | None:
    """'call 9876543210' -> 'call 98******10'. Leaves None and non-phone digits alone."""
    if not text:
        return text
    return _PHONE_RE.sub(_mask, text)


def mask_deep(value: Any) -> Any:
    """Mask phone numbers in every string inside nested dicts / lists."""
    if isinstance(value, str):
        return mask_phones(value)
    if isinstance(value, dict):
        return {k: mask_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_deep(v) for v in value]
    return value


def mask_fields(row: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Mask phone numbers in the given top-level fields of a dict (in place; returns it)."""
    for f in fields:
        if f in row:
            row[f] = mask_deep(row[f])
    return row
