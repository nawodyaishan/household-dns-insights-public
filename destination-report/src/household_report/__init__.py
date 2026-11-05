"""Household destination reporting: local evidence, explicit and bounded research.

Feature modules:

- :mod:`household_report.reporting` — preserved observations, periods, coverage and
  report assembly.
- :mod:`household_report.classification` — cache resolution, disclosure privacy and
  grounding validation (pure policy).
- :mod:`household_report.analysis` — explicit jobs, the single dispatch gate, ledger
  budgets and local summaries.
- :mod:`household_report.storage` — the one SQLite implementation.

AI and research are never required for ordinary reporting: these modules import
without a web framework, an HTTP client or an MCP SDK.
"""

__version__ = "0.1.0"
