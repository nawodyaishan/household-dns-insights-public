"""Composition root: one place that wires settings, storage, adapters and the web app.

Importing this module performs no I/O and no network call. The store is opened and
migrated explicitly, provider/evidence adapters are built only when an authorized job
asks for them (reading the owner-only secret at that moment), and the web app receives
read/command objects rather than SQL, secrets or provider clients.

There is no dependency-injection container and no plugin registry: four owned feature
modules, four bounded adapters and one store are wired by name, which is enough for
this application.
"""

from __future__ import annotations

import base64
import binascii
import os
import stat
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .analysis import AnalysisService
from .campaign import CampaignService
from .campaign_reporting import CampaignReportService
from .contracts import EvidenceClient, ModelProvider
from .inventory import InventoryService
from .reporting import ReportService
from .settings import (
    Settings,
    SettingsError,
    load_settings,
    load_settings_from_operator_config,
    read_provider_secret,
    read_secret,
)
from .storage import StorageError, Store, open_store

DEFAULT_BIND = ("127.0.0.1", 8787)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_SAFE_ERRORS = (SettingsError, StorageError, ValueError)


def resolve_bind(
    host: str | None = None,
    port: int | None = None,
    *,
    allow_container: bool | None = None,
) -> tuple[str, int]:
    """Resolve the listener address, keeping non-loopback binds explicit.

    Docker publishes a host port to the container's network interface, so a process
    listening only on the container loopback is unreachable through ``ports:``. The
    packaged Compose service therefore opts in to ``0.0.0.0`` *inside* the container
    with ``HR_ALLOW_CONTAINER_BIND=1`` while the published host address stays
    ``127.0.0.1``. Outside that explicit opt-in every non-loopback address is refused.
    """
    environment = os.environ
    resolved_host = (host if host is not None else environment.get("HR_BIND_HOST", "")).strip()
    resolved_host = resolved_host or DEFAULT_BIND[0]
    raw_port = port if port is not None else environment.get("HR_PORT", "")
    try:
        resolved_port = int(raw_port) if str(raw_port).strip() else DEFAULT_BIND[1]
    except ValueError as error:
        raise SettingsError("HR_PORT must be an integer port number") from error
    if not 1 <= resolved_port <= 65_535:
        raise SettingsError("The listener port must be between 1 and 65535")
    if resolved_host in LOOPBACK_HOSTS:
        return resolved_host, resolved_port
    opt_in = (
        allow_container
        if allow_container is not None
        else environment.get("HR_ALLOW_CONTAINER_BIND", "") == "1"
    )
    if resolved_host == "0.0.0.0" and opt_in:
        return resolved_host, resolved_port
    raise SettingsError(
        "The dashboard binds to loopback only; a container bind needs "
        "HR_ALLOW_CONTAINER_BIND=1 and a loopback-only published port"
    )


