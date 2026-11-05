"""Small shared value contracts and the two external ports.

Only concepts that several feature modules genuinely share live here. Database
rows, HTTP bodies and vendor wire formats stay local to their boundaries.

This module is deliberately stdlib-only: importing it must never pull in a web
framework, an HTTP client or the MCP SDK.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from typing import Protocol, runtime_checkable

INTERPRETATION_VERSION = 1
"""Bump when period/row interpretation changes enough to alter a data digest."""

#: Slack above the evidence budget for the fixed JSON scaffolding of one request.
REQUEST_OVERHEAD_BYTES = 4096

#: Accounting category for each permitted external attempt. Analysis owns the
#: numeric limits; storage owns counting them atomically from one ledger.
ATTEMPT_KINDS = {
    "provider_request": "request",
    "provider_probe": "request",
    "provider_catalog": "request",
    "exa_discover": "exa",
    "exa_search": "exa",
    "exa_fetch": "exa",
}


@dataclass(frozen=True, slots=True)
class AttemptBudget:
    """Conservative caps a single reservation must fit inside."""

    per_analysis_requests: int
    per_day_requests: int
    per_analysis_tokens: int
    per_day_tokens: int
    per_analysis_exa: int
    per_day_exa: int
    # None preserves the 002 combined cap for existing jobs. An optional 003 run
    # must supply each operation cap explicitly, including zero allowances.
    per_analysis_search: int | None = None
    per_day_search: int | None = None
    per_analysis_fetch: int | None = None
    per_day_fetch: int | None = None
    per_analysis_discover: int | None = None
    per_day_discover: int | None = None
    per_analysis_catalog: int | None = None
    per_day_catalog: int | None = None
    per_analysis_probe: int | None = None
    per_day_probe: int | None = None
    per_analysis_completion: int | None = None
    per_day_completion: int | None = None
    # Paid-mode currency policy (spec R17). In free mode these stay None and no
    # monetary accounting runs. Paid mode requires every tariff and ceiling; a
    # missing price fails closed at reservation rather than assuming zero.
    paid_mode: bool = False
    provider_price_per_million: float | None = None
    exa_price_per_operation: float | None = None
    per_analysis_currency: float | None = None
    per_day_currency: float | None = None
    per_analysis_exa_currency: float | None = None
    per_day_exa_currency: float | None = None

    def __post_init__(self) -> None:
        if any(
            value < 0
            for budget_field in fields(self)
            if (value := getattr(self, budget_field.name)) is not None
        ):
            raise ContractError("Budget limits cannot be negative")


class ContractError(ValueError):
    """A shared contract received structurally valid but unusable input."""


class ExternalError(RuntimeError):
    """One external attempt failed; the caller decides whether to retry.

    Adapters never retry. ``retryable`` marks transient conditions (timeouts,
    429/5xx) that the owning feature may re-attempt as a new, separately reserved
    attempt. Messages never contain credentials, headers or raw responses.
    """

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True, slots=True)
class Period:
    """A fixed half-open UTC window ``[start_epoch, end_epoch)``."""

    start_epoch: int
    end_epoch: int

    def __post_init__(self) -> None:
        if self.start_epoch >= self.end_epoch:
            raise ContractError("Period start must be before end (half-open window)")
        if self.end_epoch <= 0:
            raise ContractError("Period end must be a positive epoch")

    @property
    def seconds(self) -> int:
        return self.end_epoch - self.start_epoch

    def contains(self, timestamp: float) -> bool:
        return self.start_epoch <= timestamp < self.end_epoch


@dataclass(frozen=True, slots=True)
class SnapshotRef:
    """Content-addressed reference to preserved source observations."""

    snapshot_id: str
    datasource: str
    data_sha256: str
    period: Period
    captured_utc: str
    window_count: int
    inserted: bool = True

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.data_sha256:
            raise ContractError("Snapshot identity and digest are required")
        if self.window_count < 0:
            raise ContractError("Snapshot row count cannot be negative")


@dataclass(frozen=True, slots=True)
class PublicCandidate:
    """The only destination information allowed to leave the machine."""

    item_id: str
    public_name: str
    claim_scope: str = "service_and_provider"
    policy_revision: int = 1

    def __post_init__(self) -> None:
        name = self.public_name
        if not name or name != name.strip().lower().rstrip("."):
            raise ContractError("Public candidate names must be normalized lowercase")
        if " " in name or "/" in name or "@" in name:
            raise ContractError("Public candidate names must be plain DNS names")
        if self.claim_scope not in {"service_and_provider", "provider_only", "broad_only"}:
            raise ContractError(f"Unsupported claim scope: {self.claim_scope}")


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    source_id: str
    url: str
    excerpt: str
    content_sha256: str
    captured_utc: str

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise ContractError("Evidence sources must be public HTTPS URLs")
        if not self.source_id or not self.content_sha256:
            raise ContractError("Evidence sources require a server-generated id and hash")


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    candidate_id: str
    sources: tuple[EvidenceSource, ...] = ()

    def source_ids(self) -> frozenset[str]:
        return frozenset(source.source_id for source in self.sources)


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    span_id: str
    candidate_id: str
    source_id: str
    source_sha256: str
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """A validated, candidate-scoped classification outcome."""

    item_id: str
    service: str | None
    provider: str | None
    role: str
    category: str
    evidence_ids: tuple[str, ...]
    confidence: str
    ambiguity: str | None
    verification_state: str
    unresolved_reason: str | None = None
    span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed_states = {"reviewed", "ai_grounded", "provider_only", "ambiguous", "unknown"}
        if self.verification_state not in allowed_states:
            raise ContractError(f"Unsupported verification state: {self.verification_state}")
        if self.confidence not in {"high", "medium", "low", "unknown"}:
            raise ContractError(f"Unsupported confidence: {self.confidence}")
        if self.verification_state == "unknown" and (
            self.service or self.unresolved_reason is None
        ):
            raise ContractError("Unknown outcomes need a reason and no service")
        if self.verification_state == "provider_only" and (self.service or not self.provider):
            raise ContractError("Provider-only outcomes carry a provider and no service")
        if self.verification_state in {"reviewed", "ai_grounded"} and not self.service:
            raise ContractError("Resolved outcomes require a service")


@dataclass(frozen=True, slots=True)
class AttributionResolution:
    """Locally verified per-row device attribution, never an inference."""

    row_id: int
    device_key: str | None
    unknown_reason: str | None = None

    def __post_init__(self) -> None:
        if (self.device_key is None) == (self.unknown_reason is None):
            raise ContractError("Attribution is either a verified device or an explicit unknown")


@dataclass(frozen=True, slots=True)
class Usage:
    """Measured provider usage; unknown values stay unknown, never guessed."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    model_id: str
    context_limit: int
    completion_limit: int
    structured_output: str
    free_eligible: bool
    input_modalities: tuple[str, ...] = ("text",)
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.context_limit <= 0 or self.completion_limit <= 0:
            raise ContractError("Model limits must be positive")
        if self.completion_limit > self.context_limit:
            raise ContractError("Completion limit cannot exceed the context limit")
        if self.structured_output not in {"json_schema", "json_object", "none"}:
            raise ContractError(f"Unsupported structured output mode: {self.structured_output}")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A bounded, already-disclosed request; never a whole report or raw rows."""

    model_id: str
    system_policy: str
    candidates: tuple[PublicCandidate, ...]
    evidence: tuple[EvidenceBundle, ...] = ()
    max_completion_tokens: int = 1024
    response_schema: dict[str, object] = field(default_factory=dict)
    spans: tuple[EvidenceSpan, ...] = ()
    contract_version: int = 1

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ContractError("A model request needs at least one public candidate")
        if self.max_completion_tokens <= 0:
            raise ContractError("Completion cap must be positive")
        ids = [bundle.candidate_id for bundle in self.evidence]
        if len(ids) != len(set(ids)):
            raise ContractError("Evidence bundles must be unique per candidate")

    def payload(self) -> dict[str, object]:
        """The exact user payload that will be sent for this request.

        The request builder and the sender share this definition, so the size
        measured before sending is the size that is actually transmitted. It
        lives here, in the shared contract, so neither side has to import the
        other.
        """
        payload: dict[str, object] = {
            "candidates": [
                {
                    "item_id": candidate.item_id,
                    "name": candidate.public_name,
                    "claim_scope": candidate.claim_scope,
                }
                for candidate in self.candidates
            ],
            "evidence": [
                {
                    "candidate_id": bundle.candidate_id,
                    "sources": [
                        {
                            "source_id": source.source_id,
                            "url": source.url,
                            **({} if self.contract_version == 2 else {"excerpt": source.excerpt}),
                        }
                        for source in bundle.sources
                    ],
                }
                for bundle in self.evidence
            ],
        }
        if self.contract_version == 2:
            payload["contract_version"] = 2
            payload["spans"] = [
                {
                    "span_id": span.span_id,
                    "candidate_id": span.candidate_id,
                    "source_id": span.source_id,
                    "source_sha256": span.source_sha256,
                    "start": span.start,
                    "end": span.end,
                    "text": span.text,
                }
                for span in self.spans
            ]
        return payload

    def payload_bytes(self) -> int:
        """Serialized size of this request's payload, measured exactly as sent."""
        return len(json.dumps(self.payload(), sort_keys=True).encode())


@dataclass(frozen=True, slots=True)
class ModelReply:
    model_id: str
    text: str
    usage: Usage
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if self.finish_reason == "length":
            raise ContractError("Truncated model output is unresolved, not a result")


@runtime_checkable
class ModelProvider(Protocol):
    """One declared HTTP attempt per operation; no retries, caching or research."""

    def describe_model(self, model_id: str) -> ModelCapabilities: ...

    def complete(self, request: ModelRequest) -> ModelReply: ...


@runtime_checkable
class EvidenceClient(Protocol):
    """Bounded protocol discovery plus allowlisted search/fetch.

    Each search/fetch call makes exactly one declared tool attempt. Implementations
    never run an agent loop, never accept model-nominated tools and never fetch an
    observed destination merely because it was queried.
    """

    def discover(self, limits: dict[str, int]) -> dict[str, object]: ...

    def search(self, public_query: str, limits: dict[str, int]) -> Sequence[EvidenceSource]: ...

    def fetch(
        self, public_urls: Sequence[str], limits: dict[str, int]
    ) -> Sequence[EvidenceSource]: ...
