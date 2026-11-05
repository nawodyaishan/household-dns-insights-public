"""Research coverage and first-time worklist progression (spec R15/R16).

Coverage classifies every eligible public name into one mutually exclusive
workflow state so the owner can see what has been reviewed, cached, researched
or is still pending. The first-time worklist pages through the not-yet-researched
names after cached and already-processed exclusions, without repeating unchanged
names. Nothing here makes an external call: it is a pure local read model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .classification import exclusion_reason, resolve_domain

MAX_WORKLIST = 20

#: Mutually exclusive primary workflow states. Review/cache overlap is carried as
#: a descriptive detail, never as a second primary state.
COVERAGE_STATES = (
    "reviewed",
    "cached",
    "researched_resolved",
    "researched_unresolved",
    "excluded",
    "not_yet_researched",
)


class ResearchError(ValueError):
    """A requested research page or coverage input is unsupported."""


def _normalize(name: str) -> str:
    return name.strip().lower().rstrip(".")


def research_coverage(
    domain_rows: Mapping[str, int],
    *,
    rules: Sequence[Mapping[str, object]],
    prior_items: Mapping[str, str],
    exclude: Sequence[str] = (),
    as_of: str,
) -> dict[str, object]:
    """Classify every eligible name into one mutually exclusive workflow state.

    ``prior_items`` maps a normalized public name to its terminal research outcome
    (``resolved`` or ``unresolved``). ``exclude`` holds owner-excluded names. Each
    eligible name receives exactly one state; review/cache overlap is a detail.
    """
    excluded = {_normalize(name) for name in exclude}
    states: dict[str, str] = {}
    details: dict[str, str] = {}
    rows_by_name: dict[str, int] = {}
    for domain, count in sorted(domain_rows.items()):
        name = _normalize(str(domain))
        if not name:
            continue
        rows_by_name[name] = int(count)
        reason = exclusion_reason(name)
        if reason is not None:
            states[name] = "excluded"
            details[name] = f"unsafe to disclose: {reason}"
            continue
        if name in excluded:
            states[name] = "excluded"
            details[name] = "excluded locally by the owner"
            continue
        resolution = resolve_domain(name, rules, as_of=as_of)
        if resolution.state == "resolved" and resolution.rule is not None:
            verification = str(resolution.rule.get("verification_state", "reviewed"))
            if verification == "reviewed":
                states[name] = "reviewed"
            else:
                states[name] = "cached"
            details[name] = f"resolved by {resolution.matched} rule ({verification})"
            continue
        prior = prior_items.get(name)
        if prior == "resolved":
            states[name] = "researched_resolved"
            details[name] = "prior research resolved the service or provider"
        elif prior == "unresolved":
            states[name] = "researched_unresolved"
            details[name] = "prior research left the name unresolved"
        else:
            states[name] = "not_yet_researched"
            details[name] = "eligible but not yet researched"
    counts = {state: 0 for state in COVERAGE_STATES}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    return {
        "states": states,
        "details": details,
        "rows": rows_by_name,
        "counts": counts,
        "eligible": len(states),
        "denominator": len(domain_rows),
        "note": "Coverage describes the research workflow, not gaming detection.",
    }


def first_time_page(
    coverage: Mapping[str, object],
    *,
    offset: int = 0,
    limit: int = MAX_WORKLIST,
) -> dict[str, object]:
    """The next page of not-yet-researched names, ranked by local DNS rows.

    Cached, reviewed and already-researched names are excluded before the volume
    cap, so repeated previews advance through genuinely new names without
    repeating unchanged cached or refused work.
    """
    if offset < 0:
        raise ResearchError("Page offset cannot be negative")
    if not 1 <= limit <= MAX_WORKLIST:
        raise ResearchError("Worklist page must be between 1 and 20 names")
    states = coverage["states"]
    rows = coverage["rows"]
    pending = [
        (name, int(rows.get(name, 0)))
        for name, state in states.items()
        if state == "not_yet_researched"
    ]
    pending.sort(key=lambda item: (-item[1], item[0]))
    page = pending[offset : offset + limit]
    return {
        "candidates": [{"name": name, "dns_rows": rows_count} for name, rows_count in page],
        "offset": offset,
        "limit": limit,
        "total_pending": len(pending),
        "remaining": max(0, len(pending) - (offset + len(page))),
        "complete": offset + len(page) >= len(pending),
    }


def coverage_summary(coverage: Mapping[str, object]) -> dict[str, object]:
    """Sanitized coverage totals with explicit denominators and overlap notes."""
    counts = dict(coverage["counts"])
    pending = counts.get("not_yet_researched", 0)
    return {
        "eligible": int(coverage["eligible"]),
        "denominator": int(coverage["denominator"]),
        "counts": counts,
        "pending": pending,
        "complete": pending == 0,
        "note": str(coverage.get("note", "")),
    }


__all__ = [
    "COVERAGE_STATES",
    "MAX_WORKLIST",
    "ResearchError",
    "coverage_summary",
    "first_time_page",
    "research_coverage",
]
