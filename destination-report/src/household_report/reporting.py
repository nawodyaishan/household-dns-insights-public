"""Reporting: frozen periods, preserved observations, coverage and presentation.

This module owns DNS-specific interpretation and report assembly. It performs no
network calls, imports no web framework and never invents device attribution:
inventory may hand in explicit verified results, and absent inventory simply means
"device unknown".

The pure extraction/interpretation functions were promoted from the proven
``dns-pilot/destination_report.py`` proof of concept so there is one implementation.
The old CLI remains a thin compatibility entry point.
"""

from __future__ import annotations

import hashlib
import html
import json
import statistics
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .classification import Resolution, resolve_domain
from .contracts import Period
from .storage import Store

STATUS = dict(
    enumerate(
        [
            "UNKNOWN",
            "GRAVITY",
            "FORWARDED",
            "CACHE",
            "REGEX",
            "DENYLIST",
            "EXTERNAL_BLOCKED_IP",
            "EXTERNAL_BLOCKED_NULL",
            "EXTERNAL_BLOCKED_NXRA",
            "GRAVITY_CNAME",
            "REGEX_CNAME",
            "DENYLIST_CNAME",
            "RETRIED",
            "RETRIED_DNSSEC",
            "IN_PROGRESS",
            "DBBUSY",
            "SPECIAL_DOMAIN",
            "CACHE_STALE",
            "EXTERNAL_BLOCKED_EDE15",
        ]
    )
)
REPLY = dict(
    enumerate(
        [
            "UNKNOWN",
            "NODATA",
            "NXDOMAIN",
            "CNAME",
            "IP",
            "DOMAIN",
            "RRNAME",
            "SERVFAIL",
            "REFUSED",
            "NOTIMP",
            "OTHER",
            "DNSSEC",
            "NONE",
            "BLOB",
        ]
    )
)
QTYPE = dict(
    enumerate(
        [
            "NONE",
            "A",
            "AAAA",
            "ANY",
            "SRV",
            "SOA",
            "PTR",
            "TXT",
            "NAPTR",
            "MX",
            "DS",
            "RRSIG",
            "DNSKEY",
            "NS",
            "OTHER",
            "SVCB",
            "HTTPS",
        ]
    )
)

LIMITATIONS = [
    "DNS query rows, not unique resolutions, connections, sessions, human actions or usage duration.",
    "Router-forwarded observations may originate from household devices or the router; origin device unknown.",
    "All rows retained, including retries, reverse lookups and suspected probes; no inferred deduplication.",
    "First/last are observed query times within this window, not session boundaries.",
    "DoH, VPNs, Private Relay, alternate DNS and client/router caching can bypass observations.",
    "Persisted rows may lag by about 60 seconds. Retained bounds and quiet minutes do not prove continuous coverage.",
    "Provider attribution is not specific-service attribution. Shared CDN tenants are unknown without separate evidence.",
    "Status and reply type are distinct fields; CACHE_STALE and IN_PROGRESS are not automatically failures.",
]

#: The application may freeze a 24h/48h/custom window; the legacy CLI keeps its hour.
MAX_WINDOW_SECONDS = 48 * 3600
LEGACY_WINDOW_SECONDS = 3600


class ReportingError(ValueError):
    """A period, snapshot or report request is inconsistent or unsupported."""


def utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="microseconds")


def extraction_query(start: int, end: int, *, max_seconds: int = LEGACY_WINDOW_SECONDS) -> str:
    """One-statement read-only extraction with no filtering or projection loss."""
    start, end = int(start), int(end)
    if start >= end or end - start > max_seconds:
        raise ReportingError(
            f"Extraction accepts a positive window of at most {max_seconds} seconds"
        )
    return f"""SELECT json_object('schema_version',1,'start_epoch',{start},'end_epoch',{end},
        'captured_utc',strftime('%Y-%m-%dT%H:%M:%SZ','now'),
        'retained_rows',(SELECT count(*) FROM queries),
        'oldest_epoch',(SELECT min(timestamp) FROM queries),
        'newest_epoch',(SELECT max(timestamp) FROM queries),
        'window_count',(SELECT count(*) FROM queries WHERE timestamp >= {start} AND timestamp < {end}),
        'observations',json((SELECT json_group_array(json_object(
            'id',id,'timestamp',timestamp,'type',type,'status',status,'domain',domain,
            'client',client,'forward',forward,'additional_info',additional_info,'list_id',list_id,
            'reply_type',reply_type,'ede',ede,'reply_time',reply_time,'dnssec',dnssec))
            FROM (SELECT * FROM queries WHERE timestamp >= {start} AND timestamp < {end}
                  ORDER BY timestamp,id))),
        'rate_context',json((SELECT json_group_array(json_object('timestamp',timestamp,'client',client))
            FROM (SELECT timestamp,client FROM queries WHERE timestamp >= {start - 60}
                  AND timestamp < {start} ORDER BY timestamp))));"""


# -- periods ---------------------------------------------------------------


