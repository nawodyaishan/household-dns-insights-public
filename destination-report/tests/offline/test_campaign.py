"""Campaign policy: durations, retention, chunk planning, DST days, coverage."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from household_report.campaign import (
    CHUNK_MAX_SECONDS,
    FINALIZATION_ALLOWANCE_SECONDS,
    MAX_CAMPAIGN_HOURS,
    MAX_CHUNK_ATTEMPTS,
    SETTLING_GRACE_SECONDS,
    CampaignError,
    coverage_summary,
    covered_local_days,
    duration_hours,
    extension_allowed,
    finalize_outcome,
    is_eligible,
    plan_chunk_windows,
    settling_until,
    validate_retention,
)

NY = ZoneInfo("America/New_York")


def active_campaign(**overrides):
    campaign = {
        "campaign_id": "c1",
        "state": "active",
        "start_epoch": 1_800_000_000,
        "end_epoch": 1_800_000_000 + 72 * 3600,
        "timezone": "America/New_York",
        "retention_days": 7,
        "rules_revision": "r1",
        "rules_sha256": "x" * 64,
        "rules_state": "available",
        "rules_ack": 0,
        "finalization_deadline": None,
    }
    campaign.update(overrides)
    return campaign


def chunk(char_id, *, start, end, state="scheduled", attempts=0, settling_until=None):
    return {
        "chunk_id": char_id,
        "start_epoch": start,
        "end_epoch": end,
        "settling_until": settling_until
        if settling_until is not None
        else end + SETTLING_GRACE_SECONDS,
        "state": state,
        "attempts": attempts,
    }


class DurationTests(unittest.TestCase):
    def test_allowed_durations_map_to_elapsed_utc_hours(self):
        self.assertEqual(duration_hours(3), 72)
        self.assertEqual(duration_hours(4), 96)
        self.assertEqual(duration_hours(5), 120)

    def test_other_durations_are_rejected(self):
        for days in (0, 1, 2, 6, 7):
            with self.assertRaises(CampaignError):
                duration_hours(days)

    def test_retention_boundaries_are_one_to_thirty(self):
        self.assertEqual(validate_retention(1), 1)
        self.assertEqual(validate_retention(30), 30)
        for days in (0, 31, -1):
            with self.assertRaises(CampaignError):
                validate_retention(days)


class ChunkPlanningTests(unittest.TestCase):
    def test_windows_are_contiguous_half_open_and_clipped(self):
        windows = plan_chunk_windows(100, 4000)
        self.assertEqual(windows, [(100, 3700), (3700, 4000)])
        for start, end in windows:
            self.assertLess(end - start, CHUNK_MAX_SECONDS + 1)
            self.assertLessEqual(end - start, CHUNK_MAX_SECONDS)
            self.assertGreater(end - start, 0)
        for (_, a_end), (b_start, _) in zip(windows, windows[1:], strict=False):
            self.assertEqual(a_end, b_start)

    def test_planning_is_deterministic(self):
        self.assertEqual(plan_chunk_windows(0, 3700), plan_chunk_windows(0, 3700))
        self.assertEqual(plan_chunk_windows(0, 3700), [(0, 3600), (3600, 3700)])

    def test_exact_hour_windows(self):
        self.assertEqual(plan_chunk_windows(0, 7200), [(0, 3600), (3600, 7200)])

    def test_invalid_windows_raise(self):
        with self.assertRaises(CampaignError):
            plan_chunk_windows(4000, 100)
        with self.assertRaises(CampaignError):
            plan_chunk_windows(0, 100, chunk_seconds=0)

    def test_settling_is_the_closed_window_plus_grace(self):
        self.assertEqual(settling_until(3600), 3600 + SETTLING_GRACE_SECONDS)


class EligibilityTests(unittest.TestCase):
    def test_chunk_is_not_eligible_before_settling(self):
        campaign = active_campaign()
        pending = chunk("c:0:3600", start=0, end=3600)
        self.assertFalse(is_eligible(campaign, pending, now_epoch=1000))
        self.assertFalse(is_eligible(campaign, pending, now_epoch=3599))
        self.assertTrue(is_eligible(campaign, pending, now_epoch=3600 + SETTLING_GRACE_SECONDS))
        self.assertTrue(is_eligible(campaign, pending, now_epoch=3720))

    def test_only_scheduled_or_failed_chunks_are_claimable(self):
        campaign = active_campaign()
        for state in (
            "captured",
            "import_pending",
            "imported",
            "expired",
            "partial",
            "successful_empty",
        ):
            self.assertFalse(
                is_eligible(campaign, chunk("c1", start=0, end=100, state=state), now_epoch=10_000),
                state,
            )

    def test_eligible_after_a_failed_capture_with_headroom(self):
        campaign = active_campaign()
        failed = chunk("c1", start=0, end=100, state="failed", attempts=1)
        now = 100 + SETTLING_GRACE_SECONDS
        self.assertTrue(is_eligible(campaign, failed, now_epoch=now))
        exhausted = chunk("c1", start=0, end=100, state="failed", attempts=MAX_CHUNK_ATTEMPTS)
        self.assertFalse(is_eligible(campaign, exhausted, now_epoch=now))

    def test_chunks_beyond_the_campaign_end_are_never_claimable(self):
        campaign = active_campaign(end_epoch=1_800_000_000 + 1000)
        out_of_bounds = chunk("c1", start=1_800_000_000 + 1000, end=1_800_000_000 + 2000)
        self.assertFalse(is_eligible(campaign, out_of_bounds, now_epoch=1_800_000_000 + 5000))

    def test_finalization_allowance_bounds_claims(self):
        end = 1_800_000_000 + 72 * 3600
        deadline = end + FINALIZATION_ALLOWANCE_SECONDS
        campaign = active_campaign(
            state="finalizing", end_epoch=end, finalization_deadline=deadline
        )
        pending = chunk("c1", start=end - 3600, end=end)
        after = deadline + 60
        self.assertFalse(is_eligible(campaign, pending, now_epoch=after))
        self.assertTrue(is_eligible(campaign, pending, now_epoch=deadline - 60))

    def test_completed_campaigns_issue_no_work(self):
        for state in ("complete", "complete_with_gaps"):
            campaign = active_campaign(state=state)
            pending = chunk("c1", start=0, end=100)
            self.assertFalse(is_eligible(campaign, pending, now_epoch=10_000), state)


class LocalDayTests(unittest.TestCase):
    def test_days_are_clipped_to_the_window(self):
        start = int(datetime(2026, 3, 7, 6, 0, tzinfo=NY).timestamp())
        end = int(datetime(2026, 3, 9, 6, 0, tzinfo=NY).timestamp())
        days = covered_local_days(start, end, "America/New_York")
        self.assertEqual(days[0][1] - days[0][0], 18 * 3600)
        self.assertEqual(days[-1][1] - days[-1][0], 6 * 3600)
        self.assertEqual(days[0][0], start)
        self.assertEqual(days[-1][1], end)

    def test_spring_forward_day_is_twenty_three_hours(self):
        start = int(datetime(2026, 3, 7, 0, 0, tzinfo=NY).timestamp())
        end = int(datetime(2026, 3, 9, 0, 0, tzinfo=NY).timestamp())
        days = covered_local_days(start, end, "America/New_York")
        self.assertEqual([high - low for low, high in days], [24 * 3600, 23 * 3600])

    def test_fall_back_day_is_twenty_five_hours(self):
        start = int(datetime(2026, 10, 31, 0, 0, tzinfo=NY).timestamp())
        end = int(datetime(2026, 11, 2, 0, 0, tzinfo=NY).timestamp())
        days = covered_local_days(start, end, "America/New_York")
        self.assertEqual([high - low for low, high in days], [24 * 3600, 25 * 3600])

    def test_unknown_timezone_is_an_error(self):
        with self.assertRaises(ZoneInfoNotFoundError):
            covered_local_days(0, 7200, "Not/AZone")


class CoverageSummaryTests(unittest.TestCase):
    def test_counts_and_derives_settling_from_scheduled(self):
        now = 3650
        chunks = [
            chunk("a", start=0, end=3600, state="scheduled"),  # closed, still settling
            chunk("b", start=3600, end=7200, state="scheduled"),
            chunk("c", start=7200, end=10_800, state="imported"),
            chunk("d", start=10_800, end=14_400, state="failed", attempts=1),
        ]
        summary = coverage_summary(chunks, campaign_start=0, campaign_end=14_400, now_epoch=now)
        self.assertEqual(summary["by_state"]["settling"], 1)
        self.assertEqual(summary["by_state"]["scheduled"], 1)
        self.assertEqual(summary["by_state"]["imported"], 1)
        self.assertEqual(summary["by_state"]["failed"], 1)
        self.assertFalse(summary["fully_resolved"])
        self.assertEqual(summary["unresolved_chunks"], 3)
        self.assertEqual(summary["unresolved_intervals"][0]["state"], "scheduled")

    def test_all_imported_is_fully_resolved(self):
        chunks = [
            chunk("a", start=0, end=3600, state="imported"),
            chunk("b", start=3600, end=7200, state="successful_empty"),
        ]
        summary = coverage_summary(chunks, campaign_start=0, campaign_end=7200, now_epoch=9999)
        self.assertTrue(summary["fully_resolved"])
        self.assertEqual(summary["unresolved_chunks"], 0)

    def test_closed_after_grace_is_ready_not_settling(self):
        chunks = [chunk("a", start=0, end=3600, state="scheduled")]
        summary = coverage_summary(chunks, campaign_start=0, campaign_end=3600, now_epoch=3720)
        self.assertEqual(summary["by_state"]["ready_to_capture"], 1)
        self.assertEqual(summary["by_state"]["settling"], 0)


class FinalizeOutcomeTests(unittest.TestCase):
    def test_complete_only_when_every_window_imported_evidence(self):
        resolved = [
            chunk("a", start=0, end=100, state="imported"),
            chunk("b", start=100, end=200, state="successful_empty"),
        ]
        self.assertEqual(finalize_outcome(resolved), "complete")
        partial = [
            chunk("a", start=0, end=100, state="imported"),
            chunk("b", start=100, end=200, state="failed"),
        ]
        self.assertEqual(finalize_outcome(partial), "complete_with_gaps")
        self.assertEqual(
            finalize_outcome([chunk("a", start=0, end=100, state="partial")]),
            "complete_with_gaps",
        )


class ExtensionTests(unittest.TestCase):
    def test_extension_is_capped_at_one_hundred_twenty_hours_from_start(self):
        start = 1_800_000_000
        end = start + 72 * 3600
        maximum = start + MAX_CAMPAIGN_HOURS * 3600
        extension_allowed(
            active_campaign(start_epoch=start, end_epoch=end), maximum
        )  # exact cap ok
        with self.assertRaises(CampaignError):
            extension_allowed(active_campaign(start_epoch=start, end_epoch=end), maximum + 1)

    def test_extension_must_move_forward(self):
        end = 1_800_000_000 + 72 * 3600
        with self.assertRaises(CampaignError):
            extension_allowed(active_campaign(end_epoch=end), end)


if __name__ == "__main__":
    unittest.main()
