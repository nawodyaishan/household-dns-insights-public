#!/usr/bin/env python3
"""Compatibility CLI for the proof-of-concept DNS report.

The implementation is no longer duplicated here: extraction, interpretation and
rendering live in ``household_report.reporting``. Run this entry point from the
project environment, for example::

    uv run --project destination-report python dns-pilot/destination_report.py --help

Without a snapshot it reads one closed hour from the running pilot through the
existing ``observe_queries.sql`` helper. Re-rendering a saved snapshot needs neither
Docker nor any network access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from household_report import reporting


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, help="saved observations.json to re-render")
    parser.add_argument("--cache", type=Path, required=True, help="local classifications.json")
    parser.add_argument("--start", type=int, help="closed window start (epoch seconds)")
    parser.add_argument("--end", type=int, help="closed window end (epoch seconds)")
    parser.add_argument("--output", type=Path, required=True, help="new private output directory")
    args = parser.parse_args(argv)

    if args.snapshot:
        snapshot, raw = reporting.load_snapshot(args.snapshot)
    else:
        if args.start is None or args.end is None:
            parser.error("Supply --snapshot, or a closed --start/--end window")
        if args.end > datetime.now(UTC).timestamp() - 60:
            parser.error("The window must end at least 60 seconds ago")
        from observe_queries import sql

        raw = sql(reporting.extraction_query(args.start, args.end)).encode()
        snapshot = json.loads(raw)

    cache_bytes = args.cache.read_bytes()
    report = reporting.build_report(snapshot, json.loads(cache_bytes))
    report["source"]["observations_sha256"] = hashlib.sha256(raw).hexdigest()
    report["source"]["classification_cache_sha256"] = hashlib.sha256(cache_bytes).hexdigest()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in (
        ("observations.json", raw),
        ("classifications.json", cache_bytes),
        ("report.json", json.dumps(report, indent=2).encode()),
        ("report.html", reporting.render_html(report).encode()),
    ):
        with (args.output / name).open("xb") as handle:
            handle.write(data)
    print(
        json.dumps(
            {
                "private_report": str(args.output / "report.html"),
                "window": report["window"],
                "summary": report["summary"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
