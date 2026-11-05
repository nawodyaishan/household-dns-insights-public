"""Create the local owner password record and session key (owner-run, offline).

Example:

    uv run --project destination-report python tools/set_password.py \
        --password-file ~/.config/starlink-monitoring/destination-report/password \
        --session-key-file ~/.config/starlink-monitoring/destination-report/session-key

Both files are written with mode 0600 inside an existing 0700 directory. Existing
files are kept unless ``--force`` is given. Nothing is printed except paths and
non-reversible metadata.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import stat
import sys
from pathlib import Path

from household_report.web import AuthError, hash_password


def _prepare(path: Path, *, force: bool) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)
    mode = stat.S_IMODE(parent.stat().st_mode)
    if mode & 0o077:
        raise SystemExit(f"Refusing insecure directory mode {mode:o}: {parent}")
    if path.exists() and not force:
        raise SystemExit(f"Refusing to overwrite existing file (use --force): {path}")


def _write(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(value + "\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise SystemExit(f"Written file has unsafe permissions: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--session-key-file", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)

    password_file: Path = arguments.password_file.expanduser()
    key_file: Path = arguments.session_key_file.expanduser()
    _prepare(password_file, force=arguments.force)
    _prepare(key_file, force=arguments.force)
    if password_file.resolve() == key_file.resolve():
        raise SystemExit("Password and session key must be different files")

    try:
        first = getpass.getpass("Owner password (at least 12 characters): ")
        second = getpass.getpass("Repeat the password: ")
    except (EOFError, KeyboardInterrupt):
        raise SystemExit("Cancelled") from None
    if first != second:
        raise SystemExit("Passwords did not match")
    try:
        record = hash_password(first)
    except AuthError as error:
        raise SystemExit(str(error)) from None

    _write(password_file, record)
    _write(key_file, base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))
    print(f"Wrote password record: {password_file}")
    print(f"Wrote session key: {key_file}")
    print("Both files are 0600. Never commit or share them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
