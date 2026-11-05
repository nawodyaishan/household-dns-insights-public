"""Maintenance transactions: journal, quiesced backup, isolated restore and rollback."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from test_campaign_store import START, VALID_RULE, Clock, namespace_file
from test_release import IMAGE, OTHER

from household_report.maintenance import (
    BACKUP_MANIFEST_SCHEMA,
    STAGE_ORDER,
    MaintenanceError,
    MaintenanceJournal,
    MaintenanceLock,
    UpgradeStages,
    check_restored_pair,
    maintenance_backup,
    open_store_for_restore,
    parse_backup_manifest,
    refuse_open_writers,
    restore_isolated,
    upgrade_guards,
    verify_backup,
)
from household_report.release import ReleaseError, ReleaseManifest
from household_report.storage import SCHEMA_VERSION, open_store

BASE = "sha256:" + "e" * 64


def manifest(image_id: str = IMAGE, schema_version: int = SCHEMA_VERSION) -> ReleaseManifest:
    return ReleaseManifest(
        image_id=image_id,
        source_revision="f" * 40,
        schema_version=schema_version,
        lock_sha256="c" * 64,
        base_image_digest=BASE,
        host_bundle_sha256="d" * 64,
        built_utc="2026-11-01T00:00:00Z",
    )


class JournalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"
        self.state.mkdir(mode=0o700)
        self.journal = MaintenanceJournal(self.state)

    def test_stages_must_run_in_order_and_are_resumable_after_crash(self):
        self.journal.begin(target_image_id=OTHER)
        self.assertEqual(self.journal.resume(), UpgradeStages.STOP_BRIDGE)
        self.journal.record(UpgradeStages.STOP_BRIDGE)
        # A crash between stages leaves the transaction active and resumable.
        self.assertEqual(self.journal.resume(), UpgradeStages.STOP_WRITERS)
        with self.assertRaises(MaintenanceError):
            self.journal.record(UpgradeStages.CHECK)
        for stage in STAGE_ORDER[1:]:
            self.journal.record(stage)
        self.assertIsNone(self.journal.resume())
        self.journal.complete()
        self.assertIsNone(self.journal.resume())

    def test_double_begin_and_unknown_stage_are_refused(self):
        self.journal.begin(target_image_id=OTHER)
        with self.assertRaises(MaintenanceError):
            self.journal.begin(target_image_id=OTHER)
        with self.assertRaises(MaintenanceError):
            self.journal.record("made-up-stage")
        self.journal.reset()
        self.journal.begin(target_image_id=OTHER)

    def test_corrupt_journal_is_visible_not_silent(self):
        (self.state / "maintenance-journal.json").write_text("{not json")
        with self.assertRaises(MaintenanceError):
            self.journal.load()


class LockTests(unittest.TestCase):
    def test_second_concurrent_lock_is_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "state"
        state.mkdir(mode=0o700)
        with MaintenanceLock(state):
            with self.assertRaises(MaintenanceError), MaintenanceLock(state):
                pass


def make_store(root: Path) -> tuple[object, str]:
    """One store with one active synthetic campaign and its namespace file."""
    store = open_store(root / "app.sqlite3")
    rules = root / "rules.json"
    rules.write_bytes(namespace_file([VALID_RULE]))
    from household_report.campaign import CampaignService

    campaigns = CampaignService(store, now=Clock(START), namespace_path=rules)
    campaign_id = campaigns.start(days=3)["campaign_id"]
    return store, campaign_id


class BackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.input = self.root / "input"
        self.input.mkdir(mode=0o700)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.store, self.campaign_id = make_store(self.root)
        self.addCleanup(self.store.close)
        (self.input / ("capture-" + "a" * 32 + ".json")).write_text("evidence")
        self.archive = self.root / "archive"
        self.archive.mkdir(mode=0o700)
        self.journal = MaintenanceJournal(self.state)

    def test_active_campaign_is_preserved_with_its_original_deadline(self):
        self.journal.begin(target_image_id=OTHER)
        document = maintenance_backup(
            self.store,
            input_dir=self.input,
            destination=self.archive,
            state_dir=self.state,
            manifest=manifest(),
        )
        self.assertEqual(document["manifest_schema"], BACKUP_MANIFEST_SCHEMA)
        self.assertEqual(document["application_schema"], SCHEMA_VERSION)
        campaigns = document["campaigns"]
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(campaigns[0]["campaign_id"], self.campaign_id)
        self.assertEqual(campaigns[0]["state"], "active")
        # An active campaign has no deadline yet; the stored value stays None.
        self.assertIsNone(campaigns[0]["finalization_deadline"])
        self.assertNotIn("rules_json", campaigns[0])

    def test_finalizing_deadline_survives_the_backup(self):
        deadline = START + 3 * 24 * 3600 + 86400
        self.assertTrue(
            self.store.transition_campaign(
                self.campaign_id,
                expected_state="active",
                new_state="finalizing",
                finalization_deadline=deadline,
            )
        )
        original = self.store.campaign(self.campaign_id)["finalization_deadline"]
        self.assertIsNotNone(original)
        self.journal.begin(target_image_id=OTHER)
        document = maintenance_backup(
            self.store,
            input_dir=self.input,
            destination=self.archive,
            state_dir=self.state,
            manifest=manifest(),
        )
        self.assertEqual(document["campaigns"][0]["finalization_deadline"], original)

    def test_backup_requires_an_active_maintenance_journal(self):
        with self.assertRaises(MaintenanceError):
            maintenance_backup(
                self.store,
                input_dir=self.input,
                destination=self.archive,
                state_dir=self.state,
                manifest=manifest(),
            )

    def test_backup_refuses_nonempty_or_public_destination(self):
        self.journal.begin(target_image_id=OTHER)
        (self.archive / "stale").write_text("x")
        with self.assertRaises(MaintenanceError):
            maintenance_backup(
                self.store,
                input_dir=self.input,
                destination=self.archive,
                state_dir=self.state,
                manifest=manifest(),
            )
        (self.archive / "stale").unlink()
        self.archive.chmod(0o755)
        with self.assertRaises(MaintenanceError):
            maintenance_backup(
                self.store,
                input_dir=self.input,
                destination=self.archive,
                state_dir=self.state,
                manifest=manifest(),
            )
        self.archive.chmod(0o700)

    def test_verify_detects_tampering_and_schema_disagreement(self):
        self.journal.begin(target_image_id=OTHER)
        maintenance_backup(
            self.store,
            input_dir=self.input,
            destination=self.archive,
            state_dir=self.state,
            manifest=manifest(),
        )
        verify_backup(self.archive)
        (self.archive / "input" / ("capture-" + "a" * 32 + ".json")).write_text("tampered")
        with self.assertRaises(MaintenanceError):
            verify_backup(self.archive)
        manifest_document = json.loads((self.archive / "manifest.json").read_text())
        manifest_document["application_schema"] = 99
        (self.archive / "manifest.json").write_text(json.dumps(manifest_document))
        with self.assertRaises(MaintenanceError):
            verify_backup(self.archive)

    def test_parse_rejects_unknown_manifest_schema(self):
        with self.assertRaises(MaintenanceError):
            parse_backup_manifest({"manifest_schema": 1})


class RestoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.input = self.root / "input"
        self.input.mkdir(mode=0o700)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.store, self.campaign_id = make_store(self.root)
        self.addCleanup(self.store.close)
        self.archive = self.root / "archive"
        self.archive.mkdir(mode=0o700)
        self.journal = MaintenanceJournal(self.state)
        self.journal.begin(target_image_id=OTHER)
        self.artifact = "capture-" + "a" * 32 + ".json"
        (self.input / self.artifact).write_text("evidence")

    def backup(self):
        return maintenance_backup(
            self.store,
            input_dir=self.input,
            destination=self.archive,
            state_dir=self.state,
            manifest=manifest(),
        )

    def test_restore_into_empty_isolated_directory_preserves_data(self):
        self.backup()
        destination = self.root / "restore"
        destination.mkdir(mode=0o700)
        restored = restore_isolated(self.archive, destination)
        self.assertEqual(restored["application_schema"], SCHEMA_VERSION)
        self.assertEqual((destination / "input" / self.artifact).read_text(), "evidence")
        with open_store_for_restore(destination / "app.sqlite3") as store:
            self.assertEqual(store._conn.execute("SELECT count(*) FROM campaigns").fetchone()[0], 1)

    def test_restore_refuses_nonempty_destination_and_public_modes(self):
        self.backup()
        destination = self.root / "restore"
        destination.mkdir(mode=0o755)
        with self.assertRaises(MaintenanceError):
            restore_isolated(self.archive, destination)
        destination.rmdir()
        destination.mkdir(mode=0o700)
        (destination / "occupied").write_text("x")
        with self.assertRaises(MaintenanceError):
            restore_isolated(self.archive, destination)

    def test_newer_schema_backup_is_refused_for_this_application(self):
        # A backup written by a newer application schema cannot be opened here.
        import hashlib
        import sqlite3

        newer = self.root / "newer-archive"
        newer.mkdir(mode=0o700)
        database = newer / "app.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
            connection.commit()
        finally:
            connection.close()
        database.chmod(0o600)
        manifest_document = {
            "manifest_schema": BACKUP_MANIFEST_SCHEMA,
            "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "artifacts": {},
            "application_schema": SCHEMA_VERSION + 1,
            "release": {"image_id": IMAGE, "source_revision": "f" * 40},
            "campaigns": [],
            "config_fingerprint": None,
        }
        (newer / "manifest.json").write_text(json.dumps(manifest_document))
        destination = self.root / "restore"
        destination.mkdir(mode=0o700)
        with self.assertRaises(ReleaseError):
            restore_isolated(newer, destination)

    def test_original_store_remains_untouched_after_restore(self):
        self.backup()
        destination = self.root / "restore"
        destination.mkdir(mode=0o700)
        restore_isolated(self.archive, destination)
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM campaigns").fetchone()[0], 1
        )


class UpgradeGuardTests(unittest.TestCase):
    def test_upgrade_plan_is_ordered_and_checked(self):
        plan = upgrade_guards(manifest(), manifest(image_id=OTHER))
        self.assertEqual(plan["stages"], list(STAGE_ORDER))
        self.assertEqual(plan["to_image_id"], OTHER)

    def test_noop_and_schema_incompatible_targets_are_refused(self):
        with self.assertRaises(MaintenanceError):
            upgrade_guards(manifest(), manifest())
        with self.assertRaises(ReleaseError):
            upgrade_guards(manifest(), manifest(image_id=OTHER, schema_version=SCHEMA_VERSION + 1))

    def test_rollback_across_incompatible_schema_requires_isolated_restore(self):
        with self.assertRaises(MaintenanceError):
            upgrade_guards(
                manifest(schema_version=SCHEMA_VERSION),
                manifest(image_id=OTHER, schema_version=SCHEMA_VERSION - 1),
            )

    def test_open_writers_block_migration(self):
        refuse_open_writers(["stopped", "stopped", "absent"])
        with self.assertRaises(MaintenanceError):
            refuse_open_writers(["running", "stopped"])

    def test_recreated_pair_must_match_the_target(self):
        target = manifest(image_id=OTHER)
        check_restored_pair(OTHER, OTHER, target)
        with self.assertRaises(MaintenanceError):
            check_restored_pair(IMAGE, OTHER, target)


if __name__ == "__main__":
    unittest.main()
