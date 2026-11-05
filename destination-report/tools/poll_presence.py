#!/usr/bin/env python3
"""Explicit host-side presence poll using the established read-only RPC.

Reuses only the investigated call (``wifi_get_clients`` on the router's gRPC
endpoint through the pinned grpcurl image) and writes one envelope per sample in the
same shape the existing private ``presence-*.json`` files already have, so the
inventory importer validates them unchanged. Failed samples are recorded as explicit
errors, never as device absence, and old files are never overwritten.

    uv run --project destination-report python destination-report/tools/poll_presence.py \
        --input-dir ~/.local/share/household-report/input --count 9 --interval 15

This starts no long-running collector. Only sample counts and transport outcomes are
printed; client names, MAC addresses and payloads stay in the private files.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_ENDPOINT = "192.168.1.1:9000"
DEFAULT_IMAGE = "fullstorydev/grpcurl:v1.9.3"
SERVICE = "SpaceX.API.Device.Device/Handle"
REQUEST = '{"wifi_get_clients":{}}'
MIN_INTERVAL_SECONDS = 5.0
MAX_SAMPLES = 120

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _require_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"Refusing insecure input directory mode {mode:o}: {path}")


def _write_new(path: Path, payload: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(f"Refusing to overwrite preserved evidence: {path.name}") from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if path.exists() and path.stat().st_size == 0:
            path.unlink()


def _sample(
    index: int,
    *,
    input_dir: Path,
    endpoint: str,
    image: str,
    docker: str,
    timeout: float,
    runner: Runner,
) -> dict[str, object]:
    command = [
        docker,
        "run",
        "--rm",
        "--network",
        "host",
        image,
        "-plaintext",
        "-connect-timeout",
        "3",
        "-max-time",
        "8",
        "-d",
        REQUEST,
        endpoint,
        SERVICE,
    ]
    started = datetime.now(UTC)
    try:
        completed = runner(command, capture_output=True, text=True, timeout=timeout, check=False)
        record = {
            "end": datetime.now(UTC).isoformat(),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired:
        record = {
            "end": datetime.now(UTC).isoformat(),
            "returncode": -1,
            "stdout": "",
            "stderr": "LOCAL_TIMEOUT",
        }
    except OSError as error:
        record = {
            "end": datetime.now(UTC).isoformat(),
            "returncode": -1,
            "stdout": "",
            "stderr": f"LOCAL_ERROR {type(error).__name__}",
        }
    envelope = {
        "start": started.isoformat(),
        "end": record["end"],
        "endpoint": endpoint,
        "tail": [
            "-plaintext",
            "-connect-timeout",
            "3",
            "-max-time",
            "8",
            "-d",
            REQUEST,
            endpoint,
            SERVICE,
        ],
        "returncode": record["returncode"],
        "stdout": record["stdout"],
        "stderr": record["stderr"],
    }
    name = f"presence-{started.strftime('%Y%m%dT%H%M%SZ')}-{index:02d}.json"
    _write_new(input_dir / name, json.dumps(envelope, indent=2))
    return {"name": name, "ok": int(record["returncode"]) == 0, "returncode": record["returncode"]}


def main(argv: list[str] | None = None, *, runner: Runner | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--count", type=int, default=9)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    if not 1 <= args.count <= MAX_SAMPLES:
        parser.error(f"--count must be between 1 and {MAX_SAMPLES}")
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS:g} seconds")

    _require_private_dir(args.input_dir)
    run = runner or subprocess.run
    started = time.monotonic()
    results = []
    for index in range(args.count):
        time.sleep(max(0.0, started + args.interval * index - time.monotonic()))
        result = _sample(
            index,
            input_dir=args.input_dir,
            endpoint=args.endpoint,
            image=args.image,
            docker=args.docker,
            timeout=args.timeout,
            runner=run,
        )
        results.append(result)
        state = "OK" if result["ok"] else f"FAILED (exit {result['returncode']})"
        print(f"Presence sample {index + 1}/{args.count}: {state}", flush=True)

    failed = sum(1 for result in results if not result["ok"])
    print(
        json.dumps(
            {
                "samples": len(results),
                "succeeded": len(results) - failed,
                "failed": failed,
                "input_dir": str(args.input_dir),
            },
            indent=2,
        )
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
