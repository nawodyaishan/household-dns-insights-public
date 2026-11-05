"""Provider and evidence adapters, one module per external boundary.

Adapters own wire formats and error normalization. They never retry, never read a
credential from a request and never decide eligibility or grounding. The MCP SDK and
HTTP clients are constructed by the composition root with operator configuration.
"""

from __future__ import annotations

__all__ = ["exa_mcp", "openai_compatible"]
