"""Reporter credibility (PRD anti-spam NFR): a 0-1 track-record score.

A Bayesian average that starts every reporter at 0.6 (worth five reports of
evidence) and only moves with evidence:

    (3 + confirmed) / (5 + confirmed + flagged + 2 x rejected)

- confirmed: reports another citizen independently backed, or whose fix was verified
- flagged:   reports whose photo looked stock/screenshot or was taken far from the pin
- rejected:  submissions bounced as non-civic or unreadable

Unconfirmed reports are neutral. The score is shown next to reports; it never
hides a report or changes the impact score.
"""

from __future__ import annotations

from ..store import Store

PRIOR_GOOD = 3
PRIOR_TOTAL = 5


def credibility_from_stats(stats: dict[str, int]) -> float:
    good = stats.get("confirmed", 0)
    bad = stats.get("flagged", 0) + 2 * stats.get("rejected", 0)
    return round((PRIOR_GOOD + good) / (PRIOR_TOTAL + good + bad), 2)


def reporter_credibility(store: Store, reporter_id: str | None, cache: dict[str, float] | None = None) -> float | None:
    """Credibility for a reporter id (None for anonymous reports). ``cache`` memoises per request."""
    if not reporter_id:
        return None
    if cache is not None and reporter_id in cache:
        return cache[reporter_id]
    score = credibility_from_stats(store.reporter_stats(reporter_id))
    if cache is not None:
        cache[reporter_id] = score
    return score