def resolve_preset(preset: str, *, now: datetime | None = None) -> tuple[int, int]:
    """Resolve 24h/48h once to explicit whole-hour UTC bounds.

    Ends at the last completed hour so the window is closed and stable; the
    persistence lag is disclosed by the caller, not silently corrected.
    """
    if preset not in {"24h", "48h"}:
        raise ReportingError(f"Unsupported preset: {preset}")
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    end = moment.replace(minute=0, second=0, microsecond=0)
    hours = 24 if preset == "24h" else 48
    start = end - timedelta(hours=hours)
    return int(start.timestamp()), int(end.timestamp())


def resolve_custom(
    local_start: str,
    local_end: str,
    *,
    timezone_name: str,
) -> tuple[int, int]:
    """Resolve explicit local datetimes, rejecting ambiguous or nonexistent times.

    A DST fold can map one local time to two instants; a spring-forward gap maps it
    to none. Both are refused so a period can never silently shift.
    """
    zone = ZoneInfo(timezone_name)
    bounds = []
    for text in (local_start, local_end):
        try:
            naive = datetime.fromisoformat(text)
        except ValueError as error:
            raise ReportingError(f"Unparseable local datetime: {text}") from error
        if naive.tzinfo is not None:
            raise ReportingError(
                "Custom bounds must be naive local datetimes with an explicit zone"
            )
        candidates = {
            naive.replace(tzinfo=zone, fold=0).astimezone(UTC),
            naive.replace(tzinfo=zone, fold=1).astimezone(UTC),
        }
        roundtrip = {candidate.astimezone(zone).replace(tzinfo=None) for candidate in candidates}
        if roundtrip != {naive}:
            raise ReportingError(f"Nonexistent local time in {timezone_name}: {text}")
        if len(candidates) > 1:
            raise ReportingError(f"Ambiguous local time in {timezone_name}: {text}")
        bounds.append(int(next(iter(candidates)).timestamp()))
    if bounds[0] >= bounds[1]:
        raise ReportingError("Custom period start must be before end")
    if bounds[1] - bounds[0] > MAX_WINDOW_SECONDS:
        raise ReportingError("Custom period cannot exceed 48 hours")
    return bounds[0], bounds[1]


# -- rows and interpretation ----------------------------------------------


def normalize_domain(domain: str) -> str:
    return domain.lower().rstrip(".")


def is_reverse_lookup(domain: str) -> bool:
    return domain.endswith((".in-addr.arpa", ".ip6.arpa"))


