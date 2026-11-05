#!/usr/bin/env python3
"""Typed campaign control and worker operations for the offline application.

Control commands start/finish/extend/finalize campaigns and plan capture windows.
Worker commands claim and acknowledge typed work (settled capture chunks, report
jobs). A claim returns only validated IDs, UTC bounds and a lease token; nothing
here executes a shell, talks to Docker or reads the resolver. The supervised host
bridge (built in batch B2) drives the worker commands.

All output is JSON and sanitized: IDs, bounds, states and counts only. No namespace
rule content, domains, credentials or raw evidence is ever printed.

    uv run --project destination-report python destination-report/tools/campaign_cli.py \
        --db /path/app.sqlite3 start --days 3 --retention 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path

from household_report.campaign import CampaignError, CampaignService
from household_report.campaign_reporting import CampaignReportService
from household_report.capture_contract import validate_campaign_snapshot
from household_report.storage import StorageError, open_store


def _emit(payload: object) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db",
        default=os.environ.get("HR_DATABASE", ""),
        help="SQLite database path (or set HR_DATABASE)",
    )
    parser.add_argument(
        "--now",
        type=int,
        default=None,
        help="fake epoch clock; synthetic offline verification only",
    )
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument(
        "--namespace",
        default=os.environ.get("HR_NAMESPACE_FILE", ""),
        help="reviewed gaming-namespaces.json path (or set HR_NAMESPACE_FILE)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start the one active campaign")
    start.add_argument("--days", type=int, default=None, choices=[3, 4, 5])
    start.add_argument("--retention", dest="retention_days", type=int, default=None)
    start.add_argument("--ack-empty", action="store_true")
    start.add_argument("--generation", help="verify this generation before starting")
    start.add_argument("--identity", help="verify this identity before starting")
    start.set_defaults(handler="start")

    status = sub.add_parser("status", help="sanitized campaign status")
    status.add_argument("--campaign", help="ID; omitted selects active/finalizing")
    status.set_defaults(handler="status")
    sub.add_parser("worker-status", help="active campaign or explicit inactive state").set_defaults(
        handler="worker_status"
    )
    sub.add_parser("campaigns", help="sanitized headers of every campaign").set_defaults(
        handler="campaigns"
    )
    finish = sub.add_parser("finish", help="owner early finish clips the end")
    finish.add_argument("--campaign")
    finish.set_defaults(handler="finish")

    extend = sub.add_parser("extend", help="extend while active, capped by start + 120h")
    extend.add_argument("--hours", type=int, required=True)
    extend.add_argument("--campaign")
    extend.set_defaults(handler="extend")

    finalize = sub.add_parser("finalize", help="bounded finalization after the end")
    finalize.add_argument("--campaign")
    finalize.set_defaults(handler="finalize")

    plan = sub.add_parser("plan", help="plan prospective capture windows")
    plan.add_argument("--campaign")
    plan.set_defaults(handler="plan")

    claim = sub.add_parser(
        "claim-chunk", help="claim up to N settled capture windows (typed worker work)"
    )
    claim.add_argument("--campaign")
    claim.add_argument("--worker", default="operator")
    claim.add_argument("--limit", type=int, default=10)
    claim.add_argument("--generation", help="operator-registered source generation")
    claim.set_defaults(handler="claim_chunk")

    ack_captured = sub.add_parser("chunk-captured", help="acknowledge one extraction result")
    ack_captured.add_argument("--chunk", required=True)
    ack_captured.add_argument("--token", required=True)
    ack_captured.add_argument("--digest")
    ack_captured.add_argument("--path")
    ack_captured.add_argument("--campaign")
    ack_captured.set_defaults(handler="chunk_captured")

    ack_failed = sub.add_parser("chunk-failed", help="acknowledge one failed extraction")
    ack_failed.add_argument("--chunk", required=True)
    ack_failed.add_argument("--token", required=True)
    ack_failed.add_argument("--reason")
    ack_failed.add_argument("--campaign")
    ack_failed.set_defaults(handler="chunk_failed")

    import_pending = sub.add_parser(
        "chunk-import-pending", help="move one artifact to the import queue"
    )
    import_pending.add_argument("--chunk", required=True)
    import_pending.add_argument("--campaign")
    import_pending.set_defaults(handler="chunk_import_pending")

    imported = sub.add_parser("chunk-imported", help="acknowledge one import result")
    imported.add_argument("--chunk", required=True)
    imported.add_argument(
        "--outcome", choices=["imported", "successful_empty", "partial", "failed"]
    )
    imported.add_argument("--reason")
    imported.add_argument("--campaign")
    imported.set_defaults(handler="chunk_imported")

    generation = sub.add_parser("source-register", help="pin operator source generation")
    generation.add_argument("--generation", required=True)
    generation.add_argument("--identity", required=True)
    generation.set_defaults(handler="source_register")

    check = sub.add_parser(
        "source-check", help="read-only configured generation/identity comparison"
    )
    check.add_argument("--generation", required=True)
    check.add_argument("--identity", required=True)
    check.set_defaults(handler="source_check")

    bridge_status = sub.add_parser("bridge-status", help="read-only sanitized collector health")
    bridge_status.add_argument(
        "--status-file",
        default=os.environ.get("HR_BRIDGE_STATUS_FILE", "/state/bridge-status.json"),
    )
    bridge_status.set_defaults(handler="bridge_status")

    pending = sub.add_parser("pending-artifacts", help="bounded import and reconciliation work")
    pending.add_argument("--campaign")
    pending.add_argument("--limit", type=int, default=10)
    pending.set_defaults(handler="pending_artifacts")

    artifact = sub.add_parser("import-artifact", help="verify and import a confined capture")
    artifact.add_argument("--campaign", required=True)
    artifact.add_argument("--chunk", required=True)
    artifact.add_argument("--name", required=True)
    artifact.add_argument("--digest", required=True)
    artifact.add_argument("--reconcile", action="store_true")
    artifact.set_defaults(handler="import_artifact")

    attempts = sub.add_parser("attempt-artifacts", help="sanitized retry artifact identities")
    attempts.add_argument("--campaign", required=True)
    attempts.add_argument("--chunk", required=True)
    attempts.set_defaults(handler="attempt_artifacts")

    report_request = sub.add_parser("report-request", help="queue bounded local report")
    report_request.add_argument("--campaign", required=True)
    report_request.add_argument("--day", help="completed local day YYYY-MM-DD")
    report_request.set_defaults(handler="report_request")
    report_run = sub.add_parser("report-run", help="run one local report job without source reads")
    report_run.add_argument("--campaign", help="optional campaign ID; otherwise oldest pending")
    report_run.add_argument("--max-seconds", type=int, default=600)
    report_run.set_defaults(handler="report_run")
    report_status = sub.add_parser("report-status", help="sanitized durable job status")
    report_status.add_argument("--job", required=True)
    report_status.set_defaults(handler="report_status")
    report_rules = sub.add_parser("report-rules", help="owner pin reviewed new report rules")
    report_rules.add_argument("--campaign", required=True)
    report_rules.add_argument("--file", type=Path, required=True)
    report_rules.add_argument("--ack-empty", action="store_true")
    report_rules.set_defaults(handler="report_rules")

    job_create = sub.add_parser("job-create", help="create one deduplicated report job")
    job_create.add_argument("--campaign")
    job_create.add_argument("--dedup", required=True)
    job_create.add_argument("--params", default="{}")
    job_create.set_defaults(handler="job_create")

    job_claim = sub.add_parser("job-claim", help="claim the next pending report job")
    job_claim.add_argument("--campaign")
    job_claim.add_argument("--worker", default="operator")
    job_claim.set_defaults(handler="job_claim")

    job_finish = sub.add_parser("job-finish", help="acknowledge a running report job")
    job_finish.add_argument("--job", required=True)
    job_finish.add_argument("--token", required=True)
    job_finish.add_argument("--state", choices=["ready", "failed"], required=True)
    job_finish.add_argument("--error")
    job_finish.set_defaults(handler="job_finish")

    args = parser.parse_args(argv)
    if not args.db:
        parser.error("--db is required (or set HR_DATABASE)")
    try:
        with open_store(args.db) as store:
            service = CampaignService(
                store,
                now=(lambda: int(args.now)) if args.now is not None else None,
                timezone=args.timezone,
                namespace_path=Path(args.namespace).expanduser() if args.namespace else None,
            )
            return _dispatch(service, args, store)
    except CampaignError as error:
        print(json.dumps({"error": str(error)}, indent=2, sort_keys=True))
        return 2
    except (OSError, ValueError, StorageError) as error:
        print(json.dumps({"error": type(error).__name__}, indent=2, sort_keys=True))
        return 2


def _dispatch(service: CampaignService, args: argparse.Namespace, store=None) -> int:
    handler = args.handler
    if handler == "start":
        if args.generation or args.identity:
            if not (args.generation and args.identity):
                raise CampaignError("Both --generation and --identity are required together")
            check = service.check_source_identity(
                generation_id=args.generation, identity=args.identity
            )
            if not check["verified"]:
                raise CampaignError(
                    f"Source identity check failed ({check['code']}); run source-register first"
                )
        return _emit(
            service.start(
                days=args.days, retention_days=args.retention_days, ack_empty=args.ack_empty
            )
        )
    if handler == "status":
        return _emit(service.status(args.campaign))
    if handler == "worker_status":
        current = store.current_unfinished()
        return _emit({"campaign": service.status(current["campaign_id"]) if current else None})
    if handler == "campaigns":
        return _emit(service.list_status())
    if handler == "finish":
        return _emit(service.finish_early(args.campaign))
    if handler == "extend":
        return _emit(service.extend(args.hours, args.campaign))
    if handler == "finalize":
        return _emit(service.finalize(args.campaign))
    if handler == "plan":
        return _emit({"chunks_planned": service.plan(args.campaign)})
    if handler == "claim_chunk":
        return _emit(
            {
                "claimed": service.claim_capture_work(
                    worker=args.worker,
                    campaign_id=args.campaign,
                    limit=args.limit,
                    generation_id=args.generation,
                )
            }
        )
    if handler == "chunk_captured":
        return _emit(
            {
                "acknowledged": service.ack_capture(
                    args.chunk,
                    token=args.token,
                    outcome="captured",
                    digest=args.digest,
                    path=args.path,
                    campaign_id=args.campaign,
                )
            }
        )
    if handler == "chunk_failed":
        return _emit(
            {
                "acknowledged": service.ack_capture(
                    args.chunk,
                    token=args.token,
                    outcome="failed",
                    gap_reason=args.reason,
                    campaign_id=args.campaign,
                )
            }
        )
    if handler == "chunk_import_pending":
        return _emit({"queued": service.mark_import_pending(args.chunk, campaign_id=args.campaign)})
    if handler == "chunk_imported":
        return _emit(
            {
                "acknowledged": service.ack_import(
                    args.chunk,
                    outcome=args.outcome,
                    gap_reason=args.reason,
                    campaign_id=args.campaign,
                )
            }
        )
    if handler == "source_register":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", args.generation):
            raise CampaignError("Invalid source generation identifier")
        store.register_source_generation(generation_id=args.generation, identity=args.identity)
        return _emit({"registered": args.generation})
    if handler == "source_check":
        return _emit(
            service.check_source_identity(generation_id=args.generation, identity=args.identity)
        )
    if handler == "bridge_status":
        from household_report.collector_status import collector_context, read_status

        path = Path(args.status_file).expanduser()
        record = read_status(path)
        current = store.current_unfinished()
        if current is None:
            try:
                headers = service.list_status()
            except Exception:  # noqa: BLE001 - no campaigns at all
                headers = []
            campaign_state = str(headers[0]["state"]) if headers else None
            coverage = None
        else:
            status = service.status(current["campaign_id"])
            campaign_state = str(status["state"])
            coverage = status.get("coverage")
        return _emit(
            collector_context(
                record,
                now_epoch=service.now_epoch(),
                campaign_state=campaign_state,
                campaign_complete=campaign_state in ("complete", "complete_with_gaps"),
                coverage=coverage,
            )
        )
    if handler == "pending_artifacts":
        if not 1 <= args.limit <= 10:
            raise CampaignError("Limit must be between 1 and 10")
        campaign = service._select(args.campaign)
        now = service.now_epoch()
        deadline = campaign["finalization_deadline"]
        return _emit(
            {
                "pending": [
                    {
                        "chunk_id": row["chunk_id"],
                        "campaign_id": campaign["campaign_id"],
                        "start_epoch": row["start_epoch"],
                        "end_epoch": row["end_epoch"],
                        "generation_id": row["generation_id"],
                        "state": row["state"],
                        "path": row["artifact_path"],
                        "digest": row["artifact_digest"],
                    }
                    for row in store.chunks(campaign["campaign_id"])
                    if row["end_epoch"] <= campaign["end_epoch"]
                    and (
                        row["state"] in ("captured", "import_pending")
                        or (
                            row["state"] in ("imported", "successful_empty")
                            and not row["reconciled_utc"]
                            and row["captured_utc"]
                            and now
                            >= int(
                                datetime.fromisoformat(
                                    row["captured_utc"].replace("Z", "+00:00")
                                ).timestamp()
                            )
                            + 600
                            and (deadline is None or now <= deadline)
                        )
                    )
                ][: args.limit]
            }
        )
    if handler == "import_artifact":
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}\.json", args.name):
            raise CampaignError("Invalid artifact name")
        if not re.fullmatch(r"[0-9a-f]{64}", args.digest):
            raise CampaignError("Invalid artifact digest")
        root = Path(os.environ.get("HR_INPUT_DIR", "/input"))
        if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o077:
            raise CampaignError("Input directory is not private")
        path = root / args.name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > 32 * 1024 * 1024:
                raise CampaignError("Invalid artifact type or size")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                raw = handle.read(32 * 1024 * 1024 + 1)
        finally:
            os.close(fd)
        if hashlib.sha256(raw).hexdigest() != args.digest:
            raise CampaignError("Artifact digest mismatch")
        snapshot = json.loads(raw)
        validate_campaign_snapshot(snapshot)
        chunk = store.chunk(args.campaign, args.chunk)
        if not args.reconcile and (
            chunk["artifact_path"] != args.name or chunk["artifact_digest"] != args.digest
        ):
            raise CampaignError("Artifact does not match the acknowledged capture")
        result = store.import_campaign_capture(
            args.campaign,
            chunk_id=args.chunk,
            generation_id=chunk["generation_id"],
            artifact_digest=args.digest,
            snapshot=snapshot,
            reconciled=args.reconcile,
        )
        return _emit({"state": result, "chunk_id": args.chunk})
    if handler == "attempt_artifacts":
        return _emit({"tokens": store.capture_attempt_tokens(args.campaign, args.chunk)})
    if handler in {"report_request", "report_run", "report_status", "report_rules"}:
        reports = CampaignReportService(store, now=service.now_epoch)
        if handler == "report_request":
            return _emit({"job_id": reports.request(args.campaign, day=args.day)})
        if handler == "report_run":
            if args.campaign:
                result = reports.run_next(args.campaign, max_seconds=args.max_seconds)
            else:
                result = reports.run_next_any(max_seconds=args.max_seconds)
            return _emit({"report_id": result})
        if handler == "report_status":
            return _emit(reports.job_status(args.job))
        if args.file.is_symlink() or not args.file.is_file() or args.file.stat().st_mode & 0o077:
            raise CampaignError("Reviewed rules file must be a private regular file")
        return _emit(
            {
                "rules_sha256": reports.pin_rules(
                    args.campaign, args.file.read_bytes(), ack_empty=args.ack_empty
                )
            }
        )
    if handler == "job_create":
        params = json.loads(args.params)
        return _emit(
            {
                "job_id": service.create_report_job(
                    dedup_key=args.dedup, params=params, campaign_id=args.campaign
                )
            }
        )
    if handler == "job_claim":
        return _emit(service.claim_report_job(worker=args.worker, campaign_id=args.campaign))
    if handler == "job_finish":
        return _emit(
            {
                "acknowledged": service.finish_report_job(
                    args.job, token=args.token, state=args.state, sanitized_error=args.error
                )
            }
        )
    raise AssertionError(f"Unhandled command: {handler}")


if __name__ == "__main__":
    sys.exit(main())
