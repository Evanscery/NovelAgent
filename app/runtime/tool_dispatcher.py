"""Dispatch agent tool calls to the tool surface, reject overreach.

Dispatch is catalog-driven, in order:

1. A :class:`~app.runtime.tool_catalog.ToolCatalog` implementation
   (runtime tools such as ``dice_roll``, plus mounted MCP/imported tools).
2. The permission-scoped ``ScopedTools`` surface (the six storage tools
   ``read`` / ``write`` / ``list_files`` / ``glob_files`` /
   ``grep_lines`` / ``read_lines``).
3. Anything else raises :class:`UnknownToolError` listing the legal names
   — the legacy ``readFile`` / ``readMemory`` style proliferation stays
   forbidden.

The dispatcher does NOT enforce permission itself — that is the job of the
``ScopedTools`` it is handed (produced by ``app.runtime.permission``'s
``inject_into_tools``). A ``PermissionDenied`` raised inside a scoped tool
propagates out of :meth:`ToolDispatcher.dispatch` unchanged so the runtime can
handle it at the appropriate layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.runtime.runners.base import ToolCall

if TYPE_CHECKING:
    from app.runtime.tool_catalog import ToolCatalog

__all__ = [
    "ScopedTools",
    "ToolCall",
    "ToolDispatcher",
    "ToolResult",
    "UnknownToolError",
]


#: The storage-tool methods routed to the ScopedTools surface. This is a
#: routing table (which names map to scoped methods), not a tool
#: allowlist — the tool surface itself is declared by
#: :data:`app.agents.tools.BUILTIN_TOOL_SCHEMAS` / the ToolCatalog.
_SCOPED_TOOL_METHODS: tuple[str, ...] = (
    "read",
    "write",
    "list_files",
    "glob_files",
    "grep_lines",
    "read_lines",
)


@runtime_checkable
class ScopedTools(Protocol):
    """Permission-scoped tool surface the dispatcher delegates to.

    ``app/runtime/permission.py`` produces a concrete ``ScopedTools``
    via ``inject_into_tools``. This Protocol lets the dispatcher be built
    and tested against any object exposing the standardized methods.
    Permission enforcement happens *inside* these methods — a scope
    violation raises ``PermissionDenied`` which propagates through
    :meth:`ToolDispatcher.dispatch`.
    """

    def read(self, **kwargs: object) -> object: ...

    def write(self, **kwargs: object) -> object: ...

    def list_files(self, **kwargs: object) -> object: ...

    def glob_files(self, **kwargs: object) -> object: ...

    def grep_lines(self, **kwargs: object) -> object: ...

    def read_lines(self, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class ToolResult:
    """Outcome of dispatching a :class:`ToolCall`.

    Attributes:
        ok:     ``True`` when the tool ran without raising.
        output: The value returned by the scoped tool (untyped — read returns
                ``str``, list_files/glob_files return ``list[str]``, grep_lines
                returns ``list[tuple]``, read_lines returns ``str``, write
                returns ``bool``). Present when ``ok`` is ``True``.
        error:  Human-readable error message. Empty when ``ok`` is ``True``.
    """

    ok: bool
    output: Any = None
    error: str = ""


class UnknownToolError(Exception):
    """Raised when an agent calls a tool not in the allowed set."""


class ToolDispatcher:
    """Dispatch parsed tool calls to the tool surface.

    The dispatcher is the bridge between an agent's tool calls (parsed
    from the model response by the provider encoder) and the tool
    surface. It owns *routing* (catalog impls first, then the scoped
    storage tools); it owns neither permission enforcement (that is
    ``ScopedTools``' job) nor tool implementation (that is the
    catalog's / ``app.runtime.runtime_tools``'s job).

    Args:
        scoped_tools: The permission-scoped storage-tool surface.
        catalog:      Optional :class:`ToolCatalog`; tools with a catalog
            implementation (e.g. ``dice_roll``, mounted MCP tools) are
            invoked through it, taking precedence over scoped methods.
    """

    def __init__(self, scoped_tools: ScopedTools, catalog: ToolCatalog | None = None) -> None:
        self._tools = scoped_tools
        self._catalog = catalog

    # ── dispatch ───────────────────────────────────────────────────────────

    def dispatch(self, tool_call: ToolCall) -> ToolResult:
        """Route ``tool_call``: catalog impl first, then scoped tools.

        Raises:
            UnknownToolError: if ``tool_call.name`` has neither a catalog
                implementation nor a scoped storage method. The message
                lists the legal tool names.
            PermissionDenied: propagated unchanged from the scoped tool
                when the agent lacks permission.
        """
        name = tool_call.name

        if self._catalog is not None and self._catalog.has_impl(name):
            result = self._catalog.invoke(name, **tool_call.args)
            return ToolResult(ok=True, output=result)

        if name in _SCOPED_TOOL_METHODS:
            method = getattr(self._tools, name)
            result = method(**tool_call.args)
            return ToolResult(ok=True, output=result)

        legal = sorted(
            set(_SCOPED_TOOL_METHODS)
            | (set(self._catalog.impl_names()) if self._catalog is not None else set())
        )
        msg = f"Unknown tool: {name}. Legal tools: {', '.join(legal)}."
        raise UnknownToolError(msg)
