#!/usr/bin/env python3
"""Build, verify and compare immutable release manifests (offline-safe).

``build`` assembles a manifest from explicit arguments plus narrow local reads:
``git rev-parse``/``git status`` for the source revision and drift flag, a sha256
of ``uv.lock``, base-image digest from the Dockerfile, and a digest over the host
tool bundle. ``verify`` compares the recorded image ID against the deployed
containers. Every subprocess is bounded, uses argument arrays, and prints only
digests, IDs and stage names — never household data or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from household_report.release import (
    ReleaseError,
    ReleaseManifest,
    bundle_digest,
    check_release_pair,
    parse_manifest,
    source_drift,
    verify_host_bundle,
)

TOOLS_DIR = Path(__file__).resolve().parent
HOST_BUNDLE_FILES = (
    "campaign_cli.py",
    "campaign_preflight.py",
    "export_snapshot.py",
    "host_bridge.py",
    "import_inputs.py",
    "poll_presence.py",
    "healthcheck.py",
    "render_bridge_units.py",
)
DOCKERFILE_BASE = re.compile(
    r"^FROM\s+(\S+)@sha256:([0-9a-f]{64})(?:\s+AS\s+(\S+))?\s*$", re.MULTILINE
)


class ManifestToolError(RuntimeError):
    """A bounded local read failed; the detail stays sanitized."""


def _run(command: list[str], *, timeout: float = 30) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ManifestToolError("A bounded local read did not complete") from error
    if result.returncode != 0:
        raise ManifestToolError("A bounded local read failed")
    return result.stdout


def _file_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(part)
    return sha.hexdigest()


def host_bundle() -> dict[str, str]:
    files: dict[str, str] = {}
    for name in HOST_BUNDLE_FILES:
        path = TOOLS_DIR / name
        if path.is_symlink() or not path.is_file():
            raise ManifestToolError(f"Host bundle file is missing: {name}")
        files[name] = _file_digest(path)
    return files


def base_digests(dockerfile: Path) -> dict[str, str]:
    """The pinned builder and runtime base digests declared by the Dockerfile."""
    text = dockerfile.read_text()
    found = {
        stage or f"stage-{index}": digest
        for index, (_, digest, stage) in enumerate(DOCKERFILE_BASE.findall(text))
    }
    if not found:
        raise ManifestToolError("Dockerfile declares no digest-pinned base images")
    return found


def build(args: argparse.Namespace) -> dict[str, object]:
    app_dir = TOOLS_DIR.parent
    revision = _run(["git", "rev-parse", "HEAD"]).strip()
    status = _run(["git", "status", "--porcelain"])
    drift = source_drift(status)
    if drift["dirty"] and not args.allow_dirty:
        raise ManifestToolError(
            "Working tree is dirty; build from a clean selected commit or pass --allow-dirty"
        )
    lock_digest = _file_digest(app_dir / "uv.lock")
    bundle = host_bundle()
    dockerfile = app_dir / "Dockerfile"
    digests = base_digests(dockerfile)
    runtime_digest = digests.get("runtime")
    if runtime_digest is None:
        # The last FROM stage is the runtime image.
        runtime_digest = list(digests.values())[-1]
    manifest = ReleaseManifest(
        image_id=args.image_id,
        source_revision=revision,
        schema_version=args.schema_version,
        lock_sha256=lock_digest,
        base_image_digest=f"sha256:{runtime_digest}",
        host_bundle_sha256=bundle_digest(bundle),
        built_utc=args.built_utc,
        source_dirty=bool(drift["dirty"]),
    )
    document = {
        "manifest_schema": 1,
        **{
            key: value
            for key, value in (
                ("image_id", manifest.image_id),
                ("source_revision", manifest.source_revision),
                ("schema_version", manifest.schema_version),
                ("lock_sha256", manifest.lock_sha256),
                ("base_image_digest", manifest.base_image_digest),
                ("host_bundle_sha256", manifest.host_bundle_sha256),
                ("built_utc", manifest.built_utc),
                ("source_dirty", manifest.source_dirty),
            )
        },
    }
    if args.output:
        output = Path(args.output)
        if output.exists():
            raise ManifestToolError("Refusing to overwrite an existing manifest")
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(document, handle, sort_keys=True, indent=2)
    return document


def verify(args: argparse.Namespace) -> dict[str, object]:
    document = json.loads(Path(args.manifest).read_text())
    manifest = parse_manifest(document)
    verify_host_bundle(manifest.host_bundle_sha256, host_bundle())
    result: dict[str, object] = {
        "fingerprint": manifest.fingerprint(),
        "image_id": manifest.image_id,
        "source_dirty": manifest.source_dirty,
        "host_bundle": "verified",
    }
    if args.shared_image or args.owner_image:
        check_release_pair(
            manifest,
            args.shared_image or manifest.image_id,
            args.owner_image or manifest.image_id,
        )
        result["pair"] = "matching"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="Assemble a manifest from local metadata")
    build_parser.add_argument("--image-id", required=True, help="Built image ID (sha256:...)")
    build_parser.add_argument("--schema-version", type=int, required=True)
    build_parser.add_argument("--built-utc", required=True)
    build_parser.add_argument("--output", help="Write the manifest to this new file")
    build_parser.add_argument("--allow-dirty", action="store_true")
    verify_parser = commands.add_parser("verify", help="Verify a manifest against local inputs")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--shared-image", help="Deployed shared dashboard image ID")
    verify_parser.add_argument("--owner-image", help="Deployed owner dashboard image ID")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args)
        else:
            result = verify(args)
    except (ReleaseError, ManifestToolError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