def _decode_key(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as error:
        raise SettingsError("Session key file is not valid base64") from error


@dataclass(slots=True)
class Application:
    settings: Settings
    store: Store
    analysis: AnalysisService
    reports: ReportService
    inventory: InventoryService
    campaigns: CampaignService
    campaign_reports: CampaignReportService
    _executor: ThreadPoolExecutor | None = field(default=None, repr=False)
    _futures: set[Future[object]] = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, settings: Settings | None = None) -> Application:
        if settings is None:
            # Check for operator config path
            config_path = os.environ.get("HR_OPERATOR_CONFIG", "").strip()
            if config_path:
                resolved = load_settings_from_operator_config(Path(config_path))
            else:
                resolved = load_settings()
        else:
            resolved = settings
        store = open_store(resolved.database_path)
        inventory = InventoryService(store)
        return cls(
            settings=resolved,
            store=store,
            analysis=AnalysisService(store, budget=resolved.budget),
            reports=ReportService(
                store,
                timezone=resolved.timezone,
                gaming_namespace_path=resolved.input_dir / "gaming-namespaces.json",
                attribution_source=inventory.attributions,
            ),
            inventory=inventory,
            campaigns=CampaignService(
                store,
                timezone=resolved.timezone,
                namespace_path=resolved.input_dir / "gaming-namespaces.json",
            ),
            campaign_reports=CampaignReportService(store),
        )

    def close(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        self.store.close()

    def __enter__(self) -> Application:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- adapters (built lazily, one provider per job) ---------------------
    def provider(self) -> ModelProvider:
        config = self.settings.provider
        if config is None:
            raise SettingsError("No AI provider is configured")
        api_key = read_provider_secret(
            config.credential_path,
            provider=config.provider,
            credential_var=config.credential_var,
        )
        from .integrations.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=config.base_url,
            label=config.provider,
            free_only=config.free_only,
            context_limit=config.context_limit,
            completion_limit=config.completion_limit,
            extra_body=config.extra_body,
            structured_output=config.structured_output,
        )

    def evidence(self) -> EvidenceClient | None:
        config = self.settings.exa
        if config is None or not config.enabled:
            return None
        api_key = read_secret(config.api_key_path)
        from .integrations.exa_mcp import ExaEvidenceClient, sdk_session_factory

        return ExaEvidenceClient(
            session_factory=sdk_session_factory(config.endpoint, api_key),
            allowed_tools=config.allowed_tools,
        )

    # -- web wiring --------------------------------------------------------
    def ai_descriptor(self) -> dict[str, object]:
        config = self.settings.provider
        return {
            "enabled": self.settings.ai_enabled,
            "provider": config.provider if config else None,
            "model": config.model_id if config else None,
            "free_only": config.free_only if config else None,
            "exa_enabled": bool(self.settings.exa and self.settings.exa.enabled),
            "fingerprint": self.settings.config_fingerprint(),
            "spend": self.settings.spend_disclosure(),
        }

    def web_app(self):  # type: ignore[no-untyped-def]
        """Build the FastAPI app with isolated owner or shared-control profile."""
        import secrets

        from .web import OwnerAuth, WebConfig, create_app, hash_password

        config = self.settings.web
        if config is None:
            raise SettingsError(
                "Owner authentication is not configured; set HR_PASSWORD_FILE and "
                "HR_SESSION_KEY_FILE and create them with tools/set_password.py"
            )
        if self.settings.shared_control:
            # Never mount persistent owner secrets in the LAN shared-control profile.
            auth = OwnerAuth(
                password_record=hash_password(secrets.token_urlsafe(32)),
                session_key=secrets.token_bytes(32),
            )
        else:
            if config.password_file is None or config.session_key_file is None:
                raise SettingsError("Owner authentication requires both credential files")
            auth = OwnerAuth(
                password_record=read_secret(config.password_file),
                session_key=_decode_key(read_secret(config.session_key_file)),
            )
        return create_app(
            auth=auth,
            config=WebConfig(
                allowed_hosts=config.allowed_hosts,
                public_url=config.public_url,
                max_body_bytes=config.max_body_bytes,
                shared_control=self.settings.shared_control,
            ),
            reports=self.reports,
            inventory=self.inventory,
            analysis=self.analysis,
            runner=self.submit_analysis,
            ai=self.ai_descriptor(),
            campaigns=self.campaigns,
            campaign_reports=self.campaign_reports,
            collector=self.collector_status,
            timezone=self.settings.timezone,
        )

    def collector_status(self) -> dict[str, object]:
        """Sanitized collector health for the page; reads only the local status file."""
        from datetime import UTC, datetime

        from .collector_status import collector_context, read_status

        path = self.settings.bridge_status_file
        record = read_status(path) if path is not None else None
        current = None
        try:
            current = self.campaigns.status()
        except Exception:  # noqa: BLE001 - no unfinished campaign is normal
            current = None
        if current is None:
            try:
                headers = self.campaigns.list_status()
            except Exception:  # noqa: BLE001 - no campaigns at all
                headers = []
            campaign_state = str(headers[0]["state"]) if headers else None
            coverage = None
        else:
            campaign_state = str(current["state"])
            coverage = current.get("coverage")
        context = collector_context(
            record,
            now_epoch=int(datetime.now(UTC).timestamp()),
            campaign_state=campaign_state,
            campaign_complete=campaign_state in ("complete", "complete_with_gaps"),
            coverage=coverage,
        )
        if current is not None:
            context["report_bounds_utc"] = [
                datetime.fromtimestamp(int(current["utc_bounds"][0]), UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                datetime.fromtimestamp(int(current["utc_bounds"][1]), UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            ]
            context["report_rules_revision"] = current.get("rules_revision")
        else:
            context["report_bounds_utc"] = None
            context["report_rules_revision"] = None
        return context

    # -- the only outbound work entry point --------------------------------
    def submit_analysis(self, analysis_id: str, allow_resume: bool) -> None:
        """Queue one confirmed analysis; never called from a page read."""
        if not self.settings.ai_enabled:
            raise SettingsError("Analysis is disabled until a provider is configured")
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
            executor = self._executor
        future = executor.submit(self._run_analysis, analysis_id, allow_resume)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)

    def _forget(self, future: Future[object]) -> None:
        with self._lock:
            self._futures.discard(future)

    def _run_analysis(self, analysis_id: str, allow_resume: bool) -> None:
        try:
            config = self.settings.provider
            if config is None:
                raise SettingsError("No AI provider is configured")
            evidence = self.evidence()
            if evidence is None:
                raise SettingsError("Exa evidence is not configured; a grounded analysis needs it")
            provider = self.provider()
            capabilities = self.analysis.validate_model(
                analysis_id,
                provider=provider,
                model_id=config.model_id,
                completion_cap=config.completion_cap,
                free_only=config.free_only,
            )
            self.analysis.run(
                analysis_id,
                provider=provider,
                evidence=evidence,
                model_id=config.model_id,
                capabilities=capabilities,
                completion_cap=config.completion_cap,
                allow_resume=allow_resume,
            )
        except Exception as error:  # noqa: BLE001 - record refusal, never crash silently
            self._record_failure(analysis_id, error)

    def _record_failure(self, analysis_id: str, error: BaseException) -> None:
        detail = str(error) if isinstance(error, _SAFE_ERRORS) else type(error).__name__
        message = f"The job stopped before completion: {detail}"
        try:
            self.analysis.finish(analysis_id, state="failed")
            self.store.save_summary(analysis_id, message)
        except Exception:  # noqa: BLE001 - the original failure is what matters
            pass

    # -- local server ------------------------------------------------------
    def _tls_options(self) -> dict[str, str]:
        """Return uvicorn TLS options, refusing missing or group-readable keys."""
        config = self.settings.web
        if config is None or config.tls_cert_file is None:
            return {}
        certificate = config.tls_cert_file
        key = config.tls_key_file
        if key is None:  # guarded by WebSettings, kept explicit for type narrowing
            raise SettingsError("TLS certificate and key must be configured together")
        for label, path in (("certificate", certificate), ("key", key)):
            if not path.is_file():
                raise SettingsError(f"TLS {label} file is missing: {path}")
        if stat.S_IMODE(key.stat().st_mode) & 0o077:
            raise SettingsError("The TLS key must not be group or world readable")
        return {"ssl_certfile": str(certificate), "ssl_keyfile": str(key)}

    def serve(self, *, host: str | None = None, port: int | None = None) -> None:
        """Bind the local server; TLS is used when configured and the key is private."""
        import uvicorn

        address, listener_port = resolve_bind(host, port)
        tls = self._tls_options()
        uvicorn.run(self.web_app(), host=address, port=listener_port, log_level="info", **tls)


def main() -> None:
    with Application.open() as application:
        application.serve()


__all__ = ["Application", "DEFAULT_BIND", "main", "resolve_bind"]


if __name__ == "__main__":
    main()
