"""The single SQLite implementation: schema, transactions and named operations.

All application SQL lives here. Feature modules own policy (what a rule means, when
a job may run, which candidates are public); this module owns atomicity, immutability
and the accounting ledger. There is no generic repository interface: one concrete
store backs the application.

Accounting invariant: every dispatch reserves inside ``BEGIN IMMEDIATE`` using the
same ``call_attempts`` rows that later record usage. There is no separate daily
counter to drift, and an unconfirmed attempt stays fully reserved.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .capture_contract import validate_campaign_snapshot
from .contracts import (
    ATTEMPT_KINDS,
    INTERPRETATION_VERSION,
    AttemptBudget,
    ContractError,
    Period,
    SnapshotRef,
)

SCHEMA_VERSION = 7

#: Capture chunk states trusted by the campaign service. Scheduled covers an open
#: window; a chunk becomes claimable after its settling_until. Imported and
#: successful-empty are fully resolved; partial, expired and failed describe gaps
#: that remain explicitly visible instead of being advanced past.
CHUNK_STATES = (
    "scheduled",
    "settling",
    "captured",
    "successful_empty",
    "import_pending",
    "imported",
    "partial",
    "failed",
    "expired",
    "identity_unknown",
)

#: Attempt outcomes that still consume budget. A reserved row becomes one of the
#: terminal outcomes after a single adapter attempt; nothing is ever deleted.
CHARGEABLE_OUTCOMES = ("reserved", "dispatched", "unconfirmed", "ok", "error", "timeout")

_ROW_COLUMNS = (
    "id",
    "timestamp",
    "type",
    "status",
    "domain",
    "client",
    "forward",
    "additional_info",
    "list_id",
    "reply_type",
    "ede",
    "reply_time",
    "dnssec",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id     TEXT PRIMARY KEY,
  datasource      TEXT NOT NULL,
  schema_version  INTEGER NOT NULL,
  import_version  INTEGER NOT NULL,
  start_epoch     INTEGER NOT NULL,
  end_epoch       INTEGER NOT NULL,
  captured_utc    TEXT NOT NULL,
  retained_rows   INTEGER,
  oldest_epoch    REAL,
  newest_epoch    REAL,
  window_count    INTEGER NOT NULL,
  data_sha256     TEXT NOT NULL,
  created_utc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dns_rows (
  snapshot_id     TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
  row_id          INTEGER NOT NULL,
  timestamp       REAL NOT NULL,
  qtype           INTEGER,
  status          INTEGER,
  reply_type      INTEGER,
  ede             INTEGER,
  domain          TEXT NOT NULL,
  client          TEXT NOT NULL,
  forward         TEXT,
  additional_info TEXT,
  list_id         INTEGER,
  reply_time      REAL,
  dnssec          INTEGER,
  PRIMARY KEY (snapshot_id, row_id)
);
CREATE INDEX IF NOT EXISTS dns_rows_domain_time ON dns_rows(snapshot_id, domain, timestamp);
CREATE INDEX IF NOT EXISTS dns_rows_time ON dns_rows(snapshot_id, timestamp);

CREATE TABLE IF NOT EXISTS reports (
  report_id              INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id            TEXT NOT NULL REFERENCES snapshots(snapshot_id),
  period_digest          TEXT NOT NULL,
  interpretation_version INTEGER NOT NULL,
  created_utc            TEXT NOT NULL,
  payload_json           TEXT NOT NULL,
  UNIQUE (period_digest, interpretation_version)
);

CREATE TABLE IF NOT EXISTS classifications (
  classification_id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain            TEXT NOT NULL,
  match             TEXT NOT NULL CHECK (match IN ('exact', 'suffix')),
  field_scope       TEXT NOT NULL CHECK (field_scope IN ('service_and_provider', 'provider_only', 'broad_only')),
  service           TEXT,
  provider          TEXT,
  category          TEXT,
  confidence        TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low', 'unknown')),
  ambiguity         TEXT,
  method            TEXT NOT NULL,
  verification_state TEXT NOT NULL,
  checked_utc       TEXT NOT NULL,
  verified_until    TEXT,
  policy_revision   INTEGER NOT NULL,
  evidence_json     TEXT NOT NULL DEFAULT '[]',
  source_hash       TEXT,
  model_provenance  TEXT,
  UNIQUE (domain, match, field_scope, policy_revision, checked_utc)
);

CREATE TABLE IF NOT EXISTS analyses (
  analysis_id         TEXT PRIMARY KEY,
  state               TEXT NOT NULL CHECK (state IN ('queued', 'running', 'paused', 'completed', 'partial', 'failed', 'cancelled')),
  period_digest       TEXT NOT NULL,
  selection_digest    TEXT NOT NULL,
  analyzer_version    INTEGER NOT NULL,
  provider            TEXT,
  model_id            TEXT,
  config_fingerprint  TEXT,
  policy_revision     INTEGER,
  summary             TEXT,
  created_utc         TEXT NOT NULL,
  updated_utc         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_items (
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
  item_id     TEXT NOT NULL,
  domain      TEXT NOT NULL,
  claim_scope TEXT NOT NULL,
  state       TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'done', 'unknown', 'deferred', 'failed')),
  attempts    INTEGER NOT NULL DEFAULT 0,
  lease_until TEXT,
  result_json TEXT,
  error       TEXT,
  PRIMARY KEY (analysis_id, item_id)
);
CREATE INDEX IF NOT EXISTS analysis_items_state ON analysis_items(analysis_id, state);

CREATE TABLE IF NOT EXISTS call_attempts (
  attempt_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id     TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
  item_id         TEXT,
  kind            TEXT NOT NULL,
  dispatch_day    TEXT NOT NULL,
  created_utc     TEXT NOT NULL,
  reserved_tokens INTEGER NOT NULL DEFAULT 0,
  prompt_tokens   INTEGER,
  completion_tokens INTEGER,
  outcome         TEXT NOT NULL,
  error_class     TEXT,
  detail_json     TEXT
);
CREATE INDEX IF NOT EXISTS call_attempts_day ON call_attempts(dispatch_day);
CREATE INDEX IF NOT EXISTS call_attempts_analysis_kind ON call_attempts(analysis_id, kind);

CREATE TABLE IF NOT EXISTS inventory_polls (
  poll_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  polled_utc  TEXT NOT NULL,
  source      TEXT NOT NULL,
  ok          INTEGER NOT NULL,
  error       TEXT,
  clients_json TEXT,
  poll_digest TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_polls_digest ON inventory_polls(poll_digest);

CREATE TABLE IF NOT EXISTS device_settings (
  revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_key  TEXT NOT NULL,
  display_name TEXT,
  category    TEXT,
  created_utc TEXT NOT NULL,
  supersedes  INTEGER
);
CREATE INDEX IF NOT EXISTS device_settings_device ON device_settings(device_key, revision_id);

CREATE TABLE IF NOT EXISTS device_bindings (
  binding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  device_key    TEXT NOT NULL,
  observed_ip   TEXT,
  observed_mac  TEXT,
  valid_from_utc TEXT NOT NULL,
  valid_to_utc  TEXT,
  source        TEXT NOT NULL,
  evidence_json TEXT
);
CREATE INDEX IF NOT EXISTS device_bindings_device ON device_bindings(device_key, valid_from_utc);
"""

