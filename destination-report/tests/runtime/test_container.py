"""Explicit container check with synthetic data; never part of the offline gate.

Run with ``task runtime-check`` (which sets ``HR_RUNTIME_TESTS=1``). It builds the
current image, starts the Compose service on an ephemeral loopback port with a
temporary configuration, and proves the packaged behaviour: TLS listener, non-root
process, read-only root filesystem, no Docker socket, and idempotent imports. No
resolver, household evidence, credential or provider endpoint is touched.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from household_report.web import hash_password

APP = Path(__file__).resolve().parents[2]
COMPOSE = APP / "compose.yaml"
ENABLED = os.environ.get("HR_RUNTIME_TESTS") == "1"
PASSWORD = "runtime-check-password"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def https_ok(port: int, path: str = "/healthz") -> tuple[int, bytes]:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=context))
    url = f"https://127.0.0.1:{port}{path}"
    try:
        with opener.open(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:  # a status is still evidence
        return error.code, error.read()


@unittest.skipUnless(ENABLED, "set HR_RUNTIME_TESTS=1 (task runtime-check) to run")
class ContainerCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None or shutil.which("openssl") is None:
            raise unittest.SkipTest("docker and openssl are required")
        if os.geteuid() == 0:
            raise unittest.SkipTest("run as the owner so bind-mounted secrets stay 0600")
        try:
            subprocess.run(
                ["docker", "compose", "version"], capture_output=True, check=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            raise unittest.SkipTest("Docker Compose is unavailable") from None

        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        cls.config = root / "config"
        cls.input = root / "input"
        cls.state = root / "state"
        (cls.config / "tls").mkdir(parents=True, mode=0o700)
        cls.input.mkdir(mode=0o700)
        cls.state.mkdir(mode=0o700)
        (cls.config / "password").write_text(hash_password(PASSWORD) + "\n")
        (cls.config / "session-key").write_text(
            base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=") + "\n"
        )
        os.chmod(cls.config / "password", 0o600)
        os.chmod(cls.config / "session-key", 0o600)
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-subj",
                "/CN=household-report",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
                "-keyout",
                str(cls.config / "tls" / "key.pem"),
                "-out",
                str(cls.config / "tls" / "cert.pem"),
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )
        os.chmod(cls.config / "tls" / "key.pem", 0o600)
        os.chmod(cls.config / "tls" / "cert.pem", 0o644)

        cls.start, cls.end = 1_792_728_000, 1_792_731_600
        rows = [
            {
                "id": 1,
                "timestamp": cls.start + 1,
                "type": "A",
                "status": "FORWARDED",
                "domain": "synthetic.example.test",
                "client": "192.168.1.23",
                "forward": "1.1.1.1",
            }
        ]
        snapshot = {
            "schema_version": 1,
            "start_epoch": cls.start,
            "end_epoch": cls.end,
            "captured_utc": "2026-10-23T04:01:00Z",
            "retained_rows": 1,
            "oldest_epoch": cls.start,
            "newest_epoch": cls.end - 1,
            "window_count": 1,
            "observations": rows,
        }
        target = cls.input / f"snapshot-{cls.start}-{cls.end}.json"
        target.write_text(json.dumps(snapshot))
        os.chmod(target, 0o600)

        cls.port = free_port()
        cls.project = f"hrcheck-{os.getpid()}"
        cls.env = {
            **os.environ,
            "HR_CONFIG_DIR": str(cls.config),
            "HR_INPUT_DIR": str(cls.input),
            "HR_STATE_DIR": str(cls.state),
            "HR_PORT": str(cls.port),
            "HR_ALLOWED_HOSTS": f"127.0.0.1:8787,localhost:8787,127.0.0.1:{cls.port}",
            "HR_PUBLIC_URL": f"https://127.0.0.1:{cls.port}",
        }
        cls.compose = ["docker", "compose", "-p", cls.project, "-f", str(COMPOSE)]
        cls.addClassCleanup(cls.down)
        subprocess.run([*cls.compose, "build"], env=cls.env, check=True)
        subprocess.run([*cls.compose, "up", "-d"], env=cls.env, check=True)
        cls.wait_healthy()

    def test_packaged_shared_http_mode_needs_no_credentials_or_network(self):
        root = Path(self.temp.name)
        input_dir = root / "shared-input"
        state_dir = root / "shared-state"
        input_dir.mkdir(mode=0o700)
        state_dir.mkdir(mode=0o700)
        script = (
            "from fastapi.testclient import TestClient; "
            "from household_report.app import Application; "
            "from household_report.settings import load_settings; "
            "app = Application.open(load_settings()); "
            "client = TestClient(app.web_app(), base_url='http://10.10.10.20:8787'); "
            "assert client.get('/').status_code == 200; "
            "assert client.get('/login').status_code == 404; "
            "assert client.post('/gaming/filter', data={}).status_code == 403; "
            "assert client.post('/gaming/filter', data={}, headers={'origin': 'http://10.10.10.20:8787'}).status_code != 403; "
            "app.close()"
        )
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--entrypoint",
                "python",
                "--tmpfs",
                "/tmp:size=16m,mode=1777",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-v",
                f"{input_dir}:/input:ro",
                "-v",
                f"{state_dir}:/state",
                "-e",
                "HR_DATABASE=/state/app.sqlite3",
                "-e",
                "HR_INPUT_DIR=/input",
                "-e",
                "HR_CAMPAIGN_PROFILE=1",
                "-e",
                "HR_LAN_SHARED_CONTROL=1",
                "-e",
                "HR_LAN_BIND=10.10.10.20",
                "-e",
                "HR_ALLOWED_HOSTS=10.10.10.20:8787",
                "-e",
                "HR_PUBLIC_URL=http://10.10.10.20:8787",
                "household-report:local",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @classmethod
    def down(cls) -> None:
        subprocess.run(
            [*cls.compose, "down", "--remove-orphans"],
            env=cls.env,
            capture_output=True,
            timeout=120,
        )

    @classmethod
    def wait_healthy(cls, timeout: float = 90.0) -> None:
        container = f"{cls.project}-app-1"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            probe = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode == 0 and probe.stdout.strip() == "healthy":
                return
            time.sleep(2)
        logs = subprocess.run(
            [*cls.compose, "logs", "--tail=30"], env=cls.env, capture_output=True, text=True
        )
        raise AssertionError(f"The container never became healthy:\n{logs.stdout}{logs.stderr}")

    def container(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "exec", f"{self.project}-app-1", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_tls_health_and_unauthenticated_redirect(self):
        status, body = https_ok(self.port)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})
        status, _ = https_ok(self.port, "/")
        self.assertEqual(status, 303)
        with self.assertRaises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz", timeout=3)

    def test_process_is_unprivileged_and_root_filesystem_is_read_only(self):
        self.assertNotEqual(self.container("id", "-u").stdout.strip(), "0")
        self.assertNotEqual(self.container("touch", "/app/probe").returncode, 0)
        self.assertNotEqual(self.container("test", "-S", "/var/run/docker.sock").returncode, 0)

    def test_imports_are_idempotent_inside_the_container(self):
        command = [
            *self.compose,
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "app",
            "/app/tools/import_inputs.py",
            "--input-dir",
            "/input",
            "--db",
            "/state/app.sqlite3",
        ]
        first = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(first.returncode, 0, first.stderr)
        report = json.loads(first.stdout)
        self.assertEqual(report["snapshots"]["imported"], 1)
        second = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(second.returncode, 0, second.stderr)
        report = json.loads(second.stdout)
        self.assertEqual(report["snapshots"]["unchanged"], 1)


if __name__ == "__main__":
    unittest.main()
