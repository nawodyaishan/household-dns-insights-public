"""Typed stack driver: fresh and legacy walkthrough, boundaries, no hidden effects."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from household_report.maintenance import MaintenanceError, MaintenanceJournal, verify_backup
from household_report.release import ReleaseManifest, bundle_digest, parse_manifest
from household_report.storage import SCHEMA_VERSION, open_store

TOOLS = Path(__file__).resolve().parents[2] / "tools"
IMAGE_A = "sha256:" + "a" * 64
IMAGE_B = "sha256:" + "b" * 64
SOURCE_A = "a" * 40
SOURCE_B = "b" * 40
PS_LINE = json.dumps({"Name": "app", "State": "running", "Status": "Up 1 second"})


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(f"test_{name}", TOOLS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stack = load_module("stack_cli")
release_manifest_tool = load_module("release_manifest")


class FakeRunner:
    """Records every external effect; fails only when explicitly told to."""

    def __init__(self, *, fail_on=(), ps_output: str = PS_LINE):
        self.calls: list[dict[str, object]] = []
        self.fail_on = fail_on
        self.ps_output = ps_output

    def __call__(self, argv, *, capture_output, text, timeout, env):
        self.calls.append({"argv": list(argv), "env": dict(env)})

        class Result:
            returncode = 1 if any(token in argv for token in self.fail_on) else 0
            stdout = (
                self.ps_output if argv[:3] == ["docker", "compose", "-p"] and "ps" in argv else ""
            )
            stderr = ""

        return Result()

    def argv(self) -> list[list[str]]:
        return [list(call["argv"]) for call in self.calls]


def private(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_operator_config(
    root: Path, *, image_id: str = IMAGE_A, schema: int | None = None
) -> Path:
    config_dir = private(root / "config")
    input_dir = private(root / "input")
    state_dir = private(root / "state")
    bridge_dir = private(root / "units")
    campaign_dir = private(root / "campaign")
    (config_dir / "tls").mkdir(mode=0o700)
    document = {
        "version": 1,
        "network": {
            "vm_bind": "10.10.10.20",
            "vm_port": 8787,
            "relay_ip": "192.168.1.10",
            "relay_port": 8787,
            "owner_port": 8789,
            "timezone": "UTC",
        },
        "paths": {
            "config_dir": str(config_dir),
            "input_dir": str(input_dir),
            "state_dir": str(state_dir),
            "bridge_dir": str(bridge_dir),
            "campaign_config_dir": str(campaign_dir),
        },
        "bridge": {
            "python": str(root / "venv" / "bin" / "python"),
            "compose": str(root / "app" / "compose.yaml"),
            "docker": str(root / "bin" / "docker"),
            "container": "pihole",
            "database": "/etc/pihole/pihole-FTL.db",
            "generation": "gen-1",
            "identity": "synthetic-identity",
            "config_dir": str(config_dir),
            "state_dir": str(state_dir),
            "input_dir": str(input_dir),
        },
        "release": {
            "image_id": image_id,
            "source_revision": SOURCE_A,
            "schema_version": SCHEMA_VERSION if schema is None else schema,
            "host_bundle_hash": bundle_digest(release_manifest_tool.host_bundle()),
            "base_image_digest": "sha256:" + "c" * 64,
        },
        "ai_enabled": False,
        "campaign_profile": False,
        "shared_control": False,
    }
    path = config_dir / "operator.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    return path


def write_target_manifest(
    root: Path, *, image_id: str = IMAGE_B, schema: int | None = None
) -> Path:
    manifest = ReleaseManifest(
        image_id=image_id,
        source_revision=SOURCE_B,
        schema_version=SCHEMA_VERSION if schema is None else schema,
        lock_sha256="d" * 64,
        base_image_digest="sha256:" + "e" * 64,
        host_bundle_sha256="f" * 64,
        built_utc="2026-11-02T00:00:00Z",
    )
    path = root / "target-manifest.json"
    path.write_text(
        json.dumps(
            {
                "manifest_schema": 1,
                "image_id": manifest.image_id,
                "source_revision": manifest.source_revision,
                "schema_version": manifest.schema_version,
                "lock_sha256": manifest.lock_sha256,
                "base_image_digest": manifest.base_image_digest,
                "host_bundle_sha256": manifest.host_bundle_sha256,
                "built_utc": manifest.built_utc,
            }
        )
    )
    return path


class FreshStackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = write_operator_config(self.root)
        self.state_dir = self.root / "state"
        self.runner = FakeRunner()

    def driver(self, **kwargs):
        return stack.StackDriver(config=self.config, env={}, runner=self.runner, **kwargs)

    # -- setup --------------------------------------------------------------
    def test_setup_prepares_private_paths_and_units_with_zero_external_effects(self):
        result = self.driver().setup(user="testop")
        for name in ("config", "input", "state", "units"):
            mode = stat.S_IMODE((self.root / name).stat().st_mode)
            self.assertEqual(mode, 0o700, name)
        bridge_json = self.root / "units" / "campaign-bridge.json"
        self.assertEqual(stat.S_IMODE(bridge_json.stat().st_mode), 0o600)
        service = (self.root / "units" / "household-campaign-bridge.service").read_text()
        self.assertIn("User=testop", service)
        self.assertFalse((self.root / "units" / "household-campaign-bridge.service").is_symlink())
        self.assertTrue((self.state_dir / "stack-prepared.json").exists())
        self.assertEqual(self.runner.calls, [])
        self.assertIn("no install", result["effects"])
        self.assertEqual(result["build"], "not-requested")

    def test_setup_refuses_root_account_and_unlisted_build_is_opt_in(self):
        with self.assertRaises(stack.StackError):
            self.driver().setup(user="root")
        self.assertEqual(self.runner.calls, [])
        result = self.driver().setup(user="testop", build=True)
        self.assertEqual(result["build"], "requested")
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.argv()[0][:2], ["docker", "build"])

    def test_setup_refuses_contradictory_mixed_config_and_legacy_env(self):
        with self.assertRaises(stack.StackError) as caught:
            stack.StackDriver(config=self.config, env={"HR_DATABASE": "/tmp/x"}, runner=self.runner)
        self.assertIn("mixed path", str(caught.exception))

    def test_setup_refuses_silently_rebinding_an_existing_bridge_identity(self):
        self.driver().setup(user="testop")
        bridge_json = self.root / "units" / "campaign-bridge.json"
        document = json.loads(bridge_json.read_text())
        document["generation"] = "gen-2"
        bridge_json.write_text(json.dumps(document))
        with self.assertRaises(stack.StackError):
            self.driver().setup(user="testop")

    def test_start_refuses_after_the_configuration_changes(self):
        self.driver().setup(user="testop")
        document = json.loads(self.config.read_text())
        document["network"]["vm_port"] = 8788
        self.config.write_text(json.dumps(document))
        changed = stack.StackDriver(config=self.config, env={}, runner=self.runner)
        with self.assertRaises(stack.StackError) as caught:
            changed.start()
        self.assertIn("changed since setup", str(caught.exception))
        self.assertEqual(self.runner.calls, [])

    # -- check --------------------------------------------------------------
    def test_check_offline_verifies_release_and_makes_no_external_call(self):
        self.driver().setup(user="testop")
        result = self.driver().check()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "offline")
        self.assertEqual(result["release"]["host_bundle"], "verified")
        self.assertFalse(result["journal_active"])
        self.assertEqual(self.runner.calls, [])

    def test_check_offline_flags_missing_prepared_state_and_live_reads_only_runtime(self):
        result = self.driver().check()
        self.assertFalse(result["ok"])
        self.assertTrue(any("setup" in issue for issue in result["issues"]))
        self.assertEqual(self.runner.calls, [])
        self.driver().setup(user="testop")
        live = self.driver().check(live=True)
        self.assertTrue(live["ok"])
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.argv()[0][:3], ["docker", "compose", "-p"])
        self.assertEqual(live["runtime"]["containers"][0]["state"], "running")

    # -- start / stop / restart / status ------------------------------------
    def test_start_never_starts_a_campaign_and_neutralizes_ambient_compose_vars(self):
        with self.assertRaises(stack.StackError):
            self.driver().start()
        self.driver().setup(user="testop")
        with patch.dict(os.environ, {"COMPOSE_FILE": "/tmp/hostile.yaml"}):
            result = self.driver().start()
        self.assertEqual(self.runner.argv()[0][:3], ["docker", "image", "inspect"])
        self.assertEqual(self.runner.argv()[1][:2], ["docker", "tag"])
        argv = self.runner.argv()[2]
        self.assertEqual(argv[-2:], ["up", "-d"])
        self.assertNotIn("COMPOSE_FILE", self.runner.calls[2]["env"])
        self.assertEqual(self.runner.calls[2]["env"]["HR_STATE_DIR"], str(self.state_dir))
        self.assertEqual(result["campaign"], "not-started")
        self.assertEqual(result["network"], "unchanged")
        self.assertEqual(result["spend"], "disabled")

    def test_start_runs_the_selected_release_image_not_the_mutable_tag(self):
        """R03: the inspected immutable image must be the one Compose starts."""
        self.driver().setup(user="testop")
        self.driver().start()
        override = self.state_dir / "stack-image-override.yaml"
        self.assertTrue(override.is_file())
        self.assertEqual(override.stat().st_mode & 0o777, 0o600)
        expected_tag = "household-report:stack-" + SOURCE_A[:12]
        self.assertIn(f"image: {expected_tag}", override.read_text())
        # The selected image ID is tagged into the versioned tag, and that
        # override is the last Compose file used for the start.
        self.assertEqual(self.runner.argv()[1][:3], ["docker", "tag", IMAGE_A])
        self.assertEqual(self.runner.argv()[1][3], expected_tag)
        self.assertIn(str(override), self.runner.argv()[2])
        self.assertNotIn("household-report:local", override.read_text())

    def test_stop_requires_confirmation_and_stops_bridge_before_applications(self):
        self.driver().setup(user="testop")
        with self.assertRaises(stack.StackError):
            self.driver().stop()
        self.assertEqual(self.runner.calls, [])
        result = self.driver().stop(confirm="stop")
        argv = self.runner.argv()
        self.assertEqual(argv[0][:2], ["systemctl", "stop"])
        self.assertEqual(argv[1][-1], "stop")
        self.assertEqual(result["data"], "retained")
        self.assertEqual(result["dns"], "untouched")

    def test_restart_confirms_then_runs_stop_before_start(self):
        self.driver().setup(user="testop")
        with self.assertRaises(stack.StackError):
            self.driver().restart()
        self.driver().restart(confirm="restart")
        kinds = [(call["argv"][0], call["argv"][-1]) for call in self.runner.calls]
        self.assertEqual(
            kinds,
            [
                ("systemctl", "household-campaign-bridge.service"),
                ("docker", "stop"),
                ("docker", IMAGE_A),
                ("docker", "household-report:stack-" + SOURCE_A[:12]),
                ("docker", "-d"),
            ],
        )

    def test_status_offline_is_sanitized_and_never_migrates(self):
        self.driver().setup(user="testop")
        result = self.driver().status(live=False)
        encoded = json.dumps(result)
        self.assertNotIn("domain", encoded)
        self.assertNotIn("identity", encoded)
        self.assertIsNone(result["schema_version"])
        self.assertEqual(result["campaigns"], [])
        self.assertEqual(result["external_calls"], "none")
        self.assertEqual(self.runner.calls, [])
        # Opening a missing database in status must not create or migrate one.
        self.assertFalse((self.state_dir / "app.sqlite3").exists())

    def test_status_reports_schema_and_campaign_states_without_household_rows(self):
        self.driver().setup(user="testop")
        store = open_store(self.state_dir / "app.sqlite3")
        store.close()
        result = self.driver().status(live=False)
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        self.assertEqual(result["campaigns"], [])

    # -- upgrade / rollback ---------------------------------------------------
    def test_upgrade_runs_the_ordered_transaction_and_completes(self):
        self.driver().setup(user="testop")
        target = write_target_manifest(self.root)
        archive = self.root / "archive"
        result = self.driver().upgrade(release=target, archive=archive, confirm="upgrade")
        argv = self.runner.argv()
        self.assertEqual(argv[0][:2], ["systemctl", "stop"])
        self.assertEqual(argv[1][-1], "stop")
        self.assertEqual(argv[2][:2], ["docker", "tag"])
        self.assertEqual(argv[2][2], IMAGE_B)
        self.assertEqual(argv[3][-3:], ["up", "-d", "--force-recreate"])
        self.assertEqual(argv[4][-1], "json")
        self.assertEqual(result["journal"], "complete")
        journal = MaintenanceJournal(self.state_dir).load()
        self.assertFalse(journal["active"])
        self.assertEqual(journal["completed"], list(stack.STAGE_ORDER))
        verify_backup(archive)
        prepared = json.loads((self.state_dir / "stack-prepared.json").read_text())
        # The driver never rewrites the owner's config, so the recorded release
        # stays the configured one; the result tells the operator what to do next.
        self.assertEqual(prepared["image_id"], IMAGE_A)
        self.assertEqual(prepared["build"], "unchanged")
        self.assertIn("operator config release", result["next"])

    def test_upgrade_refuses_newer_schema_and_tag_identity_before_any_effect(self):
        self.driver().setup(user="testop")
        newer = write_target_manifest(self.root, schema=SCHEMA_VERSION + 1)
        with self.assertRaises((stack.StackError, MaintenanceError)):
            self.driver().upgrade(release=newer, confirm="upgrade")
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(MaintenanceJournal(self.state_dir).load()["active"])

        tagged = write_operator_config(self.root / "tagged", image_id="household-report:local")
        tagged_driver = stack.StackDriver(config=tagged, env={}, runner=self.runner)
        with self.assertRaises(stack.StackError):
            tagged_driver.upgrade(release=write_target_manifest(self.root), confirm="upgrade")
        self.assertEqual(self.runner.calls, [])

    def test_upgrade_refuses_rollback_to_an_older_schema_and_points_to_restore(self):
        self.driver().setup(user="testop")
        older = write_target_manifest(self.root, schema=SCHEMA_VERSION - 1)
        with self.assertRaises(stack.StackError) as caught:
            self.driver().rollback(release=older, confirm="rollback")
        self.assertIn("isolated restore", str(caught.exception))
        self.assertEqual(self.runner.calls, [])

    def test_interrupted_transaction_resumes_without_repeating_completed_stages(self):
        self.driver().setup(user="testop")
        target = write_target_manifest(self.root)
        failing = FakeRunner(fail_on=("stop",))
        driver = stack.StackDriver(config=self.config, env={}, runner=failing)
        with self.assertRaises(stack.StackError) as caught:
            driver.upgrade(release=target, archive=self.root / "archive", confirm="upgrade")
        self.assertIn("resume", str(caught.exception))
        journal = MaintenanceJournal(self.state_dir).load()
        self.assertTrue(journal["active"])
        self.assertEqual(journal["completed"][:2], ["stop-bridge", "stop-writers"])

        healthy = stack.StackDriver(config=self.config, env={}, runner=self.runner)
        result = healthy.upgrade(
            release=target, archive=self.root / "archive", confirm="upgrade", resume=True
        )
        self.assertEqual(result["journal"], "complete")
        resumed_kinds = [call["argv"][:2] for call in self.runner.calls]
        self.assertEqual(
            resumed_kinds,
            [["docker", "tag"], ["docker", "compose"], ["docker", "compose"]],
        )

    def test_active_transaction_blocks_a_different_target_and_standalone_backup(self):
        self.driver().setup(user="testop")
        target = write_target_manifest(self.root)
        journal = MaintenanceJournal(self.state_dir)
        journal.begin(target_image_id=IMAGE_B)
        with self.assertRaises(stack.StackError):
            self.driver().upgrade(release=target, confirm="upgrade")
        with self.assertRaises(stack.StackError):
            self.driver().backup(archive=self.root / "archive", confirm="backup")
        journal.reset()

    def test_rollback_switches_back_to_a_preserved_release(self):
        self.driver().setup(user="testop")
        # Current configured release is IMAGE_A; rolling back to a preserved
        # equal-schema IMAGE_B manifest passes guards and runs the transaction.
        prior = write_target_manifest(self.root, image_id=IMAGE_B)
        result = self.driver().rollback(
            release=prior, archive=self.root / "archive", confirm="rollback"
        )
        self.assertEqual(result["command"], "rollback")
        self.assertEqual(result["journal"], "complete")
        self.assertEqual(self.runner.argv()[2][2], IMAGE_B)

    # -- backup / restore / uninstall / journal ------------------------------
    def test_backup_quiesces_and_creates_a_verified_archive(self):
        self.driver().setup(user="testop")
        archive = self.root / "archive"
        result = self.driver().backup(archive=archive, confirm="backup")
        self.assertEqual(result["command"], "backup")
        verify_backup(archive)
        self.assertEqual(MaintenanceJournal(self.state_dir).load()["active"], False)

    def test_restore_is_isolated_only_and_refuses_nonempty_or_permissive_destinations(self):
        self.driver().setup(user="testop")
        archive = self.root / "archive"
        self.driver().backup(archive=archive, confirm="backup")
        dest = private(self.root / "restored")
        result = self.driver().restore(archive=archive, dest=dest, confirm="restore")
        self.assertEqual(result["mode"], "isolation")
        self.assertIn("separate explicit owner operation", result["promotion"])
        self.assertTrue((dest / "app.sqlite3").exists())
        with self.assertRaises((stack.StackError, MaintenanceError)):
            self.driver().restore(archive=archive, dest=dest, confirm="restore")
        permissive = self.root / "permissive"
        permissive.mkdir(mode=0o755)
        with self.assertRaises((stack.StackError, MaintenanceError)):
            self.driver().restore(archive=archive, dest=permissive, confirm="restore")

    def test_uninstall_previews_then_removes_only_owned_publication(self):
        self.driver().setup(user="testop")
        preview = self.driver().uninstall()
        self.assertFalse(preview["confirmed"])
        self.assertEqual(self.runner.calls, [])
        self.assertTrue((self.root / "units" / "household-campaign-bridge.service").exists())
        result = self.driver().uninstall(confirm="uninstall")
        self.assertTrue(result["confirmed"])
        self.assertEqual(self.runner.argv()[0][:2], ["systemctl", "disable"])
        self.assertEqual(self.runner.argv()[1][-1], "down")
        self.assertFalse((self.root / "units" / "household-campaign-bridge.service").exists())
        # Evidence and configuration are retained.
        self.assertTrue((self.state_dir / "stack-prepared.json").exists())
        self.assertTrue((self.root / "units" / "campaign-bridge.json").exists())
        self.assertTrue((self.root / "input").exists())

    def test_journal_status_and_gated_reset(self):
        journal = MaintenanceJournal(self.state_dir)
        status = self.driver().journal(action="status")
        self.assertFalse(status["active"])
        journal.begin(target_image_id=IMAGE_B)
        with self.assertRaises(stack.StackError):
            self.driver().journal(action="reset")
        reset = self.driver().journal(action="reset", confirm="reset-journal")
        self.assertFalse(reset["active"])

    # -- vocabulary ----------------------------------------------------------
    def test_external_effect_vocabulary_is_allowlisted(self):
        with self.assertRaises(stack.StackError):
            stack._checked_run(self.runner, ["rm", "-rf", "/"], operation="hostile")
        stack._checked_run(self.runner, ["docker", "compose", "ps"], operation="bounded")
        stack._checked_run(self.runner, ["systemctl", "status", "x"], operation="bounded")
        self.assertEqual(len(self.runner.calls), 2)


class LegacyAndProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runner = FakeRunner()

    def legacy_env(self) -> dict[str, str]:
        state = private(self.root / "state")
        inputs = private(self.root / "input")
        config = private(self.root / "config")
        open_store(state / "app.sqlite3").close()
        return {
            "HR_DATABASE": str(state / "app.sqlite3"),
            "HR_INPUT_DIR": str(inputs),
            "HR_CONFIG_DIR": str(config),
            "HR_TIMEZONE": "UTC",
        }

    def test_legacy_walkthrough_setup_check_start_status_stop_uninstall(self):
        env = self.legacy_env()
        driver = stack.StackDriver(config=None, env=env, runner=self.runner)
        setup = driver.setup()
        self.assertEqual(setup["rendered_units"], [])
        check = driver.check()
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["release"], "legacy-unmanaged")
        start = driver.start()
        self.assertEqual(start["release"], "legacy-unmanaged")
        self.assertEqual(start["campaign"], "not-started")
        status = driver.status(live=False)
        self.assertEqual(status["schema_version"], SCHEMA_VERSION)
        stop = driver.stop(confirm="stop")
        self.assertEqual(stop["bridge"], "not-installed")
        # No bridge exists in the legacy path, so no systemctl call is made.
        self.assertTrue(all(call["argv"][0] == "docker" for call in self.runner.calls))
        uninstall = driver.uninstall(confirm="uninstall")
        self.assertTrue(uninstall["confirmed"])
        with self.assertRaises(stack.StackError):
            driver.upgrade(release=write_target_manifest(self.root), confirm="upgrade")
        with self.assertRaises(stack.StackError):
            driver.backup(archive=self.root / "archive", confirm="backup")

    def test_legacy_mixed_env_is_rejected_when_config_is_selected(self):
        config = write_operator_config(self.root)
        with self.assertRaises(stack.StackError):
            stack.StackDriver(config=config, env={"AI_PROVIDER": "mistral"}, runner=self.runner)

    def test_shared_profile_uses_the_lan_compose_file_and_explicit_bind(self):
        config_dir = private(self.root / "config")
        input_dir = private(self.root / "input")
        state_dir = private(self.root / "state")
        bridge_dir = private(self.root / "units")
        campaign_dir = private(self.root / "campaign")
        document = json.loads(write_operator_config(self.root).read_text())
        document["paths"].update(
            {
                "config_dir": str(config_dir),
                "input_dir": str(input_dir),
                "state_dir": str(state_dir),
                "bridge_dir": str(bridge_dir),
                "campaign_config_dir": str(campaign_dir),
            }
        )
        document["bridge"].update(
            {
                "config_dir": str(config_dir),
                "state_dir": str(state_dir),
                "input_dir": str(input_dir),
            }
        )
        document["shared_control"] = True
        document["campaign_profile"] = True
        config = config_dir / "operator.json"
        config.write_text(json.dumps(document))
        config.chmod(0o600)
        driver = stack.StackDriver(config=config, env={}, runner=self.runner)
        driver.setup(user="testop")
        driver.start()
        argv = self.runner.argv()[-1]
        self.assertIn(str(TOOLS.parent / "compose.lan.yaml"), argv)
        self.assertEqual(self.runner.calls[-1]["env"]["HR_LAN_BIND"], "10.10.10.20")
        self.assertEqual(self.runner.calls[-1]["env"]["HR_PORT"], "8787")

    def test_owner_profile_maps_provider_credentials_into_container_paths(self):
        config_dir = private(self.root / "config")
        credentials = private(config_dir / "credentials")
        key = credentials / "mistral.key"
        key.write_text("synthetic-key")
        key.chmod(0o600)
        input_dir = private(self.root / "input")
        state_dir = private(self.root / "state")
        bridge_dir = private(self.root / "units")
        campaign_dir = private(self.root / "campaign")
        document = json.loads(write_operator_config(self.root).read_text())
        document["paths"].update(
            {
                "config_dir": str(config_dir),
                "input_dir": str(input_dir),
                "state_dir": str(state_dir),
                "bridge_dir": str(bridge_dir),
                "campaign_config_dir": str(campaign_dir),
            }
        )
        document["bridge"].update(
            {
                "config_dir": str(config_dir),
                "state_dir": str(state_dir),
                "input_dir": str(input_dir),
            }
        )
        document["ai_enabled"] = True
        document["provider"] = {
            "provider": "mistral",
            "model": "mistral-small-latest",
            "base_url": "https://api.mistral.ai/v1",
            "credential": {
                "file": str(key),
                "format": "bare",
                "variable": "MISTRAL_API_KEY",
            },
            "free_only": False,
            "completion_cap": 512,
        }
        config = config_dir / "operator.json"
        config.write_text(json.dumps(document))
        config.chmod(0o600)
        driver = stack.StackDriver(config=config, env={}, runner=self.runner)
        driver.setup(user="testop")
        driver.start()
        argv = self.runner.argv()[-1]
        self.assertIn(str(TOOLS.parent / "compose.ai.yaml"), argv)
        env = self.runner.calls[-1]["env"]
        self.assertEqual(env["AI_PROVIDER"], "mistral")
        self.assertEqual(env["AI_CREDENTIAL_FILE"], "/config/credentials/mistral.key")
        self.assertEqual(env["HR_PORT"], "8789")
        self.assertNotIn("synthetic-key", json.dumps(env))


class OperatorConfigLoaderTests(unittest.TestCase):
    """Fresh-config walkthrough regression: the canonical example must load."""

    def test_example_config_round_trips_despite_repeated_nested_keys(self):
        from household_report.operator_config import (
            create_example_config,
            load_operator_config,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operator.json"
            path.write_text(json.dumps(create_example_config(), indent=2, sort_keys=True))
            path.chmod(0o600)
            loaded = load_operator_config(path)
            self.assertEqual(loaded.paths.config_dir, loaded.bridge.config_dir)
            self.assertEqual(loaded.paths.state_dir, loaded.bridge.state_dir)

    def test_duplicate_keys_inside_one_object_are_still_refused(self):
        from household_report.operator_config import OperatorConfigError, load_operator_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operator.json"
            path.write_text('{"version": 1, "version": 2}')
            path.chmod(0o600)
            with self.assertRaises(OperatorConfigError) as caught:
                load_operator_config(path)
            self.assertIn("Duplicate key", str(caught.exception))

    def test_a_real_world_source_identity_loads_and_still_refuses_junk(self):
        """The source identity is opaque provenance, not an identifier.

        Live values are descriptive strings containing spaces, dots, slashes and
        semicolons. They are compared for equality only, so the fresh
        configuration path must accept them; the operator-config schema used to
        require identifier-safe characters and refused every real value.
        """
        from household_report.operator_config import OperatorConfigError, load_operator_config

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = json.loads(write_operator_config(root).read_text())
            config["bridge"]["identity"] = (
                "pihole FTL generation 1; provenance abc/123.xyz - registered 2026-10-28"
            )
            path = root / "config" / "operator.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            loaded = load_operator_config(path)
            self.assertEqual(
                loaded.bridge.identity,
                "pihole FTL generation 1; provenance abc/123.xyz - registered 2026-10-28",
            )
            for junk in ("", "   ", "with\nnewline", "with\x00null", "x" * 513):
                config["bridge"]["identity"] = junk
                path.write_text(json.dumps(config))
                with self.assertRaises(OperatorConfigError):
                    load_operator_config(path)

    def test_generation_and_container_remain_identifier_constrained(self):
        """Only the identity is relaxed; identifiers stay path/filename safe."""
        from household_report.operator_config import OperatorConfigError, load_operator_config

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, name in enumerate(("generation", "container")):
                case = root / f"case{index}"
                config = json.loads(write_operator_config(case).read_text())
                config["bridge"][name] = "not a valid/id"
                path = case / "config" / "operator.json"
                path.write_text(json.dumps(config))
                path.chmod(0o600)
                with self.assertRaises(OperatorConfigError):
                    load_operator_config(path)

    def test_the_compose_project_name_is_explicit_and_validated(self):
        """A deployment must name its real Compose project.

        The application bridges have fixed names (br-hr005/br-hr006), so a
        different project cannot reuse them: recreating under a derived project
        name failed with a duplicate bridge and left the live containers
        untouched but undeployed.
        """
        from household_report.operator_config import OperatorConfigError, load_operator_config

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = json.loads(write_operator_config(root).read_text())
            config["network"]["compose_project"] = "household-report"
            path = root / "config" / "operator.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            self.assertEqual(load_operator_config(path).network.compose_project, "household-report")

            for bad in ("Household-Report", "with space", "-leading", "a" * 64, "up/case"):
                config["network"]["compose_project"] = bad
                path.write_text(json.dumps(config))
                with self.assertRaises(OperatorConfigError):
                    load_operator_config(path)

    def test_the_driver_manages_the_configured_compose_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = json.loads(write_operator_config(root).read_text())
            config["network"]["compose_project"] = "household-report"
            path = root / "config" / "operator.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            runner = FakeRunner()
            driver = stack.StackDriver(config=path, env={}, runner=runner)
            self.assertEqual(driver.project, "household-report")
            driver.setup(user="testop")
            driver.start()
            compose_argv = runner.argv()[2]
            self.assertEqual(compose_argv[compose_argv.index("-p") + 1], "household-report")

    def test_an_instance_without_a_bridge_never_touches_the_campaign_bridge(self):
        """The owner research dashboard runs no capture bridge.

        It must be describable and manageable, and it must never render, stop
        or remove the campaign bridge that belongs to the shared instance.
        """
        from household_report.operator_config import load_operator_config

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = json.loads(write_operator_config(root).read_text())
            config["network"]["compose_project"] = "household-ai"
            config["campaign_profile"] = False
            config["shared_control"] = False
            config["ai_enabled"] = True
            config.pop("bridge")
            credentials = private(root / "config" / "credentials")
            key = credentials / "provider.key"
            key.write_text("synthetic-key")
            key.chmod(0o600)
            config["provider"] = {
                "provider": "mistral",
                "model": "mistral-small-latest",
                "base_url": "https://api.mistral.ai/v1",
                "credential": {
                    "file": str(key),
                    "format": "bare",
                    "variable": "MISTRAL_API_KEY",
                },
                "free_only": False,
                "completion_cap": 512,
            }
            path = root / "config" / "operator.json"
            path.write_text(json.dumps(config))
            path.chmod(0o600)

            loaded = load_operator_config(path)
            self.assertIsNone(loaded.bridge)

            runner = FakeRunner()
            driver = stack.StackDriver(config=path, env={}, runner=runner)
            self.assertEqual(driver.project, "household-ai")
            setup = driver.setup(user="testop")
            self.assertEqual(setup["rendered_units"], [])
            driver.start()
            driver.stop(confirm="stop")
            # No systemctl call: this instance has no bridge to stop.
            self.assertTrue(all(call["argv"][0] != "systemctl" for call in runner.calls))
            self.assertEqual(driver.stop(confirm="stop")["bridge"], "not-installed")
            uninstall = driver.uninstall(confirm="uninstall")
            self.assertTrue(uninstall["confirmed"])
            self.assertEqual(uninstall["removed"]["bridge_units"], [])


class ManifestTests(unittest.TestCase):
    def test_target_manifest_parses_and_rejects_unknown_fields(self):
        from household_report.release import ReleaseError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_target_manifest(root)
            parsed = parse_manifest(json.loads(path.read_text()))
            self.assertEqual(parsed.image_id, IMAGE_B)
            document = json.loads(path.read_text())
            document["surprise"] = 1
            with self.assertRaises(ReleaseError):
                parse_manifest(document)
            missing = json.loads(path.read_text())
            del missing["lock_sha256"]
            with self.assertRaises(ReleaseError):
                parse_manifest(missing)


if __name__ == "__main__":
    unittest.main()
