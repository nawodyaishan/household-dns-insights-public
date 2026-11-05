"""Operator settings and server-side secret references.

Configuration is local and explicit. There is no default model identifier, no
credential in an HTTP request and no remote capability discovery while loading
settings: constructing these objects is pure and offline.

Secrets are read from owner-only files at the moment of use, never stored on the
settings object, never serialized and never logged.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .analysis import DEFAULT_BUDGET
from .contracts import AttemptBudget
from .credentials import CredentialError, read_credential
from .operator_config import OperatorConfigError, load_operator_config

PROVIDERS = frozenset(
    {"openrouter", "9router", "groq", "openai", "ollama", "cerebras", "mistral", "llm"}
)
DEFAULT_ALLOWED_TOOLS = ("web_search_exa", "web_fetch_exa")
DEFAULT_BASE_URLS: Mapping[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "9router": "http://127.0.0.1:20128/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "mistral": "https://api.mistral.ai/v1",
}
PAID_CEILING_VARS = (
    "AI_CURRENCY_CEILING_RUN",
    "AI_CURRENCY_CEILING_DAY",
    "AI_EXA_CURRENCY_CEILING_RUN",
    "AI_EXA_CURRENCY_CEILING_DAY",
)
PAID_TARIFF_VARS = ("AI_PROVIDER_PRICE_PER_MILLION", "AI_EXA_PRICE_PER_OPERATION")


class SettingsError(ValueError):
    """The local configuration is incomplete, unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """One provider per job, with an explicitly chosen model."""

    provider: str
    model_id: str
    credential_path: Path
    base_url: str
    credential_var: str | None = None
    free_only: bool = False
    completion_cap: int = 1024
    context_limit: int | None = None
    completion_limit: int | None = None
    extra_body: Mapping[str, object] = field(default_factory=dict)
    fallback_models: tuple[str, ...] = ()
    structured_output: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.provider):
            raise SettingsError(f"Invalid AI_PROVIDER label: {self.provider!r}")
        if not self.model_id:
            raise SettingsError("AI_MODEL_ID is required when a provider is configured")
        if not self.base_url.startswith(("http://", "https://")):
            raise SettingsError("AI_BASE_URL must be an http or https URL")
        if not 1 <= self.completion_cap <= 8192:
            raise SettingsError("Completion cap must be between 1 and 8192 tokens")
        if self.context_limit is not None and self.context_limit <= 0:
            raise SettingsError("AI_CONTEXT_LIMIT must be positive")
        if self.completion_limit is not None and self.completion_limit <= 0:
            raise SettingsError("AI_COMPLETION_LIMIT must be positive")
        if self.structured_output is not None and self.structured_output not in {
            "json_schema",
            "json_object",
        }:
            raise SettingsError(
                "AI_STRUCTURED_OUTPUT must be json_schema or json_object when declared"
            )


@dataclass(frozen=True, slots=True)
class ExaConfig:
    endpoint: str
    api_key_path: Path
    allowed_tools: tuple[str, ...] = DEFAULT_ALLOWED_TOOLS
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise SettingsError("The MCP endpoint must be HTTPS")
        forbidden = {"agent_run", "web_search_advanced_exa"}
        if forbidden & set(self.allowed_tools):
            raise SettingsError("Only bounded search/fetch tools may be allowlisted")
        if not self.allowed_tools:
            raise SettingsError("At least one bounded evidence tool must be allowed")


