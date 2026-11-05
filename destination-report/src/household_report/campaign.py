"""Campaign lifecycle, deterministic chunk planning and coverage policy.

This module owns what a campaign means: who may start/finish/extend/finalize it,
which capture windows are claimable once settled, how gaps stay visible instead of
being advanced past, and how the reviewed namespace file is pinned at start. Storage
owns the rows and the atomic leases; this module owns the decisions.

Chunk windows are UTC half-open and deterministic. Local calendar days are derived
only for display and are DST-aware and clipped to the UTC campaign bounds.

This module performs no network calls and never touches the resolver.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .gaming import GamingDataError, load_namespace_list
from .storage import CHUNK_STATES, StorageError, Store

DEFAULT_DAYS = 3
ALLOWED_DAYS = (3, 4, 5)
ALLOWED_DURATION_HOURS = frozenset({72, 96, 120})
DEFAULT_RETENTION_DAYS = 7
RETENTION_MIN_DAYS = 1
RETENTION_MAX_DAYS = 30

#: One capture window is at most one hour and settles 120 seconds after it closes.
CHUNK_MAX_SECONDS = 3600
SETTLING_GRACE_SECONDS = 120
#: One later, bounded reconciliation capture for a recently completed chunk.
RECONCILE_DELAY_SECONDS = 600
#: Finalization/backfill allowance after the recorded end; no infinite retry.
FINALIZATION_ALLOWANCE_SECONDS = 24 * 3600
MAX_CHUNK_ATTEMPTS = 3
MAX_CAMPAIGN_HOURS = 120
WORKER_LEASE_SECONDS = 300
MAX_TICK_CHUNKS = 10

CAMPAIGN_STATES = ("active", "finalizing", "complete", "complete_with_gaps")
JOB_KINDS = ("capture", "report")
#: Chunk states that count as fully resolved evidence.
RESOLVED_TERMINAL_STATES = ("imported", "successful_empty")


class CampaignError(ValueError):
    """A campaign request is invalid, out of order or already decided."""


def duration_hours(days: int) -> int:
    """Elapsed UTC hours for an allowed 3/4/5-day campaign."""
    if int(days) not in ALLOWED_DAYS:
        raise CampaignError(
            f"Campaign duration must be {', '.join(str(day) for day in ALLOWED_DAYS)} days"
        )
    return int(days) * 24


def validate_retention(days: int) -> int:
    """Retention is chosen before start and bounded like the spec's suggested range."""
    if not RETENTION_MIN_DAYS <= int(days) <= RETENTION_MAX_DAYS:
        raise CampaignError(
            f"Retention must be between {RETENTION_MIN_DAYS} and {RETENTION_MAX_DAYS} days"
        )
    return int(days)


def plan_chunk_windows(
    start_epoch: int, end_epoch: int, *, chunk_seconds: int = CHUNK_MAX_SECONDS
) -> list[tuple[int, int]]:
    """Prospective non-overlapping half-open windows, clipped to the campaign bounds.

    The first and last chunks may be partial when the campaign start/end do not fall
    on a chunk boundary; every window is strictly inside ``[start_epoch, end_epoch)``.
    """
    if start_epoch >= end_epoch:
        raise CampaignError("Chunk planning needs a positive campaign window")
    if chunk_seconds <= 0:
        raise CampaignError("Chunk width must be positive")
    windows: list[tuple[int, int]] = []
    cursor = start_epoch
    while cursor < end_epoch:
        window_end = min(end_epoch, cursor + chunk_seconds)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def chunk_id(campaign_id: str, start_epoch: int, end_epoch: int) -> str:
    return f"{campaign_id}:{start_epoch}:{end_epoch}"


def settling_until(chunk_end: int) -> int:
    """A chunk becomes claimable once its window has been closed for the grace period."""
    return int(chunk_end) + SETTLING_GRACE_SECONDS


