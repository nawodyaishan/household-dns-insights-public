"""Exa MCP adapter: allowlist, strict parsing and bounded payloads over a fake session.

No MCP server is contacted. The fake session records every call so the tests can
prove that one operation makes exactly one tool attempt and never a forbidden tool.
"""

from __future__ import annotations

import json
import unittest

from household_report.contracts import ExternalError
from household_report.integrations.exa_mcp import (
    MAX_PAYLOAD_BYTES,
    ExaEvidenceClient,
    sdk_session_factory,
)

SEARCH_SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}
FETCH_SCHEMA = {"type": "object", "properties": {"urls": {"type": "array"}}}


def tools(*, search_schema=SEARCH_SCHEMA, fetch_schema=FETCH_SCHEMA, include=None):
    names = include or ("web_search_exa", "web_fetch_exa")
    listing = []
    for name in names:
        schema = search_schema if name == "web_search_exa" else fetch_schema
        listing.append({"name": name, "inputSchema": schema})
    return listing


def text_result(text: str):
    return [{"type": "text", "text": text}]


class FakeSession:
    """The narrow session surface the adapter needs, with call recording."""

    def __init__(self, *, listing=None, results=None, error=None) -> None:
        self.listing = tools() if listing is None else listing
        self.results = results or {}
        self.error = error
        self.initialized = 0
        self.calls: list[tuple[str, dict[str, object]]] = []

    def initialize(self) -> None:
        self.initialized += 1

    def list_tools(self):
        if self.error is not None:
            raise self.error
        return self.listing

    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if self.error is not None:
            raise self.error
        return self.results[name]


def client(session: FakeSession, **kwargs) -> ExaEvidenceClient:
    return ExaEvidenceClient(session_factory=lambda: session, **kwargs)


class DiscoveryTests(unittest.TestCase):
    def test_discovery_reports_allowlisted_tools_without_calling_any(self):
        session = FakeSession()
        result = client(session).discover({"max_results": 3, "timeout_seconds": 10})
        self.assertEqual(result["tools"], ["web_fetch_exa", "web_search_exa"])
        self.assertEqual(session.calls, [])
        self.assertEqual(session.initialized, 1)

    def test_missing_required_tool_fails_closed(self):
        session = FakeSession(listing=tools(include=("web_search_exa",)))
        with self.assertRaises(ExternalError) as caught:
            client(session).discover({"max_results": 3, "timeout_seconds": 10})
        self.assertFalse(caught.exception.retryable)
        self.assertIn("web_fetch_exa", str(caught.exception))

    def test_input_schema_drift_fails_closed(self):
        session = FakeSession(listing=tools(search_schema={"properties": {"q": {}}}))
        with self.assertRaises(ExternalError):
            client(session).discover({"max_results": 3, "timeout_seconds": 10})

    def test_agent_and_advanced_search_tools_cannot_be_allowlisted(self):
        for forbidden in ("agent_run", "web_search_advanced_exa"):
            with self.assertRaises(ExternalError):
                ExaEvidenceClient(
                    session_factory=lambda: FakeSession(),
                    allowed_tools=("web_search_exa", forbidden),
                )
        with self.assertRaises(ExternalError):
            ExaEvidenceClient(
                session_factory=lambda: FakeSession(), allowed_tools=("some_other_tool",)
            )

    def test_limits_are_bounded(self):
        for limits in (
            {"max_results": 0, "timeout_seconds": 10},
            {"max_results": 6, "timeout_seconds": 10},
            {"max_results": 3, "timeout_seconds": 0},
            {"max_results": 3, "timeout_seconds": 61},
        ):
            with self.assertRaises(ExternalError):
                client(FakeSession()).discover(limits)


