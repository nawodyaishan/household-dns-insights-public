"""Host-side commands: explicit, bounded, private and append-only.

Every test uses a fake Docker runner, so no container starts, no resolver is read and
no packet leaves the machine. The files the commands write are checked for mode 0600,
exact payload preservation, refusal to overwrite and explicit failure records.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(f"household_tool_{name}", TOOLS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed(command, stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=command, returncode=returncode, stdout=stdout, stderr=stderr
    )


class FakeRunner:
    def __init__(
        self,
        *,
        stdout="",
        returncode=0,
        stderr="",
        error: BaseException | None = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.error = error
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if self.error is not None:
            raise self.error
        return completed(command, self.stdout, self.returncode, self.stderr)


def snapshot_payload(start: int, end: int, *, window_count: int | None = None) -> str:
    rows = [
        {
            "id": 1,
            "timestamp": start + 1,
            "type": "A",
            "status": "FORWARDED",
            "domain": "private.example.test",
            "client": "192.168.1.23",
            "forward": "1.1.1.1",
        },
        {
            "id": 2,
            "timestamp": start + 2,
            "type": "AAAA",
            "status": "GRAVITY",
            "domain": "blocked.example.test",
            "client": "192.168.1.70",
            "forward": None,
        },
    ]
    return json.dumps(
        {
            "schema_version": 1,
            "start_epoch": start,
            "end_epoch": end,
            "captured_utc": "2026-10-23T04:01:00Z",
            "retained_rows": 2,
            "oldest_epoch": start,
            "newest_epoch": end - 1,
            "window_count": len(rows) if window_count is None else window_count,
            "observations": rows,
        }
    )


class ExportSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.input_dir = self.root / "input"
        self.input_dir.mkdir(mode=0o700)
        self.tool = load_tool("export_snapshot")
        self.end = int(time.time()) - 3600
        self.start = self.end - 600

    def run_tool(self, runner, *, start=None, end=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = self.tool.main(
                [
                    "--input-dir",
                    str(self.input_dir),
                    "--start",
                    str(self.start if start is None else start),
                    "--end",
                    str(self.end if end is None else end),
                ],
                runner=runner,
            )
        return code, output.getvalue()

    def test_exports_one_closed_window_read_only_and_private(self):
        payload = snapshot_payload(self.start, self.end)
        runner = FakeRunner(stdout=payload)
        code, output = self.run_tool(runner)
        self.assertEqual(code, 0)
        target = self.input_dir / f"snapshot-{self.start}-{self.end}.json"
        self.assertEqual(target.read_text(), payload)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        command = runner.commands[0]
        self.assertEqual(command[:2], ["docker", "exec"])
        self.assertIn("PRAGMA query_only=ON; SELECT json_object(", command[-1])
        self.assertIn("pihole-FTL", command)
        summary = json.loads(output)
        self.assertEqual(summary["rows"], 2)
        for private in ("private.example.test", "blocked.example.test", "192.168.1.23"):
            self.assertNotIn(private, output)

    def test_refuses_an_open_or_too_wide_window_before_running(self):
        runner = FakeRunner(stdout=snapshot_payload(self.start, self.end))
        with self.assertRaises(SystemExit):
            self.run_tool(runner, start=self.end - 10, end=int(time.time()))
        with self.assertRaises(SystemExit):
            self.run_tool(runner, start=self.end - 7200)
        self.assertEqual(runner.commands, [])
        self.assertEqual(list(self.input_dir.iterdir()), [])

    def test_refuses_an_insecure_directory(self):
        os.chmod(self.input_dir, 0o755)
        with self.assertRaises(SystemExit):
            self.run_tool(FakeRunner(stdout=snapshot_payload(self.start, self.end)))

    def test_refuses_to_overwrite_preserved_evidence(self):
        target = self.input_dir / f"snapshot-{self.start}-{self.end}.json"
        target.write_text("already preserved")
        runner = FakeRunner(stdout=snapshot_payload(self.start, self.end))
        with self.assertRaises(SystemExit):
            self.run_tool(runner)
        self.assertEqual(target.read_text(), "already preserved")
        self.assertEqual(runner.commands, [])

    def test_writes_nothing_when_the_extraction_is_inconsistent(self):
        cases = [
            snapshot_payload(self.start, self.end, window_count=99),
            json.dumps({"start_epoch": self.start, "end_epoch": self.end}),
            "not json",
        ]
        for payload in cases:
            with self.subTest(payload=payload[:30]):
                with self.assertRaises(SystemExit):
                    self.run_tool(FakeRunner(stdout=payload))
                self.assertEqual(list(self.input_dir.iterdir()), [])

    def test_writes_nothing_when_the_container_read_fails(self):
        with self.assertRaises(SystemExit):
            self.run_tool(FakeRunner(stdout="", returncode=1))
        self.assertEqual(list(self.input_dir.iterdir()), [])


class PresencePollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.input_dir = Path(self.directory.name) / "input"
        self.input_dir.mkdir(mode=0o700)
        self.tool = load_tool("poll_presence")
        self.body = json.dumps(
            {
                "wifiGetClients": {
                    "clients": [
                        {
                            "name": "private-laptop",
                            "macAddress": "aa:bb:cc:dd:ee:01",
                            "ipAddress": "192.168.1.23",
                            "iface": "RF_5GHZ",
                            "role": "CLIENT",
                        }
                    ]
                }
            }
        )

    def run_tool(self, runner, *extra):
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            patch.object(self.tool.time, "sleep"),
        ):
            code = self.tool.main(
                ["--input-dir", str(self.input_dir), *extra],
                runner=runner,
            )
        return code, output.getvalue()

    def envelopes(self):
        return [json.loads(path.read_text()) for path in sorted(self.input_dir.glob("*.json"))]

    def test_records_one_envelope_with_the_established_read_only_call(self):
        runner = FakeRunner(stdout=self.body)
        code, output = self.run_tool(runner, "--count", "1")
        self.assertEqual(code, 0)
        command = runner.commands[0]
        self.assertEqual(command[:5], ["docker", "run", "--rm", "--network", "host"])
        self.assertIn("fullstorydev/grpcurl:v1.9.3", command)
        self.assertIn('{"wifi_get_clients":{}}', command)
        self.assertIn("SpaceX.API.Device.Device/Handle", command)
        envelope = self.envelopes()[0]
        self.assertEqual(envelope["returncode"], 0)
        self.assertEqual(envelope["endpoint"], "192.168.1.1:9000")
        self.assertEqual(json.loads(envelope["stdout"]), json.loads(self.body))
        self.assertEqual(stat.S_IMODE(next(self.input_dir.glob("*.json")).stat().st_mode), 0o600)
        for private in ("private-laptop", "aa:bb:cc:dd:ee:01", "192.168.1.23"):
            self.assertNotIn(private, output)

    def test_a_failed_sample_is_an_explicit_error_not_absence(self):
        runner = FakeRunner(stdout="", returncode=1, stderr="collector failed")
        code, output = self.run_tool(runner, "--count", "1")
        self.assertEqual(code, 1)
        envelope = self.envelopes()[0]
        self.assertEqual(envelope["returncode"], 1)
        self.assertEqual(envelope["stderr"], "collector failed")
        self.assertEqual(envelope["stdout"], "")
        summary = json.loads(output[output.index("{") :])
        self.assertEqual(summary["failed"], 1)

    def test_a_local_timeout_is_recorded_as_a_gap(self):
        runner = FakeRunner(error=subprocess.TimeoutExpired(cmd="docker", timeout=15))
        code, _ = self.run_tool(runner, "--count", "1")
        self.assertEqual(code, 1)
        envelope = self.envelopes()[0]
        self.assertEqual(envelope["returncode"], -1)
        self.assertEqual(envelope["stderr"], "LOCAL_TIMEOUT")

    def test_refuses_unbounded_or_too_frequent_polling(self):
        for extra in (("--count", "0"), ("--count", "121"), ("--count", "1", "--interval", "1")):
            with self.subTest(extra=extra):
                with self.assertRaises(SystemExit):
                    self.run_tool(FakeRunner(stdout=self.body), *extra)
        self.assertEqual(list(self.input_dir.iterdir()), [])

    def test_refuses_an_insecure_directory(self):
        os.chmod(self.input_dir, 0o755)
        with self.assertRaises(SystemExit):
            self.run_tool(FakeRunner(stdout=self.body), "--count", "1")

    def test_refuses_to_overwrite_an_existing_evidence_file(self):
        target = self.input_dir / "presence-20261023T040000Z-00.json"
        target.write_text("preserved")
        with self.assertRaises(SystemExit):
            self.tool._write_new(target, "new")
        self.assertEqual(target.read_text(), "preserved")


class ImportInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.input_dir = self.root / "input"
        self.input_dir.mkdir(mode=0o700)
        self.database = self.root / "app.sqlite3"
        self.tool = load_tool("import_inputs")
        self.start = 1_792_728_000
        self.end = self.start + 3600
        (self.input_dir / f"snapshot-{self.start}-{self.end}.json").write_text(
            snapshot_payload(self.start, self.end)
        )
        self.presence = {
            "start": "2026-10-23T04:00:05Z",
            "end": "2026-10-23T04:00:05Z",
            "endpoint": "192.168.1.1:9000",
            "tail": [],
            "returncode": 0,
            "stdout": json.dumps(
                {
                    "wifiGetClients": {
                        "clients": [
                            {
                                "name": "private-laptop",
                                "macAddress": "aa:bb:cc:dd:ee:01",
                                "ipAddress": "192.168.1.23",
                                "iface": "RF_5GHZ",
                                "role": "CLIENT",
                            }
                        ]
                    }
                }
            ),
            "stderr": "",
        }
        (self.input_dir / "presence-20261023T040005Z-00.json").write_text(json.dumps(self.presence))

    def run_tool(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = self.tool.main(["--input-dir", str(self.input_dir), "--db", str(self.database)])
        return code, json.loads(output.getvalue())

    def test_imports_once_and_never_twice(self):
        code, report = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(report["snapshots"], {"imported": 1, "unchanged": 0, "invalid": []})
        self.assertEqual(report["polls"]["imported"], 1)
        code, report = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(report["snapshots"], {"imported": 0, "unchanged": 1, "invalid": []})
        self.assertEqual(report["polls"]["unchanged"], 1)
        self.assertTrue(self.database.is_file())

    def test_namespace_rules_file_is_not_treated_as_a_snapshot(self):
        (self.input_dir / "gaming-namespaces.json").write_text(
            '{"schema_version":1,"revision":"synthetic","rules":[]}'
        )
        code, report = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(report["snapshots"]["invalid"], [])
        self.assertEqual(report["snapshots"]["imported"], 1)
        self.assertEqual(report["polls"]["invalid"], [])

    def test_invalid_snapshot_still_fails_when_namespace_file_is_present(self):
        (self.input_dir / "gaming-namespaces.json").write_text(
            '{"schema_version":1,"revision":"synthetic","rules":[]}'
        )
        (self.input_dir / "snapshot-broken.json").write_text("{}")
        code, report = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(report["snapshots"]["invalid"], ["snapshot-broken.json"])

    def test_invalid_files_are_named_and_fail_the_command(self):
        (self.input_dir / "snapshot-broken.json").write_text("{}")
        (self.input_dir / "presence-broken.json").write_text("[]")
        code, report = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(report["snapshots"]["invalid"], ["snapshot-broken.json"])
        self.assertEqual(report["polls"]["invalid"], ["presence-broken.json"])

    def test_missing_input_directory_is_refused(self):
        with self.assertRaises(SystemExit):
            self.tool.main(["--input-dir", str(self.root / "missing"), "--db", str(self.database)])


if __name__ == "__main__":
    unittest.main()
