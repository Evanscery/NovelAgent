"""Unified tools: read(resource)/search(resource)/write(resource) — NO proliferation.

Per ``docs/refactor_guide.md:112-123`` the standardized tool surface is exactly
three tools — ``read(resource)``, ``search(resource)``, ``write(resource)``.
The legacy ``readFile`` / ``readMemory`` / ``readLore`` style proliferation is
forbidden (guide:113-118); this module deliberately defines ONLY the three
unified tool names and nothing else.

This module owns **two concerns**:

1. **Schema metadata** for the dispatcher / parser / agent prompt assembly:
   - :data:`TOOL_REGISTRY` — name → function mapping
   - :data:`TOOL_SCHEMAS` — per-tool ``{"name", "args", "returns"}`` schema
   - :func:`get_tool_schema` — lookup
   - :func:`list_available_tools` — ``["read", "search", "write"]``

2. **Agent-facing executor** — :class:`ToolExecutor` holds a
   :class:`~app.runtime.permission.ScopedTools` (which wraps a
   :class:`~app.data.store.ResourceStore` + a
   :class:`~app.runtime.permission.Permission`) and exposes the three
   unified tool methods. Permission enforcement happens *inside* the
   wrapped ``ScopedTools`` (guide:80 越权访问 reject) — this layer adds
   no permission logic of its own, it only routes the call.

The actual file I/O (and grep-style search) lives in
:class:`~app.data.store.ResourceStore`; the permission gate lives in
:class:`~app.runtime.permission.ScopedTools`; the agent-facing schema +
executor glue lives here. Three layers, three responsibilities, one
unified tool surface.
"""

from __future__ import annotations

from typing import Protocol, TypeAlias, cast, runtime_checkable

from app.data.store import SearchHit
from app.runtime.permission import ScopedTools

__all__ = [
    "TOOL_REGISTRY",
    "TOOL_SCHEMAS",
    "ToolExecutor",
    "ToolFunc",
    "get_tool_schema",
    "list_available_tools",
]

# The standardized tool surface. Per refactor_guide:113-118 NO other tool
# names are permitted — readFile / readMemory / readLore etc. are forbidden.
# This frozenset is the single source of truth for "what tools exist".
ALLOWED_TOOLS: frozenset[str] = frozenset({"read", "search", "write"})


# ── Schemas ────────────────────────────────────────────────────────────────


ToolSchema: TypeAlias = dict[str, object]
"""Type alias for a tool's schema dict: ``{"name", "args", "returns"}``."""


