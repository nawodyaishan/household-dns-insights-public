"""The old proof-of-concept CLI still works, now through the shared implementation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "dns-pilot" / "destination_report.py"


class LegacyCliTests(unittest.TestCase):
    def test_cli_help_runs_from_the_project_environment(self):
        result = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--snapshot", result.stdout)

    def test_render_from_a_saved_snapshot_needs_no_docker_or_network(self):
        rows = [
            {
                "id": index,
                "timestamp": 100 + index,
                "type": 1,
                "status": 2,
                "domain": "example.com",
                "client": "192.168.1.1",
                "forward": None,
                "additional_info": None,
                "list_id": None,
                "reply_type": 4,
                "ede": None,
                "reply_time": 0.01,
                "dnssec": 0,
            }
            for index in range(2)
        ]
        snapshot = {
            "schema_version": 1,
            "start_epoch": 100,
            "end_epoch": 3700,
            "captured_utc": "2026-10-23T06:00:00Z",
            "retained_rows": 2,
            "oldest_epoch": 90,
            "newest_epoch": 200,
            "window_count": 2,
            "observations": rows,
            "rate_context": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            snapshot_path = workspace / "observations.json"
            cache_path = workspace / "classifications.json"
            output = workspace / "report"
            snapshot_path.write_text(json.dumps(snapshot))
            cache_path.write_text(json.dumps({"revision": "test", "mappings": []}))
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--snapshot",
                    str(snapshot_path),
                    "--cache",
                    str(cache_path),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("observations.json", "classifications.json", "report.json", "report.html"):
                self.assertTrue((output / name).is_file(), name)
            page = (output / "report.html").read_text()
            self.assertIn("example.com", page)
            self.assertNotIn("<script src=", page)
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["summary"]["raw_rows"], 2)
            self.assertIn("observations_sha256", report["source"])


if __name__ == "__main__":
    unittest.main()