def periodicity(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Burst starts describe query timing only; they are not sessions or lookups."""
    starts = []
    previous = None
    for row in sorted(rows, key=lambda r: float(r["timestamp"])):
        moment = float(row["timestamp"])
        if previous is None or moment - previous > 10:
            starts.append(moment)
        previous = moment
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    median = statistics.median(gaps) if gaps else 0
    regular = (
        len(gaps) >= 3
        and median >= 60
        and all(abs(gap - median) <= max(5, median * 0.15) for gap in gaps)
    )
    return {
        "suspected": regular,
        "burst_start_count": len(starts),
        "median_gap_seconds": round(median, 3),
        "rule": (
            "10-second burst separation; >=4 starts; gaps within 15% or 5s of median >=60s; "
            "heuristic only"
        ),
    }


def load_snapshot(path: str | Path) -> tuple[dict[str, object], bytes]:
    """Read a preserved extraction payload and retain its exact bytes for hashing."""
    raw = Path(path).read_bytes()
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ReportingError(f"Snapshot is not valid JSON: {path}") from error
    missing = {
        "schema_version",
        "start_epoch",
        "end_epoch",
        "captured_utc",
        "window_count",
        "observations",
    } - set(snapshot)
    if missing:
        raise ReportingError(f"Snapshot is missing required fields: {sorted(missing)}")
    return snapshot, raw


def validate_snapshot(snapshot: Mapping[str, object]) -> None:
    """Reject snapshots whose counts, ids or bounds do not reconcile."""
    rows = snapshot["observations"]
    if not isinstance(rows, list) or not rows:
        raise ReportingError("Snapshot has no observations")
    start, end = int(snapshot["start_epoch"]), int(snapshot["end_epoch"])
    if start >= end:
        raise ReportingError("Snapshot bounds are not a positive half-open window")
    if len(rows) != int(snapshot["window_count"]):
        raise ReportingError("Snapshot window_count does not match its rows")
    if len({row["id"] for row in rows}) != len(rows):
        raise ReportingError("Snapshot contains duplicate row ids")
    if any(not start <= float(row["timestamp"]) < end for row in rows):
        raise ReportingError("Snapshot contains rows outside its own bounds")


def coverage(
    rows: Sequence[Mapping[str, object]],
    *,
    start_epoch: int,
    end_epoch: int,
    retained_rows: int | None,
    oldest_epoch: float | None,
    newest_epoch: float | None,
    captured_utc: str | None,
    collection_gaps: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Describe what was observed and what merely appears quiet.

    Coverage is never a claim of continuous collection: retained bounds, capture
    time and explicit gaps are shown separately from the chosen period.
    """
    window_seconds = end_epoch - start_epoch
    bins = max(1, window_seconds // 60)
    occupied: set[int] = set()
    for row in rows:
        offset = int(float(row["timestamp"])) - start_epoch
        occupied.add(min(bins - 1, max(0, offset // 60)))
    return {
        "period_start_utc": utc(start_epoch),
        "period_end_utc": utc(end_epoch),
        "period_seconds": window_seconds,
        "captured_utc": captured_utc,
        "retained_rows_all_time": retained_rows,
        "oldest_retained_epoch": oldest_epoch,
        "newest_retained_epoch": newest_epoch,
        "persistence_lag_note": "Persisted rows may trail real time by about 60 seconds.",
        "included_rows": len(rows),
        "distinct_minutes_with_rows": len(occupied),
        "total_minutes": bins,
        "quiet_minutes": bins - len(occupied),
        "quiet_minute_note": "A quiet minute is not an outage or proof of inactivity.",
        "collection_gaps": list(collection_gaps),
    }


# -- timelines and denominators --------------------------------------------

TIMELINE_BIN_SECONDS = 300
MAX_TIMELINE_BINS = 2880


def timeline(
    rows: Sequence[Mapping[str, object]],
    *,
    start_epoch: int,
    end_epoch: int,
    bin_seconds: int = TIMELINE_BIN_SECONDS,
) -> dict[str, object]:
    """Per-bin DNS row and distinct-domain counts for the chosen period.

    Zero rows in a bin means only that no query was persisted in that interval; it
    is not an outage, an empty network or proof of inactivity.
    """
    if end_epoch <= start_epoch:
        raise ReportingError("Timeline period must be a positive window")
    if not 60 <= bin_seconds <= 86_400:
        raise ReportingError("Timeline bins must be between 60 and 86400 seconds")
    bins = max(1, (end_epoch - start_epoch + bin_seconds - 1) // bin_seconds)
    if bins > MAX_TIMELINE_BINS:
        raise ReportingError(f"Timeline would need more than {MAX_TIMELINE_BINS} bins")
    row_counts = [0] * bins
    domains: list[set[str]] = [set() for _ in range(bins)]
    for row in rows:
        offset = int(float(row["timestamp"])) - start_epoch
        index = min(bins - 1, max(0, offset // bin_seconds))
        row_counts[index] += 1
        domains[index].add(normalize_domain(str(row["domain"])))
    peak = max(row_counts) if row_counts else 0
    return {
        "bin_seconds": bin_seconds,
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "peak_rows": peak,
        "bins": [
            {
                "index": index,
                "start_epoch": start_epoch + index * bin_seconds,
                "end_epoch": min(end_epoch, start_epoch + (index + 1) * bin_seconds),
                "start_utc": utc(start_epoch + index * bin_seconds),
                "rows": count,
                "domains": len(domains[index]),
                "height_percent": 0 if peak == 0 else round(100 * count / peak),
            }
            for index, count in enumerate(row_counts)
        ],
        "note": "Empty bins are quiet observations, not outages or inactivity.",
    }


def classification_coverage(report: Mapping[str, object]) -> dict[str, object]:
    """Report classification coverage by distinct domains *and* by DNS rows."""
    domain_counts: Counter[str] = Counter()
    row_counts: Counter[str] = Counter()
    for section in ("destinations", "reverse_lookups"):
        for entry in report.get(section, []):
            classification = entry["classification"]
            if classification.get("likely_service"):
                bucket = "service_specific"
            elif classification.get("provider"):
                bucket = "provider_only"
            else:
                bucket = "unresolved"
            domain_counts[bucket] += 1
            row_counts[bucket] += int(entry["query_count"])
    domains_total = sum(domain_counts.values())
    rows_total = sum(row_counts.values())
    return {
        "domains": {
            "total": domains_total,
            "service_specific": domain_counts["service_specific"],
            "provider_only": domain_counts["provider_only"],
            "unresolved": domain_counts["unresolved"],
        },
        "rows": {
            "total": rows_total,
            "service_specific": row_counts["service_specific"],
            "provider_only": row_counts["provider_only"],
            "unresolved": row_counts["unresolved"],
        },
        "note": (
            "Domains and DNS rows are separate denominators: one heavily queried "
            "unresolved domain can dominate either. Unresolved stays explicit."
        ),
    }


def analysis_coverage(report: Mapping[str, object]) -> dict[str, object]:
    """Count saved model analysis states and roles against domains and DNS rows."""
    role_domains: Counter[str] = Counter()
    role_rows: Counter[str] = Counter()
    state_domains: Counter[str] = Counter()
    state_rows: Counter[str] = Counter()
    for entry in report.get("destinations", []):
        analysis = entry["classification"].get("analysis")
        state = str(analysis.get("state")) if analysis else "not_analyzed"
        role = str(analysis.get("role") or "unknown") if analysis else "unknown"
        rows = int(entry["query_count"])
        role_domains[role] += 1
        role_rows[role] += rows
        state_domains[state] += 1
        state_rows[state] += rows
    total_domains = len(report.get("destinations", []))
    total_rows = sum(int(entry["query_count"]) for entry in report.get("destinations", []))
    return {
        "domains": {
            "total": total_domains,
            "by_role": dict(role_domains),
            "by_state": dict(state_domains),
        },
        "rows": {"total": total_rows, "by_role": dict(role_rows), "by_state": dict(state_rows)},
        "note": "Saved classifications describe household DNS evidence; device and gameplay activity remain unknown.",
    }


# -- report assembly -------------------------------------------------------


def _legacy_classification(
    resolution: Resolution, provider_resolution: Resolution | None = None
) -> dict[str, object]:
    """Merge the service and provider resolutions without inventing a service.

    A provider-only rule may name the provider/CDN but must never be promoted into a
    service-specific label; such an entry keeps ``likely_service`` empty.
    """
    if resolution.state == "resolved" and resolution.rule is not None:
        rule = dict(resolution.rule)
        merged = dict(rule)
        merged.update(
            {
                "likely_service": rule.get("service") or rule.get("likely_service"),
                "provider": rule.get("provider"),
                "category": rule.get("category", "unknown"),
                "confidence": rule.get("confidence", "unknown"),
                "ambiguity": rule.get("ambiguity") or rule.get("verification_state"),
                "evidence": rule.get("evidence", []),
                "method": rule.get("method", "reviewed_mapping"),
                "verified_until": rule.get("verified_until"),
                "verification_state": rule.get("verification_state", "reviewed"),
            }
        )
        return merged
    if (
        provider_resolution is not None
        and provider_resolution.state == "resolved"
        and provider_resolution.rule is not None
    ):
        rule = dict(provider_resolution.rule)
        return {
            "likely_service": None,
            "provider": rule.get("provider"),
            "category": rule.get("category", "unknown"),
            "confidence": rule.get("confidence", "unknown"),
            "ambiguity": rule.get("ambiguity") or "Provider known; specific service unknown",
            "evidence": rule.get("evidence", []),
            "method": rule.get("method", "reviewed_mapping"),
            "verified_until": rule.get("verified_until"),
            "verification_state": rule.get("verification_state", "reviewed"),
            "scope": "provider_only",
        }
    return {
        "likely_service": None,
        "provider": None,
        "category": "unknown",
        "confidence": "unknown",
        "ambiguity": resolution.reason or "No current verified mapping; not guessed",
        "evidence": [],
        "method": resolution.state,
    }


def build_report(
    snapshot: Mapping[str, object],
    cache: Mapping[str, object],
    *,
    attributions: Mapping[int, str] | None = None,
    now_utc: str | None = None,
    analysis_results: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Assemble the report, preserving every row and distinguishing unknowns.

    ``attributions`` may hold only locally verified row-to-device keys; rows absent
    from it remain explicitly device-unknown.
    """
    validate_snapshot(snapshot)
    rows = snapshot["observations"]
    start, end = int(snapshot["start_epoch"]), int(snapshot["end_epoch"])
    rules = cache.get("mappings", [])
    as_of = now_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z")

    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        groups[normalize_domain(str(row["domain"]))].append(row)

    analysis_by_domain: dict[str, dict[str, object]] = {}
    for saved in analysis_results:
        domain = normalize_domain(str(saved.get("domain") or ""))
        if not domain or domain in analysis_by_domain:
            continue
        try:
            result = json.loads(str(saved.get("result_json") or ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(result, Mapping) or result.get("source") != "model":
            continue
        verification = str(result.get("verification_state") or "unknown")
        state = {
            "ai_grounded": "model_proposal",
            "provider_only": "provider_association",
            "unknown": "unknown",
        }.get(verification, "unknown")
        analysis_by_domain[domain] = {
            "state": state,
            "role": str(result.get("role") or "unknown"),
            "service": result.get("service"),
            "provider": result.get("provider"),
            "category": str(result.get("category") or "unknown"),
            "confidence": str(result.get("confidence") or "unknown"),
            "reason": result.get("unresolved_reason"),
            "supporting_spans": result.get("supporting_spans", []),
            "analysis_id": str(saved.get("analysis_id") or ""),
            "created_utc": str(saved.get("created_utc") or ""),
        }

    destinations, reverse = [], []
    for domain, observations in groups.items():
        resolved = resolve_domain(domain, rules, as_of=as_of)
        provider_resolved = None
        if resolved.state != "resolved":
            provider_resolved = resolve_domain(domain, rules, as_of=as_of, field="provider")
        classification = _legacy_classification(resolved, provider_resolved)
        classification["analysis"] = analysis_by_domain.get(domain)
        timing = periodicity(observations)
        tags = []
        if timing["suspected"] or classification.get("suspected_probe_reason"):
            tags.append("suspected_periodic_probe")
        if classification.get("suspected_probe_reason"):
            timing["prior_review_suspicion"] = classification["suspected_probe_reason"]
        if classification.get("category") == "connectivity_probe":
            tags.append("documented_probe_endpoint_origin_unknown")
        if is_reverse_lookup(domain):
            tags.append("reverse_lookup")
        elif domain.endswith(".arpa"):
            tags.append("DNS_protocol_namespace_not_application_destination")
        entry = {
            "domain": domain,
            "observed_spellings": sorted({str(row["domain"]) for row in observations}),
            "query_count": len(observations),
            "first_query_utc": utc(min(float(row["timestamp"]) for row in observations)),
            "last_query_utc": utc(max(float(row["timestamp"]) for row in observations)),
            "query_types": dict(
                Counter(QTYPE.get(row["type"], f"TYPE_ID_{row['type']}") for row in observations)
            ),
            "statuses": dict(
                Counter(
                    STATUS.get(row["status"], f"STATUS_ID_{row['status']}") for row in observations
                )
            ),
            "dns_replies": dict(
                Counter(
                    REPLY.get(row["reply_type"], f"REPLY_ID_{row['reply_type']}")
                    for row in observations
                )
            ),
            "ede_codes": dict(Counter(str(row.get("ede")) for row in observations)),
            "apparent_clients": dict(Counter(str(row["client"]) for row in observations)),
            "domain_qtype_second_groups": len(
                {(row["type"], int(float(row["timestamp"]))) for row in observations}
            ),
            "observation_ids": [row["id"] for row in observations],
            "tags": tags,
            "periodicity": timing,
            "classification": classification,
        }
        (reverse if is_reverse_lookup(domain) else destinations).append(entry)

    for group in (destinations, reverse):
        group.sort(key=lambda entry: (-entry["query_count"], entry["domain"]))

    rate_rows = sorted(
        list(snapshot.get("rate_context", [])) + list(rows), key=lambda r: float(r["timestamp"])
    )
    queues: dict[str, deque[float]] = defaultdict(deque)
    peaks: Counter[str] = Counter()
    peak_windows: dict[str, dict[str, object]] = {}
    for row in rate_rows:
        moment, client = float(row["timestamp"]), str(row["client"])
        queue = queues[client]
        while queue and queue[0] < moment - 60:
            queue.popleft()
        queue.append(moment)
        if moment >= start and len(queue) > peaks[client]:
            peaks[client] = len(queue)
            peak_windows[client] = {
                "rows": len(queue),
                "start_epoch": moment - 60,
                "end_epoch": moment,
                "start_utc": utc(moment - 60),
                "end_utc": utc(moment),
            }

    verified = attributions or {}
    attributed_rows = sum(1 for row in rows if row["id"] in verified)
    router_rows = sum(1 for row in rows if str(row["client"]) == "192.168.1.1")

    report = {
        "schema_version": 2,
        "generated_utc": as_of,
        "window": {
            "start_utc": utc(start),
            "end_utc": utc(end),
            "bounds": "[start,end)",
            "seconds": end - start,
        },
        "source": {
            key: snapshot.get(key)
            for key in ["captured_utc", "retained_rows", "oldest_epoch", "newest_epoch"]
        },
        "coverage": coverage(
            rows,
            start_epoch=start,
            end_epoch=end,
            retained_rows=snapshot.get("retained_rows"),
            oldest_epoch=snapshot.get("oldest_epoch"),
            newest_epoch=snapshot.get("newest_epoch"),
            captured_utc=snapshot.get("captured_utc"),
        ),
        "summary": {
            "raw_rows": len(rows),
            "distinct_domains": len(groups),
            "reverse_rows": sum(entry["query_count"] for entry in reverse),
            "destination_rows": sum(entry["query_count"] for entry in destinations),
            "router_forwarded_rows_origin_unknown": router_rows,
            "other_apparent_client_rows": len(rows) - router_rows,
            "device_attributed_rows": attributed_rows,
            "device_unattributed_rows": len(rows) - attributed_rows,
            "service_labeled_domains": sum(
                bool(entry["classification"]["likely_service"]) for entry in destinations
            ),
            "provider_only_domains": sum(
                not entry["classification"]["likely_service"]
                and bool(entry["classification"]["provider"])
                for entry in destinations
            ),
            "unmapped_domains": sum(
                entry["classification"]["confidence"] == "unknown" for entry in destinations
            ),
            "dns_replies": dict(
                Counter(REPLY.get(row["reply_type"], str(row["reply_type"])) for row in rows)
            ),
            "statuses": dict(
                Counter(STATUS.get(row["status"], str(row["status"])) for row in rows)
            ),
            "peak_persisted_rows_in_inclusive_60s_by_apparent_client": dict(peaks),
            "peak_60s_windows": peak_windows,
        },
        "rate_note": (
            "Timestamp-based inclusive 60-second spans with preceding-minute context; "
            "not FTL limiter headroom."
        ),
        "limitations": LIMITATIONS,
        "destinations": destinations,
        "reverse_lookups": reverse,
        "classification_cache_revision": cache.get("revision", "none"),
    }
    report["analysis_coverage"] = analysis_coverage(report)
    if sum(entry["query_count"] for entry in destinations + reverse) != len(rows):
        raise ReportingError("Report lost or duplicated observations during grouping")
    return report


def render_html(report: Mapping[str, object]) -> str:
    """Private, dependency-free HTML with no remote assets or scripts."""

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
        "<title>Private DNS observations</title>",
        "<style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:20px;"
        "background:#f5f7fa;color:#182331}",
        "article,header{background:white;padding:18px;margin:14px 0;border:1px solid #ccd4df;"
        "border-radius:10px}",
        "h2{overflow-wrap:anywhere;font-size:1.15rem}dd{margin:0 0 8px;overflow-wrap:anywhere}"
        "dt{font-weight:bold}",
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}"
        "summary{cursor:pointer;padding:10px 0}</style>",
        "<header><h1>Private household DNS observations</h1>",
        "<p>Local evidence · no tracking of people or devices</p>",
        f"<p>{esc(report['window']['start_utc'])} ≤ query time &lt; "
        f"{esc(report['window']['end_utc'])}</p>",
        "<p>UTC timestamps.</p>",
        "<h2>Snapshot reconciliation and DNS outcomes</h2><pre>"
        + esc(json.dumps(report["summary"], indent=2))
        + "</pre>",
        "<h2>Coverage</h2><pre>" + esc(json.dumps(report["coverage"], indent=2)) + "</pre>",
        "<ul>" + "".join("<li>" + esc(item) + "</li>" for item in report["limitations"]) + "</ul>",
        "<p>" + esc(report["rate_note"]) + "</p>",
        '<p>Private files alongside this report: <a href="report.json">structured report</a> · '
        '<a href="observations.json">all original observations</a> · '
        '<a href="classifications.json">classification cache used</a>.</p></header>',
    ]
    for section in ("destinations", "reverse_lookups"):
        parts.append("<h2>" + esc(section.replace("_", " ").title()) + "</h2>")
        for entry in report[section]:
            classification = entry["classification"]
            parts.append("<article><h2>" + esc(entry["domain"]) + "</h2><dl>")
            fields = {
                "DNS query rows (not connections)": entry["query_count"],
                "First observed query (UTC)": entry["first_query_utc"],
                "Last observed query (UTC)": entry["last_query_utc"],
                "Likely service": classification["likely_service"] or "Unknown / ambiguous",
                "Provider": classification["provider"] or "Unknown",
                "Category": classification["category"],
                "Classification confidence": classification["confidence"],
                "Ambiguity": classification["ambiguity"],
                "Tags": ", ".join(entry["tags"]) or "None",
            }
            parts.extend(
                "<dt>" + esc(key) + "</dt><dd>" + esc(value) + "</dd>"
                for key, value in fields.items()
            )
            parts.append(
                "</dl><details><summary>DNS outcomes, query types and presentation grouping"
                "</summary><pre>"
            )
            parts.append(
                esc(
                    json.dumps(
                        {
                            key: entry[key]
                            for key in [
                                "query_types",
                                "statuses",
                                "dns_replies",
                                "ede_codes",
                                "domain_qtype_second_groups",
                                "periodicity",
                                "apparent_clients",
                            ]
                        },
                        indent=2,
                    )
                )
            )
            parts.append(
                "</pre><p>Grouping is presentation only; no rows removed or unique sessions "
                "inferred.</p></details>"
            )
            for evidence in classification["evidence"]:
                url = str(evidence["url"])
                if urlparse(url).scheme != "https":
                    continue
                parts.append(
                    '<p><a rel="noreferrer noopener" href="'
                    + esc(url)
                    + '">'
                    + esc(url)
                    + "</a><br>"
                    + esc(evidence.get("claim", ""))
                    + "</p>"
                )
            parts.append(
                "<details><summary>Original spellings and raw row IDs</summary><pre>"
                + esc(
                    json.dumps(
                        {key: entry[key] for key in ["observed_spellings", "observation_ids"]},
                        indent=2,
                    )
                )
                + "</pre></details></article>"
            )
    parts.append("</html>")
    return "\n".join(parts)


def snapshot_sha256(rows: Sequence[Mapping[str, object]]) -> str:
    """Stable digest of canonical rows, independent of capture time."""
    ordered = sorted(rows, key=lambda row: (float(row["timestamp"]), int(row["id"])))
    return hashlib.sha256(
        json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotSummary:
    snapshot_id: str
    period_start: int
    period_end: int
    row_count: int
    digest: str


# -- stored reports (the web read model) -----------------------------------


@dataclass(frozen=True, slots=True)
class Window:
    """One requested period, clipped to the stored observations that cover it."""

    start_epoch: int
    end_epoch: int
    preset: str
    snapshot_ids: tuple[str, ...]


def _qualify(rows: Sequence[Mapping[str, object]], snapshot_id: str) -> list[dict[str, object]]:
    """Qualify source row IDs with their snapshot so imports cannot conflate them."""
    return [{**row, "id": f"{snapshot_id}:{row['id']}"} for row in rows]


def _covered_ranges(
    sources: Sequence[Mapping[str, object]], *, start: int, end: int
) -> list[dict[str, object]]:
    """Intervals inside the window that no imported snapshot covers."""
    gaps: list[dict[str, object]] = []
    cursor = start
    for source in sorted(sources, key=lambda item: int(item["start_epoch"])):
        source_start = max(start, int(source["start_epoch"]))
        source_end = min(end, int(source["end_epoch"]))
        if source_end <= cursor:
            continue
        if source_start > cursor:
            gaps.append(
                {"start_utc": utc(cursor), "end_utc": utc(source_start), "reason": "no import"}
            )
        cursor = max(cursor, source_end)
    if cursor < end:
        gaps.append({"start_utc": utc(cursor), "end_utc": utc(end), "reason": "no import"})
    return gaps


def merge_period_digest(
    rows: Sequence[Mapping[str, object]], *, start_epoch: int, end_epoch: int
) -> str:
    """Stable digest of the included qualified rows and bounds for job identity."""
    ordered = sorted(rows, key=lambda row: (float(row["timestamp"]), str(row["id"])))
    payload = {
        "schema": "reporting-period-v1",
        "start": start_epoch,
        "end": end_epoch,
        "interpretation": 1,
        "rows": [
            [row["id"], row["timestamp"], row["domain"], row["client"], row["type"]]
            for row in ordered
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ReportService:
    """Build dashboard read models from stored snapshots; no network, no writes."""

    def __init__(
        self,
        store: Store,
        *,
        timezone: str = "UTC",
        gaming_namespace_path: str | Path | None = None,
        attribution_source: Callable[[Sequence[Mapping[str, object]]], Mapping[object, str]]
        | None = None,
    ) -> None:
        self._store = store
        self._timezone = timezone
        self._gaming_namespace_path = Path(gaming_namespace_path) if gaming_namespace_path else None
        self._attribution_source = attribution_source

    def snapshots(self) -> list[dict[str, object]]:
        return self._store.snapshots()

    def latest(self) -> dict[str, object] | None:
        snapshots = self._store.snapshots()
        return snapshots[0] if snapshots else None

    def gaming_projection(
        self, namespace_list: object | None = None, *, snapshot_id: str | None = None
    ):
        """Build the pinned, household-only gaming projection from one closed import."""
        from .gaming import (
            GamingDataError,
            NamespaceList,
            build_gaming_projection,
            load_namespace_list,
        )

        if namespace_list is None:
            raw: bytes | None
            if self._gaming_namespace_path is None:
                raw = None
            else:
                try:
                    raw = self._gaming_namespace_path.read_bytes()
                except FileNotFoundError:
                    raw = None
                except OSError:
                    raw = b""
            try:
                namespace_list = load_namespace_list(raw)
            except GamingDataError:
                namespace_list = NamespaceList(
                    "invalid",
                    None,
                    hashlib.sha256(raw).hexdigest() if raw is not None else None,
                    (),
                    "Namespace list is invalid",
                )
        if not isinstance(namespace_list, NamespaceList):
            raise ReportingError("A validated namespace list is required")
        metas = self._store.snapshots()
        if not metas:
            return None
        selected_id = snapshot_id or str(metas[0]["snapshot_id"])
        meta = next((item for item in metas if item["snapshot_id"] == selected_id), None)
        if meta is None:
            raise ReportingError("Unknown snapshot")
        start, end = int(meta["start_epoch"]), int(meta["end_epoch"])
        if end <= start:
            raise ReportingError("Snapshot bounds are unavailable")
        if end - start > LEGACY_WINDOW_SECONDS:
            raise ReportingError("Gaming view supports closed snapshots of at most one hour")
        report = self.report(preset="snapshot", snapshot_id=selected_id, attributions={})
        if report is None:
            return None
        rows = self._store.rows(selected_id, Period(start, end))
        return build_gaming_projection(report, namespace_list, rows)

    def usage_summary(
        self, *, dispatch_day: str | None, analysis_id: str | None = None
    ) -> dict[str, object]:
        """Expose only local usage ledger aggregates; make no external health calls."""
        return self._store.usage_summary(dispatch_day=dispatch_day, analysis_id=analysis_id)

    def gaming_export(
        self, *, snapshot_id: str, basis: str, group: str, role: str
    ) -> dict[str, object]:
        from .gaming import gaming_export_projection

        projection = self.gaming_projection(snapshot_id=snapshot_id)
        if projection is None:
            raise ReportingError("Snapshot is unavailable")
        return gaming_export_projection(projection, basis=basis, group=group, role=role)

    def window(
        self,
        *,
        preset: str = "24h",
        snapshot_id: str | None = None,
        start_local: str | None = None,
        end_local: str | None = None,
        now: datetime | None = None,
    ) -> Window | None:
        """Resolve one explicit half-open UTC window over available snapshots."""
        metas = self._store.snapshots()
        if not metas:
            return None
        if snapshot_id is not None:
            selected = [meta for meta in metas if meta["snapshot_id"] == snapshot_id]
            if not selected:
                raise ReportingError("Unknown snapshot")
            if preset in {"24h", "48h"}:
                start, end = resolve_preset(preset, now=now)
            elif preset == "custom":
                if not start_local or not end_local:
                    raise ReportingError("A custom period needs both bounds")
                start, end = resolve_custom(start_local, end_local, timezone_name=self._timezone)
            else:
                meta = selected[0]
                start, end = int(meta["start_epoch"]), int(meta["end_epoch"])
            preset = "snapshot" if preset == "snapshot" else preset
        elif preset in {"24h", "48h"}:
            start, end = resolve_preset(preset, now=now)
        elif preset == "custom":
            if not start_local or not end_local:
                raise ReportingError("A custom period needs both bounds")
            start, end = resolve_custom(start_local, end_local, timezone_name=self._timezone)
        elif preset == "snapshot":
            meta = metas[0]
            start, end = int(meta["start_epoch"]), int(meta["end_epoch"])
        else:
            raise ReportingError(f"Unsupported period: {preset}")
        if end - start > MAX_WINDOW_SECONDS:
            raise ReportingError("The requested period exceeds the 48-hour limit")
        if end <= start:
            return None
        covered = [
            meta
            for meta in metas
            if int(meta["start_epoch"]) < end
            and int(meta["end_epoch"]) > start
            and (snapshot_id is None or meta["snapshot_id"] == snapshot_id)
        ]
        if not covered:
            return None
        return Window(
            start_epoch=int(start),
            end_epoch=int(end),
            preset=preset,
            snapshot_ids=tuple(str(meta["snapshot_id"]) for meta in covered),
        )

    def report(
        self,
        *,
        preset: str = "24h",
        snapshot_id: str | None = None,
        start_local: str | None = None,
        end_local: str | None = None,
        attributions: Mapping[object, str] | None = None,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        """Assemble the dashboard report, preserving every included observation."""
        window = self.window(
            preset=preset,
            snapshot_id=snapshot_id,
            start_local=start_local,
            end_local=end_local,
            now=now,
        )
        if window is None:
            return None
        sources: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []
        for meta in self._store.snapshots():
            identifier = str(meta["snapshot_id"])
            if identifier not in window.snapshot_ids:
                continue
            source_start = max(window.start_epoch, int(meta["start_epoch"]))
            source_end = min(window.end_epoch, int(meta["end_epoch"]))
            if source_end <= source_start:
                continue
            selected = self._store.rows(identifier, Period(source_start, source_end))
            if not selected:
                continue
            rows.extend(_qualify(selected, identifier))
            sources.append(
                {
                    "snapshot_id": identifier,
                    "datasource": meta["datasource"],
                    "start_epoch": source_start,
                    "end_epoch": source_end,
                    "start_utc": utc(source_start),
                    "end_utc": utc(source_end),
                    "rows": len(selected),
                    "retained_rows": meta.get("retained_rows"),
                    "oldest_epoch": meta.get("oldest_epoch"),
                    "newest_epoch": meta.get("newest_epoch"),
                    "captured_utc": meta["captured_utc"],
                    "imported_utc": meta["created_utc"],
                }
            )
        if not rows:
            return None
        rows.sort(key=lambda row: (float(row["timestamp"]), str(row["id"])))
        retained = [int(source["retained_rows"]) for source in sources if source["retained_rows"]]
        oldest = [float(source["oldest_epoch"]) for source in sources if source["oldest_epoch"]]
        newest = [float(source["newest_epoch"]) for source in sources if source["newest_epoch"]]
        snapshot = {
            "schema_version": 2,
            "start_epoch": window.start_epoch,
            "end_epoch": window.end_epoch,
            "captured_utc": max(str(source["captured_utc"]) for source in sources),
            "retained_rows": max(retained) if retained else None,
            "oldest_epoch": min(oldest) if oldest else None,
            "newest_epoch": max(newest) if newest else None,
            "window_count": len(rows),
            "observations": rows,
        }
        rules = self._store.classification_rules()
        cache = {
            "mappings": rules,
            "revision": rules[0]["classification_id"] if rules else "none",
        }
        resolved = attributions
        if resolved is None and self._attribution_source is not None:
            resolved = self._attribution_source(rows)
        report = build_report(
            snapshot,
            cache,
            attributions=resolved,
            analysis_results=self._store.latest_analysis_results(),
        )
        report["snapshot_id"] = (
            window.snapshot_ids[0] if len(window.snapshot_ids) == 1 else "merged"
        )
        report["snapshot_ids"] = list(window.snapshot_ids)
        report["preset"] = window.preset
        report["sources"] = sources
        report["data_gaps"] = _covered_ranges(
            sources, start=window.start_epoch, end=window.end_epoch
        )
        report["period_digest"] = merge_period_digest(
            rows, start_epoch=window.start_epoch, end_epoch=window.end_epoch
        )
        report["timeline"] = timeline(
            rows, start_epoch=window.start_epoch, end_epoch=window.end_epoch
        )
        report["classification_coverage"] = classification_coverage(report)
        report["reporting_timezone"] = self._timezone
        return report


def filter_report(
    report: Mapping[str, object],
    *,
    query: str = "",
    category: str = "",
    service_only: bool = False,
) -> dict[str, object]:
    """Local display filter over a frozen report; it never changes stored data."""
    needle = query.strip().lower()
    selected = []
    for entry in report["destinations"]:
        classification = entry["classification"]
        if needle and needle not in str(entry["domain"]).lower():
            continue
        if category and classification.get("category") != category:
            continue
        if service_only and not classification.get("likely_service"):
            continue
        selected.append(entry)
    return {
        "destinations": selected,
        "query": query.strip(),
        "category": category,
        "service_only": service_only,
        "matched_domains": len(selected),
        "matched_rows": sum(int(entry["query_count"]) for entry in selected),
        "total_domains": len(report["destinations"]),
        "total_rows": int(report["summary"]["destination_rows"]),
    }


def report_categories(report: Mapping[str, object]) -> list[str]:
    return sorted(
        {
            str(entry["classification"].get("category") or "unknown")
            for entry in report["destinations"]
        }
    )
