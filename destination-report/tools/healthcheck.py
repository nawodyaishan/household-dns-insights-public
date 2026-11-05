#!/usr/bin/env python3
"""Container health probe for the loopback listener.

Tries the configured scheme's public ``/healthz`` on 127.0.0.1. A self-signed owner
certificate is accepted because the probe never leaves the container's own loopback
interface and verifies nothing else. No secret and no household data are read.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _approved_target() -> tuple[int, str]:
    """Probe the first allowlisted host:port as that host; loopback stays plain.

    Published LAN profiles allow only the approved public host, so the probe must
    present exactly that Host header while still staying on 127.0.0.1.
    """
    entries = [
        entry.strip()
        for entry in os.environ.get("HR_ALLOWED_HOSTS", "").split(",") or []
        if entry.strip()
    ]
    if not entries:
        return DEFAULT_PORT, ""
    first = entries[0]
    if ":" not in first:
        # Host-only or unparseable entries: fail safe to the plain local probe.
        return DEFAULT_PORT, ""
    port = DEFAULT_PORT
    candidate = first.rsplit(":", 1)[1]
    if candidate.isdigit():
        port = int(candidate)
    if first.startswith(("127.0.0.1", "localhost")):
        return port, ""
    return port, first


def _probe(url: str, context: ssl.SSLContext | None, host_header: str = "") -> bool:
    try:
        request = urllib.request.Request(url, headers={"Host": host_header} if host_header else {})
        with urllib.request.urlopen(request, timeout=3, context=context) as response:
            return response.status == 200 and json.loads(response.read()) == {"ok": True}
    except (urllib.error.URLError, OSError, ValueError):
        return False


def main() -> int:
    port, host_header = _approved_target()
    if _probe(f"https://{HOST}:{port}/healthz", _tls_context(), host_header):
        return 0
    if _probe(f"http://{HOST}:{port}/healthz", None, host_header):
        return 0
    print("healthz probe failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
