"""B2 host boundary: no Docker in tests; commands are captured by a fake runner."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from test_tools import load_tool


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("input", "config", "state"):
            (self.root / name).mkdir(mode=0o700)
        for name in ("docker", "python", "compose.yaml"):
            (self.root / name).write_text("")
        self.config = {
            "python": str(self.root / "python"),
            "docker": str(self.root / "docker"),
            "compose": str(self.root / "compose.yaml"),
            "input_dir": str(self.root / "input"),
            "config_dir": str(self.root / "config"),
            "state_dir": str(self.root / "state"),
            "container": "test-resolver",
            "database": "/etc/pihole/pihole-FTL.db",
            "generation": "gen1",
            "identity": "test-generation",
        }
        self.module = load_tool("host_bridge")

    def test_inactive_campaign_never_runs_exporter(self):
        commands = []

        def fake(command, **keywords):
            commands.append(command)
            if "worker-status" in command:
                return CompletedProcess(command, 0, '{"campaign":null}', "")
            return CompletedProcess(command, 0, '{"verified":true}', "")

        self.assertEqual(self.module.Bridge(self.config, runner=fake).tick(), 0)
        self.assertTrue(all("export_snapshot.py" not in " ".join(c) for c in commands))
        self.assertTrue(all("--now" not in c for c in commands))
        self.assertTrue(any("report-run" in c for c in commands))

    def test_worker_failure_before_identity_check_finishes_is_recorded(self):
        def fake(command, **keywords):
            return CompletedProcess(command, 1, "", "private error")

        with self.assertRaises(self.module.BridgeError):
            self.module.Bridge(self.config, runner=fake, clock=lambda: 500).tick()
        record = json.loads((self.root / "state" / "bridge-status.json").read_text())
        self.assertEqual(record["attempt"]["code"], "bridge_failed")
        self.assertEqual(record["consecutive_failures"], 1)
        self.assertNotIn("private error", json.dumps(record))

    def test_identity_change_before_pending_import_latches_without_import(self):
        operations = []
        checks = iter((True, False))

        def fake(command, **keywords):
            operation = command[command.index("/app/tools/campaign_cli.py") + 3]
            operations.append(operation)
            if operation == "source-check":
                verified = next(checks)
                response = {"verified": verified, "code": "ok" if verified else "identity_mismatch"}
            elif operation == "worker-status":
                response = {
                    "campaign": {
                        "state": "active",
                        "campaign_id": "camp-1",
                        "utc_bounds": [100, 1000],
                    }
                }
            elif operation == "pending-artifacts":
                response = {"pending": []}
            else:
                response = {}
            return CompletedProcess(command, 0, json.dumps(response), "")

        bridge = self.module.Bridge(self.config, runner=fake, clock=lambda: 500)
        with self.assertRaises(self.module.BridgeError):
            bridge.tick()
        status = json.loads((self.root / "state" / "bridge-status.json").read_text())
        self.assertEqual(status["last_error_code"], "identity_mismatch")
        self.assertTrue(status["latched_fingerprint"])
        self.assertNotIn("import-artifact", operations)
        operations.clear()
        bridge.tick()
        self.assertNotIn("source-check", operations)

    def test_only_virtualenv_python_symlink_is_accepted(self):
        venv_bin = self.root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python = venv_bin / "python"
        python.symlink_to(self.root / "python")
        self.module.Bridge({**self.config, "python": str(python)})

        rogue = self.root / "python-link"
        rogue.symlink_to(self.root / "python")
        for override in (
            {"python": str(rogue)},
            {"docker": str(rogue)},
            {"compose": str(rogue)},
        ):
            with self.subTest(override=override), self.assertRaises(self.module.BridgeError):
                self.module.Bridge({**self.config, **override})
        python.unlink()
        python.symlink_to(self.root / "missing-python")
        with self.assertRaises(self.module.BridgeError):
            self.module.Bridge({**self.config, "python": str(python)})

    def test_rejects_hostile_work_before_extraction(self):
        commands = []

        def fake(command, **keywords):
            commands.append(command)
            operation = command[command.index("/app/tools/campaign_cli.py") + 3]
            if operation == "worker-status":
                data = {
                    "campaign": {
                        "state": "active",
                        "campaign_id": "camp-1",
                        "utc_bounds": [100, 200],
                    }
                }
            elif operation == "pending-artifacts":
                data = {"pending": []}
            elif operation == "claim-chunk":
                data = {
                    "claimed": [
                        {
                            "campaign_id": "camp-1",
                            "chunk_id": "../escape",
                            "generation_id": "gen1",
                            "lease_token": "token",
                            "start_epoch": 100,
                            "end_epoch": 200,
                        }
                    ]
                }
            else:
                data = {"verified": True}
            return CompletedProcess(command, 0, json.dumps(data), "")

        with self.assertRaises(self.module.BridgeError):
            self.module.Bridge(self.config, runner=fake, clock=lambda: 500).tick()
        self.assertTrue(all("export_snapshot.py" not in " ".join(c) for c in commands))
        self.assertTrue(all(not isinstance(c, str) for c in commands))

    def test_symlinked_input_and_config_refused(self):
        (self.root / "link").symlink_to(self.root / "input", target_is_directory=True)
        for key in ("input_dir", "config_dir"):
            config = {**self.config, key: str(self.root / "link")}
            with self.assertRaises(self.module.BridgeError):
                self.module.Bridge(config)

    def test_restart_imports_pending_artifact_without_new_source_read(self):
        work = {
            "campaign_id": "camp-1",
            "chunk_id": "camp-1:100:200",
            "generation_id": "gen1",
            "start_epoch": 100,
            "end_epoch": 200,
            "state": "import_pending",
            "path": "capture-valid.json",
        }
        raw = b'{"synthetic":"private evidence"}'
        (self.root / "input" / work["path"]).write_bytes(raw)
        work["digest"] = hashlib.sha256(raw).hexdigest()
        operations = []

        def fake(command, **keywords):
            operations.append(command)
            operation = command[command.index("/app/tools/campaign_cli.py") + 3]
            if operation == "worker-status":
                response = {
                    "campaign": {
                        "state": "active",
                        "campaign_id": "camp-1",
                        "utc_bounds": [100, 1000],
                    }
                }
            elif operation == "pending-artifacts":
                response = {"pending": [work]}
            elif operation == "import-artifact":
                response = {"state": "imported"}
            elif operation == "claim-chunk":
                response = {"claimed": []}
            else:
                response = {"verified": True}
            return CompletedProcess(command, 0, json.dumps(response), "")

        self.assertEqual(self.module.Bridge(self.config, runner=fake, clock=lambda: 500).tick(), 1)
        self.assertTrue(any("import-artifact" in c for c in operations))
        self.assertFalse(any("export_snapshot.py" in " ".join(c) for c in operations))

    def test_identity_is_rechecked_immediately_before_pending_import(self):
        checks = iter((True, True, False))
        operations = []
        work = {
            "campaign_id": "camp-1",
            "chunk_id": "camp-1:100:200",
            "generation_id": "gen1",
            "start_epoch": 100,
            "end_epoch": 200,
            "state": "import_pending",
            "path": "capture-valid.json",
            "digest": "d" * 64,
        }

        def fake(command, **keywords):
            operation = command[command.index("/app/tools/campaign_cli.py") + 3]
            operations.append(operation)
            if operation == "source-check":
                response = {"verified": next(checks), "code": "identity_mismatch"}
            elif operation == "worker-status":
                response = {
                    "campaign": {
                        "state": "active",
                        "campaign_id": "camp-1",
                        "utc_bounds": [100, 1000],
                    }
                }
            elif operation == "pending-artifacts":
                response = {"pending": [work]}
            else:
                response = {"state": "imported"}
            return CompletedProcess(command, 0, json.dumps(response), "")

        with self.assertRaises(self.module.BridgeError):
            self.module.Bridge(self.config, runner=fake, clock=lambda: 500).tick()
        self.assertNotIn("import-artifact", operations)

    def test_one_settled_claim_is_exported_and_imported_without_shell(self):
        work = {
            "campaign_id": "camp-1",
            "chunk_id": "camp-1:100:200",
            "generation_id": "gen1",
            "start_epoch": 100,
            "end_epoch": 200,
            "lease_token": "token1",
        }
        operations = []
        claims = iter(([work], []))

        def fake(command, **keywords):
            operations.append(command)
            if "export_snapshot.py" in " ".join(command):
                path = self.root / "input" / "capture-token1.json"
                path.write_bytes(b'{"synthetic":"private evidence"}')
                response = {"snapshot": path.name}
            else:
                operation = command[command.index("/app/tools/campaign_cli.py") + 3]
                if operation == "worker-status":
                    response = {
                        "campaign": {
                            "state": "active",
                            "campaign_id": "camp-1",
                            "utc_bounds": [100, 1000],
                        }
                    }
                elif operation == "pending-artifacts":
                    response = {"pending": []}
                elif operation == "claim-chunk":
                    response = {"claimed": next(claims)}
                    self.assertEqual(command[command.index("--limit") + 1], "1")
                elif operation == "attempt-artifacts":
                    response = {"tokens": ["token1"]}
                elif operation == "chunk-captured":
                    response = {"acknowledged": True}
                elif operation == "import-artifact":
                    response = {"state": "imported"}
                else:
                    response = {"verified": True}
            return CompletedProcess(command, 0, json.dumps(response), "")

        self.assertEqual(self.module.Bridge(self.config, runner=fake, clock=lambda: 500).tick(), 1)
        self.assertTrue(any("--digest" in c and "chunk-captured" in c for c in operations))
        self.assertTrue(any("import-artifact" in c for c in operations))
        self.assertTrue(all(isinstance(c, list) for c in operations))

    def test_rendered_system_service_is_opt_in_bounded_and_account_scoped(self):
        renderer = load_tool("render_bridge_units")
        config = self.root / "config" / "bridge.json"
        config.write_text(json.dumps(self.config))
        os.chmod(config, 0o600)
        service, timer = renderer.render(
            user="operator",
            config=config,
            python=self.root / "python",
            bridge=self.root / "bridge.py",
        )
        self.assertIn("User=operator", service)
        self.assertIn("TimeoutStartSec=610", service)
        self.assertIn("ReadWritePaths=", service)
        self.assertIn("OnUnitInactiveSec=60s", timer)
        self.assertIn("Persistent=false", timer)
        self.assertNotIn("ExecStartPre=", service)


if __name__ == "__main__":
    unittest.main()