class SearchTests(unittest.TestCase):
    def payload(self, *entries):
        return text_result(json.dumps({"results": list(entries)}))

    def test_json_results_become_bounded_sources(self):
        session = FakeSession(
            results={
                "web_search_exa": self.payload(
                    {
                        "url": "https://www.example.com/about",
                        "title": "Example Video",
                        "text": "Example Video is a video streaming service.",
                    }
                )
            }
        )
        sources = client(session).search("example.com", {"max_results": 3, "timeout_seconds": 10})
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].source_id, "s1")
        self.assertEqual(sources[0].url, "https://www.example.com/about")
        self.assertIn("video streaming", sources[0].excerpt)
        self.assertEqual(len(sources[0].content_sha256), 64)
        self.assertEqual(len(session.calls), 1)
        name, arguments = session.calls[0]
        self.assertEqual(name, "web_search_exa")
        self.assertEqual(arguments, {"query": "example.com", "numResults": 3})

    def test_duplicate_urls_are_collapsed(self):
        entry = {"url": "https://www.example.com/", "text": "Same page."}
        session = FakeSession(results={"web_search_exa": self.payload(entry, entry)})
        sources = client(session).search("example.com", {"max_results": 5, "timeout_seconds": 10})
        self.assertEqual(len(sources), 1)

    def test_plain_text_block_form_is_accepted(self):
        body = "Example Video\nURL: https://www.example.com/about\nA video streaming service."
        session = FakeSession(results={"web_search_exa": text_result(body)})
        sources = client(session).search("example.com", {"max_results": 3, "timeout_seconds": 10})
        self.assertEqual(sources[0].url, "https://www.example.com/about")
        self.assertIn("streaming", sources[0].excerpt)

    def test_unrecognized_payload_is_rejected(self):
        for body in ("", "no urls here at all", "{not json", json.dumps({"other": []})):
            session = FakeSession(results={"web_search_exa": text_result(body)})
            with self.assertRaises(ExternalError):
                client(session).search("example.com", {"max_results": 3, "timeout_seconds": 10})

    def test_private_or_non_https_evidence_urls_are_never_accepted(self):
        for url in (
            "http://www.example.com/about",
            "https://router.lan/admin",
            "https://printer.local/",
            "https://10.0.0.1/",
            "https://[::1]/",
            "https://localhost:8787/",
        ):
            session = FakeSession(
                results={"web_search_exa": self.payload({"url": url, "text": "Local."})}
            )
            with self.assertRaises(ExternalError):
                client(session).search("example.com", {"max_results": 3, "timeout_seconds": 10})

    def test_payload_cap_drops_whole_sources_instead_of_truncating(self):
        huge = "https://www.example.com/" + "a" * (MAX_PAYLOAD_BYTES + 1)
        session = FakeSession(
            results={"web_search_exa": self.payload({"url": huge, "text": "Too large."})}
        )
        sources = client(session).search("example.com", {"max_results": 3, "timeout_seconds": 10})
        self.assertEqual(sources, [])

    def test_query_must_be_one_public_name(self):
        session = FakeSession(results={"web_search_exa": self.payload()})
        with self.assertRaises(ExternalError):
            client(session).search("", {"max_results": 3, "timeout_seconds": 10})
        with self.assertRaises(ExternalError):
            client(session).search("a" * 254, {"max_results": 3, "timeout_seconds": 10})
        self.assertEqual(session.calls, [])


class FetchTests(unittest.TestCase):
    def test_fetch_sends_allowlisted_urls_and_parses_results(self):
        session = FakeSession(
            results={
                "web_fetch_exa": text_result(
                    json.dumps(
                        [
                            {
                                "url": "https://www.example.com/about",
                                "text": "Example Video is a video streaming service.",
                            }
                        ]
                    )
                )
            }
        )
        sources = client(session).fetch(
            ["https://www.example.com/about"], {"max_results": 2, "timeout_seconds": 10}
        )
        self.assertEqual(sources[0].source_id, "s1")
        self.assertEqual(session.calls[0][0], "web_fetch_exa")
        self.assertEqual(session.calls[0][1]["maxCharacters"], 2048)

    def test_fetch_bounds_the_url_count_and_scheme(self):
        session = FakeSession(results={"web_fetch_exa": text_result("[]")})
        with self.assertRaises(ExternalError):
            client(session).fetch([], {"max_results": 2, "timeout_seconds": 10})
        with self.assertRaises(ExternalError):
            client(session).fetch(
                [f"https://example.com/{index}" for index in range(4)],
                {"max_results": 2, "timeout_seconds": 10},
            )
        with self.assertRaises(ExternalError):
            client(session).fetch(
                ["https://router.lan/admin"], {"max_results": 2, "timeout_seconds": 10}
            )
        self.assertEqual(session.calls, [])


class FailureTests(unittest.TestCase):
    def test_transport_errors_are_retryable_and_redacted(self):
        session = FakeSession(error=OSError("connection reset to internal host"))
        with self.assertRaises(ExternalError) as caught:
            client(session).search("example.com", {"max_results": 3, "timeout_seconds": 10})
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("internal host", str(caught.exception))

    def test_protocol_errors_are_not_retryable(self):
        session = FakeSession(error=RuntimeError("unexpected"))
        with self.assertRaises(ExternalError) as caught:
            client(session).discover({"max_results": 3, "timeout_seconds": 10})
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(str(caught.exception), "MCP discovery failed: RuntimeError")

    def test_sdk_factory_refuses_unsafe_configuration(self):
        with self.assertRaises(ExternalError):
            sdk_session_factory("http://mcp.example.com/mcp", "key")
        with self.assertRaises(ExternalError):
            sdk_session_factory("https://mcp.example.com/mcp", "")


if __name__ == "__main__":
    unittest.main()
