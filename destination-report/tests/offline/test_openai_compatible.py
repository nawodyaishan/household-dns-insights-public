"""OpenAI-compatible adapter tests: one attempt, capability discovery, and limits."""

from __future__ import annotations

import json
import unittest

import httpx

from household_report.classification import build_model_request
from household_report.contracts import ExternalError, ModelRequest, PublicCandidate
from household_report.integrations.openai_compatible import (
    AUTO_ROUTER_MODELS,
    RESERVED_BODY_KEYS,
    OpenAICompatibleProvider,
)

CANDIDATE = PublicCandidate(item_id="example.com", public_name="example.com")


def request(model: str = "vendor/test-model") -> ModelRequest:
    return build_model_request(
        model_id=model, candidates=[CANDIDATE], evidence={}, completion_cap=128
    )


class MistralCatalogueTests(unittest.TestCase):
    """Mistral-shaped /v1/models responses (bare array, max_context_length cards)."""

    MISTRAL_ENTRY = {
        "id": "mistral-small-latest",
        "object": "model",
        "created": 1756746619,
        "owned_by": "mistral_organization",
        "capabilities": {
            "completion_chat": True,
            "completion_fim": False,
            "function_calling": False,
            "enterprise_features": False,
            "vision": False,
        },
        "max_context_length": 32768,
    }

    def provider(self, *, structured_output=None):
        def handler(req: httpx.Request) -> httpx.Response:
            self.assertEqual(req.method, "GET")
            self.assertEqual(str(req.url), "https://api.mistral.ai/v1/models")
            return httpx.Response(
                200, json=[self.MISTRAL_ENTRY, {"id": "other", "max_context_length": 8}]
            )

        return OpenAICompatibleProvider(
            api_key="key",
            base_url="https://api.mistral.ai/v1",
            label="mistral",
            structured_output=structured_output,
            completion_limit=512,
            transport=httpx.MockTransport(handler),
        )

    def test_bare_array_catalogue_is_read_with_max_context_length(self):
        capabilities = self.provider(structured_output="json_schema").describe_model(
            "mistral-small-latest"
        )
        self.assertEqual(capabilities.context_limit, 32768)
        self.assertEqual(capabilities.completion_limit, 512)
        self.assertEqual(capabilities.structured_output, "json_schema")
        self.assertIn("operator-declared structured-output mode", capabilities.notes)
        self.assertFalse(capabilities.free_eligible)

    def test_unknown_structured_mode_declaration_is_refused_without_any_request(self):
        with self.assertRaises(ExternalError):
            self.provider(structured_output="json_five")

    def test_catalogue_of_non_object_entries_is_refused(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["not-an-object"])

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="https://api.mistral.ai/v1",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(ExternalError) as ctx:
            provider.describe_model("mistral-small-latest")
        self.assertIn("catalogue", str(ctx.exception))


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_empty_api_key_is_refused(self):
        with self.assertRaises(ExternalError):
            OpenAICompatibleProvider(api_key="", base_url="http://127.0.0.1:20128/v1")

    def test_reserved_body_key_override_is_refused(self):
        for key in RESERVED_BODY_KEYS:
            with self.assertRaises(ExternalError) as ctx:
                OpenAICompatibleProvider(
                    api_key="secret",
                    base_url="http://127.0.0.1:20128/v1",
                    extra_body={key: "illegal"},
                )
            self.assertIn("extra_body may not override", str(ctx.exception))

    def test_openrouter_catalogue_with_pricing_and_top_provider(self):
        def handler(req: httpx.Request) -> httpx.Response:
            self.assertEqual(req.url.path, "/api/v1/models")
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "openai/gpt-oss-20b",
                            "context_length": 131072,
                            "pricing": {"prompt": "0.000018", "completion": "0.00009"},
                            "top_provider": {"max_completion_tokens": 32768},
                            "supported_parameters": [
                                "tools",
                                "response_format",
                                "structured_outputs",
                            ],
                        }
                    ]
                },
            )

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="https://openrouter.ai/api/v1",
            label="openrouter",
            transport=httpx.MockTransport(handler),
        )
        caps = provider.describe_model("openai/gpt-oss-20b")
        self.assertEqual(caps.model_id, "openai/gpt-oss-20b")
        self.assertEqual(caps.context_limit, 131072)
        self.assertEqual(caps.completion_limit, 32768)
        self.assertEqual(caps.structured_output, "json_schema")
        self.assertFalse(caps.free_eligible)

    def test_9router_catalogue_with_capabilities(self):
        def handler(req: httpx.Request) -> httpx.Response:
            self.assertEqual(req.url.path, "/v1/models")
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "ag/gemini-3.8-flash",
                            "object": "model",
                            "capabilities": {
                                "contextWindow": 1048576,
                                "maxOutput": 65536,
                                "tools": True,
                            },
                            "context_length": 1048576,
                            "max_completion_tokens": 65536,
                        }
                    ]
                },
            )

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="http://127.0.0.1:20128/v1",
            label="9router",
            transport=httpx.MockTransport(handler),
        )
        caps = provider.describe_model("ag/gemini-3.8-flash")
        self.assertEqual(caps.model_id, "ag/gemini-3.8-flash")
        self.assertEqual(caps.context_limit, 1048576)
        self.assertEqual(caps.completion_limit, 65536)
        self.assertEqual(caps.structured_output, "none")

    def test_operator_declared_limits_fill_missing_catalogue_limits(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "local/model"}]})

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="http://localhost:11434/v1",
            label="ollama",
            context_limit=8192,
            completion_limit=2048,
            transport=httpx.MockTransport(handler),
        )
        caps = provider.describe_model("local/model")
        self.assertEqual(caps.context_limit, 8192)
        self.assertEqual(caps.completion_limit, 2048)
        self.assertIn("operator-declared context/completion limit", caps.notes)

    def test_missing_limits_without_operator_declaration_is_refused(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "sparse/model"}]})

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="http://127.0.0.1:20128/v1",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(ExternalError) as ctx:
            provider.describe_model("sparse/model")
        self.assertIn("lacks verified context/completion limits", str(ctx.exception))

    def test_auto_router_models_are_refused(self):
        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="https://openrouter.ai/api/v1",
        )
        for model_id in AUTO_ROUTER_MODELS:
            with self.assertRaises(ExternalError) as ctx:
                provider.describe_model(model_id)
            self.assertIn("picks models per request", str(ctx.exception))

    def test_unknown_model_raises_external_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "other/model"}]})

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="http://127.0.0.1:20128/v1",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(ExternalError) as ctx:
            provider.describe_model("wanted/model")
        self.assertIn("is not in the", str(ctx.exception))

    def test_complete_sends_expected_payload_and_extra_body(self):
        captured_body: dict[str, object] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            self.assertEqual(req.url.path, "/v1/chat/completions")
            captured_body = json.loads(req.content)
            return httpx.Response(
                200,
                json={
                    "id": "chat-1",
                    "model": "vendor/test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"candidates": []}),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
                },
            )

        provider = OpenAICompatibleProvider(
            api_key="secret-key",
            base_url="http://127.0.0.1:20128/v1",
            extra_body={"provider": {"require_parameters": True, "data_collection": "deny"}},
            transport=httpx.MockTransport(handler),
        )
        reply = provider.complete(request("vendor/test-model"))
        self.assertEqual(reply.finish_reason, "stop")
        self.assertEqual(reply.usage.total_tokens, 70)
        self.assertEqual(captured_body["model"], "vendor/test-model")
        self.assertFalse(captured_body["stream"])
        self.assertEqual(captured_body["temperature"], 0)
        self.assertEqual(
            captured_body["provider"],
            {"require_parameters": True, "data_collection": "deny"},
        )

    def test_free_only_checks_zero_cost_and_usage(self):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "chat-2",
                    "model": "vendor/free-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"candidates": []}),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                        "cost": 0.05,
                    },
                },
            )

        provider = OpenAICompatibleProvider(
            api_key="key",
            base_url="https://openrouter.ai/api/v1",
            free_only=True,
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(ExternalError) as ctx:
            provider.complete(request("vendor/free-model"))
        self.assertIn("non-zero cost", str(ctx.exception))

    def test_http_status_errors_are_classified_without_exposing_body(self):
        for status in (401, 403, 429, 500):

            def handler(req: httpx.Request, s=status) -> httpx.Response:
                return httpx.Response(s, text="sensitive body info")

            provider = OpenAICompatibleProvider(
                api_key="key",
                base_url="http://127.0.0.1:20128/v1",
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(ExternalError) as ctx:
                provider.complete(request("vendor/test-model"))
            self.assertNotIn("sensitive body info", str(ctx.exception))
            self.assertEqual(ctx.exception.status, status)
