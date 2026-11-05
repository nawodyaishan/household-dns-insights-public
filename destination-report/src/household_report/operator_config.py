"""Operator configuration: single versioned JSON document driving all deployment settings.

This replaces ad-hoc environment variables, Make variables, and Compose interpolation
with one explicit, validated, secret-free configuration file. Credentials are referenced
by path/format/variable, never embedded.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


class OperatorConfigError(ValueError):
    """The operator configuration is incomplete, unsafe, or inconsistent."""


# Supported credential formats
CredentialFormat = Literal["bare", "dotenv"]


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    """Network and publication settings."""

    vm_bind: str  # e.g., "10.10.10.20"
    vm_port: int = 8787
    relay_ip: str = ""  # e.g., "192.168.1.10" for Proxmox relay
    relay_port: int = 8787
    owner_port: int = 8789
    timezone: str = "UTC"
    #: Docker Compose project that owns this deployment's containers and network.
    #: Empty means "derive one from the state directory". An existing deployment
    #: must name its real project: a different project cannot reuse the fixed
    #: application bridge names (br-hr005/br-hr006) and would fail to start.
    compose_project: str = ""

    def __post_init__(self) -> None:
        # Validate VM bind
        import ipaddress

        try:
            addr = ipaddress.ip_address(self.vm_bind)
        except ValueError as e:
            raise OperatorConfigError(f"Invalid vm_bind IP: {self.vm_bind}") from e
        if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
            raise OperatorConfigError("vm_bind must not be wildcard, loopback, or multicast")
        if not addr.is_private:
            raise OperatorConfigError("vm_bind must be a private address")

        # Validate relay IP if provided
        if self.relay_ip:
            try:
                relay_addr = ipaddress.ip_address(self.relay_ip)
            except ValueError as e:
                raise OperatorConfigError(f"Invalid relay_ip: {self.relay_ip}") from e
            if relay_addr.is_unspecified or relay_addr.is_loopback or relay_addr.is_multicast:
                raise OperatorConfigError("relay_ip must not be wildcard, loopback, or multicast")

        # Validate ports
        for name, port in [
            ("vm_port", self.vm_port),
            ("relay_port", self.relay_port),
            ("owner_port", self.owner_port),
        ]:
            if not 1 <= port <= 65535:
                raise OperatorConfigError(f"{name} must be between 1 and 65535")

        # Validate the Compose project name against Docker's own rules.
        if self.compose_project and not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,62}", self.compose_project
        ):
            raise OperatorConfigError(
                "compose_project must be a lowercase Docker Compose project name"
            )


@dataclass(frozen=True, slots=True)
class PathsConfig:
    """Private filesystem paths (all under 0700 parent directories)."""

    config_dir: str  # Owner credentials, TLS, campaign config
    input_dir: str  # Read-only snapshots, namespace
    state_dir: str  # Writable SQLite, WAL, artifacts
    bridge_dir: str  # Generated systemd units
    campaign_config_dir: str  # Campaign-specific config (can equal config_dir)

    def __post_init__(self) -> None:
        for name, path in [
            ("config_dir", self.config_dir),
            ("input_dir", self.input_dir),
            ("state_dir", self.state_dir),
            ("bridge_dir", self.bridge_dir),
            ("campaign_config_dir", self.campaign_config_dir),
        ]:
            if not os.path.isabs(path):
                raise OperatorConfigError(f"{name} must be an absolute path")
            if any(c.isspace() for c in path):
                raise OperatorConfigError(f"{name} must not contain whitespace")


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """Host bridge executable and resolver connection (validated at preflight)."""

    python: str  # Absolute path to venv python
    compose: str  # Absolute path to compose.yaml
    docker: str  # Absolute path to docker CLI
    container: str  # Resolver container name/ID
    database: str  # Resolver database path (e.g., /etc/pihole/pihole-FTL.db)
    generation: str  # Source generation ID (e.g., "gen-1")
    identity: str  # Provenance identity string
    config_dir: str  # Must match paths.config_dir
    state_dir: str  # Must match paths.state_dir
    input_dir: str  # Must match paths.input_dir

    def __post_init__(self) -> None:
        for name, path in [
            ("python", self.python),
            ("compose", self.compose),
            ("docker", self.docker),
        ]:
            if not os.path.isabs(path):
                raise OperatorConfigError(f"bridge.{name} must be an absolute path")
            if any(c.isspace() or c == "%" for c in path):
                raise OperatorConfigError(
                    f"bridge.{name} must not contain whitespace or specifiers"
                )

        for name, path in [
            ("config_dir", self.config_dir),
            ("state_dir", self.state_dir),
            ("input_dir", self.input_dir),
        ]:
            if not os.path.isabs(path):
                raise OperatorConfigError(f"bridge.{name} must be an absolute path")

        if not self.database.startswith("/etc/pihole/") or not self.database.endswith(".db"):
            raise OperatorConfigError("bridge.database must be under /etc/pihole/ and end with .db")

        for name in ("generation", "container"):
            val = getattr(self, name)
            if (
                not isinstance(val, str)
                or not val
                or not re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", val)
            ):
                raise OperatorConfigError(f"bridge.{name} must be a valid identifier")

        # The source identity is an OPAQUE provenance string that is only ever
        # compared for equality with the registered record (see
        # storage.register_source_generation and campaign.check_source_identity).
        # It is not an identifier and is never used as a path, filename or lease
        # token, so real values legitimately contain spaces, dots, slashes and
        # semicolons. Requiring identifier-safe characters here made the fresh
        # configuration path unable to express the live identity. It must still
        # be a bounded, printable, single-line string so it cannot corrupt a
        # log line or the durable status file.
        identity = self.identity
        if (
            not isinstance(identity, str)
            or not identity
            or len(identity) > 512
            or identity != identity.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in identity)
        ):
            raise OperatorConfigError(
                "bridge.identity must be a bounded, printable, single-line string"
            )


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """Reference to a secret file; never contains the secret itself."""

    file: str  # Absolute path to credential file
    format: CredentialFormat
    variable: str  # Variable name inside the file

    def __post_init__(self) -> None:
        if not os.path.isabs(self.file):
            raise OperatorConfigError("credential file must be an absolute path")
        if self.format not in ("bare", "dotenv"):
            raise OperatorConfigError(
                f"credential format must be 'bare' or 'dotenv', got {self.format!r}"
            )
        if not self.variable or not re.fullmatch(r"[A-Za-z0-9_]+", self.variable):
            raise OperatorConfigError("credential variable must be a valid identifier")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """AI provider configuration (optional; AI-off when omitted)."""

    provider: str
    model: str
    base_url: str
    credential: CredentialRef
    free_only: bool = False
    completion_cap: int = 1024
    context_limit: int | None = None
    completion_limit: int | None = None
    extra_body: dict[str, object] = field(default_factory=dict)
    fallback_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.provider):
            raise OperatorConfigError(f"Invalid provider label: {self.provider!r}")
        if not self.model:
            raise OperatorConfigError("model is required")
        if not self.base_url.startswith(("http://", "https://")):
            raise OperatorConfigError("base_url must be an http or https URL")
        if not 1 <= self.completion_cap <= 8192:
            raise OperatorConfigError("completion_cap must be between 1 and 8192")
        if self.context_limit is not None and self.context_limit <= 0:
            raise OperatorConfigError("context_limit must be positive")
        if self.completion_limit is not None and self.completion_limit <= 0:
            raise OperatorConfigError("completion_limit must be positive")


@dataclass(frozen=True, slots=True)
class ExaConfig:
    """Exa MCP configuration (optional)."""

    endpoint: str
    credential: CredentialRef
    allowed_tools: tuple[str, ...] = ("web_search_exa", "web_fetch_exa")
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.endpoint.startswith("https://"):
            raise OperatorConfigError("Exa endpoint must be HTTPS")
        forbidden = {"agent_run", "web_search_advanced_exa"}
        if forbidden & set(self.allowed_tools):
            raise OperatorConfigError("Only bounded search/fetch tools may be allowlisted")
        if not self.allowed_tools:
            raise OperatorConfigError("At least one bounded evidence tool must be allowed")


@dataclass(frozen=True, slots=True)
class ReleaseConfig:
    """Immutable release identification."""

    image_id: str  # sha256:... or tag
    source_revision: str  # Git commit SHA
    schema_version: int  # Expected database schema version
    host_bundle_hash: str  # SHA256 of host tool bundle
    base_image_digest: str  # Base image digest


@dataclass(frozen=True, slots=True)
class OperatorConfig:
    """Complete operator configuration (secret-free)."""

    version: int = 1
    network: NetworkConfig = field(default_factory=NetworkConfig)
    paths: PathsConfig = field(
        default_factory=lambda: PathsConfig(
            config_dir="",
            input_dir="",
            state_dir="",
            bridge_dir="",
            campaign_config_dir="",
        )
    )
    #: The host capture bridge. None for an instance that runs no bridge (for
    #: example the owner research dashboard): that deployment must not render,
    #: stop or remove the campaign bridge, which belongs to the shared instance.
    bridge: BridgeConfig | None = None
    provider: ProviderConfig | None = None
    exa: ExaConfig | None = None
    release: ReleaseConfig | None = None
    ai_enabled: bool = False
    campaign_profile: bool = True
    shared_control: bool = True

    def __post_init__(self) -> None:
        if self.version != 1:
            raise OperatorConfigError(f"Unsupported config version: {self.version}")

        # Cross-reference validation
        if self.bridge is not None:
            if self.bridge.config_dir != self.paths.config_dir:
                raise OperatorConfigError("bridge.config_dir must match paths.config_dir")
            if self.bridge.state_dir != self.paths.state_dir:
                raise OperatorConfigError("bridge.state_dir must match paths.state_dir")
            if self.bridge.input_dir != self.paths.input_dir:
                raise OperatorConfigError("bridge.input_dir must match paths.input_dir")

        # AI-off enforcement for campaign profile. ``ai_enabled`` is derived,
        # never trusted: a frozen instance is updated through object.__setattr__
        # (a plain assignment raised FrozenInstanceError and made every load fail).
        if self.campaign_profile:
            if self.provider is not None or self.exa is not None:
                raise OperatorConfigError("Campaign profile refuses AI and Exa configuration")
            derived = False
        else:
            derived = self.provider is not None
        if self.ai_enabled and not derived:
            raise OperatorConfigError(
                "ai_enabled=true contradicts the selected profile/provider; "
                "set it consistently or configure the provider"
            )
        object.__setattr__(self, "ai_enabled", derived)

        # Shared control requires campaign profile
        if self.shared_control and not self.campaign_profile:
            raise OperatorConfigError("Shared control requires campaign_profile=true")


# JSON schema for validation
SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "const": 1},
        "network": {"type": "object", "required": ["vm_bind"]},
        "paths": {
            "type": "object",
            "required": [
                "config_dir",
                "input_dir",
                "state_dir",
                "bridge_dir",
                "campaign_config_dir",
            ],
        },
        "bridge": {
            "type": "object",
            "required": [
                "python",
                "compose",
                "docker",
                "container",
                "database",
                "generation",
                "identity",
                "config_dir",
                "state_dir",
                "input_dir",
            ],
        },
        "provider": {"type": ["object", "null"]},
        "exa": {"type": ["object", "null"]},
        "release": {"type": ["object", "null"]},
        "ai_enabled": {"type": "boolean"},
        "campaign_profile": {"type": "boolean"},
        "shared_control": {"type": "boolean"},
    },
    "required": ["version", "network", "paths"],
    "additionalProperties": False,
}


def load_operator_config(path: Path) -> OperatorConfig:
    """Load and validate operator configuration from JSON file."""
    if not path.is_file():
        raise OperatorConfigError(f"Operator config not found: {path}")
    if path.is_symlink():
        raise OperatorConfigError("Operator config must not be a symlink")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise OperatorConfigError("Operator config must not be group/other readable (0600)")

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise OperatorConfigError(f"Invalid JSON: {e}") from e

    # Reject unknown fields
    allowed = {
        "version",
        "network",
        "paths",
        "bridge",
        "provider",
        "exa",
        "release",
        "ai_enabled",
        "campaign_profile",
        "shared_control",
    }
    unknown = set(raw.keys()) - allowed
    if unknown:
        raise OperatorConfigError(f"Unknown configuration fields: {sorted(unknown)}")

    # Reject duplicate keys (JSON parser keeps last, we want to fail)
    # This is best-effort since json module doesn't expose duplicates
    # We'll check by re-scanning raw text for duplicate keys
    _check_duplicate_keys(path.read_text())

    return _parse_config(raw)


def _check_duplicate_keys(text: str) -> None:
    """Reject duplicate keys inside any one object; nested repeats are legal.

    Different sections legitimately repeat key names (``paths.config_dir`` and
    ``bridge.config_dir``), so detection must be per object, not per document.
    ``object_pairs_hook`` sees exactly the key pairs of one JSON object.
    """

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise OperatorConfigError(f"Duplicate key in configuration: {key}")
            seen.add(key)
        return dict(pairs)

    try:
        json.loads(text, object_pairs_hook=reject_duplicates)
    except OperatorConfigError:
        raise
    except json.JSONDecodeError:
        return  # load_operator_config reports invalid JSON with its own message


def _parse_config(raw: dict[str, Any]) -> OperatorConfig:
    """Parse validated raw dict into OperatorConfig."""
    try:
        network = NetworkConfig(**raw["network"])
        paths = PathsConfig(**raw["paths"])
        bridge = BridgeConfig(**raw["bridge"]) if raw.get("bridge") else None

        provider = None
        if raw.get("provider"):
            p = raw["provider"]
            credential = CredentialRef(**p["credential"])
            provider = ProviderConfig(
                provider=p["provider"],
                model=p["model"],
                base_url=p["base_url"],
                credential=credential,
                free_only=p.get("free_only", False),
                completion_cap=p.get("completion_cap", 1024),
                context_limit=p.get("context_limit"),
                completion_limit=p.get("completion_limit"),
                extra_body=p.get("extra_body", {}),
                fallback_models=tuple(p.get("fallback_models", [])),
            )

        exa = None
        if raw.get("exa"):
            e = raw["exa"]
            credential = CredentialRef(**e["credential"])
            exa = ExaConfig(
                endpoint=e["endpoint"],
                credential=credential,
                allowed_tools=tuple(e.get("allowed_tools", ["web_search_exa", "web_fetch_exa"])),
                enabled=e.get("enabled", True),
            )

        release = None
        if raw.get("release"):
            r = raw["release"]
            release = ReleaseConfig(
                image_id=r["image_id"],
                source_revision=r["source_revision"],
                schema_version=r["schema_version"],
                host_bundle_hash=r["host_bundle_hash"],
                base_image_digest=r["base_image_digest"],
            )

        return OperatorConfig(
            version=raw["version"],
            network=network,
            paths=paths,
            bridge=bridge,
            provider=provider,
            exa=exa,
            release=release,
            ai_enabled=raw.get("ai_enabled", False),
            campaign_profile=raw.get("campaign_profile", True),
            shared_control=raw.get("shared_control", True),
        )
    except TypeError as e:
        raise OperatorConfigError(f"Invalid configuration structure: {e}") from e
    except OperatorConfigError:
        raise
    except Exception as e:
        raise OperatorConfigError(f"Configuration parsing failed: {e}") from e


def create_example_config() -> dict[str, Any]:
    """Create an example configuration dictionary (for documentation)."""
    return {
        "version": 1,
        "network": {
            "vm_bind": "10.10.10.20",
            "vm_port": 8787,
            "relay_ip": "192.168.1.10",
            "relay_port": 8787,
            "owner_port": 8789,
            "timezone": "UTC",
            "compose_project": "household-report",
        },
        "paths": {
            "config_dir": "/home/operator/.config/starlink-monitoring/campaign",
            "input_dir": "/home/operator/.local/share/household-report/input",
            "state_dir": "/home/operator/.local/share/household-report/state",
            "bridge_dir": "/home/operator/.local/share/household-report/generated-units",
            "campaign_config_dir": "/home/operator/.config/starlink-monitoring/campaign",
        },
        "bridge": {
            "python": "/home/operator/github/starlink-monitoring/destination-report/.venv/bin/python",
            "compose": "/home/operator/github/starlink-monitoring/destination-report/compose.yaml",
            "docker": "/usr/bin/docker",
            "container": "starlink-dns-pilot",
            "database": "/etc/pihole/pihole-FTL.db",
            "generation": "gen-1",
            "identity": "provenance-abc123",
            "config_dir": "/home/operator/.config/starlink-monitoring/campaign",
            "state_dir": "/home/operator/.local/share/household-report/state",
            "input_dir": "/home/operator/.local/share/household-report/input",
        },
        "provider": None,
        "exa": None,
        "release": None,
        "ai_enabled": False,
        "campaign_profile": True,
        "shared_control": True,
    }


def write_example_config(path: Path) -> None:
    """Write example configuration to file (operator must customize)."""
    example = create_example_config()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(example, indent=2, sort_keys=True))
    path.chmod(0o600)


__all__ = [
    "OperatorConfig",
    "OperatorConfigError",
    "NetworkConfig",
    "PathsConfig",
    "BridgeConfig",
    "CredentialRef",
    "ProviderConfig",
    "ExaConfig",
    "ReleaseConfig",
    "load_operator_config",
    "create_example_config",
    "write_example_config",
]
