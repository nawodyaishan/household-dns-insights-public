"""Exa evidence adapter over the application's own MCP client.

Only ``web_search_exa`` and ``web_fetch_exa`` are ever called. ``agent_run`` and
``web_search_advanced_exa`` are rejected by the allowlist, and a model can never
nominate a tool or URL. Protocol or payload drift fails closed rather than guessing.

The MCP SDK is imported lazily inside the real session factory so offline tests and
ordinary reporting never need it. The real transport is exercised only in the
separately authorized runtime validation.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

from ..contracts import EvidenceSource, ExternalError

SEARCH_TOOL = "web_search_exa"
FETCH_TOOL = "web_fetch_exa"
FORBIDDEN_TOOLS = frozenset({"agent_run", "web_search_advanced_exa"})
MAX_RESULTS = 5
MAX_EXCERPT_CHARS = 2048
MAX_PAYLOAD_BYTES = 16 * 1024
_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home", ".localhost", ".arpa")


class McpSession(Protocol):
    """The narrow MCP surface this adapter needs; fake sessions implement it too."""

    def initialize(self) -> None: ...

    def list_tools(self) -> list[Mapping[str, object]]: ...

    def call_tool(
        self, name: str, arguments: Mapping[str, object]
    ) -> list[Mapping[str, object]]: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reject_private_url(url: str, *, operation: str) -> str:
    """Allow only public HTTPS URLs; never fetch a local or literal address."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ExternalError(f"{operation}: only public HTTPS evidence URLs are allowed")
    host = parts.hostname.lower().rstrip(".")
    if host.endswith(_PRIVATE_SUFFIXES) or host in {"localhost"}:
        raise ExternalError(f"{operation}: private hostnames are not fetched")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ExternalError(f"{operation}: IP literals are not fetched")
    return url


def _source(url: str, text: str, *, index: int) -> EvidenceSource:
    excerpt = " ".join(text.split())[:MAX_EXCERPT_CHARS]
    return EvidenceSource(
        source_id=f"s{index}",
        url=url,
        excerpt=excerpt,
        content_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
        captured_utc=_utc_now(),
    )


def _parse_items(text: str, *, operation: str) -> list[tuple[str, str]]:
    """Parse tool text into (url, excerpt) pairs, failing closed on drift.

    Accepts the structured JSON form and, conservatively, the plain-text block form
    with an explicit ``URL:`` line. Anything else is rejected.
    """
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise ExternalError(f"{operation}: tool payload is not valid JSON") from error
        if isinstance(payload, Mapping):
            payload = payload.get("results")
        if not isinstance(payload, list):
            raise ExternalError(f"{operation}: tool payload has no results list")
        items: list[tuple[str, str]] = []
        for entry in payload:
            if not isinstance(entry, Mapping):
                raise ExternalError(f"{operation}: result is not an object")
            url = entry.get("url") or entry.get("link")
            body = entry.get("text") or entry.get("snippet") or entry.get("content") or ""
            title = entry.get("title") or ""
            if not isinstance(url, str) or not isinstance(body, str):
                raise ExternalError(f"{operation}: result lacks a url or text field")
            items.append((url, f"{title} {body}".strip()))
        return items

    items = []
    current: list[str] = []
    url: str | None = None
    for line in stripped.splitlines():
        stripped_line = line.strip()
        if stripped_line.lower().startswith(("url:", "link:")):
            if url is not None:
                items.append((url, "\n".join(current)))
            url = stripped_line.split(":", 1)[1].strip()
            current = []
        elif url is not None and stripped_line:
            current.append(stripped_line)
    if url is not None:
        items.append((url, "\n".join(current)))
    if not items:
        raise ExternalError(f"{operation}: unrecognized tool payload")
    return items


