"""Campaign storage: v2→v3 migration, durable chunks/jobs/reports and one-active lifecycle."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from household_report import storage as storage_module
from household_report.campaign import (
    FINALIZATION_ALLOWANCE_SECONDS,
    MAX_CHUNK_ATTEMPTS,
    WORKER_LEASE_SECONDS,
    CampaignError,
    CampaignService,
)
from household_report.storage import SCHEMA_VERSION, StorageError, open_store

START = 1_800_000_000  # hour-aligned so 3 days == exactly 72 one-hour windows
HOUR = 3600

VALID_RULE = {
    "rule_id": "rule-1",
    "namespace": "games.example",
    "match": "suffix",
    "group_id": "ptf",
    "group_label": "Platform",
    "group_kind": "platform",
    "review_note": "Reviewed locally.",
}


class Clock:
    """Deterministic epoch clock for offline boundary tests."""

    def __init__(self, epoch: int):
        self.epoch = epoch

    def __call__(self) -> int:
        return self.epoch

    def advance(self, seconds: int) -> None:
        self.epoch += seconds


def namespace_file(rules=(), revision="r1"):
    return json.dumps({"schema_version": 1, "revision": revision, "rules": list(rules)}).encode()


class CampaignStoreTest(unittest.TestCase):
    def make_service(self, store=None, *, namespace=None):
        store = store or self.store
        path = namespace if namespace is not None else self.namespace
        return CampaignService(
            store, now=self.clock, timezone="America/New_York", namespace_path=path
        )

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "app.sqlite3"
        self.store = open_store(self.path)
        self.addCleanup(self.store.close)
        self.clock = Clock(START)
        self.namespace = Path(self.directory.name) / "gaming-namespaces.json"
        self.namespace.write_bytes(namespace_file())
        self.service = self.make_service()

    def start(self, **keywords):
        keywords.setdefault("days", 3)
        keywords.setdefault("retention_days", 7)
        keywords.setdefault("ack_empty", True)
        keywords.setdefault("timezone", "America/New_York")
        return self.service.start(**keywords)

    def import_every_chunk(self):
        """Claim, capture and import every planned chunk."""
        while claims := self.service.claim_capture_work(worker="test"):
            for claim in claims:
                self.assertTrue(
                    self.service.ack_capture(
                        claim["chunk_id"],
                        token=claim["lease_token"],
                        outcome="captured",
                        digest="d" * 64,
                        path=f"/private/{claim['chunk_id']}.json",
                    )
                )
                self.assertTrue(self.service.mark_import_pending(claim["chunk_id"]))
                self.assertTrue(self.service.ack_import(claim["chunk_id"], outcome="imported"))


class MigrationTests(CampaignStoreTest):
    def test_fresh_database_opens_at_version_three(self):
        version = self.store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)

    def test_v2_fixture_migrates_and_preserves_legacy_data(self):
        legacy = Path(self.directory.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.executescript(storage_module._SCHEMA)
        connection.execute(
            """INSERT INTO snapshots (snapshot_id, datasource, schema_version, import_version,
                   start_epoch, end_epoch, captured_utc, retained_rows, oldest_epoch,
                   newest_epoch, window_count, data_sha256, created_utc)
               VALUES ('legacy-snap', 'ftl-live', 1, 1, 100, 3700, '2026-10-23T06:00:00Z',
                       2, 90, 200, 1, 'aaaa', '2026-10-23T06:00:00Z')"""
        )
        connection.execute(
            """INSERT INTO dns_rows (snapshot_id, row_id, timestamp, qtype, status, domain,
                   client)
               VALUES ('legacy-snap', 1, 100, 1, 2, 'example.com', '192.168.1.1')"""
        )
        connection.execute(
            """INSERT INTO classifications (domain, match, field_scope, confidence, method,
                   verification_state, checked_utc, policy_revision)
               VALUES ('example.com', 'exact', 'service_and_provider', 'high', 'manual',
                       'reviewed', '2026-10-23T06:00:00Z', 1)"""
        )
        connection.execute(
            """INSERT INTO analyses (analysis_id, state, period_digest, selection_digest,
                   analyzer_version, created_utc, updated_utc)
               VALUES ('legacy-analysis', 'completed', 'pd', 'sd', 2,
                       '2026-10-23T06:00:00Z', '2026-10-23T07:00:00Z')"""
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        connection.close()

        with open_store(legacy) as migrated:
            self.assertEqual(
                migrated._conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
            row = migrated.snapshot("legacy-snap")
            self.assertEqual(row["datasource"], "ftl-live")
            self.assertEqual(len(migrated.rows("legacy-snap")), 1)
            self.assertEqual(len(migrated.classification_rules()), 1)
            self.assertEqual(migrated.analysis("legacy-analysis")["state"], "completed")
            # The v3 campaign surface is available after migration.
            migrated.create_campaign(
                campaign_id="c-after-migration",
                start_epoch=START,
                end_epoch=START + 72 * HOUR,
                timezone="UTC",
                retention_days=7,
                rules_revision=None,
                rules_sha256="x" * 64,
                rules_state="available",
                rules_ack=True,
            )
            self.assertEqual(migrated.campaign("c-after-migration")["state"], "active")
            self.assertEqual(migrated.migrate(), SCHEMA_VERSION)
            self.assertEqual(len(migrated.classification_rules()), 1)

    def test_source_generation_identity_cannot_be_reused(self):
        self.store.register_source_generation(generation_id="gen-1", identity="resolver-a")
        self.store.register_source_generation(generation_id="gen-1", identity="resolver-a")
        self.assertEqual(self.store.source_generation("gen-1")["identity"], "resolver-a")
        with self.assertRaises(StorageError):
            self.store.register_source_generation(generation_id="gen-1", identity="resolver-b")

    def test_generation_is_pinned_before_claim_and_cannot_be_rebound(self):
        self.store.register_source_generation(generation_id="gen-1", identity="resolver-a")
        self.store.register_source_generation(generation_id="gen-2", identity="resolver-b")
        campaign_id = self.start()["campaign_id"]
        first = self.store.chunks(campaign_id)[0]["chunk_id"]
        self.assertTrue(
            self.store.bind_chunk_generation(campaign_id, chunk_id=first, generation_id="gen-1")
        )
        self.assertFalse(
            self.store.bind_chunk_generation(campaign_id, chunk_id=first, generation_id="gen-2")
        )
        self.assertEqual(self.store.chunk(campaign_id, first)["generation_id"], "gen-1")

    def test_newer_database_is_refused(self):
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        connection.commit()
        connection.close()
        with self.assertRaises(StorageError):
            open_store(self.path)


class OneActiveCampaignTests(CampaignStoreTest):
    def test_start_stores_lifecycle_fields_and_no_earlier_history(self):
        status = self.start(days=5, retention_days=14)
        self.assertEqual(status["state"], "active")
        self.assertEqual(status["utc_bounds"][1] - status["utc_bounds"][0], 120 * HOUR)
        self.assertEqual(status["retention_days"], 14)
        self.assertEqual(status["timezone"], "America/New_York")
        self.assertTrue(status["rules_empty_acknowledged"])
        rows = self.store._conn.execute("SELECT count(*) FROM dns_rows").fetchone()[0]
        self.assertEqual(rows, 0)

    def test_rules_are_pinned_including_digest_and_revision(self):
        raw = namespace_file([VALID_RULE], revision="r2")
        self.namespace.write_bytes(raw)
        status = self.service.start(days=3, retention_days=7, timezone="UTC")
        self.assertEqual(status["rules_revision"], "r2")
        self.assertEqual(status["rules_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(status["coverage"]["chunks_planned"], 72)

    def test_rejects_concurrent_start_in_the_policy_layer(self):
        self.start()
        other = self.make_service()
        with self.assertRaises(CampaignError):
            other.start(days=3)

    def test_rejects_concurrent_start_at_the_database_layer(self):
        self.start()
        other = open_store(self.path)
        self.addCleanup(other.close)
        with self.assertRaises(StorageError):
            other.create_campaign(
                campaign_id="second",
                start_epoch=START,
                end_epoch=START + 72 * HOUR,
                timezone="UTC",
                retention_days=7,
                rules_revision=None,
                rules_sha256="x" * 64,
                rules_state="available",
                rules_ack=True,
            )

    def test_missing_invalid_and_unacknowledged_empty_rules_block_start(self):
        missing = self.directory.name + "/absent.json"
        blocked = CampaignService(self.store, now=self.clock, namespace_path=Path(missing))
        with self.assertRaises(CampaignError):
            blocked.start(days=3)
        self.namespace.write_bytes(b'{"schema_version": 1, "revision": "", "rules": "nope"}')
        with self.assertRaises(CampaignError):
            self.service.start(days=3)
        self.namespace.write_bytes(namespace_file())
        with self.assertRaises(CampaignError):
            self.service.start(days=3, ack_empty=False)
        self.assertTrue(self.service.start(days=3, ack_empty=True)["state"] == "active")

    def test_active_and_finalizing_cannot_coexist(self):
        self.start()
        self.clock.advance(HOUR)
        self.service.finish_early()
        with open_store(self.path) as other:
            with self.assertRaises(StorageError):
                other.create_campaign(
                    campaign_id="second",
                    start_epoch=START + HOUR,
                    end_epoch=START + 73 * HOUR,
                    timezone="UTC",
                    retention_days=7,
                    rules_revision="r1",
                    rules_sha256="x" * 64,
                    rules_state="available",
                    rules_ack=True,
                )

    def test_planning_is_idempotent_per_window(self):
        self.start()
        campaign_id = self.store.current_unfinished()["campaign_id"]
        self.assertEqual(len(self.store.chunks(campaign_id)), 72)
        self.assertEqual(self.service.plan(), 0)
        self.assertEqual(len(self.store.chunks(campaign_id)), 72)

    def test_extension_is_capped_and_finishing_blocks_it(self):
        status = self.start(days=3)
        campaign_id = status["campaign_id"]
        extended = self.service.extend(48, campaign_id)
        self.assertEqual(extended["utc_bounds"][1] - extended["utc_bounds"][0], 120 * HOUR)
        with self.assertRaises(CampaignError):
            self.service.extend(1, campaign_id)
        self.clock.advance(1)
        self.service.finish_early(campaign_id)
        with self.assertRaises(CampaignError):
            self.service.extend(1, campaign_id)

    def test_finish_early_clips_the_end_and_opens_the_allowance(self):
        status = self.start(days=5)
        campaign_id = status["campaign_id"]
        self.clock.advance(10 * HOUR)
        finished = self.service.finish_early(campaign_id)
        self.assertEqual(finished["state"], "finalizing")
        self.assertEqual(finished["utc_bounds"][1], START + 10 * HOUR)
        self.assertEqual(
            finished["finalization_deadline_epoch"],
            START + 10 * HOUR + FINALIZATION_ALLOWANCE_SECONDS,
        )

    def test_early_finish_creates_partial_chunk_and_excludes_later_windows(self):
        campaign_id = self.start(days=5)["campaign_id"]
        self.clock.advance(10 * HOUR + 1800)
        finished = self.service.finish_early(campaign_id)
        self.assertEqual(finished["utc_bounds"][1], START + 10 * HOUR + 1800)
        self.assertEqual(finished["coverage"]["chunks_planned"], 11)
        inside = [
            chunk
            for chunk in self.store.chunks(campaign_id)
            if int(chunk["end_epoch"]) <= finished["utc_bounds"][1]
        ]
        self.assertEqual(len(inside), 11)
        self.assertEqual(inside[-1]["end_epoch"] - inside[-1]["start_epoch"], 1800)


class ChunkClaimTests(CampaignStoreTest):
    def test_unsettled_windows_are_not_claimable(self):
        self.start()
        self.assertEqual(self.service.claim_capture_work(), [])

    def test_claims_are_atomic_across_two_connections(self):
        self.start()
        self.clock.advance(72 * HOUR + 120)
        other_service = self.make_service(open_store(self.path))
        self.addCleanup(other_service._store.close)
        first = self.service.claim_capture_work(worker="a", limit=10)
        second = other_service.claim_capture_work(worker="b", limit=10)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(second), 10)
        self.assertFalse(
            {claim["chunk_id"] for claim in first} & {claim["chunk_id"] for claim in second}
        )

    def test_stale_lease_is_reclaimed_but_the_old_token_cannot_ack(self):
        self.start()
        self.clock.advance(72 * HOUR + 120)
        first = self.service.claim_capture_work(worker="a", limit=1)[0]
        self.clock.advance(WORKER_LEASE_SECONDS + 1)
        second = self.service.claim_capture_work(worker="b", limit=1)
        self.assertEqual(len(second), 1)
        stale = first["chunk_id"]
        self.assertFalse(
            self.service.ack_capture(stale, token=first["lease_token"], outcome="captured")
        )
        self.assertTrue(
            self.service.ack_capture(stale, token=second[0]["lease_token"], outcome="captured")
        )
        attempts = self.store._conn.execute(
            "SELECT outcome FROM capture_attempts WHERE chunk_id = ? ORDER BY claimed_utc", (stale,)
        ).fetchall()
        self.assertEqual([row["outcome"] for row in attempts], [None, "captured"])

    def test_backward_clock_pauses_claims_until_previous_time_is_reached(self):
        self.start()
        self.clock.advance(2 * HOUR + 120)
        first = self.service.claim_capture_work(limit=1)
        self.assertEqual(len(first), 1)
        self.clock.advance(-HOUR)
        self.assertEqual(self.service.claim_capture_work(limit=1), [])
        self.clock.advance(HOUR)
        self.assertEqual(len(self.service.claim_capture_work(limit=1)), 1)

    def test_retry_headroom_is_bounded_per_chunk_then_blocked(self):
        self.start()
        self.clock.advance(72 * HOUR + 120)
        first_chunk = None
        for _ in range(MAX_CHUNK_ATTEMPTS):
            claim = self.service.claim_capture_work(worker="a", limit=1)[0]
            first_chunk = first_chunk or claim["chunk_id"]
            self.assertEqual(claim["chunk_id"], first_chunk)
            self.assertTrue(
                self.service.ack_capture(
                    claim["chunk_id"], token=claim["lease_token"], outcome="failed"
                )
            )
        # Retry bound is per chunk: the exhausted window is never offered again
        # while others still have headroom. Its gap stays visible as failed.
        remaining = self.service.claim_capture_work(worker="a", limit=10)
        self.assertNotIn(first_chunk, [claim["chunk_id"] for claim in remaining])
        campaign_id = self.store.current_unfinished()["campaign_id"]
        exhausted = self.store.chunk(campaign_id, first_chunk)
        self.assertEqual(exhausted["state"], "failed")
        self.assertEqual(int(exhausted["attempts"]), MAX_CHUNK_ATTEMPTS)


class FinalizationTests(CampaignStoreTest):
    def test_unreconciled_imports_finish_with_visible_gaps_at_deadline(self):
        status = self.start()
        campaign_id = status["campaign_id"]
        self.clock.advance(72 * HOUR + 120)
        self.import_every_chunk()
        self.assertEqual(self.service.finalize(campaign_id)["state"], "finalizing")
        self.clock.advance(FINALIZATION_ALLOWANCE_SECONDS)
        finished = self.service.finalize(campaign_id)
        self.assertEqual(finished["state"], "complete_with_gaps")
        self.assertTrue(finished["coverage"]["fully_resolved"])
        self.assertEqual(finished["coverage"]["reconciliation_pending"], 72)

    def test_reconciled_chunks_can_complete_before_allowance_expires(self):
        campaign_id = self.start()["campaign_id"]
        self.clock.advance(72 * HOUR + 120)
        self.import_every_chunk()
        for chunk in self.store.chunks(campaign_id):
            self.assertTrue(self.store.mark_reconciled(campaign_id, chunk_id=chunk["chunk_id"]))
        self.assertEqual(self.service.finalize(campaign_id)["state"], "complete")

    def test_complete_with_gaps_preserves_unresolved_intervals(self):
        status = self.start()
        campaign_id = status["campaign_id"]
        self.clock.advance(72 * HOUR + 120)
        skipped = None
        while claims := self.service.claim_capture_work(worker="test"):
            for claim in claims:
                if skipped is None:
                    skipped = claim["chunk_id"]
                    continue
                self.assertTrue(
                    self.service.ack_capture(claim["chunk_id"], token=claim["lease_token"])
                )
                self.assertTrue(self.service.mark_import_pending(claim["chunk_id"]))
                self.assertTrue(self.service.ack_import(claim["chunk_id"], outcome="imported"))
        self.assertIsNotNone(skipped)
        finished = self.service.finalize(campaign_id)
        self.assertEqual(finished["state"], "finalizing")
        self.clock.advance(FINALIZATION_ALLOWANCE_SECONDS)
        finished = self.service.finalize(campaign_id)
        self.assertEqual(finished["state"], "complete_with_gaps")
        self.assertEqual(finished["coverage"]["unresolved_chunks"], 1)
        self.assertEqual(len(finished["coverage"]["unresolved_intervals"]), 1)
        unresolved = self.store.chunk(campaign_id, skipped)
        self.assertEqual(unresolved["state"], "expired")

    def test_restart_after_end_issues_no_new_work_and_new_campaigns_may_start(self):
        status = self.start()
        campaign_id = status["campaign_id"]
        self.clock.advance(200 * HOUR)  # far past the end and its allowance
        self.assertEqual(self.service.claim_capture_work(), [])
        self.assertEqual(self.service.plan(campaign_id), 0)
        finished = self.service.finalize(campaign_id)
        self.assertEqual(finished["state"], "complete_with_gaps")
        self.assertIn("expired", finished["coverage"]["by_state"])
        self.assertEqual(finished["coverage"]["by_state"]["expired"], 72)
        # A completed campaign does not block a later, separate campaign.
        next_campaign = self.service.start(days=3, ack_empty=True)
        self.assertEqual(next_campaign["state"], "active")


class JobAndReportTests(CampaignStoreTest):
    def test_report_jobs_dedup_and_leases(self):
        campaign_id = self.start()["campaign_id"]
        first = self.service.create_report_job(dedup_key="k1", params={"day": "2026-10-24"})
        again = self.service.create_report_job(dedup_key="k1", params={"day": "2026-10-24"})
        self.assertEqual(first, again)
        claimed = self.service.claim_report_job()
        self.assertIsNotNone(claimed)
        self.assertFalse(self.service.finish_report_job(first, token="wrong", state="ready"))
        self.assertTrue(
            self.service.finish_report_job(first, token=claimed["lease_token"], state="ready")
        )
        self.assertIsNone(self.service.claim_report_job())
        self.assertEqual(self.store.job(first)["state"], "ready")
        self.assertEqual(self.store.job(first)["campaign_id"], campaign_id)

    def test_expired_job_lease_reclaims_across_connections(self):
        self.start()
        job_id = self.service.create_report_job(dedup_key="k1")
        first = self.service.claim_report_job(worker="one")
        with open_store(self.path) as other_store:
            other = self.make_service(other_store)
            self.assertIsNone(other.claim_report_job(worker="two"))
            self.clock.advance(WORKER_LEASE_SECONDS + 1)
            reclaimed = other.claim_report_job(worker="two")
            self.assertEqual(reclaimed["job_id"], job_id)
            self.assertFalse(
                self.service.finish_report_job(job_id, token=first["lease_token"], state="ready")
            )
            self.assertTrue(
                other.finish_report_job(job_id, token=reclaimed["lease_token"], state="ready")
            )

    def test_frozen_reports_are_immutable_and_deduplicated(self):
        campaign_id = self.start()["campaign_id"]
        first, created = self.store.save_frozen_report(
            report_id="report-1",
            campaign_id=campaign_id,
            requested_start=START,
            requested_end=START + 72 * HOUR,
            actual_start=START,
            actual_end=START + 72 * HOUR,
            dedup_key="window-1",
            rules_sha256="r" * 64,
            coverage_sha256="c" * 64,
            capture_revisions=["chunk-a", "chunk-b"],
            payload={"destinations": []},
            expires_utc="2026-10-27T00:00:00Z",
        )
        self.assertTrue(created)
        second, created_again = self.store.save_frozen_report(
            report_id="report-2",
            campaign_id=campaign_id,
            requested_start=START,
            requested_end=START + 72 * HOUR,
            actual_start=START,
            actual_end=START + 72 * HOUR,
            dedup_key="window-1",
            rules_sha256="other",
            coverage_sha256=None,
            payload={"destinations": [{"fake": True}]},
            expires_utc="2026-10-27T00:00:00Z",
        )
        self.assertFalse(created_again)
        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(self.store.frozen_report(first)["payload_json"]),
            {"destinations": [], "predecessor_report_id": None, "revision": 1},
        )
        self.assertEqual(self.store.frozen_report(first)["revision"], 1)
        self.assertIsNone(self.store.frozen_report(first)["predecessor_report_id"])


if __name__ == "__main__":
    unittest.main()
