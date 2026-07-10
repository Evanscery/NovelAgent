"""Unified tool schema metadata — read/write + file I/O tools.

Per ``docs/refactor_guide.md:112-123`` the standardized tool surface is a
small set of unified tools. This module owns the **schema metadata** for
the dispatcher / parser / agent prompt assembly:

- :data:`TOOL_REGISTRY` — name -> name mapping (the executor class lives in
  the Runtime layer at :mod:`app.runtime.tool_executor`)
- :data:`TOOL_SCHEMAS` — per-tool ``{"name", "args", "returns"}`` schema
- :func:`get_tool_schema` — lookup
- :func:`list_available_tools` — canonical tool name list

The :class:`ToolExecutor` class has been migrated to
:mod:`app.runtime.tool_executor` (Runtime layer). This module no longer
imports from :mod:`app.data.store` or :mod:`app.runtime.permission` — it
is pure schema metadata with no execution concerns.
"""

from __future__ import annotations

from typing import Protocol, TypeAlias, runtime_checkable

__all__ = [
    "ALLOWED_TOOLS",
    "TOOL_REGISTRY",
    "TOOL_SCHEMAS",
    "ToolFunc",
    "ToolSchema",
    "get_tool_schema",
    "list_available_tools",
]

# The standardized tool surface. Per refactor_guide:113-118 NO other tool
# names are permitted — readFile / readMemory / readLore etc. are forbidden.
# This frozenset is the single source of truth for "what tools exist".
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {"read", "write", "list_files", "glob_files", "grep_lines", "read_lines"}
)


# -- Schemas -----------------------------------------------------------------


ToolSchema: TypeAlias = dict[str, object]
"""Type alias for a tool's schema dict: ``{"name", "args", "returns"}``."""


TOOL_SCHEMAS: dict[str, ToolSchema] = {
    "read": {
        "name": "read",
        "args": {"resource_type": "str", "filename": "str | None"},
        "returns": "str",
    },
    "write": {
        "name": "write",
        "args": {
            "resource_type": "str",
            "filename": "str",
            "content": "str",
        },
        "returns": "bool",
    },
    "list_files": {
        "name": "list_files",
        "args": {"resource_type": "str"},
        "returns": "list[str]",
    },
    "glob_files": {
        "name": "glob_files",
        "args": {"resource_type": "str", "pattern": "str"},
        "returns": "list[str]",
    },
    "grep_lines": {
        "name": "grep_lines",
        "args": {"resource_type": "str", "pattern": "str", "filename": "str | None"},
        "returns": "list[tuple[str, int, str]]",
    },
    "read_lines": {
        "name": "read_lines",
        "args": {"resource_type": "str", "filename": "str", "start": "int", "end": "int"},
        "returns": "str",
    },
}


def get_tool_schema(name: str) -> ToolSchema:
    """Return the schema dict for tool *name*.

    Args:
        name: One of the allowed tool names (see :data:`ALLOWED_TOOLS`).

    Returns:
        The schema dict ``{"name", "args", "returns"}``.

    Raises:
        KeyError: If *name* is not one of the allowed tools. This is a
            hard error (not a silent ``None`` return) to surface misconfiguration
            early -- per refactor_guide:113-118 only the unified names
            are valid.
    """
    if name not in TOOL_SCHEMAS:
        valid = ", ".join(sorted(TOOL_SCHEMAS))
        msg = f"Unknown tool: {name!r}. Valid tools: {valid}"
        raise KeyError(msg)
    return TOOL_SCHEMAS[name]


def list_available_tools() -> list[str]:
    """Return the names of the unified tools, in canonical order.

    The order matches :data:`app.agents.agent._DEFAULT_TOOLS` and the order
    the tools are presented to agents in their prompt.
    """
    return ["read", "list_files", "glob_files", "grep_lines", "read_lines", "write"]


# -- ToolFunc Protocol -------------------------------------------------------


@runtime_checkable
class ToolFunc(Protocol):
    """Structural type for the tool methods on :class:`ToolExecutor`.

    Each tool takes its named arguments as keyword args and returns the
    result type declared in :data:`TOOL_SCHEMAS`. The Protocol is
    intentionally loose (``**kwargs: object`` -> ``object``) so the
    dispatcher can call any of them uniformly via ``getattr``; the precise
    per-tool signature is declared on :class:`ToolExecutor`'s methods
    (in :mod:`app.runtime.tool_executor`) and in :data:`TOOL_SCHEMAS`.
    """

    def __call__(self, **kwargs: object) -> object: ...


# -- TOOL_REGISTRY -----------------------------------------------------------
#
# Maps tool name -> tool name (identity mapping). The executor class
# (:class:`app.runtime.tool_executor.ToolExecutor`) lives in the Runtime
# layer and is constructed per agent per round with an injected
# ScopedTools. The registry validates that a parsed tool name is one of
# the allowed tools; actual invocation goes through a concrete
# ``ToolExecutor`` instance.
TOOL_REGISTRY: dict[str, str] = {
    "read": "read",
    "write": "write",
    "list_files": "list_files",
    "glob_files": "glob_files",
    "grep_lines": "grep_lines",
    "read_lines": "read_lines",
}
