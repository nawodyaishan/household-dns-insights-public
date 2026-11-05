"""Composition-root wiring: settings, store, web app and the disabled-AI gate.

No server is started and no adapter is constructed; the provider/evidence clients are
proven absent by asking the application what it would do when they are unconfigured.
"""

from __future__ import annotations

import base64
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from household_report.app import Application, resolve_bind
from household_report.settings import ProviderConfig, Settings, SettingsError, WebSettings
from household_report.web import hash_password

PASSWORD = "correct horse battery staple"


class ApplicationWiringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        secret_dir = self.root / "config"
        secret_dir.mkdir(mode=0o700)
        self.password_file = secret_dir / "password"
        self.password_file.write_text(hash_password(PASSWORD) + "\n")
        self.session_file = secret_dir / "session-key"
        self.session_file.write_text(
            base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=") + "\n"
        )
        for path in (self.password_file, self.session_file):
            os.chmod(path, 0o600)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.web = WebSettings(
            password_file=self.password_file,
            session_key_file=self.session_file,
            allowed_hosts=("testserver",),
            public_url="http://testserver",
        )
        self.settings = Settings(
            database_path=self.root / "app.sqlite3",
            input_dir=self.root,
            web=self.web,
        )

    def test_web_app_refuses_to_start_without_owner_auth(self):
        application = Application.open(
            Settings(database_path=self.root / "app.sqlite3", input_dir=self.root)
        )
        self.addCleanup(application.close)
        with self.assertRaises(SettingsError):
            application.web_app()

    def test_web_app_serves_public_pages_and_hides_data_behind_login(self):
        with Application.open(self.settings) as application:
            client = TestClient(application.web_app())
            self.assertEqual(client.get("/healthz").json(), {"ok": True})
            self.assertEqual(client.get("/login").status_code, 200)
            self.assertEqual(client.get("/", follow_redirects=False).status_code, 303)
            self.assertEqual(application.ai_descriptor()["enabled"], False)

    def test_shared_campaign_starts_without_secret_files_or_tls(self):
        settings = Settings(
            database_path=self.root / "shared.sqlite3",
            input_dir=self.root,
            web=WebSettings(
                password_file=None,
                session_key_file=None,
                allowed_hosts=("testserver",),
                public_url="http://testserver",
            ),
            campaign_profile=True,
            shared_control=True,
            campaign_bind="10.10.10.20",
        )
        with Application.open(settings) as application:
            client = TestClient(application.web_app())
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/login").status_code, 404)
            self.assertEqual(application._tls_options(), {})

    def test_ai_is_never_started_without_a_provider(self):
        with Application.open(self.settings) as application:
            self.assertIsNone(application.settings.config_fingerprint())
            with self.assertRaises(SettingsError):
                application.submit_analysis("a" * 64, False)
            self.assertEqual(application.analysis.history(), [])

    def test_explicit_dotenv_is_used_only_when_provider_is_requested(self):
        key_file = self.root / ".env.local"
        key_file.write_text('9ROUTER_API_KEY="synthetic-key"\n')
        key_file.chmod(0o600)
        settings = replace(
            self.settings,
            provider=ProviderConfig(
                provider="9router",
                model_id="ag/gemini-3.8-flash",
                credential_path=key_file,
                base_url="http://127.0.0.1:20128/v1",
            ),
        )
        with patch(
            "household_report.integrations.openai_compatible.OpenAICompatibleProvider"
        ) as factory:
            with Application.open(settings) as application:
                descriptor = application.ai_descriptor()
                self.assertEqual(descriptor["enabled"], True)
                self.assertEqual(descriptor["spend"]["paid_mode"], False)
                self.assertIsNone(descriptor["spend"]["currency_ceiling_run"])
                factory.assert_not_called()
                application.provider()
            factory.assert_called_once_with(
                api_key="synthetic-key",
                base_url="http://127.0.0.1:20128/v1",
                label="9router",
                free_only=False,
                context_limit=None,
                completion_limit=None,
                extra_body={},
                structured_output=None,
            )

    def test_session_key_file_must_be_owner_only(self):
        os.chmod(self.session_file, 0o644)
        with Application.open(self.settings) as application:
            with self.assertRaises(SettingsError):
                application.web_app()

    def test_tls_is_absent_unless_configured(self):
        with Application.open(self.settings) as application:
            self.assertEqual(application._tls_options(), {})

    def test_tls_key_must_be_owner_only(self):
        certificate = self.root / "cert.pem"
        key = self.root / "key.pem"
        certificate.write_text("test certificate")
        key.write_text("test key")
        os.chmod(certificate, 0o644)
        os.chmod(key, 0o644)
        web = replace(
            self.web,
            public_url="https://testserver",
            tls_cert_file=certificate,
            tls_key_file=key,
        )
        settings = replace(self.settings, web=web)
        with Application.open(settings) as application:
            with self.assertRaises(SettingsError):
                application._tls_options()
        os.chmod(key, 0o600)
        with Application.open(settings) as application:
            self.assertEqual(
                application._tls_options(),
                {"ssl_certfile": str(certificate), "ssl_keyfile": str(key)},
            )

    def test_tls_certificate_must_exist(self):
        key = self.root / "key.pem"
        key.write_text("test key")
        os.chmod(key, 0o600)
        web = replace(
            self.web,
            public_url="https://testserver",
            tls_cert_file=self.root / "missing.pem",
            tls_key_file=key,
        )
        with Application.open(replace(self.settings, web=web)) as application:
            with self.assertRaises(SettingsError):
                application._tls_options()


class ListenerTests(unittest.TestCase):
    """The listener is loopback unless a container bind is explicitly opted in."""

    def test_default_listener_is_loopback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_bind(), ("127.0.0.1", 8787))

    def test_non_loopback_listeners_need_the_container_opt_in(self):
        with self.assertRaises(SettingsError):
            resolve_bind("0.0.0.0", allow_container=False)
        with self.assertRaises(SettingsError):
            resolve_bind("10.10.10.20", allow_container=True)
        self.assertEqual(resolve_bind("0.0.0.0", allow_container=True), ("0.0.0.0", 8787))
        self.assertEqual(resolve_bind("::1", allow_container=False), ("::1", 8787))

    def test_container_opt_in_comes_from_explicit_environment(self):
        with patch.dict(os.environ, {"HR_ALLOW_CONTAINER_BIND": "1"}, clear=True):
            self.assertEqual(resolve_bind("0.0.0.0"), ("0.0.0.0", 8787))
        with patch.dict(os.environ, {"HR_ALLOW_CONTAINER_BIND": "true"}, clear=True):
            with self.assertRaises(SettingsError):
                resolve_bind("0.0.0.0")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SettingsError):
                resolve_bind("0.0.0.0")

    def test_bind_environment_and_port_validation(self):
        with patch.dict(os.environ, {"HR_BIND_HOST": "127.0.0.1", "HR_PORT": "8799"}, clear=True):
            self.assertEqual(resolve_bind(), ("127.0.0.1", 8799))
        with patch.dict(os.environ, {"HR_PORT": "eighty"}, clear=True):
            with self.assertRaises(SettingsError):
                resolve_bind()
        with self.assertRaises(SettingsError):
            resolve_bind("127.0.0.1", 0)
        with self.assertRaises(SettingsError):
            resolve_bind("127.0.0.1", 70_000)


if __name__ == "__main__":
    unittest.main()
