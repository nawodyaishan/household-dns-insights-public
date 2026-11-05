#!/usr/bin/env python3
"""Typed operator driver for the stack lifecycle (006 plan D2).

One command, one explicit effect, one sanitized JSON result on stdout::

    setup | check | start | status | stop | restart | upgrade | rollback |
    backup | restore | uninstall | journal

Boundaries enforced here, not by convention:

- No command starts or finishes a campaign, reads resolver source rows,
  changes firewall/DNS state, or spends money.
- External effects go through one injected runner restricted to an
  allowlisted Docker/systemd argument-array vocabulary with a neutralized
  environment (ambient ``COMPOSE_*``/``HR_*``/``AI_*``/``EXA_*`` variables
  are stripped; only explicit resolved values are passed).
- ``--config`` selects the operator JSON (fresh installation). Without it the
  driver reads the legacy ``HR_*`` environment. Passing ``--config`` while
  legacy ``HR_*``/``AI_*`` variables are present refuses as a contradictory
  mixed path.
- Destructive commands (stop, restart, upgrade, rollback, backup, restore,
  uninstall) refuse without their exact confirmation token.

Everything printed is sanitized: no credentials, no household rows, no source
identity strings, no provider payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from household_report.collector_status import classify_status, read_status
from household_report.maintenance import (
    STAGE_ORDER,
    MaintenanceError,
    MaintenanceJournal,
    MaintenanceLock,
    UpgradeStages,
    maintenance_backup,
    restore_isolated,
    upgrade_guards,
    verify_backup,
)
from household_report.operator_config import (
    OperatorConfig,
    OperatorConfigError,
    load_operator_config,
)
from household_report.release import (
    ReleaseError,
    ReleaseManifest,
    check_schema_compatibility,
    parse_manifest,
    verify_host_bundle,
)
from household_report.settings import (
    Settings,
    SettingsError,
    load_settings,
    load_settings_from_operator_config,
)
from household_report.storage import SCHEMA_VERSION, StorageError, Store, open_store

TOOLS_DIR = Path(__file__).resolve().parent
APP_DIR = TOOLS_DIR.parent
PREPARED_NAME = "stack-prepared.json"
PREPARED_SCHEMA = 1
BRIDGE_UNITS = ("household-campaign-bridge.service", "household-campaign-bridge.timer")
#: Every external effect must start with one of these argument-array prefixes.
ALLOWED_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("docker", "compose"),
    ("docker", "build"),
    ("docker", "image", "inspect"),
    ("docker", "tag"),
    ("systemctl",),
)
#: Ambient variables that must never influence a driver-invoked subprocess.
NEUTRALIZED_PREFIXES = ("COMPOSE_", "HR_", "AI_", "EXA_")
#: Exact legacy AI keys the settings loader reads. A broad ``AI_`` prefix would
#: trip unrelated ambient variables (for example ``AI_AGENT``).
LEGACY_AI_KEYS = frozenset(
    {
        "AI_PROVIDER",
        "AI_MODEL_ID",
        "LLM_MODEL",
        "AI_CREDENTIAL_FILE",
        "LLM_CREDENTIAL_FILE",
        "AI_BASE_URL",
        "LLM_BASE_URL",
        "AI_CREDENTIAL_VAR",
        "AI_CONTEXT_LIMIT",
        "AI_COMPLETION_LIMIT",
        "AI_COMPLETION_CAP",
        "AI_EXTRA_BODY_JSON",
        "AI_FALLBACK_MODELS",
        "AI_FREE_ONLY",
        "AI_PAID_MODE",
        "AI_PROVIDER_PRICE_PER_MILLION",
        "AI_EXA_PRICE_PER_OPERATION",
        "AI_CURRENCY_CEILING_RUN",
        "AI_CURRENCY_CEILING_DAY",
        "AI_EXA_CURRENCY_CEILING_RUN",
        "AI_EXA_CURRENCY_CEILING_DAY",
    }
)
CONFIRMATIONS = {
    "stop": "stop",
    "restart": "restart",
    "upgrade": "upgrade",
    "rollback": "rollback",
    "backup": "backup",
    "restore": "restore",
    "uninstall": "uninstall",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


class StackError(RuntimeError):
    """A command precondition failed; the detail stays sanitized."""


# -- configuration resolution -------------------------------------------------


def _neutralized_env() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items() if not key.startswith(NEUTRALIZED_PREFIXES)
    }


def _private_dir(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise StackError(f"{label} must not be a symlink")
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise StackError(f"{label} must be a directory")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise StackError(f"{label} must be private (0700), not group/other accessible")
    return path


def _write_private_json(path: Path, document: Mapping[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(document, handle, sort_keys=True, indent=2)


def _load_tools_module(name: str):
    """Import a sibling operator tool (script execution and test loading both work)."""
    import importlib.util

    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    spec = importlib.util.spec_from_file_location(f"stack_{name}", TOOLS_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        raise StackError(f"Operator tool is missing: {name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checked_run(
    runner: Runner, argv: list[str], *, operation: str, env: Mapping[str, str] | None = None
) -> str:
    """Run exactly one allowlisted argument array; never leak command output."""
    if not any(tuple(argv[: len(prefix)]) == prefix for prefix in ALLOWED_PREFIXES):
        raise StackError(f"Refused unlisted external effect for {operation}")
    try:
        result = runner(
            list(argv),
            capture_output=True,
            text=True,
            timeout=120,
            env=dict(env or _neutralized_env()),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StackError(f"{operation} could not be executed") from error
    if result.returncode != 0:
        raise StackError(f"{operation} failed (exit {result.returncode}); see sanitized status")
    return result.stdout or ""


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compose_ps(stdout: str) -> list[dict[str, str]]:
    """Parse `docker compose ps --format json` lines (best effort, sanitized)."""
    containers: list[dict[str, str]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, list):
            entries = entry
        elif isinstance(entry, dict):
            entries = [entry]
        else:
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            containers.append(
                {
                    "name": str(item.get("Name") or item.get("name") or ""),
                    "state": str(item.get("State") or item.get("state") or "unknown"),
                    "status": str(item.get("Status") or item.get("status") or ""),
                }
            )
    return containers


# -- driver -------------------------------------------------------------------


class StackDriver:
    """Resolves one configuration and executes one explicit stack command."""

    def __init__(
        self,
        *,
        config: Path | None = None,
        env: Mapping[str, str] | None = None,
        runner: Runner = subprocess.run,
        now_epoch: int | None = None,
    ) -> None:
        self._env = dict(os.environ if env is None else env)
        self._runner = runner
        self._now_epoch = now_epoch
        self._operator: OperatorConfig | None = None
        self._config_source = config
        if config is not None:
            legacy = sorted(
                key
                for key in self._env
                if key.startswith(("HR_", "EXA_", "LLM_")) or key in LEGACY_AI_KEYS
            )
            if legacy:
                raise StackError(
                    "CONFIG was selected while legacy HR_*/AI_*/EXA_* variables are present; "
                    f"resolve the mixed path first: {legacy}"
                )
            try:
                self._operator = load_operator_config(config)
                self._settings = load_settings_from_operator_config(config)
            except (OperatorConfigError, SettingsError) as error:
                raise StackError(f"Operator configuration rejected: {error}") from error
        else:
            try:
                self._settings = load_settings(self._env)
            except SettingsError as error:
                raise StackError(f"Legacy configuration rejected: {error}") from error
        self._state_dir = (
            Path(self._operator.paths.state_dir)
            if self._operator is not None
            else self._settings.database_path.parent
        )
        self._input_dir = (
            Path(self._operator.paths.input_dir)
            if self._operator is not None
            else self._settings.input_dir
        )

    # -- derived views -------------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def project(self) -> str:
        """The Docker Compose project that owns this deployment.

        An existing deployment names its real project in the operator config:
        a different project cannot reuse the fixed application bridge names
        (br-hr005/br-hr006) and would fail to start, and it would not manage
        the containers this installation already owns.
        """
        if self._operator is not None:
            configured = self._operator.network.compose_project
            if configured:
                return configured
        return "hr-" + hashlib.sha256(str(self._state_dir).encode()).hexdigest()[:10]

    def _profile(self) -> str:
        if self._settings.shared_control:
            return "shared"
        if self._settings.ai_enabled:
            return "owner"
        return "loopback"

    def _compose_files(self) -> list[Path]:
        base = [APP_DIR / "compose.yaml"]
        profile = self._profile()
        if profile == "shared":
            base.append(APP_DIR / "compose.lan.yaml")
        elif profile == "owner":
            base.append(APP_DIR / "compose.ai.yaml")
        return base

    def _compose_env(self) -> dict[str, str]:
        env = _neutralized_env()
        web = self._settings.web
        port = 8787
        if web is not None:
            parsed = urlsplit(web.public_url)
            if parsed.port:
                port = parsed.port
            env["HR_PUBLIC_URL"] = web.public_url
            env["HR_ALLOWED_HOSTS"] = ",".join(web.allowed_hosts)
        env.update(
            {
                "HR_CONFIG_DIR": str(self._config_dir()) if self._config_dir() else "",
                "HR_INPUT_DIR": str(self._input_dir),
                "HR_STATE_DIR": str(self._state_dir),
                "HR_PORT": str(port),
                "HR_TIMEZONE": self._settings.timezone,
                "HR_UID": str(os.getuid()),
                "HR_GID": str(os.getgid()),
            }
        )
        provider = self._settings.provider
        if provider is not None:
            env.update(
                {
                    "AI_PROVIDER": provider.provider,
                    "AI_MODEL_ID": provider.model_id,
                    "AI_BASE_URL": provider.base_url,
                    "AI_FREE_ONLY": "1" if provider.free_only else "0",
                    "AI_CREDENTIAL_FILE": self._container_path(provider.credential_path),
                    "AI_CREDENTIAL_VAR": provider.credential_var or "",
                    "AI_COMPLETION_CAP": str(provider.completion_cap),
                }
            )
            if provider.context_limit:
                env["AI_CONTEXT_LIMIT"] = str(provider.context_limit)
            if provider.completion_limit:
                env["AI_COMPLETION_LIMIT"] = str(provider.completion_limit)
        exa = self._settings.exa
        if exa is not None and exa.enabled:
            env["EXA_MCP_URL"] = exa.endpoint
            env["EXA_KEY_FILE"] = self._container_path(exa.api_key_path)
        if self._profile() == "shared":
            bind = (
                self._operator.network.vm_bind
                if self._operator is not None
                else self._env.get("HR_LAN_BIND", "")
            )
            if not bind:
                raise StackError("The shared profile needs an explicit approved LAN bind")
            env["HR_LAN_BIND"] = bind
        return {
            key: value for key, value in env.items() if value != "" or key == "AI_CREDENTIAL_VAR"
        }

    def _config_dir(self) -> Path | None:
        if self._operator is not None:
            return Path(self._operator.paths.config_dir)
        raw = self._env.get("HR_CONFIG_DIR", "").strip()
        return Path(raw) if raw else None

    def _container_path(self, host_path: Path) -> str:
        config_dir = self._config_dir()
        if config_dir is None:
            raise StackError("A credential path needs an explicit configuration directory")
        try:
            relative = Path(host_path).resolve().relative_to(config_dir.resolve())
        except ValueError as error:
            raise StackError(
                "Credential file must live inside the mounted configuration directory"
            ) from error
        return "/config/" + str(relative)

    def _compose_argv(self, *args: str, extra_files: Sequence[Path] = ()) -> list[str]:
        argv = ["docker", "compose", "-p", self.project]
        for file in [*self._compose_files(), *extra_files]:
            argv += ["-f", str(file)]
        argv += list(args)
        return argv

    def _bridge_units_dir(self) -> Path | None:
        # An instance that runs no bridge (the owner research dashboard) must
        # not render, stop or remove the campaign bridge: that belongs to the
        # shared instance and to the operator's host.
        if self._operator is None or self._operator.bridge is None:
            return None
        return Path(self._operator.paths.bridge_dir)

    def _bridge_json(self) -> Path | None:
        units_dir = self._bridge_units_dir()
        return units_dir / "campaign-bridge.json" if units_dir else None

    def _has_bridge(self) -> bool:
        path = self._bridge_json()
        return path is not None and path.exists()

    def _database_path(self) -> Path:
        if self._operator is not None:
            return self._state_dir / "app.sqlite3"
        return self._settings.database_path

    # -- prepared state ------------------------------------------------------
    def _config_identity(self) -> str:
        """Digest of exactly the configuration this driver resolved.

        The operator file is secret-free by design; for the legacy path only the
        variable names the loader reads are digested, never their values.
        """
        if self._config_source is not None:
            return hashlib.sha256(self._config_source.read_bytes()).hexdigest()[:32]
        legacy = {
            key: value
            for key, value in sorted(self._env.items())
            if key.startswith(("HR_", "EXA_", "LLM_")) or key in LEGACY_AI_KEYS
        }
        return hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()[:32]

    def _prepared_path(self) -> Path:
        return self._state_dir / PREPARED_NAME

    def _write_prepared(self, *, build: str) -> dict[str, object]:
        release = self._operator.release if self._operator is not None else None
        document = {
            "prepared_schema": PREPARED_SCHEMA,
            "prepared_utc": _now_utc(),
            "config_identity": self._config_identity(),
            "profile": self._profile(),
            "image_id": release.image_id if release else None,
            "schema_version": release.schema_version if release else SCHEMA_VERSION,
            "build": build,
        }
        _write_private_json(self._prepared_path(), document)
        return document

    def _require_prepared(self) -> dict[str, object]:
        path = self._prepared_path()
        if not path.exists() or path.is_symlink():
            raise StackError("Stack is not prepared; run setup first")
        try:
            document = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise StackError("Prepared state is unreadable; re-run setup") from error
        if document.get("prepared_schema") != PREPARED_SCHEMA:
            raise StackError("Prepared state schema is unsupported; re-run setup")
        if document.get("config_identity") != self._config_identity():
            raise StackError("Configuration changed since setup; re-run setup")
        return document

    # -- release helpers -----------------------------------------------------
    def _release(self):
        if self._operator is None or self._operator.release is None:
            raise StackError("This command needs an explicit release in the operator config")
        return self._operator.release

    def _current_manifest(self) -> ReleaseManifest:
        release = self._release()
        if not release.image_id.startswith("sha256:"):
            raise StackError("Release switching needs an immutable image ID; a tag is not identity")
        lock = _load_tools_module("release_manifest")
        digests = lock.base_digests(APP_DIR / "Dockerfile")
        runtime = digests.get("runtime") or list(digests.values())[-1]
        return ReleaseManifest(
            image_id=release.image_id,
            source_revision=release.source_revision,
            schema_version=release.schema_version,
            lock_sha256=lock._file_digest(APP_DIR / "uv.lock"),
            base_image_digest=f"sha256:{runtime}",
            host_bundle_sha256=release.host_bundle_hash,
            built_utc=_now_utc(),
        )

    def _target_manifest(self, path: Path) -> ReleaseManifest:
        if path.is_symlink() or not path.is_file():
            raise StackError("Target release manifest must be a regular file")
        try:
            return parse_manifest(json.loads(path.read_text()))
        except (OSError, ValueError, ReleaseError) as error:
            raise StackError(f"Target release manifest rejected: {error}") from error

    def _tag_for(self, source_revision: str) -> str:
        return "household-report:stack-" + source_revision[:12]

    def _image_tag(self, manifest: ReleaseManifest) -> str:
        return self._tag_for(manifest.source_revision)

    # -- commands ------------------------------------------------------------
    def setup(self, *, build: bool = False, user: str | None = None) -> dict[str, object]:
        directories: list[str] = []
        for raw in filter(
            None,
            (
                str(self._config_dir()) if self._config_dir() else None,
                str(self._input_dir),
                str(self._state_dir),
                str(self._bridge_units_dir()) if self._bridge_units_dir() else None,
            ),
        ):
            directories.append(str(_private_dir(Path(raw), "Private directory")))
        units: list[str] = []
        bridge_path = self._bridge_json()
        if (
            bridge_path is not None
            and self._operator is not None
            and self._operator.bridge is not None
        ):
            bridge = self._operator.bridge
            payload = {
                "python": bridge.python,
                "compose": bridge.compose,
                "input_dir": bridge.input_dir,
                "container": bridge.container,
                "database": bridge.database,
                "docker": bridge.docker,
                "generation": bridge.generation,
                "identity": bridge.identity,
                "config_dir": bridge.config_dir,
                "state_dir": bridge.state_dir,
            }
            if bridge_path.exists():
                try:
                    existing = json.loads(bridge_path.read_text())
                except (OSError, ValueError) as error:
                    raise StackError("Existing bridge configuration is unreadable") from error
                if existing != payload:
                    raise StackError(
                        "Existing bridge configuration differs; resolve it explicitly "
                        "before setup (identity is never rebound silently)"
                    )
            else:
                _write_private_json(bridge_path, payload)
            account = user or pwd.getpwuid(os.getuid()).pw_name
            if account == "root":
                raise StackError("Bridge units need an explicit non-root operator account")
            units_module = _load_tools_module("render_bridge_units")
            service, timer = units_module.render(
                user=account,
                config=bridge_path,
                python=Path(bridge.python),
                bridge=TOOLS_DIR / "host_bridge.py",
            )
            units_dir = _private_dir(Path(self._operator.paths.bridge_dir), "Bridge directory")
            for name, content in zip(BRIDGE_UNITS, (service, timer), strict=True):
                target = units_dir / name
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644
                )
                with os.fdopen(descriptor, "w") as handle:
                    handle.write(content)
                units.append(str(target))
        build_state = "not-requested"
        if build:
            release = self._release()
            _checked_run(
                self._runner,
                [
                    "docker",
                    "build",
                    "-f",
                    str(APP_DIR / "Dockerfile"),
                    "-t",
                    self._tag_for(release.source_revision),
                    str(APP_DIR),
                ],
                operation="image build",
            )
            build_state = "requested"
        prepared = self._write_prepared(build=build_state)
        return {
            "command": "setup",
            "directories": directories,
            "rendered_units": units,
            "build": build_state,
            "prepared": prepared,
            "effects": "local preparation only: no install, publication, capture or research",
        }

    def check(self, *, live: bool = False) -> dict[str, object]:
        issues: list[str] = []
        for raw in filter(
            None,
            (
                str(self._config_dir()) if self._config_dir() else None,
                str(self._input_dir),
                str(self._state_dir),
            ),
        ):
            path = Path(raw)
            if not path.is_dir():
                issues.append(f"missing directory: {path.name}")
            elif stat.S_IMODE(path.stat().st_mode) & 0o077:
                issues.append(f"permissive directory: {path.name}")
        try:
            self._require_prepared()
        except StackError as error:
            issues.append(str(error))
        release_state: object = "legacy-unmanaged"
        if self._operator is not None and self._operator.release is not None:
            release = self._operator.release
            try:
                bundle = _load_tools_module("release_manifest")
                verify_host_bundle(release.host_bundle_hash, bundle.host_bundle())
                check_schema_compatibility(release.schema_version, SCHEMA_VERSION)
                release_state = {
                    "image_id": release.image_id,
                    "schema_version": release.schema_version,
                    "host_bundle": "verified",
                }
            except Exception as error:  # noqa: BLE001 - sanitized into an issue list
                issues.append(f"release check failed: {type(error).__name__}")
        journal = MaintenanceJournal(self._state_dir).load()
        result: dict[str, object] = {
            "command": "check",
            "mode": "live" if live else "offline",
            "profile": self._profile(),
            "release": release_state,
            "journal_active": bool(journal.get("active")),
            "issues": issues,
            "ok": not issues,
        }
        if live:
            stdout = _checked_run(
                self._runner,
                self._compose_argv("ps", "-a", "--format", "json"),
                operation="runtime status read",
            )
            result["runtime"] = {"observed": True, "containers": _compose_ps(stdout)}
        else:
            result["runtime"] = {"observed": False, "note": "offline mode reads no runtime state"}
        return result

    def start(self) -> dict[str, object]:
        prepared = self._require_prepared()
        release_note = "legacy-unmanaged"
        extra_files: list[Path] = []
        if self._operator is not None and self._operator.release is not None:
            release = self._release()
            _checked_run(
                self._runner,
                ["docker", "image", "inspect", release.image_id],
                operation="selected release image check",
            )
            release_note = release.image_id
            # The selected immutable image must be the one Compose runs; the
            # base Compose file pins the mutable `household-report:local` tag.
            extra_files = [self._apply_release_override(release)]
        _checked_run(
            self._runner,
            self._compose_argv("up", "-d", extra_files=extra_files),
            operation="application pair start",
            env=self._compose_env(),
        )
        return {
            "command": "start",
            "profile": prepared["profile"],
            "release": release_note,
            "campaign": "not-started",
            "network": "unchanged",
            "spend": "disabled",
        }

    def status(self, *, live: bool = True) -> dict[str, object]:
        journal = MaintenanceJournal(self._state_dir).load()
        result: dict[str, object] = {
            "command": "status",
            "profile": self._profile(),
            "project": self.project,
            "schema_version": None,
            "campaigns": [],
            "journal": {
                "active": bool(journal.get("active")),
                "completed": list(journal.get("completed") or []),
                "next_stage": MaintenanceJournal(self._state_dir).resume(),
            },
            "prepared": self._prepared_path().exists(),
            "network": "unchanged",
            "external_calls": "none",
        }
        database = self._database_path()
        if database.exists():
            store = Store.open(database)
            try:
                result["schema_version"] = int(
                    store._conn.execute("PRAGMA user_version").fetchone()[0]
                )
                result["campaigns"] = [
                    {"campaign_id": str(row["campaign_id"]), "state": str(row["state"])}
                    for row in store.campaigns()
                ]
            finally:
                store.close()
        status_path = (
            self._state_dir / "bridge-status.json"
            if self._settings.bridge_status_file is None
            else self._settings.bridge_status_file
        )
        record = read_status(Path(status_path)) if status_path.exists() else None
        active = next(
            (c for c in result["campaigns"] if c["state"] in {"active", "finalizing"}), None
        )
        result["collector"] = classify_status(
            record,
            now_epoch=self._now_epoch or int(datetime.now(UTC).timestamp()),
            campaign_state=active["state"] if active else None,
            campaign_complete=None if active else True,
        )
        if live:
            try:
                stdout = _checked_run(
                    self._runner,
                    self._compose_argv("ps", "-a", "--format", "json"),
                    operation="runtime status read",
                    env=self._compose_env(),
                )
                result["runtime"] = {"observed": True, "containers": _compose_ps(stdout)}
            except StackError:
                result["runtime"] = {"observed": False, "note": "runtime state unavailable"}
        else:
            result["runtime"] = {"observed": False, "note": "offline status"}
        return result

    def stop(self, *, confirm: str | None = None) -> dict[str, object]:
        self._require_confirm("stop", confirm)
        warnings: list[str] = []
        if self._has_bridge():
            try:
                _checked_run(
                    self._runner,
                    ["systemctl", "stop", "household-campaign-bridge.service"],
                    operation="bridge stop",
                )
            except StackError as error:
                warnings.append(str(error))
        _checked_run(
            self._runner,
            self._compose_argv("stop"),
            operation="application pair stop",
            env=self._compose_env(),
        )
        return {
            "command": "stop",
            "bridge": "stopped" if self._has_bridge() else "not-installed",
            "applications": "stopped",
            "data": "retained",
            "dns": "untouched",
            "warnings": warnings,
        }

    def restart(self, *, confirm: str | None = None) -> dict[str, object]:
        self._require_confirm("restart", confirm)
        stopped = self.stop(confirm="stop")
        started = self.start()
        return {
            "command": "restart",
            "stopped": stopped,
            "started": started,
            "campaign": "not-restarted",
        }

    def _transaction(
        self,
        *,
        target: ReleaseManifest | None,
        archive: Path,
        change_release: bool,
    ) -> dict[str, object]:
        current = self._current_manifest() if change_release or target is None else None
        if change_release:
            assert target is not None and current is not None
            try:
                plan = upgrade_guards(current, target)
            except (MaintenanceError, ReleaseError) as error:
                raise StackError(str(error)) from error
        else:
            plan = {"stages": list(STAGE_ORDER), "release_switch": False}
        journal = MaintenanceJournal(self._state_dir)
        with MaintenanceLock(self._state_dir):
            if journal.load().get("active"):
                if target is not None and journal.load().get("target_image_id") != target.image_id:
                    raise StackError(
                        "Another maintenance transaction is active for a different target"
                    )
            else:
                journal.begin(
                    target_image_id=(
                        target.image_id if target is not None else current.image_id  # type: ignore[union-attr]
                    )
                )
            stage_work = {
                UpgradeStages.STOP_BRIDGE: self._stage_stop_bridge,
                UpgradeStages.STOP_WRITERS: self._stage_stop_writers,
                UpgradeStages.BACKUP: lambda: self._stage_backup(archive),
                UpgradeStages.MIGRATE: self._stage_migrate,
                UpgradeStages.RECREATE: lambda: self._stage_recreate(
                    target or current  # type: ignore[arg-type]
                ),
                UpgradeStages.CHECK: lambda: self._stage_check(
                    target or current  # type: ignore[arg-type]
                ),
            }
            while True:
                stage = journal.resume()
                if stage is None:
                    break
                journal.record(stage)
                try:
                    stage_work[stage]()
                except (StackError, MaintenanceError, StorageError, ReleaseError) as error:
                    raise StackError(
                        f"Maintenance stage {stage!r} failed: {error}; the journal stays "
                        f"active at {journal.resume()!r} for resume or rollback"
                    ) from error
            journal.complete()
        if target is not None:
            self._write_prepared(build="unchanged")
        return {
            "plan": plan,
            "archive": str(archive),
            "journal": "complete",
            "state": "running" if change_release else "recreated",
        }

    def _stage_stop_bridge(self) -> None:
        if self._has_bridge():
            try:
                _checked_run(
                    self._runner,
                    ["systemctl", "stop", "household-campaign-bridge.service"],
                    operation="bridge stop",
                )
            except StackError:
                pass  # Absent unit is quiesced; the journal records the attempt.

    def _stage_stop_writers(self) -> None:
        _checked_run(
            self._runner,
            self._compose_argv("stop"),
            operation="writer stop",
            env=self._compose_env(),
        )

    def _stage_backup(self, archive: Path) -> None:
        if archive.exists() and any(archive.iterdir()):
            raise StackError("Backup archive directory must be empty")
        _private_dir(archive, "Backup archive")
        manifest = self._current_manifest()
        store = open_store(self._database_path())
        try:
            maintenance_backup(
                store,
                input_dir=self._input_dir,
                destination=archive,
                state_dir=self._state_dir,
                manifest=manifest,
                config_fingerprint=self._settings.config_fingerprint(),
            )
        finally:
            store.close()
        verify_backup(archive)

    def _stage_migrate(self) -> None:
        store = open_store(self._database_path())  # idempotent; explicit here
        store.close()

    def _apply_release_override(self, release) -> Path:
        """Tag the selected immutable image and point Compose at that exact tag.

        The base Compose file pins the mutable ``household-report:local`` tag, so
        a release that is only inspected is not necessarily the release that
        runs. This writes a private override file that replaces the image with
        the versioned tag of the selected image ID.
        """
        tag = self._tag_for(release.source_revision)
        _checked_run(
            self._runner,
            ["docker", "tag", release.image_id, tag],
            operation="release tag",
        )
        override = self._state_dir / "stack-image-override.yaml"
        descriptor = os.open(override, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"services:\n  app:\n    image: {tag}\n")
        return override

    def _stage_recreate(self, target: ReleaseManifest) -> None:
        override = self._apply_release_override(target)
        _checked_run(
            self._runner,
            self._compose_argv("up", "-d", "--force-recreate", extra_files=[override]),
            operation="pair recreation",
            env=self._compose_env(),
        )

    def _stage_check(self, target: ReleaseManifest) -> None:
        stdout = _checked_run(
            self._runner,
            self._compose_argv("ps", "-a", "--format", "json"),
            operation="post-recreation check",
            env=self._compose_env(),
        )
        containers = _compose_ps(stdout)
        if not containers:
            raise StackError("No containers observed after recreation")
        if any(entry["state"] != "running" for entry in containers):
            raise StackError("Containers are not running after recreation")
        if any("Restarting" in entry["status"] for entry in containers):
            raise StackError("A container is restarting after recreation")

    def upgrade(
        self,
        *,
        release: Path,
        archive: Path | None = None,
        resume: bool = False,
        confirm: str | None = None,
    ) -> dict[str, object]:
        self._require_confirm("upgrade", confirm)
        target = self._target_manifest(release)
        if not resume and MaintenanceJournal(self._state_dir).load().get("active"):
            raise StackError("A maintenance transaction is active; resume it or reset explicitly")
        destination = archive or (
            self._state_dir / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        result = self._transaction(target=target, archive=destination, change_release=True)
        return {
            "command": "upgrade",
            **result,
            "next": (
                "point the operator config release section at the target manifest, "
                "then re-run setup and check (the driver never rewrites owner config)"
            ),
        }

    def rollback(
        self, *, release: Path, archive: Path | None = None, confirm: str | None = None
    ) -> dict[str, object]:
        self._require_confirm("rollback", confirm)
        target = self._target_manifest(release)
        if MaintenanceJournal(self._state_dir).load().get("active"):
            raise StackError("A maintenance transaction is active; resume it or reset explicitly")
        destination = archive or (
            self._state_dir / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        )
        try:
            result = self._transaction(target=target, archive=destination, change_release=True)
        except StackError as error:
            if "isolated restore" in str(error):
                raise StackError(
                    f"{error}; use restore with the preserved pre-upgrade archive into a "
                    "new private directory (production promotion stays a separate action)"
                ) from error
            raise
        return {
            "command": "rollback",
            **result,
            "next": (
                "point the operator config release section at the preserved manifest, "
                "then re-run setup and check (the driver never rewrites owner config)"
            ),
        }

    def backup(self, *, archive: Path, confirm: str | None = None) -> dict[str, object]:
        self._require_confirm("backup", confirm)
        if MaintenanceJournal(self._state_dir).load().get("active"):
            raise StackError(
                "A maintenance transaction is active; resume or reset it before a standalone backup"
            )
        result = self._transaction(target=None, archive=archive, change_release=False)
        return {"command": "backup", **result, "effects": "quiesce, backup, recreate same release"}

    def restore(
        self, *, archive: Path, dest: Path, confirm: str | None = None
    ) -> dict[str, object]:
        self._require_confirm("restore", confirm)
        manifest = restore_isolated(archive, dest)
        return {
            "command": "restore",
            "mode": "isolation",
            "destination": str(dest),
            "application_schema": manifest.get("application_schema"),
            "promotion": "separate explicit owner operation; production is untouched",
        }

    def uninstall(self, *, confirm: str | None = None) -> dict[str, object]:
        owned_units = []
        units_dir = self._bridge_units_dir()
        if units_dir is not None:
            owned_units = [
                str(units_dir / name)
                for name in BRIDGE_UNITS
                if (units_dir / name).is_file() and not (units_dir / name).is_symlink()
            ]
        preview = {
            "command": "uninstall",
            "confirmed": False,
            "would_remove": {
                "compose_project": self.project,
                "bridge_units": owned_units,
                "timer": "household-campaign-bridge.timer",
            },
            "retained": [
                str(self._state_dir),
                str(self._input_dir),
                "configuration",
                "images",
                "backups",
                "DNS",
            ],
            "effects": "preview only; nothing was removed",
        }
        if confirm != CONFIRMATIONS["uninstall"]:
            return preview
        warnings: list[str] = []
        if self._has_bridge() or owned_units:
            try:
                _checked_run(
                    self._runner,
                    ["systemctl", "disable", "--now", "household-campaign-bridge.timer"],
                    operation="timer disable",
                )
            except StackError as error:
                warnings.append(str(error))
        try:
            _checked_run(
                self._runner,
                self._compose_argv("down"),
                operation="publication removal",
                env=self._compose_env(),
            )
        except StackError as error:
            warnings.append(str(error))
        removed = []
        for raw in owned_units:
            path = Path(raw)
            if path.is_file() and not path.is_symlink():
                path.unlink()
                removed.append(raw)
        return {
            "command": "uninstall",
            "confirmed": True,
            "removed": {"compose_project": self.project, "bridge_units": removed},
            "retained": preview["retained"],
            "warnings": warnings,
            "dns": "untouched",
        }

    def journal(self, *, action: str, confirm: str | None = None) -> dict[str, object]:
        record = MaintenanceJournal(self._state_dir)
        if action == "status":
            document = record.load()
            return {
                "command": "journal",
                "action": "status",
                "active": bool(document.get("active")),
                "completed": list(document.get("completed") or []),
                "next_stage": record.resume(),
            }
        if confirm != "reset-journal":
            raise StackError("Journal reset needs the exact confirmation token")
        record.reset()
        return {"command": "journal", "action": "reset", "active": False}

    def _require_confirm(self, command: str, confirm: str | None) -> None:
        if confirm != CONFIRMATIONS[command]:
            raise StackError(
                f"{command} refuses without explicit confirmation: pass --confirm {command}"
            )


# -- command line -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, help="Operator JSON (fresh installation)")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Prepare private paths and render units")
    setup.add_argument("--build", action="store_true", help="Also build the release image")
    setup.add_argument("--user", help="Non-root operator account for the bridge units")
    check = commands.add_parser("check", help="Offline validation by default")
    check.add_argument("--live", action="store_true", help="Add a narrow runtime read")
    commands.add_parser("start", help="Start the selected application pair")
    status = commands.add_parser("status", help="Aggregated sanitized health")
    status.add_argument("--offline", action="store_true", help="Skip the runtime read")
    stop = commands.add_parser("stop", help="Stop bridge then applications")
    stop.add_argument("--confirm", help="Must be 'stop'")
    restart = commands.add_parser("restart", help="Stop, then start the same operation")
    restart.add_argument("--confirm", help="Must be 'restart'")
    upgrade = commands.add_parser("upgrade", help="Reviewable maintenance transaction")
    upgrade.add_argument("--release", type=Path, required=True, help="Target release manifest")
    upgrade.add_argument("--archive", type=Path, help="Empty backup directory")
    upgrade.add_argument("--resume", action="store_true", help="Resume the active transaction")
    upgrade.add_argument("--confirm", help="Must be 'upgrade'")
    rollback = commands.add_parser("rollback", help="Switch back to a preserved release")
    rollback.add_argument("--release", type=Path, required=True)
    rollback.add_argument("--archive", type=Path)
    rollback.add_argument("--confirm", help="Must be 'rollback'")
    backup = commands.add_parser("backup", help="Quiesce, back up, recreate the same release")
    backup.add_argument("--archive", type=Path, required=True)
    backup.add_argument("--confirm", help="Must be 'backup'")
    restore = commands.add_parser("restore", help="Restore only into an empty private directory")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--dest", type=Path, required=True)
    restore.add_argument("--confirm", help="Must be 'restore'")
    uninstall = commands.add_parser("uninstall", help="Preview, then remove owned publication")
    uninstall.add_argument("--confirm", help="Must be 'uninstall'")
    journal = commands.add_parser("journal", help="Maintenance journal status or reset")
    journal.add_argument("action", choices=("status", "reset"))
    journal.add_argument("--confirm", help="Reset needs 'reset-journal'")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        driver = StackDriver(config=args.config)
        if args.command == "setup":
            result = driver.setup(build=args.build, user=args.user)
        elif args.command == "check":
            result = driver.check(live=args.live)
        elif args.command == "start":
            result = driver.start()
        elif args.command == "status":
            result = driver.status(live=not args.offline)
        elif args.command == "stop":
            result = driver.stop(confirm=args.confirm)
        elif args.command == "restart":
            result = driver.restart(confirm=args.confirm)
        elif args.command == "upgrade":
            result = driver.upgrade(
                release=args.release, archive=args.archive, resume=args.resume, confirm=args.confirm
            )
        elif args.command == "rollback":
            result = driver.rollback(
                release=args.release, archive=args.archive, confirm=args.confirm
            )
        elif args.command == "backup":
            result = driver.backup(archive=args.archive, confirm=args.confirm)
        elif args.command == "restore":
            result = driver.restore(archive=args.archive, dest=args.dest, confirm=args.confirm)
        elif args.command == "uninstall":
            result = driver.uninstall(confirm=args.confirm)
        else:
            result = driver.journal(action=args.action, confirm=args.confirm)
    except (StackError, MaintenanceError, OperatorConfigError, SettingsError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
