"""Release identity contracts: manifest validation, pair checks and drift."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from household_report.release import (
    MANIFEST_SCHEMA_VERSION,
    ReleaseError,
    ReleaseManifest,
    bundle_digest,
    check_release_pair,
    check_schema_compatibility,
    parse_manifest,
    schema_compatible,
    source_drift,
    verify_host_bundle,
    verify_image_id,
)

TOOLS = Path(__file__).resolve().parents[2] / "tools"
IMAGE = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
LOCK = "c" * 64
BUNDLE = "d" * 64
BASE = "sha256:" + "e" * 64


def manifest(**overrides) -> ReleaseManifest:
    values = {
        "image_id": IMAGE,
        "source_revision": "f" * 40,
        "schema_version": 6,
        "lock_sha256": LOCK,
        "base_image_digest": BASE,
        "host_bundle_sha256": BUNDLE,
        "built_utc": "2026-11-01T00:00:00Z",
    }
    values.update(overrides)
    return ReleaseManifest(**values)


class ManifestTests(unittest.TestCase):
    def test_valid_manifest_fingerprint_is_stable(self):
        first, second = manifest(), manifest()
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertNotEqual(first.fingerprint(), manifest(image_id=OTHER).fingerprint())

    def test_invalid_fields_are_refused(self):
        with self.assertRaises(ReleaseError):
            manifest(image_id="household-report:local")
        with self.assertRaises(ReleaseError):
            manifest(source_revision="not-a-hash")
        with self.assertRaises(ReleaseError):
            manifest(lock_sha256="short")
        with self.assertRaises(ReleaseError):
            manifest(schema_version=0)
        with self.assertRaises(ReleaseError):
            manifest(built_utc="")

    def test_parse_manifest_rejects_unknown_and_missing_fields(self):
        document = json.loads(
            json.dumps(
                {
                    "manifest_schema": MANIFEST_SCHEMA_VERSION,
                    "image_id": IMAGE,
                    "source_revision": "f" * 40,
                    "schema_version": 6,
                    "lock_sha256": LOCK,
                    "base_image_digest": BASE,
                    "host_bundle_sha256": BUNDLE,
                    "built_utc": "2026-11-01T00:00:00Z",
                }
            )
        )
        parsed = parse_manifest(document)
        self.assertEqual(parsed.image_id, IMAGE)
        with self.assertRaises(ReleaseError):
            parse_manifest({**document, "surprise": 1})
        incomplete = dict(document)
        del incomplete["lock_sha256"]
        with self.assertRaises(ReleaseError):
            parse_manifest(incomplete)
        with self.assertRaises(ReleaseError):
            parse_manifest({**document, "manifest_schema": 99})

    def test_tags_are_never_identity(self):
        with self.assertRaises(ReleaseError):
            verify_image_id(IMAGE, "household-report:local")

    def test_mixed_pair_is_refused(self):
        check_release_pair(manifest(), IMAGE, IMAGE)
        with self.assertRaises(ReleaseError):
            check_release_pair(manifest(), IMAGE, OTHER)
        with self.assertRaises(ReleaseError):
            check_release_pair(manifest(), OTHER, IMAGE)


class SchemaTests(unittest.TestCase):
    def test_equal_or_older_schema_is_compatible(self):
        self.assertTrue(schema_compatible(6, 6))
        self.assertTrue(schema_compatible(5, 6))
        self.assertFalse(schema_compatible(7, 6))

    def test_in_place_downgrade_is_refused(self):
        with self.assertRaises(ReleaseError):
            check_schema_compatibility(7, 6)
        check_schema_compatibility(6, 6)


class DriftTests(unittest.TestCase):
    def test_clean_tree(self):
        self.assertEqual(
            source_drift(""),
            {"dirty": False, "modified_tracked": 0, "untracked": 0},
        )

    def test_modified_and_untracked_are_counted_separately(self):
        drift = source_drift(" M src/x.py\n?? notes.md\nM  file\n")
        self.assertTrue(drift["dirty"])
        self.assertEqual(drift["modified_tracked"], 2)
        self.assertEqual(drift["untracked"], 1)


class BundleTests(unittest.TestCase):
    def test_digest_is_order_independent_and_stable(self):
        first = bundle_digest({"a.py": "1" * 64, "b.py": "2" * 64})
        second = bundle_digest({"b.py": "2" * 64, "a.py": "1" * 64})
        self.assertEqual(first, second)
        self.assertNotEqual(first, bundle_digest({"a.py": "3" * 64, "b.py": "2" * 64}))

    def test_bundle_mismatch_is_refused(self):
        verify_host_bundle(bundle_digest({"a.py": "1" * 64}), {"a.py": "1" * 64})
        with self.assertRaises(ReleaseError):
            verify_host_bundle(bundle_digest({"a.py": "1" * 64}), {"a.py": "2" * 64})


class ToolTests(unittest.TestCase):
    """The operator CLI assembles the same contracts from bounded local reads."""

    def load(self):
        spec = importlib.util.spec_from_file_location(
            "household_tool_release_manifest", TOOLS / "release_manifest.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_host_bundle_lists_only_existing_tool_files(self):
        module = self.load()
        module.HOST_BUNDLE_FILES = ("release_manifest.py",)
        files = module.host_bundle()
        self.assertEqual(set(files), {"release_manifest.py"})
        self.assertEqual(len(files["release_manifest.py"]), 64)

    def test_missing_bundle_file_is_refused(self):
        module = self.load()
        module.HOST_BUNDLE_FILES = ("definitely-missing.py",)
        with self.assertRaises(module.ManifestToolError):
            module.host_bundle()

    def test_base_digests_reads_pinned_stages(self):
        module = self.load()
        dockerfile = TOOLS.parent / "Dockerfile"
        digests = module.base_digests(dockerfile)
        self.assertEqual(len(digests), 2)
        for stage, digest in digests.items():
            self.assertIn(stage, {"uv", "runtime"})
            self.assertRegex(digest, r"[0-9a-f]{64}")

    def test_build_refuses_dirty_tree_without_opt_in(self):
        module = self.load()
        args = type(
            "Args",
            (),
            {
                "image_id": IMAGE,
                "schema_version": 6,
                "built_utc": "2026-11-01T00:00:00Z",
                "output": None,
                "allow_dirty": False,
            },
        )()
        original = module._run

        def fake_run(command, *, timeout=30):
            if command[:2] == ["git", "rev-parse"]:
                return "f" * 40 + "\n"
            return " M dirty.py\n"

        module._run = fake_run
        try:
            with self.assertRaises(module.ManifestToolError):
                module.build(args)
        finally:
            module._run = original

    def test_build_produces_a_valid_manifest_document(self):
        module = self.load()
        args = type(
            "Args",
            (),
            {
                "image_id": IMAGE,
                "schema_version": 6,
                "built_utc": "2026-11-01T00:00:00Z",
                "output": None,
                "allow_dirty": False,
            },
        )()
        original = module._run

        def fake_run(command, *, timeout=30):
            if command[:2] == ["git", "rev-parse"]:
                return "f" * 40 + "\n"
            return ""

        module._run = fake_run
        try:
            document = module.build(args)
        finally:
            module._run = original
        parsed = parse_manifest(document)
        self.assertEqual(parsed.image_id, IMAGE)
        self.assertFalse(parsed.source_dirty)


if __name__ == "__main__":
    unittest.main()
