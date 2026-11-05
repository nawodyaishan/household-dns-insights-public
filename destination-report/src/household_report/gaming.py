"""Private namespace matching and a client-free gaming DNS read projection."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

MAX_NAMESPACE_BYTES = 256 * 1024
MAX_NAMESPACE_RULES = 1000
MAX_REVISION_LENGTH = 80
MAX_GROUP_TEXT_LENGTH = 120
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_GROUP_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_RULE_FIELDS = {
    "rule_id",
    "namespace",
    "match",
    "group_id",
    "group_label",
    "group_kind",
    "review_note",
}


class GamingDataError(ValueError):
    """Namespace data is invalid and must not be partially applied."""


@dataclass(frozen=True, slots=True)
class NamespaceList:
    state: str
    revision: str | None
    sha256: str | None
    rules: tuple[dict[str, str], ...]
    error: str | None = None


def _normalize_domain(value: str) -> str:
    return value.lower().rstrip(".")


def _is_reverse_or_protocol(domain: str) -> bool:
    return domain.endswith(".arpa")


def _timeline(
    rows: Sequence[Mapping[str, object]], *, start_epoch: int, end_epoch: int
) -> dict[str, object]:
    bin_seconds = 300
    bins = max(1, (end_epoch - start_epoch + bin_seconds - 1) // bin_seconds)
    counts = [0] * bins
    domains: list[set[str]] = [set() for _ in range(bins)]
    for row in rows:
        index = min(
            bins - 1,
            max(0, (int(float(row["timestamp"])) - start_epoch) // bin_seconds),
        )
        counts[index] += 1
        domains[index].add(_normalize_domain(str(row["domain"])))
    peak = max(counts, default=0)
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
                "start_utc": datetime.fromtimestamp(
                    start_epoch + index * bin_seconds, UTC
                ).isoformat(timespec="microseconds"),
                "rows": count,
                "domains": len(domains[index]),
                "height_percent": 0 if peak == 0 else round(100 * count / peak),
            }
            for index, count in enumerate(counts)
        ],
        "note": "Empty bins are quiet observations, not outages or inactivity.",
    }


def _host_name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise GamingDataError("Namespace must be a hostname")
    host = _normalize_domain(value)
    if len(host) > 253 or ":" in host or "/" in host or "*" in host:
        raise GamingDataError("Namespace must be a plain DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise GamingDataError("IP addresses are not namespaces")
    labels = host.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise GamingDataError("Namespace hostname is invalid or too broad")
    if host.endswith(".arpa"):
        raise GamingDataError("Reverse and protocol namespaces are not allowed")
    return host


def load_namespace_list(raw: bytes | None) -> NamespaceList:
    """Validate a complete versioned JSON list; missing differs from valid empty."""
    if raw is None:
        return NamespaceList("unavailable", None, None, (), "Namespace list is missing")
    if len(raw) > MAX_NAMESPACE_BYTES:
        raise GamingDataError("Namespace list exceeds the size limit")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GamingDataError("Namespace list is not valid JSON") from error
    if not isinstance(document, Mapping) or set(document) != {
        "schema_version",
        "revision",
        "rules",
    }:
        raise GamingDataError("Namespace list has an unsupported structure")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise GamingDataError("Namespace list version is unsupported")
    revision = document["revision"]
    if not isinstance(revision, str) or not revision.strip() or len(revision) > MAX_REVISION_LENGTH:
        raise GamingDataError("Namespace list revision is invalid")
    raw_rules = document["rules"]
    if not isinstance(raw_rules, list) or len(raw_rules) > MAX_NAMESPACE_RULES:
        raise GamingDataError("Namespace rules must be a bounded list")

    rules: list[dict[str, str]] = []
    rule_ids: set[str] = set()
    groups: dict[str, tuple[str, str]] = {}
    precedence: dict[tuple[str, str], tuple[str, str, str]] = {}
    for candidate in raw_rules:
        if not isinstance(candidate, Mapping) or set(candidate) != _RULE_FIELDS:
            raise GamingDataError("A namespace rule has an unsupported structure")
        if any(not isinstance(value, str) for value in candidate.values()):
            raise GamingDataError("Namespace rule fields must be strings")
        rule_id = candidate["rule_id"]
        group_id = candidate["group_id"]
        label = candidate["group_label"].strip()
        kind = candidate["group_kind"]
        note = candidate["review_note"].strip()
        match = candidate["match"]
        namespace = _host_name(candidate["namespace"])
        if not _GROUP_ID.fullmatch(rule_id) or rule_id in rule_ids:
            raise GamingDataError("Namespace rule ID is invalid or duplicated")
        if not _GROUP_ID.fullmatch(group_id):
            raise GamingDataError("Namespace group ID is invalid")
        if not label or len(label) > MAX_GROUP_TEXT_LENGTH or not note:
            raise GamingDataError("Namespace group label and review note are required")
        if kind not in {"game", "platform"} or match not in {"exact", "suffix"}:
            raise GamingDataError("Namespace rule kind or match mode is unsupported")
        group = (label, kind)
        if group_id in groups and groups[group_id] != group:
            raise GamingDataError("Namespace group has inconsistent label or kind")
        groups[group_id] = group
        key = (match, namespace)
        value = (group_id, label, kind)
        if key in precedence and precedence[key] != value:
            raise GamingDataError("Namespace rules conflict at equal precedence")
        precedence[key] = value
        rule_ids.add(rule_id)
        rules.append(
            {
                "rule_id": rule_id,
                "namespace": namespace,
                "match": match,
                "group_id": group_id,
                "group_label": label,
                "group_kind": kind,
                "review_note": note,
            }
        )
    rules.sort(key=lambda item: (item["match"], item["namespace"], item["rule_id"]))
    return NamespaceList("available", revision, hashlib.sha256(raw).hexdigest(), tuple(rules))


def match_namespace(domain: str, rules: Sequence[Mapping[str, str]]) -> dict[str, str] | None:
    """Exact match first; otherwise choose the longest DNS-label suffix."""
    host = _normalize_domain(domain)
    exact = [rule for rule in rules if rule["match"] == "exact" and host == rule["namespace"]]
    if exact:
        return dict(min(exact, key=lambda rule: rule["rule_id"]))
    suffixes = [
        rule
        for rule in rules
        if rule["match"] == "suffix"
        and (host == rule["namespace"] or host.endswith(f".{rule['namespace']}"))
    ]
    if not suffixes:
        return None
    longest = max(len(rule["namespace"]) for rule in suffixes)
    return dict(
        min((r for r in suffixes if len(r["namespace"]) == longest), key=lambda r: r["rule_id"])
    )


def _analysis(entry: Mapping[str, object]) -> dict[str, object] | None:
    classification = entry.get("classification")
    saved = classification.get("analysis") if isinstance(classification, Mapping) else None
    if not isinstance(saved, Mapping):
        return None
    spans = saved.get("supporting_spans")
    return {
        key: saved.get(key)
        for key in (
            "state",
            "role",
            "service",
            "provider",
            "category",
            "reason",
            "analysis_id",
            "created_utc",
        )
    } | {"supporting_spans": spans if isinstance(spans, list) else []}


def build_gaming_projection(
    report: Mapping[str, object],
    namespace_list: NamespaceList,
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return a restricted household projection and timeline for eligible rows."""
    if not isinstance(report.get("snapshot_id"), str):
        raise GamingDataError("A pinned snapshot report is required")
    source_entries = [
        item
        for section in ("destinations", "reverse_lookups")
        for item in report.get(section, ())
        if isinstance(item, Mapping)
    ]
    projected = []
    for source in source_entries:
        domain = _normalize_domain(str(source.get("domain") or ""))
        if not domain or _is_reverse_or_protocol(domain):
            continue
        known = (
            match_namespace(domain, namespace_list.rules)
            if namespace_list.state == "available"
            else None
        )
        analysis = _analysis(source)
        model = bool(
            analysis
            and analysis.get("state") == "model_proposal"
            and analysis.get("role") == "gameplay_matchmaking"
        )
        if known is None and not model:
            continue
        projected.append(
            {
                "domain": domain,
                "query_count": int(source.get("query_count", 0)),
                "first_query_utc": source.get("first_query_utc"),
                "last_query_utc": source.get("last_query_utc"),
                "query_types": dict(source.get("query_types", {})),
                "statuses": dict(source.get("statuses", {})),
                "dns_replies": dict(source.get("dns_replies", {})),
                "observation_ids": list(source.get("observation_ids", ())),
                "known_list_match": known is not None,
                "known_rule": known,
                "model_proposal": model,
                "analysis": analysis,
                "group": (
                    {key: known[key] for key in ("group_id", "group_label", "group_kind")}
                    if known
                    else {
                        "group_id": "model-proposals",
                        "group_label": "Model proposals — game unknown",
                        "group_kind": "unknown",
                    }
                ),
            }
        )
    projected.sort(key=lambda item: (-int(item["query_count"]), str(item["domain"])))
    selected_ids = {identifier for item in projected for identifier in item["observation_ids"]}
    snapshot_id = str(report["snapshot_id"])
    selected_rows = [
        {**row, "id": f"{snapshot_id}:{row['id']}"}
        for row in rows
        if f"{snapshot_id}:{row.get('id')}" in selected_ids
    ]
    window = report.get("window")
    if not isinstance(window, Mapping):
        raise GamingDataError("Snapshot period is unavailable")
    sources = report.get("sources")
    source = sources[0] if isinstance(sources, Sequence) and sources else None
    try:
        start_epoch = int(float(source["start_epoch"] if source else window["start_epoch"]))
        end_epoch = int(float(source["end_epoch"] if source else window["end_epoch"]))
    except (KeyError, TypeError, ValueError) as error:
        raise GamingDataError("Snapshot period is unavailable") from error

    all_domains = source_entries
    known_domains = sum(bool(item["known_list_match"]) for item in projected)
    model_domains = sum(bool(item["model_proposal"]) for item in projected)
    fingerprint_payload = {
        "interpretation_version": 1,
        "snapshot_id": snapshot_id,
        "period_digest": report.get("period_digest"),
        "namespace_state": namespace_list.state,
        "namespace_revision": namespace_list.revision,
        "namespace_sha256": namespace_list.sha256,
        "analysis": [
            {"domain": item["domain"], **item["analysis"]}
            for item in projected
            if item["analysis"] is not None
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    total_rows = sum(int(item.get("query_count", 0)) for item in all_domains)
    reverse_entries = [
        item
        for item in all_domains
        if str(item.get("domain", "")).endswith((".in-addr.arpa", ".ip6.arpa"))
    ]
    protocol_entries = [
        item
        for item in all_domains
        if str(item.get("domain", "")).endswith(".arpa") and item not in reverse_entries
    ]
    source_meta = source if isinstance(source, Mapping) else {}
    window_metadata = dict(window)
    window_metadata.update(
        {
            "start_epoch": start_epoch,
            "end_epoch": end_epoch,
            "timezone": report.get("reporting_timezone"),
            "captured_utc": source_meta.get("captured_utc"),
            "imported_utc": source_meta.get("imported_utc"),
        }
    )
    return {
        "snapshot_id": report["snapshot_id"],
        "window": window_metadata,
        "namespace": {
            "state": namespace_list.state,
            "revision": namespace_list.revision,
            "sha256": namespace_list.sha256,
            "rule_count": len(namespace_list.rules),
            "error": namespace_list.error,
        },
        "entries": projected,
        "counts": {
            "snapshot_domains": len(all_domains),
            "snapshot_rows": total_rows,
            "eligible_domains": len(projected),
            "eligible_rows": sum(int(item["query_count"]) for item in projected),
            "known_list_domains": known_domains,
            "model_domains": model_domains,
            "known_model_overlap_domains": sum(
                bool(item["known_list_match"] and item["model_proposal"]) for item in projected
            ),
            "reverse_domains": len(reverse_entries),
            "reverse_rows": sum(int(item.get("query_count", 0)) for item in reverse_entries),
            "protocol_domains": len(protocol_entries),
            "protocol_rows": sum(int(item.get("query_count", 0)) for item in protocol_entries),
            "not_selected_domains": len(all_domains) - len(projected),
            "not_selected_rows": total_rows - sum(int(item["query_count"]) for item in projected),
        },
        "timeline": _timeline(selected_rows, start_epoch=start_epoch, end_epoch=end_epoch),
        "fingerprint": fingerprint,
        "household_scope": "household scope; device unknown",
        "limitations": [
            "DNS destination relevance is not proof of a connection, game launch, match, player, device or play time.",
            "Namespace matches are owner-reviewed and incomplete; model proposals are not independently verified.",
        ],
    }


def gaming_export_projection(
    projection: Mapping[str, object],
    *,
    basis: str = "all",
    group: str = "",
    role: str = "",
) -> dict[str, object]:
    """Create a domain-only export allowlist using the page's exact filters/order."""
    if basis not in {"all", "known_list", "model"}:
        basis = "all"
    entries = list(projection.get("entries", ()))
    if basis == "known_list":
        entries = [entry for entry in entries if entry["known_list_match"]]
    elif basis == "model":
        entries = [entry for entry in entries if entry["model_proposal"]]
    if group:
        entries = [entry for entry in entries if entry["group"]["group_id"] == group]
    if role:
        entries = [
            entry
            for entry in entries
            if (entry.get("analysis") or {}).get("role", "unknown") == role
        ]
    rows = []
    for entry in entries:
        analysis = entry.get("analysis") or {}
        rule = entry.get("known_rule") or {}
        rows.append(
            {
                "domain": entry["domain"],
                "group_id": entry["group"]["group_id"],
                "group_label": entry["group"]["group_label"],
                "group_kind": entry["group"]["group_kind"],
                "query_count": entry["query_count"],
                "first_query_utc": entry["first_query_utc"],
                "last_query_utc": entry["last_query_utc"],
                "known_list_match": entry["known_list_match"],
                "model_proposal": entry["model_proposal"],
                "rule_id": rule.get("rule_id"),
                "saved_state": analysis.get("state"),
                "saved_role": analysis.get("role"),
                "proposed_service": analysis.get("service"),
                "unknown_reason_code": analysis.get("reason"),
                "analysis_id": analysis.get("analysis_id"),
                "analysis_created_utc": analysis.get("created_utc"),
                "household_scope": "household scope; device unknown",
            }
        )
    window = projection["window"]
    namespace = projection["namespace"]
    metadata = {
        "export_schema_version": 1,
        "snapshot_id": projection["snapshot_id"],
        "window": {
            "start_utc": window["start_utc"],
            "end_utc": window["end_utc"],
            "start_epoch": window["start_epoch"],
            "end_epoch": window["end_epoch"],
            "timezone": window.get("timezone"),
        },
        "namespace_revision": namespace.get("revision"),
        "namespace_sha256": namespace.get("sha256"),
        "fingerprint": projection["fingerprint"],
        "filters": {"basis": basis, "group": group, "role": role},
    }
    return {
        "metadata": metadata,
        "counts": dict(projection["counts"]),
        "limitations": list(projection["limitations"]),
        "rows": rows,
        "timeline": {
            "bin_seconds": projection["timeline"]["bin_seconds"],
            "start_epoch": projection["timeline"]["start_epoch"],
            "end_epoch": projection["timeline"]["end_epoch"],
            "bins": [
                {
                    key: bin_[key]
                    for key in ("index", "start_epoch", "end_epoch", "start_utc", "rows", "domains")
                }
                for bin_ in projection["timeline"]["bins"]
            ],
        },
    }


class ReviewError(ValueError):
    """A proposed gaming association is unsupported and must not be stored."""


#: Labels that name a generic service rather than a specific game or platform. A
#: human review must identify a concrete association; these do not qualify.
_GENERIC_SERVICE_LABELS = frozenset(
    {
        "game",
        "gaming",
        "game client",
        "gaming service",
        "game unknown",
        "unknown",
        "unspecified",
    }
)


def validate_review_proposal(
    *,
    hostname: str,
    group_id: str,
    group_label: str,
    group_kind: str,
    review_note: str,
    match: str = "exact",
) -> dict[str, str]:
    """Validate one human review of an exact observed name.

    Human review proposes a specific exact-host association with an evidence note.
    It never creates a broadening suffix rule (publisher/CDN overreach) and never
    promotes a generic AI service label into a specific gaming association. The
    returned rule carries the exact observed hostname as its namespace and the
    evidence note as its provenance, so reviewed rules stay distinguishable from
    model proposals.
    """
    if match != "exact":
        raise ReviewError("Human review proposes exact observed names, never broadening suffixes")
    try:
        host = _host_name(hostname)
    except GamingDataError as error:
        raise ReviewError(f"Not a usable exact hostname: {error}") from error
    if group_kind not in {"game", "platform"}:
        raise ReviewError("A reviewed association needs a game or platform kind")
    if not _GROUP_ID.fullmatch(group_id):
        raise ReviewError("A reviewed association needs a valid group ID")
    label = group_label.strip()
    if not label or len(label) > MAX_GROUP_TEXT_LENGTH:
        raise ReviewError("A reviewed association needs a specific group label")
    if label.lower() in _GENERIC_SERVICE_LABELS or "game unknown" in label.lower():
        raise ReviewError("A generic service label is not a specific gaming association")
    note = review_note.strip()
    if not note:
        raise ReviewError("A reviewed association needs an evidence note")
    rule_id = f"review-{hashlib.sha256(host.encode()).hexdigest()[:12]}"
    return {
        "rule_id": rule_id,
        "namespace": host,
        "match": match,
        "group_id": group_id,
        "group_label": label,
        "group_kind": group_kind,
        "review_note": note,
    }