@dataclass(frozen=True, slots=True)
class WebSettings:
    """Local owner access; the web app refuses to start without it."""

    password_file: Path | None
    session_key_file: Path | None
    allowed_hosts: tuple[str, ...] = ("127.0.0.1:8787", "localhost:8787")
    public_url: str = "http://127.0.0.1:8787"
    max_body_bytes: int = 65_536
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = None

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise SettingsError("At least one allowed host is required")
        if self.max_body_bytes < 1024:
            raise SettingsError("Body cap must be at least 1024 bytes")
        if not self.public_url.startswith(("http://", "https://")):
            raise SettingsError("Public URL must be an absolute http(s) URL")
        if (self.tls_cert_file is None) != (self.tls_key_file is None):
            raise SettingsError("TLS certificate and key must be configured together")
        if self.tls_cert_file is not None and not self.public_url.startswith("https://"):
            raise SettingsError("A TLS listener needs an https public URL")


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    input_dir: Path
    timezone: str = "UTC"
    provider: ProviderConfig | None = None
    exa: ExaConfig | None = None
    budget: AttemptBudget = field(default=DEFAULT_BUDGET)
    web: WebSettings | None = None
    campaign_profile: bool = False
    campaign_bind: str | None = None
    shared_control: bool = False
    bridge_status_file: Path | None = None

    def __post_init__(self) -> None:
        if self.shared_control and not self.campaign_profile:
            raise SettingsError("Shared control requires the opt-in campaign profile")
        if not self.campaign_profile:
            return
        if self.provider is not None or self.exa is not None:
            raise SettingsError("Campaign profile refuses AI and external evidence configuration")
        web = self.web
        if web is None:
            raise SettingsError("Campaign profile needs web configuration")
        if self.shared_control:
            if any((web.password_file, web.session_key_file, web.tls_cert_file, web.tls_key_file)):
                raise SettingsError("Shared control refuses credentials and TLS material")
        elif any(
            value is None
            for value in (
                web.password_file,
                web.session_key_file,
                web.tls_cert_file,
                web.tls_key_file,
            )
        ):
            raise SettingsError("Campaign profile needs explicit owner credentials and TLS")
        url = urlsplit(web.public_url)
        if (
            url.scheme != ("http" if self.shared_control else "https")
            or not url.hostname
            or url.username
            or url.password
            or url.hostname in {"localhost", "127.0.0.1"}
        ):
            raise SettingsError("Campaign profile needs an explicit LAN HTTPS origin")
        try:
            bind = ipaddress.ip_address(self.campaign_bind or "")
        except ValueError as error:
            raise SettingsError("Campaign profile needs an explicit VM LAN bind IP") from error
        if bind.is_unspecified or bind.is_loopback or bind.is_multicast or bind.is_link_local:
            raise SettingsError("Campaign profile refuses wildcard and non-LAN binds")
        if self.shared_control and not bind.is_private:
            raise SettingsError("Shared control requires a private VM bind")
        if (
            url.path not in {"", "/"}
            or url.query
            or url.fragment
            or web.allowed_hosts != (url.netloc,)
        ):
            raise SettingsError("Campaign profile hosts must equal its one LAN origin")

    @property
    def ai_enabled(self) -> bool:
        return self.provider is not None

    def describe(self) -> dict[str, object]:
        """Safe summary for logs/status: no paths to secrets, no credential bytes."""
        return {
            "ai_enabled": self.ai_enabled,
            "provider": self.provider.provider if self.provider else None,
            "model": self.provider.model_id if self.provider else None,
            "free_only": self.provider.free_only if self.provider else None,
            "exa_enabled": bool(self.exa and self.exa.enabled),
            "timezone": self.timezone,
        }

    def config_fingerprint(self) -> str | None:
        """Stable, non-secret description of the AI/MCP configuration for job identity."""
        if self.provider is None:
            return None
        payload = {
            "provider": self.provider.provider,
            "model": self.provider.model_id,
            "base_url": self.provider.base_url,
            "free_only": self.provider.free_only,
            "completion_cap": self.provider.completion_cap,
            "context_limit": self.provider.context_limit,
            "completion_limit": self.provider.completion_limit,
            "extra_body": dict(self.provider.extra_body),
            "fallbacks": list(self.provider.fallback_models),
            "structured_output": self.provider.structured_output,
            "paid_mode": self.budget.paid_mode,
            "provider_price_per_million": self.budget.provider_price_per_million,
            "exa_price_per_operation": self.budget.exa_price_per_operation,
            "currency_ceiling_run": self.budget.per_analysis_currency,
            "currency_ceiling_day": self.budget.per_day_currency,
            "exa_currency_ceiling_run": self.budget.per_analysis_exa_currency,
            "exa_currency_ceiling_day": self.budget.per_day_exa_currency,
            "exa_enabled": bool(self.exa and self.exa.enabled),
            "exa_tools": list(self.exa.allowed_tools) if self.exa else [],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:32]

    def spend_disclosure(self) -> dict[str, object]:
        """Per-run spend policy so every page shows the owner's tariffs and ceilings."""
        budget = self.budget
        return {
            "paid_mode": bool(budget.paid_mode),
            "provider_price_per_million": budget.provider_price_per_million,
            "exa_price_per_operation": budget.exa_price_per_operation,
            "currency_ceiling_run": budget.per_analysis_currency,
            "currency_ceiling_day": budget.per_day_currency,
            "exa_currency_ceiling_run": budget.per_analysis_exa_currency,
            "exa_currency_ceiling_day": budget.per_day_exa_currency,
        }


