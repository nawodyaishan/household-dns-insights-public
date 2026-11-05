"""Offline regression tests for collector heartbeat health."""

import unittest

from household_report.collector_status import classify_status, mark_attempt, mark_running


def _record(**overrides):
    base = mark_attempt(
        None,
        now_epoch=1000,
        start_epoch=1000,
        end_epoch=1000,
        code="ok",
        stage="bridge",
        running=False,
        failure=False,
        last_success_fields={"bridge_epoch": 1000},
    )
    base.update(overrides)
    return base


class CollectorHeartbeatTests(unittest.TestCase):
    def test_missing_status_is_unavailable_not_healthy(self):
        self.assertEqual(classify_status(None, now_epoch=1000)["state"], "unavailable")

    def test_no_active_campaign_is_distinct(self):
        record = _record()
        self.assertEqual(classify_status(record, now_epoch=1000)["state"], "no_campaign")

    def test_completed_campaign_is_historical_not_failed(self):
        record = _record()
        self.assertEqual(
            classify_status(record, now_epoch=1000, campaign_state="complete")["state"],
            "historical",
        )

    def test_waiting_is_not_stale_when_no_work_is_due(self):
        record = _record(pending_eligible=0)
        self.assertEqual(
            classify_status(record, now_epoch=1000, campaign_state="active")["state"], "waiting"
        )

    def test_successful_empty_is_not_a_gap(self):
        record = _record(pending_eligible=0)
        result = classify_status(
            record, now_epoch=1000, campaign_state="active", coverage={"successful_empty": 3}
        )
        self.assertEqual(result["state"], "successful_empty")

    def test_partial_and_expired_are_distinct(self):
        record = _record(pending_eligible=0)
        partial = classify_status(
            record,
            now_epoch=1000,
            campaign_state="active",
            coverage={"partial": 1, "imported": 2},
        )
        self.assertEqual(partial["state"], "partial")
        expired = classify_status(
            record,
            now_epoch=1000,
            campaign_state="active",
            coverage={"expired": 1, "imported": 2},
        )
        self.assertEqual(expired["state"], "expired")

    def test_latched_identity_is_visible(self):
        record = _record(consecutive_failures=1, latched_fingerprint="abc")
        self.assertEqual(classify_status(record, now_epoch=1000)["state"], "latched")

    def test_capture_failure_keeps_prior_success(self):
        record = mark_attempt(
            _record(),
            now_epoch=1100,
            start_epoch=1000,
            end_epoch=1100,
            code="capture_failed",
            stage="capture",
            running=False,
            failure=True,
        )
        self.assertEqual(record["last_success"]["bridge_epoch"], 1000)
        self.assertEqual(classify_status(record, now_epoch=1100)["state"], "failed")

    def test_work_does_not_become_overdue_until_900_seconds_after_eligibility(self):
        record = mark_attempt(
            None,
            now_epoch=1000,
            start_epoch=1000,
            end_epoch=1000,
            code="ok",
            stage="bridge",
            running=False,
            failure=False,
            pending_eligible=1,
        )
        record["eligible_since_epoch"] = 1000
        record["updated_epoch"] = 1900
        self.assertNotEqual(
            classify_status(record, now_epoch=1900, campaign_state="active")["state"], "overdue"
        )
        record["updated_epoch"] = 1901
        self.assertEqual(
            classify_status(record, now_epoch=1901, campaign_state="active")["state"], "overdue"
        )

    def test_running_tick_becomes_stale_when_heartbeat_expires(self):
        record = mark_running(None, now_epoch=1000)
        self.assertEqual(classify_status(record, now_epoch=1720)["state"], "running")
        self.assertEqual(classify_status(record, now_epoch=1721)["state"], "stale_heartbeat")

    def test_failed_tick_also_becomes_stale_when_bridge_stops(self):
        record = mark_attempt(
            None,
            now_epoch=1000,
            start_epoch=1000,
            end_epoch=1000,
            code="capture_failed",
            stage="capture",
            running=False,
            failure=True,
        )
        self.assertEqual(classify_status(record, now_epoch=1001)["state"], "failed")
        self.assertEqual(classify_status(record, now_epoch=1721)["state"], "stale_heartbeat")


if __name__ == "__main__":
    unittest.main()