def is_eligible(
    campaign: Mapping[str, object], chunk: Mapping[str, object], *, now_epoch: int
) -> bool:
    """Whether one capture window may be claimed right now.

    Guards every boundary the bridge must never cross: the window must already be
    settled, remain inside the recorded campaign bounds, still be within the
    finalization allowance, and have retry headroom left. A backward wall-clock jump
    simply keeps ``now_epoch`` below the settling time, so no new work is issued.
    """
    if campaign["state"] in ("complete", "complete_with_gaps"):
        return False
    if chunk["state"] not in ("scheduled", "failed"):
        return False
    if int(chunk["end_epoch"]) > int(campaign["end_epoch"]):
        return False
    if now_epoch < int(chunk["settling_until"]):
        return False
    if int(chunk["attempts"]) >= MAX_CHUNK_ATTEMPTS:
        return False
    deadline = campaign.get("finalization_deadline")
    if deadline is not None and now_epoch > int(deadline):
        return False
    return True


def covered_local_days(start_epoch: int, end_epoch: int, timezone: str) -> list[tuple[int, int]]:
    """Each local calendar day intersecting the window, clipped and DST-aware.

    Returns half-open UTC spans: a fall-back day containing a repeated hour is one
    longer span and a spring-forward day is one shorter span. Days with no overlap
    with the window are omitted.
    """
    if end_epoch <= start_epoch:
        raise CampaignError("Day clipping needs a positive window")
    zone = ZoneInfo(timezone)
    start_date = datetime.fromtimestamp(start_epoch, tz=zone).date()
    end_date = datetime.fromtimestamp(end_epoch - 1, tz=zone).date()
    days: list[tuple[int, int]] = []
    cursor = start_date
    while cursor <= end_date:
        day_start = _local_midnight_utc(cursor, zone)
        day_end = _local_midnight_utc(cursor + timedelta(days=1), zone)
        low = max(day_start, start_epoch)
        high = min(day_end, end_epoch)
        if high > low:
            days.append((low, high))
        cursor += timedelta(days=1)
    return days


def _local_midnight_utc(day, zone: ZoneInfo) -> int:
    naive = datetime(day.year, day.month, day.day)
    return int(naive.replace(tzinfo=zone, fold=0).timestamp())


def coverage_summary(
    chunks: Sequence[Mapping[str, object]],
    *,
    campaign_start: int,
    campaign_end: int,
    now_epoch: int,
) -> dict[str, object]:
    """Coverage by chunk state, with explicit unresolved intervals.

    Coverage tracks acquisition, never household visibility: a quiet scheduled
    window and an expired window are different and both stay visible. The scheduled
    count is split into open, settling and ready-to-capture windows.
    """
    counts: Counter[str] = Counter(str(chunk["state"]) for chunk in chunks)
    scheduled = counts["scheduled"]
    settling = 0
    ready = 0
    oldest_ready: int | None = None
    oldest_import_pending: int | None = None
    for chunk in chunks:
        if chunk["state"] == "scheduled" and int(chunk["end_epoch"]) <= now_epoch:
            scheduled -= 1
            if now_epoch < int(chunk["settling_until"]):
                settling += 1
            else:
                ready += 1
                moment = int(chunk["settling_until"])
                oldest_ready = moment if oldest_ready is None else min(oldest_ready, moment)
        elif chunk["state"] in ("captured", "import_pending"):
            captured = chunk.get("captured_utc")
            if captured:
                moment = int(
                    datetime.fromisoformat(str(captured).replace("Z", "+00:00")).timestamp()
                )
                oldest_import_pending = (
                    moment if oldest_import_pending is None else min(oldest_import_pending, moment)
                )
    counts["scheduled"] = scheduled
    counts["settling"] = settling
    counts["ready_to_capture"] = ready
    unresolved = [
        {
            "start_epoch": int(chunk["start_epoch"]),
            "end_epoch": int(chunk["end_epoch"]),
            "state": chunk["state"],
        }
        for chunk in chunks
        if chunk["state"] not in RESOLVED_TERMINAL_STATES
    ]
    planned = len(chunks)
    ordered = {
        name: int(counts.get(name, 0)) for name in CHUNK_STATES + ("settling", "ready_to_capture")
    }
    return {
        "campaign_seconds": int(campaign_end) - int(campaign_start),
        "chunks_planned": planned,
        "by_state": ordered,
        "unresolved_chunks": len(unresolved),
        "unresolved_intervals": unresolved,
        "oldest_ready_epoch": oldest_ready,
        "oldest_import_pending_epoch": oldest_import_pending,
        "reconciliation_pending": sum(
            chunk["state"] in RESOLVED_TERMINAL_STATES and not chunk.get("reconciled_utc")
            for chunk in chunks
        ),
        "fully_resolved": all(chunk["state"] in RESOLVED_TERMINAL_STATES for chunk in chunks),
        "note": "Coverage describes acquisition, not household visibility or inactivity.",
    }