def read_secret(path: Path) -> str:
    """Read an owner-only secret file; refuse permissive or foreign files."""
    try:
        info = path.stat()
    except FileNotFoundError as error:
        raise SettingsError(f"Secret file is missing: {path}") from error
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise SettingsError(f"Secret file must not be group/world accessible: {path}")
    if info.st_uid != os.getuid():
        raise SettingsError(f"Secret file must be owned by the running user: {path}")
    value = path.read_text().strip()
    if not value or any(char.isspace() for char in value):
        raise SettingsError(f"Secret file is empty or malformed: {path}")
    return value


def read_provider_secret(
    path: Path,
    *,
    provider: str = "openai",
    credential_var: str | None = None,
) -> str:
    """Read an explicitly selected provider file; never source a dotenv as shell code."""
    try:
        info = path.stat()
    except FileNotFoundError as error:
        raise SettingsError(f"Secret file is missing: {path}") from error
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise SettingsError(f"Secret file must not be group/world accessible: {path}")
    if info.st_uid != os.getuid():
        raise SettingsError(f"Secret file must be owned by the running user: {path}")

    if path.name != ".env.local":
        return read_secret(path)

    # For .env.local: parse key-value lines with strict assignment, no shell syntax.
    content = path.read_text()
    assignments: dict[str, str] = {}
    for line_idx, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(
            r'([A-Za-z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([A-Za-z0-9_\-.:/]+))',
            line,
        )
        if match is None:
            raise SettingsError(
                f".env.local line {line_idx} contains unsupported syntax or shell expressions"
            )
        var_name, double_quoted, single_quoted, bare = match.groups()
        val = (
            double_quoted
            if double_quoted is not None
            else (single_quoted if single_quoted is not None else bare)
        )
        assignments[var_name] = val

    candidates: list[str] = []
    if credential_var:
        candidates.append(credential_var)
    else:
        candidates.extend(
            [
                f"{provider.upper()}_API_KEY",
                "AI_API_KEY",
                "LLM_API_KEY",
                "OPENAI_API_KEY",
            ]
        )

    for cand in candidates:
        if cand in assignments:
            val = assignments[cand].strip()
            if not val:
                raise SettingsError(f"Secret variable {cand} in {path.name} is empty")
            return val
    raise SettingsError(
        f"No key for provider {provider!r} found in {path.name} (checked {candidates})"
    )


def _bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _provider(environ: Mapping[str, str]) -> ProviderConfig | None:
    name = (environ.get("AI_PROVIDER") or "").strip().lower()
    model = (environ.get("AI_MODEL_ID") or environ.get("LLM_MODEL") or "").strip()
    credential = (
        environ.get("AI_CREDENTIAL_FILE") or environ.get("LLM_CREDENTIAL_FILE") or ""
    ).strip()
    base_url_raw = (environ.get("AI_BASE_URL") or environ.get("LLM_BASE_URL") or "").strip()

    if not name and not base_url_raw and not model and not credential:
        return None

    if not name:
        name = "llm"

    if not model:
        raise SettingsError("AI_MODEL_ID is required; there is no default model")
    if not credential:
        raise SettingsError("AI_CREDENTIAL_FILE is required; keys are never read from requests")

    if not base_url_raw:
        default_base = DEFAULT_BASE_URLS.get(name)
        if not default_base:
            raise SettingsError(f"AI_BASE_URL is required when AI_PROVIDER is {name!r}")
        base_url_raw = default_base

    base_url = base_url_raw.rstrip("/")

    context_limit = None
    if environ.get("AI_CONTEXT_LIMIT", "").strip():
        try:
            context_limit = int(environ["AI_CONTEXT_LIMIT"])
        except ValueError as error:
            raise SettingsError("AI_CONTEXT_LIMIT must be an integer") from error

    completion_limit = None
    if environ.get("AI_COMPLETION_LIMIT", "").strip():
        try:
            completion_limit = int(environ["AI_COMPLETION_LIMIT"])
        except ValueError as error:
            raise SettingsError("AI_COMPLETION_LIMIT must be an integer") from error

    extra_body: Mapping[str, object] = {}
    extra_json = environ.get("AI_EXTRA_BODY_JSON", "").strip()
    if extra_json:
        try:
            parsed = json.loads(extra_json)
        except ValueError as error:
            raise SettingsError("AI_EXTRA_BODY_JSON must be valid JSON") from error
        if not isinstance(parsed, Mapping):
            raise SettingsError("AI_EXTRA_BODY_JSON must be a JSON object")
        extra_body = parsed

    fallbacks = tuple(
        item.strip() for item in environ.get("AI_FALLBACK_MODELS", "").split(",") if item.strip()
    )

    cap_str = environ.get("AI_COMPLETION_CAP", "").strip()
    completion_cap = int(cap_str) if cap_str else 1024

    structured_raw = environ.get("AI_STRUCTURED_OUTPUT", "").strip().lower()
    structured_output = structured_raw or None

    return ProviderConfig(
        provider=name,
        model_id=model,
        credential_path=Path(credential).expanduser(),
        base_url=base_url,
        credential_var=environ.get("AI_CREDENTIAL_VAR", "").strip() or None,
        free_only=_bool(environ.get("AI_FREE_ONLY")),
        completion_cap=completion_cap,
        context_limit=context_limit,
        completion_limit=completion_limit,
        extra_body=extra_body,
        fallback_models=fallbacks,
        structured_output=structured_output,
    )


