"""Packaged synthetic 120-hour campaign/recovery benchmark.

Run explicitly with ``task campaign-benchmark`` (which sets
``HR_BENCHMARK_TESTS=1``). The image is built from the current lock, then two
separate one-off containers execute ``tools/campaign_benchmark.py`` against the
same private temporary state directory:

1. ``prepare`` starts a five-day campaign, acknowledges/imports 120 hourly
   synthetic windows, freezes a to-date report, exports it and finalizes.
2. ``verify`` is a second process: it re-checks the frozen report digest,
   generates a completed-day report, then backs up, verifies and restores into an
   isolated empty directory.

Only synthetic rows and temporary directories are used. No resolver, Docker
socket, household evidence, credential or network endpoint is touched. The test
records peak RSS, CPU time, report latency and storage growth for ``tasks.md``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
COMPOSE = APP / "compose.yaml"
ENABLED = os.environ.get("HR_BENCHMARK_TESTS") == "1"


@unittest.skipUnless(ENABLED, "set HR_BENCHMARK_TESTS=1 (task campaign-benchmark)")
class CampaignBenchmark(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is required")
        if os.geteuid() == 0:
            raise unittest.SkipTest("run as the owner so bind-mounted state stays private")
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
        for directory in (cls.config, cls.input, cls.state):
            directory.mkdir(mode=0o700)

        cls.project = f"hrbench-{os.getpid()}"
        cls.env = {
            **os.environ,
            "HR_CONFIG_DIR": str(cls.config),
            "HR_INPUT_DIR": str(cls.input),
            "HR_STATE_DIR": str(cls.state),
            "HR_PORT": "8787",
            "AI_PROVIDER": "",
            "AI_MODEL_ID": "",
            "EXA_MCP_URL": "",
        }
        cls.compose = ["docker", "compose", "-p", cls.project, "-f", str(COMPOSE)]
        cls.addClassCleanup(cls.down)
        subprocess.run([*cls.compose, "build"], env=cls.env, check=True)

    @classmethod
    def down(cls) -> None:
        subprocess.run(
            [*cls.compose, "down", "--remove-orphans", "--volumes"],
            env=cls.env,
            capture_output=True,
            timeout=120,
        )

    @classmethod
    def benchmark(cls, phase: str) -> dict:
        command = [
            *cls.compose,
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "python",
            "app",
            "/app/tools/campaign_benchmark.py",
            "--db",
            "/state/benchmark.sqlite3",
            "--work-dir",
            "/state/benchmark",
            "--hours",
            "120",
            "--rows-per-hour",
            "120",
            phase,
        ]
        completed = subprocess.run(
            command, env=cls.env, capture_output=True, text=True, timeout=1800
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"{phase} failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )
        return json.loads(completed.stdout)

    def test_full_campaign_then_restart_recovery_and_restore(self):
        prepared = self.benchmark("prepare")
        self.assertEqual(prepared["hours"], 120)
        self.assertEqual(prepared["rows"], 120 * 120)
        self.assertEqual(prepared["campaign_state"], "complete")
        self.assertEqual(prepared["report_job_state"], "ready")
        self.assertGreater(prepared["report_json_bytes"], 0)
        self.assertGreater(prepared["database_bytes"], 0)
        self.assertGreater(prepared["artifact_bytes"], 0)
        self.assertGreater(prepared["peak_rss_kib"], 0)

        recovered = self.benchmark("verify")
        self.assertTrue(recovered["frozen_report_unchanged"])
        self.assertEqual(recovered["day_report_job"], "ready")
        self.assertGreater(recovered["day_report_seconds"], 0)
        self.assertGreater(recovered["archive_database_bytes"], 0)
        self.assertGreaterEqual(recovered["archive_artifact_count"], 120)
        self.assertEqual(recovered["restore_database_bytes"], recovered["archive_database_bytes"])
        self.assertEqual(recovered["restored_input_bytes"], recovered["archive_artifact_bytes"])

        print(
            "CAMPAIGN_BENCHMARK "
            + json.dumps({"prepare": prepared, "verify": recovered}, sort_keys=True)
        )


if __name__ == "__main__":
    unittest.main()
