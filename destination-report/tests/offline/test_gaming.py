"""Synthetic namespace matching and household gaming read-model tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from household_report.gaming import (
    GamingDataError,
    ReviewError,
    build_gaming_projection,
    load_namespace_list,
    match_namespace,
    validate_review_proposal,
)
from household_report.reporting import ReportService
from household_report.storage import open_store


def rule(
    namespace="game.example.test",
    *,
    match="suffix",
    group_id="game-one",
    group_label="Game One",
    group_kind="game",
):
    return {
        "rule_id": "rule-1",
        "namespace": namespace,
        "match": match,
        "group_id": group_id,
        "group_label": group_label,
        "group_kind": group_kind,
        "review_note": "Synthetic rule for tests",
    }


def result(state, role="unknown"):
    return {
        "state": state,
        "role": role,
        "service": "Synthetic service",
        "provider": "Synthetic provider",
        "category": "software",
        "reason": None,
        "analysis_id": "analysis-1",
        "created_utc": "2026-10-23T06:00:00Z",
        "supporting_spans": [{"text": "synthetic evidence"}],
    }


def entry(domain, count, analysis=None, *, ids=None):
    return {
        "domain": domain,
        "query_count": count,
        "first_query_utc": "2026-10-23T06:00:00Z",
        "last_query_utc": "2026-10-23T06:05:00Z",
        "query_types": {"A": count},
        "statuses": {"FORWARDED": count},
        "dns_replies": {"IP": count},
        "observation_ids": ids or list(range(count)),
        "apparent_clients": {"192.0.2.1": count},
        "classification": {"analysis": analysis},
    }


class NamespaceTests(unittest.TestCase):
    def test_loads_reviewed_rules_and_fingerprints_exact_bytes(self):
        raw = json.dumps(
            {"schema_version": 1, "revision": "r1", "rules": [rule()]},
            separators=(",", ":"),
        ).encode()
        loaded = load_namespace_list(raw)
        self.assertEqual(loaded.state, "available")
        self.assertEqual(loaded.revision, "r1")
        self.assertEqual(loaded.sha256, hashlib.sha256(raw).hexdigest())

    def test_missing_list_is_unavailable_but_valid_empty_list_is_available(self):
        self.assertEqual(load_namespace_list(None).state, "unavailable")
        empty = load_namespace_list(b'{"schema_version":1,"revision":"r0","rules":[]}')
        self.assertEqual(empty.state, "available")
        self.assertEqual(empty.rules, ())

    def test_rejects_invalid_or_conflicting_namespace_data_as_a_whole(self):
        for bad in (
            "test",
            "*.example.test",
            "https://example.test",
            "192.0.2.1",
            "1.0.0.127.in-addr.arpa",
            "_sip._tcp.example.test",
        ):
            with self.subTest(namespace=bad):
                raw = json.dumps(
                    {"schema_version": 1, "revision": "r1", "rules": [rule(bad)]}
                ).encode()
                with self.assertRaises(GamingDataError):
                    load_namespace_list(raw)
        duplicate = [rule(), {**rule(), "rule_id": "rule-2", "group_id": "other"}]
        with self.assertRaises(GamingDataError):
            load_namespace_list(
                json.dumps({"schema_version": 1, "revision": "r1", "rules": duplicate}).encode()
            )
        with self.assertRaises(GamingDataError):
            load_namespace_list(b'{"schema_version":true,"revision":"r1","rules":[]}')

    def test_matching_normalizes_case_and_dot_and_uses_exact_then_longest_suffix(self):
        rules = load_namespace_list(
            json.dumps(
                {
                    "schema_version": 1,
                    "revision": "r1",
                    "rules": [
                        rule("example.test", group_id="broad", group_label="Broad"),
                        {
                            **rule(
                                "game.example.test", group_id="specific", group_label="Specific"
                            ),
                            "rule_id": "rule-2",
                        },
                        {
                            **rule(
                                "api.game.example.test",
                                match="exact",
                                group_id="exact",
                                group_label="Exact",
                            ),
                            "rule_id": "rule-3",
                        },
                    ],
                }
            ).encode()
        )
        self.assertEqual(match_namespace("GAME.EXAMPLE.TEST.", rules.rules)["group_id"], "specific")
        self.assertEqual(match_namespace("api.game.example.test", rules.rules)["group_id"], "exact")
        self.assertIsNone(match_namespace("game.example.test.evil.test", rules.rules))
        self.assertIsNone(match_namespace("notgame.example.org", rules.rules))


class ReviewProposalTests(unittest.TestCase):
    def valid(self, **overrides):
        proposal = {
            "hostname": "lobby.example.net",
            "group_id": "game-two",
            "group_label": "Game Two",
            "group_kind": "game",
            "review_note": "Owner-verified storefront and lobby endpoint.",
        }
        proposal.update(overrides)
        return proposal

    def test_exact_host_review_produces_a_rule(self):
        rule = validate_review_proposal(**self.valid())
        self.assertEqual(rule["namespace"], "lobby.example.net")
        self.assertEqual(rule["match"], "exact")
        self.assertEqual(rule["group_kind"], "game")
        self.assertEqual(rule["review_note"], "Owner-verified storefront and lobby endpoint.")

    def test_rejects_broadening_suffix_and_publisher_cdn_overreach(self):
        with self.assertRaises(ReviewError):
            validate_review_proposal(**self.valid(match="suffix"))
        with self.assertRaises(ReviewError):
            validate_review_proposal(
                **self.valid(hostname="cdn.example.net", match="suffix", group_id="cdn")
            )

    def test_rejects_generic_service_labels(self):
        for label in ("game", "gaming", "Game Client", "game unknown", "unknown"):
            with self.subTest(label=label):
                with self.assertRaises(ReviewError):
                    validate_review_proposal(**self.valid(group_label=label))

    def test_rejects_missing_evidence_and_invalid_host(self):
        with self.assertRaises(ReviewError):
            validate_review_proposal(**self.valid(review_note="   "))
        with self.assertRaises(ReviewError):
            validate_review_proposal(**self.valid(hostname="192.0.2.1"))
        with self.assertRaises(ReviewError):
            validate_review_proposal(**self.valid(hostname="*.example.net"))
        with self.assertRaises(ReviewError):
            validate_review_proposal(**self.valid(group_kind="service"))


class GamingProjectionTests(unittest.TestCase):
    def test_selects_known_and_grounded_gameplay_union_without_duplicate_overlap(self):
        known = load_namespace_list(
            json.dumps({"schema_version": 1, "revision": "r1", "rules": [rule()]}).encode()
        )
        report = {
            "snapshot_id": "snapshot-1",
            "period_digest": "period-digest",
            "window": {"start_utc": "start", "end_utc": "end", "bounds": "[start,end)"},
            "sources": [{"start_epoch": 100, "end_epoch": 3700}],
            "destinations": [
                entry(
                    "game.example.test",
                    2,
                    result("model_proposal", "gameplay_matchmaking"),
                    ids=["snapshot-1:1", "snapshot-1:2"],
                ),
                entry(
                    "match.example.test",
                    1,
                    result("model_proposal", "gameplay_matchmaking"),
                    ids=["snapshot-1:3"],
                ),
                entry(
                    "launcher.example.test",
                    1,
                    result("model_proposal", "launcher"),
                    ids=["snapshot-1:4"],
                ),
                entry("other.test", 1, result("unknown"), ids=["snapshot-1:5"]),
            ],
            "reverse_lookups": [entry("1.0.0.127.in-addr.arpa", 1, ids=["snapshot-1:6"])],
        }
        rows = [
            {"id": 1, "timestamp": 101, "domain": "game.example.test", "client": "192.0.2.1"},
            {"id": 2, "timestamp": 102, "domain": "game.example.test", "client": "192.0.2.1"},
            {"id": 3, "timestamp": 103, "domain": "match.example.test", "client": "192.0.2.1"},
            {"id": 4, "timestamp": 104, "domain": "launcher.example.test", "client": "192.0.2.1"},
            {"id": 5, "timestamp": 105, "domain": "other.test", "client": "192.0.2.1"},
            {"id": 6, "timestamp": 106, "domain": "1.0.0.127.in-addr.arpa", "client": "192.0.2.1"},
        ]
        projected = build_gaming_projection(report, known, rows)
        self.assertEqual(
            [item["domain"] for item in projected["entries"]],
            ["game.example.test", "match.example.test"],
        )
        self.assertEqual(projected["counts"]["known_model_overlap_domains"], 1)
        self.assertEqual(projected["counts"]["eligible_domains"], 2)
        self.assertEqual(projected["counts"]["eligible_rows"], 3)
        self.assertEqual(projected["timeline"]["bins"][0]["rows"], 3)
        self.assertNotIn("apparent_clients", projected["entries"][0])
        self.assertNotIn("client", projected["timeline"])
        self.assertEqual(projected["household_scope"], "household scope; device unknown")

    def test_service_pins_newest_window_start_and_suppresses_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            store = open_store(Path(directory) / "state.sqlite3")
            self.addCleanup(store.close)

            def snapshot(start, identifier):
                return {
                    "schema_version": 1,
                    "start_epoch": start,
                    "end_epoch": start + 3600,
                    "captured_utc": "2026-10-23T06:00:00Z",
                    "retained_rows": 1,
                    "oldest_epoch": start,
                    "newest_epoch": start,
                    "window_count": 1,
                    "observations": [
                        {
                            "id": identifier,
                            "timestamp": start,
                            "type": 1,
                            "status": 2,
                            "domain": "game.example.test",
                            "client": "192.0.2.1",
                            "forward": None,
                            "additional_info": None,
                            "list_id": None,
                            "reply_type": 4,
                            "ede": None,
                            "reply_time": 0.01,
                            "dnssec": 0,
                        }
                    ],
                }

            older = store.import_snapshot(snapshot(50, 1), datasource="synthetic")
            newer = store.import_snapshot(snapshot(100, 2), datasource="synthetic")
            namespace = load_namespace_list(
                json.dumps({"schema_version": 1, "revision": "r1", "rules": [rule()]}).encode()
            )

            def forbidden_attribution(_rows):
                self.fail("gaming projection must suppress attribution callback")

            service = ReportService(store, attribution_source=forbidden_attribution)
            projection = service.gaming_projection(namespace)
            self.assertEqual(projection["snapshot_id"], newer.snapshot_id)
            self.assertNotEqual(projection["snapshot_id"], older.snapshot_id)
            self.assertEqual(projection["counts"]["eligible_rows"], 1)

    def test_service_refuses_snapshot_wider_than_one_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            store = open_store(Path(directory) / "state.sqlite3")
            self.addCleanup(store.close)
            snapshot = {
                "schema_version": 1,
                "start_epoch": 100,
                "end_epoch": 7300,
                "captured_utc": "2026-10-23T06:00:00Z",
                "retained_rows": 1,
                "oldest_epoch": 100,
                "newest_epoch": 100,
                "window_count": 1,
                "observations": [
                    {
                        "id": 1,
                        "timestamp": 100,
                        "type": 1,
                        "status": 2,
                        "domain": "game.example.test",
                        "client": "192.0.2.1",
                        "forward": None,
                        "additional_info": None,
                        "list_id": None,
                        "reply_type": 4,
                        "ede": None,
                        "reply_time": 0.01,
                        "dnssec": 0,
                    }
                ],
            }
            store.import_snapshot(snapshot, datasource="synthetic")
            namespace = load_namespace_list(b'{"schema_version":1,"revision":"r0","rules":[]}')
            with self.assertRaisesRegex(ValueError, "at most one hour"):
                ReportService(store).gaming_projection(namespace)

    def test_newer_unknown_and_non_gameplay_proposals_do_not_select_model_only(self):
        unavailable = load_namespace_list(None)
        report = {
            "snapshot_id": "snapshot-1",
            "period_digest": "period-digest",
            "window": {"start_utc": "start", "end_utc": "end", "bounds": "[start,end)"},
            "sources": [{"start_epoch": 100, "end_epoch": 3700}],
            "destinations": [
                entry("newer-unknown.test", 1, result("unknown"), ids=[1]),
                entry("launcher.test", 1, result("model_proposal", "launcher"), ids=[2]),
                entry(
                    "gameplay.test", 1, result("model_proposal", "gameplay_matchmaking"), ids=[3]
                ),
            ],
            "reverse_lookups": [],
        }
        projected = build_gaming_projection(
            report,
            unavailable,
            [
                {"id": i, "timestamp": 100 + i, "domain": f"{i}.test", "client": "x"}
                for i in (1, 2, 3)
            ],
        )
        self.assertEqual([item["domain"] for item in projected["entries"]], ["gameplay.test"])
        self.assertEqual(projected["namespace"]["state"], "unavailable")


if __name__ == "__main__":
    unittest.main()
