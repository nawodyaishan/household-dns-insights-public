"""Sanitized durable collector health model shared by bridge, web and CLI.

This module owns the on-disk format and the health classification of the host
capture bridge. Everything here is read/write-safe offline: no network, no
resolver access, no Docker. Clocks are injected (``now_epoch``) so tests use fake
clocks, matching plan D4.

The status file is private by content (no source names, no identity string, no
configuration secrets) but must be readable by the web container, so it is stored
with mode ``0o644`` inside the operator state directory and replaced atomically.
The bridge writes it; the web app and the CLI read it and derive staleness
themselves. A missing or unwritable record is visible as ``unavailable``, never
as healthy.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = 1
STATUS_FILENAME = "bridge-status.json"

#: A heartbeat is stale after 720 seconds: one bounded tick window (600s) plus
#: the 60-second scheduling cadence and a small guard. This is a documented bound,
#: not a liveness claim; the app never trusts the file to report its own death.
HEARTBEAT_STALE_SECONDS = 720
#: Eligible capture/import work is overdue after 15 minutes beyond eligibility
#: while a campaign is active.
OVERDUE_SECONDS = 900

#: Canonical health states. Web renders these; tests pin them exactly.
UNAVAILABLE = "unavailable"
RUNNING = "running"
LATCHED = "latched"
FAILED = "failed"
STALE_HEARTBEAT = "stale_heartbeat"
OVERDUE = "overdue"
COLLECTING = "collecting"
WAITING = "waiting"
NO_CAMPAIGN = "no_campaign"
HISTORICAL = "historical"
EMPTY = "successful_empty"
PARTIAL = "partial"
EXPIRED = "expired"

STATES = (
    UNAVAILABLE,
    RUNNING,
    LATCHED,
    FAILED,
    STALE_HEARTBEAT,
    OVERDUE,
    COLLECTING,
    WAITING,
    NO_CAMPAIGN,
    HISTORICAL,
    EMPTY,
    PARTIAL,
    EXPIRED,
)

LABELS = {
    UNAVAILABLE: "Timer state unavailable",
    RUNNING: "Capture tick running",
    LATCHED: "Source identity or configuration needs correction",
    FAILED: "Last capture or import attempt failed",
    STALE_HEARTBEAT: "Collector heartbeat is stale",
    OVERDUE: "Eligible capture or import work is overdue",
    COLLECTING: "Collecting",
    WAITING: "Waiting for the next closed window",
    NO_CAMPAIGN: "No active campaign",
    HISTORICAL: "Completed history; no new capture is due",
    EMPTY: "Successful empty capture",
    PARTIAL: "Partial coverage",
    EXPIRED: "Expired history present",
}

#: Fields a host bridge may persist after a tick. Key names are a fixed contract:
#: timing, outcome code, stage and counters only.
ATTEMPT_FIELDS = ("start_epoch", "end_epoch", "code", "stage", "running")
LAST_SUCCESS_FIELDS = ("bridge_epoch", "capture_epoch", "import_epoch")

#: Outcome codes a bridge may write for the last attempt.
OK = "ok"
RUNNING_CODE = "running"
LATCHED_CODE = "latched"
IDENTITY_MISMATCH = "identity_mismatch"
UNKNOWN_GENERATION = "unknown_generation"
CAPTURE_FAILED = "capture_failed"
IMPORT_FAILED = "import_failed"


def _now_iso(epoch: int) -> str:
    return (
        datetime.fromtimestamp(int(epoch), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _epoch_from_iso(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return int(parsed.timestamp())


def fresh_record(*, now_epoch: int) -> dict[str, object]:
    """A valid empty record: no attempt, no failure, no success yet."""
    return {
        "schema": SCHEMA,
        "updated_epoch": int(now_epoch),
        "attempt": None,
        "consecutive_failures": 0,
        "last_success": {field: None for field in LAST_SUCCESS_FIELDS},
        "last_error_code": None,
        "last_stage": None,
        "pending_eligible": 0,
        "latched_fingerprint": None,
    }


class CollectorStatusError(ValueError):
    """The on-disk status record is malformed or refused."""


def _is_private_dir(path: Path) -> None:
    if path.is_symlink():
        raise CollectorStatusError("Status file parent is a symlink")
    if not path.is_dir():
        raise CollectorStatusError("Status file parent is missing")
    if stat.S_IMODE(path.stat().st_mode) & 0o007:
        raise CollectorStatusError("Status file parent is not owner-only")


def write_status(
    path: Path,
    record: dict[str, object],
) -> None:
    """Atomically persist a sanitized bridge status record (world-readable file).

    The file is replaced in place (``os.replace``) so readers never observe a
    half-written record. Mode is 0644 inside the owner-only state directory so the
    web container can read it without exposing its parent tree. A failed write is
    raised as ``CollectorStatusError``; the caller surfaces it as ``unavailable``.
    """
    _is_private_dir(path.parent)
    if path.is_symlink():
        raise CollectorStatusError("Status file must not be a symlink")
    if record.get("schema") != SCHEMA:
        raise CollectorStatusError("Unsupported status schema")
    if not isinstance(record.get("attempt"), (dict, type(None))):
        raise CollectorStatusError("Status attempt must be a mapping or null")
    if not isinstance(record.get("consecutive_failures"), int):
        raise CollectorStatusError("Status failures must be an integer")
    if not isinstance(record.get("last_success"), dict):
        raise CollectorStatusError("Status last-success must be a mapping")
    payload = json.dumps(record, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    temporary: str | None = None
    try:
        handle, temporary = tempfile.mkstemp(
            prefix=".bridge-status.", suffix=".tmp", dir=str(path.parent), text=True
        )
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        raise CollectorStatusError("Could not persist bridge status") from error


def read_status(path: Path) -> dict[str, object] | None:
    """Parse the bridge status record; ``None`` means unavailable, never raises."""
    try:
        info = path.stat()
    except OSError:
        return None
    if info.st_size > 64 * 1024 or not stat.S_ISREG(info.st_mode):
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None
    return record


def mark_running(record: dict[str, object] | None, *, now_epoch: int) -> dict[str, object]:
    """Mark a tick as in progress. Consecutive failures and last-success history are
    preserved; a running tick is never mistaken for fresh success."""
    base = dict(record) if isinstance(record, dict) else fresh_record(now_epoch=now_epoch)
    base["updated_epoch"] = int(now_epoch)
    base["attempt"] = {
        "start_epoch": int(now_epoch),
        "end_epoch": None,
        "code": RUNNING_CODE,
        "stage": None,
        "running": True,
    }
    return base


def mark_attempt(
    record: dict[str, object] | None,
    *,
    now_epoch: int,
    start_epoch: int | None = None,
    end_epoch: int | None = None,
    code: str,
    stage: str,
    running: bool,
    failure: bool | None,
    last_success_fields: dict[str, int] | None = None,
    pending_eligible: int | None = None,
    eligible_since_epoch: int | None = None,
    clear_eligibility: bool = False,
    latched_fingerprint: str | None = None,
    clear_latch: bool = False,
) -> dict[str, object]:
    """Record one finished (or still-running) tick attempt.

    ``failure=True`` increments consecutive failures and stores the sanitized code;
    ``failure=False`` resets the consecutive-failure counter; ``failure=None`` keeps
    the counter unchanged (used for latched heartbeat ticks that skip all work).
    ``last_success_fields`` (bridge/capture/import epochs) only ever move forward, so
    a capture failure never erases an earlier success. A ``latched_fingerprint``
    (config hash, not the identity itself) marks the durable identity/config latch;
    ``clear_latch`` clears it after a successful explicit re-check.
    """
    base = dict(record) if isinstance(record, dict) else fresh_record(now_epoch=now_epoch)
    base["updated_epoch"] = int(now_epoch)
    if failure is True:
        failures = int(base.get("consecutive_failures") or 0) + 1
    elif failure is False:
        failures = 0
    else:
        failures = int(base.get("consecutive_failures") or 0)
    base["consecutive_failures"] = failures
    base["attempt"] = {
        "start_epoch": int(start_epoch) if start_epoch is not None else None,
        "end_epoch": int(end_epoch) if end_epoch is not None else None,
        "code": str(code),
        "stage": str(stage),
        "running": bool(running),
    }
    if failure is True:
        base["last_error_code"] = str(code)
        base["last_stage"] = str(stage)
    elif failure is False:
        base["last_error_code"] = None
        base["last_stage"] = None
    if pending_eligible is not None:
        base["pending_eligible"] = int(pending_eligible)
    if eligible_since_epoch is not None:
        base["eligible_since_epoch"] = int(eligible_since_epoch)
    elif clear_eligibility:
        base["eligible_since_epoch"] = None
    if latched_fingerprint is not None:
        base["latched_fingerprint"] = str(latched_fingerprint)
    elif clear_latch:
        base["latched_fingerprint"] = None
    success = dict(base.get("last_success") or {})
    if last_success_fields:
        for field, value in last_success_fields.items():
            previous = success.get(field)
            success[field] = (
                max(int(previous), int(value)) if isinstance(previous, int) else int(value)
            )
    base["last_success"] = success
    return base


def collect_heartbeat_age(record: dict[str, object] | None, *, now_epoch: int) -> int | None:
    """Seconds since the freshest bridge heartbeat, or ``None`` when none exists."""
    if not isinstance(record, dict):
        return None
    stamps: list[int] = []
    last = record.get("last_success")
    if isinstance(last, dict) and isinstance(last.get("bridge_epoch"), int):
        stamps.append(int(last["bridge_epoch"]))
    attempt = record.get("attempt")
    if isinstance(attempt, dict):
        if isinstance(attempt.get("end_epoch"), int):
            stamps.append(int(attempt["end_epoch"]))
        if isinstance(attempt.get("start_epoch"), int):
            stamps.append(int(attempt["start_epoch"]))
    if isinstance(record.get("updated_epoch"), int):
        stamps.append(int(record["updated_epoch"]))
    return int(now_epoch) - max(stamps) if stamps else None


def classify_status(
    record: dict[str, object] | None,
    *,
    now_epoch: int,
    campaign_state: str | None = None,
    campaign_complete: bool | None = None,
    coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    """Classify collector health from the durable record, a fake clock and optional
    campaign context.

    ``campaign_state`` is the current campaign state (``"active"``/``"finalizing"``/
    ``"complete"``/``"complete_with_gaps"``) or ``None`` when there is no campaign
    the app can see. ``coverage`` may carry the campaign's chunk ``by_state`` counts
    (``successful_empty``/``partial``/``expired``/...) to distinguish acquisition
    outcomes the bridge heartbeat alone cannot represent.

    R08 guarantees: no active campaign, waiting for settled data, successful empty
    capture, partial coverage, stale collection, failed capture/import, expired
    history and unavailable status are distinct. Zero processed work is never
    treated as capture success. Completed campaigns are not failed for having no
    new capture due.
    """
    if record is None:
        return _health(
            UNAVAILABLE,
            detail="No fresh host status file exists for the capture timer.",
        )
    age = collect_heartbeat_age(record, now_epoch=now_epoch)
    attempt = record.get("attempt")
    running = bool(isinstance(attempt, dict) and attempt.get("running"))
    if running and age is not None and age <= HEARTBEAT_STALE_SECONDS:
        return _health(
            RUNNING,
            detail="A bounded capture tick is in progress; one more window is still allowed.",
        )
    if age is not None and age > HEARTBEAT_STALE_SECONDS:
        return _health(
            STALE_HEARTBEAT,
            detail=(
                f"No bridge heartbeat for {age}s (stale after "
                f"{HEARTBEAT_STALE_SECONDS}s). Capture may have stopped; the web "
                "derives this independently of the bridge."
            ),
        )
    latched = record.get("latched_fingerprint")
    if isinstance(latched, str) and latched:
        return _health(
            LATCHED,
            detail=(
                "Source identity or configuration is latched. Correct the operator "
                "configuration or run an explicit retry-check before capture resumes."
            ),
        )
    failures = int(record.get("consecutive_failures") or 0)
    if failures:
        stage = str(record.get("last_stage") or "capture")
        code = str(record.get("last_error_code") or "failed")
        return _health(
            FAILED,
            detail=f"Last {stage} attempt failed ({code}); prior successes remain intact.",
        )
    if campaign_complete or campaign_state in ("complete", "complete_with_gaps"):
        return _health(
            HISTORICAL,
            detail="Completed history stays visible and is not reported as failure.",
        )
    if campaign_state is None:
        return _health(
            NO_CAMPAIGN,
            detail="No active campaign; the bridge records its heartbeat without capturing.",
        )
    # Campaign is active/finalizing: distinguish acquisition outcome by coverage.
    pending = int(record.get("pending_eligible") or 0)
    if coverage is not None and isinstance(coverage.get("ready_to_capture"), int):
        pending = max(pending, int(coverage["ready_to_capture"]))
    if coverage is None:
        by_state: dict[str, int] = {}
    else:
        by_state = {
            str(key): int(value)
            for key, value in coverage.items()
            if isinstance(value, int)
            and str(key)
            in {
                "scheduled",
                "settling",
                "captured",
                "successful_empty",
                "import_pending",
                "imported",
                "partial",
                "failed",
                "expired",
                "ready_to_capture",
            }
        }
    eligible_since = record.get("eligible_since_epoch")
    if coverage is not None:
        coverage_ready = coverage.get("oldest_ready_epoch")
        if isinstance(coverage_ready, int):
            eligible_since = coverage_ready
    capture_overdue = (
        pending > 0
        and isinstance(eligible_since, int)
        and int(now_epoch) - eligible_since > OVERDUE_SECONDS
    )
    import_since = record.get("import_eligible_since_epoch")
    if coverage is not None:
        coverage_import = coverage.get("oldest_import_pending_epoch")
        if isinstance(coverage_import, int):
            import_since = coverage_import
    import_overdue = (
        by_state.get("import_pending", 0) > 0
        and isinstance(import_since, int)
        and int(now_epoch) - import_since > OVERDUE_SECONDS
    )
    if capture_overdue or import_overdue:
        return _health(
            OVERDUE,
            detail=(
                f"Eligible capture/import has been pending more than {OVERDUE_SECONDS}s "
                f"while the campaign is active (eligible {pending})."
            ),
        )
    successful_empty = by_state.get("successful_empty", 0)
    partial = by_state.get("partial", 0)
    expired = by_state.get("expired", 0)
    imported = by_state.get("imported", 0)
    if successful_empty and not imported and not partial:
        return _health(
            EMPTY,
            detail="Successful empty capture was acknowledged; it is not a gap.",
        )
    if expired:
        return _health(
            EXPIRED,
            detail="Expired history remains visible and is distinct from capture success.",
        )
    if partial or (imported and by_state.get("scheduled", 0)):
        return _health(PARTIAL, detail="Coverage is partial; unresolved windows stay visible.")
    if pending > 0:
        return _health(COLLECTING, detail="Eligible capture work is being processed.")
    return _health(
        WAITING,
        detail="No closed window is due yet; waiting is not staleness until work is due.",
    )


def _health(state: str, *, detail: str) -> dict[str, object]:
    return {
        "state": state,
        "label": LABELS[state],
        "detail": detail,
    }


def collector_context(
    record: dict[str, object] | None,
    *,
    now_epoch: int,
    campaign_state: str | None = None,
    campaign_complete: bool | None = None,
    coverage: dict[str, object] | None = None,
) -> dict[str, object]:
    """One sanitized health context for the web default page and the CLI.

    Combines the durable bridge record (or the ``unavailable`` classification when
    the record is missing/unreadable) with display-local timestamps that survive
    restart. No source names, no identity string, no configuration material.
    """
    health = classify_status(
        record,
        now_epoch=now_epoch,
        campaign_state=campaign_state,
        campaign_complete=campaign_complete,
        coverage=coverage,
    )
    base: dict[str, object] = dict(health)
    if record is None:
        base["updated_epoch"] = None
        base["attempt"] = None
        base["consecutive_failures"] = None
        base["last_success"] = None
        base["pending_eligible"] = None
        base["latched_fingerprint"] = None
        base["campaign_state"] = campaign_state
        for field in ("bridge", "capture", "import"):
            base[f"last_{field}_epoch_utc"] = None
        return base
    attempt = record.get("attempt")
    base["updated_epoch"] = record.get("updated_epoch")
    base["attempt"] = attempt
    base["consecutive_failures"] = record.get("consecutive_failures")
    base["last_success"] = record.get("last_success")
    base["pending_eligible"] = record.get("pending_eligible")
    base["latched_fingerprint"] = bool(record.get("latched_fingerprint"))
    base["campaign_state"] = campaign_state
    for field in ("bridge", "capture", "import"):
        base[f"last_{field}_epoch_utc"] = None
    if isinstance(record.get("last_success"), dict):
        for field in ("bridge_epoch", "capture_epoch", "import_epoch"):
            value = record["last_success"].get(field)
            if isinstance(value, int):
                base[f"last_{field}_utc"] = _now_iso(value)
    return base


__all__ = [
    "ATTEMPT_FIELDS",
    "CAPTURE_FAILED",
    "COLLECTING",
    "CollectorStatusError",
    "EMPTY",
    "EXPIRED",
    "FAILED",
    "HEARTBEAT_STALE_SECONDS",
    "HISTORICAL",
    "IDENTITY_MISMATCH",
    "IMPORT_FAILED",
    "LAST_SUCCESS_FIELDS",
    "LABELS",
    "LATCHED",
    "LATCHED_CODE",
    "NO_CAMPAIGN",
    "OK",
    "OVERDUE",
    "OVERDUE_SECONDS",
    "PARTIAL",
    "RUNNING",
    "RUNNING_CODE",
    "SCHEMA",
    "STATES",
    "STALE_HEARTBEAT",
    "UNAVAILABLE",
    "UNKNOWN_GENERATION",
    "WAITING",
    "classify_status",
    "collect_heartbeat_age",
    "collector_context",
    "fresh_record",
    "mark_attempt",
    "mark_running",
    "read_status",
    "write_status",
]
