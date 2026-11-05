#!/usr/bin/env python3
"""Owner-only offline preview, backup, verification, isolated restore and retirement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from household_report.campaign_retirement import CampaignRetirement
from household_report.storage import open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview")
    preview.add_argument("--campaign", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--archive", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    retire = commands.add_parser("retire")
    retire.add_argument("--campaign", required=True)
    retire.add_argument("--digest", required=True)
    retire.add_argument("--backup-choice", choices=("backed_up", "declined"), required=True)
    retire.add_argument("--confirm", required=True, help="Repeat the campaign ID exactly")
    args = parser.parse_args(argv)
    if args.command == "retire" and args.confirm != args.campaign:
        parser.error("Explicit campaign ID confirmation is required")
    if args.command == "restore":
        # Never open or migrate the active database merely to verify/restore a backup.
        service = CampaignRetirement(None, input_dir=args.input_dir)
        result = service.restore(args.archive, args.destination)
    elif args.command == "verify":
        service = CampaignRetirement(None, input_dir=args.input_dir)
        result = service.verify(args.archive)
    else:
        with open_store(args.db) as store:
            service = CampaignRetirement(store, input_dir=args.input_dir)
            if args.command == "preview":
                result = service.preview(args.campaign)
            elif args.command == "backup":
                result = service.backup(args.archive)
            else:
                result = service.retire(
                    args.campaign, expected_digest=args.digest, backup_choice=args.backup_choice
                )
    # No domain, client, raw row or path is printed to the console.
    if args.command == "preview":
        result = {
            key: value
            for key, value in result.items()
            if key in {"campaign_id", "state", "counts", "digest"}
        }
    else:
        result = (
            {"operation": args.command, "campaign_id": args.campaign}
            if args.command == "retire"
            else {
                "operation": args.command,
                "database_sha256": result["database_sha256"],
                "artifact_count": len(result["artifacts"]),
            }
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