def finalize_outcome(chunks: Sequence[Mapping[str, object]]) -> str:
    """Complete only when every planned window imported successful evidence."""
    if all(chunk["state"] in RESOLVED_TERMINAL_STATES for chunk in chunks):
        return "complete"
    return "complete_with_gaps"


def extension_allowed(campaign: Mapping[str, object], candidate_end: int) -> None:
    """Extensions are owner-only-in-practice, while active, and capped by start + 120h."""
    if int(campaign["end_epoch"]) >= int(candidate_end):
        raise CampaignError("Extension must move the end forward")
    maximum = int(campaign["start_epoch"]) + MAX_CAMPAIGN_HOURS * 3600
    if int(candidate_end) > maximum:
        raise CampaignError(
            f"An extension cannot exceed {MAX_CAMPAIGN_HOURS} hours from the original start"
        )


class CampaignService:
    """Offline orchestration: lifecycle, planning, claims and coverage.

    ``now`` is an injectable epoch clock so tests can drive deterministic boundaries
    without waiting. All output is sanitized: only IDs, bounds, states and counts;
    never namespace rule content, domains or secrets.
    """

    def __init__(
        self,
        store: Store,
        *,
        now: Callable[[], int] | None = None,
        timezone: str = "UTC",
        namespace_path: str | Path | None = None,
    ) -> None:
        self._store = store
        self._now = now or (lambda: int(datetime.now(UTC).timestamp()))
        self._timezone = timezone
        self._namespace_path = Path(namespace_path) if namespace_path else None

    # -- clock helpers ----------------------------------------------------
    def now_epoch(self) -> int:
        return int(self._now())

    def _iso(self, epoch: int) -> str:
        return (
            datetime.fromtimestamp(int(epoch), UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    def _select(self, campaign_id: str | None) -> dict[str, object]:
        if campaign_id is None:
            unfinished = self._store.current_unfinished()
            if unfinished is None:
                raise CampaignError("No active or finalizing campaign; pass --campaign")
            return unfinished
        return self._store.campaign(campaign_id)

    # -- lifecycle --------------------------------------------------------
    def start(
        self,
        *,
        days: int | None = None,
        retention_days: int | None = None,
        timezone: str | None = None,
        ack_empty: bool = False,
    ) -> dict[str, object]:
        """Start the one active campaign after pinning reviewed rules.

        The namespace file must be present and valid; a valid-but-empty set needs
        explicit owner acknowledgment. Earlier history is never imported here.
        """
        days = DEFAULT_DAYS if days is None else int(days)
        retention_days = DEFAULT_RETENTION_DAYS if retention_days is None else int(retention_days)
        tz = timezone or self._timezone
        hours = duration_hours(days)
        validate_retention(retention_days)
        if self._store.current_unfinished() is not None:
            raise CampaignError("Only one campaign may be active or finalizing at a time")
        revision, sha256, state, rules = self._namespace_document()
        if not rules and not ack_empty:
            raise CampaignError(
                "A valid-empty namespace set requires owner acknowledgment (--ack-empty)"
            )
        now = self.now_epoch()
        end = now + hours * 3600
        campaign_id = f"camp-{secrets.token_hex(8)}"
        try:
            self._store.create_campaign(
                campaign_id=campaign_id,
                start_epoch=now,
                end_epoch=end,
                timezone=tz,
                retention_days=retention_days,
                rules_revision=revision,
                rules_sha256=sha256,
                rules_state=state,
                rules_ack=ack_empty,
                rules_json=[dict(rule) for rule in rules],
                now_utc=self._iso(now),
            )
        except StorageError as error:
            raise CampaignError(str(error)) from error
        self.plan(campaign_id)
        return self.status(campaign_id)

    def _namespace_document(self) -> tuple[str | None, str, str, list[dict[str, str]]]:
        raw: bytes | None
        if self._namespace_path is None:
            raw = None
        else:
            try:
                raw = self._namespace_path.read_bytes()
            except FileNotFoundError:
                raw = None
            except OSError:
                raw = b""
        try:
            namespaces = load_namespace_list(raw)
        except GamingDataError as error:
            raise CampaignError(f"Namespace rules are invalid: {error}") from error
        if namespaces.state != "available":
            raise CampaignError(
                "Namespace rules are missing; campaign readiness requires reviewed rules"
            )
        sha256 = namespaces.sha256 or hashlib.sha256(raw or b"").hexdigest()
        return (
            namespaces.revision,
            sha256,
            namespaces.state,
            [dict(rule) for rule in namespaces.rules],
        )

    def finish_early(self, campaign_id: str | None = None) -> dict[str, object]:
        """Owner early finish clips the end and opens the finalization allowance."""
        campaign = self._select(campaign_id)
        if campaign["state"] != "active":
            raise CampaignError(f"Cannot finish a {campaign['state']} campaign early")
        now = self.now_epoch()
        if now <= int(campaign["start_epoch"]):
            raise CampaignError("Early finish needs elapsed campaign time")
        end = min(int(campaign["end_epoch"]), now)
        if not self._store.finish_campaign_early(
            campaign["campaign_id"],
            end_epoch=end,
            now_utc=self._iso(now),
            allowance=FINALIZATION_ALLOWANCE_SECONDS,
        ):
            raise CampaignError("Campaign state changed concurrently; retry")
        return self.status(campaign["campaign_id"])

    def extend(self, hours: int, campaign_id: str | None = None) -> dict[str, object]:
        """Owner-only extension while active; never beyond start + 120 hours."""
        hours = int(hours)
        if hours < 1:
            raise CampaignError("Extension hours must be positive")
        campaign = self._select(campaign_id)
        if campaign["state"] != "active":
            raise CampaignError("Only an active campaign can be extended")
        new_end = int(campaign["end_epoch"]) + hours * 3600
        extension_allowed(campaign, new_end)
        changed = self._store.extend_campaign(
            campaign["campaign_id"],
            candidate_end=new_end,
            now_utc=self._iso(self.now_epoch()),
        )
        if not changed:
            raise CampaignError("Campaign state changed concurrently; retry")
        self.plan(campaign["campaign_id"])
        return self.status(campaign["campaign_id"])

    def finalize(self, campaign_id: str | None = None) -> dict[str, object]:
        """Bounded finalization: resolve or expire chunks, then mark complete(-with-gaps)."""
        campaign = self._select(campaign_id)
        now = self.now_epoch()
        if campaign["state"] == "active":
            campaign = self._advance_to_finalizing(campaign["campaign_id"], now)
        if campaign["state"] != "finalizing":
            raise CampaignError(f"A {campaign['state']} campaign is not finalizable")
        if now < int(campaign["end_epoch"]):
            raise CampaignError("Finalization requires the recorded end to have passed")
        self.plan(campaign["campaign_id"])
        chunks = [
            chunk
            for chunk in self._store.chunks(campaign["campaign_id"])
            if int(chunk["end_epoch"]) <= int(campaign["end_epoch"])
        ]
        unresolved = [
            chunk["chunk_id"]
            for chunk in chunks
            if chunk["state"] not in (*RESOLVED_TERMINAL_STATES, "partial", "expired")
        ]
        deadline = int(campaign["finalization_deadline"])
        unreconciled = any(
            chunk["state"] in RESOLVED_TERMINAL_STATES and not chunk.get("reconciled_utc")
            for chunk in chunks
        )
        if (unresolved or unreconciled) and now < deadline:
            # Backfill and retry remain possible until the original allowance
            # expires. Never mark missing source history as complete early.
            return self.status(campaign["campaign_id"])
        if unresolved:
            self._store.expire_chunks(
                campaign["campaign_id"],
                chunk_ids=unresolved,
                reason="finalization deadline reached",
                now_utc=self._iso(now),
            )
            chunks = [
                chunk
                for chunk in self._store.chunks(campaign["campaign_id"])
                if int(chunk["end_epoch"]) <= int(campaign["end_epoch"])
            ]
        outcome = "complete_with_gaps" if unreconciled else finalize_outcome(chunks)
        changed = self._store.transition_campaign(
            campaign["campaign_id"],
            expected_state="finalizing",
            new_state=outcome,
            now_utc=self._iso(now),
        )
        if not changed:
            raise CampaignError("Campaign state changed concurrently; retry")
        self._store.record_owner_event(
            campaign["campaign_id"], action="finalized", detail=outcome, now_utc=self._iso(now)
        )
        return self.status(campaign["campaign_id"])

    def _advance_to_finalizing(self, campaign_id: str, now: int) -> dict[str, object]:
        campaign = self._store.campaign(campaign_id)
        if campaign["state"] != "active" or now < int(campaign["end_epoch"]):
            return campaign
        deadline = int(campaign["end_epoch"]) + FINALIZATION_ALLOWANCE_SECONDS
        self._store.transition_campaign(
            campaign_id,
            expected_state="active",
            new_state="finalizing",
            end_epoch=int(campaign["end_epoch"]),
            finalization_deadline=deadline,
            now_utc=self._iso(now),
        )
        self._store.record_owner_event(
            campaign_id,
            action="end_reached",
            detail=f"end {campaign['end_epoch']}",
            now_utc=self._iso(now),
        )
        return self._store.campaign(campaign_id)

    # -- source identity (read-only, fail-closed) ---------------------------
    def check_source_identity(self, *, generation_id: str, identity: str) -> dict[str, object]:
        """Read-only comparison of configured generation/identity with the canonical
        record. Never registers, never upserts, never rebinds; a mismatch is a hard
        failure with an actionable sanitized code. First registration is the explicit
        ``source-register`` owner action, and a changed resolver generation requires a
        new generation record, not relabelling historical rows."""
        if not generation_id or not re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", generation_id):
            raise CampaignError("Invalid source generation identifier")
        try:
            record = self._store.source_generation(generation_id)
        except StorageError:
            return {
                "verified": False,
                "code": "unknown_generation",
                "generation_id": generation_id,
            }
        if str(record["identity"]) != str(identity):
            return {
                "verified": False,
                "code": "identity_mismatch",
                "generation_id": generation_id,
            }
        return {
            "verified": True,
            "code": "ok",
            "generation_id": generation_id,
        }

    # -- planning and claims ----------------------------------------------
    def plan(self, campaign_id: str | None = None) -> int:
        """Plan prospective chunks clipped to the campaign end; idempotent by window."""
        campaign = self._select(campaign_id)
        if campaign["state"] in ("complete", "complete_with_gaps"):
            return 0
        now = self.now_epoch()
        if campaign["state"] == "finalizing":
            deadline = campaign.get("finalization_deadline")
            if deadline is not None and now > int(deadline):
                return 0
        start, end = int(campaign["start_epoch"]), int(campaign["end_epoch"])
        windows = plan_chunk_windows(start, end)
        plans = [
            {
                "chunk_id": chunk_id(campaign["campaign_id"], window_start, window_end),
                "start_epoch": window_start,
                "end_epoch": window_end,
                "settling_until": settling_until(window_end),
            }
            for window_start, window_end in windows
        ]
        return self._store.plan_chunks(campaign["campaign_id"], plans)

    def claim_capture_work(
        self,
        *,
        worker: str = "worker",
        campaign_id: str | None = None,
        limit: int = 10,
        generation_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Claim up to ``limit`` settled windows; returns sanitized work descriptors."""
        if not 1 <= limit <= MAX_TICK_CHUNKS:
            raise CampaignError(f"Claim limit must be between 1 and {MAX_TICK_CHUNKS}")
        campaign = self._select(campaign_id)
        now = self.now_epoch()
        if campaign["state"] == "active" and now >= int(campaign["end_epoch"]):
            # Forward jumps enforce the original bounds: capture continues only
            # inside the 24-hour finalization allowance after the recorded end.
            campaign = self._advance_to_finalizing(campaign["campaign_id"], now)
        if campaign["state"] in ("complete", "complete_with_gaps"):
            return []
        if not self._store.observe_campaign_clock(campaign["campaign_id"], epoch=now):
            return []
        now = self.now_epoch()
        chunks = [
            chunk
            for chunk in self._store.chunks(campaign["campaign_id"])
            if int(chunk["end_epoch"]) <= int(campaign["end_epoch"])
        ]
        if generation_id:
            self._store.source_generation(generation_id)
            for chunk in chunks:
                if chunk["state"] == "scheduled" and chunk["generation_id"] is None:
                    self._store.bind_chunk_generation(
                        campaign["campaign_id"],
                        chunk_id=chunk["chunk_id"],
                        generation_id=generation_id,
                    )
            chunks = [
                chunk
                for chunk in self._store.chunks(campaign["campaign_id"])
                if int(chunk["end_epoch"]) <= int(campaign["end_epoch"])
            ]
        eligible = [
            chunk["chunk_id"]
            for chunk in chunks
            if is_eligible(campaign, chunk, now_epoch=now)
            and (generation_id is None or chunk["generation_id"] == generation_id)
        ]
        claimed = self._store.claim_chunks(
            campaign["campaign_id"],
            chunk_ids=eligible,
            worker=worker,
            lease_seconds=WORKER_LEASE_SECONDS,
            limit=limit,
            now_utc=self._iso(now),
        )
        result: list[dict[str, object]] = []
        for chunk_id, token in claimed.items():
            chunk = self._store.chunk(campaign["campaign_id"], chunk_id)
            result.append(
                {
                    "chunk_id": chunk_id,
                    "campaign_id": campaign["campaign_id"],
                    "start_epoch": int(chunk["start_epoch"]),
                    "end_epoch": int(chunk["end_epoch"]),
                    "settling_until": int(chunk["settling_until"]),
                    "lease_token": token,
                    "generation_id": chunk["generation_id"],
                }
            )
        return result

    def ack_capture(
        self,
        chunk_id: str,
        *,
        token: str,
        outcome: str = "captured",
        digest: str | None = None,
        path: str | None = None,
        gap_reason: str | None = None,
        campaign_id: str | None = None,
    ) -> bool:
        campaign = self._select(campaign_id)
        return self._store.ack_capture(
            campaign["campaign_id"],
            chunk_id=chunk_id,
            token=token,
            outcome=outcome,
            artifact_digest=digest,
            artifact_path=path,
            gap_reason=gap_reason,
            now_utc=self._iso(self.now_epoch()),
        )

    def mark_import_pending(self, chunk_id: str, *, campaign_id: str | None = None) -> bool:
        campaign = self._select(campaign_id)
        return self._store.mark_import_pending(
            campaign["campaign_id"], chunk_id=chunk_id, now_utc=self._iso(self.now_epoch())
        )

    def ack_import(
        self,
        chunk_id: str,
        *,
        outcome: str,
        gap_reason: str | None = None,
        campaign_id: str | None = None,
    ) -> bool:
        campaign = self._select(campaign_id)
        return self._store.ack_import(
            campaign["campaign_id"],
            chunk_id=chunk_id,
            outcome=outcome,
            gap_reason=gap_reason,
            now_utc=self._iso(self.now_epoch()),
        )

    # -- report jobs (typed metadata; frozen generation arrives in B3) ----
    def create_report_job(
        self,
        *,
        dedup_key: str,
        params: Mapping[str, object] | None = None,
        campaign_id: str | None = None,
    ) -> str:
        campaign = self._select(campaign_id)
        job_id = f"job-{secrets.token_hex(12)}"
        created, _ = self._store.create_job(
            job_id=job_id,
            campaign_id=campaign["campaign_id"],
            kind="report",
            dedup_key=dedup_key,
            params=params,
            now_utc=self._iso(self.now_epoch()),
        )
        return created

    def claim_report_job(
        self, *, worker: str = "worker", campaign_id: str | None = None
    ) -> dict[str, object] | None:
        campaign = self._select(campaign_id)
        pending = self._store.pending_jobs(
            campaign["campaign_id"], kind="report", now_utc=self._iso(self.now_epoch())
        )
        if not pending:
            return None
        job_id = str(pending[0]["job_id"])
        token, claimed = self._store.claim_job(
            job_id,
            worker=worker,
            lease_seconds=WORKER_LEASE_SECONDS,
            now_utc=self._iso(self.now_epoch()),
        )
        if not claimed:
            return None
        job = self._store.job(job_id)
        return {
            "job_id": job_id,
            "kind": "report",
            "campaign_id": campaign["campaign_id"],
            "lease_token": token,
            "params": job.get("params_json"),
        }

    def finish_report_job(
        self,
        job_id: str,
        *,
        token: str,
        state: str,
        sanitized_error: str | None = None,
    ) -> bool:
        return self._store.finish_job(
            job_id,
            token=token,
            state=state,
            sanitized_error=sanitized_error,
            now_utc=self._iso(self.now_epoch()),
        )

    # -- status -----------------------------------------------------------
    def status(self, campaign_id: str | None = None) -> dict[str, object]:
        """Sanitized campaign status: IDs, bounds, states and coverage only."""
        campaign = self._select(campaign_id)
        chunks = [
            chunk
            for chunk in self._store.chunks(campaign["campaign_id"])
            if int(chunk["end_epoch"]) <= int(campaign["end_epoch"])
        ]
        summary = coverage_summary(
            chunks,
            campaign_start=int(campaign["start_epoch"]),
            campaign_end=int(campaign["end_epoch"]),
            now_epoch=self.now_epoch(),
        )
        return {
            "campaign_id": campaign["campaign_id"],
            "state": campaign["state"],
            "utc_bounds": [int(campaign["start_epoch"]), int(campaign["end_epoch"])],
            "timezone": campaign["timezone"],
            "retention_days": int(campaign["retention_days"]),
            "rules_revision": campaign.get("rules_revision"),
            "rules_sha256": campaign["rules_sha256"],
            "rules_state": campaign["rules_state"],
            "rules_empty_acknowledged": bool(campaign["rules_ack"]),
            "created_utc": campaign["created_utc"],
            "updated_utc": campaign["updated_utc"],
            "finalization_deadline_epoch": campaign.get("finalization_deadline"),
            "coverage": summary,
        }

    def list_status(self) -> list[dict[str, object]]:
        """Every campaign's sanitized header, newest first."""
        headers = []
        for row in self._store.campaigns():
            headers.append(
                {
                    "campaign_id": row["campaign_id"],
                    "state": row["state"],
                    "utc_bounds": [int(row["start_epoch"]), int(row["end_epoch"])],
                    "retention_days": int(row["retention_days"]),
                    "rules_revision": row.get("rules_revision"),
                    "created_utc": row["created_utc"],
                }
            )
        return headers


__all__ = [
    "ALLOWED_DAYS",
    "CAMPAIGN_STATES",
    "CHUNK_MAX_SECONDS",
    "CampaignError",
    "CampaignService",
    "FINALIZATION_ALLOWANCE_SECONDS",
    "JOB_KINDS",
    "MAX_CHUNK_ATTEMPTS",
    "MAX_TICK_CHUNKS",
    "MAX_CAMPAIGN_HOURS",
    "RECONCILE_DELAY_SECONDS",
    "RESOLVED_TERMINAL_STATES",
    "SETTLING_GRACE_SECONDS",
    "chunk_id",
    "covered_local_days",
    "coverage_summary",
    "duration_hours",
    "extension_allowed",
    "finalize_outcome",
    "is_eligible",
    "plan_chunk_windows",
    "settling_until",
    "validate_retention",
]
