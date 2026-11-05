"""B3 contracts: frozen five-day union, queued reports and allowlisted exports."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from test_campaign_store import START, VALID_RULE, Clock, namespace_file
from test_tools import load_tool

from household_report import storage as storage_module
from household_report.campaign import CampaignService, covered_local_days
from household_report.campaign_reporting import CampaignReportError, CampaignReportService
from household_report.storage import StorageError, open_store


def row(identifier, timestamp, domain="play.games.example", status=2):
    return {
        "id": identifier,
        "timestamp": timestamp,
        "type": 1,
        "status": status,
        "domain": domain,
        "client": "router",
        "reply_type": 4,
    }


class CampaignReportTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = open_store(Path(temporary.name) / "app.sqlite3")
        self.addCleanup(self.store.close)
        self.clock = Clock(START)
        rules = Path(temporary.name) / "rules.json"
        rules.write_bytes(namespace_file([VALID_RULE]))
        self.campaign_service = CampaignService(
            self.store, now=self.clock, namespace_path=rules, timezone="America/New_York"
        )
        self.campaign = self.campaign_service.start(days=5, retention_days=7)["campaign_id"]
        self.store.register_source_generation(generation_id="gen1", identity="resolver-a")
        self.service = CampaignReportService(self.store, now=self.clock)

    def capture(self, index, rows, *, generation="gen1", oldest=None, reconcile=False):
        start = START + index * 3600
        end = start + 3600
        chunk_id = f"{self.campaign}:{start}:{end}"
        if not reconcile:
            self.clock.epoch = max(self.clock.epoch, end + 120)
            claim = self.campaign_service.claim_capture_work(generation_id=generation, limit=10)
            selected = next(item for item in claim if item["chunk_id"] == chunk_id)
            self.campaign_service.ack_capture(
                chunk_id, token=selected["lease_token"], digest="a" * 64, path="capture-test.json"
            )
            self.campaign_service.mark_import_pending(chunk_id)
        snapshot = {
            "schema_version": 2,
            "read_state": "ok",
            "source_generation": generation,
            "start_epoch": start,
            "end_epoch": end,
            "window_count": len(rows),
            "observations": rows,
            "retained_rows": 100,
            "oldest_epoch": start - 3600 if oldest is None else oldest,
            "captured_utc": "2027-01-01T00:00:00Z",
        }
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return self.store.import_campaign_capture(
            self.campaign,
            chunk_id=chunk_id,
            generation_id=generation,
            artifact_digest=digest,
            snapshot=snapshot,
            reconciled=reconcile,
        )

    def request_and_run(self, **kwargs):
        job_id = self.service.request(self.campaign, **kwargs)
        self.service.run_next(self.campaign)
        return self.service.job_status(job_id)

    def test_five_day_report_keeps_distinct_ids_and_exposes_gaps(self):
        self.capture(0, [row(1, START + 60), row(2, START + 60)])
        self.clock.epoch = START + 120 * 3600 + 120
        report = self.request_and_run()
        self.assertEqual(report["state"], "ready")
        payload = self.service.get(report["report_id"])
        self.assertEqual(payload["window"]["requested_end"], START + 120 * 3600)
        self.assertEqual(payload["counts"]["eligible_rows"], 2)
        self.assertEqual(payload["coverage"]["unresolved_chunks"], 119)
        self.assertFalse(payload["coverage"]["fully_resolved"])
        self.assertEqual(len(payload["entries"]), 1)

    def test_complete_120_hour_union_has_no_duplicate_queries(self):
        for index in range(120):
            self.capture(index, [row(index + 1, START + index * 3600 + 60)])
        for chunk in self.store.chunks(self.campaign):
            self.store.mark_reconciled(self.campaign, chunk_id=chunk["chunk_id"])
        status = self.request_and_run()
        payload = self.service.get(status["report_id"])
        self.assertEqual(
            payload["window"]["end_epoch"] - payload["window"]["start_epoch"], 120 * 3600
        )
        self.assertEqual(payload["counts"]["eligible_rows"], 120)
        self.assertEqual(payload["counts"]["snapshot_rows"], 120)
        self.assertEqual(len(payload["timeline"]["bins"]), 1440)
        self.assertTrue(payload["coverage"]["fully_resolved"])

    def test_v4_migration_preserves_existing_capture_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v4.sqlite3"
            conn = sqlite3.connect(path, isolation_level=None)
            conn.executescript(
                storage_module._SCHEMA + storage_module._SCHEMA_V3 + storage_module._SCHEMA_V4
            )
            conn.execute("PRAGMA user_version = 4")
            conn.execute(
                """INSERT INTO campaigns (campaign_id, state, start_epoch, end_epoch,
                   timezone, retention_days, rules_sha256, rules_state, rules_json,
                   created_utc, updated_utc, last_clock_epoch)
                   VALUES ('old', 'active', 100, 200, 'UTC', 7, 'hash', 'available',
                           '[]', '2027-01-01T00:00:00Z', '2027-01-01T00:00:00Z', 100)"""
            )
            conn.execute(
                "INSERT INTO source_generations (generation_id, identity, configured_utc)"
                " VALUES ('g', 'resolver', '2027-01-01T00:00:00Z')"
            )
            conn.execute("""INSERT INTO campaign_queries
                         (campaign_id, generation_id, source_id, immutable_sha256, row_json,
                          updated_utc) VALUES ('old','g',8,'sha','{}','2027-01-01T00:00:00Z')""")
            conn.close()
            with open_store(path) as migrated:
                self.assertEqual(migrated.migrate(), 7)
                self.assertEqual(
                    migrated._conn.execute("SELECT source_id FROM campaign_queries").fetchone()[0],
                    8,
                )
                self.assertEqual(
                    migrated._conn.execute("SELECT count(*) FROM campaign_job_results").fetchone()[
                        0
                    ],
                    0,
                )

    def test_successful_empty_is_not_a_missing_report(self):
        self.capture(0, [])
        self.clock.epoch = START + 3600 + 120
        status = self.request_and_run()
        self.assertEqual(status["state"], "ready")
        payload = self.service.get(status["report_id"])
        self.assertEqual(payload["counts"]["eligible_rows"], 0)
        self.assertEqual(payload["coverage"]["by_state"]["successful_empty"], 1)

    def test_equivalent_clicks_reuse_job_and_later_rows_create_new_revision(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        first = self.service.request(self.campaign)
        self.assertEqual(first, self.service.request(self.campaign))
        self.service.run_next(self.campaign)
        frozen_id = self.service.job_status(first)["report_id"]
        self.clock.epoch = START + 7200 + 120
        self.capture(1, [row(2, START + 3660)])
        later = self.request_and_run()
        self.assertNotEqual(later["report_id"], frozen_id)
        self.assertEqual(self.service.get(frozen_id)["counts"]["eligible_rows"], 1)
        self.assertEqual(self.service.get(later["report_id"])["counts"]["eligible_rows"], 2)

    def test_queued_request_rejects_changed_evidence_and_new_request_succeeds(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        old = self.service.request(self.campaign)
        self.capture(0, [row(1, START + 60), row(2, START + 70)], reconcile=True)
        self.assertIsNone(self.service.run_next(self.campaign))
        self.assertEqual(self.service.job_status(old)["state"], "failed")
        self.assertIsNone(self.service.job_status(old)["report_id"])
        newer = self.service.request(self.campaign)
        self.assertNotEqual(newer, old)
        self.service.run_next(self.campaign)
        self.assertEqual(
            self.service.get(self.service.job_status(newer)["report_id"])["counts"][
                "eligible_rows"
            ],
            2,
        )

    def test_frozen_expiry_covers_possible_campaign_extension(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        report = self.request_and_run()["report_id"]
        stored = self.store.frozen_report(report)
        from datetime import datetime

        expiry = datetime.fromisoformat(stored["expires_utc"].replace("Z", "+00:00"))
        self.assertGreaterEqual(expiry.timestamp(), START + 120 * 3600 + 7 * 86400)

    def test_late_recapture_new_revision_does_not_rewrite_saved_report(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        frozen = self.request_and_run()["report_id"]
        self.capture(0, [row(1, START + 60), row(2, START + 70)], reconcile=True)
        later = self.request_and_run()["report_id"]
        self.assertNotEqual(frozen, later)
        self.assertEqual(self.service.get(frozen)["counts"]["eligible_rows"], 1)
        self.assertEqual(self.service.get(later)["counts"]["eligible_rows"], 2)
        self.assertNotIn("router", json.dumps(self.service.get(later)))

    def test_export_csv_neutralizes_formulas_and_matches_json_rows(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        report_id = self.request_and_run()["report_id"]
        document = self.service.export_json(report_id)
        csv = self.service.export_csv(report_id)
        self.assertEqual(len(document["rows"]), 1)
        self.assertEqual(document["rows"][0]["query_count"], 1)
        self.assertIn("play.games.example", csv)
        self.assertNotIn("client", json.dumps(document))

    def test_rejects_unsettled_day_and_arbitrary_bounds(self):
        with self.assertRaises(CampaignReportError):
            self.service.request(self.campaign, day="not-a-day")
        with self.assertRaises(CampaignReportError):
            self.service.request(self.campaign, start_epoch=START - 5)

    def test_rules_revision_changes_new_report_not_old(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        first_id = self.request_and_run()["report_id"]
        self.service.pin_rules(
            self.campaign, namespace_file([], revision="empty-r2"), ack_empty=True
        )
        second_id = self.request_and_run()["report_id"]
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(self.service.get(first_id)["counts"]["eligible_rows"], 1)
        self.assertEqual(self.service.get(second_id)["counts"]["eligible_rows"], 0)
        self.clock.advance(1)
        self.service.pin_rules(self.campaign, namespace_file([VALID_RULE]))
        restored = self.request_and_run()["report_id"]
        self.assertEqual(self.service.get(restored)["counts"]["eligible_rows"], 1)
        self.clock.advance(1)
        self.service.pin_rules(
            self.campaign, namespace_file([], revision="empty-r2"), ack_empty=True
        )
        self.assertEqual(
            self.service.get(self.request_and_run()["report_id"])["counts"]["eligible_rows"], 0
        )

    def test_complete_local_day_clips_partial_edges_across_dst(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        first = datetime.fromtimestamp(START, ZoneInfo("America/New_York")).date()
        first_end = next(
            end
            for start, end in covered_local_days(START, START + 120 * 3600, "America/New_York")
            if datetime.fromtimestamp(start, ZoneInfo("America/New_York")).date() == first
        )
        self.clock.epoch = first_end + 120
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = first_end + 120
        report_id = self.request_and_run(day=first.isoformat())["report_id"]
        self.assertEqual(self.service.get(report_id)["window"]["end_epoch"], first_end)
        self.assertEqual(self.service.get(report_id)["window"]["start_epoch"], START)

    def test_fall_back_day_report_is_25_elapsed_hours(self):
        from datetime import UTC, datetime

        with tempfile.TemporaryDirectory() as directory:
            store = open_store(Path(directory) / "dst.sqlite3")
            self.addCleanup(store.close)
            start = int(datetime(2026, 10, 31, 4, tzinfo=UTC).timestamp())
            clock = Clock(start)
            rules = Path(directory) / "rules.json"
            rules.write_bytes(namespace_file([VALID_RULE]))
            lifecycle = CampaignService(
                store, now=clock, namespace_path=rules, timezone="America/New_York"
            )
            campaign = lifecycle.start(days=3)["campaign_id"]
            store.register_source_generation(generation_id="dst-gen", identity="resolver")
            day_start, day_end = covered_local_days(start, start + 72 * 3600, "America/New_York")[1]
            self.assertEqual(day_end - day_start, 25 * 3600)
            clock.epoch = day_end + 120
            chunk = store.chunks(campaign)[24]
            store.bind_chunk_generation(
                campaign, chunk_id=chunk["chunk_id"], generation_id="dst-gen"
            )
            token = store.claim_chunks(
                campaign,
                chunk_ids=[chunk["chunk_id"]],
                worker="test",
                lease_seconds=300,
                limit=1,
                now_utc=datetime.fromtimestamp(clock.epoch, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            )
            store.ack_capture(
                campaign,
                chunk_id=chunk["chunk_id"],
                token=token[chunk["chunk_id"]],
                outcome="captured",
                now_utc=datetime.fromtimestamp(clock.epoch, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            )
            store.mark_import_pending(
                campaign,
                chunk_id=chunk["chunk_id"],
                now_utc=datetime.fromtimestamp(clock.epoch, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            )
            store.ack_import(
                campaign,
                chunk_id=chunk["chunk_id"],
                outcome="successful_empty",
                now_utc=datetime.fromtimestamp(clock.epoch, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            )
            reports = CampaignReportService(store, now=clock)
            job = reports.request(campaign, day="2026-11-01")
            reports.run_next(campaign)
            window = reports.get(reports.job_status(job)["report_id"])["window"]
            self.assertEqual(window["end_epoch"] - window["start_epoch"], 25 * 3600)

    def test_failed_job_reports_no_source_state_and_repeated_request_is_stable(self):
        self.clock.epoch = START + 3600 + 120
        job = self.service.request(self.campaign)
        self.assertIsNone(self.service.run_next(self.campaign))
        self.assertEqual(self.service.job_status(job)["state"], "failed")
        self.assertEqual(job, self.service.request(self.campaign))

    def test_deadline_with_imported_evidence_yields_honest_partial(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 7200 + 120
        job = self.service.request(self.campaign)
        moments = iter([0.0, 1.0, 61.0])
        worker = CampaignReportService(self.store, now=self.clock, monotonic=lambda: next(moments))
        worker.run_next(self.campaign, max_seconds=60)
        status = worker.job_status(job)
        self.assertEqual(status["state"], "ready")
        self.assertGreater(worker.get(status["report_id"])["coverage"]["unresolved_chunks"], 0)

    def test_stale_job_token_cannot_publish_or_replace_frozen_output(self):
        self.capture(0, [row(1, START + 60)])
        job = self.service.request(self.campaign)
        old, claimed = self.store.claim_job(
            job, worker="old", lease_seconds=1, now_utc=self.service.now_utc()
        )
        self.assertTrue(claimed)
        self.clock.advance(2)
        self.service.run_next(self.campaign)
        status = self.service.job_status(job)
        self.assertEqual(status["state"], "ready")
        with self.assertRaises(StorageError):
            self.store.finish_campaign_report(
                job_id=job,
                token=old,
                report_id="forged",
                campaign_id=self.campaign,
                requested_start=START,
                requested_end=START + 3600,
                actual_start=START,
                actual_end=START + 3600,
                dedup_key="forged",
                rules_sha256="forged",
                coverage_sha256="forged",
                capture_revisions=[],
                payload={},
                expires_utc=self.service.now_utc(),
                now_utc=self.service.now_utc(),
            )
        self.assertEqual(self.service.job_status(job)["report_id"], status["report_id"])

    def test_saved_grounded_gameplay_and_known_rule_union_count_once(self):
        self.capture(
            0,
            [
                row(1, START + 60),
                row(2, START + 70, "lobby.other.example"),
                row(3, START + 80, "lobby.other.example"),
            ],
        )
        for identifier, domain in (
            ("a-known", "play.games.example"),
            ("b-model", "lobby.other.example"),
        ):
            self.store._conn.execute(
                """INSERT INTO analyses (analysis_id, state, period_digest, selection_digest,
                   analyzer_version, created_utc, updated_utc)
                   VALUES (?, 'completed', ?, ?, 2, '2027-01-01T00:00:00Z', '2027-01-01T00:00:00Z')""",
                (identifier, identifier, identifier),
            )
            self.store._conn.execute(
                """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope,
                   state, result_json) VALUES (?, ?, ?, 'service_and_provider', 'done', ?)""",
                (
                    identifier,
                    identifier,
                    domain,
                    json.dumps(
                        {
                            "source": "model",
                            "verification_state": "ai_grounded",
                            "role": "gameplay_matchmaking",
                            "service": "Example game",
                            "evidence_ids": ["e1"],
                            "source_hashes": {"e1": "f" * 64},
                            "grounding_contract_version": 2,
                        }
                    ),
                ),
            )
        report_id = self.request_and_run()["report_id"]
        payload = self.service.get(report_id)
        self.assertEqual(payload["counts"]["eligible_rows"], 3)
        self.assertEqual(payload["counts"]["known_model_overlap_domains"], 1)
        self.assertEqual(payload["counts"]["model_domains"], 2)
        self.assertEqual(payload["entries"][0]["statuses"]["FORWARDED"], 2)

    def test_csv_formula_label_is_neutralized_without_changing_json(self):
        self.capture(0, [row(1, START + 60)])
        self.service.pin_rules(
            self.campaign,
            namespace_file([{**VALID_RULE, "group_label": "=SUM(1+1)"}], revision="formula"),
        )
        report_id = self.request_and_run()["report_id"]
        self.assertIn("'=SUM(1+1)", self.service.export_csv(report_id))
        self.assertEqual(self.service.export_json(report_id)["rows"][0]["group_label"], "=SUM(1+1)")

    def test_typed_cli_request_worker_and_status_never_print_raw_rows(self):
        self.capture(0, [row(1, START + 60)])
        cli = load_tool("campaign_cli")

        def execute(*args):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = cli.main(
                    [
                        "--db",
                        str(self.store._conn.execute("PRAGMA database_list").fetchone()["file"]),
                        "--now",
                        str(self.clock.epoch),
                        *args,
                    ]
                )
            return result, json.loads(buffer.getvalue())

        result, job = execute("report-request", "--campaign", self.campaign)
        self.assertEqual(result, 0)
        self.assertNotIn("play.games.example", json.dumps(job))
        result, done = execute("report-run")
        self.assertEqual(result, 0)
        self.assertTrue(done["report_id"])
        status = execute("report-status", "--job", job["job_id"])[1]
        self.assertEqual(status["state"], "ready")

    def test_one_live_report_job_is_claimable_across_connections(self):
        self.capture(0, [row(1, START + 60)])
        first = self.service.request(self.campaign)
        self.clock.epoch = START + 7200 + 120
        second = self.service.request(self.campaign)
        from household_report.storage import open_store

        db = self.store._conn.execute("PRAGMA database_list").fetchone()["file"]
        with open_store(db) as other:
            token, claimed = self.store.claim_job(
                first, worker="one", lease_seconds=660, now_utc=self.service.now_utc()
            )
            self.assertTrue(claimed)
            _, claimed = other.claim_job(
                second, worker="two", lease_seconds=660, now_utc=self.service.now_utc()
            )
            self.assertFalse(claimed)
            self.store.finish_job(
                first, token=token, state="failed", now_utc=self.service.now_utc()
            )
            _, claimed = other.claim_job(
                second, worker="two", lease_seconds=660, now_utc=self.service.now_utc()
            )
            self.assertTrue(claimed)

    def test_exhausted_report_lease_is_failed_and_does_not_starve_next_job(self):
        self.capture(0, [row(1, START + 60)])
        old = self.service.request(self.campaign)
        for _ in range(3):
            _, claimed = self.store.claim_job(
                old, worker="crashed", lease_seconds=1, now_utc=self.service.now_utc()
            )
            self.assertTrue(claimed)
            self.clock.advance(2)
        self.clock.epoch = START + 7200 + 120
        later = self.service.request(self.campaign)
        self.service.run_next(self.campaign)
        self.assertEqual(self.service.job_status(old)["state"], "failed")
        self.assertEqual(self.service.job_status(later)["state"], "ready")

    def test_explicit_private_exports_are_immutable_and_matching(self):
        self.capture(0, [row(1, START + 60)])
        report_id = self.request_and_run()["report_id"]
        exporter = load_tool("export_campaign_report")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            db = Path(self.store._conn.execute("PRAGMA database_list").fetchone()["file"])
            json_path, csv_path = path / "report.json", path / "report.csv"
            for format_, destination in (("json", json_path), ("csv", csv_path)):
                self.assertEqual(
                    exporter.main(
                        [
                            "--db",
                            str(db),
                            "--report",
                            report_id,
                            "--format",
                            format_,
                            "--output",
                            str(destination),
                        ]
                    ),
                    0,
                )
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(SystemExit):
                    exporter.main(
                        [
                            "--db",
                            str(db),
                            "--report",
                            report_id,
                            "--format",
                            format_,
                            "--output",
                            str(destination),
                        ]
                    )
            document = json.loads(json_path.read_bytes())
            self.assertIn(document["rows"][0]["domain"], csv_path.read_text(encoding="utf-8-sig"))

    def test_trailing_window_rejects_unsupported_hours(self):
        for hours in (1, 12, 36, 72):
            with self.subTest(hours=hours):
                with self.assertRaises(CampaignReportError):
                    self.service.request(self.campaign, hours=hours)

    def test_24h_window_clips_to_settled_campaign_data(self):
        for index in range(3):
            self.capture(index, [row(index + 1, START + index * 3600 + 60)])
        self.clock.epoch = START + 3 * 3600 + 120
        report_id = self.request_and_run(hours=24)["report_id"]
        payload = self.service.get(report_id)
        self.assertEqual(payload["window"]["start_epoch"], START)
        self.assertEqual(payload["window"]["end_epoch"], START + 3 * 3600)
        self.assertEqual(payload["window"]["requested_start"], START)
        self.assertEqual(payload["window"]["requested_end"], START + 3 * 3600)
        self.assertEqual(payload["window"]["actual_end"], START + 3 * 3600)

    def test_requested_and_actual_bounds_differ_before_settling(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 150
        report_id = self.request_and_run()["report_id"]
        payload = self.service.get(report_id)
        self.assertEqual(payload["window"]["requested_end"], START + 3630)
        self.assertEqual(payload["window"]["actual_end"], START + 3600)
        self.assertEqual(payload["window"]["end_epoch"], START + 3600)

    def test_purpose_is_independent_of_game_identity(self):
        self.capture(
            0,
            [
                row(1, START + 60),
                row(2, START + 70, "lobby.other.example"),
            ],
        )
        self.store._conn.execute(
            """INSERT INTO analyses (analysis_id, state, period_digest, selection_digest,
               analyzer_version, created_utc, updated_utc)
               VALUES ('b-model', 'completed', 'd', 'd', 2, '2027-01-01T00:00:00Z',
               '2027-01-01T00:00:00Z')"""
        )
        self.store._conn.execute(
            """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state,
               result_json) VALUES ('b-model', 'b-model', 'lobby.other.example',
               'service_and_provider', 'done', ?)""",
            (
                json.dumps(
                    {
                        "source": "model",
                        "verification_state": "ai_grounded",
                        "role": "gameplay_matchmaking",
                        "service": "Other game",
                        "evidence_ids": ["e1"],
                        "source_hashes": {"e1": "f" * 64},
                        "grounding_contract_version": 2,
                    }
                ),
            ),
        )
        report_id = self.request_and_run()["report_id"]
        entries = {entry["domain"]: entry for entry in self.service.get(report_id)["entries"]}
        # A known-list match without a saved model role has an independent, unknown purpose.
        self.assertEqual(entries["play.games.example"]["purpose"], "unknown")
        self.assertTrue(entries["play.games.example"]["known_list_match"])
        self.assertFalse(entries["play.games.example"]["model_proposal"])
        # A model proposal carries a purpose mapped from its saved role.
        self.assertEqual(entries["lobby.other.example"]["purpose"], "gameplay/matchmaking-related")
        self.assertFalse(entries["lobby.other.example"]["known_list_match"])
        # Page and export carry the same purpose label.
        exported = self.service.export_json(report_id)
        exported_entries = {row["domain"]: row for row in exported["rows"]}
        self.assertEqual(
            exported_entries["lobby.other.example"]["purpose"], "gameplay/matchmaking-related"
        )

    def test_unknown_source_generation_is_rejected(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        inputs = self.store.campaign_report_inputs(self.campaign)
        inputs["registered_generations"] = ["someone-else"]
        with self.assertRaises(CampaignReportError):
            from household_report.campaign_reporting import _selection

            _selection(inputs, start=START, end=START + 3600, now=int(self.clock.epoch))

    def test_updated_report_links_immutable_predecessor_and_revision(self):
        self.capture(0, [row(1, START + 60)])
        self.clock.epoch = START + 3600 + 120
        first = self.request_and_run()["report_id"]
        self.assertEqual(self.service.get(first)["revision"], 1)
        self.assertIsNone(self.service.get(first)["predecessor_report_id"])
        # Same inputs reuse the same frozen report and revision.
        self.clock.epoch = START + 7200 + 120
        self.capture(1, [row(2, START + 3660)])
        later = self.request_and_run()["report_id"]
        self.assertNotEqual(later, first)
        self.assertEqual(self.service.get(later)["revision"], 2)
        self.assertEqual(self.service.get(later)["predecessor_report_id"], first)
        self.assertEqual(self.service.get(first)["counts"]["eligible_rows"], 1)
        self.assertEqual(self.service.get(later)["counts"]["eligible_rows"], 2)

    def test_review_association_adds_exact_rule_and_changes_report(self):
        self.capture(0, [row(1, START + 60, "lobby.example.net")])
        self.clock.epoch = START + 3600 + 120
        before = self.service.get(self.request_and_run()["report_id"])
        self.assertEqual(before["counts"]["eligible_rows"], 0)
        rule = self.service.review_association(
            self.campaign,
            hostname="lobby.example.net",
            group_id="game-two",
            group_label="Game Two",
            group_kind="game",
            review_note="Owner-verified storefront and lobby endpoint.",
        )
        self.assertEqual(rule["match"], "exact")
        after = self.service.get(self.request_and_run()["report_id"])
        self.assertEqual(after["counts"]["eligible_rows"], 1)
        entry = after["entries"][0]
        self.assertTrue(entry["known_list_match"])
        self.assertFalse(entry["model_proposal"])
        self.assertEqual(entry["group"]["group_label"], "Game Two")
        # The reviewed rule enters the audited provenance stream.
        events = self.store.owner_events(self.campaign)
        reviews = [event for event in events if event["action"] == "gaming_association_review"]
        self.assertEqual(len(reviews), 1)
        self.assertIn("lobby.example.net", reviews[0]["detail"])

    def test_review_association_rejects_generic_and_broadening_proposals(self):
        from household_report.gaming import ReviewError

        base = {
            "campaign_id": self.campaign,
            "hostname": "lobby.example.net",
            "group_id": "game-two",
            "group_label": "Game Two",
            "group_kind": "game",
            "review_note": "Reviewed.",
        }
        for override in ({"group_label": "game"}, {"review_note": "   "}):
            with self.subTest(override=override):
                with self.assertRaises(ReviewError):
                    self.service.review_association(**{**base, **override})


if __name__ == "__main__":
    unittest.main()
