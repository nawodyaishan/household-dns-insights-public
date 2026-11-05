#!/usr/bin/env python3
"""Render inactive system-level service/timer from fixed offline operator settings."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def render(*, user: str, config: Path, python: Path, bridge: Path) -> tuple[str, str]:
    if user == "root" or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("Invalid non-root operator account")
    for path in (config, python, bridge):
        if not path.is_absolute() or any(ch.isspace() or ch == "%" for ch in str(path)):
            raise ValueError("Unit paths must be absolute and contain no whitespace or specifiers")
    settings = json.loads(config.read_text())
    writes = []
    for name in ("input_dir", "state_dir"):
        path = Path(settings[name])
        if not path.is_absolute() or any(ch.isspace() or ch == "%" for ch in str(path)):
            raise ValueError("Writable paths must be absolute and contain no specifiers")
        writes.append(path)
    service = f"""[Unit]
Description=Bounded household campaign capture bridge
Wants=docker.service network-online.target
After=docker.service network-online.target

[Service]
Type=oneshot
User={user}
ExecStart={python} {bridge} --config {config}
TimeoutStartSec=610
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths={writes[0]} {writes[1]}

[Install]
WantedBy=multi-user.target
"""
    # The host bridge checks private input/state modes; Docker access is
    # privileged in practice. No service is enabled by rendering these files.
    timer = """[Unit]
Description=Check bounded household campaign work once per minute

[Timer]
OnBootSec=60s
OnUnitInactiveSec=60s
Persistent=false
Unit=household-campaign-bridge.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    service, timer = render(
        user=args.user, config=args.config, python=args.python, bridge=args.bridge
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "household-campaign-bridge.service").write_text(service)
    (args.output / "household-campaign-bridge.timer").write_text(timer)
    print(
        json.dumps(
            {"rendered": ["household-campaign-bridge.service", "household-campaign-bridge.timer"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
