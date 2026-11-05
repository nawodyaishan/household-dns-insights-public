"""Container health probe: exact approved Host in every published profile.

All probes stay on the container's own loopback interface; the stub HTTPS/HTTP
server only records which Host header arrived. No resolver, socket or network
outside localhost is touched.
"""

from __future__ import annotations

import http.server
import json
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_tools import load_tool

HEALTH = load_tool("healthcheck")


class _StubHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz" and self.headers.get("Host", "") == self.server.expected_host:
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


def _stub(expected_host: str, https: bool = False):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.expected_host = expected_host
    cleanup = None
    if https:
        directory = tempfile.TemporaryDirectory()
        cert = Path(directory.name) / "cert.pem"
        key = Path(directory.name) / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            check=True,
            capture_output=True,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        cleanup = directory
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    scheme = "https" if https else "http"
    return server, thread, cleanup, f"{scheme}://127.0.0.1:{server.server_address[1]}/healthz"


class ApprovedHostTargetTests(unittest.TestCase):
    def _target(self, allowed):
        with patch.dict("os.environ", {"HR_ALLOWED_HOSTS": allowed}):
            return HEALTH._approved_target()

    def test_lan_profile_probes_with_the_relayed_public_host_and_port(self):
        self.assertEqual(self._target("192.168.1.10:8787"), (8787, "192.168.1.10:8787"))

    def test_tls_lan_profile_uses_its_own_bind_as_the_public_host(self):
        self.assertEqual(self._target("10.10.10.20:8443"), (8443, "10.10.10.20:8443"))

    def test_loopback_profile_keeps_the_plain_local_probe(self):
        self.assertEqual(self._target("127.0.0.1:8787,localhost:8787"), (8787, ""))
        self.assertEqual(self._target("localhost:9999"), (9999, ""))

    def test_missing_or_unparseable_allowlist_falls_back_to_defaults(self):
        self.assertEqual(self._target(""), (8787, ""))
        self.assertEqual(self._target("bad-entry"), (8787, ""))


class ProbeHostHeaderTests(unittest.TestCase):
    def test_lan_probe_succeeds_only_with_the_approved_host_header(self):
        server, thread, cleanup, url = _stub("192.168.1.10:8787")
        try:
            self.assertTrue(HEALTH._probe(url, None, "192.168.1.10:8787"))
            self.assertFalse(HEALTH._probe(url, None, "localhost:8787"))
            self.assertFalse(HEALTH._probe(url, None, ""))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if cleanup:
                cleanup.cleanup()

    def test_https_probe_ignores_the_self_signed_owner_certificate(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        server, thread, cleanup, url = _stub("placeholder")
        server.expected_host = url.split("//", 1)[1].split("/", 1)[0]
        try:
            self.assertTrue(HEALTH._probe(url, context, ""))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if cleanup:
                cleanup.cleanup()


if __name__ == "__main__":
    unittest.main()
