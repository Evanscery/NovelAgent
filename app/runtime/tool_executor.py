"""Runtime-layer ToolExecutor — agent-facing tool executor wrapping ScopedTools.

Migrated from ``app/agents/tools.py`` (todo 3 of the layer-violation fix).
The schema metadata (``TOOL_SCHEMAS``, ``TOOL_REGISTRY``, ``ALLOWED_TOOLS``)
stays in the Agent layer at ``app/agents/tools.py``; the executor class
lives here in the Runtime layer because it is runtime execution glue, not
agent-facing schema definition.

The executor holds a :class:`~app.runtime.permission.ScopedTools` (which
wraps a :class:`~app.data.store.ResourceStore` + a
:class:`~app.runtime.permission.Permission`) and exposes the unified tool
methods. Permission enforcement happens *inside* the wrapped
``ScopedTools`` — this layer adds no permission logic of its own, it only
routes the call.
"""

from __future__ import annotations

from app.runtime.permission import ScopedTools


class ToolExecutor:
    """Agent-facing tool executor wrapping a :class:`ScopedTools`.

    Per the todo 16 design choice (b): the executor holds a
    :class:`~app.runtime.permission.ScopedTools` (which itself wraps a
    :class:`~app.data.store.ResourceStore` + a
    :class:`~app.runtime.permission.Permission`) and exposes the unified
    tool methods. The runtime constructs one ``ToolExecutor`` per
    agent per round, injecting the agent's scoped tools.

    Permission enforcement happens *inside* the wrapped ``ScopedTools``
    (a :class:`~app.runtime.permission.PermissionDenied` raised there
    propagates unchanged through this layer). This class adds no permission
    logic of its own — it is the agent-facing executor glue, not a
    re-implementation of the store or the permission gate.

    The methods mirror :meth:`ScopedTools.read` / :meth:`ScopedTools.search`
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

    def search(self, resource_type: str, query: str) -> list[tuple[str, int, str]]:
        """Grep-style search within a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            query: Substring to search for (case-insensitive).

        Returns:
            A list of ``(filename, line_number, line_text)`` tuples.

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
