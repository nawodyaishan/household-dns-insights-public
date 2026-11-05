"""Provider-agnostic OpenAI-compatible adapter: one declared HTTP attempt per operation.

Any endpoint that serves ``GET {base}/models`` and ``POST {base}/chat/completions``
works (OpenRouter, 9Router, Groq, OpenAI, Ollama, LM Studio, ...). Catalogue fields
differ between providers, so limits are read from the known field names and, only
when the catalogue omits them, from explicit operator-declared values. Nothing is
guessed: a model without verified limits is ineligible. Provider-specific request
options arrive as an explicit ``extra_body`` and can never replace core fields.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from ..contracts import ExternalError, ModelCapabilities, ModelReply, ModelRequest
from .common import (
    chat_reply,
    classify_status,
    json_schema_format,
    request_messages,
    transport_error,
    usage_from,
)

MODELS_PATH = "/models"
CHAT_PATH = "/chat/completions"
#: Request fields owned by this adapter; ``extra_body`` cannot override them.
RESERVED_BODY_KEYS = frozenset(
    {"model", "messages", "max_tokens", "max_completion_tokens", "response_format", "stream"}
)
#: Router aliases that pick a model per request; refused for bounded, accounted jobs.
AUTO_ROUTER_MODELS = frozenset({"openrouter/auto", "openrouter/free"})


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _first_positive(*values: object) -> int | None:
    for value in values:
        number = _positive_int(value)
        if number is not None:
            return number
    return None


def _price_is_zero(value: object) -> bool:
    if value is None:
        return False
    try:
        return float(str(value)) == 0.0
    except (TypeError, ValueError):
        return False


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


class OpenAICompatibleProvider:
    """One OpenAI-compatible endpoint implementing the ``ModelProvider`` port."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        label: str = "llm",
        free_only: bool = False,
        context_limit: int | None = None,
        completion_limit: int | None = None,
        extra_body: Mapping[str, object] | None = None,
        structured_output: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ExternalError("Model provider credential is empty")
        extra = dict(extra_body or {})
        clash = RESERVED_BODY_KEYS & set(extra)
        if clash:
            raise ExternalError(f"extra_body may not override {sorted(clash)}")
        if structured_output is not None and structured_output not in {
            "json_schema",
            "json_object",
        }:
            raise ExternalError(
                "Declared structured-output mode must be json_schema or json_object"
            )
        self._label = label
        self._free_only = free_only
        self._context_limit = context_limit
        self._completion_limit = completion_limit
        self._structured_output = structured_output
        self._extra = extra
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout, connect=5.0),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenAICompatibleProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- port --------------------------------------------------------------
    def describe_model(self, model_id: str) -> ModelCapabilities:
        if model_id in AUTO_ROUTER_MODELS:
            raise ExternalError(f"{model_id} picks models per request; bounded jobs refuse it")
        entry = self._catalogue_entry(model_id)
        capabilities = _mapping(entry.get("capabilities"))
        top = _mapping(entry.get("top_provider"))
        context = _first_positive(
            entry.get("context_length"),
            entry.get("context_window"),
            entry.get("max_context_length"),
            capabilities.get("contextWindow"),
            top.get("context_length"),
        )
        completion = _first_positive(
            top.get("max_completion_tokens"),
            entry.get("max_completion_tokens"),
            capabilities.get("maxOutput"),
        )
        declared: list[str] = []
        if self._context_limit is not None:
            context = (
                min(context, self._context_limit) if context is not None else self._context_limit
            )
            declared.append("context")
        if self._completion_limit is not None:
            completion = (
                min(completion, self._completion_limit)
                if completion is not None
                else self._completion_limit
            )
            declared.append("completion")
        if context is None or completion is None:
            raise ExternalError(
                f"{self._label} catalogue lacks verified context/completion limits for "
                f"{model_id!r}; declare them explicitly or the model is ineligible"
            )
        if completion > context:
            completion = context
        params = entry.get("supported_parameters")
        params_set = set(params) if isinstance(params, list) else set()
        structured = (
            "json_schema" if {"response_format", "structured_outputs"} & params_set else "none"
        )
        pricing = _mapping(entry.get("pricing"))
        free = bool(pricing) and (
            _price_is_zero(pricing.get("prompt")) and _price_is_zero(pricing.get("completion"))
        )
        notes = f"metadata from {self._label} {MODELS_PATH}"
        if structured == "none" and self._structured_output is not None:
            # Some catalogues (e.g. Mistral cards) never advertise supported
            # parameters; an operator-declared mode replaces the unverified
            # "none" inference and is still proven by the actual bounded
            # completion before any result is stored.
            structured = self._structured_output
            notes += "; operator-declared structured-output mode"
        if declared:
            notes += f"; operator-declared {'/'.join(declared)} limit"
        return ModelCapabilities(
            model_id=model_id,
            context_limit=context,
            completion_limit=completion,
            structured_output=structured,
            free_eligible=free,
            input_modalities=("text",),
            notes=notes,
        )

    def complete(self, request: ModelRequest) -> ModelReply:
        operation = f"{self._label} completion"
        body: dict[str, object] = {
            **self._extra,
            "model": request.model_id,
            "messages": request_messages(request),
            "max_tokens": request.max_completion_tokens,
            "response_format": json_schema_format(request.response_schema),
            "stream": False,
        }
        body.setdefault("temperature", 0)
        try:
            response = self._client.post(CHAT_PATH, json=body)
        except Exception as error:  # noqa: BLE001 - normalized, never swallowed
            raise transport_error(error, operation=operation) from error
        if response.status_code != 200:
            raise classify_status(response.status_code, operation=operation)
        try:
            payload = response.json()
        except ValueError as error:
            raise ExternalError(f"{operation} is not JSON") from error
        if not isinstance(payload, Mapping):
            raise ExternalError(f"{operation} payload is not an object")
        if self._free_only:
            if usage_from(payload).total_tokens is None:
                raise ExternalError("Free-only completion returned no measured usage")
            usage = _mapping(payload.get("usage"))
            if "cost" in usage and not _price_is_zero(usage.get("cost")):
                raise ExternalError("Free-only completion reported a non-zero cost")
        return chat_reply(
            payload,
            requested_model=request.model_id,
            operation=operation,
            strict_model=self._free_only,
        )

    # -- helpers -----------------------------------------------------------
    def _catalogue_entry(self, model_id: str) -> Mapping[str, object]:
        operation = f"{self._label} model metadata"
        try:
            response = self._client.get(MODELS_PATH)
        except Exception as error:  # noqa: BLE001 - normalized, never swallowed
            raise transport_error(error, operation=operation) from error
        if response.status_code != 200:
            raise classify_status(response.status_code, operation=operation)
        try:
            payload = response.json()
        except ValueError as error:
            raise ExternalError(f"{operation} is not JSON") from error
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if data is None and isinstance(payload, list):
            # Some compatible endpoints (Mistral model cards) return the list
            # directly instead of an ``{"object": "list", "data": [...]}`` wrapper.
            data = [entry for entry in payload if isinstance(entry, Mapping)]
        if not isinstance(data, list):
            if isinstance(payload, list):
                raise ExternalError(f"{operation} list has no objects")
            raise ExternalError(f"{operation} has no data list")
        for entry in data:
            if isinstance(entry, Mapping) and entry.get("id") == model_id:
                return entry
        raise ExternalError(f"Model {model_id!r} is not in the {self._label} catalogue")


__all__ = ["AUTO_ROUTER_MODELS", "OpenAICompatibleProvider", "RESERVED_BODY_KEYS"]
