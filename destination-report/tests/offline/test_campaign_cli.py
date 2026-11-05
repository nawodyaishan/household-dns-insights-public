"""Typed campaign CLI: control and worker commands, sanitized and offline."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / "tools"
START = 1_800_000_000
HOUR = 3600
DAY = 24 * HOUR


def load_cli():
    spec = importlib.util.spec_from_file_location(
        "household_campaign_cli", TOOLS / "campaign_cli.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def namespace_file(rules=(), revision="r1"):
    return json.dumps({"schema_version": 1, "revision": revision, "rules": list(rules)}).encode()


class CampaignCliTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_cli()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / "app.sqlite3"
        self.namespace = Path(self.directory.name) / "gaming-namespaces.json"
        self.namespace.write_bytes(namespace_file())

    def run_cli(self, *args):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = self.mod.main(list(args))
        return code, json.loads(captured.getvalue() or "null")

    def base(self, now):
        return ["--db", str(self.db), "--namespace", str(self.namespace), "--now", str(now)]

    def test_source_check_is_read_only_and_distinguishes_mismatch(self):
        code, payload = self.run_cli(
            *self.base(START), "source-check", "--generation", "gen1", "--identity", "resolver-a"
        )
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["code"], "unknown_generation")
        self.run_cli(
            *self.base(START), "source-register", "--generation", "gen1", "--identity", "resolver-a"
        )
        code, payload = self.run_cli(
            *self.base(START), "source-check", "--generation", "gen1", "--identity", "resolver-a"
        )
        self.assertEqual(payload["code"], "ok")
        code, payload = self.run_cli(
            *self.base(START), "source-check", "--generation", "gen1", "--identity", "resolver-b"
        )
        self.assertEqual(payload["code"], "identity_mismatch")
        # source-check never rebinds identity.
        code, payload = self.run_cli(
            *self.base(START), "source-check", "--generation", "gen1", "--identity", "resolver-a"
        )
        self.assertTrue(payload["verified"])

    def test_start_refuses_unregistered_or_mismatched_identity(self):
        code, payload = self.run_cli(
            *self.base(START),
            "start",
            "--ack-empty",
            "--generation",
            "gen1",
            "--identity",
            "resolver-a",
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown_generation", payload["error"])
        self.run_cli(
            *self.base(START), "source-register", "--generation", "gen1", "--identity", "resolver-a"
        )
        code, payload = self.run_cli(
            *self.base(START),
            "start",
            "--ack-empty",
            "--generation",
            "gen1",
            "--identity",
            "resolver-b",
        )
        self.assertEqual(code, 2)
        self.assertIn("identity_mismatch", payload["error"])
        code, payload = self.run_cli(
            *self.base(START),
            "start",
            "--ack-empty",
            "--generation",
            "gen1",
            "--identity",
            "resolver-a",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "active")

    def test_bridge_status_reports_unavailable_without_file(self):
        code, payload = self.run_cli(
            *self.base(START),
            "bridge-status",
            "--status-file",
            str(Path(self.directory.name) / "missing.json"),
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "unavailable")

    def test_help_mentions_control_and_worker_commands(self):
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stdout(io.StringIO()):
                self.mod.main(["--db", str(self.db), "--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_start_status_and_planning(self):
        code, payload = self.run_cli(
            *self.base(START), "start", "--days", "3", "--retention", "7", "--ack-empty"
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["utc_bounds"][1] - payload["utc_bounds"][0], 72 * HOUR)
        self.assertEqual(payload["coverage"]["chunks_planned"], 72)
        code, status = self.run_cli(*self.base(START), "status")
        self.assertEqual(code, 0)
        self.assertEqual(status["state"], "active")
        # Sanitized output: no rule content, no domains.
        self.assertNotIn("rules_json", status)
        self.assertNotIn("games.example", json.dumps(status))

    def test_missing_and_unacknowledged_empty_rules_are_refused(self):
        self.namespace.unlink()
        code, payload = self.run_cli(*self.base(START), "start")
        self.assertEqual(code, 2)
        self.assertIn("missing", payload["error"])
        self.namespace.write_bytes(namespace_file())
        code, payload = self.run_cli(*self.base(START), "start")
        self.assertEqual(code, 2)
        self.assertIn("acknowledgment", payload["error"])

    def test_worker_flow_claims_and_acknowledges_typed_work(self):
        self.run_cli(*self.base(START), "start", "--days", "3", "--ack-empty")
        now = START + 72 * HOUR + 120
        code, payload = self.run_cli(
            *self.base(now), "claim-chunk", "--worker", "operator", "--limit", "1"
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(len(payload["claimed"]), 1)
        claim = payload["claimed"][0]
        self.assertIn("lease_token", claim)
        self.assertIn("campaign_id", claim)
        code, payload = self.run_cli(
            *self.base(now),
            "chunk-captured",
            "--chunk",
            claim["chunk_id"],
            "--token",
            claim["lease_token"],
            "--digest",
            "d" * 64,
        )
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["acknowledged"])
        self.assertTrue(
            self.run_cli(*self.base(now), "chunk-import-pending", "--chunk", claim["chunk_id"])[1][
                "queued"
            ]
        )
        self.assertTrue(
            self.run_cli(
                *self.base(now),
                "chunk-imported",
                "--chunk",
                claim["chunk_id"],
                "--outcome",
                "imported",
            )[1]["acknowledged"]
        )
        code, status = self.run_cli(*self.base(now), "status")
        self.assertEqual(code, 0)
        self.assertEqual(status["coverage"]["by_state"]["imported"], 1)

    def test_import_artifact_checks_digest_path_and_replays_after_import(self):
        self.run_cli(*self.base(START), "start", "--ack-empty")
        self.run_cli(
            *self.base(START), "source-register", "--generation", "gen1", "--identity", "resolver-a"
        )
        now = START + 3600 + 120
        claim = self.run_cli(
            *self.base(now), "claim-chunk", "--generation", "gen1", "--limit", "1"
        )[1]["claimed"][0]
        input_dir = Path(self.directory.name) / "input"
        input_dir.mkdir(mode=0o700)
        snapshot = {
            "schema_version": 2,
            "read_state": "ok",
            "source_generation": "gen1",
            "start_epoch": START,
            "end_epoch": START + 3600,
            "captured_utc": "2027-01-01T00:00:00Z",
            "retained_rows": 1,
            "oldest_epoch": START - 1,
            "window_count": 0,
            "observations": [],
        }
        raw = json.dumps(snapshot).encode()
        path = input_dir / "capture-safe.json"
        path.write_bytes(raw)
        os.chmod(path, 0o600)
        digest = hashlib.sha256(raw).hexdigest()
        self.run_cli(
            *self.base(now),
            "chunk-captured",
            "--chunk",
            claim["chunk_id"],
            "--token",
            claim["lease_token"],
            "--path",
            path.name,
            "--digest",
            digest,
        )
        self.run_cli(*self.base(now), "chunk-import-pending", "--chunk", claim["chunk_id"])
        args = (
            *self.base(now),
            "import-artifact",
            "--campaign",
            claim["campaign_id"],
            "--chunk",
            claim["chunk_id"],
            "--name",
            path.name,
            "--digest",
            digest,
        )
        with patch.dict(os.environ, {"HR_INPUT_DIR": str(input_dir)}):
            self.assertEqual(self.run_cli(*args)[1]["state"], "successful_empty")
            self.assertEqual(self.run_cli(*args)[1]["state"], "successful_empty")
            self.assertEqual(self.run_cli(*args[:-1], "0" * 64)[0], 2)
            (input_dir / "capture-link.json").symlink_to(path)
            altered = list(args)
            altered[altered.index("--name") + 1] = "capture-link.json"
            self.assertEqual(self.run_cli(*altered)[0], 2)
            altered[altered.index("--name") + 1] = "../escape.json"
            self.assertEqual(self.run_cli(*altered)[0], 2)

    def test_worker_cannot_request_more_than_ten_chunks(self):
        self.run_cli(*self.base(START), "start", "--days", "3", "--ack-empty")
        code, payload = self.run_cli(
            *self.base(START + 72 * HOUR + 120), "claim-chunk", "--limit", "11"
        )
        self.assertEqual(code, 2)
        self.assertIn("between 1 and 10", payload["error"])

    def test_finish_extend_and_finalize_via_cli(self):
        self.run_cli(*self.base(START), "start", "--days", "5", "--ack-empty")
        now = START + 10 * HOUR
        code, finished = self.run_cli(*self.base(now), "finish")
        self.assertEqual(code, 0)
        self.assertEqual(finished["state"], "finalizing")
        self.assertEqual(finished["utc_bounds"][1], START + 10 * HOUR)
        code, payload = self.run_cli(*self.base(now), "extend", "--hours", "1")
        self.assertEqual(code, 2)
        self.assertIn("active", payload["error"])

    def test_full_offline_campaign_to_complete_with_gaps(self):
        self.run_cli(*self.base(START), "start", "--days", "3", "--ack-empty")
        now = START + 72 * HOUR + 120
        claims = []
        for _ in range(8):
            code, payload = self.run_cli(
                *self.base(now), "claim-chunk", "--worker", "operator", "--limit", "10"
            )
            self.assertEqual(code, 0, payload)
            self.assertLessEqual(len(payload["claimed"]), 10)
            claims.extend(payload["claimed"])
        self.assertEqual(len(claims), 72)
        code, payload = self.run_cli(*self.base(now), "finalize")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "finalizing")
        code, payload = self.run_cli(*self.base(now + DAY), "finalize")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["state"], "complete_with_gaps")
        # Without imports every planned window stays a visible gap.
        self.assertEqual(payload["coverage"]["unresolved_chunks"], 72)

    def test_report_job_metadata_via_cli(self):
        self.run_cli(*self.base(START), "start", "--days", "3", "--ack-empty")
        code, payload = self.run_cli(
            *self.base(START), "job-create", "--dedup", "k1", "--params", '{"day":"2026-10-24"}'
        )
        self.assertEqual(code, 0, payload)
        job_id = payload["job_id"]
        code, payload = self.run_cli(*self.base(START), "job-claim")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["job_id"], job_id)
        self.assertTrue(
            self.run_cli(
                *self.base(START),
                "job-finish",
                "--job",
                job_id,
                "--token",
                payload["lease_token"],
                "--state",
                "ready",
            )[1]["acknowledged"]
        )


if __name__ == "__main__":
    unittest.main()
