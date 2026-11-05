"""Storage contracts: preserved rows, immutable versions and one ledger."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from household_report.contracts import AttemptBudget, Period
from household_report.storage import BudgetExceeded, StorageError, open_store


def snapshot(rows, *, start=100, end=3700):
    return {
        "schema_version": 1,
        "start_epoch": start,
        "end_epoch": end,
        "captured_utc": "2026-10-23T06:00:00Z",
        "retained_rows": 2,
        "oldest_epoch": 90,
        "newest_epoch": 200,
        "window_count": len(rows),
        "observations": rows,
    }


def row(identifier, timestamp, domain="a.test", client="192.168.1.1"):
    return {
        "id": identifier,
        "timestamp": timestamp,
        "type": 1,
        "status": 2,
        "domain": domain,
        "client": client,
        "forward": None,
        "additional_info": None,
        "list_id": None,
        "reply_type": 4,
        "ede": None,
        "reply_time": 0.01,
        "dnssec": 0,
    }


BUDGET = AttemptBudget(
    per_analysis_requests=3,
    per_day_requests=5,
    per_analysis_tokens=1000,
    per_day_tokens=2000,
    per_analysis_exa=4,
    per_day_exa=2,
)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "app.sqlite3"
        self.store = open_store(self.path)
        self.addCleanup(self.store.close)

    def import_two_rows(self):
        return self.store.import_snapshot(
            snapshot([row(1, 100), row(2, 200)]), datasource="ftl-live"
        )

    def create_analysis(self, analysis_id="analysis-1", items=("a.test",)):
        return self.store.create_analysis(
            analysis_id=analysis_id,
            period_digest="digest",
            selection_digest="selection",
            analyzer_version=1,
            provider=None,
            model_id=None,
            config_fingerprint=None,
            policy_revision=1,
            items=[{"item_id": item, "domain": item} for item in items],
        )

    # -- snapshots ---------------------------------------------------------
    def test_import_preserves_every_row_and_field(self):
        ref = self.import_two_rows()
        self.assertEqual(ref.window_count, 2)
        rows = self.store.rows(ref.snapshot_id)
        self.assertEqual([item["id"] for item in rows], [1, 2])
        self.assertEqual(rows[0]["reply_time"], 0.01)
        self.assertEqual(rows[0]["dnssec"], 0)

    def test_import_rejects_mismatched_counts_duplicates_and_out_of_bounds(self):
        bad_count = snapshot([row(1, 100)])
        bad_count["window_count"] = 2
        with self.assertRaises(StorageError):
            self.store.import_snapshot(bad_count, datasource="ftl-live")
        with self.assertRaises(StorageError):
            self.store.import_snapshot(snapshot([row(1, 100), row(1, 200)]), datasource="ftl-live")
        with self.assertRaises(StorageError):
            self.store.import_snapshot(snapshot([row(1, 5)]), datasource="ftl-live")

    def test_reimport_is_idempotent(self):
        first = self.import_two_rows()
        second = self.import_two_rows()
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        count = self.store._conn.execute("SELECT count(*) FROM dns_rows").fetchone()[0]
        self.assertEqual(count, 2)

    def test_period_digest_is_stable_and_versioned(self):
        ref = self.import_two_rows()
        digest = self.store.period_digest(ref.snapshot_id, Period(100, 3700))
        self.assertEqual(digest, self.store.period_digest(ref.snapshot_id, Period(100, 3700)))
        self.assertNotEqual(
            digest,
            self.store.period_digest(ref.snapshot_id, Period(100, 3700), interpretation_version=2),
        )
        self.assertNotEqual(digest, self.store.period_digest(ref.snapshot_id, Period(100, 200)))
        with self.assertRaises(StorageError):
            self.store.period_digest(ref.snapshot_id, Period(3700, 3800))

    def test_reports_are_immutable_and_reused_by_digest(self):
        ref = self.import_two_rows()
        first = self.store.save_report(
            snapshot_id=ref.snapshot_id,
            period_digest="d1",
            interpretation_version=1,
            payload={"a": 1},
        )
        second = self.store.save_report(
            snapshot_id=ref.snapshot_id,
            period_digest="d1",
            interpretation_version=1,
            payload={"a": 2},
        )
        self.assertEqual(first, second)
        self.assertEqual(self.store.report_payload(first), {"a": 1})

    def test_classification_rules_append_immutable_revisions(self):
        base = {
            "domain": "a.test",
            "match": "exact",
            "field_scope": "service_and_provider",
            "service": "First",
            "confidence": "high",
            "method": "manual",
            "verification_state": "reviewed",
            "checked_utc": "2026-10-23T06:00:00Z",
            "policy_revision": 1,
            "evidence": [{"url": "https://docs.example", "claim": "c"}],
        }
        self.store.add_classification_rule(base)
        self.store.add_classification_rule(
            {**base, "service": "Second", "checked_utc": "2026-10-24T06:00:00Z"}
        )
        rules = self.store.classification_rules()
        self.assertEqual(len(rules), 2)
        self.assertEqual([entry["service"] for entry in rules], ["Second", "First"])

    # -- jobs and budget ---------------------------------------------------
    def test_analysis_identity_is_idempotent_and_items_are_unique(self):
        first, created = self.create_analysis()
        second, created_again = self.create_analysis()
        self.assertEqual(first, second)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(len(self.store.items(first)), 1)

    def test_claim_is_atomic_across_two_connections(self):
        analysis, _ = self.create_analysis(items=("a.test", "b.test"))
        other = open_store(self.path)
        self.addCleanup(other.close)
        claimed = self.store.claim_items(analysis, item_ids=["a.test", "b.test"], lease_seconds=60)
        self.assertEqual(sorted(claimed), ["a.test", "b.test"])
        self.assertEqual(
            other.claim_items(analysis, item_ids=["a.test", "b.test"], lease_seconds=60), []
        )

    def test_reservations_refuse_to_overspend_and_count_retries(self):
        analysis, _ = self.create_analysis()
        for index in range(3):
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="provider_request",
                budget=BUDGET,
                reserved_tokens=100,
                now_utc=f"2026-10-23T0{index}:00:00Z",
            )
        with self.assertRaises(BudgetExceeded) as caught:
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="provider_probe",
                budget=BUDGET,
                reserved_tokens=100,
                now_utc="2026-10-23T04:00:00Z",
            )
        self.assertEqual(caught.exception.scope, "analysis")

    def test_midnight_rolls_the_day_counter_but_not_analysis_progress(self):
        analysis, _ = self.create_analysis()
        for day in ("2026-10-23", "2026-10-24"):
            for index in range(2):
                self.store.reserve_attempt(
                    analysis_id=analysis,
                    kind="exa_search",
                    budget=BUDGET,
                    dispatch_day=day,
                    now_utc=f"{day}T0{index}:00:00Z",
                )
        # Analysis Exa cap is 2 and is already spent, despite the new UTC day.
        with self.assertRaises(BudgetExceeded) as caught:
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="exa_fetch",
                budget=BUDGET,
                dispatch_day="2026-10-25",
                now_utc="2026-10-25T01:00:00Z",
            )
        self.assertEqual(caught.exception.scope, "analysis")

    def test_unconfirmed_attempt_stays_fully_charged(self):
        analysis, _ = self.create_analysis()
        reservation = self.store.reserve_attempt(
            analysis_id=analysis,
            kind="provider_request",
            budget=BUDGET,
            reserved_tokens=400,
            now_utc="2026-10-23T01:00:00Z",
        )
        self.store.complete_attempt(reservation.attempt_id, outcome="unconfirmed")
        usage = self.store.budget_usage(analysis, "2026-10-23")
        self.assertEqual(usage["analysis_tokens"], 400)
        self.assertEqual(usage["analysis_requests"], 1)

    def test_operation_limits_are_separate_and_zero_refuses_before_dispatch(self):
        analysis, _ = self.create_analysis()
        bounded = AttemptBudget(
            per_analysis_requests=3,
            per_day_requests=5,
            per_analysis_tokens=1000,
            per_day_tokens=2000,
            per_analysis_exa=4,
            per_day_exa=4,
            per_analysis_search=1,
            per_day_search=1,
            per_analysis_fetch=0,
            per_day_fetch=0,
            per_analysis_discover=0,
            per_day_discover=0,
            per_analysis_catalog=0,
            per_day_catalog=0,
            per_analysis_probe=0,
            per_day_probe=0,
            per_analysis_completion=0,
            per_day_completion=0,
        )
        self.store.reserve_attempt(
            analysis_id=analysis, kind="exa_search", budget=bounded, dispatch_day="2026-10-23"
        )
        for kind in (
            "exa_search",
            "exa_fetch",
            "exa_discover",
            "provider_catalog",
            "provider_probe",
            "provider_request",
        ):
            with self.assertRaises(BudgetExceeded):
                self.store.reserve_attempt(
                    analysis_id=analysis, kind=kind, budget=bounded, dispatch_day="2026-10-23"
                )
        self.assertEqual(self.store.count_attempts(analysis), 1)
        usage = self.store.budget_usage(analysis, "2026-10-23")
        self.assertEqual(usage["analysis_search"], 1)
        self.assertEqual(usage["analysis_fetch"], 0)

    def test_exa_attempts_do_not_spend_the_provider_request_budget(self):
        """The two declared allowances are spent only by their own category.

        Exa searches and provider requests have separate declared limits. When
        Exa attempts were also charged against the provider request allowance,
        a batch of four candidates (four searches plus one completion) could
        never fit inside a twelve-request analysis.
        """
        analysis, _ = self.create_analysis()
        separated = AttemptBudget(
            per_analysis_requests=3,
            per_day_requests=5,
            per_analysis_tokens=1000,
            per_day_tokens=2000,
            per_analysis_exa=4,
            per_day_exa=4,
            per_analysis_search=4,
            per_day_search=4,
            per_analysis_fetch=4,
            per_day_fetch=4,
            per_analysis_discover=4,
            per_day_discover=4,
            per_analysis_catalog=3,
            per_day_catalog=3,
            per_analysis_probe=3,
            per_day_probe=3,
            per_analysis_completion=3,
            per_day_completion=3,
        )
        # Four Exa attempts are allowed and must not consume the request budget.
        for _ in range(4):
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="exa_search",
                budget=separated,
                dispatch_day="2026-10-23",
            )
        usage = self.store.budget_usage(analysis, "2026-10-23")
        self.assertEqual(usage["analysis_search"], 4)
        # Three provider requests still fit; the fourth does not.
        for _ in range(3):
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="provider_request",
                budget=separated,
                dispatch_day="2026-10-23",
            )
        with self.assertRaises(BudgetExceeded):
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="provider_request",
                budget=separated,
                dispatch_day="2026-10-23",
            )

    def test_measured_usage_replaces_the_reservation_when_lower(self):
        analysis, _ = self.create_analysis()
        reservation = self.store.reserve_attempt(
            analysis_id=analysis,
            kind="provider_request",
            budget=BUDGET,
            reserved_tokens=400,
            now_utc="2026-10-23T01:00:00Z",
        )
        self.store.complete_attempt(
            reservation.attempt_id, outcome="ok", prompt_tokens=100, completion_tokens=50
        )
        self.assertEqual(self.store.budget_usage(analysis, "2026-10-23")["analysis_tokens"], 150)

    def test_usage_summary_separates_exa_groq_other_provider_and_measurements(self):
        def analysis(analysis_id, provider):
            return self.store.create_analysis(
                analysis_id=analysis_id,
                period_digest=f"d-{analysis_id}",
                selection_digest=f"s-{analysis_id}",
                analyzer_version=2,
                provider=provider,
                model_id="synthetic",
                config_fingerprint=None,
                policy_revision=1,
                items=[{"item_id": "a.test", "domain": "a.test"}],
            )

        groq_id, _ = analysis("groq-run", "groq")
        other_id, _ = analysis("other-run", "openrouter")
        groq_completion = self.store.reserve_attempt(
            analysis_id=groq_id,
            kind="provider_request",
            budget=BUDGET,
            reserved_tokens=100,
            dispatch_day="2026-10-23",
        )
        self.store.complete_attempt(
            groq_completion.attempt_id, outcome="ok", prompt_tokens=12, completion_tokens=3
        )
        exa_search = self.store.reserve_attempt(
            analysis_id=groq_id,
            kind="exa_search",
            budget=BUDGET,
            dispatch_day="2026-10-23",
        )
        self.store.complete_attempt(exa_search.attempt_id, outcome="timeout")
        other_completion = self.store.reserve_attempt(
            analysis_id=other_id,
            kind="provider_request",
            budget=BUDGET,
            reserved_tokens=50,
            dispatch_day="2026-10-23",
        )
        self.store.complete_attempt(
            other_completion.attempt_id, outcome="ok", prompt_tokens=20, completion_tokens=4
        )

        summary = self.store.usage_summary(dispatch_day="2026-10-23")
        self.assertEqual(summary["exa"]["search"]["attempts"], 1)
        self.assertEqual(summary["exa"]["search"]["outcomes"], {"timeout": 1})
        self.assertEqual(summary["providers"]["groq"]["completion"]["attempts"], 1)
        self.assertEqual(summary["providers"]["groq"]["completion"]["measured_prompt_tokens"], 12)
        self.assertEqual(summary["providers"]["groq"]["completion"]["reserved_tokens"], 100)
        self.assertEqual(summary["providers"]["groq"]["completion"]["budget_charged_tokens"], 15)
        self.assertEqual(summary["providers"]["openrouter"]["completion"]["attempts"], 1)
        run = self.store.usage_summary(dispatch_day=None, analysis_id=groq_id)
        self.assertEqual(run["scope"]["analysis_id"], "groq-run")
        self.assertEqual(run["providers"]["groq"]["completion"]["missing_measurements"], 0)

    def test_token_reservation_is_refused_when_the_bound_does_not_fit(self):
        analysis, _ = self.create_analysis()
        with self.assertRaises(BudgetExceeded):
            self.store.reserve_attempt(
                analysis_id=analysis,
                kind="provider_request",
                budget=BUDGET,
                reserved_tokens=1500,
                now_utc="2026-10-23T01:00:00Z",
            )
        self.assertEqual(self.store.count_attempts(analysis), 0)

    def test_interrupted_work_pauses_and_returns_to_pending_not_replay(self):
        analysis, _ = self.create_analysis(items=("a.test",))
        self.store.claim_items(analysis, item_ids=["a.test"], lease_seconds=60)
        self.assertTrue(self.store.pause_interrupted(analysis))
        self.assertEqual(self.store.analysis(analysis)["state"], "paused")
        self.assertEqual(self.store.items(analysis)[0]["state"], "pending")
        self.assertFalse(self.store.pause_interrupted(analysis))

    def test_summary_is_written_once_and_only_on_terminal_rows(self):
        analysis, _ = self.create_analysis()
        self.assertFalse(self.store.save_summary(analysis, "premature"))
        self.store.finish_analysis(analysis, state="completed")
        self.assertTrue(self.store.save_summary(analysis, "first"))
        self.assertFalse(self.store.save_summary(analysis, "second"))
        self.assertEqual(self.store.analysis(analysis)["summary"], "first")

    def test_no_write_lock_is_held_while_a_call_is_in_flight(self):
        analysis, _ = self.create_analysis()
        reservation = self.store.reserve_attempt(
            analysis_id=analysis,
            kind="provider_request",
            budget=BUDGET,
            reserved_tokens=100,
            now_utc="2026-10-23T01:00:00Z",
        )
        # A second connection must be able to write between reserve and complete.
        other = sqlite3.connect(self.path, timeout=0.5, isolation_level=None)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")
        other.execute(
            "UPDATE analyses SET updated_utc = updated_utc WHERE analysis_id = ?", (analysis,)
        )
        other.execute("COMMIT")
        self.store.complete_attempt(reservation.attempt_id, outcome="ok")


if __name__ == "__main__":
    unittest.main()
