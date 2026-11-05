"""Explicit private campaign retirement and verifiable isolated SQLite backup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .storage import StorageError, Store


class RetirementError(ValueError):
    """Retirement/backup precondition is unsafe or changed."""


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(part)
    return sha.hexdigest()


def _private(path: Path) -> None:
    if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
        raise RetirementError("A private 0700 regular directory is required")


class CampaignRetirement:
    def __init__(self, store: Store | None, *, input_dir: Path):
        self.store = store
        self.input_dir = input_dir

    def preview(self, campaign_id: str) -> dict[str, object]:
        try:
            return self.store.retirement_preview(campaign_id)
        except StorageError as error:
            raise RetirementError(str(error)) from error

    def _owned_file(self, name: str) -> Path:
        if not re.fullmatch(r"(?:capture-[a-f0-9]{32}|reconcile-[a-f0-9]{32})\.json", name):
            raise RetirementError("Unexpected campaign artifact name")
        path = self.input_dir / name
        if path.is_symlink():
            raise RetirementError("Symlinked campaign artifact refused")
        return path

    def retire(
        self, campaign_id: str, *, expected_digest: str, backup_choice: str
    ) -> dict[str, object]:
        _private(self.input_dir)
        preview = self.preview(campaign_id)
        if (
            preview["digest"] != expected_digest
            or preview["state"] not in {"complete", "complete_with_gaps"}
            or backup_choice not in {"backed_up", "declined"}
        ):
            raise RetirementError("Review a completed campaign and explicit backup choice")
        paths = [self._owned_file(name) for name in preview["artifact_names"]]
        try:
            retired = self.store.retire_campaign(
                campaign_id, expected_digest=expected_digest, backup_choice=backup_choice
            )
        except StorageError as error:
            raise RetirementError(str(error)) from error
        # Missing files are already cleaned; only derived, campaign-owned names may be removed.
        # A crash here leaves a private orphan, never deletes a shared legacy row/file.
        for path in paths:
            if path.is_file() and not path.is_symlink():
                path.unlink()
        return retired

    def backup(self, destination: Path) -> dict[str, object]:
        _private(destination)
        _private(self.input_dir)
        if self.store is None or any(
            campaign["state"] in {"active", "finalizing"} for campaign in self.store.campaigns()
        ):
            raise RetirementError("Finish all campaigns before a consistent private backup")
        if any(destination.iterdir()):
            raise RetirementError("Backup directory must be empty")
        database = destination / "app.sqlite3"
        # SQLite's backup API snapshots the WAL safely without copying open DB files.
        with closing(sqlite3.connect(database)) as copy, self.store._conn_lock:
            self.store._conn.backup(copy)
        database.chmod(0o600)
        names = sorted(
            path.name for path in self.input_dir.iterdir() if path.is_file() or path.is_symlink()
        )
        artifact_dir = destination / "input"
        artifact_dir.mkdir(mode=0o700)
        artifacts: dict[str, str] = {}
        for name in names:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
                raise RetirementError("Unsafe private input name")
            source = self.input_dir / name
            if source.is_symlink():
                raise RetirementError("Symlinked private input refused")
            if not source.is_file():
                continue
            target = artifact_dir / name
            with source.open("rb") as reader, target.open("xb") as writer:
                os.chmod(target, 0o600)
                for part in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(part)
            artifacts[name] = _digest(target)
        manifest = {
            "schema_version": 1,
            "database_sha256": _digest(database),
            "artifacts": artifacts,
        }
        file = destination / "manifest.json"
        file.write_text(json.dumps(manifest, sort_keys=True))
        file.chmod(0o600)
        return manifest

    def verify(self, destination: Path) -> dict[str, object]:
        _private(destination)
        manifest_file = destination / "manifest.json"
        database = destination / "app.sqlite3"
        if manifest_file.is_symlink() or database.is_symlink():
            raise RetirementError("Symlinked backup refused")
        try:
            manifest = json.loads(manifest_file.read_text())
            if manifest["database_sha256"] != _digest(database):
                raise RetirementError("Backup database digest mismatch")
            for name, digest in manifest["artifacts"].items():
                path = destination / "input" / name
                if (
                    path.is_symlink()
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
                    or _digest(path) != digest
                ):
                    raise RetirementError("Backup artifact digest mismatch")
            with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as copy:
                if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RetirementError("Backup integrity check failed")
            return manifest
        except (OSError, KeyError, TypeError, ValueError, sqlite3.DatabaseError) as error:
            raise RetirementError("Backup verification failed") from error

    def restore(self, archive: Path, destination: Path) -> dict[str, object]:
        """Only an empty private isolation directory; never overwrite running state."""
        manifest = self.verify(archive)
        _private(destination)
        if any(destination.iterdir()):
            raise RetirementError("Restore destination must be empty")
        input_dir = destination / "input"
        input_dir.mkdir(mode=0o700)
        for name in ("app.sqlite3", *manifest["artifacts"]):
            source = archive / ("input" if name != "app.sqlite3" else "") / name
            target = (input_dir if name != "app.sqlite3" else destination) / name
            with source.open("rb") as reader, target.open("xb") as writer:
                os.chmod(target, 0o600)
                shutil.copyfileobj(reader, writer)
        return manifest
