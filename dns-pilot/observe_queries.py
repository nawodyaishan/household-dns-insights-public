#!/usr/bin/env python3
"""Resumable, private DNS observation sampler.

Writes aggregate counts only: no domain names, no URLs, no client hostnames.
Output goes to PRIVATE_OBSERVATION/ (git-ignored) as one JSON object per line.
Run with --once for a single sample, or --loop for the 24-48 hour window.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get('STARLINK_OBSERVATION_DIR', ROOT / 'PRIVATE_OBSERVATION'))
CONTAINER = 'starlink-dns-pilot'
DB = '/etc/pihole/pihole-FTL.db'


def sql(query):
    out = subprocess.check_output(
        ['docker', 'exec', CONTAINER, 'pihole-FTL', 'sqlite3', DB,
         'PRAGMA query_only=ON; ' + query], text=True, timeout=30
    ).strip()
    return out


def snapshot_query(now, window_seconds):
    """One SQLite statement: all database metrics share the same read snapshot.

    Query counts are persisted rows, not unique resolutions or connections.
    Peak rates use timestamp-based inclusive 60-second spans per apparent client,
    not a rolling 15-minute average or a reconstruction of FTL's limiter state.
    """
    now, window_seconds = int(now), int(window_seconds)
    if window_seconds <= 0:
        raise ValueError('window_seconds must be positive')
    since = now - window_seconds
    return f"""WITH retained AS (SELECT * FROM queries WHERE timestamp < {now}),
        window AS (SELECT * FROM retained WHERE timestamp >= {since}),
        rates AS (
            SELECT client,timestamp,count(*) OVER (
                PARTITION BY client ORDER BY timestamp
                RANGE BETWEEN 60 PRECEDING AND CURRENT ROW) AS n
            FROM retained WHERE timestamp >= {min(since, now - 60) - 60}
        )
        SELECT json_object(
            'queries_total_all_time',(SELECT count(*) FROM retained),
            'queries_in_window',(SELECT count(*) FROM window),
            'distinct_domains_in_window',(SELECT count(DISTINCT domain) FROM window),
            'oldest_row_utc',(SELECT datetime(min(timestamp),'unixepoch') FROM retained),
            'newest_row_utc',(SELECT datetime(max(timestamp),'unixepoch') FROM retained),
            'status_in_window',json((SELECT json_group_object(status,n) FROM
                (SELECT status,count(*) n FROM window GROUP BY status))),
            'clients_in_window',json((SELECT json_group_object(client,n) FROM
                (SELECT client,count(*) n FROM window GROUP BY client))),
            'queries_last_60s_by_client',json((SELECT json_group_object(client,n) FROM
                (SELECT client,count(*) n FROM retained WHERE timestamp >= {now - 60}
                 GROUP BY client))),
            'peak_queries_in_60s_by_client',json((SELECT json_group_object(client,n) FROM
                (SELECT client,max(n) n FROM rates WHERE timestamp >= {since}
                 GROUP BY client)))
        );"""


def count_rate_limit_warnings(text):
    pattern = re.compile(r'\brate[ ._-]?limit(?:ing|ed|\s+warning)\b', re.IGNORECASE)
    return sum(bool(pattern.search(line)) for line in text.splitlines())


def sample(window_seconds=900):
    now = int(time.time())
    row = json.loads(sql(snapshot_query(now, window_seconds)))
    row.update({
        'utc': datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'),
        'window_seconds': window_seconds,
        'count_semantics': 'persisted DNS query rows; no retry deduplication',
        'total_semantics': 'retained rows before utc; legacy all_time key is not a lifetime counter',
        'rate_semantics': 'persisted rows per apparent client in 60-second spans; not limiter headroom',
        'attribution': 'router-forwarded observations; origin device unknown',
        'snapshot_consistent': True,
    })
    logs = subprocess.run(
        ['docker', 'logs', CONTAINER], capture_output=True, text=True, check=True, timeout=15
    )
    row['rate_limit_warnings'] = count_rate_limit_warnings(logs.stdout + logs.stderr)
    row['rate_limit_warning_scope'] = 'available container logs; cumulative, rotation-limited'
    row['db_bytes'] = int(
        subprocess.check_output(
            ['docker', 'exec', CONTAINER, 'stat', '-c', '%s', DB], text=True
        ).strip()
    )
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--hours', type=float, default=48.0)
    parser.add_argument('--interval', type=int, default=900)
    args = parser.parse_args()
    OUT.mkdir(mode=0o700, exist_ok=True)
    target = OUT / 'samples.jsonl'
    deadline = time.time() + args.hours * 3600
    while True:
        try:
            row = sample(args.interval)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            row = {
                'utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'error': 'sampling_failed',
                'detail': 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else str(exc.returncode),
            }
        with target.open('a') as handle:
            handle.write(json.dumps(row, sort_keys=True) + '\n')
        if args.once or not args.loop or time.time() >= deadline:
            print(json.dumps(row, indent=2, sort_keys=True))
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    sys.exit(main())
