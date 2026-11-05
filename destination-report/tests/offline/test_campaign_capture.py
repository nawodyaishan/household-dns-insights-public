"""B2 bounded capture contracts using disposable databases and fake source processes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from test_campaign_store import START, Clock, namespace_file
from test_tools import load_tool

from household_report import storage as storage_module
from household_report.campaign import CampaignService
from household_report.capture_contract import CaptureError, validate_campaign_snapshot
from household_report.storage import StorageError, open_store


def envelope(start, end, generation="gen1", rows=None, retained=1, oldest=None):
    rows = [] if rows is None else rows
    return {
        "schema_version": 2,
        "start_epoch": start,
        "end_epoch": end,
        "captured_utc": "2027-01-15T00:00:00Z",
        "read_state": "ok",
        "source_generation": generation,
        "retained_rows": retained,
        "oldest_epoch": start - 1 if oldest is None else oldest,
        "window_count": len(rows),
        "observations": rows,
    }


def row(source_id, stamp, domain="example.test", status=2):
    return {
        "id": source_id,
        "timestamp": stamp,
        "type": 1,
        "status": status,
        "domain": domain,
        "client": "router",
    }


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = open_store(self.path / "db.sqlite3")
        self.addCleanup(self.store.close)
        rules = self.path / "rules.json"
        rules.write_bytes(namespace_file())
        self.clock = Clock(START)
        self.service = CampaignService(self.store, now=self.clock, namespace_path=rules)
        self.campaign = self.service.start(ack_empty=True)["campaign_id"]
        self.store.register_source_generation(generation_id="gen1", identity="resolver-a")
        self.clock.advance(3600 + 120)
        self.claim = self.service.claim_capture_work(generation_id="gen1")[0]
        self.chunk = self.claim["chunk_id"]

    def import_rows(self, rows, digest="a" * 64, *, reconcile=False):
        snapshot = envelope(START, START + 3600, rows=rows)
        return self.store.import_campaign_capture(
            self.campaign,
            chunk_id=self.chunk,
            generation_id="gen1",
            artifact_digest=digest,
            snapshot=snapshot,
            reconciled=reconcile,
        )

    def captured(self):
        self.assertTrue(
            self.service.ack_capture(
                self.chunk,
                token=self.claim["lease_token"],
                digest="a" * 64,
                path="capture-safe.json",
            )
        )
        self.assertTrue(self.service.mark_import_pending(self.chunk))

    def test_successful_empty_distinct_from_failed_or_unavailable(self):
        self.captured()
        self.assertEqual(self.import_rows([]), "successful_empty")
        self.assertEqual(self.store.campaign_query_rows(self.campaign), [])
        self.assertEqual(self.store.chunk(self.campaign, self.chunk)["state"], "successful_empty")
        uncertain = envelope(START, START + 3600, retained=None)
        self.assertEqual(
            self.store.import_campaign_capture(
                self.campaign,
                chunk_id=self.chunk,
                generation_id="gen1",
                artifact_digest="b" * 64,
                snapshot=uncertain,
                reconciled=True,
            ),
            "partial",
        )
        self.assertEqual(self.store.chunk(self.campaign, self.chunk)["state"], "partial")
        with self.assertRaises(CaptureError):
            validate_campaign_snapshot({**envelope(START, START + 3600), "read_state": "error"})

    def test_distinct_ids_survive_identical_rows_and_recapture_is_idempotent(self):
        self.captured()
        rows = [row(100, START + 60), row(101, START + 60)]
        self.import_rows(rows)
        self.import_rows(rows)
        self.assertEqual(len(self.store.campaign_query_rows(self.campaign)), 2)
        self.assertEqual(
            self.import_rows([row(100, START + 60, status=3)], "b" * 64, reconcile=True), "imported"
        )
        self.assertEqual(len(self.store.campaign_query_rows(self.campaign)), 2)
        self.assertEqual(self.store.campaign_query_rows(self.campaign)[0]["status"], 3)

    def test_conflicting_identity_rolls_back_entire_revision(self):
        self.captured()
        self.import_rows([row(100, START + 60)])
        with self.assertRaises(StorageError):
            self.import_rows([row(100, START + 60, "different.test")], "b" * 64, reconcile=True)
        self.assertEqual(len(self.store.campaign_query_rows(self.campaign)), 1)
        self.assertIsNone(self.store.chunk(self.campaign, self.chunk)["reconciled_utc"])

    def test_next_window_id_regression_refuses_import(self):
        self.captured()
        self.import_rows([row(100, START + 60)])
        self.clock.advance(3600)
        second = self.service.claim_capture_work(generation_id="gen1")[0]
        self.service.ack_capture(second["chunk_id"], token=second["lease_token"])
        self.service.mark_import_pending(second["chunk_id"])
        with self.assertRaises(StorageError):
            self.store.import_campaign_capture(
                self.campaign,
                chunk_id=second["chunk_id"],
                generation_id="gen1",
                artifact_digest="c" * 64,
                snapshot=envelope(START + 3600, START + 7200, rows=[row(99, START + 3660)]),
            )

    def test_v3_database_migrates_without_changing_campaign_rows(self):
        path = self.path / "old-v3.sqlite3"
        conn = sqlite3.connect(path, isolation_level=None)
        conn.executescript(storage_module._SCHEMA + storage_module._SCHEMA_V3)
        conn.execute("PRAGMA user_version = 3")
        conn.execute(
            """INSERT INTO campaigns (campaign_id, state, start_epoch, end_epoch,
               timezone, retention_days, rules_sha256, rules_state, rules_json,
               created_utc, updated_utc, last_clock_epoch)
               VALUES ('old-camp', 'active', 100, 200, 'UTC', 7, 'abc', 'available',
                       '[]', '2027-01-01T00:00:00Z', '2027-01-01T00:00:00Z', 100)"""
        )
        conn.close()
        with open_store(path) as migrated:
            self.assertEqual(migrated.campaign("old-camp")["rules_sha256"], "abc")
            self.assertEqual(migrated.migrate(), 7)

    def test_unreconciled_chunk_remains_a_gap_at_finalization_deadline(self):
        self.captured()
        self.import_rows([row(100, START + 60)])
        self.clock.epoch = START + 72 * 3600 + 120
        while claims := self.service.claim_capture_work(generation_id="gen1"):
            for claim in claims:
                self.service.ack_capture(claim["chunk_id"], token=claim["lease_token"])
                self.service.mark_import_pending(claim["chunk_id"])
                self.service.ack_import(claim["chunk_id"], outcome="imported")
        self.clock.epoch = START + 72 * 3600 + 86400
        result = self.service.finalize(self.campaign)
        self.assertEqual(result["state"], "complete_with_gaps")
        self.assertEqual(result["coverage"]["reconciliation_pending"], 72)


class ExportSafetyTest(unittest.TestCase):
    def test_campaign_empty_export_and_no_overwrite(self):
        from subprocess import CompletedProcess

        exporter = load_tool("export_snapshot")

        with tempfile.TemporaryDirectory() as directory:
            source = {
                "start_epoch": 100,
                "end_epoch": 200,
                "captured_utc": "2027-01-01T00:00:00Z",
                "window_count": 0,
                "retained_rows": 12,
                "observations": [],
            }

            def fake(*args, **kwargs):
                return CompletedProcess(args, 0, json.dumps(source), "")

            self.assertEqual(
                exporter.main(
                    [
                        "--input-dir",
                        directory,
                        "--start",
                        "100",
                        "--end",
                        "200",
                        "--generation",
                        "gen1",
                        "--artifact",
                        "safe",
                    ],
                    runner=fake,
                ),
                0,
            )
            saved = Path(directory) / "safe.json"
            self.assertEqual(json.loads(saved.read_bytes())["read_state"], "ok")
            original = hashlib.sha256(saved.read_bytes()).hexdigest()
            with self.assertRaises(SystemExit):
                exporter.main(
                    [
                        "--input-dir",
                        directory,
                        "--start",
                        "100",
                        "--end",
                        "200",
                        "--generation",
                        "gen1",
                        "--artifact",
                        "safe",
                    ],
                    runner=fake,
                )
            self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), original)

    def test_symlinked_directory_refused(self):
        exporter = load_tool("export_snapshot")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaises(SystemExit):
                exporter._require_private_dir(root / "link")


if __name__ == "__main__":
    unittest.main()
