"""Architecture boundaries and the "AI unavailable, reporting still works" rule.

A small AST check, not an architecture-lint framework: it proves the approved
dependency direction at the source level so a later batch cannot quietly wire AI
clients into reporting or SQL into the web layer.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "household_report"

#: Import direction from plan.md. Feature policies never import web/app/inventory
#: clients, and nothing here may import a vendor SDK at module import time.
#: ``settings`` and ``app`` are composition modules: settings reads the approved
#: safety budget from ``analysis`` and app may reach an adapter lazily.
ALLOWED = {
    "contracts": set(),
    "capture_contract": set(),
    "classification": {"contracts"},
    "storage": {"contracts", "capture_contract"},
    "campaign": {"gaming", "storage"},
    "collector_status": set(),
    "campaign_reporting": {"campaign", "gaming", "reporting", "storage"},
    "campaign_retirement": {"storage"},
    "reporting": {"classification", "contracts", "gaming", "storage"},
    "gaming": set(),
    "inventory": {"contracts", "storage"},
    "analysis": {"classification", "contracts", "research", "storage"},
    "research": {"classification"},
    "web": set(),
    "settings": {"analysis", "contracts", "credentials", "operator_config"},
    "credentials": set(),
    "operator_config": set(),
    "release": set(),
    "maintenance": {"release", "storage"},
    "app": {
        "analysis",
        "campaign",
        "campaign_reporting",
        "collector_status",
        "contracts",
        "credentials",
        "integrations",
        "inventory",
        "operator_config",
        "reporting",
        "settings",
        "storage",
        "web",
    },
}

#: The web boundary is allowed a framework; it is still forbidden SQL and vendors.
FORBIDDEN_WEB_IMPORTS = {"sqlite3", "httpx", "requests", "socket", "mcp", "pydantic"}
FORBIDDEN_WEB_RELATIVE = {"storage", "integrations", "analysis", "reporting", "settings"}

#: Adapters talk to vendors; they must not reach into the ledger or the runner.
FORBIDDEN_ADAPTER_IMPORTS = {"analysis", "app", "reporting", "settings", "storage", "web"}

FORBIDDEN_THIRD_PARTY = {
    "fastapi",
    "httpx",
    "jinja2",
    "mcp",
    "pydantic",
    "starlette",
    "uvicorn",
}


def imports_of(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text())
    absolute: set[str] = set()
    relative: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                absolute.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    relative.add(node.module.split(".")[0])
            elif node.module:
                absolute.add(node.module.split(".")[0])
    return absolute, relative


class BoundaryTests(unittest.TestCase):
    def modules(self):
        return {path.stem: path for path in SOURCE.glob("*.py") if path.stem != "__init__"}

    def adapters(self):
        return {
            path.stem: path
            for path in (SOURCE / "integrations").glob("*.py")
            if path.stem != "__init__"
        }

    def test_only_approved_intra_package_imports_exist(self):
        for name, path in self.modules().items():
            _, relative = imports_of(path)
            self.assertLessEqual(
                relative,
                ALLOWED[name],
                f"{name} imports {sorted(relative - ALLOWED[name])} which reverses the approved direction",
            )

    def test_no_vendor_or_web_sdk_is_imported_by_core_modules(self):
        for name, path in self.modules().items():
            if name in {"web", "app"}:
                continue
            absolute, _ = imports_of(path)
            bad = absolute & FORBIDDEN_THIRD_PARTY
            self.assertFalse(bad, f"{name} imports {sorted(bad)} at module import time")

    def test_web_is_a_thin_boundary(self):
        path = self.modules()["web"]
        absolute, relative = imports_of(path)
        self.assertEqual(relative, set(), f"web imports package modules {sorted(relative)}")
        self.assertFalse(
            absolute & FORBIDDEN_WEB_IMPORTS,
            f"web imports {sorted(absolute & FORBIDDEN_WEB_IMPORTS)}",
        )
        self.assertFalse(
            relative & FORBIDDEN_WEB_RELATIVE,
            f"web reaches into {sorted(relative & FORBIDDEN_WEB_RELATIVE)}",
        )
        text = path.read_text()
        for forbidden in ("BEGIN IMMEDIATE", "SELECT ", "INSERT INTO", "Authorization:"):
            self.assertNotIn(forbidden, text, f"web contains database/provider detail: {forbidden}")

    def test_web_loads_no_remote_asset_or_module_level_network_call(self):
        for name in ("web.py",):
            text = (SOURCE / name).read_text()
            self.assertNotIn("https://cdn", text)
            self.assertNotIn("fonts.googleapis", text)
            self.assertNotIn("import socket", text)
            self.assertNotIn("urllib.request", text)

    def test_inventory_never_imports_providers_web_or_analysis(self):
        _, relative = imports_of(self.modules()["inventory"])
        self.assertLessEqual(relative, {"contracts", "storage"})

    def test_adapters_never_import_the_ledger_or_the_runner(self):
        for name, path in self.adapters().items():
            _, relative = imports_of(path)
            bad = relative & FORBIDDEN_ADAPTER_IMPORTS
            self.assertFalse(bad, f"integrations/{name} reaches into {sorted(bad)}")

    def test_adapters_do_not_import_each_other_at_module_level(self):
        for name, path in self.adapters().items():
            _, relative = imports_of(path)
            self.assertNotIn(
                "openai_compatible",
                relative if name != "openai_compatible" else set(),
                f"integrations/{name} imports a sibling adapter",
            )
            self.assertNotIn(
                "exa_mcp",
                relative if name != "exa_mcp" else set(),
                f"integrations/{name} imports a sibling adapter",
            )

    def test_reporting_and_inventory_are_usable_without_ai_integrations(self):
        """Proved in a clean interpreter, so a sibling test cannot mask the result."""
        import subprocess
        import sys

        code = (
            "import sys\n"
            "import household_report.classification\n"
            "import household_report.inventory\n"
            "import household_report.reporting\n"
            "bad = [name for name in ('httpx', 'fastapi', 'mcp', 'pydantic', 'starlette',"
            " 'uvicorn') if name in sys.modules]\n"
            "print(','.join(bad))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        self.assertEqual(
            result.stdout.strip(), "", f"core modules imported {result.stdout.strip()}"
        )

    def test_analysis_is_the_only_module_that_can_dispatch(self):
        text = (SOURCE / "analysis.py").read_text()
        self.assertIn("def dispatch_attempt", text)
        for name in ("reporting.py", "classification.py", "storage.py"):
            self.assertNotIn("dispatch_attempt", (SOURCE / name).read_text())

    def test_no_module_retries_inside_an_adapter(self):
        for name, path in self.adapters().items():
            text = path.read_text()
            self.assertNotIn(
                "for attempt in range", text, f"integrations/{name} retries on its own"
            )


if __name__ == "__main__":
    unittest.main()
