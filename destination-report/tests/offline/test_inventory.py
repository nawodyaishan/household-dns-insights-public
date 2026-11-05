"""Inventory normalization, presence states, manual revisions and strict bindings.

Every fixture here is synthetic. No router, dish, provider or host file is contacted,
and no private poll content is copied into the repository.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from household_report.inventory import (
    GAP,
    LISTED,
    MANAGEMENT_IPS,
    NOT_LISTED,
    InventoryError,
    InventoryService,
    apply_manual_settings,
    attribution_conflicts,
    latest_manual_settings,
    load_poll,
    mac_warnings,
    normalize_client,
    parse_poll,
    presence_timeline,
    resolve_attribution,
)
from household_report.storage import open_store

BASE = 1_792_728_000  # 2026-10-23 04:00:00 UTC


def client(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name": "device-a",
        "macAddress": "aa:bb:cc:dd:ee:01",
        "ipAddress": "192.168.1.23",
        "iface": "RF_5GHZ",
        "role": "CLIENT",
    }
    entry.update(overrides)
    return entry


def envelope(
    clients: list[dict[str, object]],
    *,
    start: str,
    returncode: int = 0,
) -> dict[str, object]:
    body = {
        "apiVersion": 133,
        "wifiGetClients": {"clients": clients, "hasClientIndex": False, "clientIndex": 0},
    }
    return {
        "start": start,
        "end": start,
        "endpoint": "dish",
        "tail": [],
        "returncode": returncode,
        "stdout": json.dumps(body) if returncode == 0 else "",
        "stderr": "" if returncode == 0 else "collector failed",
    }


def stored_poll(
    *, polled_utc: str, ok: bool, clients: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "polled_utc": polled_utc,
        "ok": ok,
        "observations": [normalize_client(item) for item in clients or []],
    }


def temp_file(directory: str, name: str, payload: dict[str, object]) -> Path:
    path = Path(directory) / name
    path.write_text(json.dumps(payload))
    return path


class NormalizationTests(unittest.TestCase):
    def test_proto3_omitted_booleans_are_unknown_not_false(self):
        observation = normalize_client(client())
        self.assertIsNone(observation.active)
        self.assertIsNone(observation.dhcp_lease_found)
        self.assertIsNone(observation.dhcp_lease_active)
        self.assertIsNone(observation.lease_expires_s)

    def test_present_booleans_and_integers_are_kept(self):
        observation = normalize_client(
            client(active=False, dhcpLeaseFound=True, associatedTimeS=420, snr=31)
        )
        self.assertIs(observation.active, False)
        self.assertIs(observation.dhcp_lease_found, True)
        self.assertEqual(observation.associated_time_s, 420)
        self.assertEqual(observation.snr, 31)

    def test_every_reported_field_is_preserved_verbatim(self):
        raw = client(
            givenName="Kitchen",
            deviceId="d-1",
            clientId="c-1",
            ipv6Addresses=["fd00::1"],
            upstreamMacAddress="aa:bb:cc:dd:ee:99",
            domains=["x.example"],
        )
        observation = normalize_client(raw)
        self.assertEqual(observation.raw, raw)
        self.assertEqual(observation.label, "Kitchen")
        self.assertEqual(observation.device_key, "mac:aa:bb:cc:dd:ee:01")

    def test_randomized_and_malformed_macs_are_flagged(self):
        self.assertTrue(
            any("locally administered" in warning for warning in mac_warnings("02:11:22:33:44:55"))
        )
        self.assertTrue(mac_warnings("not-a-mac"))
        self.assertTrue(mac_warnings("00:00:00:00:00:00"))
        self.assertEqual(mac_warnings("00:bb:cc:dd:ee:01"), [])

    def test_identity_falls_back_without_inventing_uniqueness(self):
        observation = normalize_client({"clientId": "c-1", "role": "CLIENT"})
        self.assertEqual(observation.device_key, "client:c-1")
        anonymous = normalize_client({"role": "CLIENT"})
        self.assertTrue(anonymous.device_key.startswith("hash:"))

    def test_non_mapping_client_is_rejected(self):
        with self.assertRaises(InventoryError):
            normalize_client("not-an-object")  # type: ignore[arg-type]


class PollParsingTests(unittest.TestCase):
    def test_envelope_becomes_one_ordered_poll(self):
        poll = parse_poll(
            envelope(
                [client(), client(macAddress="aa:bb:cc:dd:ee:02", name="b")],
                start="2026-10-23T04:00:00+00:00",
            ),
            source="presence-00.json",
        )
        self.assertTrue(poll.ok)
        self.assertEqual(poll.polled_utc, "2026-10-23T04:00:00Z")
        self.assertEqual(len(poll.observations), 2)
        self.assertFalse(any(observation.is_infrastructure for observation in poll.observations))

    def test_failed_poll_is_a_gap_without_clients(self):
        payload = envelope([], start="2026-10-23T04:00:15+00:00", returncode=3)
        poll = parse_poll(payload, source="presence-01.json")
        self.assertFalse(poll.ok)
        self.assertIn("3", poll.error or "")
        self.assertEqual(poll.observations, ())

    def test_malformed_body_is_rejected(self):
        with self.assertRaises(InventoryError):
            parse_poll(
                {
                    "stdout": "{",
                    "start": "2026-10-23T04:00:00Z",
                    "end": "2026-10-23T04:00:01Z",
                    "returncode": 0,
                },
                source="x",
            )
        with self.assertRaises(InventoryError):
            parse_poll(
                {
                    "start": "2026-10-23T04:00:00Z",
                    "end": "2026-10-23T04:00:01Z",
                    "returncode": 0,
                    "stdout": "{}",
                },
                source="x",
            )

    def test_duplicate_device_in_one_poll_is_rejected(self):
        with self.assertRaises(InventoryError):
            parse_poll(envelope([client(), client()], start="2026-10-23T04:00:00Z"), source="x")

    def test_duplicate_identical_polls_share_a_digest(self):
        payload = envelope([client()], start="2026-10-23T04:00:00Z")
        self.assertEqual(
            parse_poll(payload, source="a").digest, parse_poll(payload, source="b").digest
        )

    def test_load_poll_reads_a_local_file_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = temp_file(
                directory, "presence-00.json", envelope([client()], start="2026-10-23T04:00:00Z")
            )
            poll = load_poll(path)
        self.assertEqual(poll.source, "presence-00.json")
        with self.assertRaises(InventoryError):
            load_poll("/nonexistent/presence.json")


class PresenceTests(unittest.TestCase):
    def polls(self):
        return [
            stored_poll(
                polled_utc="2026-10-23T04:00:00Z",
                ok=True,
                clients=[client()],
            ),
            stored_poll(
                polled_utc="2026-10-23T04:00:15Z",
                ok=True,
                clients=[client(), client(macAddress="aa:bb:cc:dd:ee:02", name="b")],
            ),
            stored_poll(polled_utc="2026-10-23T04:00:30Z", ok=False),
            stored_poll(
                polled_utc="2026-10-23T04:00:45Z",
                ok=True,
                clients=[client(macAddress="aa:bb:cc:dd:ee:02", name="b")],
            ),
        ]

    def test_states_are_listed_missing_or_gap_and_nothing_else(self):
        timeline = presence_timeline(self.polls())
        by_key = {view["device_key"]: view for view in timeline["devices"]}
        first = by_key["mac:aa:bb:cc:dd:ee:01"]
        second = by_key["mac:aa:bb:cc:dd:ee:02"]
        self.assertEqual(
            [segment["state"] for segment in first["segments"]], [LISTED, GAP, NOT_LISTED]
        )
        self.assertEqual(
            [segment["state"] for segment in second["segments"]], [NOT_LISTED, LISTED, GAP, LISTED]
        )
        self.assertEqual(first["state"], NOT_LISTED)
        self.assertEqual(second["state"], LISTED)
        self.assertEqual(len(timeline["gaps"]), 1)
        self.assertEqual(timeline["gaps"][0]["start_utc"], "2026-10-23T04:00:30Z")

    def test_presence_never_claims_offline_uptime_or_activity(self):
        timeline = presence_timeline(self.polls())
        text = json.dumps(
            {
                "devices": timeline["devices"],
                "notes": timeline["notes"],
                "gaps": timeline["gaps"],
            }
        ).lower()
        for forbidden in ('"state": "offline"', "disconnected", "user activity", "was asleep"):
            self.assertNotIn(forbidden, text)
        self.assertIn("not proof", " ".join(timeline["notes"]))
        self.assertIn("not os uptime", " ".join(timeline["notes"]).lower())

    def test_controller_is_infrastructure_not_a_household_client(self):
        polls = [
            stored_poll(
                polled_utc="2026-10-23T04:00:00Z",
                ok=True,
                clients=[client(role="CONTROLLER", name="router", macAddress="aa:bb:cc:dd:ee:09")],
            )
        ]
        timeline = presence_timeline(polls)
        self.assertEqual(timeline["devices"], [])
        self.assertEqual(len(timeline["infrastructure"]), 1)
        self.assertEqual(timeline["infrastructure"][0]["role"], "CONTROLLER")

    def test_unknown_role_is_flagged(self):
        timeline = presence_timeline(
            [
                stored_poll(
                    polled_utc="2026-10-23T04:00:00Z", ok=True, clients=[client(role="UNKNOWN")]
                )
            ]
        )
        warnings = timeline["devices"][0]["warnings"]
        self.assertTrue(any("role was not reported" in warning for warning in warnings))

    def test_a_device_absent_from_every_poll_is_unobserved(self):
        timeline = presence_timeline([stored_poll(polled_utc="2026-10-23T04:00:00Z", ok=False)])
        self.assertEqual(timeline["devices"], [])
        self.assertEqual(timeline["polls"]["failed"], 1)


class ManualRevisionTests(unittest.TestCase):
    def test_supersede_chain_wins_and_stale_branches_are_ignored(self):
        revisions = [
            {
                "revision_id": 1,
                "device_key": "k",
                "display_name": "One",
                "category": None,
                "supersedes": None,
            },
            {
                "revision_id": 2,
                "device_key": "k",
                "display_name": "Two",
                "category": "phone",
                "supersedes": 1,
            },
            {
                "revision_id": 3,
                "device_key": "k",
                "display_name": "Stale",
                "category": None,
                "supersedes": 1,
            },
        ]
        latest = latest_manual_settings(revisions)["k"]
        self.assertEqual(latest["revision_id"], 2)
        self.assertEqual(latest["display_name"], "Two")

    def test_manual_overlay_never_rewrites_the_observed_label(self):
        view = {"device_key": "k", "label": "observed-name", "state": LISTED}
        enriched = apply_manual_settings(
            view, {"revision_id": 4, "display_name": "Kitchen", "category": "tv"}
        )
        self.assertEqual(enriched["display_name"], "Kitchen")
        self.assertEqual(enriched["observed_label"], "observed-name")
        self.assertEqual(enriched["category_source"], "manual")
        plain = apply_manual_settings(view, None)
        self.assertEqual(plain["display_name"], "observed-name")
        self.assertEqual(plain["category"], "unknown")


class AttributionTests(unittest.TestCase):
    def row(self, row_id: object, client_ip: str, moment: float) -> dict[str, object]:
        return {"id": row_id, "client": client_ip, "timestamp": moment, "domain": "x.example"}

    def binding(self, key: str, ip: str, start: str, end: str | None = None) -> dict[str, object]:
        return {
            "binding_id": 1,
            "device_key": key,
            "observed_ip": ip,
            "valid_from_utc": start,
            "valid_to_utc": end,
        }

    def test_attribution_needs_a_time_valid_binding(self):
        rows = [self.row(1, "192.168.1.23", BASE + 10)]
        self.assertEqual(resolve_attribution(rows, []), {})
        later = [self.binding("mac:a", "192.168.1.23", "2026-10-23T05:00:00Z")]
        self.assertEqual(resolve_attribution(rows, later), {})
        valid = [self.binding("mac:a", "192.168.1.23", "2026-10-23T03:00:00Z")]
        self.assertEqual(resolve_attribution(rows, valid), {1: "mac:a"})

    def test_expired_binding_does_not_attribute_new_rows(self):
        rows = [self.row(1, "192.168.1.23", BASE + 3600)]
        expired = [
            self.binding("mac:a", "192.168.1.23", "2026-10-23T03:00:00Z", "2026-10-23T04:30:00Z")
        ]
        self.assertEqual(resolve_attribution(rows, expired), {})

    def test_conflicting_bindings_leave_rows_unattributed(self):
        rows = [self.row(1, "192.168.1.23", BASE + 60)]
        bindings = [
            self.binding("mac:a", "192.168.1.23", "2026-10-23T03:00:00Z"),
            self.binding("mac:b", "192.168.1.23", "2026-10-23T04:00:00Z"),
        ]
        self.assertEqual(resolve_attribution(rows, bindings), {})
        conflicts = attribution_conflicts(bindings)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("overlapping", conflicts[0]["reason"])

    def test_mac_only_binding_never_matches_an_ip_row(self):
        rows = [self.row(1, "192.168.1.23", BASE + 60)]
        bindings = [
            {
                "binding_id": 1,
                "device_key": "mac:a",
                "observed_ip": None,
                "observed_mac": "aa:bb:cc:dd:ee:01",
                "valid_from_utc": "2026-10-23T03:00:00Z",
                "valid_to_utc": None,
            }
        ]
        self.assertEqual(resolve_attribution(rows, bindings), {})

    def test_router_and_dish_addresses_stay_unattributed(self):
        rows = [self.row(1, address, BASE + 60) for address in sorted(MANAGEMENT_IPS)]
        bindings = [
            self.binding("mac:router", address, "2026-10-23T03:00:00Z")
            for address in sorted(MANAGEMENT_IPS)
        ]
        self.assertEqual(resolve_attribution(rows, bindings), {})

    def test_invalid_binding_interval_is_rejected(self):
        with self.assertRaises(InventoryError):
            resolve_attribution(
                [self.row(1, "192.168.1.23", BASE + 60)],
                [
                    self.binding(
                        "mac:a",
                        "192.168.1.23",
                        "2026-10-23T05:00:00Z",
                        "2026-10-23T04:00:00Z",
                    )
                ],
            )


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = open_store(Path(self.directory.name) / "app.sqlite3")
        self.addCleanup(self.store.close)
        self.service = InventoryService(self.store)

    def test_import_is_idempotent_and_keeps_failed_polls(self):
        path = temp_file(
            self.directory.name,
            "presence-00.json",
            envelope([client()], start="2026-10-23T04:00:00Z"),
        )
        first = self.service.import_poll_file(path)
        second = self.service.import_poll_file(path)
        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(len(self.service.polls()), 1)
        failed = temp_file(
            self.directory.name,
            "presence-01.json",
            envelope([client()], start="2026-10-23T04:00:15Z", returncode=2),
        )
        self.service.import_poll_file(failed)
        polls = self.service.polls()
        self.assertEqual([poll["ok"] for poll in polls], [True, False])

    def test_manual_edits_are_audited_superseding_and_reversible(self):
        path = temp_file(
            self.directory.name,
            "presence-00.json",
            envelope([client()], start="2026-10-23T04:00:00Z"),
        )
        self.service.import_poll_file(path)
        key = "mac:aa:bb:cc:dd:ee:01"
        self.service.edit_device(key, display_name="Kitchen", category="tv")
        self.service.edit_device(key, display_name="Kitchen TV", category="tv")
        revisions = self.store.device_settings()
        self.assertEqual(len(revisions), 2)
        self.assertEqual(revisions[1]["supersedes"], revisions[0]["revision_id"])
        view = self.service.devices()["devices"][0]
        self.assertEqual(view["display_name"], "Kitchen TV")
        self.assertEqual(view["observed_label"], "device-a")
        self.service.edit_device(key, display_name=None, category=None)
        restored = self.service.devices()["devices"][0]
        self.assertEqual(restored["display_name"], "device-a")
        self.assertEqual(restored["category"], "unknown")
        self.assertEqual(len(self.store.device_settings()), 3)

    def test_unknown_device_and_category_are_rejected(self):
        with self.assertRaises(InventoryError):
            self.service.edit_device("mac:nope", display_name="x", category=None)
        path = temp_file(
            self.directory.name,
            "presence-00.json",
            envelope([client()], start="2026-10-23T04:00:00Z"),
        )
        self.service.import_poll_file(path)
        with self.assertRaises(InventoryError):
            self.service.edit_device("mac:aa:bb:cc:dd:ee:01", display_name="x", category="toaster")

    def test_service_never_attributes_from_the_current_poll_alone(self):
        path = temp_file(
            self.directory.name,
            "presence-00.json",
            envelope([client()], start="2026-10-23T04:00:00Z"),
        )
        self.service.import_poll_file(path)
        rows = [{"id": 1, "client": "192.168.1.23", "timestamp": BASE + 30}]
        self.assertEqual(self.service.attributions(rows), {})


if __name__ == "__main__":
    unittest.main()
