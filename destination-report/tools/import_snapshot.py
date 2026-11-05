#!/usr/bin/env python3
"""Explicit host-side snapshot import. Not a web job and never a live FTL migration.

Reads one preserved extraction payload and writes it into the application SQLite
store, preserving every row. Run from the resolved project environment, for example::

    uv run --project destination-report python destination-report/tools/import_snapshot.py \
        --snapshot PRIVATE_OBSERVATION/2026-10-23_0400-0500Z.json \
        --db ~/.local/share/household-report/app.sqlite3 \
        --datasource pihole-ftl-live

This command performs no network access and never starts a resolver change.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from household_report.contracts import Period
from household_report.reporting import load_snapshot
from household_report.storage import open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--datasource", required=True, help="stable local source identity")
    args = parser.parse_args(argv)

    snapshot, raw = load_snapshot(args.snapshot)
    with open_store(args.db) as store:
        ref = store.import_snapshot(snapshot, datasource=args.datasource)
        period = Period(ref.period.start_epoch, ref.period.end_epoch)
        digest = store.period_digest(ref.snapshot_id, period)
    print(
        json.dumps(
            {
                "snapshot_id": ref.snapshot_id,
                "datasource": ref.datasource,
                "rows": ref.window_count,
                "period": [period.start_epoch, period.end_epoch],
                "period_digest": digest,
                "bytes": len(raw),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
