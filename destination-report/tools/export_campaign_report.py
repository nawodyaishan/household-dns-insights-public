#!/usr/bin/env python3
"""Explicit owner-only export of one immutable campaign projection to a private file."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from household_report.campaign_reporting import CampaignReportService
from household_report.storage import open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--format", choices=("csv", "json"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    parent = args.output.parent
    if parent.is_symlink() or any(path.is_symlink() for path in parent.parents):
        parser.error("Symlinked export parent refused")
    if not parent.is_dir() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
        parser.error("Export directory must exist and be private")
    if args.output.exists() or args.output.is_symlink():
        parser.error("Refusing to replace preserved report")
    with open_store(args.db) as store:
        reports = CampaignReportService(store)
        if args.format == "json":
            content = json.dumps(reports.export_json(args.report), sort_keys=True, indent=2)
        else:
            content = reports.export_csv(args.report)
    payload = content.encode("utf-8-sig" if args.format == "csv" else "utf-8")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    print(
        json.dumps(
            {
                "report_id": args.report,
                "format": args.format,
                "bytes": len(payload),
                "written": args.output.name,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
