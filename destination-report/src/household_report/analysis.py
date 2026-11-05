"""Analysis: explicit jobs, one dispatch gate, ledger budgets and local summaries.

Every external operation — provider request, capability probe, MCP discovery,
search or fetch — must pass through :meth:`AnalysisService.dispatch_attempt`. The
gate reserves against the ``call_attempts`` ledger inside a short
``BEGIN IMMEDIATE`` transaction, releases the database lock, performs exactly one
adapter attempt, then records the normalized outcome. Adapters cannot retry or
spend on their own.

There is no agent loop, no workflow engine and no summary table: a job is a row,
and its single local summary is a conditional update on that row.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .classification import (
    GroundingError,
    build_model_request,
    parse_batch_content,
    plan_public_candidates,
    resolve_domain,
    result_to_rule,
    validate_grounded,
)
from .contracts import (
    AttemptBudget,
    ContractError,
    EvidenceBundle,
    EvidenceClient,
    ExternalError,
    ModelCapabilities,
    ModelProvider,
    ModelReply,
    PublicCandidate,
    Usage,
)
from .research import (
    MAX_WORKLIST,
    first_time_page,
)
from .research import (
    coverage_summary as _coverage_summary,
)
from .research import (
    research_coverage as _research_coverage,
)
from .storage import AttemptReservation, BudgetExceeded, StorageError, Store

#: Safety defaults from the approved plan. Configurable, never assumed at runtime.
DEFAULT_BUDGET = AttemptBudget(
    per_analysis_requests=12,
    per_day_requests=60,
    per_analysis_tokens=524_288,
    per_day_tokens=2_097_152,
    per_analysis_exa=12,
    per_day_exa=60,
)

ANALYZER_VERSION = 2
MAX_BATCH_SIZE = 4
DEFAULT_LEASE_SECONDS = 120
MAX_ATTEMPTS_PER_OPERATION = 2
RETRY_BACKOFF_SECONDS = (0.5, 1.5)
PREVIEW_VERSION = 1
SEARCH_LIMITS = {"max_results": 5, "timeout_seconds": 30}
LIVE_OPERATION_NAMES = ("discover", "catalog", "probe", "search", "fetch", "completion")


class AnalysisError(RuntimeError):
    """The requested job transition is not permitted in its current state."""


class UnknownTokenBound(AnalysisError):
    """A conservative token reservation cannot be computed, so dispatch is refused."""


class ModelIneligible(AnalysisError):
    """The selected model cannot fit the configured token budget."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def analysis_identity(
    *,
    period_digest: str,
    selection_digest: str,
    analyzer_version: int,
    provider: str | None,
    model_id: str | None,
    config_fingerprint: str | None,
    policy_revision: int | None,
    nonce: str | None = None,
) -> str:
    """Stable identity: same period/selection/configuration means the same analysis.

    Mutable global cache revisions and key rotation are deliberately excluded.
    """
    payload = {
        "period": period_digest,
        "selection": selection_digest,
        "analyzer": analyzer_version,
        "provider": provider,
        "model": model_id,
        "config": config_fingerprint,
        "policy": policy_revision,
        "nonce": nonce,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def selection_digest(item_ids: Sequence[str]) -> str:
    """Identity of the explicit unresolved selection, order-independent."""
    ordered = sorted({str(item) for item in item_ids})
    return hashlib.sha256("\x00".join(ordered).encode()).hexdigest()


def reservation_tokens(
    capabilities: ModelCapabilities, *, completion_cap: int, require_structured: bool = True
) -> int:
    """Conservative reservation: full context limit plus the completion cap.

    No verified tokenizer/framing bound is assumed, so a character heuristic would
    under-reserve. A model that cannot fit the budget is ineligible rather than
    silently truncated. The bounded structured-output probe passes
    ``require_structured=False`` because proving that capability is its whole purpose.
    """
    if completion_cap <= 0:
        raise UnknownTokenBound("Completion cap must be positive")
    if capabilities.completion_limit < completion_cap:
        raise ModelIneligible(
            f"Model completion limit {capabilities.completion_limit} is below the "
            f"requested cap {completion_cap}"
        )
    if require_structured and capabilities.structured_output == "none":
        raise ModelIneligible("Model does not support structured output")
    return capabilities.context_limit + completion_cap


@dataclass(frozen=True, slots=True)
class DispatchResult:
    reservation: AttemptReservation
    reply: object | None
    usage: Usage
    outcome: str
    charged_tokens: int


class AnalysisService:
    """Job lifecycle and the single external-call gate."""

    def __init__(
        self,
        store: Store,
        *,
        budget: AttemptBudget = DEFAULT_BUDGET,
        max_attempts_per_operation: int = MAX_ATTEMPTS_PER_OPERATION,
        deadline_monotonic: float | None = None,
        external_attempt_timeout_seconds: float = 30.0,
    ) -> None:
        if not 1 <= max_attempts_per_operation <= MAX_ATTEMPTS_PER_OPERATION:
            raise AnalysisError(
                f"max_attempts_per_operation must be between 1 and {MAX_ATTEMPTS_PER_OPERATION}"
            )
        if external_attempt_timeout_seconds <= 0:
            raise AnalysisError("External attempt timeout must be positive")
        self._store = store
        self._budget = budget
        self._max_attempts_per_operation = max_attempts_per_operation
        self._deadline_monotonic = deadline_monotonic
        self._external_attempt_timeout_seconds = external_attempt_timeout_seconds

    @property
    def budget(self) -> AttemptBudget:
        return self._budget

    # -- job creation ------------------------------------------------------
    def create(
        self,
        *,
        period_digest: str,
        selected_item_ids: Sequence[str],
        candidates: Sequence[Mapping[str, object]],
        provider: str | None,
        model_id: str | None,
        config_fingerprint: str | None,
        policy_revision: int | None,
    ) -> tuple[str, bool]:
        if not candidates:
            raise AnalysisError("An analysis needs at least one candidate")
        identity = analysis_identity(
            period_digest=period_digest,
            selection_digest=selection_digest(selected_item_ids),
            analyzer_version=ANALYZER_VERSION,
            provider=provider,
            model_id=model_id,
            config_fingerprint=config_fingerprint,
            policy_revision=policy_revision,
        )
        return self._store.create_analysis(
            analysis_id=identity,
            period_digest=period_digest,
            selection_digest=selection_digest(selected_item_ids),
            analyzer_version=ANALYZER_VERSION,
            provider=provider,
            model_id=model_id,
            config_fingerprint=config_fingerprint,
            policy_revision=policy_revision,
            items=candidates,
        )

    def status(self, analysis_id: str) -> dict[str, object]:
        analysis = self._store.analysis(analysis_id)
        analysis["items"] = self._store.items(analysis_id)
        analysis["usage"] = self._store.budget_usage(analysis_id, utc_now()[:10])
        return analysis

    def history(self, *, limit: int = 10) -> list[dict[str, object]]:
        return self._store.recent_analyses(limit=limit)

    def limits(self) -> dict[str, int]:
        return _limits_view(self._budget)

    def live_run_manifest_template(self) -> dict[str, object]:
        """Local-only, non-executable manifest shape with every allowance at zero."""
        operation_limits = {
            f"{name}_per_{scope}": 0
            for name in LIVE_OPERATION_NAMES
            for scope in ("analysis", "day")
        }
        return {
            "schema_version": 1,
            "status": "not_ready",
            "candidate": None,
            "evidence_mode": None,
            "public_disclosure": [],
            "provider": None,
            "model_id": None,
            "limits": {
                **operation_limits,
                "requests_per_analysis": 0,
                "requests_per_day": 0,
                "tokens_per_analysis": 0,
                "tokens_per_day": 0,
                "retries": 0,
                "duration_seconds": 0,
            },
            "token_reservation": 0,
            "authorization": None,
        }

    def pause_interrupted(self, analysis_id: str) -> bool:
        """After a restart, pause in-flight work; never replay it automatically."""
        return self._store.pause_interrupted(analysis_id)

    def claim_batch(self, analysis_id: str, *, limit: int = MAX_BATCH_SIZE) -> list[str]:
        if not 1 <= limit <= MAX_BATCH_SIZE:
            raise AnalysisError(f"Batch size must be between 1 and {MAX_BATCH_SIZE}")
        pending = [item["item_id"] for item in self._store.pending_items(analysis_id, limit=limit)]
        return self._store.claim_items(
            analysis_id, item_ids=pending, lease_seconds=DEFAULT_LEASE_SECONDS
        )

    # -- the gate ----------------------------------------------------------
    def reserve(
        self,
        analysis_id: str,
        *,
        kind: str,
        tokens: int = 0,
        item_id: str | None = None,
    ) -> AttemptReservation:
        """Reserve one attempt without dispatching it (used by tests and callers)."""
        return self._store.reserve_attempt(
            analysis_id=analysis_id,
            kind=kind,
            budget=self._budget,
            item_id=item_id,
            reserved_tokens=tokens,
        )

    def dispatch_attempt(
        self,
        analysis_id: str,
        *,
        kind: str,
        operation: Callable[[], object],
        tokens: int = 0,
        item_id: str | None = None,
        usage_of: Callable[[object], Usage] | None = None,
    ) -> DispatchResult:
        """Reserve, dispatch exactly once outside the write lock, then record.

        Timeouts and exceptions are normalized into a terminal outcome; the full
        reservation stays charged because an unconfirmed attempt may have cost
        money. Callers decide whether to retry — as a new, separately reserved
        attempt.
        """
        self._require_time_for_attempt()
        reservation = self.reserve(analysis_id, kind=kind, tokens=tokens, item_id=item_id)
        usage = Usage()
        try:
            reply = operation()
        except TimeoutError as error:
            self._store.complete_attempt(
                reservation.attempt_id,
                outcome="timeout",
                error_class=type(error).__name__,
            )
            raise
        except Exception as error:  # noqa: BLE001 - normalized into the ledger
            self._store.complete_attempt(
                reservation.attempt_id,
                outcome="error",
                error_class=type(error).__name__,
            )
            raise
        if usage_of is not None:
            usage = usage_of(reply)
        if isinstance(reply, ModelReply):
            usage = reply.usage
        self._store.complete_attempt(
            reservation.attempt_id,
            outcome="ok",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        charged = usage.total_tokens if usage.total_tokens is not None else tokens
        return DispatchResult(
            reservation=reservation,
            reply=reply,
            usage=usage,
            outcome="ok",
            charged_tokens=charged,
        )

    def _require_time_for_attempt(self) -> None:
        """Refuse dispatch unless a full bounded adapter timeout fits the run."""
        if self._deadline_monotonic is None:
            return
        if time.monotonic() + self._external_attempt_timeout_seconds > self._deadline_monotonic:
            raise AnalysisError("Run deadline reached; no external attempt was dispatched")

    def record_ambiguous(self, reservation: AttemptReservation) -> None:
        """Keep an unconfirmed attempt fully charged after a lost response."""
        self._store.complete_attempt(reservation.attempt_id, outcome="unconfirmed")

    def checkpoint(
        self,
        analysis_id: str,
        item_id: str,
        *,
        outcome: str,
        result: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        self._store.checkpoint_item(analysis_id, item_id, state=outcome, result=result, error=error)

    def finish(self, analysis_id: str, *, state: str) -> None:
        self._store.finish_analysis(analysis_id, state=state)

    def usage(self, analysis_id: str) -> dict[str, int]:
        return self._store.budget_usage(analysis_id, utc_now()[:10])

    # -- research coverage and first-time worklist (spec R15/R16) -----------
    def research_coverage(
        self, domain_rows: Mapping[str, int], *, as_of: str | None = None
    ) -> dict[str, object]:
        """Classify every eligible name into one mutually exclusive workflow state.

        Uses the live classification rules and prior terminal research outcomes
        from the local store. No external call is made and nothing is selected:
        this is a pure local read model.
        """
        return _research_coverage(
            domain_rows,
            rules=self._store.classification_rules(),
            prior_items=self._store.researched_domains(),
            as_of=as_of or utc_now(),
        )

    def first_time_page(
        self, coverage: Mapping[str, object], *, offset: int = 0, limit: int = MAX_WORKLIST
    ) -> dict[str, object]:
        """The next bounded page of not-yet-researched names (spec R16)."""
        from .research import ResearchError

        try:
            return first_time_page(coverage, offset=offset, limit=limit)  # type: ignore[arg-type]
        except ResearchError as error:
            raise AnalysisError(str(error)) from error

    def coverage_summary(self, coverage: Mapping[str, object]) -> dict[str, object]:
        """Sanitized coverage totals with explicit denominators."""
        return _coverage_summary(coverage)  # type: ignore[arg-type]

    # -- preview, confirmation and reanalysis -------------------------------
    def preview(
        self,
        *,
        period_digest: str,
        domain_rows: Mapping[str, int],
        provider: str | None,
        model_id: str | None,
        config_fingerprint: str | None,
        policy_revision: int | None,
        exclude: Sequence[str] = (),
    ) -> Preview:
        """Describe exactly what a confirmation would send; make no call."""
        plans, exclusions = plan_public_candidates(
            domain_rows,
            exclude=exclude,
            policy_revision=policy_revision or 1,
        )
        rules = self._store.classification_rules()
        as_of = utc_now()
        candidates = []
        for plan in plans:
            resolution = resolve_domain(plan.candidate.public_name, rules, as_of=as_of)
            candidates.append(
                {
                    "item_id": plan.candidate.item_id,
                    "name": plan.candidate.public_name,
                    "dns_rows": plan.dns_rows,
                    "cached": resolution.state == "resolved",
                }
            )
        token = preview_token_for(
            period_digest=period_digest,
            candidate_ids=[item["item_id"] for item in candidates],
            provider=provider,
            model_id=model_id,
            config_fingerprint=config_fingerprint,
            policy_revision=policy_revision,
        )
        return Preview(
            token=token,
            period_digest=period_digest,
            provider=provider,
            model_id=model_id,
            config_fingerprint=config_fingerprint,
            policy_revision=policy_revision,
            candidates=tuple(candidates),
            exclusions=tuple({"domain": item.domain, "reason": item.reason} for item in exclusions),
            limits=_limits_view(self._budget),
        )

    def start(
        self,
        *,
        period_digest: str,
        candidates: Sequence[Mapping[str, object]],
        provider: str | None,
        model_id: str | None,
        config_fingerprint: str | None,
        policy_revision: int | None,
        preview_token: str,
    ) -> tuple[str, bool]:
        """Create the frozen job only when the confirmed preview still matches."""
        if not candidates:
            raise AnalysisError("An analysis needs at least one candidate")
        normalized = []
        for item in candidates:
            name = str(item.get("domain") or item.get("name") or "").strip().lower().rstrip(".")
            if not name:
                raise AnalysisError("Each candidate needs a public name")
            normalized.append(
                {
                    "item_id": str(item["item_id"]),
                    "domain": name,
                    "claim_scope": str(item.get("claim_scope", "service_and_provider")),
                }
            )
        expected = preview_token_for(
            period_digest=period_digest,
            candidate_ids=[str(item["item_id"]) for item in candidates],
            provider=provider,
            model_id=model_id,
            config_fingerprint=config_fingerprint,
            policy_revision=policy_revision,
        )
        if not hmac.compare_digest(expected, preview_token):
            raise AnalysisError("Preview is stale or altered; reload and confirm again")
        return self.create(
            period_digest=period_digest,
            selected_item_ids=[item["item_id"] for item in normalized],
            candidates=normalized,
            provider=provider,
            model_id=model_id,
            config_fingerprint=config_fingerprint,
            policy_revision=policy_revision,
        )

    def reanalyze(self, analysis_id: str, *, nonce: str) -> str:
        """Create a new revision with the same candidates and a fresh identity."""
        if not nonce or len(nonce) > 64:
            raise AnalysisError("Reanalysis needs a short explicit nonce")
        original = self._store.analysis(analysis_id)
        items = self._store.items(analysis_id)
        candidates = [
            {
                "item_id": item["item_id"],
                "domain": item["domain"],
                "claim_scope": item["claim_scope"],
            }
            for item in items
        ]
        if not candidates:
            raise AnalysisError("The original analysis has no candidates to repeat")
        identity = analysis_identity(
            period_digest=str(original["period_digest"]),
            selection_digest=str(original["selection_digest"]),
            analyzer_version=ANALYZER_VERSION,
            provider=original["provider"],
            model_id=original["model_id"],
            config_fingerprint=original["config_fingerprint"],
            policy_revision=original["policy_revision"],
            nonce=nonce,
        )
        created, _ = self._store.create_analysis(
            analysis_id=identity,
            period_digest=str(original["period_digest"]),
            selection_digest=str(original["selection_digest"]),
            analyzer_version=ANALYZER_VERSION,
            provider=original["provider"],
            model_id=original["model_id"],
            config_fingerprint=original["config_fingerprint"],
            policy_revision=original["policy_revision"],
            items=candidates,
        )
        return created

    # -- model eligibility -------------------------------------------------
    def validate_model(
        self,
        analysis_id: str,
        *,
        provider: ModelProvider,
        model_id: str,
        completion_cap: int,
        free_only: bool = False,
        probe: bool = True,
    ) -> ModelCapabilities:
        """Check metadata (and, if needed, one bounded schema probe) before work."""
        described = self.dispatch_attempt(
            analysis_id,
            kind="provider_catalog",
            operation=lambda: provider.describe_model(model_id),
        ).reply
        if not isinstance(described, ModelCapabilities):
            raise AnalysisError("Provider metadata did not return model capabilities")
        capabilities = described
        if free_only and not capabilities.free_eligible:
            raise ModelIneligible(
                f"Model {model_id!r} is not zero-priced; free-only mode refuses it"
            )
        if capabilities.structured_output == "none":
            if not probe:
                raise ModelIneligible("Model has no verified structured-output support")
            probe_cap = min(completion_cap, 64)
            synthetic = PublicCandidate(item_id="example.com", public_name="example.com")
            request = build_model_request(
                model_id=model_id,
                candidates=[synthetic],
                evidence={},
                completion_cap=probe_cap,
            )
            tokens = reservation_tokens(
                capabilities, completion_cap=probe_cap, require_structured=False
            )
            reply = self.dispatch_attempt(
                analysis_id,
                kind="provider_probe",
                tokens=tokens,
                operation=lambda: provider.complete(request),
            ).reply
            if not isinstance(reply, ModelReply):
                raise AnalysisError("Provider probe did not return a model reply")
            try:
                parse_batch_content(reply.text)
            except GroundingError as error:
                raise ModelIneligible(
                    f"Model failed the bounded structured-output probe: {error}"
                ) from error
            capabilities = ModelCapabilities(
                model_id=capabilities.model_id,
                context_limit=capabilities.context_limit,
                completion_limit=capabilities.completion_limit,
                structured_output="json_schema",
                free_eligible=capabilities.free_eligible,
                input_modalities=capabilities.input_modalities,
                notes="structured output validated by one bounded probe",
            )
        return capabilities

    # -- the runner --------------------------------------------------------
    def run(
        self,
        analysis_id: str,
        *,
        provider: ModelProvider,
        evidence: EvidenceClient,
        model_id: str,
        capabilities: ModelCapabilities,
        completion_cap: int = 1024,
        sleep: Callable[[float], None] = time.sleep,
        max_batches: int = 64,
        allow_resume: bool = False,
    ) -> dict[str, object]:
        """Run or resume a frozen job in bounded batches, checkpointing each item."""
        analysis = self._store.analysis(analysis_id)
        state = str(analysis["state"])
        if state in {"completed", "failed", "cancelled"} or (
            state == "partial" and not allow_resume
        ):
            return self._result(analysis_id)
        if int(analysis["analyzer_version"]) != ANALYZER_VERSION:
            raise AnalysisError(
                "Old analysis revision cannot be resumed under a new grounding contract"
            )
        self._store.pause_interrupted(analysis_id)
        if allow_resume:
            self._store.clear_summary(analysis_id)
            self._store.reopen_deferred(analysis_id)
        rules = self._store.classification_rules()
        tokens = reservation_tokens(capabilities, completion_cap=completion_cap)
        deferred = False
        batches = 0
        while batches < max_batches:
            batches += 1
            claimed = self.claim_batch(analysis_id, limit=MAX_BATCH_SIZE)
            if not claimed:
                break
            try:
                self._run_batch(
                    analysis_id,
                    claimed,
                    provider=provider,
                    evidence=evidence,
                    model_id=model_id,
                    tokens=tokens,
                    completion_cap=completion_cap,
                    rules=rules,
                    sleep=sleep,
                )
            except BudgetExceeded as error:
                deferred = True
                self._defer_remaining(analysis_id, reason=str(error))
                break
        state = self._terminal_state(analysis_id, forced_partial=deferred)
        summary = self.finish_with_summary(analysis_id, state=state)
        return {
            "analysis_id": analysis_id,
            "state": state,
            "summary": summary,
            "usage": self.usage(analysis_id),
        }

    def resume(self, analysis_id: str, **kwargs: object) -> dict[str, object]:
        """Explicit resume: same frozen job, only unfinished candidates."""
        return self.run(analysis_id, **kwargs)  # type: ignore[arg-type]

    def _run_batch(
        self,
        analysis_id: str,
        claimed: Sequence[str],
        *,
        provider: ModelProvider,
        evidence: EvidenceClient,
        model_id: str,
        tokens: int,
        completion_cap: int,
        rules: Sequence[Mapping[str, object]],
        sleep: Callable[[float], None],
    ) -> None:
        analysis = self._store.analysis(analysis_id)
        policy_revision = int(analysis["policy_revision"] or 1)
        items = {item["item_id"]: item for item in self._store.items(analysis_id)}
        candidates: list[PublicCandidate] = []
        bundles: dict[str, EvidenceBundle] = {}
        as_of = utc_now()

        for item_id in claimed:
            item = items[item_id]
            resolution = resolve_domain(str(item["domain"]), rules, as_of=as_of)
            if resolution.state == "resolved" and resolution.rule is not None:
                rule = resolution.rule
                self.checkpoint(
                    analysis_id,
                    item_id,
                    outcome="done",
                    result={
                        "service": rule.get("service"),
                        "provider": rule.get("provider"),
                        "category": rule.get("category", "unknown"),
                        "confidence": rule.get("confidence", "unknown"),
                        "ambiguity": rule.get("ambiguity"),
                        "verification_state": rule.get("verification_state", "reviewed"),
                        "evidence_ids": [],
                        "source": "cache",
                        "matched": resolution.matched,
                    },
                )
                continue

            try:
                found = self._call_with_retries(
                    analysis_id,
                    kind="exa_search",
                    tokens=0,
                    item_id=item_id,
                    operation=lambda name=str(item["domain"]): evidence.search(
                        name, dict(SEARCH_LIMITS)
                    ),
                    sleep=sleep,
                ).reply
            except ExternalError as error:
                self.checkpoint(
                    analysis_id,
                    item_id,
                    outcome="failed",
                    error=f"evidence search failed: {error}",
                )
                continue
            sources = tuple(found) if found is not None else ()
            if not sources:
                self.checkpoint(
                    analysis_id,
                    item_id,
                    outcome="unknown",
                    result={
                        "unresolved_reason": "no public evidence retrieved",
                        "source": "evidence",
                    },
                )
                continue
            candidate = PublicCandidate(
                item_id=item_id,
                public_name=str(item["domain"]),
                claim_scope=str(item["claim_scope"]),
                policy_revision=policy_revision,
            )
            candidates.append(candidate)
            bundles[item_id] = EvidenceBundle(candidate_id=item_id, sources=sources)

        if not candidates:
            return

        request = build_model_request(
            model_id=model_id,
            candidates=candidates,
            evidence=bundles,
            completion_cap=completion_cap,
        )
        bounded_bundles = {bundle.candidate_id: bundle for bundle in request.evidence}
        try:
            reply = self._call_with_retries(
                analysis_id,
                kind="provider_request",
                tokens=tokens,
                operation=lambda: provider.complete(request),
                sleep=sleep,
            ).reply
        except ExternalError as error:
            for candidate in candidates:
                self.checkpoint(
                    analysis_id,
                    candidate.item_id,
                    outcome="failed",
                    error=f"model call failed: {error}",
                )
            return
        if not isinstance(reply, ModelReply):
            raise AnalysisError("Provider returned no model reply")
        try:
            results = parse_batch_content(reply.text)
        except GroundingError as error:
            for candidate in candidates:
                self.checkpoint(
                    analysis_id,
                    candidate.item_id,
                    outcome="unknown",
                    result={
                        "unresolved_reason": f"model output rejected: {error}",
                        "source": "model",
                    },
                )
            return

        by_id = {str(item.get("item_id")): item for item in results}
        for candidate in candidates:
            payload = by_id.get(candidate.item_id)
            if payload is None:
                self.checkpoint(
                    analysis_id,
                    candidate.item_id,
                    outcome="unknown",
                    result={
                        "unresolved_reason": "model omitted this candidate",
                        "source": "model",
                    },
                )
                continue
            bundle = bounded_bundles[candidate.item_id]
            try:
                result = validate_grounded(
                    payload,
                    candidate=candidate,
                    evidence=bundle,
                    spans=request.spans,
                    expected_version=request.contract_version,
                )
            except GroundingError as error:
                self.checkpoint(
                    analysis_id,
                    candidate.item_id,
                    outcome="unknown",
                    result={
                        "unresolved_reason": f"model output rejected: {error}",
                        "source": "model",
                    },
                )
                continue
            self.checkpoint(
                analysis_id,
                candidate.item_id,
                outcome="done",
                result={
                    "service": result.service,
                    "provider": result.provider,
                    "role": result.role,
                    "category": result.category,
                    "confidence": result.confidence,
                    "ambiguity": result.ambiguity,
                    "verification_state": result.verification_state,
                    "evidence_ids": list(result.evidence_ids),
                    "span_ids": list(result.span_ids),
                    "supporting_spans": [
                        {
                            "span_id": span.span_id,
                            "source_id": span.source_id,
                            "source_url": next(
                                source.url
                                for source in bundle.sources
                                if source.source_id == span.source_id
                            ),
                            "source_sha256": span.source_sha256,
                            "start": span.start,
                            "end": span.end,
                            "text": span.text,
                        }
                        for span in request.spans
                        if span.span_id in result.span_ids
                    ],
                    "grounding_contract_version": request.contract_version,
                    "source_hashes": {
                        source.source_id: hashlib.sha256(source.excerpt.encode()).hexdigest()
                        for source in bundle.sources
                        if source.source_id in result.evidence_ids
                    },
                    "unresolved_reason": result.unresolved_reason,
                    "source": "model",
                },
            )
            try:
                rule = result_to_rule(
                    result,
                    candidate=candidate,
                    evidence=bundle,
                    checked_utc=utc_now(),
                    model_provenance=f"model:{reply.model_id}",
                )
            except GroundingError:
                rule = None
            if rule is not None:
                self._store.add_classification_rule(rule)

    def _call_with_retries(
        self,
        analysis_id: str,
        *,
        kind: str,
        tokens: int,
        operation: Callable[[], object],
        item_id: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> DispatchResult:
        """At most two separately reserved attempts, and only for transient errors."""
        last: Exception | None = None
        for attempt in range(1, self._max_attempts_per_operation + 1):
            try:
                return self.dispatch_attempt(
                    analysis_id, kind=kind, tokens=tokens, operation=operation, item_id=item_id
                )
            except (ExternalError, TimeoutError) as error:
                last = error
                retryable = isinstance(error, TimeoutError) or bool(
                    getattr(error, "retryable", False)
                )
                if not retryable or attempt == self._max_attempts_per_operation:
                    raise
                sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])
        raise AnalysisError("Retry loop ended without a result") from last

    def _defer_remaining(self, analysis_id: str, *, reason: str) -> None:
        for item in self._store.items(analysis_id):
            if item["state"] in {"pending", "claimed"}:
                self.checkpoint(analysis_id, item["item_id"], outcome="deferred", error=reason)

    def _terminal_state(self, analysis_id: str, *, forced_partial: bool) -> str:
        states = {item["state"] for item in self._store.items(analysis_id)}
        if "pending" in states or "claimed" in states:
            # Work remains and was not refused by a budget: keep it explicitly resumable.
            return "partial" if forced_partial else "paused"
        if forced_partial or states - {"done", "unknown"}:
            return "partial"
        return "completed"

    def _result(self, analysis_id: str) -> dict[str, object]:
        analysis = self._store.analysis(analysis_id)
        return {
            "analysis_id": analysis_id,
            "state": analysis["state"],
            "summary": analysis["summary"],
            "usage": self.usage(analysis_id),
        }

    # -- summary -----------------------------------------------------------
    def compose_summary(self, analysis_id: str) -> str:
        """Deterministic local summary from stored results; no extra model call."""
        self._store.analysis(analysis_id)  # existence check before composing
        items = self._store.items(analysis_id)
        buckets = {"done": 0, "unknown": 0, "deferred": 0, "failed": 0, "pending": 0, "claimed": 0}
        services = 0
        providers = 0
        for item in items:
            state = str(item["state"])
            buckets[state] = buckets.get(state, 0) + 1
            if state == "done" and item["result_json"]:
                result = json.loads(item["result_json"])
                if result.get("service"):
                    services += 1
                elif result.get("provider"):
                    providers += 1
        usage = self._store.budget_usage(analysis_id, utc_now()[:10])
        parts = [
            f"{len(items)} candidates considered: {services} service-specific, "
            f"{providers} provider or infrastructure only, {buckets['unknown']} unknown.",
        ]
        if buckets["deferred"]:
            parts.append(f"{buckets['deferred']} deferred by budget for explicit review.")
        if buckets["failed"]:
            parts.append(f"{buckets['failed']} failed and remain unresolved.")
        if buckets["pending"] or buckets["claimed"]:
            parts.append(
                f"{buckets['pending'] + buckets['claimed']} not yet completed; resume explicitly."
            )
        parts.append(
            f"Provider requests: {usage['analysis_requests']}, reserved/used tokens: "
            f"{usage['analysis_tokens']}, Exa attempts: {usage['analysis_exa']}. "
            "Counts are local observations, not connections, sessions or device activity."
        )
        return " ".join(parts)

    def finish_with_summary(self, analysis_id: str, *, state: str) -> str | None:
        """Store at most one summary, only on a terminal analysis row."""
        self.finish(analysis_id, state=state)
        if state not in {"completed", "partial", "failed", "cancelled"}:
            return None
        summary = self.compose_summary(analysis_id)
        return summary if self._store.save_summary(analysis_id, summary) else None


def preview_token_for(
    *,
    period_digest: str,
    candidate_ids: Sequence[str],
    provider: str | None,
    model_id: str | None,
    config_fingerprint: str | None,
    policy_revision: int | None,
) -> str:
    """Identity of exactly what a confirmation would disclose and spend on."""
    payload = {
        "version": PREVIEW_VERSION,
        "period": period_digest,
        "selection": selection_digest(candidate_ids),
        "provider": provider,
        "model": model_id,
        "config": config_fingerprint,
        "policy": policy_revision,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Preview:
    """Local-only disclosure preview; no call happens to build it."""

    token: str
    period_digest: str
    provider: str | None
    model_id: str | None
    config_fingerprint: str | None
    policy_revision: int | None
    candidates: tuple[dict[str, object], ...]
    exclusions: tuple[dict[str, object], ...]
    limits: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "preview_token": self.token,
            "period_digest": self.period_digest,
            "provider": self.provider,
            "model_id": self.model_id,
            "config_fingerprint": self.config_fingerprint,
            "policy_revision": self.policy_revision,
            "candidates": list(self.candidates),
            "excluded": list(self.exclusions),
            "limits": dict(self.limits),
            "note": (
                "Only the listed public names and their bounded evidence excerpts leave "
                "this machine, and only after explicit confirmation. Counts, clients, "
                "timestamps and raw rows never do."
            ),
        }


def _limits_view(budget: AttemptBudget) -> dict[str, int]:
    limits = {
        "requests_per_analysis": budget.per_analysis_requests,
        "requests_per_day": budget.per_day_requests,
        "tokens_per_analysis": budget.per_analysis_tokens,
        "tokens_per_day": budget.per_day_tokens,
        "exa_per_analysis": budget.per_analysis_exa,
        "exa_per_day": budget.per_day_exa,
    }
    for name in ("search", "fetch", "discover", "catalog", "probe", "completion"):
        for scope in ("analysis", "day"):
            value = getattr(budget, f"per_{scope}_{name}")
            if value is not None:
                limits[f"{name}_per_{scope}"] = value
    return limits


def budget_from_mapping(values: Mapping[str, int]) -> AttemptBudget:
    """Build limits from explicit operator configuration, rejecting silent defaults."""
    required = {
        "per_analysis_requests",
        "per_day_requests",
        "per_analysis_tokens",
        "per_day_tokens",
        "per_analysis_exa",
        "per_day_exa",
    }
    missing = required - set(values)
    if missing:
        raise ContractError(f"Missing budget fields: {sorted(missing)}")
    optional = {
        f"per_{scope}_{kind}"
        for scope in ("analysis", "day")
        for kind in ("search", "fetch", "discover", "catalog", "probe", "completion")
    }
    return AttemptBudget(**{key: int(values[key]) for key in required | (optional & set(values))})


def live_budget_from_mapping(values: Mapping[str, int]) -> AttemptBudget:
    """Fail closed for an optional run unless every operation has a numeric cap."""
    operations = {
        f"per_{scope}_{kind}"
        for scope in ("analysis", "day")
        for kind in ("search", "fetch", "discover", "catalog", "probe", "completion")
    }
    missing = operations - set(values)
    if missing:
        raise ContractError(f"Missing live operation limits: {sorted(missing)}")
    return budget_from_mapping(values)


__all__ = [
    "ANALYZER_VERSION",
    "MAX_ATTEMPTS_PER_OPERATION",
    "PREVIEW_VERSION",
    "Preview",
    "preview_token_for",
    "AnalysisError",
    "AnalysisService",
    "BudgetExceeded",
    "DEFAULT_BUDGET",
    "DispatchResult",
    "ModelIneligible",
    "StorageError",
    "UnknownTokenBound",
    "analysis_identity",
    "budget_from_mapping",
    "live_budget_from_mapping",
    "reservation_tokens",
    "selection_digest",
]
