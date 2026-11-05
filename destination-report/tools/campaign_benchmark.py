#!/usr/bin/env python3
"""Packaged synthetic 120-hour campaign and recovery benchmark.

This tool runs **inside the application image** against private temporary
directories. It uses the same storage, campaign and reporting services as the host
bridge and the owner CLI, with a deterministic fake clock and synthetic rows. It
never reads the resolver, Docker socket, household evidence or any network service.

Phase ``prepare`` starts one five-day campaign, acknowledges and imports 120 hourly
synthetic windows, generates one frozen to-date report, exports it, then finalizes
the campaign. Phase ``verify`` runs in a **separate process** after a restart,
re-checks the immutable report digest, generates one completed-day report, and
performs a private backup, verification and isolated restore.

Only counts, identifiers, byte sizes, elapsed seconds and resource totals are
printed. Synthetic domains and rule content never appear in the output.

    python tools/campaign_benchmark.py --db /state/benchmark.sqlite3 \
        --work-dir /state/benchmark prepare --hours 120 --rows-per-hour 120
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import secrets
import stat
import time
from datetime import UTC, datetime
from pathlib import Path

from household_report.campaign import (
    FINALIZATION_ALLOWANCE_SECONDS,
    SETTLING_GRACE_SECONDS,
    CampaignService,
)
from household_report.campaign_reporting import CampaignReportService
from household_report.campaign_retirement import CampaignRetirement
from household_report.storage import open_store

BENCH_START = 1_800_000_000
GENERATION = "bench-generation"
RULE = {
    "rule_id": "bench-rule",
    "namespace": "games.example",
    "match": "suffix",
    "group_id": "bench-group",
    "group_label": "Synthetic group",
    "group_kind": "platform",
    "review_note": "synthetic benchmark rule",
}


class Clock:
    def __init__(self, epoch: int) -> None:
        self.epoch = epoch

    def __call__(self) -> int:
        return int(self.epoch)


def _private(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise SystemExit(f"Private directory required: {path.name}")
    return path


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _bytes_under(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


def _database_bytes(store) -> int:
    page_count = store._conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = store._conn.execute("PRAGMA page_size").fetchone()[0]
    return int(page_count) * int(page_size)


def _json_export(reports: CampaignReportService, report_id: str) -> bytes:
    return json.dumps(reports.export_json(report_id), sort_keys=True, indent=2).encode()


def _resource() -> dict[str, float | int]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "peak_rss_kib": int(usage.ru_maxrss),
        "cpu_seconds": round(usage.ru_utime + usage.ru_stime, 3),
    }


def _synthetic_rows(start: int, end: int, count: int, first_id: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for offset in range(count):
        identifier = first_id + offset
        domain = (
            f"synthetic-{identifier}.games.example"
            if identifier % 2
            else f"synthetic-{identifier}.other.example"
        )
        rows.append(
            {
                "id": identifier,
                "timestamp": start + (offset % 3600),
                "type": 1,
                "status": 2,
                "domain": domain,
                "client": "synthetic-client",
                "reply_type": 4,
            }
        )
    return rows


def _namespace(work: Path) -> Path:
    path = work / "benchmark-namespaces.json"
    _write_private(
        path, json.dumps({"schema_version": 1, "revision": "bench-1", "rules": [RULE]}).encode()
    )
    return path


def prepare(args: argparse.Namespace) -> dict[str, object]:
    work = _private(args.work_dir)
    artifacts = _private(work / "artifacts")
    exports = _private(work / "exports")
    if args.db.exists():
        raise SystemExit("Benchmark database already exists; use a fresh private directory")
    namespace = _namespace(work)
    clock = Clock(BENCH_START)
    started = time.perf_counter()

    with open_store(args.db) as store:
        service = CampaignService(store, now=clock, timezone="UTC", namespace_path=namespace)
        campaign_id = service.start(days=5, retention_days=7)["campaign_id"]
        store.register_source_generation(generation_id=GENERATION, identity="synthetic-benchmark")
        campaign = store.campaign(campaign_id)
        campaign_start = int(campaign["start_epoch"])
        campaign_end = int(campaign["end_epoch"])

        capture_started = time.perf_counter()
        next_id = 1
        for index in range(args.hours):
            chunk_start = campaign_start + index * 3600
            chunk_end = chunk_start + 3600
            chunk_id = f"{campaign_id}:{chunk_start}:{chunk_end}"
            clock.epoch = chunk_end + SETTLING_GRACE_SECONDS + 1
            claim = service.claim_capture_work(generation_id=GENERATION, limit=10)
            selected = next(item for item in claim if item["chunk_id"] == chunk_id)
            rows = _synthetic_rows(chunk_start, chunk_end, args.rows_per_hour, next_id)
            next_id += args.rows_per_hour
            name = f"capture-{secrets.token_hex(16)}.json"
            snapshot = {
                "schema_version": 2,
                "read_state": "ok",
                "source_generation": GENERATION,
                "start_epoch": chunk_start,
                "end_epoch": chunk_end,
                "window_count": len(rows),
                "observations": rows,
                "retained_rows": len(rows),
                "oldest_epoch": campaign_start,
                "captured_utc": datetime.fromtimestamp(chunk_end, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }
            payload = json.dumps(snapshot, sort_keys=True).encode()
            _write_private(artifacts / name, payload)
            digest = hashlib.sha256(payload).hexdigest()
            service.ack_capture(chunk_id, token=selected["lease_token"], digest=digest, path=name)
            service.mark_import_pending(chunk_id)
            store.import_campaign_capture(
                campaign_id,
                chunk_id=chunk_id,
                generation_id=GENERATION,
                artifact_digest=digest,
                snapshot=snapshot,
            )
        capture_seconds = round(time.perf_counter() - capture_started, 3)

        # One bounded late-data reconciliation pass, as the host bridge does after
        # the 600-second delay. Without it, a campaign is truthfully "complete with
        # gaps" even when every window imported, because no recapture was attempted.
        reconcile_started = time.perf_counter()
        clock.epoch = campaign_end + 700
        for index in range(args.hours):
            chunk_start = campaign_start + index * 3600
            chunk_end = chunk_start + 3600
            chunk_id = f"{campaign_id}:{chunk_start}:{chunk_end}"
            rows = _synthetic_rows(
                chunk_start, chunk_end, args.rows_per_hour, 1 + index * args.rows_per_hour
            )
            name = f"reconcile-{secrets.token_hex(16)}.json"
            snapshot = {
                "schema_version": 2,
                "read_state": "ok",
                "source_generation": GENERATION,
                "start_epoch": chunk_start,
                "end_epoch": chunk_end,
                "window_count": len(rows),
                "observations": rows,
                "retained_rows": len(rows),
                "oldest_epoch": campaign_start,
                "captured_utc": datetime.fromtimestamp(chunk_end + 700, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            }
            payload = json.dumps(snapshot, sort_keys=True).encode()
            _write_private(artifacts / name, payload)
            store.import_campaign_capture(
                campaign_id,
                chunk_id=chunk_id,
                generation_id=GENERATION,
                artifact_digest=hashlib.sha256(payload).hexdigest(),
                snapshot=snapshot,
                reconciled=True,
            )
        reconcile_seconds = round(time.perf_counter() - reconcile_started, 3)

        clock.epoch = campaign_end + 701
        reports = CampaignReportService(store, now=clock)
        job_id = reports.request(campaign_id)
        report_started = time.perf_counter()
        report_id = reports.run_next(campaign_id)
        report_seconds = round(time.perf_counter() - report_started, 3)
        if report_id is None:
            raise SystemExit("The to-date report did not complete")
        status = reports.job_status(job_id)
        json_bytes = _json_export(reports, report_id)
        csv_bytes = reports.export_csv(report_id).encode()
        _write_private(exports / "report.json", json_bytes)
        _write_private(exports / "report.csv", csv_bytes)
        report_sha256 = hashlib.sha256(json_bytes).hexdigest()

        finalize_started = time.perf_counter()
        clock.epoch = campaign_end + FINALIZATION_ALLOWANCE_SECONDS + 1
        service.finalize(campaign_id)
        finalize_seconds = round(time.perf_counter() - finalize_started, 3)
        final = store.campaign(campaign_id)
        if final["state"] not in ("complete", "complete_with_gaps"):
            raise SystemExit("The synthetic campaign did not finalize")

        prepared = {
            "scenario": f"{args.hours}h-full-campaign",
            "hours": args.hours,
            "rows_per_hour": args.rows_per_hour,
            "rows": args.hours * args.rows_per_hour,
            "campaign_id": campaign_id,
            "campaign_state": final["state"],
            "job_id": job_id,
            "report_id": report_id,
            "report_job_state": status["state"],
            "report_sha256": report_sha256,
            "report_json_bytes": len(json_bytes),
            "report_csv_bytes": len(csv_bytes),
            "capture_seconds": capture_seconds,
            "reconcile_seconds": reconcile_seconds,
            "report_seconds": report_seconds,
            "finalize_seconds": finalize_seconds,
            "database_bytes": _database_bytes(store),
            "wal_bytes": (
                Path(f"{args.db}-wal").stat().st_size if Path(f"{args.db}-wal").exists() else 0
            ),
            "artifact_bytes": _bytes_under(artifacts),
            "export_bytes": _bytes_under(exports),
            "total_seconds": round(time.perf_counter() - started, 3),
            **_resource(),
        }
        _write_private(work / "state.json", json.dumps(prepared, sort_keys=True).encode())
        return prepared


def verify(args: argparse.Namespace) -> dict[str, object]:
    work = _private(args.work_dir)
    artifacts = _private(work / "artifacts")
    state = json.loads((work / "state.json").read_text())
    started = time.perf_counter()

    with open_store(args.db) as store:
        campaign = store.campaign(state["campaign_id"])
        clock = Clock(int(campaign["end_epoch"]) + SETTLING_GRACE_SECONDS)
        reports = CampaignReportService(store, now=clock)
        replay = _json_export(reports, state["report_id"])
        if hashlib.sha256(replay).hexdigest() != state["report_sha256"]:
            raise SystemExit("The frozen report changed after restart")
        frozen_status = reports.job_status(state["job_id"])
        if frozen_status["report_id"] != state["report_id"]:
            raise SystemExit("The report job lost its frozen result")

        campaign_start = int(store.campaign(state["campaign_id"])["start_epoch"])
        day = datetime.fromtimestamp(campaign_start + 86400, UTC).date().isoformat()
        day_started = time.perf_counter()
        day_job = reports.request(state["campaign_id"], day=day)
        day_report = reports.run_next(state["campaign_id"])
        day_seconds = round(time.perf_counter() - day_started, 3)
        if day_report is None:
            raise SystemExit("The completed-day report did not complete")

        archive = _private(work / "archive")
        if any(archive.iterdir()):
            raise SystemExit("The benchmark archive directory is not empty")
        retirement = CampaignRetirement(store, input_dir=artifacts)
        backup_started = time.perf_counter()
        retirement.backup(archive)
        retirement.verify(archive)
        restore = _private(work / "restore")
        if any(restore.iterdir()):
            raise SystemExit("The benchmark restore directory is not empty")
        retirement.restore(archive, restore)
        recovery_seconds = round(time.perf_counter() - backup_started, 3)

        result = {
            "scenario": f"{state['hours']}h-full-campaign-recovery",
            "campaign_id": state["campaign_id"],
            "frozen_report_unchanged": True,
            "day_report_id": day_report,
            "day_report_job": reports.job_status(day_job)["state"],
            "day_report_seconds": day_seconds,
            "backup_restore_seconds": recovery_seconds,
            "archive_database_bytes": (archive / "app.sqlite3").stat().st_size,
            "archive_artifact_bytes": _bytes_under(archive / "input"),
            "archive_artifact_count": len(list((archive / "input").iterdir())),
            "restore_database_bytes": (restore / "app.sqlite3").stat().st_size,
            "restored_input_bytes": _bytes_under(restore / "input"),
            "database_bytes": _database_bytes(store),
            "total_seconds": round(time.perf_counter() - started, 3),
            **_resource(),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--hours", type=int, default=120)
    parser.add_argument("--rows-per-hour", type=int, default=120)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    commands.add_parser("verify")
    args = parser.parse_args(argv)
    if not 1 <= args.hours <= 120:
        parser.error("--hours must be between 1 and 120")
    if not 1 <= args.rows_per_hour <= 10_000:
        parser.error("--rows-per-hour must be between 1 and 10000")
    if args.command == "prepare":
        result = prepare(args)
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        result = verify(args)
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
