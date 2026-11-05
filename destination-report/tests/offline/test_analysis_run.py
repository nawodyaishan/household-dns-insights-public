"""Runner contracts: cache-first batches, grounding, budgets, retries and resume.

Every external effect goes through fakes. Nothing here contacts a provider or MCP
server, and the tests assert that an empty cache is the only reason a call happens.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from household_report.analysis import (
    AnalysisError,
    AnalysisService,
    ModelIneligible,
    Preview,
)
from household_report.contracts import (
    AttemptBudget,
    EvidenceSource,
    ExternalError,
    ModelCapabilities,
    ModelReply,
    Usage,
)
from household_report.storage import open_store

BUDGET = AttemptBudget(
    per_analysis_requests=8,
    per_day_requests=40,
    per_analysis_tokens=100_000,
    per_day_tokens=400_000,
    per_analysis_exa=8,
    per_day_exa=40,
)

TIGHT = AttemptBudget(
    per_analysis_requests=2,
    per_day_requests=4,
    per_analysis_tokens=100_000,
    per_day_tokens=200_000,
    per_analysis_exa=1,
    per_day_exa=2,
)

MODEL = "test/model"
EXCERPT = "Example Video is a video streaming service operated by Example Inc."


def capabilities(**overrides) -> ModelCapabilities:
    base = {
        "model_id": MODEL,
        "context_limit": 8000,
        "completion_limit": 2000,
        "structured_output": "json_schema",
        "free_eligible": True,
    }
    base.update(overrides)
    return ModelCapabilities(**base)


def source(index: int = 1) -> EvidenceSource:
    return EvidenceSource(
        source_id=f"s{index}",
        url="https://www.example.com/about",
        excerpt=EXCERPT,
        content_sha256="a" * 64,
        captured_utc="2026-10-23T00:00:00Z",
    )


class FakeEvidence:
    """One bounded search per item; records queries and never fetches."""

    def __init__(self, *, sources=None, error: Exception | None = None) -> None:
        self.sources = sources if sources is not None else {"*": (source(),)}
        self.error = error
        self.searches: list[str] = []

    def discover(self, limits):
        raise AssertionError("a run never performs protocol discovery")

    def search(self, public_query, limits):
        self.searches.append(public_query)
        if self.error is not None:
            raise self.error
        return self.sources.get(public_query, self.sources.get("*", ()))

    def fetch(self, public_urls, limits):
        raise AssertionError("a run never fetches arbitrary URLs")


class GroundedProvider:
    """Answers every requested candidate with a grounded, cited result."""

    def __init__(self) -> None:
        self.requests = []

    def describe_model(self, model_id):
        raise AssertionError("the runner does not probe metadata")

    def complete(self, request):
        self.requests.append(request)
        results = []
        for candidate in request.candidates:
            bundle = next(
                item for item in request.evidence if item.candidate_id == candidate.item_id
            )
            results.append(
                {
                    "item_id": candidate.item_id,
                    "service": "Example Video",
                    "provider": "Example Inc",
                    "role": "unknown",
                    "category": "media",
                    "evidence_ids": [bundle.sources[0].source_id],
                    "contract_version": 2,
                    "span_ids": [
                        next(
                            span.span_id
                            for span in request.spans
                            if span.candidate_id == candidate.item_id
                        )
                    ],
                    "confidence": "high",
                    "ambiguity": None,
                    "unresolved_reason": None,
                }
            )
        return ModelReply(
            model_id=request.model_id,
            text=json.dumps({"results": results}),
            usage=Usage(prompt_tokens=30, completion_tokens=10),
        )


class ScriptedProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests = []

    def describe_model(self, model_id):
        raise AssertionError("the runner does not probe metadata")

    def complete(self, request):
        self.requests.append(request)
        text = (
            self.text.replace("__FIRST_SPAN__", request.spans[0].span_id)
            if request.spans
            else self.text
        )
        return ModelReply(model_id=request.model_id, text=text, usage=Usage(10, 5))


class NoCallProvider:
    def __init__(self) -> None:
        self.requests = []

    def describe_model(self, model_id):
        raise AssertionError("a cached analysis must not describe a model")

    def complete(self, request):
        self.requests.append(request)
        raise AssertionError("a cached analysis must not call the provider")


class RunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "app.sqlite3"
        self.store = open_store(self.path)
        self.addCleanup(self.store.close)
        self.service = AnalysisService(self.store, budget=BUDGET)

    # -- helpers -----------------------------------------------------------
    def create(self, domains, *, period="period", budget_service=None):
        service = budget_service or self.service
        return service.create(
            period_digest=period,
            selected_item_ids=list(domains),
            candidates=[{"item_id": name, "domain": name} for name in domains],
            provider="groq",
            model_id=MODEL,
            config_fingerprint="cfg",
            policy_revision=1,
        )[0]

    def run_job(self, analysis, *, provider, evidence, service=None, **kwargs):
        service = service or self.service
        return service.run(
            analysis,
            provider=provider,
            evidence=evidence,
            model_id=MODEL,
            capabilities=capabilities(),
            sleep=kwargs.pop("sleep", lambda _seconds: None),
            **kwargs,
        )

    def items(self, analysis):
        return {item["item_id"]: item for item in self.store.items(analysis)}

    def reviewed_rule(self, domain, *, verified_until="2099-01-01T00:00:00Z"):
        self.store.add_classification_rule(
            {
                "domain": domain,
                "match": "exact",
                "field_scope": "service_and_provider",
                "service": "Example Video",
                "provider": "Example Inc",
                "category": "media",
                "confidence": "high",
                "ambiguity": None,
                "method": "reviewed",
                "verification_state": "reviewed",
                "checked_utc": "2026-10-01T00:00:00Z",
                "verified_until": verified_until,
                "policy_revision": 1,
                "evidence": [
                    {
                        "url": "https://www.example.com/about",
                        "claim": "Example Video is a video streaming service.",
                    }
                ],
                "source_hash": "b" * 64,
                "model_provenance": None,
            }
        )

    # -- cache first -------------------------------------------------------
    def test_cache_hit_makes_no_external_call_at_all(self):
        self.reviewed_rule("cdn.example.org")
        analysis = self.create(["cdn.example.org"])
        provider, evidence = NoCallProvider(), FakeEvidence()
        result = self.run_job(analysis, provider=provider, evidence=evidence)
        self.assertEqual(result["state"], "completed")
        item = self.items(analysis)["cdn.example.org"]
        self.assertEqual(item["state"], "done")
        self.assertEqual(json.loads(item["result_json"])["source"], "cache")
        self.assertEqual(provider.requests, [])
        self.assertEqual(evidence.searches, [])
        self.assertEqual(self.store.count_attempts(analysis), 0)

    def test_expired_cache_rule_is_researched(self):
        self.reviewed_rule("cdn.example.org", verified_until="2000-01-01T00:00:00Z")
        analysis = self.create(["cdn.example.org"])
        evidence = FakeEvidence()
        self.run_job(analysis, provider=GroundedProvider(), evidence=evidence)
        self.assertEqual(evidence.searches, ["cdn.example.org"])

    def test_grounded_result_is_promoted_to_a_dated_rule(self):
        analysis = self.create(["cdn.example.org"])
        provider, evidence = GroundedProvider(), FakeEvidence()
        result = self.run_job(analysis, provider=provider, evidence=evidence)
        self.assertEqual(result["state"], "completed")
        stored = json.loads(self.items(analysis)["cdn.example.org"]["result_json"])
        self.assertEqual(stored["service"], "Example Video")
        self.assertEqual(stored["source"], "model")
        self.assertEqual(stored["evidence_ids"], ["s1"])
        self.assertEqual(stored["grounding_contract_version"], 2)
        self.assertEqual(stored["supporting_spans"][0]["text"], EXCERPT)
        rules = [
            rule
            for rule in self.store.classification_rules()
            if rule["domain"] == "cdn.example.org"
        ]
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["verification_state"], "ai_grounded")
        self.assertEqual(rules[0]["evidence"][0]["claim"], EXCERPT)
        self.assertTrue(rules[0]["verified_until"].startswith("20"))
        self.assertEqual(self.store.count_attempts(analysis), 2)
        self.assertEqual(result["usage"]["analysis_exa"], 1)
        self.assertEqual(result["usage"]["analysis_tokens"], 40)

    def test_second_job_reuses_the_promoted_rule(self):
        first = self.create(["cdn.example.org"])
        self.run_job(first, provider=GroundedProvider(), evidence=FakeEvidence())
        second = self.create(["cdn.example.org"], period="period-2")
        self.assertNotEqual(first, second)
        provider, evidence = NoCallProvider(), FakeEvidence()
        result = self.run_job(second, provider=provider, evidence=evidence)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(
            json.loads(self.items(second)["cdn.example.org"]["result_json"])["source"], "cache"
        )
        self.assertEqual(provider.requests, [])

    # -- explicit unknowns -------------------------------------------------
    def test_no_evidence_is_an_explicit_unknown_and_no_model_call(self):
        analysis = self.create(["cdn.example.org"])
        provider, evidence = NoCallProvider(), FakeEvidence(sources={})
        result = self.run_job(analysis, provider=provider, evidence=evidence)
        self.assertEqual(result["state"], "completed")
        stored = json.loads(self.items(analysis)["cdn.example.org"]["result_json"])
        self.assertEqual(stored["unresolved_reason"], "no public evidence retrieved")
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.classification_rules(), [])

    def test_omitted_candidate_stays_unknown(self):
        analysis = self.create(["alpha.example.org", "beta.example.org"])
        provider = ScriptedProvider(
            json.dumps(
                {
                    "results": [
                        {
                            "item_id": "alpha.example.org",
                            "service": "Example Video",
                            "provider": "Example Inc",
                            "role": "unknown",
                            "category": "media",
                            "evidence_ids": ["s1"],
                            "contract_version": 2,
                            "span_ids": ["__FIRST_SPAN__"],
                            "confidence": "high",
                            "ambiguity": None,
                            "unresolved_reason": None,
                        }
                    ]
                }
            )
        )
        self.run_job(analysis, provider=provider, evidence=FakeEvidence())
        items = self.items(analysis)
        self.assertEqual(items["alpha.example.org"]["state"], "done")
        self.assertEqual(items["beta.example.org"]["state"], "unknown")
        stored = json.loads(items["beta.example.org"]["result_json"])
        self.assertEqual(stored["unresolved_reason"], "model omitted this candidate")

    def test_unretrieved_evidence_id_rejects_the_claim(self):
        analysis = self.create(["cdn.example.org"])
        provider = ScriptedProvider(
            json.dumps(
                {
                    "results": [
                        {
                            "item_id": "cdn.example.org",
                            "service": "Example Video",
                            "provider": "Example Inc",
                            "role": "unknown",
                            "category": "media",
                            "evidence_ids": ["s9"],
                            "contract_version": 2,
                            "span_ids": [],
                            "confidence": "high",
                            "ambiguity": None,
                            "unresolved_reason": None,
                        }
                    ]
                }
            )
        )
        self.run_job(analysis, provider=provider, evidence=FakeEvidence())
        item = self.items(analysis)["cdn.example.org"]
        self.assertEqual(item["state"], "unknown")
        self.assertIn("not retrieved", json.loads(item["result_json"])["unresolved_reason"])
        self.assertEqual(self.store.classification_rules(), [])

    def test_malformed_model_output_rejects_the_whole_batch(self):
        analysis = self.create(["cdn.example.org"])
        provider = ScriptedProvider("I think it is a video service.")
        self.run_job(analysis, provider=provider, evidence=FakeEvidence())
        item = self.items(analysis)["cdn.example.org"]
        self.assertEqual(item["state"], "unknown")
        self.assertIn("rejected", json.loads(item["result_json"])["unresolved_reason"])

    # -- budgets and retries ----------------------------------------------
    def test_budget_exhaustion_defers_the_rest_and_finishes_partial(self):
        service = AnalysisService(self.store, budget=TIGHT)
        analysis = self.create(["alpha.example.org", "beta.example.org"], budget_service=service)
        result = self.run_job(
            analysis, provider=GroundedProvider(), evidence=FakeEvidence(), service=service
        )
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["usage"]["analysis_exa"], 1)
        self.assertEqual(self.store.count_attempts(analysis), 1)
        states = {item["state"] for item in self.store.items(analysis)}
        self.assertEqual(states, {"deferred"})
        self.assertIn("deferred by budget", str(result["summary"]))

    def test_explicit_resume_reopens_deferred_items_only(self):
        tight = AnalysisService(self.store, budget=TIGHT)
        analysis = self.create(["alpha.example.org", "beta.example.org"], budget_service=tight)
        self.run_job(analysis, provider=GroundedProvider(), evidence=FakeEvidence(), service=tight)
        self.assertEqual(self.store.analysis(analysis)["state"], "partial")

        resumed = self.run_job(
            analysis,
            provider=GroundedProvider(),
            evidence=FakeEvidence(),
            service=self.service,
            allow_resume=True,
        )
        self.assertEqual(resumed["state"], "completed")
        self.assertEqual({item["state"] for item in self.store.items(analysis)}, {"done"})
        self.assertNotIn("deferred", str(resumed["summary"]))
        self.assertIn("2 candidates considered", str(resumed["summary"]))

        before = self.store.count_attempts(analysis)
        again = self.service.resume(
            analysis,
            provider=NoCallProvider(),
            evidence=FakeEvidence(),
            model_id=MODEL,
            capabilities=capabilities(),
        )
        self.assertEqual(again["state"], "completed")
        self.assertEqual(self.store.count_attempts(analysis), before)

    def test_retryable_failure_is_charged_twice_then_fails(self):
        analysis = self.create(["cdn.example.org"])
        sleeps: list[float] = []
        evidence = FakeEvidence(error=ExternalError("upstream 503", retryable=True))
        result = self.run_job(
            analysis,
            provider=NoCallProvider(),
            evidence=evidence,
            sleep=sleeps.append,
        )
        self.assertEqual(result["state"], "partial")
        self.assertEqual(self.store.count_attempts(analysis), 2)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(self.items(analysis)["cdn.example.org"]["state"], "failed")

    def test_single_attempt_policy_does_not_retry_transient_failure(self):
        guarded = AnalysisService(self.store, budget=BUDGET, max_attempts_per_operation=1)
        analysis = self.create(["cdn.example.org"], budget_service=guarded)
        sleeps: list[float] = []
        evidence = FakeEvidence(error=ExternalError("upstream 503", retryable=True))
        result = self.run_job(
            analysis,
            provider=NoCallProvider(),
            evidence=evidence,
            service=guarded,
            sleep=sleeps.append,
        )
        self.assertEqual(result["state"], "partial")
        self.assertEqual(len(evidence.searches), 1)
        self.assertEqual(self.store.count_attempts(analysis), 1)
        self.assertEqual(sleeps, [])

    def test_non_retryable_failure_is_not_retried(self):
        analysis = self.create(["cdn.example.org"])
        evidence = FakeEvidence(error=ExternalError("credentials rejected", retryable=False))
        self.run_job(analysis, provider=NoCallProvider(), evidence=evidence)
        self.assertEqual(self.store.count_attempts(analysis), 1)

    def test_batch_limit_pauses_instead_of_losing_progress(self):
        domains = [f"host{index}.example.org" for index in range(1, 7)]
        analysis = self.create(domains)
        result = self.run_job(
            analysis, provider=GroundedProvider(), evidence=FakeEvidence(), max_batches=1
        )
        self.assertEqual(result["state"], "paused")
        self.assertIsNone(self.store.analysis(analysis)["summary"])
        states = [item["state"] for item in self.store.items(analysis)]
        self.assertEqual(states.count("done"), 4)
        self.assertEqual(states.count("pending"), 2)

        resumed = self.service.resume(
            analysis,
            provider=GroundedProvider(),
            evidence=FakeEvidence(),
            model_id=MODEL,
            capabilities=capabilities(),
        )
        self.assertEqual(resumed["state"], "completed")
        self.assertEqual({item["state"] for item in self.store.items(analysis)}, {"done"})

    # -- preview, confirmation and reanalysis -----------------------------
    def test_preview_is_local_and_excludes_private_names(self):
        preview = self.service.preview(
            period_digest="period",
            domain_rows={"router.lan": 10, "10.0.0.1": 4, "cdn.example.org": 7},
            provider="groq",
            model_id=MODEL,
            config_fingerprint="cfg",
            policy_revision=1,
        )
        self.assertIsInstance(preview, Preview)
        self.assertEqual([item["name"] for item in preview.candidates], ["cdn.example.org"])
        self.assertEqual(len(preview.exclusions), 2)
        self.assertEqual(len(preview.limits), 6)
        self.assertEqual(self.store.count_attempts("nonexistent"), 0)
        self.assertNotEqual(
            preview.token,
            self.service.preview(
                period_digest="period",
                domain_rows={"cdn.example.org": 7},
                provider="groq",
                model_id="other/model",
                config_fingerprint="cfg",
                policy_revision=1,
            ).token,
        )

    def test_start_requires_the_confirmed_preview(self):
        preview = self.service.preview(
            period_digest="period",
            domain_rows={"cdn.example.org": 7},
            provider="groq",
            model_id=MODEL,
            config_fingerprint="cfg",
            policy_revision=1,
        )
        analysis, created = self.service.start(
            period_digest="period",
            candidates=[{"item_id": "cdn.example.org", "domain": "CDN.Example.ORG"}],
            provider="groq",
            model_id=MODEL,
            config_fingerprint="cfg",
            policy_revision=1,
            preview_token=preview.token,
        )
        self.assertTrue(created)
        self.assertEqual(self.store.items(analysis)[0]["domain"], "cdn.example.org")
        with self.assertRaises(AnalysisError):
            self.service.start(
                period_digest="period",
                candidates=[{"item_id": "cdn.example.org", "domain": "cdn.example.org"}],
                provider="groq",
                model_id="other/model",
                config_fingerprint="cfg",
                policy_revision=1,
                preview_token=preview.token,
            )

    def test_reanalyze_needs_an_explicit_nonce(self):
        analysis = self.create(["cdn.example.org"])
        self.run_job(analysis, provider=GroundedProvider(), evidence=FakeEvidence())
        first = self.service.reanalyze(analysis, nonce="one")
        self.assertNotEqual(first, analysis)
        self.assertEqual(self.service.reanalyze(analysis, nonce="one"), first)
        self.assertNotEqual(self.service.reanalyze(analysis, nonce="two"), first)
        self.assertEqual(
            {item["state"] for item in self.store.items(first)},
            {"pending"},
        )
        with self.assertRaises(AnalysisError):
            self.service.reanalyze(analysis, nonce="")

    # -- model eligibility -------------------------------------------------
    def test_structured_output_probe_is_one_bounded_request(self):
        analysis = self.create(["cdn.example.org"])
        provider = ScriptedProvider(json.dumps({"results": [{"item_id": "example.com"}]}))
        capabilities_without_schema = capabilities(structured_output="none")
        described = self.service.validate_model(
            analysis,
            provider=_DescribingProvider(provider, capabilities_without_schema),
            model_id=MODEL,
            completion_cap=1024,
        )
        self.assertEqual(described.structured_output, "json_schema")
        self.assertEqual(provider.requests[0].max_completion_tokens, 64)
        self.assertEqual(self.store.count_attempts(analysis), 2)

    def test_failed_probe_makes_the_model_ineligible(self):
        analysis = self.create(["cdn.example.org"])
        provider = ScriptedProvider("not json at all")
        with self.assertRaises(ModelIneligible):
            self.service.validate_model(
                analysis,
                provider=_DescribingProvider(provider, capabilities(structured_output="none")),
                model_id=MODEL,
                completion_cap=1024,
            )

    def test_free_only_mode_refuses_a_priced_model(self):
        analysis = self.create(["cdn.example.org"])
        provider = _DescribingProvider(ScriptedProvider("{}"), capabilities(free_eligible=False))
        with self.assertRaises(ModelIneligible):
            self.service.validate_model(
                analysis,
                provider=provider,
                model_id=MODEL,
                completion_cap=1024,
                free_only=True,
            )
        self.assertEqual(self.store.count_attempts(analysis), 1)


class _DescribingProvider:
    """Wraps a scripted completer with fixed metadata."""

    def __init__(self, completer, described: ModelCapabilities) -> None:
        self._completer = completer
        self._described = described
        self.requests = completer.requests

    def describe_model(self, model_id):
        return self._described

    def complete(self, request):
        return self._completer.complete(request)


if __name__ == "__main__":
    unittest.main()
