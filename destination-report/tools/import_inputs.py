#!/usr/bin/env python3
"""Explicit input import: preserved snapshot/presence files into the app database.

The application container mounts its input directory read-only and never walks the
resolver. This command imports what the owner has already exported, idempotently:
a snapshot is identified by its rows and a poll by its digest, so re-running it after
a restart imports nothing twice and never rewrites existing evidence.

    uv run --project destination-report python destination-report/tools/import_inputs.py \
        --input-dir ~/.local/share/household-report/input \
        --db ~/.local/share/household-report/app.sqlite3

Inside the packaged app the same command runs against the mounted input directory and
the private state volume. Only file names and counts are printed; row, client and
domain content stays in the database and the private files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from household_report.contracts import ContractError
from household_report.inventory import InventoryError, InventoryService
from household_report.reporting import ReportingError, load_snapshot, validate_snapshot
from household_report.storage import StorageError, open_store


def _snapshot_files(input_dir: Path) -> list[Path]:
    reserved_files = {"gaming-namespaces.json"}
    return sorted(
        path
        for path in input_dir.glob("*.json")
        if path.is_file()
        and not path.name.startswith("presence-")
        and path.name not in reserved_files
    )


def _presence_files(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("presence-*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument(
        "--datasource",
        default="pihole-ftl-live",
        help="stable local identity for imported snapshots",
    )
    args = parser.parse_args(argv)

    if not args.input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_dir}")

    snapshots_imported = snapshots_unchanged = 0
    snapshots_invalid: list[str] = []
    polls_imported = polls_unchanged = 0
    polls_invalid: list[str] = []

    with open_store(args.db) as store:
        inventory = InventoryService(store)
        for path in _snapshot_files(args.input_dir):
            try:
                snapshot, _ = load_snapshot(path)
                validate_snapshot(snapshot)
                reference = store.import_snapshot(snapshot, datasource=args.datasource)
            except (ReportingError, StorageError, ContractError, OSError, KeyError, TypeError):
                snapshots_invalid.append(path.name)
                continue
            if reference.inserted:
                snapshots_imported += 1
            else:
                snapshots_unchanged += 1

        for path in _presence_files(args.input_dir):
            try:
                result = inventory.import_poll_file(path)
            except (InventoryError, OSError, KeyError, TypeError, ValueError):
                polls_invalid.append(path.name)
                continue
            if result.get("inserted"):
                polls_imported += 1
            else:
                polls_unchanged += 1

    print(
        json.dumps(
            {
                "snapshots": {
                    "imported": snapshots_imported,
                    "unchanged": snapshots_unchanged,
                    "invalid": snapshots_invalid,
                },
                "polls": {
                    "imported": polls_imported,
                    "unchanged": polls_unchanged,
                    "invalid": polls_invalid,
                },
            },
            indent=2,
        )
    )
    return 0 if not snapshots_invalid and not polls_invalid else 1


if __name__ == "__main__":
    sys.exit(main())
