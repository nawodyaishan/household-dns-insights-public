#!/usr/bin/env python3
"""Opt-in host-only campaign tick; never run from the web container.

Fixed operator configuration chooses all executables/paths. Claimed work supplies
only bounds, generation and opaque IDs. No command is passed through a shell.
One tick is capped at ten windows and ten minutes; a host flock wraps the tick.

The bridge never registers or rebinds source identity. Every tick first runs the
read-only ``source-check``; a mismatch or unknown generation fails before any
source extraction/import and latches against the current configuration fingerprint.
Latched ticks skip capture entirely but still write the durable heartbeat so the
web can report a stuck collector without the bridge's cooperation. An explicit
``--retry-check`` (or a changed configuration fingerprint) clears the latch.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from household_report.campaign import MAX_TICK_CHUNKS
from household_report.collector_status import (
    CAPTURE_FAILED,
    IDENTITY_MISMATCH,
    IMPORT_FAILED,
    LATCHED_CODE,
    OK,
    STATUS_FILENAME,
    CollectorStatusError,
    mark_attempt,
    mark_running,
    read_status,
    write_status,
)

SAFE_ID = re.compile(r"[A-Za-z0-9:_-]{1,160}\Z")

#: Non-secret configuration keys that participate in the identity/config latch.
_FINGERPRINT_KEYS = (
    "python",
    "compose",
    "input_dir",
    "container",
    "database",
    "docker",
    "generation",
    "identity",
    "config_dir",
    "state_dir",
)


def _config_fingerprint(config: dict[str, object]) -> str:
    """Stable, non-secret hash of identity-relevant configuration for the latch."""
    payload = json.dumps(
        {key: config[key] for key in _FINGERPRINT_KEYS if key in config},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class BridgeError(RuntimeError):
    """A tick stopped safely; details stay in the private operator logs."""


class IdentityError(BridgeError):
    """Canonical source identity verification failed."""

    def __init__(self, code: str):
        self.code = (
            code if code in {"identity_mismatch", "unknown_generation"} else "identity_mismatch"
        )
        super().__init__(self.code)


def _private(path: Path, *, directory: bool = False) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise BridgeError("Symlinked operator path refused")
    if not path.exists() or (directory and not path.is_dir()):
        raise BridgeError("Operator path unavailable")
    if path.stat().st_mode & 0o077:
        raise BridgeError("Operator path is not private")


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise BridgeError("Invalid work identifier")
    return value


def _venv_python_link(path: Path) -> bool:
    """Allow the venv interpreter link, not arbitrary executable symlinks."""
    return (
        path.is_symlink()
        and path.name == "python"
        and path.parent.name == "bin"
        and path.parent.parent.name == ".venv"
        and not any(parent.is_symlink() for parent in path.parents)
        and path.is_file()
    )


class Bridge:
    def __init__(self, config: dict, *, runner=subprocess.run, clock=time.time, retry_check=False):
        required = {
            "python",
            "compose",
            "input_dir",
            "container",
            "database",
            "docker",
            "generation",
            "identity",
            "config_dir",
            "state_dir",
        }
        if set(config) != required:
            raise BridgeError("Operator configuration keys differ from the fixed contract")
        self.config = config
        self.runner = runner
        self.clock = clock
        self.retry_check = bool(retry_check)
        self._status_path = Path(config["state_dir"]) / STATUS_FILENAME
        _private(Path(config["input_dir"]), directory=True)
        _private(Path(config["config_dir"]), directory=True)
        _private(Path(config["state_dir"]), directory=True)
        compose = Path(config["compose"])
        if not compose.is_absolute() or not compose.is_file() or compose.is_symlink():
            raise BridgeError("Compose template must be an absolute regular file")
        for key in ("python", "docker"):
            path = Path(config[key])
            if (
                not path.is_absolute()
                or not path.is_file()
                or (path.is_symlink() and not (key == "python" and _venv_python_link(path)))
            ):
                raise BridgeError("Executable must be an absolute regular path")
        for key in ("generation", "container"):
            _identifier(config[key])
        if not str(config["database"]).startswith("/etc/pihole/") or not str(
            config["database"]
        ).endswith(".db"):
            raise BridgeError("Resolver database path is outside the fixed read-only scope")
        if not isinstance(config["identity"], str) or not config["identity"]:
            raise BridgeError("Source generation identity is required")

    def _run(self, command: list[str], timeout: float, *, env=None) -> dict:
        try:
            result = self.runner(
                command, capture_output=True, text=True, timeout=timeout, check=False, env=env
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BridgeError("Bounded subprocess unavailable or timed out") from error
        if result.returncode:
            raise BridgeError("Bounded subprocess failed; no source content logged")
        try:
            data = json.loads(result.stdout)
        except (ValueError, TypeError) as error:
            raise BridgeError("Invalid worker response") from error
        if not isinstance(data, dict):
            raise BridgeError("Invalid worker response")
        return data

    def app(self, command: str, *args: str, deadline: float) -> dict:
        if command not in {
            "source-check",
            "status",
            "worker-status",
            "claim-chunk",
            "pending-artifacts",
            "chunk-captured",
            "chunk-failed",
            "chunk-import-pending",
            "import-artifact",
            "attempt-artifacts",
            "report-run",
            "finalize",
        }:
            raise BridgeError("Unrecognized bridge operation")
        config = self.config
        env = os.environ.copy()
        env.update(
            HR_CONFIG_DIR=config["config_dir"],
            HR_INPUT_DIR=config["input_dir"],
            HR_STATE_DIR=config["state_dir"],
        )
        return self._run(
            [
                config["docker"],
                "compose",
                "-f",
                config["compose"],
                "exec",
                "-T",
                "app",
                "python",
                "/app/tools/campaign_cli.py",
                "--db",
                "/state/app.sqlite3",
                command,
                *args,
            ],
            max(1, min(600 if command == "report-run" else 60, deadline - self.clock())),
            env=env,
        )

    def _export(self, work: dict, name: str, deadline: float) -> str:
        config = self.config
        target = Path(config["input_dir"]) / (name + ".json")
        if not target.exists() and not target.is_symlink():
            result = self._run(
                [
                    config["python"],
                    str(Path(__file__).with_name("export_snapshot.py")),
                    "--input-dir",
                    config["input_dir"],
                    "--start",
                    str(work["start_epoch"]),
                    "--end",
                    str(work["end_epoch"]),
                    "--generation",
                    work["generation_id"],
                    "--artifact",
                    name,
                    "--container",
                    config["container"],
                    "--database",
                    config["database"],
                    "--docker",
                    config["docker"],
                ],
                max(1, min(90, deadline - self.clock())),
            )
            if result.get("snapshot") != target.name:
                raise BridgeError("Exporter returned an unexpected artifact")
        if target.is_symlink() or not target.is_file() or target.stat().st_size > 32 * 1024 * 1024:
            raise BridgeError("Unsafe capture artifact")
        with target.open("rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        return digest

    def _import(self, work: dict, name: str, digest: str, deadline: float, *, reconcile=False):
        self._require_identity(deadline)
        args = [
            "--campaign",
            work["campaign_id"],
            "--chunk",
            work["chunk_id"],
            "--name",
            name + ".json",
            "--digest",
            digest,
        ]
        if reconcile:
            args.append("--reconcile")
        self._importing = True
        try:
            result = self.app("import-artifact", *args, deadline=deadline)
        finally:
            self._importing = False
        if result.get("state") not in ("imported", "successful_empty", "partial"):
            raise BridgeError("Capture import was not acknowledged")

    def tick(self) -> int:
        limit_time = self.clock() + 600
        config = self.config
        start = int(self.clock())
        fingerprint = _config_fingerprint(config)
        record = read_status(self._status_path)
        self._importing = False

        # A durable latch (same config fingerprint still failing identity) skips
        # capture/export/import entirely — no FTL reads — but keeps writing the
        # heartbeat so the web can report the stuck collector independently.
        latched = (
            isinstance(record, dict)
            and record.get("latched_fingerprint") == fingerprint
            and not self.retry_check
        )
        if latched:
            record = mark_attempt(
                record,
                now_epoch=start,
                start_epoch=start,
                end_epoch=start,
                code=LATCHED_CODE,
                stage="identity",
                running=False,
                failure=None,
                latched_fingerprint=fingerprint,
            )
            self._write(record)
            self._report_tick(limit_time)
            return 0

        # Read-only identity preflight: never registers, never upserts, never
        # rebinds. A mismatch or unknown generation is a hard failure before any
        # source extraction/import and it latches against this configuration.
        record = mark_running(record, now_epoch=start)
        self._write(record)
        try:
            check = self.app(
                "source-check",
                "--generation",
                config["generation"],
                "--identity",
                config["identity"],
                deadline=limit_time,
            )
        except BridgeError:
            record = mark_attempt(
                record,
                now_epoch=int(self.clock()),
                start_epoch=start,
                end_epoch=int(self.clock()),
                code="bridge_failed",
                stage="identity",
                running=False,
                failure=True,
            )
            self._write(record)
            raise
        if check.get("verified") is not True:
            code = str(check.get("code") or IDENTITY_MISMATCH)
            record = mark_attempt(
                record,
                now_epoch=start,
                start_epoch=start,
                end_epoch=start,
                code=code,
                stage="identity",
                running=False,
                failure=True,
                latched_fingerprint=fingerprint,
                pending_eligible=0,
            )
            self._write(record)
            self._report_tick(limit_time)
            return 0
        # Verified: clear any stale latch from an earlier config fingerprint and
        # mark the bridge live; earlier capture/import successes are preserved.
        record = mark_attempt(
            record,
            now_epoch=start,
            start_epoch=start,
            end_epoch=start,
            code=OK,
            stage="identity",
            running=False,
            failure=False,
            clear_latch=True,
            last_success_fields={"bridge_epoch": start},
            pending_eligible=0,
        )
        self._write(record)

        # An inactive application must not trigger a resolver read. Worker
        # errors are not confused with an inactive campaign (monitoring gap).
        status = self.app("worker-status", deadline=limit_time).get("campaign")
        if status is None:
            self._report_tick(limit_time)
            return 0
        if not isinstance(status, dict):
            raise BridgeError("Invalid campaign status")
        if status.get("state") not in ("active", "finalizing"):
            return 0
        campaign = _identifier(status.get("campaign_id"))
        completed = 0
        pending = self.app(
            "pending-artifacts", "--campaign", campaign, "--limit", "10", deadline=limit_time
        ).get("pending", [])
        if not isinstance(pending, list) or len(pending) > 10:
            raise BridgeError("Invalid pending work list")
        try:
            self._require_identity(limit_time)
            for work in pending:
                if self.clock() >= limit_time or completed >= MAX_TICK_CHUNKS:
                    break
                self._validate(work, status)
                if work["state"] in ("captured", "import_pending"):
                    name = work["path"]
                    if not isinstance(name, str) or not re.fullmatch(
                        r"[A-Za-z0-9_-]{1,96}\.json", name
                    ):
                        raise BridgeError("Invalid pending artifact name")
                    if work["state"] == "captured":
                        self.app(
                            "chunk-import-pending",
                            "--campaign",
                            campaign,
                            "--chunk",
                            work["chunk_id"],
                            deadline=limit_time,
                        )
                    self._import(work, name[:-5], work["digest"], limit_time)
                    record = mark_attempt(
                        record,
                        now_epoch=int(self.clock()),
                        end_epoch=int(self.clock()),
                        code=OK,
                        stage="import",
                        running=False,
                        failure=False,
                        last_success_fields={"import_epoch": int(self.clock())},
                    )
                else:
                    name = "reconcile-" + hashlib.sha256(work["chunk_id"].encode()).hexdigest()[:32]
                    digest = self._export(work, name, limit_time)
                    self._import(work, name, digest, limit_time, reconcile=True)
                    record = mark_attempt(
                        record,
                        now_epoch=int(self.clock()),
                        end_epoch=int(self.clock()),
                        code=OK,
                        stage="import",
                        running=False,
                        failure=False,
                        last_success_fields={"import_epoch": int(self.clock())},
                    )
                completed += 1
            while completed < MAX_TICK_CHUNKS and self.clock() < limit_time:
                claims = self.app(
                    "claim-chunk",
                    "--campaign",
                    campaign,
                    "--generation",
                    config["generation"],
                    "--limit",
                    "1",
                    deadline=limit_time,
                ).get("claimed", [])
                if not isinstance(claims, list) or len(claims) > 1:
                    raise BridgeError("Invalid capture work list")
                if not claims:
                    break
                for work in claims:
                    self._validate(work, status)
                    self._require_identity(limit_time)
                    token = _identifier(work["lease_token"])
                    name = "capture-" + token
                    acknowledged = False
                    try:
                        tokens = self.app(
                            "attempt-artifacts",
                            "--campaign",
                            campaign,
                            "--chunk",
                            work["chunk_id"],
                            deadline=limit_time,
                        ).get("tokens", [])
                        if not isinstance(tokens, list) or len(tokens) > 3:
                            raise BridgeError("Invalid capture attempt history")
                        for previous in tokens:
                            candidate = "capture-" + _identifier(previous)
                            artifact = Path(config["input_dir"]) / (candidate + ".json")
                            if artifact.exists() or artifact.is_symlink():
                                name = candidate
                                break
                        digest = self._export(work, name, limit_time)
                        ack = self.app(
                            "chunk-captured",
                            "--campaign",
                            campaign,
                            "--chunk",
                            work["chunk_id"],
                            "--token",
                            token,
                            "--digest",
                            digest,
                            "--path",
                            name + ".json",
                            deadline=limit_time,
                        )
                        if ack.get("acknowledged") is not True:
                            raise BridgeError("Stale capture lease")
                        acknowledged = True
                        record = mark_attempt(
                            record,
                            now_epoch=int(self.clock()),
                            end_epoch=int(self.clock()),
                            code=OK,
                            stage="capture",
                            running=False,
                            failure=False,
                            last_success_fields={"capture_epoch": int(self.clock())},
                        )
                        self.app(
                            "chunk-import-pending",
                            "--campaign",
                            campaign,
                            "--chunk",
                            work["chunk_id"],
                            deadline=limit_time,
                        )
                        self._import(work, name, digest, limit_time)
                        record = mark_attempt(
                            record,
                            now_epoch=int(self.clock()),
                            end_epoch=int(self.clock()),
                            code=OK,
                            stage="import",
                            running=False,
                            failure=False,
                            last_success_fields={"import_epoch": int(self.clock())},
                        )
                    except BridgeError:
                        # If the capture was acknowledged, pending-artifacts recovers
                        # import next tick. Otherwise the lease expires for bounded retry.
                        if not acknowledged:
                            self.app(
                                "chunk-failed",
                                "--campaign",
                                campaign,
                                "--chunk",
                                work["chunk_id"],
                                "--token",
                                token,
                                "--reason",
                                "bounded source extraction failed",
                                deadline=limit_time,
                            )
                        raise
                    completed += 1
            if self.clock() >= status["utc_bounds"][1] and self.clock() < limit_time:
                self.app("finalize", "--campaign", campaign, deadline=limit_time)
        except BridgeError as error:
            # Persist the failure independently of worker calls; recorded capture
            # success is never erased by a later failure in the same tick.
            if isinstance(error, IdentityError):
                code, stage = error.code, "identity"
            elif self._importing:
                code, stage = IMPORT_FAILED, "import"
            else:
                code, stage = CAPTURE_FAILED, "capture"
            record = mark_attempt(
                record,
                now_epoch=int(self.clock()),
                end_epoch=int(self.clock()),
                code=code,
                stage=stage,
                running=False,
                failure=True,
                latched_fingerprint=fingerprint if isinstance(error, IdentityError) else None,
            )
            self._write(record)
            raise
        pending_count = max(0, len(pending) + completed)
        if pending_count:
            eligible_since = record.get("eligible_since_epoch")
            record = mark_attempt(
                record,
                now_epoch=int(self.clock()),
                end_epoch=int(self.clock()),
                code=OK,
                stage="bridge",
                running=False,
                failure=False,
                pending_eligible=pending_count,
                eligible_since_epoch=(
                    int(eligible_since) if isinstance(eligible_since, int) else start
                ),
            )
        else:
            record = mark_attempt(
                record,
                now_epoch=int(self.clock()),
                end_epoch=int(self.clock()),
                code=OK,
                stage="bridge",
                running=False,
                failure=False,
                pending_eligible=0,
                clear_eligibility=True,
            )
        self._write(record)
        self._report_tick(limit_time)
        return completed

    def _require_identity(self, deadline: float) -> None:
        """Re-verify configured identity right before a capture/import to close
        races. Fails closed with an actionable code and never blocks on reads."""
        check = self.app(
            "source-check",
            "--generation",
            self.config["generation"],
            "--identity",
            self.config["identity"],
            deadline=deadline,
        )
        if check.get("verified") is not True:
            code = str(check.get("code") or IDENTITY_MISMATCH)
            raise IdentityError(code)

    def _write(self, record: dict[str, object]) -> None:
        """Persist the sanitized status file; an unwritable state is visible as
        unavailable from the app side rather than crashing the capture tick."""
        try:
            write_status(self._status_path, record)
        except CollectorStatusError:
            pass

    def _report_tick(self, deadline: float) -> None:
        """Process one local report even if the capture campaign is complete."""
        remaining = int(deadline - self.clock()) - 5
        if remaining >= 30:
            self.app("report-run", "--max-seconds", str(min(remaining, 600)), deadline=deadline)

    def _validate(self, work: dict, status: dict) -> None:
        if not isinstance(work, dict):
            raise BridgeError("Invalid work descriptor")
        for key in ("chunk_id", "campaign_id", "generation_id"):
            _identifier(work.get(key))
        start, end = work.get("start_epoch"), work.get("end_epoch")
        if (
            work["campaign_id"] != status["campaign_id"]
            or work["generation_id"] != self.config["generation"]
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not status["utc_bounds"][0] <= start < end <= status["utc_bounds"][1]
            or end - start > 3600
            or self.clock() < end + 120
        ):
            raise BridgeError("Work outside configured source or settled campaign bounds")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--retry-check",
        action="store_true",
        help="force one identity re-check even while the durable latch is set",
    )
    args = parser.parse_args(argv)
    try:
        _private(args.config)
        config = json.loads(args.config.read_text())
        bridge = Bridge(config, retry_check=args.retry_check)
        lock = Path(config["state_dir"]) / "campaign-bridge.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps({"processed": bridge.tick()}))
        finally:
            os.close(fd)
        return 0
    except (BridgeError, OSError, ValueError, KeyError, BlockingIOError):
        print(json.dumps({"error": "Bridge tick stopped; inspect private operator status"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