def _exa(environ: Mapping[str, str]) -> ExaConfig | None:
    endpoint = environ.get("EXA_MCP_URL", "").strip()
    if not endpoint:
        return None
    key_file = environ.get("EXA_KEY_FILE", "").strip()
    if not key_file:
        raise SettingsError("EXA_KEY_FILE is required when EXA_MCP_URL is configured")
    tools = tuple(
        item.strip()
        for item in environ.get("EXA_ALLOWED_TOOLS", ",".join(DEFAULT_ALLOWED_TOOLS)).split(",")
        if item.strip()
    )
    return ExaConfig(
        endpoint=endpoint,
        api_key_path=Path(key_file).expanduser(),
        allowed_tools=tools,
        enabled=_bool(environ.get("EXA_ENABLED"), default=True),
    )


def _web(environ: Mapping[str, str]) -> WebSettings | None:
    password = environ.get("HR_PASSWORD_FILE", "").strip()
    session = environ.get("HR_SESSION_KEY_FILE", "").strip()
    shared = _bool(environ.get("HR_LAN_SHARED_CONTROL"))
    if not password and not session and not shared:
        return None
    if (not password or not session) and not shared:
        raise SettingsError("HR_PASSWORD_FILE and HR_SESSION_KEY_FILE are both required")
    hosts = tuple(
        item.strip()
        for item in environ.get("HR_ALLOWED_HOSTS", "127.0.0.1:8787,localhost:8787").split(",")
        if item.strip()
    )
    cert = environ.get("HR_TLS_CERT_FILE", "").strip()
    key = environ.get("HR_TLS_KEY_FILE", "").strip()
    return WebSettings(
        password_file=Path(password).expanduser() if password else None,
        session_key_file=Path(session).expanduser() if session else None,
        allowed_hosts=hosts,
        public_url=environ.get("HR_PUBLIC_URL", "http://127.0.0.1:8787").strip(),
        max_body_bytes=int(environ.get("HR_MAX_BODY_BYTES", "65536")),
        tls_cert_file=Path(cert).expanduser() if cert else None,
        tls_key_file=Path(key).expanduser() if key else None,
    )


