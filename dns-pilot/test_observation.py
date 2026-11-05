"""Observation sampler contract: aggregates only, never individual domains."""
import json
import importlib.util
import contextlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'observe_queries.py'
SPEC = importlib.util.spec_from_file_location('observe_queries', SCRIPT)
OBSERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBSERVER)


class SnapshotTests(unittest.TestCase):
    def test_rate_limit_messages_match_real_hyphenated_text(self):
        self.assertTrue(hasattr(OBSERVER, 'count_rate_limit_warnings'))
        self.assertEqual(OBSERVER.count_rate_limit_warnings(
            'Rate-limiting client router\nclient was rate limited\nrate-limit warning\n'
            'FTLCONF_dns_rateLimit=1000/60\nnormal request'), 3)

    def test_query_timeout_becomes_gap_sample(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(OBSERVER, 'OUT', Path(tmp)), \
                mock.patch.object(OBSERVER.sys, 'argv', ['observe_queries.py', '--once']), \
                mock.patch.object(OBSERVER, 'sample', side_effect=subprocess.TimeoutExpired('query', 30)), \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                OBSERVER.main()
            except subprocess.TimeoutExpired:
                self.fail('A bounded query timeout must be recorded as a monitoring gap')
            row = json.loads(Path(tmp, 'samples.jsonl').read_text())
            self.assertEqual(row['error'], 'sampling_failed')
            self.assertEqual(row['detail'], 'timeout')

    def snapshot(self, rows):
        self.assertTrue(hasattr(OBSERVER, 'snapshot_query'), 'One-statement snapshot query is missing')
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE queries(timestamp REAL,domain TEXT,client TEXT,status INTEGER)')
        db.executemany('INSERT INTO queries VALUES (?,?,?,?)', rows)
        return json.loads(db.execute(OBSERVER.snapshot_query(1000, 30)).fetchone()[0])

    def test_one_snapshot_reconciles_totals_and_half_open_window(self):
        r = self.snapshot([(900, 'a.test', 'router', 2), (970, 'a.test', 'router', 2),
                           (971, 'a.test', 'router', 14), (999, 'b.test', 'router', 17),
                           (1000, 'future.test', 'router', 3)])
        self.assertEqual(r['queries_total_all_time'], 4)
        self.assertEqual(r['queries_in_window'], 3)
        self.assertEqual(r['distinct_domains_in_window'], 2)
        self.assertEqual(sum(r['status_in_window'].values()), 3)
        self.assertEqual(sum(r['clients_in_window'].values()), 3)
        self.assertEqual(r['status_in_window']['14'], 1)  # Never deduplicate retries.

    def test_measured_60_second_peak_is_not_15_minute_average(self):
        rows = [(950 + n / 1000, 'burst.test', 'router', 2) for n in range(1100)]
        r = self.snapshot(rows + [(980, 'other.test', 'other', 3),
                                  (990, 'a.test', 'router', 2)])
        self.assertEqual(r['peak_queries_in_60s_by_client']['router'], 1101)
        self.assertEqual(r['queries_last_60s_by_client']['router'], 1101)
        self.assertEqual(r['peak_queries_in_60s_by_client']['other'], 1)

    def test_empty_snapshot_has_empty_maps_and_zero_counts(self):
        r = self.snapshot([])
        self.assertEqual(r['queries_in_window'], 0)
        self.assertEqual(r['status_in_window'], {})
        self.assertEqual(r['peak_queries_in_60s_by_client'], {})


class ObservationTests(unittest.TestCase):
    def test_sampler_never_selects_individual_domains(self):
        self.assertTrue(SCRIPT.is_file(), 'Observation sampler is missing')
        source = SCRIPT.read_text()
        for forbidden in ['SELECT domain', 'GROUP_CONCAT(domain', 'GROUP_CONCAT(DISTINCT domain) FROM queries WHERE timestamp > ']:
            self.assertNotIn(forbidden, source)
        self.assertIn('PRIVATE_OBSERVATION', source)
        self.assertIn('count(DISTINCT domain)', source)

    def test_single_sample_shape(self):
        # Never write test samples into the live observation series.
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, STARLINK_OBSERVATION_DIR=tmp)
            result = subprocess.run(
                ['python3', str(SCRIPT), '--once'],
                capture_output=True, text=True, timeout=120, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            sample = json.loads(result.stdout)
            written = Path(tmp, 'samples.jsonl').read_text().splitlines()
            self.assertEqual(len(written), 1)
        for key in [
            'utc', 'window_seconds', 'queries_in_window', 'distinct_domains_in_window',
            'status_in_window', 'clients_in_window', 'rate_limit_warnings', 'db_bytes',
        ]:
            self.assertIn(key, sample)
        self.assertNotIn('domains', sample)
        self.assertIsInstance(sample['status_in_window'], dict)


if __name__ == '__main__':
    unittest.main()
