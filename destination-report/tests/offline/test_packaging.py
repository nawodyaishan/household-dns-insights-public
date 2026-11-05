"""Packaging invariants read from the Dockerfile, Compose file and build context.

No Docker command and no network call: these are text-level proofs that the one image
comes from the lock, runs unprivileged and never receives the Docker socket, the live
resolver database or an administration credential. Runtime behaviour of the built
image belongs to the explicitly invoked ``tests/runtime`` checks.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
DOCKERFILE = APP / "Dockerfile"
COMPOSE = APP / "compose.yaml"
DOCKERIGNORE = APP / ".dockerignore"

ALLOWED_COPY_SOURCES = {"pyproject.toml", "uv.lock", "README.md", "src", "tools"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = read(DOCKERFILE)

    def test_base_and_builder_are_pinned_by_digest(self):
        references = re.findall(r"(?m)^FROM\s+(\S+)", self.text)
        self.assertEqual(len(references), 2)
        for reference in references:
            self.assertRegex(reference, r"@sha256:[0-9a-f]{64}$")

    def test_dependencies_come_from_the_lock_without_dev_tools(self):
        self.assertIn("uv sync --locked --no-dev --no-editable", self.text)
        for line in self.text.splitlines():
            if "uv sync" in line:
                self.assertIn("--locked", line)
                self.assertIn("--no-dev", line)
        for forbidden in ("pip install", "uv add", "uv pip install", "uv tool install"):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("! command -v ruff", self.text)
        self.assertIn("! command -v lefthook", self.text)

    def test_the_build_context_is_not_copied_wholesale(self):
        for line in self.text.splitlines():
            if not line.startswith("COPY "):
                continue
            parts = line.split()
            if parts[1].startswith("--from="):
                continue
            self.assertIn(parts[1], ALLOWED_COPY_SOURCES, line)

    def test_the_image_runs_unprivileged_from_one_entry_point(self):
        self.assertIn("USER 10001:10001", self.text)
        self.assertNotRegex(self.text, r"(?m)^USER\s+(root|0)")
        self.assertIn('ENTRYPOINT ["python", "-m", "household_report.app"]', self.text)

    def test_no_live_resolver_or_socket_path_is_baked_in(self):
        for forbidden in (
            "docker.sock",
            "pihole-FTL.db",
            "/etc/pihole",
            "PRIVATE_",
            "AI_CREDENTIAL",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_the_build_tool_is_not_left_in_the_runtime_image(self):
        self.assertIn("rm -f /usr/local/bin/uv", self.text)

    def test_shipped_tools_exist_in_the_build_context(self):
        self.assertIn("COPY tools ./tools", self.text)
        self.assertTrue((APP / "tools" / "healthcheck.py").is_file())
        self.assertTrue((APP / "tools" / "import_inputs.py").is_file())


class ComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = read(COMPOSE)

    def test_only_a_loopback_host_port_is_published(self):
        self.assertIn('"127.0.0.1:${HR_PORT:-8787}:8787"', self.text)
        self.assertNotRegex(self.text, r"(?m)^\s*-\s*\"0\.0\.0\.0:")

    def test_optional_lan_override_replaces_not_appends_port_and_disables_ai(self):
        lan = read(APP / "compose.lan.yaml")
        self.assertIn("ports: !override", lan)
        self.assertIn("${HR_LAN_BIND:?", lan)
        self.assertIn('HR_CAMPAIGN_PROFILE: "1"', lan)
        self.assertIn('HR_LAN_SHARED_CONTROL: "1"', lan)
        self.assertIn("volumes: !override", lan)
        self.assertNotIn("target: /config", lan)
        for key in (
            "HR_PASSWORD_FILE",
            "HR_SESSION_KEY_FILE",
            "HR_TLS_CERT_FILE",
            "HR_TLS_KEY_FILE",
        ):
            self.assertIn(f'{key}: ""', lan)
        self.assertNotIn("AI_CREDENTIAL_FILE", lan)

    def test_the_service_is_unprivileged_and_resource_bounded(self):
        for needle in (
            "read_only: true",
            "cap_drop:",
            "- ALL",
            "no-new-privileges:true",
            "mem_limit: 512m",
            "cpus: 1.0",
            "pids_limit: 128",
            'max-size: "1m"',
            'max-file: "2"',
            "tmpfs:",
            "healthcheck:",
            "restart: unless-stopped",
        ):
            self.assertIn(needle, self.text)
        for forbidden in (
            "privileged: true",
            "network_mode:",
            "pid: host",
            "ipc: host",
            "docker.sock",
            "/var/run",
            "cap_add:",
        ):
            self.assertNotIn(forbidden, self.text)

    def test_owner_material_is_read_only_and_only_state_is_writable(self):
        blocks = re.split(r"\n\s+-\s+type: bind", self.text)[1:]
        self.assertEqual(len(blocks), 3)
        self.assertIn("source:", blocks[0])
        self.assertIn("read_only: true", blocks[0])
        self.assertIn("read_only: true", blocks[1])
        self.assertNotIn("read_only: true", blocks[2])
        self.assertIn("target: /state", blocks[2])

    def test_ai_and_search_stay_disabled_by_default(self):
        for name in (
            "AI_PROVIDER",
            "AI_MODEL_ID",
            "AI_CREDENTIAL_FILE",
            "EXA_MCP_URL",
            "EXA_KEY_FILE",
        ):
            self.assertNotIn(name, self.text)

    def test_a_container_bind_needs_an_explicit_opt_in(self):
        self.assertIn("HR_BIND_HOST: 0.0.0.0", self.text)
        self.assertIn('HR_ALLOW_CONTAINER_BIND: "1"', self.text)

    def test_no_host_directory_or_volume_is_mounted_beyond_the_three(self):
        mounts = re.findall(r"source:\s*\"?\$\{(HR_[A-Z_]+)", self.text)
        self.assertEqual(mounts, ["HR_CONFIG_DIR", "HR_INPUT_DIR", "HR_STATE_DIR"])


class BuildContextTests(unittest.TestCase):
    def test_private_material_never_enters_the_build_context(self):
        text = read(DOCKERIGNORE)
        for pattern in (
            ".venv",
            "__pycache__",
            ".env",
            "*.sqlite3",
            "*.pem",
            "*.key",
            "*password*",
            "*session-key*",
            "tests",
            "PRIVATE_",
        ):
            self.assertIn(pattern, text)

    def test_the_compose_file_is_not_sent_to_the_builder(self):
        self.assertIn("compose.yaml", read(DOCKERIGNORE))


if __name__ == "__main__":
    unittest.main()
