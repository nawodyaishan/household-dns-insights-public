#!/usr/bin/env python3
"""Explicit host-side snapshot export: one closed window, read-only, no web job.

Runs the same one-statement ``query_only`` extraction the reporting module builds and
writes the untouched JSON payload into a private input directory. The application
never reaches the resolver, never gets the Docker socket and never runs a host shell;
this command is run by the owner, on the host, at the moment they choose.

    uv run --project destination-report python destination-report/tools/export_snapshot.py \
        --input-dir ~/.local/share/household-report/input \
        --start 1792728000 --end 1792731600

The window must already be closed (at least 60 seconds old) and at most one hour
wide. An existing file is never overwritten: raw evidence is append-only. Only
counts, the period and digests are printed; no domain, client or row content is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from household_report import reporting
from household_report.capture_contract import validate_campaign_snapshot

DEFAULT_CONTAINER = "starlink-dns-pilot"
DEFAULT_DB = "/etc/pihole/pihole-FTL.db"
CLOSED_GRACE_SECONDS = 60
MAX_WINDOW_SECONDS = 3600

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _require_private_dir(path: Path) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise SystemExit("Refusing symlinked input directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"Refusing insecure input directory mode {mode:o}: {path}")


def _write_new(path: Path, payload: bytes) -> None:
    """Write once, atomically, never replacing existing evidence."""
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise SystemExit(f"Refusing to overwrite preserved evidence: {path.name}") from None
    finally:
        temporary.unlink(missing_ok=True)


def _query(
    query: str,
    *,
    container: str,
    database: str,
    docker: str,
    runner: Runner,
) -> str:
    command = [
        docker,
        "exec",
        container,
        "pihole-FTL",
        "sqlite3",
        database,
        "PRAGMA query_only=ON; " + query,
    ]
    try:
        completed = runner(command, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        raise SystemExit("The read-only extraction timed out; nothing was written") from None
    except OSError as error:
        raise SystemExit(f"Cannot run {docker}: {error}") from None
    if completed.returncode != 0:
        raise SystemExit(
            "The read-only extraction failed "
            f"(exit {completed.returncode}); check the container and database path"
        )
    return completed.stdout


def main(argv: list[str] | None = None, *, runner: Runner | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True, help="window start (epoch seconds)")
    parser.add_argument("--end", type=int, required=True, help="window end (epoch seconds)")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--generation", help="operator-pinned campaign source generation")
    parser.add_argument("--artifact", help="fixed safe name for a campaign attempt")
    args = parser.parse_args(argv)

    start, end = int(args.start), int(args.end)
    if start >= end:
        parser.error("--start must precede --end")
    if end - start > MAX_WINDOW_SECONDS:
        parser.error(f"The window may be at most {MAX_WINDOW_SECONDS} seconds wide")
    grace = 120 if args.generation else CLOSED_GRACE_SECONDS
    if end > datetime.now(UTC).timestamp() - grace:
        parser.error(f"The window must be closed for at least {grace} seconds")
    if bool(args.generation) != bool(args.artifact):
        parser.error("Campaign export requires both --generation and --artifact")
    if args.artifact and not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", args.artifact):
        parser.error("Invalid campaign artifact name")
    if args.generation and not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", args.generation):
        parser.error("Invalid source generation")

    _require_private_dir(args.input_dir)
    target = args.input_dir / (
        f"{args.artifact}.json" if args.artifact else f"snapshot-{start}-{end}.json"
    )
    if target.exists() or target.is_symlink():
        parser.error(f"Refusing to overwrite preserved evidence: {target.name}")

    raw = _query(
        reporting.extraction_query(start, end),
        container=args.container,
        database=args.database,
        docker=args.docker,
        runner=runner or subprocess.run,
    )
    if len(raw.encode()) > 32 * 1024 * 1024:
        raise SystemExit("Extraction exceeds the bounded artifact size; nothing was written")
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit("The extraction did not return JSON; nothing was written") from None
    if int(snapshot.get("start_epoch", -1)) != start or int(snapshot.get("end_epoch", -1)) != end:
        raise SystemExit("The extraction returned a different window; nothing was written")
    observations = snapshot.get("observations")
    if not isinstance(observations, list) or (not observations and not args.generation):
        raise SystemExit("The extraction returned no observations; nothing was written")
    if int(snapshot.get("window_count", -1)) != len(observations):
        raise SystemExit("The extraction count does not match its rows; nothing was written")
    if any(not str(row.get("domain", "")).strip() for row in observations):
        raise SystemExit("The extraction contains a row without a name; nothing was written")

    if args.generation:
        snapshot["schema_version"] = 2
        snapshot["source_generation"] = args.generation
        snapshot["read_state"] = "ok"
        validate_campaign_snapshot(snapshot)
        payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        if len(payload) > 32 * 1024 * 1024:
            raise SystemExit("Extraction exceeds the bounded artifact size; nothing was written")
    else:
        payload = raw.encode() if isinstance(raw, str) else raw
    _write_new(target, payload)
    print(
        json.dumps(
            {
                "snapshot": target.name,
                "rows": len(observations),
                "start_utc": datetime.fromtimestamp(start, tz=UTC).isoformat(),
                "end_utc": datetime.fromtimestamp(end, tz=UTC).isoformat(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