def _to_sources(text: str, *, operation: str, limit: int) -> list[EvidenceSource]:
    sources: list[EvidenceSource] = []
    seen: set[str] = set()
    used = 0
    for url, excerpt in _parse_items(text, operation=operation):
        if not url.startswith("https://"):
            raise ExternalError(f"{operation}: evidence URL is not HTTPS")
        _reject_private_url(url, operation=operation)
        if url in seen:
            continue
        seen.add(url)
        source = _source(url, excerpt, index=len(sources) + 1)
        cost = len(source.excerpt.encode()) + len(source.url.encode())
        if used + cost > MAX_PAYLOAD_BYTES:
            break
        used += cost
        sources.append(source)
        if len(sources) >= limit:
            break
    return sources


@dataclass(frozen=True, slots=True)
class _Limits:
    max_results: int
    timeout_seconds: float


def _limits(values: Mapping[str, int] | None) -> _Limits:
    values = values or {}
    results = int(values.get("max_results", MAX_RESULTS))
    if not 1 <= results <= MAX_RESULTS:
        raise ExternalError(f"max_results must be between 1 and {MAX_RESULTS}")
    timeout = float(values.get("timeout_seconds", 30))
    if not 1 <= timeout <= 60:
        raise ExternalError("timeout_seconds must be between 1 and 60")
    return _Limits(max_results=results, timeout_seconds=timeout)


