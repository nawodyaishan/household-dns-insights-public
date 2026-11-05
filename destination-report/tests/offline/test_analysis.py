"""Analysis contracts: one dispatch gate, ledger budgets and local summaries."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from household_report.analysis import (
    AnalysisError,
    AnalysisService,
    ModelIneligible,
    UnknownTokenBound,
    analysis_identity,
    budget_from_mapping,
    live_budget_from_mapping,
    reservation_tokens,
    selection_digest,
)
from household_report.contracts import AttemptBudget, ModelCapabilities, ModelReply, Usage
from household_report.storage import BudgetExceeded, open_store

BUDGET = AttemptBudget(
    per_analysis_requests=2,
    per_day_requests=4,
    per_analysis_tokens=1000,
    per_day_tokens=2000,
    per_analysis_exa=2,
    per_day_exa=2,
)


def capabilities(**overrides):
    base = {
        "model_id": "test/model",
        "context_limit": 800,
        "completion_limit": 200,
        "structured_output": "json_schema",
        "free_eligible": True,
    }
    base.update(overrides)
    return ModelCapabilities(**base)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = open_store(Path(self.directory.name) / "app.sqlite3")
        self.addCleanup(self.store.close)
        self.service = AnalysisService(self.store, budget=BUDGET)

    def create(self, items=("a.test",), model="test/model"):
        return self.service.create(
            period_digest="period",
            selected_item_ids=[item["item_id"] for item in ({"item_id": name} for name in items)],
            candidates=[{"item_id": name, "domain": name} for name in items],
            provider="groq",
            model_id=model,
            config_fingerprint="cfg",
            policy_revision=1,
        )

    def test_same_period_selection_and_configuration_return_one_job(self):
        first, created = self.create()
        second, created_again = self.create()
        self.assertEqual(first, second)
        self.assertTrue(created)
        self.assertFalse(created_again)

    def test_identity_ignores_selection_order_but_tracks_configuration(self):
        self.assertEqual(
            selection_digest(["b.test", "a.test"]), selection_digest(["a.test", "b.test"])
        )
        base = {
            "period_digest": "p",
            "selection_digest": "s",
            "analyzer_version": 1,
            "provider": "groq",
            "model_id": "m",
            "config_fingerprint": "c",
            "policy_revision": 1,
        }
        self.assertNotEqual(
            analysis_identity(**base), analysis_identity(**{**base, "model_id": "other"})
        )

    def test_dispatch_reserves_then_records_measured_usage(self):
        analysis, _ = self.create()
        reply = ModelReply(
            model_id="test/model",
            text="{}",
            usage=Usage(prompt_tokens=100, completion_tokens=20),
        )
        result = self.service.dispatch_attempt(
            analysis,
            kind="provider_request",
            tokens=900,
            operation=lambda: reply,
        )
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.charged_tokens, 120)
        usage = self.service.usage(analysis)
        self.assertEqual(usage["analysis_tokens"], 120)
        self.assertEqual(usage["analysis_requests"], 1)

    def test_every_retry_is_a_separately_reserved_attempt(self):
        analysis, _ = self.create()
        for _ in range(2):
            self.service.dispatch_attempt(
                analysis, kind="provider_request", tokens=100, operation=lambda: "ok"
            )
        with self.assertRaises(BudgetExceeded):
            self.service.dispatch_attempt(
                analysis, kind="provider_request", tokens=100, operation=lambda: "never"
            )
        self.assertEqual(self.store.count_attempts(analysis), 2)

    def test_timeout_is_charged_and_cannot_be_retried_for_free(self):
        analysis, _ = self.create()

        def slow():
            raise TimeoutError("upstream")

        with self.assertRaises(TimeoutError):
            self.service.dispatch_attempt(
                analysis, kind="provider_request", tokens=600, operation=slow
            )
        usage = self.service.usage(analysis)
        self.assertEqual(usage["analysis_requests"], 1)
        self.assertEqual(usage["analysis_tokens"], 600)
        with self.assertRaises(BudgetExceeded):
            self.service.dispatch_attempt(
                analysis, kind="provider_request", tokens=600, operation=lambda: "ok"
            )

    def test_run_deadline_refuses_dispatch_before_reserving(self):
        analysis, _ = self.create()
        guarded = AnalysisService(
            self.store,
            budget=BUDGET,
            deadline_monotonic=110.0,
            external_attempt_timeout_seconds=30.0,
        )
        with patch("household_report.analysis.time.monotonic", return_value=81.0):
            with self.assertRaisesRegex(AnalysisError, "Run deadline reached"):
                guarded.dispatch_attempt(
                    analysis,
                    kind="provider_request",
                    tokens=10,
                    operation=lambda: self.fail("must not dispatch"),
                )
        self.assertEqual(self.store.count_attempts(analysis), 0)

    def test_single_attempt_policy_is_bounded(self):
        with self.assertRaisesRegex(AnalysisError, "max_attempts_per_operation"):
            AnalysisService(self.store, budget=BUDGET, max_attempts_per_operation=3)

    def test_operation_runs_without_holding_the_write_lock(self):
        analysis, _ = self.create()

        def operation():
            other = open_store(Path(self.directory.name) / "app.sqlite3")
            try:
                other.finish_analysis(analysis, state="paused")
            finally:
                other.close()
            return "done"

        self.service.dispatch_attempt(
            analysis, kind="provider_request", tokens=10, operation=operation
        )
        self.assertEqual(self.service.status(analysis)["state"], "paused")

    def test_batch_size_is_bounded(self):
        analysis, _ = self.create(items=("a.test", "b.test", "c.test", "d.test", "e.test"))
        self.assertEqual(len(self.service.claim_batch(analysis, limit=4)), 4)
        with self.assertRaises(AnalysisError):
            self.service.claim_batch(analysis, limit=5)

    def test_restart_pauses_instead_of_replaying(self):
        analysis, _ = self.create(items=("a.test",))
        self.service.claim_batch(analysis, limit=1)
        self.assertTrue(self.service.pause_interrupted(analysis))
        status = self.service.status(analysis)
        self.assertEqual(status["state"], "paused")
        self.assertEqual(status["items"][0]["state"], "pending")

    def test_summary_is_deterministic_and_written_once(self):
        analysis, _ = self.create(items=("a.test", "b.test"))
        self.service.checkpoint(
            analysis,
            "a.test",
            outcome="done",
            result={"service": "Example", "provider": "Example Inc"},
        )
        self.service.checkpoint(
            analysis, "b.test", outcome="unknown", result={"unresolved_reason": "no source"}
        )
        summary = self.service.finish_with_summary(analysis, state="completed")
        self.assertIn("1 service-specific", summary)
        self.assertIn("1 unknown", summary)
        self.assertIn("not connections", summary)
        self.assertIsNone(self.service.finish_with_summary(analysis, state="completed"))
        self.assertEqual(self.store.analysis(analysis)["summary"], summary)

    def test_no_summary_for_a_paused_job(self):
        analysis, _ = self.create()
        self.assertIsNone(self.service.finish_with_summary(analysis, state="paused"))

    def test_token_bound_is_conservative_and_unknown_bounds_are_refused(self):
        self.assertEqual(reservation_tokens(capabilities(), completion_cap=200), 1000)
        with self.assertRaises(ModelIneligible):
            reservation_tokens(capabilities(), completion_cap=201)
        with self.assertRaises(ModelIneligible):
            reservation_tokens(capabilities(structured_output="none"), completion_cap=10)
        with self.assertRaises(UnknownTokenBound):
            reservation_tokens(capabilities(), completion_cap=0)

    def test_budget_mapping_requires_every_field(self):
        with self.assertRaises(ValueError):
            budget_from_mapping({"per_analysis_requests": 1})
        budget = budget_from_mapping(
            {
                "per_analysis_requests": 1,
                "per_day_requests": 1,
                "per_analysis_tokens": 1,
                "per_day_tokens": 1,
                "per_analysis_exa": 1,
                "per_day_exa": 1,
            }
        )
        self.assertEqual(budget.per_day_exa, 1)
        with self.assertRaises(ValueError):
            live_budget_from_mapping(
                {
                    "per_analysis_requests": 1,
                    "per_day_requests": 1,
                    "per_analysis_tokens": 1,
                    "per_day_tokens": 1,
                    "per_analysis_exa": 1,
                    "per_day_exa": 1,
                }
            )


class CurrencyCeilingTests(unittest.TestCase):
    PAID = AttemptBudget(
        per_analysis_requests=100,
        per_day_requests=100,
        per_analysis_tokens=10_000_000,
        per_day_tokens=10_000_000,
        per_analysis_exa=100,
        per_day_exa=100,
        paid_mode=True,
        provider_price_per_million=2.0,
        exa_price_per_operation=0.01,
        per_analysis_currency=1.0,
        per_day_currency=2.0,
        per_analysis_exa_currency=1.0,
        per_day_exa_currency=2.0,
    )

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = open_store(Path(self.directory.name) / "app.sqlite3")
        self.addCleanup(self.store.close)
        self.service = AnalysisService(self.store, budget=self.PAID)
        self.analysis_id, _ = self.service.create(
            period_digest="p",
            selected_item_ids=["a.com"],
            candidates=[{"item_id": "a.com", "domain": "a.com"}],
            provider="p",
            model_id="m",
            config_fingerprint="c",
            policy_revision=1,
        )

    def attempt_count(self):
        return self.store._conn.execute("SELECT count(*) FROM call_attempts").fetchone()[0]

    def test_unknown_provider_price_fails_closed_before_any_reservation(self):
        budget = AttemptBudget(
            per_analysis_requests=10,
            per_day_requests=10,
            per_analysis_tokens=1000,
            per_day_tokens=1000,
            per_analysis_exa=10,
            per_day_exa=10,
            paid_mode=True,
            exa_price_per_operation=0.01,
            per_analysis_currency=1.0,
            per_day_currency=1.0,
            per_analysis_exa_currency=1.0,
            per_day_exa_currency=1.0,
            # provider_price_per_million intentionally missing.
        )
        service = AnalysisService(self.store, budget=budget)
        with self.assertRaises(BudgetExceeded) as caught:
            service.reserve(self.analysis_id, kind="provider_request", tokens=1000)
        self.assertEqual(caught.exception.scope, "currency")
        self.assertEqual(self.attempt_count(), 0)

    def test_unknown_exa_price_fails_closed_before_any_reservation(self):
        budget = AttemptBudget(
            per_analysis_requests=10,
            per_day_requests=10,
            per_analysis_tokens=1000,
            per_day_tokens=1000,
            per_analysis_exa=10,
            per_day_exa=10,
            paid_mode=True,
            provider_price_per_million=2.0,
            per_analysis_currency=1.0,
            per_day_currency=1.0,
            per_analysis_exa_currency=1.0,
            per_day_exa_currency=1.0,
            # exa_price_per_operation intentionally missing.
        )
        service = AnalysisService(self.store, budget=budget)
        with self.assertRaises(BudgetExceeded) as caught:
            service.reserve(self.analysis_id, kind="exa_search", tokens=0)
        self.assertEqual(caught.exception.scope, "currency")
        self.assertEqual(self.attempt_count(), 0)

    def test_provider_currency_ceiling_refuses_over_budget_dispatch(self):
        # 2.0 per million tokens: a 1,000,000-token reservation costs 2.0, above
        # the 1.0 per-analysis ceiling.
        with self.assertRaises(BudgetExceeded) as caught:
            self.service.reserve(self.analysis_id, kind="provider_request", tokens=1_000_000)
        self.assertEqual(caught.exception.scope, "currency")
        self.assertEqual(self.attempt_count(), 0)

    def test_exa_currency_ceiling_refuses_over_budget_dispatch(self):
        budget = AttemptBudget(
            per_analysis_requests=10,
            per_day_requests=10,
            per_analysis_tokens=1000,
            per_day_tokens=1000,
            per_analysis_exa=100,
            per_day_exa=100,
            paid_mode=True,
            provider_price_per_million=0.0,
            exa_price_per_operation=1.0,
            per_analysis_currency=100.0,
            per_day_currency=100.0,
            per_analysis_exa_currency=1.0,  # one operation exactly fits.
            per_day_exa_currency=100.0,
        )
        service = AnalysisService(self.store, budget=budget)
        first = service.reserve(self.analysis_id, kind="exa_search", tokens=0)
        self.assertIsNotNone(first)
        with self.assertRaises(BudgetExceeded) as caught:
            service.reserve(self.analysis_id, kind="exa_search", tokens=0)
        self.assertEqual(caught.exception.scope, "currency")

    def test_free_mode_skips_currency_accounting_entirely(self):
        budget = AttemptBudget(
            per_analysis_requests=10,
            per_day_requests=10,
            per_analysis_tokens=1000,
            per_day_tokens=1000,
            per_analysis_exa=10,
            per_day_exa=10,
            paid_mode=False,
        )
        service = AnalysisService(self.store, budget=budget)
        reservation = service.reserve(self.analysis_id, kind="provider_request", tokens=500)
        self.assertIsNotNone(reservation)
        self.assertEqual(self.attempt_count(), 1)

    def test_concurrent_reservations_cannot_both_spend_the_same_headroom(self):
        first = self.service.reserve(self.analysis_id, kind="provider_request", tokens=400_000)
        self.assertIsNotNone(first)
        # 400k tokens at 2.0/million = 0.8; a second 400k reservation would add
        # 0.8 -> 1.6, above the 1.0 per-analysis ceiling.
        with self.assertRaises(BudgetExceeded):
            self.service.reserve(self.analysis_id, kind="provider_request", tokens=400_000)
        self.assertEqual(self.attempt_count(), 1)

    def test_truly_concurrent_reservations_succeed_exactly_once(self):
        """Atomic reservation under real thread concurrency (spec R17).

        Six threads race for headroom that fits exactly one 400k-token
        reservation; the store lock and BEGIN IMMEDIATE guarantee a single
        winner with no double-spend and no lost reservation row.
        """
        import threading

        barrier = threading.Barrier(6)
        outcomes: list[str] = []

        def attempt() -> None:
            barrier.wait()
            try:
                reservation = self.service.reserve(
                    self.analysis_id, kind="provider_request", tokens=400_000
                )
            except BudgetExceeded:
                outcomes.append("refused")
            else:
                self.assertIsNotNone(reservation)
                outcomes.append("reserved")

        threads = [threading.Thread(target=attempt) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        # Exactly one 400k reservation fits under the 1.0 per-analysis ceiling
        # (0.8 each; a second would add to 1.6): one winner, five refusals.
        self.assertEqual(outcomes.count("reserved"), 1)
        self.assertEqual(outcomes.count("refused"), 5)
        self.assertEqual(self.attempt_count(), 1)


if __name__ == "__main__":
    unittest.main()
