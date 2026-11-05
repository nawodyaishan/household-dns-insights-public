"""Frozen campaign gaming reports from identified local evidence only.

No source reads, providers or web permissions live here. The report worker pins a
bounded selection, reads one consistent private database view, then stores only
the allowlisted household projection; legacy snapshot reports remain untouched.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from .campaign import SETTLING_GRACE_SECONDS, coverage_summary, covered_local_days
from .gaming import (
    NamespaceList,
    _timeline,
    load_namespace_list,
    match_namespace,
    validate_review_proposal,
)
from .reporting import QTYPE, REPLY, STATUS, utc
from .storage import StorageError, Store

INTERPRETATION_VERSION = 1
MAX_REPORT_SECONDS = 120 * 3600
REPORT_DEADLINE_SECONDS = 600
JOB_LEASE_SECONDS = 660

#: Plain-language endpoint purpose vocabulary (spec R12). A destination's game or
#: platform identity and its endpoint purpose are independent: either can be
#: unknown without the other. The model's internal role is mapped here so the
#: frozen projection and its exports share one bounded, human-readable set.
PURPOSE_BY_ROLE = {
    "downloads_updates": "update",
    "launcher": "launcher",
    "authentication": "authentication",
    "telemetry": "telemetry",
    "discovery_connectivity": "storefront",
    "gameplay_matchmaking": "gameplay/matchmaking-related",
    "shared_infrastructure": "shared infrastructure",
    "unknown": "unknown",
}

#: Trailing report windows clipped to the selected campaign's settled data.
TRAILING_HOURS = (24, 48)


class CampaignReportError(ValueError):
    """A requested report is unavailable or has an unsupported selection."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _moment(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _saved_results(results: list[dict], domains: set[str]) -> dict[str, dict]:
    """Only newest locally saved grounded gameplay per matching exact name."""
    selected: dict[str, dict] = {}
    for saved in results:
        domain = str(saved.get("domain") or "").lower().rstrip(".")
        if domain not in domains or domain in selected:
            continue
        try:
            result = json.loads(str(saved.get("result_json") or ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(result, dict) or result.get("source") != "model":
            continue
        # The newest result wins even when it no longer qualifies; do not revive
        # an older proposal that has since been marked unknown.
        evidence_ids = result.get("evidence_ids")
        source_hashes = result.get("source_hashes")
        grounded = (
            isinstance(evidence_ids, list)
            and bool(evidence_ids)
            and isinstance(source_hashes, dict)
            and all(isinstance(item, str) and item in source_hashes for item in evidence_ids)
            and result.get("grounding_contract_version") in (1, 2)
        )
        selected[domain] = {
            "state": "model_proposal"
            if result.get("verification_state") == "ai_grounded"
            and result.get("role") == "gameplay_matchmaking"
            and result.get("service")
            and grounded
            else "ineligible",
            "role": result.get("role"),
            "service": result.get("service"),
            "analysis_id": saved.get("analysis_id"),
            "created_utc": saved.get("created_utc"),
            "result_sha256": _digest(result),
        }
    return selected


def _selection(inputs: dict, *, start: int, end: int, now: int) -> dict:
    campaign = inputs["campaign"]
    if not int(campaign["start_epoch"]) <= start < end <= int(campaign["end_epoch"]):
        raise CampaignReportError("Report bounds leave the recorded campaign")
    if end - start > MAX_REPORT_SECONDS:
        raise CampaignReportError("Campaign report cannot exceed 120 hours")
    if end > now - SETTLING_GRACE_SECONDS:
        raise CampaignReportError("The selected end has not settled")
    chunks = [
        chunk
        for chunk in inputs["chunks"]
        if int(chunk["start_epoch"]) < end and int(chunk["end_epoch"]) > start
    ]
    queries = [
        record for record in inputs["queries"] if start <= float(record["row"]["timestamp"]) < end
    ]
    registered = set(inputs.get("registered_generations") or ())
    unknown_generations = sorted({str(record["generation_id"]) for record in queries} - registered)
    if unknown_generations:
        raise CampaignReportError("Report spans an unknown source generation")
    revisions = [
        revision
        for revision in inputs["revisions"]
        if any(revision["chunk_id"] == chunk["chunk_id"] for chunk in chunks)
    ]
    domains = {str(record["row"]["domain"]).lower().rstrip(".") for record in queries}
    saved = _saved_results(inputs["analyses"], domains)
    key_source = {
        "interpretation": INTERPRETATION_VERSION,
        "bounds": [start, end],
        "rules": inputs["rules"]["rules_sha256"],
        "coverage": [
            {
                field: chunk[field]
                for field in (
                    "chunk_id",
                    "start_epoch",
                    "end_epoch",
                    "state",
                    "import_utc",
                    "reconciled_utc",
                    "artifact_digest",
                    "generation_id",
                )
            }
            for chunk in chunks
        ],
        "revisions": [
            (item["chunk_id"], item["artifact_digest"], item["state"]) for item in revisions
        ],
        "queries": [
            (record["generation_id"], record["source_id"], record["row"]) for record in queries
        ],
        "saved": saved,
    }
    return {
        "chunks": chunks,
        "queries": queries,
        "revisions": revisions,
        "saved": saved,
        "fingerprint": _digest(key_source),
        "coverage_sha256": _digest(key_source["coverage"]),
        "capture_revisions": [
            f"{item['chunk_id']}:{item['artifact_digest']}" for item in revisions
        ],
    }


def _project(
    inputs: dict,
    selection: dict,
    *,
    start: int,
    end: int,
    now: int,
    requested_start: int | None = None,
    requested_end: int | None = None,
) -> dict:
    campaign = inputs["campaign"]
    rules_document = inputs["rules"]
    rules = json.loads(rules_document["rules_json"])
    namespace = NamespaceList(
        "available", rules_document["revision"], rules_document["rules_sha256"], tuple(rules)
    )
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in selection["queries"]:
        row = record["row"]
        groups[str(row["domain"]).lower().rstrip(".")].append(row)
    entries = []
    selected_rows = []
    for domain, rows in groups.items():
        if domain.endswith(".arpa"):
            continue
        known = match_namespace(domain, namespace.rules)
        saved = selection["saved"].get(domain)
        model = bool(saved and saved["state"] == "model_proposal")
        if not known and not model:
            continue
        selected_rows.extend(rows)
        entries.append(
            {
                "domain": domain,
                "query_count": len(rows),
                "first_query_utc": utc(min(float(row["timestamp"]) for row in rows)),
                "last_query_utc": utc(max(float(row["timestamp"]) for row in rows)),
                "query_types": dict(
                    Counter(
                        QTYPE.get(row.get("type"), f"TYPE_ID_{row.get('type')}") for row in rows
                    )
                ),
                "statuses": dict(
                    Counter(
                        STATUS.get(row.get("status"), f"STATUS_ID_{row.get('status')}")
                        for row in rows
                    )
                ),
                "dns_replies": dict(
                    Counter(
                        REPLY.get(row.get("reply_type"), f"REPLY_ID_{row.get('reply_type')}")
                        for row in rows
                    )
                ),
                "known_list_match": bool(known),
                "known_rule": {"rule_id": known["rule_id"], "match": known["match"]}
                if known
                else None,
                "model_proposal": model,
                "purpose": (
                    PURPOSE_BY_ROLE.get(str((saved or {}).get("role")), "unknown")
                    if model
                    else "unknown"
                ),
                "analysis": {
                    key: saved.get(key)
                    for key in ("state", "role", "service", "analysis_id", "created_utc")
                }
                if model
                else None,
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
    entries.sort(key=lambda entry: (-entry["query_count"], entry["domain"]))
    relevant = [
        {
            **chunk,
            "start_epoch": max(start, int(chunk["start_epoch"])),
            "end_epoch": min(end, int(chunk["end_epoch"])),
        }
        for chunk in selection["chunks"]
    ]
    coverage = coverage_summary(relevant, campaign_start=start, campaign_end=end, now_epoch=now)
    coverage["fully_resolved"] = bool(
        coverage["fully_resolved"] and coverage["reconciliation_pending"] == 0
    )
    capture_times = [str(chunk["captured_utc"]) for chunk in relevant if chunk["captured_utc"]]
    import_times = [str(chunk["import_utc"]) for chunk in relevant if chunk["import_utc"]]
    return {
        "schema_version": 1,
        "campaign_id": campaign["campaign_id"],
        "window": {
            "start_epoch": start,
            "end_epoch": end,
            "start_utc": utc(start),
            "end_utc": utc(end),
            "requested_start": requested_start if requested_start is not None else start,
            "requested_end": requested_end if requested_end is not None else end,
            "actual_start": start,
            "actual_end": end,
            "timezone": campaign["timezone"],
        },
        "namespace": {
            "state": "available",
            "revision": namespace.revision,
            "sha256": namespace.sha256,
            "rule_count": len(namespace.rules),
            "empty_acknowledged": bool(rules_document["rules_ack"]) and not rules,
        },
        "entries": entries,
        "counts": {
            "snapshot_rows": len(selection["queries"]),
            "snapshot_domains": len(groups),
            "eligible_rows": len(selected_rows),
            "eligible_domains": len(entries),
            "known_list_domains": sum(item["known_list_match"] for item in entries),
            "model_domains": sum(item["model_proposal"] for item in entries),
            "known_model_overlap_domains": sum(
                item["known_list_match"] and item["model_proposal"] for item in entries
            ),
            "reverse_rows": sum(
                len(rows)
                for domain, rows in groups.items()
                if domain.endswith((".in-addr.arpa", ".ip6.arpa"))
            ),
            "not_selected_rows": len(selection["queries"]) - len(selected_rows),
            "unknown_or_unmatched_rows": len(selection["queries"]) - len(selected_rows),
            "unknown_or_unmatched_domains": len(groups) - len(entries),
            "protocol_rows": sum(
                len(rows)
                for domain, rows in groups.items()
                if domain.endswith(".arpa") and not domain.endswith((".in-addr.arpa", ".ip6.arpa"))
            ),
        },
        "timeline": _timeline(selected_rows, start_epoch=start, end_epoch=end),
        "coverage": coverage,
        "freshness": {
            "last_capture_utc": max(capture_times, default=None),
            "last_import_utc": max(import_times, default=None),
        },
        "rules_sha256": namespace.sha256,
        "coverage_sha256": selection["coverage_sha256"],
        "result_fingerprint": _digest(selection["saved"]),
        "fingerprint": selection["fingerprint"],
        "household_scope": "household scope; device unknown",
        "limitations": [
            "DNS queries are not connections, gameplay, device use or play duration.",
            "Only resolver-visible rows are represented; gaps and quiet bins are not inactivity.",
            "Saved model proposals are not independently verified.",
        ],
    }


class CampaignReportService:
    """Local durable request/worker/read boundary for one frozen projection."""

    def __init__(
        self,
        store: Store,
        *,
        now: Callable[[], int] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.store = store
        self.now = now or (lambda: int(time.time()))
        self.monotonic = monotonic

    def now_utc(self) -> str:
        return _moment(int(self.now()))

    def pin_rules(self, campaign_id: str, raw: bytes, *, ack_empty: bool = False) -> str:
        namespace = load_namespace_list(raw)
        if namespace.state != "available" or (not namespace.rules and not ack_empty):
            raise CampaignReportError("Reviewed rules or an explicit empty acknowledgment required")
        self.store.pin_campaign_report_rules(
            campaign_id,
            sha256=namespace.sha256,
            revision=namespace.revision,
            rules=namespace.rules,
            ack_empty=ack_empty,
            now_utc=_moment(self.now()),
        )
        return str(namespace.sha256)

    def review_association(
        self,
        campaign_id: str,
        *,
        hostname: str,
        group_id: str,
        group_label: str,
        group_kind: str,
        review_note: str,
        author: str = "owner",
    ) -> dict[str, object]:
        """Record one human review of an exact observed name as a rule revision.

        The proposal is validated (exact host only, no publisher/CDN broadening, no
        generic service label), merged into the current reviewed rules, and pinned as
        a new revision with an audited provenance event. Reviewed rules stay distinct
        from model proposals, which are never auto-promoted here.
        """
        rule = validate_review_proposal(
            hostname=hostname,
            group_id=group_id,
            group_label=group_label,
            group_kind=group_kind,
            review_note=review_note,
        )
        inputs = self.store.campaign_report_inputs(campaign_id)
        current = json.loads(inputs["rules"]["rules_json"])
        merged = [
            item
            for item in current
            if not (
                item.get("namespace") == rule["namespace"] and item.get("match") == rule["match"]
            )
        ]
        merged.append(rule)
        merged.sort(key=lambda item: (item["match"], item["namespace"], item["rule_id"]))
        reviews = [
            event
            for event in self.store.owner_events(campaign_id)
            if event["action"] == "gaming_association_review"
        ]
        revision = f"reviewed-{len(reviews) + 1}"
        document = {"schema_version": 1, "revision": revision, "rules": merged}
        raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        namespace = load_namespace_list(raw)
        self.store.pin_campaign_report_rules(
            campaign_id,
            sha256=namespace.sha256,
            revision=namespace.revision,
            rules=namespace.rules,
            ack_empty=False,
            now_utc=_moment(int(self.now())),
        )
        self.store.record_owner_event(
            campaign_id,
            action="gaming_association_review",
            detail=json.dumps(
                {
                    "author": author,
                    "hostname": rule["namespace"],
                    "group_id": rule["group_id"],
                    "group_label": rule["group_label"],
                    "group_kind": rule["group_kind"],
                    "review_note": rule["review_note"],
                    "rule_id": rule["rule_id"],
                    "revision": revision,
                },
                sort_keys=True,
            ),
            now_utc=_moment(int(self.now())),
        )
        return rule

    def _bounds(
        self, inputs: dict, day: str | None, hours: int | None, now: int
    ) -> tuple[int, int, int, int]:
        """Resolve requested and actual report bounds, both half-open UTC.

        Returns ``(requested_start, requested_end, actual_start, actual_end)``.
        The requested span is what the visitor selected; the actual span is the
        settled, importable window actually projected. For a completed local day
        the two coincide; otherwise the actual end clips to the latest elapsed
        chunk and trailing windows clip to the campaign's settled data.
        """
        campaign = inputs["campaign"]
        lower, upper = int(campaign["start_epoch"]), int(campaign["end_epoch"])
        if day is not None:
            try:
                chosen = date.fromisoformat(day)
                if chosen.isoformat() != day:
                    raise ValueError("Noncanonical day")
            except ValueError as error:
                raise CampaignReportError("Use an available ISO local calendar day") from error
            spans = covered_local_days(lower, upper, str(campaign["timezone"]))
            selected = [
                span
                for span in spans
                if datetime.fromtimestamp(span[0], tz=ZoneInfo(campaign["timezone"])).date()
                == chosen
            ]
            if not selected or selected[0][1] > now - SETTLING_GRACE_SECONDS:
                raise CampaignReportError("The selected local day is not complete and settled")
            day_start, day_end = selected[0]
            return day_start, day_end, day_start, day_end
        if hours is not None and hours not in TRAILING_HOURS:
            raise CampaignReportError("A trailing window must be 24 or 48 hours")
        requested_end = min(now - SETTLING_GRACE_SECONDS, upper)
        requested_start = max(lower, requested_end - hours * 3600) if hours is not None else lower
        settled = [
            int(chunk["end_epoch"])
            for chunk in inputs["chunks"]
            if int(chunk["end_epoch"]) <= requested_end and int(chunk["end_epoch"]) <= upper
        ]
        if not settled:
            raise CampaignReportError("No closed, settled campaign window is available yet")
        actual_end = max(settled)
        actual_start = (
            max(requested_start, actual_end - hours * 3600)
            if hours is not None
            else requested_start
        )
        return requested_start, requested_end, actual_start, actual_end

    def request(
        self,
        campaign_id: str,
        *,
        day: str | None = None,
        hours: int | None = None,
        start_epoch: int | None = None,
    ) -> str:
        if start_epoch is not None:
            raise CampaignReportError("Visitors cannot choose arbitrary report bounds")
        if hours is not None and hours not in TRAILING_HOURS:
            raise CampaignReportError("A trailing window must be 24 or 48 hours")
        now = int(self.now())
        inputs = self.store.campaign_report_inputs(campaign_id)
        requested_start, requested_end, start, end = self._bounds(inputs, day, hours, now)
        state = _selection(inputs, start=start, end=end, now=now)
        key = _digest(
            {
                "campaign": campaign_id,
                "window": [start, end],
                "requested": [requested_start, requested_end],
                "fingerprint": state["fingerprint"],
            }
        )
        job_id, _ = self.store.create_job(
            job_id=f"job-{secrets.token_hex(12)}",
            campaign_id=campaign_id,
            kind="report",
            dedup_key=key,
            params={
                "start": start,
                "end": end,
                "requested_start": requested_start,
                "requested_end": requested_end,
                "day": day,
                "hours": hours,
                "fingerprint": state["fingerprint"],
                "dedup_key": key,
            },
            now_utc=_moment(now),
        )
        return job_id

    def run_next(
        self, campaign_id: str, *, max_seconds: int = REPORT_DEADLINE_SECONDS
    ) -> str | None:
        if not 1 <= max_seconds <= REPORT_DEADLINE_SECONDS:
            raise CampaignReportError("Report deadline must be between 1 and 600 seconds")
        now = int(self.now())
        self.store.fail_exhausted_report_jobs(now_utc=_moment(now))
        pending = self.store.pending_jobs(campaign_id, kind="report", now_utc=_moment(now))
        if not pending:
            return None
        job_id = str(pending[0]["job_id"])
        token, claimed = self.store.claim_job(
            job_id, worker="campaign-report", lease_seconds=JOB_LEASE_SECONDS, now_utc=_moment(now)
        )
        if not claimed:
            return None
        deadline = self.monotonic() + max_seconds
        try:
            params = json.loads(self.store.job(job_id)["params_json"])
            start, end = int(params["start"]), int(params["end"])
            requested_start = int(params.get("requested_start", start))
            requested_end = int(params.get("requested_end", end))
            inputs = self.store.campaign_report_inputs(campaign_id)
            state = _selection(inputs, start=start, end=end, now=now)
            dedup_key = str(params.get("dedup_key") or state["fingerprint"])
            if state["fingerprint"] != params.get("fingerprint"):
                raise CampaignReportError(
                    "Report inputs changed since request; request a new revision"
                )
            if not any(
                chunk["state"] in ("imported", "successful_empty", "partial")
                for chunk in state["chunks"]
            ):
                raise CampaignReportError("No trustworthy imported source state yet")
            if self.monotonic() >= deadline:
                raise CampaignReportError("Report deadline exceeded before projection")
            payload = _project(
                inputs,
                state,
                start=start,
                end=end,
                now=now,
                requested_start=requested_start,
                requested_end=requested_end,
            )
            if self.monotonic() >= deadline:
                payload["coverage"]["deadline_reached"] = True
                payload["coverage"]["fully_resolved"] = False
            campaign = inputs["campaign"]
            # An active campaign can still be extended within 120 elapsed hours.
            # The stored bound must never precede its eventual completion-based
            # retention date. B4 must check the *current* campaign expiry for
            # anonymous access, not this conservative private metadata bound.
            expires = _moment(
                int(campaign["start_epoch"])
                + MAX_REPORT_SECONDS
                + int(campaign["retention_days"]) * 86400
            )
            report_id = self.store.finish_campaign_report(
                job_id=job_id,
                token=token,
                report_id=f"report-{secrets.token_hex(12)}",
                campaign_id=campaign_id,
                requested_start=requested_start,
                requested_end=requested_end,
                actual_start=start,
                actual_end=end,
                dedup_key=dedup_key,
                rules_sha256=inputs["rules"]["rules_sha256"],
                coverage_sha256=state["coverage_sha256"],
                capture_revisions=state["capture_revisions"],
                payload=payload,
                expires_utc=expires,
                now_utc=_moment(int(self.now())),
            )
            return report_id
        except (CampaignReportError, StorageError, ValueError, TypeError, KeyError):
            self.store.finish_job(
                job_id,
                token=token,
                state="failed",
                sanitized_error="Report generation could not complete",
                now_utc=_moment(int(self.now())),
            )
            return None

    def job_status(self, job_id: str) -> dict:
        job = self.store.job(job_id)
        return {
            "job_id": job_id,
            "campaign_id": job["campaign_id"],
            "state": job["state"],
            "report_id": self.store.campaign_job_result(job_id),
            "error": job["sanitized_error"],
        }

    def run_next_any(self, *, max_seconds: int = REPORT_DEADLINE_SECONDS) -> str | None:
        """Run one local report, including for a completed inactive campaign."""
        self.store.fail_exhausted_report_jobs(now_utc=self.now_utc())
        for campaign in self.store.campaigns():
            if self.store.pending_jobs(
                campaign["campaign_id"], kind="report", now_utc=self.now_utc()
            ):
                return self.run_next(campaign["campaign_id"], max_seconds=max_seconds)
        return None

    def get(self, report_id: str) -> dict:
        return json.loads(self.store.frozen_report(report_id)["payload_json"])

    def export_json(
        self, report_id: str, *, basis: str = "all", group: str = "", role: str = ""
    ) -> dict:
        if basis not in {"all", "known_list", "model"} or len(group) > 64 or len(role) > 64:
            raise CampaignReportError("Unsupported frozen export filter")
        payload = self.get(report_id)
        rows = []
        for entry in payload["entries"]:
            analysis = entry.get("analysis") or {}
            rule = entry.get("known_rule") or {}
            rows.append(
                {
                    "domain": entry["domain"],
                    "query_count": entry["query_count"],
                    "group_id": entry["group"]["group_id"],
                    "group_label": entry["group"]["group_label"],
                    "group_kind": entry["group"]["group_kind"],
                    "first_query_utc": entry["first_query_utc"],
                    "last_query_utc": entry["last_query_utc"],
                    "known_list_match": entry["known_list_match"],
                    "model_proposal": entry["model_proposal"],
                    "purpose": entry["purpose"],
                    "rule_id": rule.get("rule_id"),
                    "saved_state": analysis.get("state"),
                    "saved_role": analysis.get("role"),
                    "proposed_service": analysis.get("service"),
                    "household_scope": payload["household_scope"],
                }
            )
        rows = [
            row
            for row in rows
            if (
                basis == "all"
                or (basis == "known_list" and row["known_list_match"])
                or (basis == "model" and row["model_proposal"])
            )
            and (not group or row["group_id"] == group)
            and (not role or (row["saved_role"] or "unknown") == role)
        ]
        return {
            "metadata": {
                "schema_version": 1,
                "report_id": report_id,
                "campaign_id": payload["campaign_id"],
                "window": payload["window"],
                "namespace": payload["namespace"],
                "fingerprint": payload["fingerprint"],
                "coverage_sha256": payload["coverage_sha256"],
                "revision": payload.get("revision"),
                "predecessor_report_id": payload.get("predecessor_report_id"),
            },
            "counts": {
                **payload["counts"],
                "matched_domains": len(rows),
                "matched_rows": sum(row["query_count"] for row in rows),
            },
            "coverage": payload["coverage"],
            "limitations": payload["limitations"],
            "rows": rows,
            "timeline": payload["timeline"],
        }

    def export_csv(
        self, report_id: str, *, basis: str = "all", group: str = "", role: str = ""
    ) -> str:
        document = self.export_json(report_id, basis=basis, group=group, role=role)
        fields = (
            "domain",
            "query_count",
            "group_id",
            "group_label",
            "group_kind",
            "first_query_utc",
            "last_query_utc",
            "known_list_match",
            "model_proposal",
            "purpose",
            "rule_id",
            "saved_state",
            "saved_role",
            "proposed_service",
            "household_scope",
            "report_id",
            "fingerprint",
            "eligible_rows",
            "unknown_or_unmatched_rows",
            "unresolved_chunks",
            "fully_resolved",
            "window_start_utc",
            "window_end_utc",
            "namespace_sha256",
        )
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in document["rows"]:
            values = {
                **row,
                "report_id": report_id,
                "fingerprint": document["metadata"]["fingerprint"],
                "eligible_rows": document["counts"]["eligible_rows"],
                "unknown_or_unmatched_rows": document["counts"]["unknown_or_unmatched_rows"],
                "unresolved_chunks": document["coverage"]["unresolved_chunks"],
                "fully_resolved": document["coverage"]["fully_resolved"],
                "window_start_utc": document["metadata"]["window"]["start_utc"],
                "window_end_utc": document["metadata"]["window"]["end_utc"],
                "namespace_sha256": document["metadata"]["namespace"]["sha256"],
            }
            writer.writerow(
                {
                    key: "'" + value
                    if isinstance(value, str)
                    and value.lstrip(" \t\r\n\x00\x1b").startswith(("=", "+", "-", "@"))
                    else value
                    for key, value in values.items()
                }
            )
        return output.getvalue()
