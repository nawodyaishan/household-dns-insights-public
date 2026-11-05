"""B4 explicit private lifecycle: campaign-only retirement and isolated backup."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from test_campaign_store import START, VALID_RULE, Clock, namespace_file
from test_tools import load_tool

from household_report import storage as storage_module
from household_report.campaign import CampaignService
from household_report.campaign_retirement import CampaignRetirement, RetirementError
from household_report.storage import open_store


class RetirementTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.private = self.root / "input"
        self.private.mkdir(mode=0o700)
        self.db = self.root / "app.sqlite3"
        self.store = open_store(self.db)
        self.addCleanup(self.store.close)
        rules = self.root / "rules.json"
        rules.write_bytes(namespace_file([VALID_RULE]))
        self.clock = Clock(START)
        self.campaigns = CampaignService(self.store, now=self.clock, namespace_path=rules)
        self.id = self.campaigns.start(days=3)["campaign_id"]
        self.service = CampaignRetirement(self.store, input_dir=self.private)

    def test_requires_complete_campaign_preview_confirmation_and_backup_decision(self):
        preview = self.service.preview(self.id)
        with self.assertRaises(RetirementError):
            self.service.retire(
                self.id, expected_digest=preview["digest"], backup_choice="declined"
            )
        self.store.transition_campaign(
            self.id, expected_state="active", new_state="complete_with_gaps"
        )
        with self.assertRaises(RetirementError):
            self.service.retire(self.id, expected_digest="wrong", backup_choice="declined")
        with self.assertRaises(RetirementError):
            self.service.retire(
                self.id, expected_digest=preview["digest"], backup_choice="unspecified"
            )
        current = self.service.preview(self.id)
        self.service.retire(self.id, expected_digest=current["digest"], backup_choice="declined")
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM campaigns").fetchone()[0], 0
        )
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM campaign_retirements").fetchone()[0], 1
        )

    def test_backup_manifest_verifies_and_isolated_restore_preserves_legacy_rows(self):
        legacy = {
            "schema_version": 2,
            "start_epoch": START,
            "end_epoch": START + 3600,
            "captured_utc": "2027-01-01T00:00:00Z",
            "retained_rows": 1,
            "oldest_epoch": START + 10,
            "newest_epoch": START + 10,
            "window_count": 1,
            "observations": [
                {
                    "id": 1,
                    "timestamp": START + 10,
                    "type": 1,
                    "status": 2,
                    "domain": "private.example",
                    "client": "x",
                }
            ],
        }
        # Preserve a separate legacy row and a campaign-only artifact.
        self.store.import_snapshot(legacy, datasource="synthetic")
        artifact = self.private / "capture-testtoken.json"
        artifact.write_text("private evidence")
        (self.private / "manifest.json").write_text("legacy private file, not the backup manifest")
        archive = self.root / "archive"
        archive.mkdir(mode=0o700)
        with self.assertRaises(RetirementError):
            self.service.backup(archive)
        self.store.transition_campaign(self.id, expected_state="active", new_state="complete")
        manifest = self.service.backup(archive)
        self.assertIn("capture-testtoken.json", manifest["artifacts"])
        self.assertIn("manifest.json", manifest["artifacts"])
        self.assertEqual(
            (archive / "input" / "manifest.json").read_text(),
            "legacy private file, not the backup manifest",
        )
        self.assertEqual(
            manifest["database_sha256"],
            hashlib.sha256((archive / "app.sqlite3").read_bytes()).hexdigest(),
        )
        self.service.verify(archive)
        (archive / "app.sqlite3").write_bytes(b"tampered")
        with self.assertRaises(RetirementError):
            self.service.verify(archive)

    def test_retirement_removes_only_derived_artifact_and_preserves_shared_snapshot(self):
        self.store.register_source_generation(generation_id="g", identity="resolver")
        self.clock.epoch = START + 3600 + 120
        chunk = self.campaigns.claim_capture_work(generation_id="g", limit=1)[0]
        token = chunk["lease_token"]
        owned = self.private / f"capture-{token}.json"
        owned.write_text("owned")
        shared = self.private / "shared-snapshot.json"
        shared.write_text("shared")
        self.store.import_snapshot(
            {
                "schema_version": 2,
                "start_epoch": START,
                "end_epoch": START + 3600,
                "captured_utc": "2027-01-01T00:00:00Z",
                "retained_rows": 1,
                "oldest_epoch": START + 10,
                "newest_epoch": START + 10,
                "window_count": 1,
                "observations": [
                    {
                        "id": 1,
                        "timestamp": START + 10,
                        "type": 1,
                        "status": 2,
                        "domain": "shared.example",
                        "client": "x",
                    }
                ],
            },
            datasource="legacy",
        )
        self.campaigns.ack_capture(chunk["chunk_id"], token=token, digest="a" * 64, path=owned.name)
        self.store.transition_campaign(self.id, expected_state="active", new_state="complete")
        preview = self.service.preview(self.id)
        self.assertIn(owned.name, preview["artifact_names"])
        self.service.retire(self.id, expected_digest=preview["digest"], backup_choice="declined")
        self.assertFalse(owned.exists())
        self.assertTrue(shared.exists())
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM snapshots").fetchone()[0], 1
        )

    def test_retirement_cascades_frozen_reports_and_linked_job_results(self):
        job, _ = self.store.create_job(
            job_id="job-retire", campaign_id=self.id, kind="report", dedup_key="report-key"
        )
        self.store.save_frozen_report(
            report_id="report-retire",
            campaign_id=self.id,
            requested_start=START,
            requested_end=START + 3600,
            actual_start=START,
            actual_end=START + 3600,
            dedup_key="report-key",
            rules_sha256="rules",
            coverage_sha256="coverage",
            payload={"entries": []},
            expires_utc="2027-01-01T00:00:00Z",
        )
        self.store._conn.execute(
            "INSERT INTO campaign_job_results VALUES (?, ?)", (job, "report-retire")
        )
        self.store._conn.execute("UPDATE local_jobs SET state='ready' WHERE job_id=?", (job,))
        self.store.transition_campaign(self.id, expected_state="active", new_state="complete")
        self.service.retire(
            self.id,
            expected_digest=self.service.preview(self.id)["digest"],
            backup_choice="declined",
        )
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM frozen_reports").fetchone()[0], 0
        )
        self.assertEqual(
            self.store._conn.execute("SELECT count(*) FROM campaign_job_results").fetchone()[0], 0
        )
        for table in ("local_jobs", "campaign_queries", "capture_chunks", "capture_attempts"):
            self.assertEqual(
                self.store._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0, table
            )

    def test_retirement_refuses_pending_report_worker(self):
        self.store.transition_campaign(self.id, expected_state="active", new_state="complete")
        self.store.create_job(
            job_id="queued-report", campaign_id=self.id, kind="report", dedup_key="queued"
        )
        with self.assertRaises(RetirementError):
            self.service.retire(
                self.id,
                expected_digest=self.service.preview(self.id)["digest"],
                backup_choice="declined",
            )

    def test_archive_can_be_verified_and_restored_to_empty_isolated_directory(self):
        archive = self.root / "archive"
        archive.mkdir(mode=0o700)
        self.store.transition_campaign(self.id, expected_state="active", new_state="complete")
        self.service.backup(archive)
        restored = self.root / "restored"
        restored.mkdir(mode=0o700)
        self.service.restore(archive, restored)
        with open_store(restored / "app.sqlite3") as copy:
            self.assertEqual(copy.campaign(self.id)["campaign_id"], self.id)
        with self.assertRaises(RetirementError):
            self.service.restore(archive, restored)

    def test_typed_owner_cli_does_not_retire_without_confirmation(self):
        cli = load_tool("campaign_retirement")
        self.store.transition_campaign(self.id, expected_state="active", new_state="complete")
        digest = self.service.preview(self.id)["digest"]
        base = ["--db", str(self.db), "--input-dir", str(self.private)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main([*base, "preview", "--campaign", self.id]), 0)
        preview = json.loads(output.getvalue())
        self.assertEqual(preview["campaign_id"], self.id)
        self.assertEqual(preview["digest"], digest)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main([*base, "retire", "--campaign", self.id, "--digest", digest])
        self.assertEqual(self.store.campaign(self.id)["campaign_id"], self.id)

    def test_v5_database_migrates_to_v6_without_rewriting_campaign(self):
        path = self.root / "old-v5.sqlite3"
        connection = sqlite3.connect(path, isolation_level=None)
        connection.executescript(
            storage_module._SCHEMA
            + storage_module._SCHEMA_V3
            + storage_module._SCHEMA_V4
            + storage_module._SCHEMA_V5
        )
        connection.execute("PRAGMA user_version=5")
        connection.close()
        with open_store(path) as migrated:
            self.assertEqual(migrated.migrate(), 7)
            self.assertEqual(
                migrated._conn.execute("SELECT count(*) FROM campaign_retirements").fetchone()[0], 0
            )


if __name__ == "__main__":
    unittest.main()
