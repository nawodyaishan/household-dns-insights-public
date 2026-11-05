"""The contributor entry point stays discoverable and offline-safe.

The checks read ``Taskfile.yml`` directly instead of spawning the Task binary, so
the offline suite keeps running with only Python and uv installed. Task names,
variables and defaults are documented there; the help text is the contributor's
first contact with them.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TASKFILE = ROOT / "Taskfile.yml"
TASK_LINE = re.compile(r"^  ([a-z][a-z0-9-]*):$", re.MULTILINE)
HELPER_REFERENCE = re.compile(r"\btask ([a-z][a-z0-9-]*)\b")


def read_taskfile() -> str:
    return TASKFILE.read_text(encoding="utf-8")


def declared_tasks(text: str) -> list[str]:
    return TASK_LINE.findall(text)


def task_block(text: str, name: str) -> str:
    """Return the indented body of one task, without its sibling tasks."""
    lines = text.splitlines()
    start = lines.index(f"  {name}:")
    body = []
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("   ") and line.strip():
            break
        body.append(line)
    return "\n".join(body)


class ContributorHelpTests(unittest.TestCase):
    def test_help_text_names_the_safe_workflow_and_the_gates(self):
        text = read_taskfile()
        self.assertIn("version:", text)
        block = task_block(text, "help-contributors")
        for expected in (
            "task dev-setup",
            "task quality",
            "task check",
            "CONTRIBUTING.md",
            "separate authorization",
        ):
            self.assertIn(expected, block)

    def test_help_text_only_names_declared_tasks(self):
        text = read_taskfile()
        known = set(declared_tasks(text))
        self.assertGreater(len(known), 40)
        referenced = set(HELPER_REFERENCE.findall(task_block(text, "help-contributors")))
        self.assertEqual(referenced - known, set())

    def test_every_task_is_listable(self):
        text = read_taskfile()
        lines = text.splitlines()
        missing = []
        for line in lines:
            name = TASK_LINE.match(line)
            if not name:
                continue
            block = task_block(text, name.group(1))
            if "desc:" not in block:
                missing.append(name.group(1))
        self.assertEqual(missing, [])

    def test_the_offline_gate_is_composed_of_its_parts(self):
        block = task_block(read_taskfile(), "quality")
        for part in ("lock-check", "format-check", "lint", "test-offline"):
            self.assertIn(f"task: {part}", block)


if __name__ == "__main__":
    unittest.main()
