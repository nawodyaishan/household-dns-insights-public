"""Shared credential parser for provider and Exa.

Supports two explicit formats:
- bare: single-line secret value
- dotenv: KEY=VALUE lines with strict parsing (no shell evaluation)

Never auto-loads .env.local; only reads explicitly selected files.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path


class CredentialError(ValueError):
    """Credential file is missing, malformed, or unsafe."""


def read_bare_secret(path: Path) -> str:
    """Read a bare secret file (single value, no parsing)."""
    _validate_secret_file(path)
    value = path.read_text().strip()
    if not value or any(c.isspace() for c in value):
        raise CredentialError(f"Bare secret is empty or contains whitespace: {path}")
    return value


def read_dotenv_secret(path: Path, variable: str) -> str:
    """Read a specific variable from a dotenv-formatted file.

    Strict parsing:
    - KEY=VALUE lines only
    - Values may be bare, single-quoted, or double-quoted
    - No interpolation, escapes, multiline, command substitution, or inline comments
    - Blank lines and # comments allowed
    - Duplicate keys rejected even if equal
    """
    _validate_secret_file(path)

    content = path.read_text()
    assignments: dict[str, str] = {}

    for line_num, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Match: KEY=VALUE where VALUE can be bare, 'single', or "double" quoted
        match = re.fullmatch(
            r'([A-Za-z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([A-Za-z0-9_\-.:/]+))',
            line,
        )
        if match is None:
            raise CredentialError(
                f"{path.name} line {line_num}: unsupported syntax or shell expressions"
            )

        var_name, double_q, single_q, bare = match.groups()
        value = double_q if double_q is not None else (single_q if single_q is not None else bare)

        if var_name in assignments:
            raise CredentialError(f"Duplicate key in {path.name}: {var_name}")
        assignments[var_name] = value

    if variable not in assignments:
        raise CredentialError(f"Variable {variable!r} not found in {path.name}")

    value = assignments[variable].strip()
    if not value:
        raise CredentialError(f"Variable {variable!r} in {path.name} is empty")

    return value


def read_credential(path: Path, format: str, variable: str) -> str:
    """Read a credential according to its declared format."""
    if format == "bare":
        return read_bare_secret(path)
    elif format == "dotenv":
        return read_dotenv_secret(path, variable)
    else:
        raise CredentialError(f"Unknown credential format: {format!r}")


def _validate_secret_file(path: Path) -> None:
    """Validate secret file ownership and permissions."""
    try:
        info = path.stat()
    except FileNotFoundError as e:
        raise CredentialError(f"Secret file not found: {path}") from e

    if stat.S_IMODE(info.st_mode) & 0o077:
        raise CredentialError(f"Secret file must not be group/other accessible: {path}")

    if info.st_uid != Path(__file__).stat().st_uid:  # Use current file's owner as reference
        # Actually check against current process UID
        import os

        if info.st_uid != os.getuid():
            raise CredentialError(f"Secret file must be owned by the running user: {path}")


__all__ = [
    "CredentialError",
    "read_bare_secret",
    "read_dotenv_secret",
    "read_credential",
]
