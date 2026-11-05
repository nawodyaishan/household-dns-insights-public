"""Settings and secret handling: explicit configuration, no network, no leaks."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from household_report.settings import (
    DEFAULT_BASE_URLS,
    ExaConfig,
    ProviderConfig,
    SettingsError,
    WebSettings,
    load_settings,
    read_provider_secret,
    read_secret,
)


def write_secret(path: Path, value: str, mode: int = 0o600) -> Path:
    path.write_text(value)
    path.chmod(mode)
    return path


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_database_is_required_and_ai_is_optional(self):
        with self.assertRaises(SettingsError):
            load_settings({})
        settings = load_settings({"HR_DATABASE": str(self.root / "app.sqlite3")})
        self.assertFalse(settings.ai_enabled)
        self.assertIsNone(settings.provider)
        self.assertIsNone(settings.exa)
        self.assertEqual(settings.describe()["provider"], None)

    def test_campaign_profile_rejects_ai_exa_and_requires_lan_tls_origin(self):
        base = {
            "HR_DATABASE": str(self.root / "app.sqlite3"),
            "HR_CAMPAIGN_PROFILE": "1",
            "HR_PASSWORD_FILE": str(self.root / "password"),
            "HR_SESSION_KEY_FILE": str(self.root / "session"),
            "HR_TLS_CERT_FILE": str(self.root / "cert"),
            "HR_TLS_KEY_FILE": str(self.root / "key"),
            "HR_PUBLIC_URL": "https://10.10.10.20:8787",
            "HR_LAN_BIND": "10.10.10.20",
            "HR_ALLOWED_HOSTS": "10.10.10.20:8787",
        }
        self.assertTrue(load_settings(base).campaign_profile)
        for change in (
            {
                "AI_PROVIDER": "groq",
                "AI_MODEL_ID": "m",
                "AI_CREDENTIAL_FILE": str(self.root / "secret"),
            },
            {"EXA_MCP_URL": "https://example.test", "EXA_KEY_FILE": str(self.root / "key")},
            {"HR_PUBLIC_URL": "http://10.10.10.20:8787"},
            {"HR_ALLOWED_HOSTS": "testserver"},
            {"HR_LAN_BIND": "0.0.0.0"},
        ):
            with self.subTest(change=change), self.assertRaises(SettingsError):
                load_settings({**base, **change})

    def test_shared_control_requires_explicit_private_http_campaign_without_secrets(self):
        base = {
            "HR_DATABASE": str(self.root / "app.sqlite3"),
            "HR_CAMPAIGN_PROFILE": "1",
            "HR_LAN_SHARED_CONTROL": "1",
            "HR_LAN_BIND": "10.10.10.20",
            "HR_ALLOWED_HOSTS": "10.10.10.20:8787",
            "HR_PUBLIC_URL": "http://10.10.10.20:8787",
        }
        settings = load_settings(base)
        self.assertTrue(settings.shared_control)
        self.assertIsNotNone(settings.web)
        self.assertIsNone(settings.web.password_file)
        for change in (
            {"HR_CAMPAIGN_PROFILE": "0"},
            {"HR_PUBLIC_URL": "https://10.10.10.20:8787"},
            {"HR_LAN_BIND": "0.0.0.0"},
            {
                "HR_LAN_BIND": "8.8.8.8",
                "HR_ALLOWED_HOSTS": "8.8.8.8:8787",
                "HR_PUBLIC_URL": "http://8.8.8.8:8787",
            },
            {"HR_PASSWORD_FILE": str(self.root / "password")},
            {"HR_TLS_CERT_FILE": str(self.root / "cert")},
            {
                "AI_PROVIDER": "groq",
                "AI_MODEL_ID": "m",
                "AI_CREDENTIAL_FILE": str(self.root / "key"),
            },
        ):
            with self.subTest(change=change), self.assertRaises(SettingsError):
                load_settings({**base, **change})

    def test_there_is_no_default_model(self):
        with self.assertRaises(SettingsError):
            load_settings(
                {
                    "HR_DATABASE": str(self.root / "app.sqlite3"),
                    "AI_PROVIDER": "groq",
                    "AI_CREDENTIAL_FILE": str(self.root / "key"),
                }
            )

    def test_provider_requires_a_credential_file(self):
        with self.assertRaises(SettingsError):
            load_settings(
                {
                    "HR_DATABASE": str(self.root / "app.sqlite3"),
                    "AI_PROVIDER": "groq",
                    "AI_MODEL_ID": "test/model",
                }
            )

    def test_provider_configuration_is_explicit(self):
        settings = load_settings(
            {
                "HR_DATABASE": str(self.root / "app.sqlite3"),
                "AI_PROVIDER": "openrouter",
                "AI_MODEL_ID": "openai/gpt-oss-20b",
                "AI_CREDENTIAL_FILE": str(self.root / "ai.key"),
                "AI_COMPLETION_CAP": "512",
                "AI_CONTEXT_LIMIT": "16384",
                "AI_COMPLETION_LIMIT": "2048",
                "AI_EXTRA_BODY_JSON": '{"provider": {"data_collection": "deny"}}',
            }
        )
        self.assertTrue(settings.ai_enabled)
        self.assertEqual(settings.provider.model_id, "openai/gpt-oss-20b")
        self.assertEqual(settings.provider.completion_cap, 512)
        self.assertEqual(settings.provider.context_limit, 16384)
        self.assertEqual(settings.provider.completion_limit, 2048)
        self.assertEqual(settings.provider.extra_body, {"provider": {"data_collection": "deny"}})
        self.assertFalse(settings.provider.free_only)
        described = settings.describe()
        self.assertNotIn("credential", str(described))
        self.assertNotIn(str(self.root), str(described))

    def test_default_completion_cap_is_1024(self):
        settings = load_settings(
            {
                "HR_DATABASE": str(self.root / "synthetic.sqlite3"),
                "AI_PROVIDER": "9router",
                "AI_MODEL_ID": "ag/gemini-3.8-flash",
                "AI_CREDENTIAL_FILE": str(self.root / "synthetic-key"),
            }
        )
        self.assertEqual(settings.provider.completion_cap, 1024)

    def test_free_only_is_accepted_on_any_provider(self):
        config = ProviderConfig(
            provider="9router",
            model_id="m",
            credential_path=self.root / "k",
            base_url="http://127.0.0.1:20128/v1",
            free_only=True,
        )
        self.assertTrue(config.free_only)

    def test_openrouter_free_only_and_fallbacks(self):
        settings = load_settings(
            {
                "HR_DATABASE": str(self.root / "app.sqlite3"),
                "AI_PROVIDER": "openrouter",
                "AI_MODEL_ID": "free/model",
                "AI_FREE_ONLY": "true",
                "AI_FALLBACK_MODELS": "free/other, free/third",
                "AI_CREDENTIAL_FILE": str(self.root / "openrouter.key"),
            }
        )
        self.assertTrue(settings.provider.free_only)
        self.assertEqual(settings.provider.fallback_models, ("free/other", "free/third"))

    def test_exa_requires_a_key_file_and_rejects_agent_tools(self):
        with self.assertRaises(SettingsError):
            load_settings(
                {
                    "HR_DATABASE": str(self.root / "app.sqlite3"),
                    "EXA_MCP_URL": "https://mcp.exa.ai/mcp",
                }
            )
        with self.assertRaises(SettingsError):
            ExaConfig(
                endpoint="https://mcp.exa.ai/mcp",
                api_key_path=self.root / "exa.key",
                allowed_tools=("web_search_exa", "agent_run"),
            )
        with self.assertRaises(SettingsError):
            ExaConfig(
                endpoint="http://mcp.exa.ai/mcp",
                api_key_path=self.root / "exa.key",
            )

    def test_exa_configuration_defaults_to_bounded_tools(self):
        settings = load_settings(
            {
                "HR_DATABASE": str(self.root / "app.sqlite3"),
                "EXA_MCP_URL": "https://mcp.exa.ai/mcp?tools=web_search_exa",
                "EXA_KEY_FILE": str(self.root / "exa.key"),
            }
        )
        self.assertEqual(settings.exa.allowed_tools, ("web_search_exa", "web_fetch_exa"))
        self.assertTrue(settings.exa.enabled)

    def test_tls_material_is_optional_but_must_be_a_pair(self):
        base = {
            "HR_DATABASE": str(self.root / "app.sqlite3"),
            "HR_PASSWORD_FILE": str(self.root / "password"),
            "HR_SESSION_KEY_FILE": str(self.root / "session-key"),
            "HR_PUBLIC_URL": "https://127.0.0.1:8787",
        }
        with self.assertRaises(SettingsError):
            load_settings({**base, "HR_TLS_CERT_FILE": str(self.root / "cert.pem")})
        settings = load_settings(
            {
                **base,
                "HR_TLS_CERT_FILE": str(self.root / "cert.pem"),
                "HR_TLS_KEY_FILE": str(self.root / "key.pem"),
            }
        )
        self.assertEqual(settings.web.tls_cert_file, self.root / "cert.pem")
        self.assertEqual(settings.web.tls_key_file, self.root / "key.pem")
        self.assertIsNone(
            load_settings(
                {
                    "HR_DATABASE": str(self.root / "app.sqlite3"),
                    "HR_PASSWORD_FILE": str(self.root / "password"),
                    "HR_SESSION_KEY_FILE": str(self.root / "session-key"),
                }
            ).web.tls_cert_file
        )

    def test_tls_needs_an_https_public_url(self):
        with self.assertRaises(SettingsError):
            WebSettings(
                password_file=self.root / "password",
                session_key_file=self.root / "session-key",
                tls_cert_file=self.root / "cert.pem",
                tls_key_file=self.root / "key.pem",
            )


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_owner_only_secret_is_read(self):
        path = write_secret(self.root / "key", "  secret-value\n", 0o600)
        self.assertEqual(read_secret(path), "secret-value")

    def test_explicit_owner_only_dotenv_is_read_without_evaluation(self):
        path = write_secret(
            self.root / ".env.local",
            'GROQ_API_KEY="groq-val"\nOPENROUTER_API_KEY="or-val"\n9ROUTER_API_KEY="nr-val"\n',
            0o600,
        )
        self.assertEqual(read_provider_secret(path, provider="groq"), "groq-val")
        self.assertEqual(read_provider_secret(path, provider="openrouter"), "or-val")
        self.assertEqual(read_provider_secret(path, provider="9router"), "nr-val")
        self.assertEqual(read_provider_secret(path, credential_var="9ROUTER_API_KEY"), "nr-val")
        self.assertNotIn("GROQ_API_KEY=", read_provider_secret(path, provider="groq"))

    def test_dotenv_never_auto_loaded(self):
        write_secret(self.root / ".env.local", 'OPENROUTER_API_KEY="test-value"\n', 0o600)
        self.assertIsNone(load_settings({"HR_DATABASE": str(self.root / "app.sqlite3")}).provider)

    def test_dotenv_rejects_permissions_and_shell_syntax(self):
        path = write_secret(self.root / ".env.local", 'OPENROUTER_API_KEY="test-value"\n', 0o644)
        with self.assertRaises(SettingsError):
            read_provider_secret(path, provider="openrouter")
        path.chmod(0o600)
        for value in (
            "OPENROUTER_API_KEY=$(echo unsafe)",
            'OPENROUTER_API_KEY="unterminated',
            "export OPENROUTER_API_KEY=test",
        ):
            path.write_text(value)
            with self.assertRaises(SettingsError):
                read_provider_secret(path, provider="openrouter")
        # Missing key raises SettingsError
        path.write_text('OTHER_KEY="val"\n')
        with self.assertRaises(SettingsError):
            read_provider_secret(path, provider="openrouter")

    def test_permissive_secret_is_refused(self):
        path = write_secret(self.root / "key", "secret", 0o644)
        with self.assertRaises(SettingsError):
            read_secret(path)
        path.chmod(0o640)
        with self.assertRaises(SettingsError):
            read_secret(path)

    def test_missing_empty_or_multiline_secret_is_refused(self):
        with self.assertRaises(SettingsError):
            read_secret(self.root / "missing")
        empty = write_secret(self.root / "empty", "   \n", 0o600)
        with self.assertRaises(SettingsError):
            read_secret(empty)
        multi = write_secret(self.root / "multi", "one two\n", 0o600)
        with self.assertRaises(SettingsError):
            read_secret(multi)

    def test_secret_never_appears_in_settings_repr(self):
        path = write_secret(self.root / "key", "top-secret", 0o600)
        settings = load_settings(
            {
                "HR_DATABASE": str(self.root / "app.sqlite3"),
                "AI_PROVIDER": "groq",
                "AI_MODEL_ID": "m",
                "AI_CREDENTIAL_FILE": str(path),
            }
        )
        self.assertNotIn("top-secret", repr(settings))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class MistralAndSpendPolicyTests(unittest.TestCase):
    """Mistral readiness and paid-mode currency policy (spec R17)."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key = write_secret(self.root / "mistral.key", "mistral-key")

    def settings(self, **extra):
        base = {
            "HR_DATABASE": str(self.root / "app.sqlite3"),
            "AI_PROVIDER": "mistral",
            "AI_MODEL_ID": "mistral-small-latest",
            "AI_CREDENTIAL_FILE": str(self.key),
        }
        return load_settings({**base, **extra})

    def test_mistral_has_an_explicit_default_endpoint(self):
        self.assertEqual(DEFAULT_BASE_URLS["mistral"], "https://api.mistral.ai/v1")
        settings = self.settings()
        self.assertEqual(settings.provider.base_url, "https://api.mistral.ai/v1")
        self.assertFalse(settings.provider.free_only)

    def test_operator_can_declare_a_structured_output_mode(self):
        settings = self.settings(**{"AI_STRUCTURED_OUTPUT": "json_schema"})
        self.assertEqual(settings.provider.structured_output, "json_schema")
        with self.assertRaises(SettingsError):
            self.settings(**{"AI_STRUCTURED_OUTPUT": "xml"})
        self.assertIsNone(self.settings().provider.structured_output)

    def test_default_spend_mode_is_free_with_no_currency_accounting(self):
        settings = self.settings()
        self.assertFalse(settings.budget.paid_mode)
        self.assertIsNone(settings.budget.provider_price_per_million)

    def test_tariff_variables_require_paid_mode(self):
        with self.assertRaises(SettingsError):
            self.settings(**{"AI_PROVIDER_PRICE_PER_MILLION": "2.0"})

    def test_paid_mode_requires_tariffs_and_ceilings(self):
        complete = {
            "AI_PAID_MODE": "1",
            "AI_PROVIDER_PRICE_PER_MILLION": "2.0",
            "AI_EXA_PRICE_PER_OPERATION": "0.01",
            "AI_CURRENCY_CEILING_RUN": "1.00",
            "AI_CURRENCY_CEILING_DAY": "2.00",
            "AI_EXA_CURRENCY_CEILING_RUN": "0.50",
            "AI_EXA_CURRENCY_CEILING_DAY": "1.00",
        }
        settings = self.settings(**complete)
        budget = settings.budget
        self.assertTrue(budget.paid_mode)
        self.assertEqual(budget.provider_price_per_million, 2.0)
        self.assertEqual(budget.exa_price_per_operation, 0.01)
        self.assertEqual(budget.per_analysis_currency, 1.0)
        self.assertEqual(budget.per_day_currency, 2.0)
        self.assertEqual(budget.per_analysis_exa_currency, 0.5)
        self.assertEqual(budget.per_day_exa_currency, 1.0)
        # Any missing tariff/ceiling fails closed.
        for key in complete:
            if key == "AI_PAID_MODE":
                continue
            with self.subTest(key=key):
                broken = {k: v for k, v in complete.items() if k != key}
                with self.assertRaises(SettingsError):
                    self.settings(**broken)

    def test_paid_mode_refuses_free_only_and_non_positive_values(self):
        paid = {
            "AI_PAID_MODE": "1",
            "AI_PROVIDER_PRICE_PER_MILLION": "2.0",
            "AI_EXA_PRICE_PER_OPERATION": "0.01",
            "AI_CURRENCY_CEILING_RUN": "1.00",
            "AI_CURRENCY_CEILING_DAY": "2.00",
            "AI_EXA_CURRENCY_CEILING_RUN": "0.50",
            "AI_EXA_CURRENCY_CEILING_DAY": "1.00",
        }
        with self.assertRaises(SettingsError):
            self.settings(**paid, **{"AI_FREE_ONLY": "1"})
        with self.assertRaises(SettingsError):
            self.settings(**{**paid, "AI_CURRENCY_CEILING_RUN": "0"})
        with self.assertRaises(SettingsError):
            self.settings(**{**paid, "AI_EXA_PRICE_PER_OPERATION": "-0.01"})
        with self.assertRaises(SettingsError):
            self.settings(**{**paid, "AI_PROVIDER_PRICE_PER_MILLION": "not-a-number"})

    def test_paid_mode_without_a_provider_is_refused(self):
        with self.assertRaises(SettingsError):
            load_settings(
                {
                    "HR_DATABASE": str(self.root / "app.sqlite3"),
                    "AI_PAID_MODE": "1",
                    "AI_PROVIDER_PRICE_PER_MILLION": "2.0",
                    "AI_EXA_PRICE_PER_OPERATION": "0.01",
                    "AI_CURRENCY_CEILING_RUN": "1.00",
                    "AI_CURRENCY_CEILING_DAY": "2.00",
                    "AI_EXA_CURRENCY_CEILING_RUN": "0.50",
                    "AI_EXA_CURRENCY_CEILING_DAY": "1.00",
                }
            )

    def test_fingerprint_binds_the_spend_policy(self):
        free = self.settings()
        paid = self.settings(
            **{
                "AI_PAID_MODE": "1",
                "AI_PROVIDER_PRICE_PER_MILLION": "2.0",
                "AI_EXA_PRICE_PER_OPERATION": "0.01",
                "AI_CURRENCY_CEILING_RUN": "1.00",
                "AI_CURRENCY_CEILING_DAY": "2.00",
                "AI_EXA_CURRENCY_CEILING_RUN": "0.50",
                "AI_EXA_CURRENCY_CEILING_DAY": "1.00",
            }
        )
        self.assertIsNotNone(free.config_fingerprint())
        self.assertNotEqual(free.config_fingerprint(), paid.config_fingerprint())
        # Changing one ceiling changes the fingerprint again.
        paid2 = self.settings(
            **{
                "AI_PAID_MODE": "1",
                "AI_PROVIDER_PRICE_PER_MILLION": "2.0",
                "AI_EXA_PRICE_PER_OPERATION": "0.01",
                "AI_CURRENCY_CEILING_RUN": "3.00",
                "AI_CURRENCY_CEILING_DAY": "2.00",
                "AI_EXA_CURRENCY_CEILING_RUN": "0.50",
                "AI_EXA_CURRENCY_CEILING_DAY": "1.00",
            }
        )
        self.assertNotEqual(paid.config_fingerprint(), paid2.config_fingerprint())

    def test_disclosure_reports_tariffs_and_ceilings(self):
        settings = self.settings(
            **{
                "AI_PAID_MODE": "1",
                "AI_PROVIDER_PRICE_PER_MILLION": "2.0",
                "AI_EXA_PRICE_PER_OPERATION": "0.01",
                "AI_CURRENCY_CEILING_RUN": "1.00",
                "AI_CURRENCY_CEILING_DAY": "2.00",
                "AI_EXA_CURRENCY_CEILING_RUN": "0.50",
                "AI_EXA_CURRENCY_CEILING_DAY": "1.00",
            }
        )
        disclosure = settings.spend_disclosure()
        self.assertTrue(disclosure["paid_mode"])
        self.assertEqual(disclosure["currency_ceiling_day"], 2.0)
        self.assertFalse(self.settings().spend_disclosure()["paid_mode"])


if __name__ == "__main__":
    unittest.main()