def _positive_float(env: Mapping[str, str], key: str) -> float | None:
    raw = env.get(key, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise SettingsError(f"{key} must be a number") from error
    if value <= 0:
        raise SettingsError(f"{key} must be positive")
    return value


def _budget(env: Mapping[str, str]) -> AttemptBudget:
    """Build the dispatch budget: category caps always, spend policy only in paid mode.

    Paid mode requires every tariff and every owner-set currency ceiling up
    front (spec R17): a configuration without a complete, positive tariff is
    refused here so no paid dispatch can ever see an unknown price. Free-only
    and paid mode are mutually exclusive.
    """
    paid = _bool(env.get("AI_PAID_MODE"))
    tariff = {key: _positive_float(env, key) for key in PAID_TARIFF_VARS}
    ceilings = {key: _positive_float(env, key) for key in PAID_CEILING_VARS}
    if not paid:
        declared = [key for key, value in (*tariff.items(), *ceilings.items()) if value is not None]
        if declared:
            raise SettingsError(
                "Spend policy variables require AI_PAID_MODE=1; set them together: "
                f"{sorted(declared)}"
            )
        return DEFAULT_BUDGET
    if _bool(env.get("AI_FREE_ONLY")) is True:
        raise SettingsError("AI_FREE_ONLY contradicts AI_PAID_MODE; choose one spend policy")
    provider_config = _provider(env)
    if provider_config is None:
        raise SettingsError("AI_PAID_MODE requires a configured AI provider")
    if provider_config.free_only:
        raise SettingsError("AI_FREE_ONLY contradicts AI_PAID_MODE; choose one spend policy")
    missing = [key for key, value in (*tariff.items(), *ceilings.items()) if value is None]
    if missing:
        raise SettingsError(
            f"Paid mode needs every tariff and currency ceiling set explicitly: {sorted(missing)}"
        )
    return AttemptBudget(
        per_analysis_requests=DEFAULT_BUDGET.per_analysis_requests,
        per_day_requests=DEFAULT_BUDGET.per_day_requests,
        per_analysis_tokens=DEFAULT_BUDGET.per_analysis_tokens,
        per_day_tokens=DEFAULT_BUDGET.per_day_tokens,
        per_analysis_exa=DEFAULT_BUDGET.per_analysis_exa,
        per_day_exa=DEFAULT_BUDGET.per_day_exa,
        paid_mode=True,
        provider_price_per_million=tariff["AI_PROVIDER_PRICE_PER_MILLION"],
        exa_price_per_operation=tariff["AI_EXA_PRICE_PER_OPERATION"],
        per_analysis_currency=ceilings["AI_CURRENCY_CEILING_RUN"],
        per_day_currency=ceilings["AI_CURRENCY_CEILING_DAY"],
        per_analysis_exa_currency=ceilings["AI_EXA_CURRENCY_CEILING_RUN"],
        per_day_exa_currency=ceilings["AI_EXA_CURRENCY_CEILING_DAY"],
    )


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load local settings from environment variables (legacy path)."""
    env = os.environ if environ is None else environ
    database = env.get("HR_DATABASE", "").strip()
    if not database:
        raise SettingsError("HR_DATABASE is required")
    return Settings(
        database_path=Path(database).expanduser(),
        input_dir=Path(env.get("HR_INPUT_DIR", "").strip() or ".").expanduser(),
        timezone=env.get("HR_TIMEZONE", "UTC"),
        provider=_provider(env),
        exa=_exa(env),
        budget=_budget(env),
        web=_web(env),
        campaign_profile=_bool(env.get("HR_CAMPAIGN_PROFILE")),
        campaign_bind=env.get("HR_LAN_BIND", "").strip() or None,
        shared_control=_bool(env.get("HR_LAN_SHARED_CONTROL")),
        bridge_status_file=(
            Path(env.get("HR_BRIDGE_STATUS_FILE", "").strip()).expanduser()
            if env.get("HR_BRIDGE_STATUS_FILE", "").strip()
            else None
        ),
    )


def load_settings_from_operator_config(config_path: Path) -> Settings:
    """Load settings from operator configuration file.

    This is the primary configuration path for 006+. It reads the versioned
    operator JSON, resolves credential references, and builds the Settings object.
    """
    try:
        op_config = load_operator_config(config_path)
    except OperatorConfigError as e:
        raise SettingsError(f"Operator config error: {e}") from e

    # Build environment from operator config
    env: dict[str, str] = {
        "HR_DATABASE": str(Path(op_config.paths.state_dir) / "app.sqlite3"),
        "HR_INPUT_DIR": op_config.paths.input_dir,
        "HR_TIMEZONE": op_config.network.timezone,
        "HR_CAMPAIGN_PROFILE": "1" if op_config.campaign_profile else "0",
        "HR_LAN_BIND": op_config.network.vm_bind,
        "HR_LAN_SHARED_CONTROL": "1" if op_config.shared_control else "0",
        "HR_BRIDGE_STATUS_FILE": str(Path(op_config.paths.state_dir) / "bridge-status.json"),
    }

    # Network settings
    if op_config.shared_control:
        # Shared HTTP profile
        relay_host = op_config.network.relay_ip or op_config.network.vm_bind
        env["HR_PUBLIC_URL"] = f"http://{relay_host}:{op_config.network.vm_port}"
        env["HR_ALLOWED_HOSTS"] = f"{relay_host}:{op_config.network.vm_port}"
    elif op_config.ai_enabled:
        # Owner HTTPS profile
        env["HR_PUBLIC_URL"] = (
            f"https://{op_config.network.relay_ip or op_config.network.vm_bind}:{op_config.network.owner_port}"
        )
        env["HR_ALLOWED_HOSTS"] = (
            f"{op_config.network.relay_ip or op_config.network.vm_bind}:{op_config.network.owner_port}"
        )
        env["HR_TLS_CERT_FILE"] = str(Path(op_config.paths.config_dir) / "tls" / "cert.pem")
        env["HR_TLS_KEY_FILE"] = str(Path(op_config.paths.config_dir) / "tls" / "key.pem")
        env["HR_PASSWORD_FILE"] = str(Path(op_config.paths.config_dir) / "password")
        env["HR_SESSION_KEY_FILE"] = str(Path(op_config.paths.config_dir) / "session-key")
    else:
        # Loopback default
        env["HR_PUBLIC_URL"] = f"https://127.0.0.1:{op_config.network.vm_port}"
        env["HR_ALLOWED_HOSTS"] = (
            f"127.0.0.1:{op_config.network.vm_port},localhost:{op_config.network.vm_port}"
        )
        env["HR_TLS_CERT_FILE"] = str(Path(op_config.paths.config_dir) / "tls" / "cert.pem")
        env["HR_TLS_KEY_FILE"] = str(Path(op_config.paths.config_dir) / "tls" / "key.pem")
        env["HR_PASSWORD_FILE"] = str(Path(op_config.paths.config_dir) / "password")
        env["HR_SESSION_KEY_FILE"] = str(Path(op_config.paths.config_dir) / "session-key")

    # Provider configuration
    if op_config.provider:
        try:
            read_credential(
                Path(op_config.provider.credential.file),
                op_config.provider.credential.format,
                op_config.provider.credential.variable,
            )
        except CredentialError as e:
            raise SettingsError(f"Provider credential error: {e}") from e

        env["AI_PROVIDER"] = op_config.provider.provider
        env["AI_MODEL_ID"] = op_config.provider.model
        env["AI_BASE_URL"] = op_config.provider.base_url
        env["AI_CREDENTIAL_FILE"] = op_config.provider.credential.file
        env["AI_CREDENTIAL_VAR"] = op_config.provider.credential.variable
        env["AI_FREE_ONLY"] = "1" if op_config.provider.free_only else "0"
        env["AI_COMPLETION_CAP"] = str(op_config.provider.completion_cap)
        if op_config.provider.context_limit:
            env["AI_CONTEXT_LIMIT"] = str(op_config.provider.context_limit)
        if op_config.provider.completion_limit:
            env["AI_COMPLETION_LIMIT"] = str(op_config.provider.completion_limit)
        if op_config.provider.extra_body:
            env["AI_EXTRA_BODY_JSON"] = json.dumps(
                op_config.provider.extra_body, separators=(",", ":")
            )
        if op_config.provider.fallback_models:
            env["AI_FALLBACK_MODELS"] = ",".join(op_config.provider.fallback_models)

    # Exa configuration
    if op_config.exa:
        try:
            read_credential(
                Path(op_config.exa.credential.file),
                op_config.exa.credential.format,
                op_config.exa.credential.variable,
            )
        except CredentialError as e:
            raise SettingsError(f"Exa credential error: {e}") from e

        env["EXA_MCP_URL"] = op_config.exa.endpoint
        env["EXA_KEY_FILE"] = op_config.exa.credential.file
        env["EXA_ALLOWED_TOOLS"] = ",".join(op_config.exa.allowed_tools)
        env["EXA_ENABLED"] = "1" if op_config.exa.enabled else "0"

    # Delegate to existing loader
    return load_settings(env)


__all__ = [
    "DEFAULT_ALLOWED_TOOLS",
    "ExaConfig",
    "PROVIDERS",
    "ProviderConfig",
    "Settings",
    "SettingsError",
    "WebSettings",
    "load_settings",
    "load_settings_from_operator_config",
    "read_secret",
    "read_provider_secret",
]
