"""Immutable release identity and same-release deployment checks.

A release is identified by the deployed image ID, not a tag: tags are labels. The
manifest records the source revision, locked dependency hash, base image digest,
schema compatibility and host tool-bundle hash that produced it. Both dashboards
must resolve to the same recorded image ID; a mixed pair is never "partially
upgraded success".

Everything here is pure and offline: Docker/Git/subprocess inspection lives in the
operator tool, which feeds validated values into these contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

MANIFEST_SCHEMA_VERSION = 1
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
GIT_REVISION = re.compile(r"[0-9a-f]{7,64}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ReleaseError(ValueError):
    """Release identity is unknown, mixed, drifted or incompatible."""


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """The non-secret identity of one built application release."""

    image_id: str
    source_revision: str
    schema_version: int
    lock_sha256: str
    base_image_digest: str
    host_bundle_sha256: str
    built_utc: str
    source_dirty: bool = False
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not IMAGE_ID.fullmatch(self.image_id):
            raise ReleaseError("image_id must be a sha256 image ID")
        if not GIT_REVISION.fullmatch(self.source_revision):
            raise ReleaseError("source_revision must be a Git commit hash")
        if self.schema_version < 1:
            raise ReleaseError("schema_version must be positive")
        for name, value in (
            ("lock_sha256", self.lock_sha256),
            ("host_bundle_sha256", self.host_bundle_sha256),
        ):
            if not SHA256.fullmatch(value):
                raise ReleaseError(f"{name} must be a sha256 digest")
        if not DIGEST.fullmatch(self.base_image_digest):
            raise ReleaseError("base_image_digest must be a sha256 digest")
        if not self.built_utc:
            raise ReleaseError("built_utc is required")

    def fingerprint(self) -> str:
        """Stable non-secret digest of the manifest itself."""
        payload = {
            "image_id": self.image_id,
            "source_revision": self.source_revision,
            "schema_version": self.schema_version,
            "lock_sha256": self.lock_sha256,
            "base_image_digest": self.base_image_digest,
            "host_bundle_sha256": self.host_bundle_sha256,
            "built_utc": self.built_utc,
            "source_dirty": self.source_dirty,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def parse_manifest(document: Mapping[str, object]) -> ReleaseManifest:
    """Validate a stored manifest document, refusing unknown or missing fields."""
    if not isinstance(document, Mapping):
        raise ReleaseError("Manifest must be a JSON object")
    required = {
        "manifest_schema",
        "image_id",
        "source_revision",
        "schema_version",
        "lock_sha256",
        "base_image_digest",
        "host_bundle_sha256",
        "built_utc",
    }
    missing = required - set(document)
    if missing:
        raise ReleaseError(f"Manifest is missing fields: {sorted(missing)}")
    unknown = set(document) - required - {"labels", "source_dirty"}
    if unknown:
        raise ReleaseError(f"Manifest has unknown fields: {sorted(unknown)}")
    if document["manifest_schema"] != MANIFEST_SCHEMA_VERSION:
        raise ReleaseError("Unsupported manifest schema version")
    labels = document.get("labels") or {}
    if not isinstance(labels, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in labels.items()
    ):
        raise ReleaseError("Manifest labels must be a string mapping")
    return ReleaseManifest(
        image_id=str(document["image_id"]),
        source_revision=str(document["source_revision"]),
        schema_version=int(document["schema_version"]),
        lock_sha256=str(document["lock_sha256"]),
        base_image_digest=str(document["base_image_digest"]),
        host_bundle_sha256=str(document["host_bundle_sha256"]),
        built_utc=str(document["built_utc"]),
        source_dirty=bool(document.get("source_dirty", False)),
        labels=dict(labels),
    )


def verify_image_id(expected: str, actual: str) -> None:
    """The deployed image ID must equal the manifest exactly; tags never count."""
    if expected != actual:
        raise ReleaseError("Deployed image does not match the selected release manifest")


def check_release_pair(manifest: ReleaseManifest, shared_image: str, owner_image: str) -> None:
    """Both dashboards must run the manifest's image; a mixed pair fails closed."""
    if shared_image != manifest.image_id or owner_image != manifest.image_id:
        raise ReleaseError(
            "Deployment images do not match the selected release; "
            "a mixed pair is never accepted as upgraded"
        )


def schema_compatible(manifest_schema: int, application_schema: int) -> bool:
    """An application can open a manifest built for an equal or older schema."""
    return manifest_schema <= application_schema


def check_schema_compatibility(manifest_schema: int, application_schema: int) -> None:
    if not schema_compatible(manifest_schema, application_schema):
        raise ReleaseError(
            "Release expects a newer schema than this application supports; "
            "in-place downgrade is refused"
        )


def source_drift(status_output: str) -> dict[str, object]:
    """Classify `git status --porcelain` output without leaking file content."""
    lines = [line for line in status_output.splitlines() if line.strip()]
    tracked = [line for line in lines if not line.startswith("??")]
    untracked = [line for line in lines if line.startswith("??")]
    return {
        "dirty": bool(lines),
        "modified_tracked": len(tracked),
        "untracked": len(untracked),
    }


def bundle_digest(files: Mapping[str, str]) -> str:
    """Digest a host tool bundle from its sorted name -> sha256 mapping."""
    payload = json.dumps(dict(sorted(files.items())), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_host_bundle(expected_sha256: str, files: Mapping[str, str]) -> None:
    if bundle_digest(files) != expected_sha256:
        raise ReleaseError("Host tool bundle does not match the selected release")
