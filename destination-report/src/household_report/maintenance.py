"""Maintenance transactions: quiesce, backup, isolated restore and rollback guards.

The current retirement backup refuses active/finalizing campaigns because an owner
retirement must not race live capture. Maintenance is different: an upgrade stops the
bridge and both application writers *under one maintenance lock*, then takes a
consistent SQLite snapshot that may legitimately contain a paused active campaign.
The manifest records the campaign's state and original finalization deadline so a
restored deployment resumes against the same deadline instead of silently renewing it.

Stage journal: every stage is recorded before its work runs, so a crash at any point
leaves a resumable, never silently-skipped state. Restore targets are always empty,
isolated 0700 directories; production promotion is a separate explicit operation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .release import ReleaseManifest, check_schema_compatibility
from .storage import SCHEMA_VERSION, Store

BACKUP_MANIFEST_SCHEMA = 2
ARTIFACT_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


class MaintenanceError(RuntimeError):
    """A maintenance precondition failed; the detail is sanitized."""


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(part)
    return sha.hexdigest()


def _private(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
        raise MaintenanceError(f"{label} must be a private 0700 regular directory")


def _atomic_write_json(path: Path, document: Mapping[str, object]) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".journal-")
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(document, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# -- maintenance lock and stage journal --------------------------------------


class MaintenanceLock:
    """One exclusive host lock; a second maintenance run refuses to start."""

    def __init__(self, state_dir: Path) -> None:
        self._path = state_dir / "maintenance.lock"

    def __enter__(self) -> MaintenanceLock:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self._fd)
            raise MaintenanceError("Another maintenance transaction is running") from error
        return self

    def __exit__(self, *exc_info: object) -> None:
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)


@dataclass(frozen=True, slots=True)
class UpgradeStages:
    """The fixed ordered stage names of one upgrade/rollback transaction."""

    STOP_BRIDGE = "stop-bridge"
    STOP_WRITERS = "stop-writers"
    BACKUP = "backup"
    MIGRATE = "migrate"
    RECREATE = "recreate"
    CHECK = "check"


STAGE_ORDER = (
    UpgradeStages.STOP_BRIDGE,
    UpgradeStages.STOP_WRITERS,
    UpgradeStages.BACKUP,
    UpgradeStages.MIGRATE,
    UpgradeStages.RECREATE,
    UpgradeStages.CHECK,
)


class MaintenanceJournal:
    """Crash-safe ordered stage journal stored inside private state."""

    def __init__(self, state_dir: Path) -> None:
        self._path = state_dir / "maintenance-journal.json"

    def load(self) -> dict[str, object]:
        if not self._path.exists():
            return {"completed": [], "active": False}
        try:
            document = json.loads(self._path.read_text())
        except (OSError, ValueError) as error:
            raise MaintenanceError("Maintenance journal is unreadable") from error
        if not isinstance(document, dict) or not isinstance(document.get("completed"), list):
            raise MaintenanceError("Maintenance journal has an unexpected structure")
        return document

    def begin(self, *, target_image_id: str) -> None:
        document = self.load()
        if document.get("active"):
            raise MaintenanceError(
                "An earlier maintenance transaction is incomplete; resume or reset it explicitly"
            )
        _atomic_write_json(
            self._path, {"completed": [], "active": True, "target_image_id": target_image_id}
        )

    def record(self, stage: str) -> None:
        """Record a stage BEFORE its work runs; crash leaves it visibly incomplete."""
        if stage not in STAGE_ORDER:
            raise MaintenanceError("Unknown maintenance stage")
        document = self.load()
        completed = [str(item) for item in document["completed"]]
        if stage in completed:
            raise MaintenanceError("Stage already recorded")
        expected = STAGE_ORDER[len(completed)]
        if stage != expected:
            raise MaintenanceError(f"Stage {stage!r} out of order; expected {expected!r}")
        completed.append(stage)
        _atomic_write_json(self._path, {**document, "completed": completed})

    def complete(self) -> None:
        document = self.load()
        _atomic_write_json(self._path, {**document, "active": False})

    def reset(self) -> None:
        _atomic_write_json(self._path, {"completed": [], "active": False})

    def resume(self) -> str | None:
        """The next stage to run, or None when the transaction is complete."""
        document = self.load()
        if not document.get("active"):
            return None
        completed = [str(item) for item in document["completed"]]
        if len(completed) == len(STAGE_ORDER):
            return None
        return STAGE_ORDER[len(completed)]


# -- maintenance backup and isolated restore ---------------------------------


def _campaign_summary(row: Mapping[str, object]) -> dict[str, object]:
    """Sanitized campaign identity: bounds and deadline only, never domains."""
    return {
        "campaign_id": str(row["campaign_id"]),
        "state": str(row["state"]),
        "end_epoch": int(row["end_epoch"]),
        "finalization_deadline": (
            int(row["finalization_deadline"]) if row["finalization_deadline"] is not None else None
        ),
    }


def maintenance_backup(
    store: Store,
    *,
    input_dir: Path,
    destination: Path,
    state_dir: Path,
    manifest: ReleaseManifest,
    config_fingerprint: str | None = None,
) -> dict[str, object]:
    """Consistent private backup under an already-held maintenance lock.

    Unlike owner retirement, an active/finalizing campaign is allowed: the writers
    are quiesced by the maintenance transaction, and the manifest records each
    campaign's original deadline so recovery preserves it.
    """
    _private(destination, label="Backup destination")
    _private(input_dir, label="Input directory")
    if any(destination.iterdir()):
        raise MaintenanceError("Backup directory must be empty")
    if not MaintenanceJournal(state_dir).load().get("active"):
        raise MaintenanceError("Maintenance backup requires an active maintenance journal")

    database = destination / "app.sqlite3"
    with closing(sqlite3.connect(database)) as copy, store._conn_lock:
        store._conn.backup(copy)
    database.chmod(0o600)

    schema_version = int(store._conn.execute("PRAGMA user_version").fetchone()[0])
    campaigns = [
        _campaign_summary(row)
        for row in store._conn.execute(
            "SELECT campaign_id, state, end_epoch, finalization_deadline FROM campaigns"
        )
    ]

    artifact_dir = destination / "input"
    artifact_dir.mkdir(mode=0o700)
    artifacts: dict[str, str] = {}
    for path in sorted(input_dir.iterdir()):
        name = path.name
        if not ARTIFACT_NAME.fullmatch(name):
            raise MaintenanceError("Unsafe private input name")
        if path.is_symlink():
            raise MaintenanceError("Symlinked private input refused")
        if not path.is_file():
            continue
        target = artifact_dir / name
        with path.open("rb") as reader, target.open("xb") as writer:
            os.chmod(target, 0o600)
            for part in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(part)
        artifacts[name] = _digest(target)

    manifest_document = {
        "manifest_schema": BACKUP_MANIFEST_SCHEMA,
        "database_sha256": _digest(database),
        "artifacts": artifacts,
        "application_schema": schema_version,
        "release": {
            "image_id": manifest.image_id,
            "source_revision": manifest.source_revision,
            "fingerprint": manifest.fingerprint(),
        },
        "campaigns": campaigns,
        "config_fingerprint": config_fingerprint,
    }
    file = destination / "manifest.json"
    file.write_text(json.dumps(manifest_document, sort_keys=True))
    file.chmod(0o600)
    return manifest_document


def parse_backup_manifest(document: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(document, Mapping):
        raise MaintenanceError("Backup manifest must be a JSON object")
    if document.get("manifest_schema") != BACKUP_MANIFEST_SCHEMA:
        raise MaintenanceError("Unsupported backup manifest schema")
    for key in ("database_sha256", "artifacts", "application_schema", "release", "campaigns"):
        if key not in document:
            raise MaintenanceError(f"Backup manifest is missing {key}")
    if not isinstance(document["artifacts"], Mapping):
        raise MaintenanceError("Backup artifacts must be a mapping")
    if not isinstance(document["campaigns"], list):
        raise MaintenanceError("Backup campaigns must be a list")
    return dict(document)


def verify_backup(destination: Path) -> dict[str, object]:
    """Digest, integrity and structure verification of a maintenance backup."""
    _private(destination, label="Backup directory")
    manifest_file = destination / "manifest.json"
    database = destination / "app.sqlite3"
    if manifest_file.is_symlink() or database.is_symlink():
        raise MaintenanceError("Symlinked backup refused")
    try:
        manifest = parse_backup_manifest(json.loads(manifest_file.read_text()))
        if manifest["database_sha256"] != _digest(database):
            raise MaintenanceError("Backup database digest mismatch")
        for name, digest in manifest["artifacts"].items():
            path = destination / "input" / str(name)
            if (
                path.is_symlink()
                or not ARTIFACT_NAME.fullmatch(str(name))
                or _digest(path) != digest
            ):
                raise MaintenanceError("Backup artifact digest mismatch")
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as copy:
            if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise MaintenanceError("Backup integrity check failed")
            restored_schema = int(copy.execute("PRAGMA user_version").fetchone()[0])
    except (OSError, KeyError, TypeError, ValueError, sqlite3.DatabaseError) as error:
        if isinstance(error, MaintenanceError):
            raise
        raise MaintenanceError("Backup verification failed") from error
    if restored_schema != int(manifest["application_schema"]):
        raise MaintenanceError("Backup schema disagrees with its own manifest")
    return manifest


def restore_isolated(
    archive: Path,
    destination: Path,
    *,
    application_schema: int = SCHEMA_VERSION,
) -> dict[str, object]:
    """Restore into an empty isolated 0700 directory; never onto production.

    A backup written by a newer application schema is refused: opening it would be
    an implicit in-place downgrade. Promotion to production is a separate decision.
    """
    manifest = verify_backup(archive)
    check_schema_compatibility(int(manifest["application_schema"]), application_schema)
    _private(destination, label="Restore destination")
    if any(destination.iterdir()):
        raise MaintenanceError("Restore destination must be empty")
    input_dir = destination / "input"
    input_dir.mkdir(mode=0o700)
    for name in ("app.sqlite3", *manifest["artifacts"]):
        source = archive / ("input" if name != "app.sqlite3" else "") / str(name)
        target = (input_dir if name != "app.sqlite3" else destination) / str(name)
        with source.open("rb") as reader, target.open("xb") as writer:
            os.chmod(target, 0o600)
            for part in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(part)
    return manifest


# -- upgrade transaction guards ----------------------------------------------


def upgrade_guards(
    current: ReleaseManifest,
    target: ReleaseManifest,
    *,
    application_schema: int = SCHEMA_VERSION,
) -> dict[str, object]:
    """Validate a planned release switch before any writer is stopped."""
    if current.image_id == target.image_id:
        raise MaintenanceError("Target release equals the running release")
    check_schema_compatibility(target.schema_version, application_schema)
    # A rollback across an incompatible schema must go through a verified
    # pre-upgrade restore into a new directory, never an in-place downgrade.
    if target.schema_version < current.schema_version:
        raise MaintenanceError(
            "Rollback across an incompatible schema requires a pre-upgrade "
            "isolated restore, not an in-place downgrade"
        )
    return {
        "stages": list(STAGE_ORDER),
        "from_image_id": current.image_id,
        "to_image_id": target.image_id,
        "schema_from": current.schema_version,
        "schema_to": target.schema_version,
    }


def refuse_open_writers(states: Sequence[str]) -> None:
    """Both writers and the bridge must be stopped before migrate/recreate."""
    if any(state not in {"stopped", "absent"} for state in states):
        raise MaintenanceError("Writers must be quiesced before the schema migration")


def check_restored_pair(shared_image: str, owner_image: str, target: ReleaseManifest) -> None:
    """After recreation both containers must match the target exactly."""
    if shared_image != target.image_id or owner_image != target.image_id:
        raise MaintenanceError(
            "Recreated deployment is mixed; the upgrade failed and both instances must stay stopped"
        )


def open_store_for_restore(database: Path) -> Store:
    """Open a restored database read-only for verification, refusing unknown schema."""
    store = Store.open(database)
    try:
        version = int(store._conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as error:
        store.close()
        raise MaintenanceError("Restored database is unreadable") from error
    if version > SCHEMA_VERSION:
        store.close()
        raise MaintenanceError("Restored database schema is newer than this application")
    if version == 0:
        store.close()
        raise MaintenanceError("Restored database has no schema")
    return store


__all__ = [
    "BACKUP_MANIFEST_SCHEMA",
    "MaintenanceError",
    "MaintenanceJournal",
    "MaintenanceLock",
    "STAGE_ORDER",
    "UpgradeStages",
    "check_restored_pair",
    "maintenance_backup",
    "open_store_for_restore",
    "parse_backup_manifest",
    "refuse_open_writers",
    "restore_isolated",
    "upgrade_guards",
    "verify_backup",
]
