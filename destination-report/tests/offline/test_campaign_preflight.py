"""B5 offline-first campaign preflight checks with injected command runners."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_tools import load_tool

APP = Path(__file__).resolve().parents[2]
BIND = "10.10.10.20"
PUBLIC = "https://10.10.10.20:8787"
HOSTS = "10.10.10.20:8787"
NAMESPACE = {
    "schema_version": 1,
    "revision": "reviewed-1",
    "rules": [
        {
            "rule_id": "rule-1",
            "namespace": "games.example",
            "match": "suffix",
            "group_id": "g1",
            "group_label": "Group",
            "group_kind": "platform",
            "review_note": "reviewed",
        }
    ],
}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = self.root / "config"
        (self.config / "tls").mkdir(parents=True, mode=0o700)
        self.input = self.root / "input"
        self.state = self.root / "state"
        self.input.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        os.chmod(self.config, 0o700)
        (self.config / "password").write_text("scrypt$record\n")
        (self.config / "session-key").write_text("k" * 43 + "\n")
        (self.config / "tls" / "cert.pem").write_text("certificate")
        (self.config / "tls" / "key.pem").write_text("key")
        for name in ("password", "session-key", "tls/key.pem"):
            os.chmod(self.config / name, 0o600)
        self.namespace = self.config / "gaming-namespaces.json"
        self.namespace.write_text(json.dumps(NAMESPACE))
        os.chmod(self.namespace, 0o600)
        self.bridge = self.config / "campaign-bridge.json"
        self.bridge.write_text(
            json.dumps(
                {
                    "python": "/usr/bin/dash",
                    "compose": str(APP / "compose.yaml"),
                    "input_dir": str(self.input),
                    "container": "starlink-dns-pilot",
                    "database": "/etc/pihole/pihole-FTL.db",
                    "docker": "/usr/bin/dash",
                    "generation": "gen-1",
                    "identity": "pihole-ftl",
                    "config_dir": str(self.config),
                    "state_dir": str(self.state),
                }
            )
        )
        os.chmod(self.bridge, 0o600)
        self.database = self.state / "app.sqlite3"
        self.connection = sqlite3.connect(self.database)
        self.connection.executescript(
            "CREATE TABLE source_generations (generation_id TEXT PRIMARY KEY);"
            "CREATE TABLE campaigns (campaign_id TEXT PRIMARY KEY, state TEXT);"
        )
        self.connection.execute("INSERT INTO source_generations VALUES ('gen-1')")
        self.connection.commit()
        self.connection.close()
        self.tool = load_tool("campaign_preflight")
        self.calls: list[list[str]] = []

    def runner(self, command, **kwargs):
        self.calls.append(list(command))
        text = " ".join(command)
        if "openssl" in text:
            return subprocess.CompletedProcess(
                command, 0, f"IP {BIND} does match certificate\n", ""
            )
        if "compose" in text:
            payload = {
                "services": {
                    "app": {
                        "ports": [{"host_ip": BIND, "published": "8787"}],
                        "volumes": [{"target": "/config", "source": str(self.config)}],
                        "environment": {"HR_CAMPAIGN_PROFILE": "1", "HR_LAN_BIND": BIND},
                    }
                }
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if "inspect" in text:
            return subprocess.CompletedProcess(command, 0, "true\n", "")
        if "--config" in command:
            return subprocess.CompletedProcess(command, 0, "7\n", "")
        if "pragma_table_info" in text:
            return subprocess.CompletedProcess(command, 0, "7\n", "")
        if "SELECT count(*), min(timestamp)" in text:
            return subprocess.CompletedProcess(command, 0, "1000|100|2000\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    def preflight(self, **overrides):
        arguments = {
            "mode": "offline",
            "config_dir": self.config,
            "input_dir": self.input,
            "state_dir": self.state,
            "bind": BIND,
            "public_url": PUBLIC,
            "allowed_hosts": HOSTS,
            "port": "8787",
            "compose": APP / "compose.yaml",
            "lan": APP / "compose.lan.yaml",
            "bridge_config": self.bridge,
            "namespace": self.namespace,
            "database": self.database,
            "ack_empty": False,
            "env": {},
            "runner": self.runner,
        }
        arguments.update(overrides)
        return self.tool.run_preflight(**arguments)

    def failed(self, result):
        return [check["check"] for check in result["checks"] if not check["ok"]]

    def test_offline_configuration_passes_without_touching_the_resolver(self):
        result = self.preflight()
        self.assertTrue(result["ok"], self.failed(result))
        self.assertEqual(result["mode"], "offline")
        self.assertFalse(any("exec" in " ".join(call) for call in self.calls))
        self.assertFalse(any("inspect" in " ".join(call) for call in self.calls))

    def test_bridge_accepts_only_virtualenv_python_symlink(self):
        venv_bin = self.root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        python = venv_bin / "python"
        python.symlink_to("/usr/bin/dash")
        bridge = json.loads(self.bridge.read_text())
        bridge["python"] = str(python)
        self.bridge.write_text(json.dumps(bridge))
        self.assertTrue(self.preflight()["ok"])

        rogue = self.root / "python-link"
        rogue.symlink_to("/usr/bin/dash")
        for override in ({"python": str(rogue)}, {"docker": str(rogue)}, {"compose": str(rogue)}):
            with self.subTest(override=override):
                self.bridge.write_text(json.dumps({**bridge, **override}))
                failed = self.failed(self.preflight())
                self.assertIn("bridge configuration", failed)
        python.unlink()
        python.symlink_to(self.root / "missing-python")
        self.bridge.write_text(json.dumps(bridge))
        self.assertIn("bridge configuration", self.failed(self.preflight()))

    def test_shared_http_preflight_needs_no_password_or_tls_and_rejects_config_mount(self):
        for path in (
            self.config / "password",
            self.config / "session-key",
            self.config / "tls" / "cert.pem",
            self.config / "tls" / "key.pem",
        ):
            path.unlink()
        original_runner = self.runner

        def shared_runner(command, **kwargs):
            if "compose" in command:
                payload = {
                    "services": {
                        "app": {
                            "ports": [{"host_ip": BIND, "published": "8787"}],
                            "volumes": [
                                {"target": "/input", "source": str(self.input)},
                                {"target": "/state", "source": str(self.state)},
                            ],
                            "environment": {
                                "HR_CAMPAIGN_PROFILE": "1",
                                "HR_LAN_BIND": BIND,
                                "HR_LAN_SHARED_CONTROL": "1",
                                "HR_PUBLIC_URL": f"http://{HOSTS}",
                                "HR_ALLOWED_HOSTS": HOSTS,
                            },
                        }
                    }
                }
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            return original_runner(command, **kwargs)

        result = self.preflight(public_url=f"http://{HOSTS}", runner=shared_runner)
        self.assertTrue(result["ok"], self.failed(result))
        self.assertNotIn("TLS certificate", [item["check"] for item in result["checks"]])
        self.assertIn(
            "public origin",
            self.failed(
                self.preflight(
                    public_url="http://10.10.10.20:9999",
                    allowed_hosts="10.10.10.20:9999",
                    runner=shared_runner,
                )
            ),
        )

        def extra_mount(command, **kwargs):
            result = shared_runner(command, **kwargs)
            if "compose" in command:
                payload = json.loads(result.stdout)
                payload["services"]["app"]["volumes"].append(
                    {"target": "/config", "source": str(self.config)}
                )
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            return result

        self.assertIn(
            "Compose merge",
            self.failed(self.preflight(public_url=f"http://{HOSTS}", runner=extra_mount)),
        )

        def wrong_origin(command, **kwargs):
            result = shared_runner(command, **kwargs)
            if "compose" in command:
                payload = json.loads(result.stdout)
                payload["services"]["app"]["environment"]["HR_PUBLIC_URL"] = (
                    "http://10.10.10.31:8787"
                )
                return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
            return result

        self.assertIn(
            "Compose merge",
            self.failed(self.preflight(public_url=f"http://{HOSTS}", runner=wrong_origin)),
        )

    def test_relay_origin_is_explicit_and_exact_while_compose_keeps_vm_bind(self):
        def relayed_compose(command, **kwargs):
            if "compose" not in command:
                return self.runner(command, **kwargs)
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "services": {
                            "app": {
                                "ports": [{"host_ip": BIND, "published": "8787"}],
                                "networks": {"campaign": None},
                                "volumes": [
                                    {"target": "/input", "source": str(self.input)},
                                    {"target": "/state", "source": str(self.state)},
                                ],
                                "environment": {
                                    "HR_CAMPAIGN_PROFILE": "1",
                                    "HR_LAN_BIND": BIND,
                                    "HR_LAN_SHARED_CONTROL": "1",
                                    "HR_PUBLIC_URL": "http://192.168.1.10:8787",
                                    "HR_ALLOWED_HOSTS": "192.168.1.10:8787",
                                },
                            }
                        },
                        "networks": {
                            "campaign": {
                                "enable_ipv6": False,
                                "driver_opts": {"com.docker.network.bridge.name": "br-hr005"},
                            }
                        },
                    }
                ),
                "",
            )

        base = {
            "public_url": "http://192.168.1.10:8787",
            "allowed_hosts": "192.168.1.10:8787",
            "runner": relayed_compose,
        }
        self.assertTrue(self.preflight(**base, relay_ip="192.168.1.10")["ok"])
        for overrides in (
            {},
            {"relay_ip": "192.168.1.51"},
            {"relay_ip": "8.8.8.8"},
            {"relay_ip": "192.168.1.10", "bind": "10.10.10.31"},
            {"relay_ip": "192.168.1.10", "port": "9999"},
            {"relay_ip": "192.168.1.10", "public_url": "https://192.168.1.10:8787"},
            {"relay_ip": "192.168.1.10", "allowed_hosts": "192.168.1.10:8787,localhost:8787"},
        ):
            with self.subTest(overrides=overrides):
                self.assertIn("public origin", self.failed(self.preflight(**(base | overrides))))

        self.assertIn(
            "public origin",
            self.failed(
                self.preflight(
                    public_url=f"http://{HOSTS}",
                    allowed_hosts=HOSTS,
                    relay_ip="192.168.1.10",
                    runner=relayed_compose,
                )
            ),
        )

        def wrong_bridge(command, **kwargs):
            result = relayed_compose(command, **kwargs)
            if "compose" in command:
                document = json.loads(result.stdout)
                document["networks"]["campaign"]["driver_opts"][
                    "com.docker.network.bridge.name"
                ] = "br-other"
                return subprocess.CompletedProcess(command, 0, json.dumps(document), "")
            return result

        self.assertIn(
            "Compose merge",
            self.failed(
                self.preflight(**(base | {"relay_ip": "192.168.1.10", "runner": wrong_bridge}))
            ),
        )

    def test_offline_refuses_unsafe_paths_origins_and_provider_configuration(self):
        os.chmod(self.config, 0o755)
        result = self.preflight(env={"AI_PROVIDER": "groq"})
        self.assertFalse(result["ok"])
        self.assertIn("config directory", self.failed(result))
        self.assertIn("AI-off profile", self.failed(result))
        os.chmod(self.config, 0o700)
        cases = (
            ("LAN bind", "0.0.0.0", PUBLIC, HOSTS),
            ("Compose merge", BIND, "http://10.10.10.20:8787", HOSTS),
            ("public origin", BIND, PUBLIC, "10.10.10.20:8787,localhost:8787"),
        )
        for check, bind, origin, hosts in cases:
            with self.subTest(bind=bind, origin=origin):
                result = self.preflight(bind=bind, public_url=origin, allowed_hosts=hosts)
                self.assertIn(check, self.failed(result))

    def test_offline_refuses_unreviewed_empty_namespace_and_wrong_compose_merge(self):
        self.namespace.write_text(json.dumps({"schema_version": 1, "revision": "r", "rules": []}))
        result = self.preflight()
        self.assertIn("reviewed namespace", self.failed(result))
        self.assertTrue(self.preflight(ack_empty=True)["ok"])

        def two_ports(command, **kwargs):
            payload = {
                "services": {
                    "app": {
                        "ports": [
                            {"host_ip": BIND, "published": "8787"},
                            {"host_ip": "127.0.0.1", "published": "8787"},
                        ],
                        "volumes": [{"target": "/config", "source": str(self.config)}],
                        "environment": {"HR_CAMPAIGN_PROFILE": "1", "HR_LAN_BIND": BIND},
                    }
                }
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        result = self.preflight(runner=two_ports)
        self.assertIn("Compose merge", self.failed(result))

    def test_live_mode_reads_counts_schema_retention_and_generation_only(self):
        result = self.preflight(mode="live")
        self.assertTrue(result["ok"], self.failed(result))
        commands = [" ".join(call) for call in self.calls]
        self.assertTrue(any("inspect" in command for command in commands))
        self.assertTrue(any("pragma_table_info" in command for command in commands))
        self.assertTrue(any("database.maxDBdays" in command for command in commands))
        rendered = json.dumps(result)
        self.assertNotIn("games.example", rendered)
        self.assertNotIn("scrypt$", rendered)

    def test_live_mode_refuses_unregistered_generation_and_active_campaign(self):
        connection = sqlite3.connect(self.database)
        connection.execute("DELETE FROM source_generations")
        connection.commit()
        connection.close()
        result = self.preflight(mode="live")
        self.assertIn("campaign state", self.failed(result))
        connection = sqlite3.connect(self.database)
        connection.execute("INSERT INTO source_generations VALUES ('gen-1')")
        connection.execute("INSERT INTO campaigns VALUES ('camp-1', 'active')")
        connection.commit()
        connection.close()
        result = self.preflight(mode="live")
        self.assertIn("campaign state", self.failed(result))


class OwnerProfileTests(PreflightTests):
    """Owner (8789 https) profile: exact origin pair, br-hr006, AI-on, /config."""

    OWNER_ORIGINAL = "https://192.168.1.10:8789"
    OWNER_HOSTS = "192.168.1.10:8789"
    RELAY = "192.168.1.10"

    def owner_runner(self, command, **kwargs):
        self.calls.append(list(command))
        text = " ".join(command)
        if "openssl" in text:
            if f"-checkip {self.RELAY}" in text:
                return subprocess.CompletedProcess(command, 0, "covers\n", "")
            return subprocess.CompletedProcess(command, 1, "", "hostname mismatch")
        if "compose" in text:
            payload = {
                "services": {
                    "app": {
                        "ports": [{"host_ip": BIND, "published": "8789"}],
                        "networks": {"owner": None},
                        "volumes": [
                            {"target": "/config", "source": str(self.config)},
                            {"target": "/input", "source": str(self.input)},
                            {"target": "/state", "source": str(self.state)},
                        ],
                        "environment": {
                            "HR_PUBLIC_URL": self.OWNER_ORIGINAL,
                            "HR_ALLOWED_HOSTS": self.OWNER_HOSTS,
                            "AI_PROVIDER": "openrouter",
                            "AI_CREDENTIAL_FILE": "/config/.env.local",
                        },
                    }
                },
                "networks": {
                    "owner": {
                        "enable_ipv6": False,
                        "driver_opts": {"com.docker.network.bridge.name": "br-hr006"},
                    }
                },
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return self.runner(command, **kwargs)

    def owner_preflight(self, **overrides):
        base = {
            "public_url": self.OWNER_ORIGINAL,
            "allowed_hosts": self.OWNER_HOSTS,
            "port": "8789",
            "relay_ip": self.RELAY,
            "profile": "owner",
            "runner": self.owner_runner,
        }
        base.update(overrides)
        return self.preflight(**base)

    def merge_patch(self, **patches):
        """A runner whose Compose merge output is patched before returning."""

        def patched(command, **kwargs):
            result = self.owner_runner(command, **kwargs)
            if "compose" in command:
                document = json.loads(result.stdout)
                service = document["services"]["app"]
                for key, value in patches.get("env", {}).items():
                    service["environment"][key] = value
                for key in patches.get("remove_env", ()):
                    service["environment"].pop(key, None)
                for key, value in patches.get("ports", {}).items():
                    service["ports"][0][key] = value
                if "extra_network" in patches:
                    service["networks"][patches["extra_network"]] = None
                if patches.get("no_config_mount"):
                    service["volumes"] = [
                        item for item in service["volumes"] if item.get("target") != "/config"
                    ]
                return subprocess.CompletedProcess(command, 0, json.dumps(document), "")
            return result

        return patched

    def test_owner_profile_passes_without_campaign_records(self):
        result = self.owner_preflight()
        self.assertTrue(result["ok"], self.failed(result))
        names = [check["check"] for check in result["checks"]]
        for absent in ("AI-off profile", "bridge configuration", "reviewed namespace"):
            self.assertNotIn(absent, names)
        for present in ("LAN bind", "public origin", "TLS certificate", "Compose merge"):
            self.assertIn(present, names)
        # The TLS record must inspect the public relayed origin host, not the bind.
        self.assertTrue(any(f"-checkip {self.RELAY}" in " ".join(call) for call in self.calls))
        self.assertFalse(any("exec" in " ".join(call) for call in self.calls))

    def test_owner_origin_is_https_and_exact(self):
        cases = (
            {"public_url": "http://192.168.1.10:8789", "allowed_hosts": "192.168.1.10:8789"},
            {"public_url": "https://192.168.1.10:8787", "allowed_hosts": "192.168.1.10:8787"},
            {
                "public_url": "https://192.168.1.10:8789",
                "allowed_hosts": "192.168.1.10:8789,localhost:8789",
            },
            {"relay_ip": "192.168.1.51"},
            {"relay_ip": BIND},
            {"port": "8787"},
            {"bind": "10.10.10.31"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assertIn("public origin", self.failed(self.owner_preflight(**overrides)))

    def test_owner_compose_merge_refuses_drift_from_the_one_approved_shape(self):
        cases = {
            "wrong origin": {"env": {"HR_PUBLIC_URL": "https://192.168.1.51:8789"}},
            "wrong allowed hosts": {"env": {"HR_ALLOWED_HOSTS": "localhost:8789"}},
            "campaign env present": {"env": {"HR_CAMPAIGN_PROFILE": "1"}},
            "shared control present": {"env": {"HR_LAN_SHARED_CONTROL": "1"}},
            "lan bind present": {"env": {"HR_LAN_BIND": BIND}},
            "missing AI provider": {"remove_env": ("AI_PROVIDER",)},
            "credential outside /config": {"env": {"AI_CREDENTIAL_FILE": "/state/ai.key"}},
            "extra network": {"extra_network": "campaign"},
            "no /config mount": {"no_config_mount": True},
            "published port drift": {"ports": {"published": "9999"}},
            "wildcard bind": {"ports": {"host_ip": "0.0.0.0"}},
        }
        for name, patches in cases.items():
            with self.subTest(name=name):
                failed = self.failed(self.owner_preflight(runner=self.merge_patch(**patches)))
                self.assertIn("Compose merge", failed)

    def test_owner_tls_certificate_must_cover_the_public_origin(self):
        def cert_without_relay_host(command, **kwargs):
            result = self.owner_runner(command, **kwargs)
            if "openssl" in " ".join(command):
                return subprocess.CompletedProcess(command, 1, "", "hostname mismatch")
            return result

        self.assertIn(
            "TLS certificate", self.failed(self.owner_preflight(runner=cert_without_relay_host))
        )

    def test_cli_prints_json_and_fails_closed(self):
        argv = [
            "--mode",
            "offline",
            "--config-dir",
            str(self.config),
            "--input-dir",
            str(self.input),
            "--state-dir",
            str(self.state),
            "--lan-bind",
            BIND,
            "--public-url",
            PUBLIC,
            "--allowed-hosts",
            HOSTS,
            "--compose",
            str(APP / "compose.yaml"),
            "--lan-compose",
            str(APP / "compose.lan.yaml"),
            "--bridge-config",
            str(self.bridge),
            "--namespace",
            str(self.namespace),
            "--database",
            str(self.database),
        ]
        self.assertEqual(self.tool.main(argv, runner=self.runner), 0)
        argv[argv.index(BIND)] = "0.0.0.0"
        self.assertEqual(self.tool.main(argv, runner=self.runner), 1)

    def test_cli_owner_profile_prints_json_and_fails_closed(self):
        argv = [
            "--mode",
            "offline",
            "--profile",
            "owner",
            "--config-dir",
            str(self.config),
            "--input-dir",
            str(self.input),
            "--state-dir",
            str(self.state),
            "--lan-bind",
            BIND,
            "--public-url",
            self.OWNER_ORIGINAL,
            "--allowed-hosts",
            self.OWNER_HOSTS,
            "--port",
            "8789",
            "--relay-ip",
            self.RELAY,
            "--compose",
            str(APP / "compose.yaml"),
            "--lan-compose",
            str(APP / "compose.ai.yaml"),
            "--bridge-config",
            str(self.bridge),
            "--namespace",
            str(self.namespace),
            "--database",
            str(self.database),
        ]
        self.assertEqual(self.tool.main(argv, runner=self.owner_runner), 0)
        bad = argv[:]
        bad[bad.index("--public-url") + 1] = "http://192.168.1.10:8789"
        self.assertEqual(self.tool.main(bad, runner=self.owner_runner), 1)
        bad = argv[:]
        bad[bad.index("--allowed-hosts") + 1] = "192.168.1.10:8789,localhost:8789"
        self.assertEqual(self.tool.main(bad, runner=self.owner_runner), 1)


if __name__ == "__main__":
    unittest.main()