# Schema v3 is additive and preserves every v2 table unchanged: campaign lifecycle,
# durable capture chunks with leases, typed local jobs and immutable frozen report
# metadata. The partial unique index on campaigns enforces the one-unfinished
# campaign invariant at the database level even across concurrent writers.
_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS campaigns (
  campaign_id            TEXT PRIMARY KEY,
  state                  TEXT NOT NULL CHECK (state IN ('active','finalizing','complete','complete_with_gaps')),
  start_epoch            INTEGER NOT NULL,
  end_epoch              INTEGER NOT NULL,
  timezone               TEXT NOT NULL,
  retention_days         INTEGER NOT NULL,
  rules_revision         TEXT,
  rules_sha256           TEXT NOT NULL,
  rules_state            TEXT NOT NULL CHECK (rules_state IN ('available','unavailable')),
  rules_ack              INTEGER NOT NULL DEFAULT 0,
  rules_json             TEXT NOT NULL DEFAULT '[]',
  created_utc            TEXT NOT NULL,
  updated_utc            TEXT NOT NULL,
  finalization_deadline  INTEGER,
  last_clock_epoch       INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS campaigns_one_unfinished
  ON campaigns((1)) WHERE state IN ('active','finalizing');

CREATE TABLE IF NOT EXISTS campaign_owner_events (
  event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id  TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
  action       TEXT NOT NULL,
  detail       TEXT,
  occurred_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS campaign_owner_events_campaign
  ON campaign_owner_events(campaign_id, event_id);

CREATE TABLE IF NOT EXISTS source_generations (
  generation_id  TEXT PRIMARY KEY,
  identity       TEXT NOT NULL,
  configured_utc TEXT NOT NULL,
  notes          TEXT
);

CREATE TABLE IF NOT EXISTS capture_chunks (
  chunk_id        TEXT PRIMARY KEY,
  campaign_id     TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
  start_epoch     INTEGER NOT NULL,
  end_epoch       INTEGER NOT NULL,
  settling_until  INTEGER NOT NULL,
  generation_id   TEXT REFERENCES source_generations(generation_id),
  state           TEXT NOT NULL,
  attempts        INTEGER NOT NULL DEFAULT 0,
  captured_utc    TEXT,
  artifact_digest TEXT,
  artifact_path   TEXT,
  import_outcome  TEXT,
  import_utc      TEXT,
  reconciled_utc  TEXT,
  lease_token     TEXT,
  lease_until     TEXT,
  gap_reason      TEXT,
  created_utc     TEXT NOT NULL,
  updated_utc     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS capture_chunks_window
  ON capture_chunks(campaign_id, start_epoch, end_epoch);
CREATE INDEX IF NOT EXISTS capture_chunks_campaign
  ON capture_chunks(campaign_id, start_epoch);

CREATE TABLE IF NOT EXISTS capture_attempts (
  attempt_token TEXT PRIMARY KEY,
  chunk_id      TEXT NOT NULL REFERENCES capture_chunks(chunk_id) ON DELETE CASCADE,
  worker        TEXT NOT NULL,
  claimed_utc   TEXT NOT NULL,
  lease_until   TEXT NOT NULL,
  outcome       TEXT,
  finished_utc  TEXT
);
CREATE INDEX IF NOT EXISTS capture_attempts_chunk ON capture_attempts(chunk_id, claimed_utc);

CREATE TABLE IF NOT EXISTS local_jobs (
  job_id          TEXT PRIMARY KEY,
  campaign_id     TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
  kind            TEXT NOT NULL CHECK (kind IN ('capture','report')),
  dedup_key       TEXT,
  state           TEXT NOT NULL CHECK (state IN ('queued','running','ready','failed')),
  attempts        INTEGER NOT NULL DEFAULT 0,
  lease_token     TEXT,
  lease_until     TEXT,
  params_json     TEXT,
  sanitized_error TEXT,
  created_utc     TEXT NOT NULL,
  updated_utc     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS local_jobs_dedup
  ON local_jobs(campaign_id, kind, dedup_key) WHERE dedup_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS local_jobs_campaign
  ON local_jobs(campaign_id, kind, state);

CREATE TABLE IF NOT EXISTS frozen_reports (
  report_id               TEXT PRIMARY KEY,
  campaign_id             TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
  requested_start         INTEGER NOT NULL,
  requested_end           INTEGER NOT NULL,
  actual_start            INTEGER NOT NULL,
  actual_end              INTEGER NOT NULL,
  dedup_key               TEXT NOT NULL,
  rules_sha256            TEXT NOT NULL,
  coverage_sha256         TEXT,
  capture_revisions_json  TEXT NOT NULL DEFAULT '[]',
  payload_json            TEXT NOT NULL,
  created_utc             TEXT NOT NULL,
  expires_utc             TEXT NOT NULL,
  UNIQUE (campaign_id, dedup_key)
);
CREATE INDEX IF NOT EXISTS frozen_reports_campaign
  ON frozen_reports(campaign_id, created_utc);
"""

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS campaign_queries (
  campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
  generation_id TEXT NOT NULL REFERENCES source_generations(generation_id),
  source_id INTEGER NOT NULL,
  immutable_sha256 TEXT NOT NULL,
  row_json TEXT NOT NULL,
  updated_utc TEXT NOT NULL,
  PRIMARY KEY (campaign_id, generation_id, source_id)
);
CREATE TABLE IF NOT EXISTS campaign_capture_revisions (
  chunk_id TEXT NOT NULL REFERENCES capture_chunks(chunk_id) ON DELETE CASCADE,
  artifact_digest TEXT NOT NULL,
  generation_id TEXT NOT NULL REFERENCES source_generations(generation_id),
  captured_utc TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  state TEXT NOT NULL,
  PRIMARY KEY (chunk_id, artifact_digest)
);
"""

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS campaign_rules_revisions (
  campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id) ON DELETE CASCADE,
  rules_sha256 TEXT NOT NULL,
  revision TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  rules_ack INTEGER NOT NULL DEFAULT 0,
  created_utc TEXT NOT NULL,
  PRIMARY KEY(campaign_id, rules_sha256)
);
CREATE TABLE IF NOT EXISTS campaign_job_results (
  job_id TEXT PRIMARY KEY REFERENCES local_jobs(job_id) ON DELETE CASCADE,
  report_id TEXT NOT NULL REFERENCES frozen_reports(report_id)
);
"""

_SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS campaign_retirements (
  campaign_id TEXT PRIMARY KEY,
  preview_digest TEXT NOT NULL,
  backup_choice TEXT NOT NULL,
  artifact_names_json TEXT NOT NULL,
  retired_utc TEXT NOT NULL
);
"""

_SCHEMA_V7 = """
ALTER TABLE frozen_reports ADD COLUMN predecessor_report_id TEXT;
ALTER TABLE frozen_reports ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
"""


class StorageError(RuntimeError):
    """The store rejected an operation that would violate an invariant."""


class BudgetExceeded(StorageError):
    """A dispatch was refused because a conservative reservation cannot fit."""

    def __init__(self, reason: str, scope: str) -> None:
        super().__init__(reason)
        self.scope = scope


@dataclass(frozen=True, slots=True)
class AttemptReservation:
    attempt_id: int
    analysis_id: str
    kind: str
    dispatch_day: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _charge(row: sqlite3.Row) -> int:
    """Confirmed usage replaces its reservation; unknown usage keeps it charged."""
    prompt, completion = row["prompt_tokens"], row["completion_tokens"]
    if prompt is None or completion is None:
        return int(row["reserved_tokens"])
    return int(prompt) + int(completion)


def _canonical_rows(rows: Sequence[Mapping[str, object]]) -> bytes:
    ordered = sorted(rows, key=lambda row: (float(row["timestamp"]), int(row["id"])))
    return json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode()


class Store:
    """One concrete SQLite store. Open with :meth:`open` to apply pragmas."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._conn_lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def open(cls, path: str | Path, *, timeout: float = 5.0) -> Store:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(path), isolation_level=None, timeout=timeout, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return cls(connection)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def migrate(self) -> int:
        """Apply the schema idempotently, tracking the version in ``user_version``."""
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise StorageError(
                f"Database schema {current} is newer than this application ({SCHEMA_VERSION})"
            )
        if current == SCHEMA_VERSION:
            return current
        # Every v2 table is preserved unchanged; v3 only adds campaign-owned tables.
        inventory_upgrade = ""
        if current == 1:
            existing = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(inventory_polls)")
            }
            if "poll_digest" not in existing:
                inventory_upgrade = "ALTER TABLE inventory_polls ADD COLUMN poll_digest TEXT;\n"
        # executescript commits an open Python transaction. Wrap the script itself
        # so a partially applied v3 migration can never be mistaken for success.
        try:
            self._conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + inventory_upgrade
                + (_SCHEMA if current in (0, 1) else "")
                + (_SCHEMA_V3 if current < 3 else "")
                + _SCHEMA_V4
                + _SCHEMA_V5
                + _SCHEMA_V6
                + _SCHEMA_V7
                + f"\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
            )
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        return SCHEMA_VERSION

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Short-lived write transaction; never held across network calls."""
        with self._conn_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # -- snapshots and reports (reporting-owned policy) --------------------
    def import_snapshot(
        self,
        snapshot: Mapping[str, object],
        *,
        datasource: str,
        import_version: int = 1,
    ) -> SnapshotRef:
        """Validate and preserve one extraction payload, rejecting mismatches."""
        rows = snapshot.get("observations")
        if not isinstance(rows, list) or not rows:
            raise StorageError("Snapshot has no observations")
        start = int(snapshot["start_epoch"])
        end = int(snapshot["end_epoch"])
        period = Period(start, end)
        window_count = int(snapshot["window_count"])
        if len(rows) != window_count:
            raise StorageError(
                f"Snapshot window_count {window_count} does not match {len(rows)} rows"
            )
        ids = [int(row["id"]) for row in rows]
        if len(set(ids)) != len(ids):
            raise StorageError("Snapshot contains duplicate source row ids")
        for row in rows:
            timestamp = float(row["timestamp"])
            if not period.contains(timestamp):
                raise StorageError(f"Row {row['id']} falls outside the snapshot bounds")
            if not str(row.get("domain", "")).strip():
                raise StorageError(f"Row {row['id']} has no domain")

        data_sha256 = hashlib.sha256(_canonical_rows(rows)).hexdigest()
        snapshot_id = hashlib.sha256(
            f"{datasource}\x00{import_version}\x00{data_sha256}".encode()
        ).hexdigest()
        captured = str(snapshot.get("captured_utc", ""))
        if not captured:
            raise StorageError("Snapshot is missing captured_utc")

        with self._write() as conn:
            existing = conn.execute(
                "SELECT window_count, data_sha256 FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if existing is not None:
                if existing["data_sha256"] != data_sha256:
                    raise StorageError("Snapshot identity collision with different content")
                return SnapshotRef(
                    snapshot_id=snapshot_id,
                    datasource=datasource,
                    data_sha256=data_sha256,
                    period=period,
                    captured_utc=captured,
                    window_count=window_count,
                    inserted=False,
                )
            conn.execute(
                """INSERT INTO snapshots (snapshot_id, datasource, schema_version,
                       import_version, start_epoch, end_epoch, captured_utc, retained_rows,
                       oldest_epoch, newest_epoch, window_count, data_sha256, created_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    datasource,
                    int(snapshot.get("schema_version", 1)),
                    import_version,
                    start,
                    end,
                    captured,
                    snapshot.get("retained_rows"),
                    snapshot.get("oldest_epoch"),
                    snapshot.get("newest_epoch"),
                    window_count,
                    data_sha256,
                    _utc_now(),
                ),
            )
            conn.executemany(
                """INSERT INTO dns_rows (snapshot_id, row_id, timestamp, qtype, status,
                       reply_type, ede, domain, client, forward, additional_info, list_id,
                       reply_time, dnssec)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        snapshot_id,
                        int(row["id"]),
                        float(row["timestamp"]),
                        row.get("type"),
                        row.get("status"),
                        row.get("reply_type"),
                        row.get("ede"),
                        str(row["domain"]),
                        str(row["client"]),
                        row.get("forward"),
                        row.get("additional_info"),
                        row.get("list_id"),
                        row.get("reply_time"),
                        row.get("dnssec"),
                    )
                    for row in rows
                ],
            )
        return SnapshotRef(
            snapshot_id=snapshot_id,
            datasource=datasource,
            data_sha256=data_sha256,
            period=period,
            captured_utc=captured,
            window_count=window_count,
        )

    def snapshot(self, snapshot_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown snapshot: {snapshot_id}")
        return row

    def rows(self, snapshot_id: str, period: Period | None = None) -> list[dict[str, object]]:
        """Return preserved rows in the source field order used by extraction."""
        query = "SELECT * FROM dns_rows WHERE snapshot_id = ?"
        params: list[object] = [snapshot_id]
        if period is not None:
            query += " AND timestamp >= ? AND timestamp < ?"
            params.extend([period.start_epoch, period.end_epoch])
        query += " ORDER BY timestamp, row_id"
        rows = []
        for record in self._conn.execute(query, params):
            rows.append(
                {
                    "id": record["row_id"],
                    "timestamp": record["timestamp"],
                    "type": record["qtype"],
                    "status": record["status"],
                    "domain": record["domain"],
                    "client": record["client"],
                    "forward": record["forward"],
                    "additional_info": record["additional_info"],
                    "list_id": record["list_id"],
                    "reply_type": record["reply_type"],
                    "ede": record["ede"],
                    "reply_time": record["reply_time"],
                    "dnssec": record["dnssec"],
                }
            )
        return rows

    def period_digest(
        self,
        snapshot_id: str,
        period: Period,
        *,
        interpretation_version: int = INTERPRETATION_VERSION,
    ) -> str:
        """Digest the included canonical rows, bounds, source and interpretation."""
        datasource = self.snapshot(snapshot_id)["datasource"]
        rows = self.rows(snapshot_id, period)
        if not rows:
            raise StorageError("Period contains no observations")
        payload = {
            "datasource": datasource,
            "start": period.start_epoch,
            "end": period.end_epoch,
            "interpretation": interpretation_version,
            "rows": [[row[column] for column in _ROW_COLUMNS] for row in rows],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def save_report(
        self,
        *,
        snapshot_id: str,
        period_digest: str,
        interpretation_version: int,
        payload: Mapping[str, object],
    ) -> int:
        """Store one immutable report payload; identical digests are reused."""
        with self._write() as conn:
            existing = conn.execute(
                "SELECT report_id FROM reports WHERE period_digest = ? AND interpretation_version = ?",
                (period_digest, interpretation_version),
            ).fetchone()
            if existing is not None:
                return int(existing["report_id"])
            cursor = conn.execute(
                """INSERT INTO reports (snapshot_id, period_digest, interpretation_version,
                       created_utc, payload_json) VALUES (?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    period_digest,
                    interpretation_version,
                    _utc_now(),
                    json.dumps(payload, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def report_payload(self, report_id: int) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT payload_json FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown report: {report_id}")
        return json.loads(row["payload_json"])

    # -- classification rules (classification-owned policy) ----------------
    def add_classification_rule(self, rule: Mapping[str, object]) -> int:
        """Append one immutable rule revision; later updates are new rows."""
        with self._write() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO classifications (domain, match, field_scope,
                       service, provider, category, confidence, ambiguity, method,
                       verification_state, checked_utc, verified_until, policy_revision,
                       evidence_json, source_hash, model_provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule["domain"],
                    rule["match"],
                    rule["field_scope"],
                    rule.get("service"),
                    rule.get("provider"),
                    rule.get("category"),
                    rule["confidence"],
                    rule.get("ambiguity"),
                    rule["method"],
                    rule["verification_state"],
                    rule["checked_utc"],
                    rule.get("verified_until"),
                    int(rule.get("policy_revision", 1)),
                    json.dumps(rule.get("evidence", []), sort_keys=True),
                    rule.get("source_hash"),
                    rule.get("model_provenance"),
                ),
            )
            return int(cursor.lastrowid or 0)

    def classification_rules(self) -> list[dict[str, object]]:
        """Every rule revision, newest first, for policy to resolve deterministically."""
        rules = []
        for row in self._conn.execute(
            "SELECT * FROM classifications ORDER BY classification_id DESC"
        ):
            rule = dict(row)
            rule["evidence"] = json.loads(rule.pop("evidence_json"))
            rules.append(rule)
        return rules

    # -- read models and inventory (reporting/inventory-owned policy) ------
    def snapshots(self) -> list[dict[str, object]]:
        """List imported snapshots newest first; never reinterprets their rows."""
        return [
            dict(row)
            for row in self._conn.execute(
                """SELECT snapshot_id, datasource, start_epoch, end_epoch, captured_utc,
                          retained_rows, oldest_epoch, newest_epoch, window_count, created_utc
                   FROM snapshots ORDER BY start_epoch DESC, snapshot_id DESC"""
            )
        ]

    def add_inventory_poll(
        self,
        *,
        polled_utc: str,
        source: str,
        ok: bool,
        clients: Sequence[Mapping[str, object]] | None,
        digest: str,
        error: str | None = None,
    ) -> tuple[int, bool]:
        """Store one poll once; the digest makes re-importing the same file a no-op."""
        payload = (
            None if clients is None else json.dumps(clients, sort_keys=True, separators=(",", ":"))
        )
        with self._write() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO inventory_polls
                       (polled_utc, source, ok, error, clients_json, poll_digest)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (polled_utc, source, 1 if ok else 0, error, payload, digest),
            )
            inserted = cursor.rowcount == 1
            row = conn.execute(
                "SELECT poll_id FROM inventory_polls WHERE poll_digest = ?", (digest,)
            ).fetchone()
        if row is None:  # pragma: no cover - only reachable on a broken digest index
            raise StorageError("Inventory poll was neither inserted nor found")
        return int(row["poll_id"]), inserted

    def inventory_polls(self, *, limit: int | None = None) -> list[dict[str, object]]:
        """Return stored polls oldest first so presence timelines stay ordered."""
        query = "SELECT * FROM inventory_polls ORDER BY polled_utc, poll_id"
        params: tuple[object, ...] = ()
        if limit is not None:
            if limit < 1:
                raise StorageError("Poll limit must be positive")
            query = (
                "SELECT * FROM (SELECT * FROM inventory_polls"
                " ORDER BY polled_utc DESC, poll_id DESC LIMIT ?)"
                " ORDER BY polled_utc, poll_id"
            )
            params = (limit,)
        polls = []
        for row in self._conn.execute(query, params):
            poll = dict(row)
            clients = poll.pop("clients_json")
            poll["ok"] = bool(poll["ok"])
            poll["clients"] = None if clients is None else json.loads(clients)
            polls.append(poll)
        return polls

    def add_device_setting(
        self,
        *,
        device_key: str,
        display_name: str | None,
        category: str | None,
        supersedes: int | None = None,
    ) -> int:
        """Append one local manual revision; earlier revisions stay auditable."""
        with self._write() as conn:
            cursor = conn.execute(
                """INSERT INTO device_settings
                       (device_key, display_name, category, created_utc, supersedes)
                   VALUES (?, ?, ?, ?, ?)""",
                (device_key, display_name, category, _utc_now(), supersedes),
            )
            return int(cursor.lastrowid)

    def device_settings(self) -> list[dict[str, object]]:
        """Every manual revision, oldest first, for supersede-chain resolution."""
        return [
            dict(row)
            for row in self._conn.execute("SELECT * FROM device_settings ORDER BY revision_id")
        ]

    def add_device_binding(
        self,
        *,
        device_key: str,
        observed_ip: str | None,
        observed_mac: str | None,
        valid_from_utc: str,
        valid_to_utc: str | None,
        source: str,
        evidence: Mapping[str, object] | None = None,
    ) -> int:
        """Record one reviewed IP/MAC binding; no automatic or inferred feed."""
        if not observed_ip and not observed_mac:
            raise StorageError("A binding needs an observed IP or MAC")
        with self._write() as conn:
            cursor = conn.execute(
                """INSERT INTO device_bindings
                       (device_key, observed_ip, observed_mac, valid_from_utc,
                        valid_to_utc, source, evidence_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    device_key,
                    observed_ip,
                    observed_mac,
                    valid_from_utc,
                    valid_to_utc,
                    source,
                    None if evidence is None else json.dumps(evidence, sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def device_bindings(self) -> list[dict[str, object]]:
        bindings = []
        for row in self._conn.execute(
            "SELECT * FROM device_bindings ORDER BY valid_from_utc, binding_id"
        ):
            binding = dict(row)
            evidence = binding.pop("evidence_json")
            binding["evidence"] = None if evidence is None else json.loads(evidence)
            bindings.append(binding)
        return bindings

    # -- campaigns (campaign-owned lifecycle policy) ----------------------
    def create_campaign(
        self,
        *,
        campaign_id: str,
        start_epoch: int,
        end_epoch: int,
        timezone: str,
        retention_days: int,
        rules_revision: str | None,
        rules_sha256: str,
        rules_state: str,
        rules_ack: bool,
        rules_json: Sequence[Mapping[str, object]] = (),
        now_utc: str | None = None,
    ) -> None:
        """Insert the one active campaign; the partial unique index rejects a second."""
        now = now_utc or _utc_now()
        try:
            with self._write() as conn:
                conn.execute(
                    """INSERT INTO campaigns (campaign_id, state, start_epoch, end_epoch,
                           timezone, retention_days, rules_revision, rules_sha256, rules_state,
                           rules_ack, rules_json, created_utc, updated_utc, last_clock_epoch)
                       VALUES (?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        campaign_id,
                        start_epoch,
                        end_epoch,
                        timezone,
                        retention_days,
                        rules_revision,
                        rules_sha256,
                        rules_state,
                        1 if rules_ack else 0,
                        json.dumps(list(rules_json), sort_keys=True),
                        now,
                        now,
                        start_epoch,
                    ),
                )
                conn.execute(
                    """INSERT INTO campaign_owner_events (campaign_id, action, detail, occurred_utc)
                       VALUES (?, 'created', ?, ?)""",
                    (campaign_id, f"start {start_epoch} end {end_epoch}", now),
                )
        except sqlite3.IntegrityError as error:
            raise StorageError("A campaign is already active or finalizing") from error

    def campaign(self, campaign_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown campaign: {campaign_id}")
        return dict(row)

    def campaigns(self) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM campaigns ORDER BY created_utc DESC, campaign_id DESC"
            )
        ]

    def current_unfinished(self) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT * FROM campaigns WHERE state IN ('active', 'finalizing')"
            " ORDER BY created_utc DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None

    def observe_campaign_clock(self, campaign_id: str, *, epoch: int) -> bool:
        """Persist monotonic wall-clock observations; refuse a backward jump."""
        with self._write() as conn:
            row = conn.execute(
                "SELECT last_clock_epoch FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise StorageError("Unknown campaign")
            if epoch < int(row["last_clock_epoch"]):
                return False
            conn.execute(
                "UPDATE campaigns SET last_clock_epoch = ? WHERE campaign_id = ?",
                (epoch, campaign_id),
            )
            return True

    def transition_campaign(
        self,
        campaign_id: str,
        *,
        expected_state: str,
        new_state: str,
        now_utc: str | None = None,
        end_epoch: int | None = None,
        finalization_deadline: int | None = None,
    ) -> bool:
        """One guarded state transition; a concurrent writer cannot double-advance."""
        now = now_utc or _utc_now()
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE campaigns SET state = ?, end_epoch = COALESCE(?, end_epoch),
                       finalization_deadline = COALESCE(?, finalization_deadline),
                       updated_utc = ?
                   WHERE campaign_id = ? AND state = ?""",
                (
                    new_state,
                    end_epoch,
                    finalization_deadline,
                    now,
                    campaign_id,
                    expected_state,
                ),
            )
            return cursor.rowcount == 1

    def extend_campaign(self, campaign_id: str, *, candidate_end: int, now_utc: str) -> bool:
        """CAS on the original end; validation and update share one write lock."""
        with self._write() as conn:
            row = conn.execute(
                "SELECT start_epoch, end_epoch, state FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None or row["state"] != "active":
                return False
            if not int(row["end_epoch"]) < candidate_end <= int(row["start_epoch"]) + 120 * 3600:
                raise StorageError("Extension must advance the end within 120 hours")
            conn.execute(
                "UPDATE campaigns SET end_epoch = ?, updated_utc = ? WHERE campaign_id = ?",
                (candidate_end, now_utc, campaign_id),
            )
            conn.execute(
                """INSERT INTO campaign_owner_events (campaign_id, action, detail, occurred_utc)
                   VALUES (?, 'extended', ?, ?)""",
                (campaign_id, f"end {candidate_end}", now_utc),
            )
            return True

    def finish_campaign_early(
        self, campaign_id: str, *, end_epoch: int, now_utc: str, allowance: int
    ) -> bool:
        """Clip the end, invalidate crossing leases and insert one partial chunk atomically."""
        with self._write() as conn:
            row = conn.execute(
                "SELECT start_epoch, end_epoch, state FROM campaigns WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
            if row is None or row["state"] != "active":
                return False
            if not int(row["start_epoch"]) < end_epoch <= int(row["end_epoch"]):
                raise StorageError("Early finish must be inside the active campaign bounds")
            crossing = conn.execute(
                """SELECT start_epoch FROM capture_chunks WHERE campaign_id = ?
                   AND start_epoch < ? AND end_epoch > ? ORDER BY start_epoch""",
                (campaign_id, end_epoch, end_epoch),
            ).fetchall()
            conn.execute(
                """UPDATE capture_chunks SET state = 'expired', gap_reason = 'outside finished bounds',
                       lease_token = NULL, lease_until = NULL, updated_utc = ?
                   WHERE campaign_id = ? AND end_epoch > ?""",
                (now_utc, campaign_id, end_epoch),
            )
            for chunk in crossing:
                start = int(chunk["start_epoch"])
                conn.execute(
                    """INSERT OR IGNORE INTO capture_chunks (chunk_id, campaign_id, start_epoch,
                           end_epoch, settling_until, state, created_utc, updated_utc)
                       VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)""",
                    (
                        f"{campaign_id}:{start}:{end_epoch}",
                        campaign_id,
                        start,
                        end_epoch,
                        end_epoch + 120,
                        now_utc,
                        now_utc,
                    ),
                )
            conn.execute(
                """UPDATE campaigns SET end_epoch = ?, state = 'finalizing',
                       finalization_deadline = ?, updated_utc = ? WHERE campaign_id = ?""",
                (end_epoch, end_epoch + allowance, now_utc, campaign_id),
            )
            conn.execute(
                """INSERT INTO campaign_owner_events (campaign_id, action, detail, occurred_utc)
                   VALUES (?, 'finish_early', ?, ?)""",
                (campaign_id, f"end {end_epoch}", now_utc),
            )
            return True

    def record_owner_event(
        self,
        campaign_id: str,
        *,
        action: str,
        detail: str | None = None,
        now_utc: str | None = None,
    ) -> None:
        with self._write() as conn:
            conn.execute(
                """INSERT INTO campaign_owner_events (campaign_id, action, detail, occurred_utc)
                   VALUES (?, ?, ?, ?)""",
                (campaign_id, action, detail, now_utc or _utc_now()),
            )

    def owner_events(self, campaign_id: str) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self._conn.execute(
                """SELECT event_id, action, detail, occurred_utc FROM campaign_owner_events
                   WHERE campaign_id = ? ORDER BY event_id""",
                (campaign_id,),
            )
        ]

    def register_source_generation(
        self,
        *,
        generation_id: str,
        identity: str,
        notes: str | None = None,
        now_utc: str | None = None,
    ) -> None:
        """Pin operator-supplied source identity; never infer continuity from rows."""
        if not generation_id or not identity:
            raise StorageError("Source generation and identity are required")
        with self._write() as conn:
            existing = conn.execute(
                "SELECT identity FROM source_generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            if existing is not None:
                if existing["identity"] != identity:
                    raise StorageError("Source generation identity conflicts with existing record")
                return
            conn.execute(
                """INSERT INTO source_generations
                   (generation_id, identity, configured_utc, notes) VALUES (?, ?, ?, ?)""",
                (generation_id, identity, now_utc or _utc_now(), notes),
            )

    def source_generation(self, generation_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM source_generations WHERE generation_id = ?", (generation_id,)
        ).fetchone()
        if row is None:
            raise StorageError("Unknown source generation")
        return dict(row)

    def import_campaign_capture(
        self,
        campaign_id: str,
        *,
        chunk_id: str,
        generation_id: str,
        artifact_digest: str,
        snapshot: Mapping[str, object],
        reconciled: bool = False,
    ) -> str:
        """Atomically preserve an identified extraction revision, or reject ambiguity.

        An ID is scoped to its operator-pinned generation. Identical immutable fields
        may receive updated status/reply fields on recapture; conflicting identities
        and ID regressions across consecutive windows require operator intervention.
        """
        validate_campaign_snapshot(snapshot)
        rows = snapshot["observations"]
        start, end = int(snapshot["start_epoch"]), int(snapshot["end_epoch"])
        with self._write() as conn:
            chunk = conn.execute(
                "SELECT * FROM capture_chunks WHERE campaign_id = ? AND chunk_id = ?",
                (campaign_id, chunk_id),
            ).fetchone()
            if chunk is None or (start, end) != (chunk["start_epoch"], chunk["end_epoch"]):
                raise StorageError("Capture bounds do not match the planned chunk")
            if chunk["generation_id"] != generation_id:
                raise StorageError("Capture source generation is unbound or different")
            if reconciled:
                if (
                    chunk["state"] not in ("imported", "successful_empty")
                    or chunk["reconciled_utc"]
                ):
                    raise StorageError("Chunk is not eligible for reconciliation")
            elif chunk["state"] not in ("import_pending", "imported", "successful_empty"):
                raise StorageError("Chunk is not import-pending")
            existing = conn.execute(
                "SELECT state FROM campaign_capture_revisions WHERE chunk_id = ? AND artifact_digest = ?",
                (chunk_id, artifact_digest),
            ).fetchone()
            if snapshot.get("source_generation") != generation_id:
                raise StorageError("Extraction generation does not match the pinned source")
            if existing:
                return str(existing["state"])
            if rows:
                # Compare observed IDs by query time, not by capture order:
                # a later recapture may contain delayed rows in an earlier window.
                earlier = conn.execute(
                    "SELECT source_id, row_json FROM campaign_queries WHERE campaign_id = ? AND generation_id = ?",
                    (campaign_id, generation_id),
                ).fetchall()
                low, high = min(int(r["id"]) for r in rows), max(int(r["id"]) for r in rows)
                for old in earlier:
                    old_time = float(json.loads(old["row_json"])["timestamp"])
                    if (old_time < start and int(old["source_id"]) >= low) or (
                        old_time >= end and int(old["source_id"]) <= high
                    ):
                        raise StorageError(
                            "Source query ID regression; generation continuity unknown"
                        )
            for row in rows:
                immutable = {
                    key: row.get(key) for key in ("id", "timestamp", "type", "domain", "client")
                }
                fingerprint = hashlib.sha256(
                    json.dumps(immutable, sort_keys=True).encode()
                ).hexdigest()
                old = conn.execute(
                    """SELECT immutable_sha256 FROM campaign_queries
                       WHERE campaign_id = ? AND generation_id = ? AND source_id = ?""",
                    (campaign_id, generation_id, int(row["id"])),
                ).fetchone()
                if old and old["immutable_sha256"] != fingerprint:
                    raise StorageError("Conflicting immutable source query fields")
                conn.execute(
                    """INSERT INTO campaign_queries
                       (campaign_id, generation_id, source_id, immutable_sha256, row_json, updated_utc)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(campaign_id, generation_id, source_id) DO UPDATE SET
                         row_json = excluded.row_json, updated_utc = excluded.updated_utc""",
                    (
                        campaign_id,
                        generation_id,
                        int(row["id"]),
                        fingerprint,
                        json.dumps(row, sort_keys=True),
                        _utc_now(),
                    ),
                )
            oldest, retained = snapshot.get("oldest_epoch"), snapshot.get("retained_rows")
            history_known = (
                oldest is not None
                and retained is not None
                and int(retained) > 0
                and float(oldest) <= start
            )
            state = ("imported" if rows else "successful_empty") if history_known else "partial"
            conn.execute(
                """INSERT INTO campaign_capture_revisions
                   (chunk_id, artifact_digest, generation_id, captured_utc, row_count, state)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    chunk_id,
                    artifact_digest,
                    generation_id,
                    str(snapshot["captured_utc"]),
                    len(rows),
                    state,
                ),
            )
            if reconciled:
                conn.execute(
                    """UPDATE capture_chunks SET reconciled_utc = ?, updated_utc = ?,
                       state = CASE WHEN ? = 'partial' THEN 'partial' ELSE state END
                       WHERE chunk_id = ?""",
                    (_utc_now(), _utc_now(), state, chunk_id),
                )
            else:
                conn.execute(
                    """UPDATE capture_chunks SET state = ?, import_outcome = ?, import_utc = ?,
                       gap_reason = NULL, updated_utc = ? WHERE chunk_id = ?""",
                    (state, state, _utc_now(), _utc_now(), chunk_id),
                )
            return state

    def campaign_query_rows(self, campaign_id: str) -> list[dict[str, object]]:
        """Private identified rows for the later campaign projection (never legacy rows)."""
        return [
            json.loads(row["row_json"])
            for row in self._conn.execute(
                "SELECT row_json FROM campaign_queries WHERE campaign_id = ? ORDER BY generation_id, source_id",
                (campaign_id,),
            )
        ]

    def campaign_report_inputs(self, campaign_id: str) -> dict[str, object]:
        """One consistent private read of bounds, evidence, revisions and saved results.

        Called by the local report worker; never handed to the public web layer.
        The short read transaction pins a WAL snapshot, not the renderer's write lock.
        """
        with self._conn_lock:
            self._conn.execute("BEGIN")
            try:
                campaign = self.campaign(campaign_id)
                chunks = self.chunks(campaign_id)
                queries = [
                    {
                        "generation_id": record["generation_id"],
                        "source_id": record["source_id"],
                        "row": json.loads(record["row_json"]),
                    }
                    for record in self._conn.execute(
                        """SELECT generation_id, source_id, row_json FROM campaign_queries
                       WHERE campaign_id = ? ORDER BY generation_id, source_id""",
                        (campaign_id,),
                    )
                ]
                revisions = [
                    dict(record)
                    for record in self._conn.execute(
                        """SELECT r.chunk_id, r.artifact_digest, r.generation_id,
                          r.captured_utc, r.row_count, r.state
                   FROM campaign_capture_revisions r JOIN capture_chunks c USING(chunk_id)
                   WHERE c.campaign_id = ? ORDER BY r.chunk_id, r.captured_utc, r.artifact_digest""",
                        (campaign_id,),
                    )
                ]
                analyses = self.latest_analysis_results()
                registered_generations = [
                    str(row["generation_id"])
                    for row in self._conn.execute(
                        "SELECT generation_id FROM source_generations ORDER BY generation_id"
                    )
                ]
                override = self._conn.execute(
                    """SELECT r.rules_sha256, r.revision, r.rules_json, r.rules_ack
                   FROM campaign_owner_events e JOIN campaign_rules_revisions r
                     ON r.campaign_id = e.campaign_id AND r.rules_sha256 = e.detail
                   WHERE e.campaign_id = ? AND e.action = 'report_rules_revision'
                   ORDER BY e.event_id DESC LIMIT 1""",
                    (campaign_id,),
                ).fetchone()
                return {
                    "campaign": campaign,
                    "chunks": chunks,
                    "queries": queries,
                    "revisions": revisions,
                    "analyses": analyses,
                    "registered_generations": registered_generations,
                    "rules": dict(override)
                    if override
                    else {
                        "rules_sha256": campaign["rules_sha256"],
                        "revision": campaign["rules_revision"],
                        "rules_json": campaign["rules_json"],
                        "rules_ack": campaign["rules_ack"],
                    },
                }
            finally:
                self._conn.execute("ROLLBACK")

    def pin_campaign_report_rules(
        self,
        campaign_id: str,
        *,
        sha256: str,
        revision: str,
        rules: Sequence[Mapping[str, str]],
        ack_empty: bool,
        now_utc: str,
    ) -> None:
        """Audited owner-only rule revision for future reports; never rewrite old ones."""
        with self._write() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM campaigns WHERE campaign_id = ?", (campaign_id,)
                ).fetchone()
                is None
            ):
                raise StorageError("Unknown campaign")
            conn.execute(
                """INSERT OR IGNORE INTO campaign_rules_revisions
                   (campaign_id, rules_sha256, revision, rules_json, rules_ack, created_utc)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    campaign_id,
                    sha256,
                    revision,
                    json.dumps(list(rules), sort_keys=True),
                    int(ack_empty),
                    now_utc,
                ),
            )
            conn.execute(
                """INSERT INTO campaign_owner_events (campaign_id, action, detail, occurred_utc)
                   VALUES (?, 'report_rules_revision', ?, ?)""",
                (campaign_id, sha256, now_utc),
            )

    # -- capture chunks (durable planning, leases and imports) ------------
    def plan_chunks(self, campaign_id: str, chunks: Sequence[Mapping[str, object]]) -> int:
        """Insert planned chunks once; re-planning the same windows is a no-op."""
        now = _utc_now()
        with self._write() as conn:
            cursor = conn.executemany(
                """INSERT OR IGNORE INTO capture_chunks (chunk_id, campaign_id, start_epoch,
                       end_epoch, settling_until, state, created_utc, updated_utc)
                   VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)""",
                [
                    (
                        chunk["chunk_id"],
                        campaign_id,
                        int(chunk["start_epoch"]),
                        int(chunk["end_epoch"]),
                        int(chunk["settling_until"]),
                        now,
                        now,
                    )
                    for chunk in chunks
                ],
            )
            return int(cursor.rowcount)

    def chunks(self, campaign_id: str) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM capture_chunks WHERE campaign_id = ? ORDER BY start_epoch",
                (campaign_id,),
            )
        ]

    def chunk(self, campaign_id: str, chunk_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM capture_chunks WHERE campaign_id = ? AND chunk_id = ?",
            (campaign_id, chunk_id),
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown chunk: {chunk_id}")
        return dict(row)

    def capture_attempt_tokens(self, campaign_id: str, chunk_id: str) -> list[str]:
        """Attempt artifact names for a previously claimed chunk, newest first."""
        self.chunk(campaign_id, chunk_id)
        return [
            str(row["attempt_token"])
            for row in self._conn.execute(
                "SELECT attempt_token FROM capture_attempts WHERE chunk_id = ? ORDER BY rowid DESC",
                (chunk_id,),
            )
        ]

    def bind_chunk_generation(self, campaign_id: str, *, chunk_id: str, generation_id: str) -> bool:
        """Pin the configured resolver generation before a chunk is ever claimed."""
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE capture_chunks SET generation_id = ?, updated_utc = ?
                   WHERE campaign_id = ? AND chunk_id = ? AND generation_id IS NULL
                     AND attempts = 0 AND state = 'scheduled'
                     AND EXISTS (SELECT 1 FROM source_generations WHERE generation_id = ?)""",
                (generation_id, _utc_now(), campaign_id, chunk_id, generation_id),
            )
            return cursor.rowcount == 1

    def claim_chunks(
        self,
        campaign_id: str,
        *,
        chunk_ids: Sequence[str],
        worker: str,
        lease_seconds: int,
        limit: int,
        now_utc: str | None = None,
    ) -> dict[str, str]:
        """Atomically lease every settled, unleased chunk id supplied.

        Only chunks already past their settling time are claimable, so an unsettled
        or out-of-campaign window is never handed to a worker. A live lease blocks
        the claim; an expired lease is reclaimed. Returns ``{chunk_id: token}``.
        """
        if not 1 <= limit <= 10:
            raise StorageError("At most ten chunks can be claimed per tick")
        if not chunk_ids or lease_seconds < 1:
            return {}
        now = now_utc or _utc_now()
        lease = datetime.fromisoformat(now.replace("Z", "+00:00"))
        now_epoch = int(lease.timestamp())
        lease_until = (
            datetime.fromtimestamp(now_epoch + lease_seconds, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        claimed: dict[str, str] = {}
        with self._write() as conn:
            for chunk_id in chunk_ids:
                if len(claimed) >= limit:
                    break
                token = secrets.token_hex(16)
                cursor = conn.execute(
                    """UPDATE capture_chunks SET lease_token = ?, lease_until = ?,
                           attempts = attempts + 1, updated_utc = ?
                       WHERE campaign_id = ? AND chunk_id = ?
                         AND state IN ('scheduled', 'failed')
                         AND attempts < 3
                         AND settling_until <= ?
                         AND end_epoch <= (SELECT end_epoch FROM campaigns
                                          WHERE campaign_id = capture_chunks.campaign_id)
                         AND EXISTS (SELECT 1 FROM campaigns c WHERE c.campaign_id = ?
                                     AND c.state IN ('active', 'finalizing')
                                     AND c.last_clock_epoch <= ?
                                     AND ((c.state = 'active' AND ? <= c.end_epoch + 86400) OR
                                          (c.finalization_deadline IS NOT NULL
                                           AND c.finalization_deadline >= ?)))
                         AND (lease_token IS NULL OR lease_until IS NULL OR lease_until <= ?)""",
                    (
                        token,
                        lease_until,
                        now,
                        campaign_id,
                        chunk_id,
                        now_epoch,
                        campaign_id,
                        now_epoch,
                        now_epoch,
                        now_epoch,
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    conn.execute(
                        """INSERT INTO capture_attempts
                           (attempt_token, chunk_id, worker, claimed_utc, lease_until)
                           VALUES (?, ?, ?, ?, ?)""",
                        (token, chunk_id, worker, now, lease_until),
                    )
                    claimed[chunk_id] = token
        return claimed

    def ack_capture(
        self,
        campaign_id: str,
        *,
        chunk_id: str,
        token: str,
        outcome: str,
        artifact_digest: str | None = None,
        artifact_path: str | None = None,
        gap_reason: str | None = None,
        now_utc: str | None = None,
    ) -> bool:
        """Record the extraction result under the matching live lease token."""
        if outcome not in {"captured", "failed"}:
            raise StorageError(f"Unsupported capture outcome: {outcome}")
        now = now_utc or _utc_now()
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE capture_chunks SET state = ?, artifact_digest = ?, artifact_path = ?,
                       captured_utc = ?, gap_reason = ?, lease_token = NULL, lease_until = NULL,
                       updated_utc = ?
                   WHERE campaign_id = ? AND chunk_id = ? AND lease_token = ?
                     AND lease_until IS NOT NULL AND lease_until > ?""",
                (
                    outcome,
                    artifact_digest,
                    artifact_path,
                    now,
                    gap_reason,
                    now,
                    campaign_id,
                    chunk_id,
                    token,
                    now,
                ),
            )
            if cursor.rowcount == 1:
                conn.execute(
                    """UPDATE capture_attempts SET outcome = ?, finished_utc = ?
                       WHERE attempt_token = ? AND outcome IS NULL""",
                    (outcome, now, token),
                )
            return cursor.rowcount == 1

    def mark_import_pending(
        self, campaign_id: str, *, chunk_id: str, now_utc: str | None = None
    ) -> bool:
        """Move one captured artifact into the import queue (idempotent per chunk)."""
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE capture_chunks SET state = 'import_pending', updated_utc = ?"
                " WHERE campaign_id = ? AND chunk_id = ? AND state = 'captured'",
                (now_utc or _utc_now(), campaign_id, chunk_id),
            )
            return cursor.rowcount == 1

    def ack_import(
        self,
        campaign_id: str,
        *,
        chunk_id: str,
        outcome: str,
        gap_reason: str | None = None,
        now_utc: str | None = None,
    ) -> bool:
        """Record the import result; only an import-pending chunk transitions."""
        if outcome not in {"imported", "successful_empty", "partial", "failed"}:
            raise StorageError(f"Unsupported import outcome: {outcome}")
        now = now_utc or _utc_now()
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE capture_chunks SET state = ?, import_outcome = ?, import_utc = ?,
                       gap_reason = ?, updated_utc = ?
                   WHERE campaign_id = ? AND chunk_id = ? AND state = 'import_pending'""",
                (outcome, outcome, now, gap_reason, now, campaign_id, chunk_id),
            )
            return cursor.rowcount == 1

    def mark_reconciled(
        self, campaign_id: str, *, chunk_id: str, now_utc: str | None = None
    ) -> bool:
        """Mark a completed bounded late-data pass; the pass itself belongs to B2."""
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE capture_chunks SET reconciled_utc = ?, updated_utc = ?
                   WHERE campaign_id = ? AND chunk_id = ? AND state IN ('imported','successful_empty')
                     AND reconciled_utc IS NULL""",
                (now_utc or _utc_now(), now_utc or _utc_now(), campaign_id, chunk_id),
            )
            return cursor.rowcount == 1

    def expire_chunks(
        self, campaign_id: str, *, chunk_ids: Sequence[str], reason: str, now_utc: str | None = None
    ) -> int:
        """Mark unresolved chunks expired without touching preserved evidence."""
        if not chunk_ids:
            return 0
        placeholders = ",".join("?" * len(chunk_ids))
        with self._write() as conn:
            cursor = conn.execute(
                f"""UPDATE capture_chunks SET state = 'expired', gap_reason = ?,
                       lease_token = NULL, lease_until = NULL, updated_utc = ?
                   WHERE campaign_id = ? AND chunk_id IN ({placeholders})
                     AND state NOT IN ('imported', 'successful_empty', 'partial', 'expired')""",
                (reason, now_utc or _utc_now(), campaign_id, *chunk_ids),
            )
            return int(cursor.rowcount)

    # -- local jobs (typed worker/control work with leases) ---------------
    def create_job(
        self,
        *,
        job_id: str,
        campaign_id: str,
        kind: str,
        dedup_key: str | None = None,
        params: Mapping[str, object] | None = None,
        now_utc: str | None = None,
    ) -> tuple[str, bool]:
        """Create the job identity once; a duplicate dedup key returns the original."""
        if kind not in {"capture", "report"}:
            raise StorageError(f"Unsupported job kind: {kind}")
        now = now_utc or _utc_now()
        with self._write() as conn:
            if dedup_key is not None:
                existing = conn.execute(
                    "SELECT job_id FROM local_jobs WHERE campaign_id = ? AND kind = ?"
                    " AND dedup_key = ?",
                    (campaign_id, kind, dedup_key),
                ).fetchone()
                if existing is not None:
                    return str(existing["job_id"]), False
            if kind == "report":
                queued = conn.execute(
                    """SELECT count(*) FROM local_jobs WHERE kind = 'report'
                       AND state IN ('queued', 'running')"""
                ).fetchone()[0]
                if queued >= 10:
                    raise StorageError("Report queue is full")
            conn.execute(
                """INSERT INTO local_jobs (job_id, campaign_id, kind, dedup_key, state,
                       params_json, created_utc, updated_utc)
                   VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (
                    job_id,
                    campaign_id,
                    kind,
                    dedup_key,
                    json.dumps(dict(params), sort_keys=True) if params else None,
                    now,
                    now,
                ),
            )
            return job_id, True

    def claim_job(
        self,
        job_id: str,
        *,
        worker: str,
        lease_seconds: int,
        now_utc: str | None = None,
    ) -> tuple[str, bool]:
        """Lease one queued job; an expired lease on a crashed worker is reclaimed."""
        if lease_seconds < 1:
            raise StorageError("Job lease must be positive")
        now = now_utc or _utc_now()
        lease = datetime.fromisoformat(now.replace("Z", "+00:00"))
        lease_until = (
            datetime.fromtimestamp(lease.timestamp() + lease_seconds, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        token = secrets.token_hex(16)
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE local_jobs SET state = 'running', lease_token = ?, lease_until = ?,
                        attempts = attempts + 1, updated_utc = ?
                     WHERE job_id = ? AND attempts < 3 AND (
                          state = 'queued' OR
                          (state = 'running' AND (lease_until IS NULL OR lease_until <= ?)))
                     AND (kind != 'report' OR NOT EXISTS (
                       SELECT 1 FROM local_jobs other WHERE other.kind = 'report'
                         AND other.state = 'running' AND other.job_id != local_jobs.job_id
                         AND other.lease_until > ?))""",
                (token, lease_until, now, job_id, now, now),
            )
            if cursor.rowcount != 1:
                return "", False
            return token, True

    def finish_job(
        self,
        job_id: str,
        *,
        token: str,
        state: str,
        sanitized_error: str | None = None,
        now_utc: str | None = None,
    ) -> bool:
        """Acknowledge a running job under its live lease token."""
        if state not in {"ready", "failed"}:
            raise StorageError(f"Unsupported job outcome: {state}")
        now = now_utc or _utc_now()
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE local_jobs SET state = ?, sanitized_error = ?, lease_token = NULL,
                       lease_until = NULL, updated_utc = ?
                   WHERE job_id = ? AND lease_token = ?
                     AND lease_until IS NOT NULL AND lease_until > ?""",
                (
                    state,
                    sanitized_error,
                    now,
                    job_id,
                    token,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def job(self, job_id: str) -> dict[str, object]:
        row = self._conn.execute("SELECT * FROM local_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise StorageError(f"Unknown job: {job_id}")
        return dict(row)

    def pending_jobs(
        self, campaign_id: str, *, kind: str, now_utc: str | None = None
    ) -> list[dict[str, object]]:
        """Queued jobs plus running jobs whose lease has already expired."""
        if kind not in {"capture", "report"}:
            raise StorageError(f"Unsupported job kind: {kind}")
        return [
            dict(row)
            for row in self._conn.execute(
                """SELECT * FROM local_jobs WHERE campaign_id = ? AND kind = ?
                   AND attempts < 3 AND (state = 'queued' OR (state = 'running' AND
                        (lease_until IS NULL OR lease_until <= ?)))
                   ORDER BY created_utc, job_id""",
                (campaign_id, kind, now_utc or _utc_now()),
            )
        ]

    def fail_exhausted_report_jobs(self, *, now_utc: str) -> int:
        """Expose exhausted crashed jobs instead of leaving them running forever."""
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE local_jobs SET state = 'failed', lease_token = NULL,
                   lease_until = NULL, sanitized_error = 'Report worker retry limit reached',
                   updated_utc = ? WHERE kind = 'report' AND state = 'running'
                   AND attempts >= 3 AND lease_until <= ?""",
                (now_utc, now_utc),
            )
            return int(cursor.rowcount)

    # -- frozen campaign reports (immutable, deduplicated metadata) -------
    @staticmethod
    def _report_lineage(conn: sqlite3.Connection, campaign_id: str) -> tuple[int, str | None]:
        """Next revision number and the preceding report it supersedes."""
        row = conn.execute(
            """SELECT report_id, revision FROM frozen_reports WHERE campaign_id = ?
               ORDER BY created_utc DESC, report_id DESC LIMIT 1""",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return 1, None
        return int(row["revision"]) + 1, str(row["report_id"])

    def save_frozen_report(
        self,
        *,
        report_id: str,
        campaign_id: str,
        requested_start: int,
        requested_end: int,
        actual_start: int,
        actual_end: int,
        dedup_key: str,
        rules_sha256: str,
        coverage_sha256: str | None,
        capture_revisions: Sequence[str] = (),
        payload: Mapping[str, object],
        expires_utc: str,
        now_utc: str | None = None,
    ) -> tuple[str, bool]:
        """Persist one immutable projection; the same key reuses the first result."""
        with self._write() as conn:
            existing = conn.execute(
                "SELECT report_id FROM frozen_reports WHERE campaign_id = ? AND dedup_key = ?",
                (campaign_id, dedup_key),
            ).fetchone()
            if existing is not None:
                return str(existing["report_id"]), False
            revision, predecessor = self._report_lineage(conn, campaign_id)
            stored_payload = {
                **payload,
                "revision": revision,
                "predecessor_report_id": predecessor,
            }
            conn.execute(
                """INSERT INTO frozen_reports (report_id, campaign_id, requested_start,
                       requested_end, actual_start, actual_end, dedup_key, rules_sha256,
                       coverage_sha256, capture_revisions_json, payload_json, created_utc,
                       expires_utc, predecessor_report_id, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id,
                    campaign_id,
                    requested_start,
                    requested_end,
                    actual_start,
                    actual_end,
                    dedup_key,
                    rules_sha256,
                    coverage_sha256,
                    json.dumps(list(capture_revisions), sort_keys=True),
                    json.dumps(stored_payload, sort_keys=True),
                    now_utc or _utc_now(),
                    expires_utc,
                    predecessor,
                    revision,
                ),
            )
            return report_id, True

    def frozen_report(self, report_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM frozen_reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown frozen report: {report_id}")
        return dict(row)

    def frozen_reports(self, campaign_id: str) -> list[dict[str, object]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM frozen_reports WHERE campaign_id = ? ORDER BY created_utc, report_id",
                (campaign_id,),
            )
        ]

    def finish_campaign_report(
        self,
        *,
        job_id: str,
        token: str,
        report_id: str,
        campaign_id: str,
        requested_start: int,
        requested_end: int,
        actual_start: int,
        actual_end: int,
        dedup_key: str,
        rules_sha256: str,
        coverage_sha256: str,
        capture_revisions: Sequence[str],
        payload: Mapping[str, object],
        expires_utc: str,
        now_utc: str,
    ) -> str:
        """Freeze output and acknowledge its leased job in one transaction."""
        with self._write() as conn:
            row = conn.execute(
                """SELECT job_id FROM local_jobs WHERE job_id = ? AND campaign_id = ?
                   AND kind = 'report' AND state = 'running' AND lease_token = ?
                   AND lease_until > ?""",
                (job_id, campaign_id, token, now_utc),
            ).fetchone()
            if row is None:
                raise StorageError("Report job lease is stale")
            existing = conn.execute(
                "SELECT report_id FROM frozen_reports WHERE campaign_id = ? AND dedup_key = ?",
                (campaign_id, dedup_key),
            ).fetchone()
            if existing:
                report_id = str(existing["report_id"])
            else:
                revision, predecessor = self._report_lineage(conn, campaign_id)
                stored_payload = {
                    **payload,
                    "revision": revision,
                    "predecessor_report_id": predecessor,
                }
                conn.execute(
                    """INSERT INTO frozen_reports (report_id, campaign_id, requested_start,
                       requested_end, actual_start, actual_end, dedup_key, rules_sha256,
                       coverage_sha256, capture_revisions_json, payload_json, created_utc,
                       expires_utc, predecessor_report_id, revision)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        report_id,
                        campaign_id,
                        requested_start,
                        requested_end,
                        actual_start,
                        actual_end,
                        dedup_key,
                        rules_sha256,
                        coverage_sha256,
                        json.dumps(list(capture_revisions), sort_keys=True),
                        json.dumps(stored_payload, sort_keys=True),
                        now_utc,
                        expires_utc,
                        predecessor,
                        revision,
                    ),
                )
            conn.execute(
                "INSERT INTO campaign_job_results (job_id, report_id) VALUES (?, ?)",
                (job_id, report_id),
            )
            conn.execute(
                """UPDATE local_jobs SET state = 'ready', lease_token = NULL,
                   lease_until = NULL, updated_utc = ? WHERE job_id = ?""",
                (now_utc, job_id),
            )
            return report_id

    def campaign_job_result(self, job_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT report_id FROM campaign_job_results WHERE job_id = ?", (job_id,)
        ).fetchone()
        return str(row["report_id"]) if row else None

    def retirement_preview(self, campaign_id: str) -> dict[str, object]:
        """Private, exact campaign-owned rows and artifact names; no shared tables."""
        campaign = self.campaign(campaign_id)
        chunks = self.chunks(campaign_id)
        tokens = [
            str(row["attempt_token"])
            for row in self._conn.execute(
                """SELECT a.attempt_token FROM capture_attempts a
               JOIN capture_chunks c ON c.chunk_id = a.chunk_id
               WHERE c.campaign_id = ? ORDER BY a.attempt_token""",
                (campaign_id,),
            )
        ]
        names = {f"capture-{token}.json" for token in tokens}
        names.update(
            "reconcile-"
            + hashlib.sha256(str(chunk["chunk_id"]).encode()).hexdigest()[:32]
            + ".json"
            for chunk in chunks
            if chunk["reconciled_utc"]
        )
        for chunk in chunks:
            path = chunk["artifact_path"]
            if path and path not in names:
                raise StorageError("Campaign has an unowned artifact reference")
        counts = {
            table: int(
                self._conn.execute(
                    f"SELECT count(*) FROM {table} WHERE campaign_id = ?", (campaign_id,)
                ).fetchone()[0]
            )
            for table in ("capture_chunks", "campaign_queries", "local_jobs", "frozen_reports")
        }
        data = {
            "campaign_id": campaign_id,
            "state": campaign["state"],
            "end_epoch": campaign["end_epoch"],
            "retention_days": campaign["retention_days"],
            "updated_utc": campaign["updated_utc"],
            "counts": counts,
            "artifact_names": sorted(names),
            "chunk_revisions": [
                (row["chunk_id"], row["state"], row["artifact_digest"], row["updated_utc"])
                for row in chunks
            ],
            "query_revision": hashlib.sha256(
                json.dumps(
                    [
                        tuple(row)
                        for row in self._conn.execute(
                            """SELECT generation_id, source_id, immutable_sha256, row_json
                           FROM campaign_queries WHERE campaign_id = ?
                           ORDER BY generation_id, source_id""",
                            (campaign_id,),
                        )
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "report_ids": [
                row["report_id"]
                for row in self._conn.execute(
                    "SELECT report_id FROM frozen_reports WHERE campaign_id = ? ORDER BY report_id",
                    (campaign_id,),
                )
            ],
        }
        data["digest"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return data

    def retire_campaign(
        self,
        campaign_id: str,
        *,
        expected_digest: str,
        backup_choice: str,
        now_utc: str | None = None,
    ) -> dict[str, object]:
        if backup_choice not in {"backed_up", "declined"}:
            raise StorageError("Explicit backup decision required")
        with self._write() as conn:
            preview = self.retirement_preview(campaign_id)
            if preview["state"] not in {"complete", "complete_with_gaps"}:
                raise StorageError("Finish the campaign before retirement")
            if conn.execute(
                """SELECT 1 FROM local_jobs WHERE campaign_id = ?
                               AND state IN ('queued', 'running') LIMIT 1""",
                (campaign_id,),
            ).fetchone():
                raise StorageError("Finish or fail pending campaign jobs before retirement")
            if preview["digest"] != expected_digest:
                raise StorageError("Campaign changed since the retirement preview")
            conn.execute(
                """INSERT INTO campaign_retirements
                         (campaign_id, preview_digest, backup_choice, artifact_names_json, retired_utc)
                         VALUES (?, ?, ?, ?, ?)""",
                (
                    campaign_id,
                    expected_digest,
                    backup_choice,
                    json.dumps(preview["artifact_names"]),
                    now_utc or _utc_now(),
                ),
            )
            conn.execute("DELETE FROM campaigns WHERE campaign_id = ?", (campaign_id,))
            return preview

    # -- analyses and the dispatch ledger (analysis-owned policy) ----------
    def create_analysis(
        self,
        *,
        analysis_id: str,
        period_digest: str,
        selection_digest: str,
        analyzer_version: int,
        provider: str | None,
        model_id: str | None,
        config_fingerprint: str | None,
        policy_revision: int | None,
        items: Sequence[Mapping[str, object]],
    ) -> tuple[str, bool]:
        """Create the job identity once; a duplicate identity returns the original."""
        now = _utc_now()
        with self._write() as conn:
            existing = conn.execute(
                "SELECT analysis_id FROM analyses WHERE analysis_id = ?", (analysis_id,)
            ).fetchone()
            if existing is not None:
                return analysis_id, False
            conn.execute(
                """INSERT INTO analyses (analysis_id, state, period_digest, selection_digest,
                       analyzer_version, provider, model_id, config_fingerprint,
                       policy_revision, created_utc, updated_utc)
                   VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis_id,
                    period_digest,
                    selection_digest,
                    analyzer_version,
                    provider,
                    model_id,
                    config_fingerprint,
                    policy_revision,
                    now,
                    now,
                ),
            )
            conn.executemany(
                """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state)
                   VALUES (?, ?, ?, ?, 'pending')""",
                [
                    (
                        analysis_id,
                        item["item_id"],
                        item["domain"],
                        item.get("claim_scope", "service_and_provider"),
                    )
                    for item in items
                ],
            )
            return analysis_id, True

    def analysis(self, analysis_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()
        if row is None:
            raise StorageError(f"Unknown analysis: {analysis_id}")
        return dict(row)

    def recent_analyses(self, *, limit: int = 10) -> list[dict[str, object]]:
        """Job headers newest first; no candidate payloads or provider text."""
        if not 1 <= limit <= 100:
            raise StorageError("Recent-analysis limit must be between 1 and 100")
        return [
            dict(row)
            for row in self._conn.execute(
                """SELECT analysis_id, state, provider, model_id, created_utc, updated_utc,
                          summary
                   FROM analyses ORDER BY created_utc DESC, analysis_id DESC LIMIT ?""",
                (limit,),
            )
        ]

    def pending_items(self, analysis_id: str, *, limit: int) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """SELECT * FROM analysis_items WHERE analysis_id = ? AND state = 'pending'
               ORDER BY item_id LIMIT ?""",
            (analysis_id, limit),
        )
        return [dict(row) for row in rows]

    def researched_domains(self) -> dict[str, str]:
        """Terminal research outcome per public name, newest result wins.

        A name is ``resolved`` only when its stored result carries a service or
        provider; anything else (unknown, deferred, failed, malformed) is
        ``unresolved``. Cancelled analyses are excluded so they never count as
        successful research.
        """
        result: dict[str, str] = {}
        rows = self._conn.execute(
            """SELECT ai.domain, ai.state, ai.result_json
               FROM analysis_items ai JOIN analyses a USING (analysis_id)
               WHERE a.state IN ('completed', 'partial', 'paused')
                 AND ai.state IN ('done', 'unknown', 'deferred', 'failed')
               ORDER BY ai.rowid DESC"""
        )
        for row in rows:
            domain = str(row["domain"]).lower().rstrip(".")
            if not domain or domain in result:
                continue  # newest row already recorded (rows are DESC)
            if str(row["state"]) != "done":
                result[domain] = "unresolved"
                continue
            try:
                payload = json.loads(row["result_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            result[domain] = (
                "resolved"
                if isinstance(payload, Mapping)
                and (payload.get("service") or payload.get("provider"))
                else "unresolved"
            )
        return result

    def claim_items(
        self,
        analysis_id: str,
        *,
        item_ids: Sequence[str],
        lease_seconds: int,
        now_utc: str | None = None,
    ) -> list[str]:
        """Atomically claim pending items; concurrent workers get an empty list."""
        if not item_ids:
            return []
        now = now_utc or _utc_now()
        lease = datetime.fromisoformat(now.replace("Z", "+00:00"))
        lease_until = (
            datetime.fromtimestamp(lease.timestamp() + lease_seconds, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        claimed: list[str] = []
        with self._write() as conn:
            conn.execute(
                "UPDATE analyses SET state = 'running', updated_utc = ? WHERE analysis_id = ?",
                (now, analysis_id),
            )
            for item_id in item_ids:
                cursor = conn.execute(
                    """UPDATE analysis_items SET state = 'claimed', lease_until = ?,
                           attempts = attempts + 1
                       WHERE analysis_id = ? AND item_id = ? AND state = 'pending'""",
                    (lease_until, analysis_id, item_id),
                )
                if cursor.rowcount == 1:
                    claimed.append(item_id)
        return claimed

    def reserve_attempt(
        self,
        *,
        analysis_id: str,
        kind: str,
        budget: AttemptBudget,
        item_id: str | None = None,
        reserved_tokens: int = 0,
        dispatch_day: str | None = None,
        now_utc: str | None = None,
    ) -> AttemptReservation:
        """Reserve one declared external attempt, or refuse before any dispatch.

        The reservation and the budget check share one ``BEGIN IMMEDIATE``
        transaction, so concurrent tabs/processes cannot both spend the same
        remaining headroom. Charges are derived from the ledger itself.
        """
        if kind not in ATTEMPT_KINDS:
            raise StorageError(f"Unsupported attempt kind: {kind}")
        if reserved_tokens < 0:
            raise StorageError("Reserved tokens cannot be negative")
        now = now_utc or _utc_now()
        day = dispatch_day or now[:10]
        category = ATTEMPT_KINDS[kind]
        operation = {
            "exa_search": "search",
            "exa_fetch": "fetch",
            "exa_discover": "discover",
            "provider_catalog": "catalog",
            "provider_probe": "probe",
            "provider_request": "completion",
        }[kind]

        def charged(rows: Sequence[sqlite3.Row]) -> tuple[int, int, int]:
            count = len(rows)
            tokens = sum(_charge(row) for row in rows)
            exa = sum(1 for row in rows if ATTEMPT_KINDS.get(row["kind"]) == "exa")
            return count, tokens, exa

        with self._write() as conn:
            analysis_rows = conn.execute(
                f"""SELECT kind, reserved_tokens, prompt_tokens, completion_tokens
                    FROM call_attempts WHERE analysis_id = ?
                    AND outcome IN ({",".join("?" * len(CHARGEABLE_OUTCOMES))})""",
                (analysis_id, *CHARGEABLE_OUTCOMES),
            ).fetchall()
            day_rows = conn.execute(
                f"""SELECT kind, reserved_tokens, prompt_tokens, completion_tokens
                    FROM call_attempts WHERE dispatch_day = ?
                    AND outcome IN ({",".join("?" * len(CHARGEABLE_OUTCOMES))})""",
                (day, *CHARGEABLE_OUTCOMES),
            ).fetchall()

            analysis_count, analysis_tokens, analysis_exa = charged(analysis_rows)
            day_count, day_tokens, day_exa = charged(day_rows)
            # The declared limits are per category: a provider request budget and
            # a separate Exa budget. Charging Exa attempts against the provider
            # request limit would spend one category's allowance with another
            # category's work, so each count covers only its own attempts.
            analysis_requests = analysis_count - analysis_exa
            day_requests = day_count - day_exa
            for scope, rows in (("analysis", analysis_rows), ("day", day_rows)):
                limit = getattr(budget, f"per_{scope}_{operation}")
                if limit is not None:
                    count = sum(1 for row in rows if row["kind"] == kind)
                    if count + 1 > limit:
                        raise BudgetExceeded(
                            f"{scope.title()} {operation} budget exhausted ({count}/{limit})",
                            scope,
                        )

            if category == "request":
                if analysis_requests + 1 > budget.per_analysis_requests:
                    raise BudgetExceeded(
                        f"Analysis request budget exhausted ({analysis_requests}/"
                        f"{budget.per_analysis_requests})",
                        "analysis",
                    )
                if day_requests + 1 > budget.per_day_requests:
                    raise BudgetExceeded(
                        f"Daily request budget exhausted ({day_requests}/{budget.per_day_requests})",
                        "day",
                    )
                if analysis_tokens + reserved_tokens > budget.per_analysis_tokens:
                    raise BudgetExceeded(
                        "Analysis token budget cannot cover this reservation", "analysis"
                    )
                if day_tokens + reserved_tokens > budget.per_day_tokens:
                    raise BudgetExceeded("Daily token budget cannot cover this reservation", "day")
            else:
                if analysis_exa + 1 > budget.per_analysis_exa:
                    raise BudgetExceeded(
                        f"Analysis Exa budget exhausted ({analysis_exa}/{budget.per_analysis_exa})",
                        "analysis",
                    )
                if day_exa + 1 > budget.per_day_exa:
                    raise BudgetExceeded(
                        f"Daily Exa budget exhausted ({day_exa}/{budget.per_day_exa})", "day"
                    )

            # Paid-mode currency ceilings (spec R17). An unknown price fails
            # closed here, before any reservation row is written, so no spend
            # can be recorded against an unverifiable tariff.
            if budget.paid_mode:
                if category == "request":
                    price = budget.provider_price_per_million
                    if price is None:
                        raise BudgetExceeded(
                            "Unknown provider price; paid dispatch is refused", "currency"
                        )
                    spent_analysis = sum(
                        _charge(row) * price / 1_000_000
                        for row in analysis_rows
                        if ATTEMPT_KINDS.get(row["kind"]) == "request"
                    )
                    spent_day = sum(
                        _charge(row) * price / 1_000_000
                        for row in day_rows
                        if ATTEMPT_KINDS.get(row["kind"]) == "request"
                    )
                    new_cost = reserved_tokens * price / 1_000_000
                    if (
                        budget.per_analysis_currency is not None
                        and spent_analysis + new_cost > budget.per_analysis_currency
                    ):
                        raise BudgetExceeded("Analysis currency ceiling reached", "currency")
                    if (
                        budget.per_day_currency is not None
                        and spent_day + new_cost > budget.per_day_currency
                    ):
                        raise BudgetExceeded("Daily currency ceiling reached", "currency")
                else:
                    price = budget.exa_price_per_operation
                    if price is None:
                        raise BudgetExceeded(
                            "Unknown Exa price; paid dispatch is refused", "currency"
                        )
                    spent_analysis = (
                        sum(1 for row in analysis_rows if ATTEMPT_KINDS.get(row["kind"]) == "exa")
                        * price
                    )
                    spent_day = (
                        sum(1 for row in day_rows if ATTEMPT_KINDS.get(row["kind"]) == "exa")
                        * price
                    )
                    new_cost = price
                    if (
                        budget.per_analysis_exa_currency is not None
                        and spent_analysis + new_cost > budget.per_analysis_exa_currency
                    ):
                        raise BudgetExceeded("Analysis Exa currency ceiling reached", "currency")
                    if (
                        budget.per_day_exa_currency is not None
                        and spent_day + new_cost > budget.per_day_exa_currency
                    ):
                        raise BudgetExceeded("Daily Exa currency ceiling reached", "currency")

            cursor = conn.execute(
                """INSERT INTO call_attempts (analysis_id, item_id, kind, dispatch_day,
                       created_utc, reserved_tokens, outcome)
                   VALUES (?, ?, ?, ?, ?, ?, 'reserved')""",
                (analysis_id, item_id, kind, day, now, reserved_tokens),
            )
            conn.execute(
                "UPDATE analyses SET updated_utc = ? WHERE analysis_id = ?", (now, analysis_id)
            )
            return AttemptReservation(
                attempt_id=int(cursor.lastrowid),
                analysis_id=analysis_id,
                kind=kind,
                dispatch_day=day,
            )

    def complete_attempt(
        self,
        attempt_id: int,
        *,
        outcome: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        error_class: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        """Record the single adapter outcome; missing usage keeps the reservation."""
        if outcome not in {"ok", "error", "timeout", "unconfirmed"}:
            raise StorageError(f"Unsupported terminal outcome: {outcome}")
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE call_attempts SET outcome = ?, prompt_tokens = ?,
                       completion_tokens = ?, error_class = ?, detail_json = ?
                   WHERE attempt_id = ? AND outcome IN ('reserved', 'dispatched')""",
                (
                    outcome,
                    prompt_tokens,
                    completion_tokens,
                    error_class,
                    json.dumps(detail, sort_keys=True) if detail else None,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"Attempt {attempt_id} is already terminal or unknown")

    def budget_usage(self, analysis_id: str, dispatch_day: str) -> dict[str, int]:
        """Ledger-derived usage for display; never authoritative for a decision alone."""
        placeholders = ",".join("?" * len(CHARGEABLE_OUTCOMES))
        analysis_rows = self._conn.execute(
            f"SELECT kind, reserved_tokens, prompt_tokens, completion_tokens FROM call_attempts"
            f" WHERE analysis_id = ? AND outcome IN ({placeholders})",
            (analysis_id, *CHARGEABLE_OUTCOMES),
        ).fetchall()
        day_rows = self._conn.execute(
            f"SELECT kind, reserved_tokens, prompt_tokens, completion_tokens FROM call_attempts"
            f" WHERE dispatch_day = ? AND outcome IN ({placeholders})",
            (dispatch_day, *CHARGEABLE_OUTCOMES),
        ).fetchall()

        def totals(rows: Sequence[sqlite3.Row]) -> tuple[int, int, int]:
            tokens = sum(_charge(row) for row in rows)
            exa = sum(1 for row in rows if ATTEMPT_KINDS.get(row["kind"]) == "exa")
            return len(rows), tokens, exa

        analysis_count, analysis_tokens, analysis_exa = totals(analysis_rows)
        day_count, day_tokens, day_exa = totals(day_rows)
        usage = {
            "analysis_requests": analysis_count,
            "analysis_tokens": analysis_tokens,
            "analysis_exa": analysis_exa,
            "day_requests": day_count,
            "day_tokens": day_tokens,
            "day_exa": day_exa,
        }
        for operation, kind in (
            ("search", "exa_search"),
            ("fetch", "exa_fetch"),
            ("discover", "exa_discover"),
            ("catalog", "provider_catalog"),
            ("probe", "provider_probe"),
            ("completion", "provider_request"),
        ):
            usage[f"analysis_{operation}"] = sum(row["kind"] == kind for row in analysis_rows)
            usage[f"day_{operation}"] = sum(row["kind"] == kind for row in day_rows)
        return usage

    def usage_summary(
        self, *, dispatch_day: str | None, analysis_id: str | None = None
    ) -> dict[str, object]:
        """Read a provider-separated, ledger-derived usage summary without mutations."""
        if analysis_id is None and dispatch_day is None:
            raise StorageError("Usage summary needs a UTC day or an analysis ID")
        if analysis_id is None:
            rows = self._conn.execute(
                """SELECT c.kind, c.dispatch_day, c.reserved_tokens, c.prompt_tokens,
                          c.completion_tokens, c.outcome, a.provider
                   FROM call_attempts AS c JOIN analyses AS a USING (analysis_id)
                   WHERE c.dispatch_day = ? ORDER BY c.attempt_id""",
                (dispatch_day,),
            ).fetchall()
            scope: dict[str, object] = {"kind": "utc_day", "dispatch_day": dispatch_day}
        else:
            rows = self._conn.execute(
                """SELECT c.kind, c.dispatch_day, c.reserved_tokens, c.prompt_tokens,
                          c.completion_tokens, c.outcome, a.provider
                   FROM call_attempts AS c JOIN analyses AS a USING (analysis_id)
                   WHERE c.analysis_id = ? ORDER BY c.attempt_id""",
                (analysis_id,),
            ).fetchall()
            scope = {"kind": "analysis", "analysis_id": analysis_id}

        def empty_stats() -> dict[str, object]:
            return {
                "attempts": 0,
                "outcomes": {},
                "reserved_tokens": 0,
                "budget_charged_tokens": 0,
                "measured_prompt_tokens": 0,
                "measured_completion_tokens": 0,
                "complete_measurements": 0,
                "missing_measurements": 0,
                "measurement_status": "not_applicable",
            }

        exa = {name: empty_stats() for name in ("search", "fetch", "discover")}
        providers: dict[str, dict[str, dict[str, object]]] = {}
        operation_for_kind = {
            "exa_search": ("exa", "search"),
            "exa_fetch": ("exa", "fetch"),
            "exa_discover": ("exa", "discover"),
            "provider_catalog": ("provider", "catalog"),
            "provider_probe": ("provider", "probe"),
            "provider_request": ("provider", "completion"),
        }
        for row in rows:
            category = operation_for_kind.get(str(row["kind"]))
            if category is None:
                continue
            owner, operation = category
            if owner == "exa":
                stats = exa[operation]
            else:
                provider = str(row["provider"] or "unattributed")
                provider_stats = providers.setdefault(
                    provider,
                    {name: empty_stats() for name in ("catalog", "probe", "completion")},
                )
                stats = provider_stats[operation]
            stats["attempts"] = int(stats["attempts"]) + 1
            outcomes = stats["outcomes"]
            assert isinstance(outcomes, dict)
            outcome = str(row["outcome"])
            outcomes[outcome] = int(outcomes.get(outcome, 0)) + 1
            reserved = int(row["reserved_tokens"] or 0)
            stats["reserved_tokens"] = int(stats["reserved_tokens"]) + reserved
            if row["prompt_tokens"] is not None:
                stats["measured_prompt_tokens"] = int(stats["measured_prompt_tokens"]) + int(
                    row["prompt_tokens"]
                )
            if row["completion_tokens"] is not None:
                stats["measured_completion_tokens"] = int(
                    stats["measured_completion_tokens"]
                ) + int(row["completion_tokens"])
            complete = row["prompt_tokens"] is not None and row["completion_tokens"] is not None
            if complete:
                stats["complete_measurements"] = int(stats["complete_measurements"]) + 1
            else:
                stats["missing_measurements"] = int(stats["missing_measurements"]) + 1
            if outcome in CHARGEABLE_OUTCOMES:
                stats["budget_charged_tokens"] = int(stats["budget_charged_tokens"]) + _charge(row)

        for group in [exa, *providers.values()]:
            for stats in group.values():
                attempts = int(stats["attempts"])
                complete = int(stats["complete_measurements"])
                missing = int(stats["missing_measurements"])
                stats["measurement_status"] = (
                    "not_applicable"
                    if attempts == 0
                    else "unavailable"
                    if complete == 0
                    else "partial"
                    if missing
                    else "complete"
                )
        return {"scope": scope, "exa": exa, "providers": providers}

    def checkpoint_item(
        self,
        analysis_id: str,
        item_id: str,
        *,
        state: str,
        result: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        """Persist one item result before the next dispatch."""
        if state not in {"done", "unknown", "deferred", "failed"}:
            raise StorageError(f"Unsupported item state: {state}")
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE analysis_items SET state = ?, result_json = ?, error = ?,
                       lease_until = NULL
                   WHERE analysis_id = ? AND item_id = ?""",
                (
                    state,
                    json.dumps(result, sort_keys=True) if result is not None else None,
                    error,
                    analysis_id,
                    item_id,
                ),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"Unknown analysis item: {analysis_id}/{item_id}")

    def finish_analysis(self, analysis_id: str, *, state: str) -> None:
        """Set a terminal state; a paused/running job is never silently completed."""
        if state not in {"completed", "partial", "failed", "cancelled", "paused"}:
            raise StorageError(f"Unsupported analysis state: {state}")
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE analyses SET state = ?, updated_utc = ? WHERE analysis_id = ?",
                (state, _utc_now(), analysis_id),
            )
            if cursor.rowcount != 1:
                raise StorageError(f"Unknown analysis: {analysis_id}")

    def save_summary(self, analysis_id: str, summary: str) -> bool:
        """Conditionally store the one local summary on a terminal analysis row."""
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE analyses SET summary = ?, updated_utc = ?
                   WHERE analysis_id = ? AND summary IS NULL
                   AND state IN ('completed', 'partial', 'failed', 'cancelled')""",
                (summary, _utc_now(), analysis_id),
            )
            return cursor.rowcount == 1

    def clear_summary(self, analysis_id: str) -> None:
        """Drop a previous terminal summary when a job is explicitly resumed.

        The summary is one column, not a history: a resumed job must not keep
        describing a state it has already left.
        """
        with self._write() as conn:
            conn.execute(
                "UPDATE analyses SET summary = NULL, updated_utc = ? WHERE analysis_id = ?",
                (_utc_now(), analysis_id),
            )

    def pause_interrupted(self, analysis_id: str) -> bool:
        """After restart, pause work that was mid-flight instead of replaying it."""
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE analyses SET state = 'paused', updated_utc = ?
                   WHERE analysis_id = ? AND state IN ('queued', 'running')""",
                (_utc_now(), analysis_id),
            )
            conn.execute(
                "UPDATE analysis_items SET state = 'pending', lease_until = NULL"
                " WHERE analysis_id = ? AND state = 'claimed'",
                (analysis_id,),
            )
            return cursor.rowcount == 1

    def reopen_deferred(self, analysis_id: str) -> int:
        """Return budget-deferred items to pending for an explicit resume.

        Only ``deferred`` items are reopened: a failed item stays failed so the
        operator sees it, and a completed or unknown item is never replayed.
        """
        with self._write() as conn:
            cursor = conn.execute(
                """UPDATE analysis_items SET state = 'pending', error = NULL,
                       lease_until = NULL
                   WHERE analysis_id = ? AND state = 'deferred'""",
                (analysis_id,),
            )
            return int(cursor.rowcount)

    def items(self, analysis_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM analysis_items WHERE analysis_id = ? ORDER BY item_id",
            (analysis_id,),
        )
        return [dict(row) for row in rows]

    def latest_analysis_results(self, *, analyzer_version: int = 2) -> list[dict[str, object]]:
        """Return the newest completed local result per exact candidate name."""
        rows = self._conn.execute(
            """SELECT a.analysis_id, a.created_utc, a.analyzer_version,
                      i.item_id, i.domain, i.state, i.result_json
               FROM analyses AS a JOIN analysis_items AS i USING (analysis_id)
               WHERE a.analyzer_version = ? AND i.state IN ('done', 'unknown')
                 AND i.result_json IS NOT NULL
               ORDER BY a.created_utc DESC, a.analysis_id DESC, i.item_id""",
            (analyzer_version,),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_attempts(self, analysis_id: str) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS n FROM call_attempts WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()
        return int(row["n"])


def open_store(path: str | Path, *, timeout: float = 5.0) -> Store:
    """Convenience opener that migrates before use."""
    store = Store.open(path, timeout=timeout)
    try:
        store.migrate()
    except BaseException:
        store.close()
        raise
    return store


__all__ = [
    "BudgetExceeded",
    "CHUNK_STATES",
    "ContractError",
    "SCHEMA_VERSION",
    "StorageError",
    "Store",
    "open_store",
]
