"""Shared wire helpers for the two OpenAI-compatible provider adapters.

Only serialization, usage normalization and error classification live here. Model
eligibility, prompt/schema construction and grounding stay in the owning feature
modules. Nothing in this module retries, logs a credential or reads a response body
into an error message.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx

from ..contracts import (
    REQUEST_OVERHEAD_BYTES,
    ExternalError,
    ModelReply,
    ModelRequest,
    Usage,
)

#: Statuses worth a second, separately reserved attempt. Everything else fails closed.
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def classify_status(status: int, *, operation: str) -> ExternalError:
    """Map an HTTP status to a redacted error without reading the body."""
    if status in {401, 403}:
        return ExternalError(f"{operation}: credentials rejected ({status})", status=status)
    return ExternalError(
        f"{operation}: upstream returned {status}",
        retryable=status in RETRYABLE_STATUS,
        status=status,
    )


def transport_error(error: Exception, *, operation: str) -> ExternalError:
    """Normalize a client-side failure; timeouts and connection resets are retryable."""
    if isinstance(error, httpx.TimeoutException):
        return ExternalError(f"{operation}: timed out", retryable=True)
    if isinstance(error, (httpx.NetworkError, httpx.RemoteProtocolError)):
        return ExternalError(f"{operation}: connection failed", retryable=True)
    return ExternalError(f"{operation}: {type(error).__name__}")


def request_messages(request: ModelRequest) -> list[dict[str, str]]:
    """Serialize an approved request into OpenAI-style messages.

    The evidence payload is re-checked against the disclosure bound: a caller that
    bypasses :func:`household_report.classification.build_model_request` fails here
    instead of sending more than approved. The payload itself is defined once, on
    the request contract, so the size checked here is the size that is sent.
    """
    from ..classification import MAX_EVIDENCE_BYTES, MAX_EXCERPT_CHARS

    encoded = json.dumps(request.payload(), sort_keys=True)
    if len(encoded.encode()) > MAX_EVIDENCE_BYTES + REQUEST_OVERHEAD_BYTES:
        raise ExternalError("Request evidence exceeds the approved disclosure bound")
    for bundle in request.evidence:
        for source in bundle.sources:
            if len(source.excerpt) > MAX_EXCERPT_CHARS:
                raise ExternalError("Evidence excerpt exceeds the approved disclosure bound")
    return [
        {"role": "system", "content": request.system_policy},
        {"role": "user", "content": encoded},
    ]


def usage_from(payload: Mapping[str, object]) -> Usage:
    """Read measured usage; absent or malformed values stay unknown, never guessed."""
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return Usage()
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return Usage(
        prompt_tokens=int(prompt) if isinstance(prompt, int) and prompt >= 0 else None,
        completion_tokens=(
            int(completion) if isinstance(completion, int) and completion >= 0 else None
        ),
    )


def first_choice(payload: Mapping[str, object], *, operation: str) -> Mapping[str, object]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ExternalError(f"{operation}: response has no choices")
    return choices[0]


def message_text(choice: Mapping[str, object], *, operation: str) -> str:
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ExternalError(f"{operation}: response has no message")
    content = message.get("content")
    if isinstance(content, list):
        # Some gateways return content parts; join text parts only.
        text = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and part.get("type") in {None, "text"}
        )
    elif isinstance(content, str):
        text = content
    else:
        text = ""
    if not text.strip():
        raise ExternalError(f"{operation}: response content is empty")
    return text


def chat_reply(
    payload: Mapping[str, object],
    *,
    requested_model: str,
    operation: str,
    strict_model: bool = False,
) -> ModelReply:
    """Normalize a chat completion, refusing truncation and silent substitution."""
    choice = first_choice(payload, operation=operation)
    finish = choice.get("finish_reason")
    if finish == "length":
        raise ExternalError(f"{operation}: output was truncated")
    returned = str(payload.get("model") or requested_model)
    if strict_model and returned != requested_model:
        raise ExternalError(
            f"{operation}: provider substituted model {returned!r} for {requested_model!r}"
        )
    return ModelReply(
        model_id=returned,
        text=message_text(choice, operation=operation),
        usage=usage_from(payload),
        finish_reason=str(finish) if finish else None,
    )


def json_schema_format(schema: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "destination_classification",
            "strict": True,
            "schema": dict(schema),
        },
    }


def require_https(url: str, *, operation: str) -> None:
    if not url.startswith("https://"):
        raise ExternalError(f"{operation}: evidence URL is not HTTPS")


@dataclass(frozen=True, slots=True)
class TextItem:
    """One text content part returned by an MCP tool."""

    text: str


def text_from_content(content: Sequence[object], *, operation: str) -> str:
    """Join text parts of an MCP tool result, ignoring non-text parts."""
    parts: list[str] = []
    for item in content:
        if isinstance(item, Mapping):
            if item.get("type") in {None, "text"} and isinstance(item.get("text"), str):
                parts.append(item["text"])
        elif hasattr(item, "text") and isinstance(item.text, str):
            parts.append(item.text)
    joined = "\n".join(parts).strip()
    if not joined:
        raise ExternalError(f"{operation}: tool returned no text content")
    return joined


__all__ = [
    "RETRYABLE_STATUS",
    "TextItem",
    "chat_reply",
    "classify_status",
    "first_choice",
    "json_schema_format",
    "message_text",
    "request_messages",
    "require_https",
    "text_from_content",
    "transport_error",
    "usage_from",
]