class ExaEvidenceClient:
    """Bounded ``EvidenceClient`` over an injected MCP session factory."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], McpSession],
        allowed_tools: Sequence[str] = (SEARCH_TOOL, FETCH_TOOL),
    ) -> None:
        if FORBIDDEN_TOOLS & set(allowed_tools):
            raise ExternalError("Agent and advanced-search tools are not permitted")
        if not set(allowed_tools) <= {SEARCH_TOOL, FETCH_TOOL}:
            raise ExternalError("Only web_search_exa and web_fetch_exa may be allowed")
        self._factory = session_factory
        self._allowed = tuple(allowed_tools)

    def _run(self, operation: str, action: Callable[[McpSession], object]) -> object:
        session = self._factory()
        try:
            session.initialize()
            return action(session)
        except ExternalError:
            raise
        except Exception as error:  # noqa: BLE001 - normalized, never leaked
            retryable = isinstance(error, (TimeoutError, OSError, ConnectionError))
            raise ExternalError(
                f"MCP {operation} failed: {type(error).__name__}", retryable=retryable
            ) from error

    # -- port --------------------------------------------------------------
    def discover(self, limits: dict[str, int]) -> dict[str, object]:
        _limits(limits)

        def action(session: McpSession) -> dict[str, object]:
            tools = session.list_tools()
            by_name = {
                str(tool.get("name")): tool
                for tool in tools
                if isinstance(tool, Mapping) and tool.get("name")
            }
            for name in self._allowed:
                if name not in by_name:
                    raise ExternalError(f"MCP discovery: required tool {name!r} is missing")
                schema = by_name[name].get("inputSchema") or by_name[name].get("input_schema")
                properties = schema.get("properties") if isinstance(schema, Mapping) else None
                required = {"query"} if name == SEARCH_TOOL else {"urls"}
                if not isinstance(properties, Mapping) or not required <= set(properties):
                    raise ExternalError(f"MCP discovery: {name!r} input schema drifted")
            return {"tools": sorted(self._allowed), "available": sorted(by_name)}

        return self._run("discovery", action)  # type: ignore[return-value]

    def search(self, public_query: str, limits: dict[str, int]) -> Sequence[EvidenceSource]:
        if not public_query or len(public_query) > 253:
            raise ExternalError("Search query must be one public DNS name")
        bounded = _limits(limits)

        def action(session: McpSession) -> list[EvidenceSource]:
            content = session.call_tool(
                SEARCH_TOOL,
                {"query": public_query, "numResults": bounded.max_results},
            )
            return _to_sources(
                _text(content, operation="search"),
                operation="search",
                limit=bounded.max_results,
            )

        return self._run("search", action)  # type: ignore[return-value]

    def fetch(self, public_urls: Sequence[str], limits: dict[str, int]) -> Sequence[EvidenceSource]:
        if not public_urls or len(public_urls) > 3:
            raise ExternalError("Fetch accepts between one and three URLs")
        for url in public_urls:
            _reject_private_url(url, operation="fetch")
        bounded = _limits(limits)

        def action(session: McpSession) -> list[EvidenceSource]:
            content = session.call_tool(
                FETCH_TOOL,
                {"urls": list(public_urls), "maxCharacters": MAX_EXCERPT_CHARS},
            )
            return _to_sources(
                _text(content, operation="fetch"),
                operation="fetch",
                limit=bounded.max_results,
            )

        return self._run("fetch", action)  # type: ignore[return-value]


def _text(content: Sequence[object], *, operation: str) -> str:
    from .common import text_from_content

    return text_from_content(content, operation=operation)


# -- real SDK session ------------------------------------------------------
class SdkSession:
    """Stateless MCP session: one bounded connection per operation.

    Imports the official SDK lazily so the offline test suite and ordinary reporting
    do not depend on it. Not exercised by automated tests; runtime validation is a
    separate authorization.
    """

    def __init__(self, url: str, headers: Mapping[str, str], timeout: float) -> None:
        self._url = url
        self._headers = dict(headers)
        self._timeout = timeout

    def initialize(self) -> None:
        self._run(_noop)

    def list_tools(self) -> list[Mapping[str, object]]:
        return self._run(_list_tools)

    def call_tool(self, name: str, arguments: Mapping[str, object]) -> list[Mapping[str, object]]:
        return self._run(lambda session: _call_tool(session, name, arguments))

    def _run(self, action: Callable[[object], object]) -> object:
        return asyncio.run(self._async(action))

    async def _async(self, action: Callable[[object], object]) -> object:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as error:  # pragma: no cover - runtime-only path
            raise ExternalError("The MCP SDK is not installed") from error
        async with streamablehttp_client(
            self._url,
            headers=self._headers,
            timeout=timedelta(seconds=self._timeout),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await action(session)


async def _noop(session: object) -> None:
    return None


async def _list_tools(session: object) -> list[Mapping[str, object]]:
    result = await session.list_tools()
    tools = getattr(result, "tools", None)
    if not isinstance(tools, list):
        raise ExternalError("MCP list_tools returned no tool list")
    return [
        {"name": tool.name, "inputSchema": getattr(tool, "inputSchema", None)} for tool in tools
    ]


async def _call_tool(
    session: object, name: str, arguments: Mapping[str, object]
) -> list[Mapping[str, object]]:
    result = await session.call_tool(name, dict(arguments))
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        raise ExternalError(f"MCP tool {name!r} returned no content")
    normalized: list[Mapping[str, object]] = []
    for item in content:
        if hasattr(item, "model_dump"):
            normalized.append(item.model_dump())
        elif isinstance(item, Mapping):
            normalized.append(dict(item))
        else:
            normalized.append(
                {"type": getattr(item, "type", None), "text": getattr(item, "text", "")}
            )
    return normalized


def sdk_session_factory(
    endpoint: str, api_key: str, *, timeout: float = 30.0
) -> Callable[[], McpSession]:
    """Build the real factory; the key is captured in memory, never logged."""
    if not endpoint.startswith("https://"):
        raise ExternalError("The MCP endpoint must be HTTPS")
    if not api_key:
        raise ExternalError("The Exa credential is empty")

    def factory() -> McpSession:
        return SdkSession(endpoint, {"x-api-key": api_key}, timeout)

    return factory


__all__ = [
    "FETCH_TOOL",
    "FORBIDDEN_TOOLS",
    "MAX_RESULTS",
    "SEARCH_TOOL",
    "ExaEvidenceClient",
    "McpSession",
    "SdkSession",
    "sdk_session_factory",
]
