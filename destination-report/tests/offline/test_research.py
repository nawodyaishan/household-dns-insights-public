"""Research coverage and first-time worklist progression tests (R15/R16)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from household_report.research import (
    COVERAGE_STATES,
    ResearchError,
    coverage_summary,
    first_time_page,
    research_coverage,
)
from household_report.storage import open_store


def rule(domain, *, verification_state="reviewed", service="Synthetic service"):
    return {
        "domain": domain,
        "match": "exact",
        "field_scope": "service_and_provider",
        "service": service,
        "provider": None,
        "category": "software",
        "confidence": "high",
        "ambiguity": None,
        "method": "human" if verification_state == "reviewed" else "ai_grounded",
        "verification_state": verification_state,
        "checked_utc": "2026-11-01T00:00:00Z",
        "verified_until": "2099-01-01T00:00:00Z",
        "policy_revision": 1,
        "evidence": [{"url": "https://example.com", "claim": "synthetic"}],
        "source_hash": None,
        "model_provenance": None,
    }


AS_OF = "2026-11-02T00:00:00Z"


class CoverageTests(unittest.TestCase):
    def test_each_name_gets_exactly_one_mutually_exclusive_state(self):
        domain_rows = {
            "reviewed.com": 10,
            "cached.com": 9,
            "resolved.com": 8,
            "unresolved.com": 7,
            "safe.com": 6,
            "pending.com": 5,
            "1.0.0.127.in-addr.arpa": 4,
        }
        coverage = research_coverage(
            domain_rows,
            rules=[
                rule("reviewed.com"),
                rule("cached.com", verification_state="ai_grounded"),
            ],
            prior_items={"resolved.com": "resolved", "unresolved.com": "unresolved"},
            exclude=[],
            as_of=AS_OF,
        )
        states = coverage["states"]
        self.assertEqual(states["reviewed.com"], "reviewed")
        self.assertEqual(states["cached.com"], "cached")
        self.assertEqual(states["resolved.com"], "researched_resolved")
        self.assertEqual(states["unresolved.com"], "researched_unresolved")
        self.assertEqual(states["pending.com"], "not_yet_researched")
        self.assertEqual(states["safe.com"], "not_yet_researched")
        self.assertEqual(states["1.0.0.127.in-addr.arpa"], "excluded")
        self.assertEqual(set(states), set(domain_rows))
        self.assertEqual(sum(coverage["counts"].values()), coverage["eligible"])

    def test_owner_exclusion_and_unsafe_names_are_excluded(self):
        coverage = research_coverage(
            {"safe.com": 3, "private.example": 2},
            rules=[],
            prior_items={},
            exclude=["safe.com"],
            as_of=AS_OF,
        )
        self.assertEqual(coverage["states"]["safe.com"], "excluded")
        self.assertIn("excluded locally by the owner", coverage["details"]["safe.com"])
        self.assertEqual(coverage["states"]["private.example"], "excluded")

    def test_summary_exposes_explicit_denominator(self):
        coverage = research_coverage(
            {"a.com": 1, "b.com": 1},
            rules=[],
            prior_items={},
            as_of=AS_OF,
        )
        summary = coverage_summary(coverage)
        self.assertEqual(summary["eligible"], 2)
        self.assertEqual(summary["denominator"], 2)
        self.assertEqual(summary["pending"], 2)
        self.assertFalse(summary["complete"])

    def test_states_are_bounded_to_the_documented_vocabulary(self):
        self.assertEqual(
            set(COVERAGE_STATES),
            {
                "reviewed",
                "cached",
                "researched_resolved",
                "researched_unresolved",
                "excluded",
                "not_yet_researched",
            },
        )


class FirstTimePageTests(unittest.TestCase):
    def coverage(self, names, *, cached=(), prior=None, exclude=()):
        domain_rows = {name: index + 1 for index, name in enumerate(names)}
        rules = [rule(name) for name in cached]
        return research_coverage(
            domain_rows,
            rules=rules,
            prior_items=prior or {},
            exclude=list(exclude),
            as_of=AS_OF,
        )

    def test_page_excludes_cached_reviewed_and_researched_names(self):
        coverage = self.coverage(
            ["cached.com", "resolved.com", "pending.com", "other.com"],
            cached=["cached.com"],
            prior={"resolved.com": "resolved"},
        )
        page = first_time_page(coverage, limit=20)
        names = [item["name"] for item in page["candidates"]]
        self.assertNotIn("cached.com", names)
        self.assertNotIn("resolved.com", names)
        self.assertIn("pending.com", names)
        self.assertIn("other.com", names)

    def test_over_forty_names_progress_across_pages_without_repeating(self):
        names = [f"name-{index:02d}.com" for index in range(45)]
        cached = ["name-00.com", "name-01.com"]
        coverage = self.coverage(names, cached=cached)
        first = first_time_page(coverage, offset=0, limit=20)
        second = first_time_page(coverage, offset=20, limit=20)
        third = first_time_page(coverage, offset=40, limit=20)
        first_names = {item["name"] for item in first["candidates"]}
        second_names = {item["name"] for item in second["candidates"]}
        third_names = {item["name"] for item in third["candidates"]}
        self.assertEqual(len(first_names), 20)
        self.assertEqual(len(second_names), 20)
        self.assertEqual(len(third_names), 3)
        self.assertFalse(first_names & second_names)
        self.assertFalse(first_names & third_names)
        self.assertFalse(second_names & third_names)
        self.assertNotIn("name-00.com", first_names)
        self.assertNotIn("name-01.com", first_names)
        self.assertFalse(first["complete"])
        self.assertTrue(third["complete"])
        self.assertEqual(first["remaining"], 23)

    def test_researched_names_leave_the_pending_pool(self):
        coverage = self.coverage(
            ["a.com", "b.com", "c.com"],
            prior={"a.com": "unresolved", "b.com": "resolved"},
        )
        page = first_time_page(coverage, limit=20)
        self.assertEqual([item["name"] for item in page["candidates"]], ["c.com"])
        self.assertTrue(page["complete"])

    def test_invalid_page_limit_and_offset_are_rejected(self):
        coverage = self.coverage(["a.com"])
        for limit in (0, 21, -1):
            with self.subTest(limit=limit):
                with self.assertRaises(ResearchError):
                    first_time_page(coverage, limit=limit)
        with self.assertRaises(ResearchError):
            first_time_page(coverage, offset=-1)


class StoreResearchTests(unittest.TestCase):
    def research_store(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = open_store(Path(directory.name) / "app.sqlite3")
        self.addCleanup(store.close)
        store._conn.execute(
            """INSERT INTO analyses (analysis_id, state, period_digest, selection_digest,
               analyzer_version, created_utc, updated_utc)
               VALUES ('a1', 'completed', 'd', 'd', 2, '2026-11-01T00:00:00Z',
               '2026-11-01T00:00:00Z')"""
        )
        store._conn.execute(
            """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state,
               result_json) VALUES ('a1', 'i1', 'resolved.com', 'service_and_provider',
               'done', ?)""",
            ('{"service": "Game", "provider": null}',),
        )
        store._conn.execute(
            """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state,
               result_json) VALUES ('a1', 'i2', 'unknown.com', 'service_and_provider',
               'unknown', ?)""",
            ('{"unresolved_reason": "no evidence"}',),
        )
        return store

    def test_researched_domains_maps_terminal_outcomes(self):
        store = self.research_store()
        researched = store.researched_domains()
        self.assertEqual(researched["resolved.com"], "resolved")
        self.assertEqual(researched["unknown.com"], "unresolved")

    def test_legacy_states_never_invent_successful_research(self):
        """Cancelled jobs and non-done terminal items map to unresolved or absent.

        Mirrors legacy analyses: a cancelled analysis must not contribute any
        disposition, and failed/deferred/unknown items are unresolved, never
        resolved, regardless of any result payload they carry.
        """
        store = self.research_store()
        store._conn.execute(
            """INSERT INTO analyses (analysis_id, state, period_digest, selection_digest,
               analyzer_version, created_utc, updated_utc)
               VALUES ('a2', 'cancelled', 'd', 'd', 2, '2026-11-02T00:00:00Z',
               '2026-11-02T00:00:00Z')"""
        )
        store._conn.execute(
            """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state,
               result_json) VALUES ('a2', 'i3', 'cancelled.com', 'service_and_provider',
               'done', ?)""",
            ('{"service": "Should not count", "provider": "x"}',),
        )
        store._conn.execute(
            """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state,
               result_json) VALUES ('a1', 'i4', 'deferred.com', 'service_and_provider',
               'deferred', ?)""",
            ('{"service": "Sneaky", "provider": "y"}',),
        )
        store._conn.execute(
            """INSERT INTO analysis_items (analysis_id, item_id, domain, claim_scope, state,
               result_json) VALUES ('a1', 'i5', 'failed.com', 'service_and_provider',
               'failed', NULL)"""
        )
        researched = store.researched_domains()
        self.assertNotIn("cancelled.com", researched)
        self.assertEqual(researched["deferred.com"], "unresolved")
        self.assertEqual(researched["failed.com"], "unresolved")


if __name__ == "__main__":
    unittest.main()
