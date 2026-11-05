"""Reporting contracts: promotion of the proof-of-concept behaviour plus periods.

No household data, network, Docker or credentials are required.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import UTC, datetime

from household_report import reporting


def snapshot_of(domains, *, start=100, end=3700):
    rows = [
        {
            "id": index,
            "timestamp": 100 + index,
            "domain": domain,
            "client": "192.168.1.1",
            "type": 1 if index % 2 else 2,
            "status": 14 if index % 2 else 17,
            "reply_type": 0 if index % 2 else 4,
            "ede": None,
        }
        for index, domain in enumerate(domains)
    ]
    return {
        "start_epoch": start,
        "end_epoch": end,
        "window_count": len(rows),
        "observations": rows,
        "rate_context": [],
        "retained_rows": len(rows),
        "oldest_epoch": 100,
        "newest_epoch": 3699,
        "captured_utc": "2026-10-23T06:00:00Z",
    }


class ReportingTests(unittest.TestCase):
    def test_preserves_every_row_and_query_type_without_retry_deduplication(self):
        report = reporting.build_report(snapshot_of(["a.test"] * 4), {})
        self.assertEqual(report["summary"]["raw_rows"], 4)
        self.assertEqual(report["destinations"][0]["query_count"], 4)
        self.assertEqual(report["destinations"][0]["observation_ids"], [0, 1, 2, 3])
        self.assertEqual(sum(report["destinations"][0]["query_types"].values()), 4)
        self.assertEqual(sum(report["destinations"][0]["statuses"].values()), 4)
        self.assertEqual(sum(report["destinations"][0]["dns_replies"].values()), 4)

    def test_reverse_lookups_are_separate_but_retained(self):
        report = reporting.build_report(snapshot_of(["a.test", "1.1.168.192.in-addr.arpa"]), {})
        self.assertEqual(report["summary"]["raw_rows"], 2)
        self.assertEqual(report["summary"]["reverse_rows"], 1)
        self.assertEqual(len(report["reverse_lookups"]), 1)
        self.assertEqual(report["reverse_lookups"][0]["query_count"], 1)

    def test_provider_only_rule_fills_provider_but_never_a_service(self):
        rule = {
            "match": "suffix",
            "domain": "jsdelivr.test",
            "field_scope": "provider_only",
            "service": None,
            "provider": "Shared CDN",
            "category": "cdn",
            "confidence": "medium",
            "method": "reviewed_mapping",
            "verification_state": "verified",
            "evidence": [{"url": "https://docs.example/cdn", "claim": "Shared namespace"}],
            "verified_until": "2030-01-01T00:00:00Z",
        }
        report = reporting.build_report(snapshot_of(["cdn.jsdelivr.test"]), {"mappings": [rule]})
        classification = report["destinations"][0]["classification"]
        self.assertIsNone(classification["likely_service"])
        self.assertEqual(classification["provider"], "Shared CDN")
        self.assertEqual(classification["scope"], "provider_only")
        coverage = reporting.classification_coverage(report)
        self.assertEqual(coverage["domains"]["provider_only"], 1)
        self.assertEqual(coverage["domains"]["service_specific"], 0)
        self.assertEqual(report["summary"]["provider_only_domains"], 1)

    def test_unknown_and_shared_cdn_do_not_become_specific_services(self):
        rule = {
            "match": "suffix",
            "domain": "cdn.test",
            "likely_service": None,
            "provider": "Shared CDN",
            "category": "shared_infrastructure",
            "confidence": "high",
            "ambiguity": "Tenant unknown",
            "evidence": [{"url": "https://docs.example/cdn", "claim": "Shared namespace"}],
            "verified_until": "2030-01-01T00:00:00Z",
        }
        report = reporting.build_report(
            snapshot_of(["video-service.cdn.test", "cdn.test.evil.test"]), {"mappings": [rule]}
        )
        by_domain = {entry["domain"]: entry for entry in report["destinations"]}
        self.assertIsNone(by_domain["video-service.cdn.test"]["classification"]["likely_service"])
        self.assertEqual(by_domain["cdn.test.evil.test"]["classification"]["confidence"], "unknown")

    def test_expired_or_uncited_cache_is_unknown(self):
        rule = {
            "match": "exact",
            "domain": "a.test",
            "likely_service": "Invented",
            "confidence": "high",
            "evidence": [],
            "verified_until": "2030-01-01T00:00:00Z",
        }
        report = reporting.build_report(snapshot_of(["a.test"]), {"mappings": [rule]})
        self.assertEqual(report["destinations"][0]["classification"]["confidence"], "unknown")
        rule["evidence"] = [{"url": "https://docs.example", "claim": "Old claim"}]
        rule["verified_until"] = "2020-01-01T00:00:00Z"
        report = reporting.build_report(snapshot_of(["a.test"]), {"mappings": [rule]})
        self.assertEqual(report["destinations"][0]["classification"]["confidence"], "unknown")

    def test_saved_model_proposals_remain_separate_and_coverage_denominators_reconcile(self):
        snapshot = snapshot_of(["example.com", "example.com", "other.test"])
        proposals = [
            {
                "domain": "example.com",
                "analysis_id": "analysis-1",
                "created_utc": "2026-10-23T06:00:00Z",
                "result_json": json.dumps(
                    {
                        "source": "model",
                        "service": "Example Launcher",
                        "provider": "Example Inc",
                        "role": "launcher",
                        "category": "software",
                        "confidence": "medium",
                        "verification_state": "ai_grounded",
                        "supporting_spans": [
                            {
                                "source_id": "s1",
                                "source_url": "https://docs.example/about",
                                "source_sha256": "a" * 64,
                                "start": 0,
                                "end": 24,
                                "text": "Example.com launcher docs",
                            }
                        ],
                    }
                ),
            }
        ]
        report = reporting.build_report(snapshot, {}, analysis_results=proposals)
        by_domain = {item["domain"]: item for item in report["destinations"]}
        self.assertIsNone(by_domain["example.com"]["classification"]["likely_service"])
        self.assertEqual(
            by_domain["example.com"]["classification"]["analysis"]["state"], "model_proposal"
        )
        coverage = report["analysis_coverage"]
        self.assertEqual(coverage["domains"]["total"], 2)
        self.assertEqual(coverage["rows"]["total"], 3)
        self.assertEqual(coverage["domains"]["by_role"]["launcher"], 1)
        self.assertEqual(coverage["rows"]["by_state"]["not_analyzed"], 1)

    def test_suspected_periodic_probe_is_only_a_tag_not_a_subtraction(self):
        snapshot = snapshot_of(["example.org"] * 4)
        for row, timestamp in zip(snapshot["observations"], [100, 1000, 1900, 2800], strict=True):
            row["timestamp"] = timestamp
        report = reporting.build_report(snapshot, {})
        entry = report["destinations"][0]
        self.assertIn("suspected_periodic_probe", entry["tags"])
        self.assertEqual(entry["query_count"], 4)
        self.assertEqual(entry["periodicity"]["median_gap_seconds"], 900)

    def test_reviewed_probe_suspicion_is_retained_without_regular_timing(self):
        rule = {
            "match": "exact",
            "domain": "probe.test",
            "likely_service": None,
            "provider": None,
            "category": "unknown",
            "confidence": "low",
            "ambiguity": "Purpose unknown",
            "suspected_probe_reason": "Earlier local cadence review; unproven",
            "evidence": [{"url": "https://docs.example/probe", "claim": "Namespace only"}],
            "verified_until": "2030-01-01T00:00:00Z",
        }
        report = reporting.build_report(snapshot_of(["probe.test"]), {"mappings": [rule]})
        self.assertIn("suspected_periodic_probe", report["destinations"][0]["tags"])
        self.assertEqual(report["summary"]["raw_rows"], 1)

    def test_snapshot_mismatch_fails_instead_of_publishing_partial_totals(self):
        snapshot = snapshot_of(["a.test"])
        snapshot["window_count"] = 2
        with self.assertRaises(ValueError):
            reporting.build_report(snapshot, {})

    def test_peak_60s_rate_includes_context_and_records_window_times(self):
        snapshot = snapshot_of(["a.test"] * 4)
        for row, timestamp in zip(snapshot["observations"], [100, 120, 180, 181], strict=True):
            row["timestamp"] = timestamp
        snapshot["rate_context"] = [{"timestamp": 99, "client": "192.168.1.1"}]
        report = reporting.build_report(snapshot, {})
        peak = report["summary"]["peak_60s_windows"]["192.168.1.1"]
        self.assertEqual(peak["rows"], 3)
        self.assertEqual(peak["start_epoch"], 60)
        self.assertEqual(peak["end_epoch"], 120)

    def test_html_escapes_observed_domains_and_loads_no_remote_assets(self):
        report = reporting.build_report(snapshot_of(["<script>alert(1)</script>.test"]), {})
        page = reporting.render_html(report)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script src=", page)
        self.assertNotIn("<img", page)

    def test_extraction_sql_is_one_read_statement_and_half_open(self):
        database = sqlite3.connect(":memory:")
        self.addCleanup(database.close)
        database.execute(
            "CREATE TABLE queries(id,timestamp,type,status,domain,client,reply_type,ede,"
            "reply_time,dnssec,forward,additional_info,list_id)"
        )
        database.executemany(
            "INSERT INTO queries(id,timestamp,type,status,domain,client,reply_type,ede,"
            "reply_time,dnssec) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (1, 99, 1, 2, "a.test", "router", 4, None, 0.1, 0),
                (2, 100, 1, 2, "a.test", "router", 4, None, 0.1, 0),
                (3, 3700, 1, 2, "a.test", "router", 4, None, 0.1, 0),
            ],
        )
        result = json.loads(database.execute(reporting.extraction_query(100, 3700)).fetchone()[0])
        self.assertEqual(result["window_count"], 1)
        self.assertEqual([row["id"] for row in result["observations"]], [2])
        self.assertEqual(len(result["rate_context"]), 1)
        for key in ("forward", "additional_info", "list_id"):
            self.assertIn(key, result["observations"][0])

    def test_extraction_refuses_more_than_the_legacy_hour(self):
        with self.assertRaises(reporting.ReportingError):
            reporting.extraction_query(0, 7200)
        query = reporting.extraction_query(0, 7200, max_seconds=reporting.MAX_WINDOW_SECONDS)
        self.assertIn("json_object", query)

    def test_presets_resolve_once_to_closed_whole_hours(self):
        moment = datetime(2026, 10, 23, 6, 45, 30, tzinfo=UTC)
        start, end = reporting.resolve_preset("24h", now=moment)
        self.assertEqual(end - start, 24 * 3600)
        self.assertEqual(datetime.fromtimestamp(end, UTC).minute, 0)
        self.assertEqual(datetime.fromtimestamp(end, UTC).second, 0)
        self.assertEqual(datetime.fromtimestamp(end, UTC), datetime(2026, 10, 23, 6, 0, tzinfo=UTC))
        with self.assertRaises(reporting.ReportingError):
            reporting.resolve_preset("7d", now=moment)

    def test_custom_bounds_reject_nonexistent_and_ambiguous_local_times(self):
        start, end = reporting.resolve_custom(
            "2026-10-23T00:00:00", "2026-10-23T06:00:00", timezone_name="UTC"
        )
        self.assertEqual(end - start, 6 * 3600)
        # 02:30 does not exist on the US spring-forward date.
        with self.assertRaises(reporting.ReportingError):
            reporting.resolve_custom(
                "2026-03-08T00:00:00", "2026-03-08T02:30:00", timezone_name="America/New_York"
            )
        # 01:30 happens twice on the US fall-back date.
        with self.assertRaises(reporting.ReportingError):
            reporting.resolve_custom(
                "2026-11-01T00:00:00", "2026-11-01T01:30:00", timezone_name="America/New_York"
            )

    def test_coverage_separates_quiet_minutes_from_collection_gaps(self):
        snapshot = snapshot_of(["a.test"] * 2)
        report = reporting.build_report(snapshot, {})
        coverage = report["coverage"]
        self.assertEqual(coverage["included_rows"], 2)
        self.assertEqual(coverage["total_minutes"], 60)
        self.assertGreater(coverage["quiet_minutes"], 0)
        self.assertIn("not an outage", coverage["quiet_minute_note"])
        self.assertEqual(coverage["retained_rows_all_time"], 2)

    def test_attribution_counts_reconcile_and_router_rows_stay_unknown(self):
        snapshot = snapshot_of(["a.test", "b.test"])
        snapshot["observations"][1]["client"] = "192.168.1.23"
        report = reporting.build_report(snapshot, {}, attributions={0: "device-a"})
        summary = report["summary"]
        self.assertEqual(summary["device_attributed_rows"], 1)
        self.assertEqual(summary["device_unattributed_rows"], 1)
        self.assertEqual(
            summary["device_attributed_rows"] + summary["device_unattributed_rows"],
            summary["raw_rows"],
        )
        self.assertEqual(summary["router_forwarded_rows_origin_unknown"], 1)


if __name__ == "__main__":
    unittest.main()