TOOL_SCHEMAS: dict[str, ToolSchema] = {
    "read": {
        "name": "read",
        "args": {"resource_type": "str", "filename": "str | None"},
        "returns": "str",
    },
    "search": {
        "name": "search",
        "args": {"resource_type": "str", "query": "str"},
        "returns": "list[SearchHit]",
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
}


def get_tool_schema(name: str) -> ToolSchema:
    """Return the schema dict for tool *name*.

    Args:
        name: One of ``"read"``, ``"search"``, ``"write"``.

    Returns:
        The schema dict ``{"name", "args", "returns"}``.

    Raises:
        KeyError: If *name* is not one of the three allowed tools. This is a
            hard error (not a silent ``None`` return) to surface misconfiguration
            early — per refactor_guide:113-118 only the three unified names
            are valid.
    """
    if name not in TOOL_SCHEMAS:
        valid = ", ".join(sorted(TOOL_SCHEMAS))
        msg = f"Unknown tool: {name!r}. Valid tools: {valid}"
        raise KeyError(msg)
    return TOOL_SCHEMAS[name]


def list_available_tools() -> list[str]:
    """Return the names of the three unified tools, in canonical order.

    The order is ``["read", "search", "write"]`` — matching
    :data:`app.agents.agent._DEFAULT_TOOLS` and the order the tools are
    presented to agents in their prompt.
    """
    return ["read", "search", "write"]


# ── ToolFunc Protocol ──────────────────────────────────────────────────────


@runtime_checkable
class ToolFunc(Protocol):
    """Structural type for the three tool methods on :class:`ToolExecutor`.

    Each tool takes its named arguments as keyword args and returns either
    ``str`` (read), ``list[SearchHit]`` (search), or ``bool`` (write). The
    Protocol is intentionally loose (``**kwargs: object`` → ``object``) so
    the dispatcher can call any of them uniformly via ``getattr``; the
    precise per-tool signature is declared on :class:`ToolExecutor`'s methods
    and in :data:`TOOL_SCHEMAS`.
    """

    def __call__(self, **kwargs: object) -> object: ...


# ── ToolExecutor ───────────────────────────────────────────────────────────


class ToolExecutor:
    """Agent-facing tool executor wrapping a :class:`ScopedTools`.

    Per the todo 16 design choice (b): the executor holds a
    :class:`~app.runtime.permission.ScopedTools` (which itself wraps a
    :class:`~app.data.store.ResourceStore` + a
    :class:`~app.runtime.permission.Permission`) and exposes the three
    unified tool methods. The runtime constructs one ``ToolExecutor`` per
    agent per round, injecting the agent's scoped tools.

    Permission enforcement happens *inside* the wrapped ``ScopedTools``
    (a :class:`~app.runtime.permission.PermissionDenied` raised there
    propagates unchanged through this layer). This class adds no permission
    logic of its own — it is the agent-facing schema/executor glue, not a
    re-implementation of the store or the permission gate.

    The three methods mirror :meth:`ScopedTools.read` / :meth:`ScopedTools.search`
    / :meth:`ScopedTools.write` one-for-one so a ``ToolExecutor`` can be
    used anywhere a ``ScopedTools`` Protocol is expected (e.g. the
    :class:`~app.runtime.tool_dispatcher.ToolDispatcher`).
    """

    def __init__(self, scoped_tools: ScopedTools) -> None:
        self._scoped = scoped_tools

    @property
    def scoped_tools(self) -> ScopedTools:
        """The wrapped permission-scoped tool surface (exposed for wrapping/testing)."""
        return self._scoped

    # ── unified tools: read / search / write ────────────────────────────

    def read(self, resource_type: str, filename: str | None = None) -> str:
        """Read content from a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY`` (e.g. ``"state"``).
            filename: Optional specific file within the resource; ``None``
                reads all content files concatenated.

        Returns:
            The file content (str).

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.read(resource_type, filename)

    def search(self, resource_type: str, query: str) -> list[SearchHit]:
        """Grep-style search within a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            query: Substring to search for (case-insensitive).

        Returns:
            A list of :class:`~app.data.store.SearchHit`.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (search is a read op).
        """
        return self._scoped.search(resource_type, query)

    def write(self, resource_type: str, filename: str, content: str) -> bool:
        """Write content to a resource, maintaining the index.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            filename: File name within the resource directory.
            content: The text to write.

        Returns:
            ``True`` on success.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``write`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.write(resource_type, filename, content)


# ── TOOL_REGISTRY ──────────────────────────────────────────────────────────
#
# Maps tool name → bound method. We cannot bind methods on a *specific*
# ToolExecutor instance at module import time (the executor is constructed
# per agent per round with an injected ScopedTools), so the registry holds
# the *unbound* tool functions — i.e. :meth:`ToolExecutor.read` /
# :meth:`ToolExecutor.search` / :meth:`ToolExecutor.write`. The dispatcher
# uses the registry to (a) validate a parsed tool name is one of the three
# allowed, and (b) look up the function for schema introspection. Actual
# invocation goes through a concrete ``ToolExecutor`` instance.
TOOL_REGISTRY: dict[str, ToolFunc] = {
    "read": cast(ToolFunc, ToolExecutor.read),
    "search": cast(ToolFunc, ToolExecutor.search),
    "write": cast(ToolFunc, ToolExecutor.write),
}
