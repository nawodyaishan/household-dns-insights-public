#!/usr/bin/env python3
"""Bounded campaign preflight: offline configuration first, live reads only on request.

Offline mode never contacts Docker, the resolver or the campaign database. It checks
private paths, secrets, TLS/name binding, the LAN Compose merge, the bridge contract,
the reviewed namespace and disk headroom, so an install/build cannot silently read
household data.

Live mode (``--mode live``) adds a narrow, read-only check of the resolver container,
the FTL query schema, its retention setting and the registered source generation.
It prints counts and settings only: never domains, clients, rows or credentials.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from household_report.gaming import GamingDataError, load_namespace_list

SAFE_ID = re.compile(r"[A-Za-z0-9:_-]{1,160}\Z")
BRIDGE_KEYS = {
    "python",
    "compose",
    "input_dir",
    "container",
    "database",
    "docker",
    "generation",
    "identity",
    "config_dir",
    "state_dir",
}
QUERY_COLUMNS = {
    "id",
    "timestamp",
    "type",
    "status",
    "domain",
    "client",
    "reply_type",
}
PROVIDER_KEYS = ("AI_PROVIDER", "AI_MODEL_ID", "AI_CREDENTIAL_FILE", "EXA_MCP_URL", "EXA_KEY_FILE")
MIN_FREE_BYTES = 2 * 1024**3

Runner = Callable[..., subprocess.CompletedProcess[str]]


class PreflightError(RuntimeError):
    """One preflight check failed; the detail is sanitized."""


def _private_dir(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_dir():
        raise PreflightError(f"{label} must be a real directory")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PreflightError(f"{label} must be 0700 (no group/other access)")
    return str(path)


def _secret(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise PreflightError(f"{label} is missing or empty")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PreflightError(f"{label} must not be group/other readable")
    return str(path)


def _lan_bind(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise PreflightError("LAN bind must be one explicit IP address") from error
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise PreflightError("LAN bind must not be wildcard, loopback or multicast")
    if not address.is_private:
        raise PreflightError("LAN bind must be a private address")
    return str(address)


def _origin(
    public_url: str,
    allowed_hosts: str,
    bind: str,
    port: str,
    relay_ip: str,
    profile: str = "campaign",
) -> str:
    parsed = urlsplit(public_url)
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
        raise PreflightError("Public URL must be a plain HTTP or HTTPS origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise PreflightError("Public URL must not contain a path, query or fragment")
    owner = profile == "owner"
    if owner and parsed.scheme != "https":
        raise PreflightError("Owner dashboard origin must be https")
    if relay_ip:
        if bind != "10.10.10.20" or relay_ip != "192.168.1.10":
            raise PreflightError("Unapproved dashboard relay address pair")
        if owner and port != "8789":
            raise PreflightError("Owner relay must publish exactly the owner port")
        if not owner and (port != "8787" or parsed.scheme != "http"):
            raise PreflightError("Unapproved dashboard relay address pair")
    elif parsed.hostname != bind:
        raise PreflightError("Public URL host must equal the approved LAN bind")
    if parsed.netloc != f"{relay_ip or bind}:{port}":
        raise PreflightError("Public URL port must equal the published port")
    hosts = tuple(host.strip() for host in allowed_hosts.split(",") if host.strip())
    if hosts != (parsed.netloc,):
        raise PreflightError("Allowed hosts must equal the one public origin")
    if parsed.scheme == "http":
        _lan_bind(bind)
    return parsed.netloc


def _tls(cert: Path, key: Path, bind: str, runner: Runner) -> str:
    _secret(key, "TLS key")
    if cert.is_symlink() or not cert.is_file() or cert.stat().st_size == 0:
        raise PreflightError("TLS certificate is missing or empty")
    openssl = shutil.which("openssl")
    if openssl is None:
        raise PreflightError("openssl is required to inspect the certificate")
    try:
        completed = runner(
            [openssl, "x509", "-noout", "-checkip", bind, "-in", str(cert)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError("The certificate could not be inspected") from error
    if completed.returncode != 0:
        raise PreflightError("The certificate does not cover the LAN bind address")
    return f"certificate covers {bind}"


def _compose(
    compose: Path,
    lan: Path,
    env: Mapping[str, str],
    bind: str,
    port: str,
    config_dir: Path,
    runner: Runner,
    relay_ip: str = "",
    profile: str = "campaign",
) -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise PreflightError("docker CLI is required for the offline Compose merge")
    command = [
        docker,
        "compose",
        "-f",
        str(compose),
        "-f",
        str(lan),
        "config",
        "--format",
        "json",
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, **env},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError("The Compose merge could not be rendered") from error
    if completed.returncode != 0:
        raise PreflightError("The Compose merge failed (set the required HR_* values)")
    try:
        document = json.loads(completed.stdout)
        service = document["services"]["app"]
        ports = service["ports"]
        volumes = service["volumes"]
        environment = service["environment"]
    except (ValueError, KeyError, TypeError) as error:
        raise PreflightError("The Compose merge has an unexpected structure") from error
    if len(ports) != 1 or ports[0].get("host_ip") != bind or str(ports[0].get("published")) != port:
        raise PreflightError("The LAN merge must publish exactly one approved host address")
    config_mounts = [item for item in volumes if item.get("target") == "/config"]
    owner = profile == "owner"
    if owner:
        network = document.get("networks", {}).get("owner", {})
        if (
            set(service.get("networks", {})) != {"owner"}
            or not isinstance(network, dict)
            or network.get("enable_ipv6") is not False
            or network.get("driver_opts", {}).get("com.docker.network.bridge.name") != "br-hr006"
        ):
            raise PreflightError("Owner merge must use the dedicated guarded IPv4 bridge")
        expected_origin = "https://192.168.1.10:8789"
        if (
            environment.get("HR_PUBLIC_URL") != expected_origin
            or environment.get("HR_ALLOWED_HOSTS") != "192.168.1.10:8789"
            or environment.get("HR_CAMPAIGN_PROFILE")
            or environment.get("HR_LAN_SHARED_CONTROL")
            or environment.get("HR_LAN_BIND")
        ):
            raise PreflightError("Owner merge must publish exactly the one approved origin")
        if not environment.get("AI_PROVIDER") or not str(
            environment.get("AI_CREDENTIAL_FILE", "")
        ).startswith("/config"):
            raise PreflightError("Owner merge must configure the AI credential under /config")
        if len(config_mounts) != 1 or config_mounts[0].get("source") != str(config_dir):
            raise PreflightError("Owner merge must mount the dedicated config directory")
        return f"one host binding {bind}:{port}"
    if relay_ip:
        network = document.get("networks", {}).get("campaign", {})
        if (
            set(service.get("networks", {})) != {"campaign"}
            or not isinstance(network, dict)
            or network.get("enable_ipv6") is not False
            or network.get("driver_opts", {}).get("com.docker.network.bridge.name") != "br-hr005"
        ):
            raise PreflightError("Relayed app must use the dedicated guarded IPv4 bridge")
    if environment.get("HR_CAMPAIGN_PROFILE") != "1" or environment.get("HR_LAN_BIND") != bind:
        raise PreflightError("The LAN merge must select the AI-off campaign profile")
    if env["HR_PUBLIC_URL"].startswith("http://"):
        if (
            environment.get("HR_PUBLIC_URL") != env["HR_PUBLIC_URL"]
            or environment.get("HR_ALLOWED_HOSTS") != env["HR_ALLOWED_HOSTS"]
        ):
            raise PreflightError("Shared HTTP profile origin and Host must match the approved IP")
        if config_mounts or environment.get("HR_LAN_SHARED_CONTROL") != "1":
            raise PreflightError(
                "Shared HTTP profile must omit credentials and enable shared control"
            )
        if any(
            environment.get(key)
            for key in (
                "HR_PASSWORD_FILE",
                "HR_SESSION_KEY_FILE",
                "HR_TLS_CERT_FILE",
                "HR_TLS_KEY_FILE",
            )
        ):
            raise PreflightError("Shared HTTP profile must not configure credential paths")
    elif len(config_mounts) != 1 or config_mounts[0].get("source") != str(config_dir):
        raise PreflightError("The LAN merge must mount the dedicated campaign config directory")
    return f"one host binding {bind}:{port}"


def _bridge(path: Path, expected: Mapping[str, str]) -> str:
    _secret(path, "Bridge configuration")
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise PreflightError("Bridge configuration is not valid JSON") from error
    if not isinstance(document, dict) or set(document) != BRIDGE_KEYS:
        raise PreflightError("Bridge configuration keys differ from the fixed contract")
    for key in ("generation", "container"):
        if not isinstance(document[key], str) or not SAFE_ID.fullmatch(document[key]):
            raise PreflightError(f"Bridge {key} is invalid")
    if not str(document["database"]).startswith("/etc/pihole/") or not str(
        document["database"]
    ).endswith(".db"):
        raise PreflightError("Bridge database is outside the fixed read-only scope")
    if not isinstance(document["identity"], str) or not document["identity"]:
        raise PreflightError("Bridge source identity is required")
    for key in ("python", "compose", "docker"):
        candidate = Path(str(document[key]))
        # uv creates .venv/bin/python as a symlink; no other executable links are allowed.
        venv_python = (
            key == "python"
            and candidate.is_symlink()
            and candidate.name == "python"
            and candidate.parent.name == "bin"
            and candidate.parent.parent.name == ".venv"
            and not any(parent.is_symlink() for parent in candidate.parents)
        )
        if (
            not candidate.is_absolute()
            or not candidate.is_file()
            or (candidate.is_symlink() and not venv_python)
        ):
            raise PreflightError(f"Bridge {key} must be an absolute regular file")
    for key in ("input_dir", "state_dir", "config_dir"):
        if str(document[key]) != expected[key]:
            raise PreflightError(f"Bridge {key} must match the approved private path")
        _private_dir(Path(str(document[key])), f"Bridge {key}")
    return f"generation {document['generation']}"


def _namespace(path: Path, ack_empty: bool) -> str:
    _secret(path, "Namespace file")
    try:
        namespace = load_namespace_list(path.read_bytes())
    except GamingDataError as error:
        raise PreflightError(f"Namespace list is invalid: {error}") from error
    if namespace.state != "available":
        raise PreflightError("Namespace list is unavailable; review it before starting")
    if not namespace.rules and not ack_empty:
        raise PreflightError("Namespace list is empty; review it or acknowledge the empty list")
    return f"revision {namespace.revision}, {len(namespace.rules)} rules"


def _disk(paths: list[Path]) -> str:
    free = min(shutil.disk_usage(path).free for path in paths)
    if free < MIN_FREE_BYTES:
        raise PreflightError("Less than 2 GiB free on a private path")
    return f"{free // 1024**2} MiB free"


def _no_provider(env: Mapping[str, str]) -> str:
    configured = [key for key in PROVIDER_KEYS if env.get(key)]
    if configured:
        raise PreflightError("Provider configuration is present; the campaign profile is AI-off")
    return "no provider configuration"


def _docker_exec(
    docker: str, container: str, args: list[str], runner: Runner
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            [docker, "exec", container, *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError("The bounded resolver check did not run") from error


def _live_container(docker: str, container: str, runner: Runner) -> str:
    try:
        completed = runner(
            [docker, "inspect", "--format", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError("The resolver container could not be inspected") from error
    if completed.returncode != 0 or completed.stdout.strip() != "true":
        raise PreflightError("The resolver container is not running")
    return "container running"


def _live_schema(docker: str, container: str, database: str, runner: Runner) -> tuple[str, str]:
    names = ",".join(f"'{name}'" for name in sorted(QUERY_COLUMNS))
    schema = (
        "PRAGMA query_only=ON; SELECT count(*) FROM pragma_table_info('queries') "
        f"WHERE name IN ({names});"
    )
    completed = _docker_exec(docker, container, ["pihole-FTL", "sqlite3", database, schema], runner)
    if completed.returncode != 0 or completed.stdout.strip() != str(len(QUERY_COLUMNS)):
        raise PreflightError("The FTL query schema is missing required columns")
    counts = _docker_exec(
        docker,
        container,
        [
            "pihole-FTL",
            "sqlite3",
            database,
            "PRAGMA query_only=ON; SELECT count(*), min(timestamp), max(timestamp) FROM queries;",
        ],
        runner,
    )
    if counts.returncode != 0:
        raise PreflightError("The FTL query table could not be read")
    try:
        total, oldest, newest = counts.stdout.strip().split("|")
    except ValueError as error:
        raise PreflightError("The FTL query counts were not readable") from error
    retention = _docker_exec(
        docker, container, ["pihole-FTL", "--config", "database.maxDBdays"], runner
    )
    if retention.returncode != 0 or not retention.stdout.strip():
        raise PreflightError("The FTL retention setting could not be read")
    return (
        f"{int(total)} rows, oldest {oldest or 'none'}, newest {newest or 'none'}",
        f"FTL maxDBdays={retention.stdout.strip()}",
    )


def _live_state(database: Path, generation: str) -> str:
    import sqlite3

    if database.is_symlink() or not database.is_file():
        raise PreflightError("The campaign database is missing")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise PreflightError("The campaign database could not be opened read-only") from error
    try:
        row = connection.execute(
            "SELECT count(*) FROM source_generations WHERE generation_id = ?", (generation,)
        ).fetchone()
        unfinished = connection.execute(
            "SELECT count(*) FROM campaigns WHERE state IN ('active','finalizing')"
        ).fetchone()[0]
    except sqlite3.Error as error:
        raise PreflightError("The campaign database schema is unavailable") from error
    finally:
        connection.close()
    if not row or not row[0]:
        raise PreflightError("The bridge source generation is not registered")
    if unfinished:
        raise PreflightError("A campaign is already active or finalizing")
    return "generation registered, no active campaign"


def run_preflight(
    *,
    mode: str,
    config_dir: Path,
    input_dir: Path,
    state_dir: Path,
    bind: str,
    public_url: str,
    allowed_hosts: str,
    port: str,
    compose: Path,
    lan: Path,
    bridge_config: Path,
    namespace: Path,
    database: Path,
    ack_empty: bool,
    env: Mapping[str, str],
    runner: Runner = subprocess.run,
    relay_ip: str = "",
    profile: str = "campaign",
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def record(name: str, function: Callable[[], str]) -> None:
        try:
            detail = function()
        except PreflightError as error:
            checks.append({"check": name, "ok": False, "detail": str(error)})
        else:
            checks.append({"check": name, "ok": True, "detail": detail})

    record("config directory", lambda: _private_dir(config_dir, "Configuration directory"))
    record("input directory", lambda: _private_dir(input_dir, "Input directory"))
    record("state directory", lambda: _private_dir(state_dir, "State directory"))
    owner = profile == "owner"
    shared = public_url.startswith("http://")
    tls_host = relay_ip if owner and relay_ip else bind
    if not shared:
        record("owner password", lambda: _secret(config_dir / "password", "Owner password"))
        record("session key", lambda: _secret(config_dir / "session-key", "Session key"))
    record("LAN bind", lambda: _lan_bind(bind))
    record(
        "public origin",
        lambda: _origin(public_url, allowed_hosts, bind, port, relay_ip, profile=profile),
    )
    if not shared:
        record(
            "TLS certificate",
            lambda: _tls(
                config_dir / "tls" / "cert.pem",
                config_dir / "tls" / "key.pem",
                tls_host,
                runner,
            ),
        )
    compose_env = {
        "HR_CONFIG_DIR": str(config_dir),
        "HR_CAMPAIGN_CONFIG_DIR": str(config_dir),
        "HR_INPUT_DIR": str(input_dir),
        "HR_STATE_DIR": str(state_dir),
        "HR_LAN_BIND": bind,
        "HR_PORT": port,
        "HR_ALLOWED_HOSTS": allowed_hosts,
        "HR_PUBLIC_URL": public_url,
    }
    record(
        "Compose merge",
        lambda: _compose(
            compose, lan, compose_env, bind, port, config_dir, runner, relay_ip, profile=profile
        ),
    )
    if not owner:
        record(
            "bridge configuration",
            lambda: _bridge(
                bridge_config,
                {
                    "input_dir": str(input_dir),
                    "state_dir": str(state_dir),
                    "config_dir": str(config_dir),
                },
            ),
        )
        record("reviewed namespace", lambda: _namespace(namespace, ack_empty))
        record("disk headroom", lambda: _disk([config_dir, input_dir, state_dir]))
        record("AI-off profile", lambda: _no_provider(env))
    else:
        record("disk headroom", lambda: _disk([config_dir, state_dir]))
    record("timezone", lambda: str(ZoneInfo(os.environ.get("HR_TIMEZONE", "UTC"))))
    if mode == "live":
        docker = shutil.which("docker")
        if docker is None:
            record(
                "resolver container",
                lambda: (_ for _ in ()).throw(PreflightError("docker CLI is required")),
            )
        else:
            bridge = json.loads(bridge_config.read_text())
            record(
                "resolver container",
                lambda: _live_container(docker, str(bridge["container"]), runner),
            )

            def schema() -> str:
                counts, retention = _live_schema(
                    docker, str(bridge["container"]), str(bridge["database"]), runner
                )
                return f"{counts}; {retention}"

            record("FTL schema and retention", schema)
            record(
                "campaign state",
                lambda: _live_state(database, str(bridge["generation"])),
            )
    return {
        "mode": mode,
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }


def main(argv: list[str] | None = None, *, runner: Runner | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--lan-bind", required=True)
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--allowed-hosts", required=True)
    parser.add_argument("--port", default="8787")
    parser.add_argument("--relay-ip", default="", help="explicit approved Proxmox browser relay IP")
    parser.add_argument(
        "--profile",
        choices=("campaign", "owner"),
        default="campaign",
        help="campaign: 8787 LAN publication; owner: 8789 https owner dashboard",
    )
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--lan-compose", type=Path, required=True)
    parser.add_argument("--bridge-config", type=Path, required=True)
    parser.add_argument("--namespace", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--ack-empty", action="store_true")
    args = parser.parse_args(argv)
    result = run_preflight(
        mode=args.mode,
        config_dir=args.config_dir,
        input_dir=args.input_dir,
        state_dir=args.state_dir,
        bind=args.lan_bind,
        public_url=args.public_url,
        allowed_hosts=args.allowed_hosts,
        port=str(args.port),
        compose=args.compose,
        lan=args.lan_compose,
        bridge_config=args.bridge_config,
        namespace=args.namespace,
        database=args.database,
        ack_empty=args.ack_empty,
        env=os.environ,
        runner=runner or subprocess.run,
        relay_ip=args.relay_ip,
        profile=args.profile,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
