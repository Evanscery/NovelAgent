"""Runtime-layer ToolExecutor — agent-facing tool executor wrapping ScopedTools.

Migrated from ``app/agents/tools.py`` (todo 3 of the layer-violation fix).
The schema metadata (``TOOL_SCHEMAS``, ``TOOL_REGISTRY``, ``ALLOWED_TOOLS``)
stays in the Agent layer at ``app/agents/tools.py``; the executor class
lives here in the Runtime layer because it is runtime execution glue, not
agent-facing schema definition.

The executor holds a :class:`~app.runtime.permission.ScopedTools` (which
wraps a :class:`~app.data.store.ResourceStore` + a
:class:`~app.runtime.permission.Permission`) and exposes the unified tool
methods: ``read``, ``write``, ``list_files``, ``glob_files``,
``grep_lines``, ``read_lines``. Permission enforcement happens *inside*
the wrapped ``ScopedTools`` — this layer adds no permission logic of its
own, it only routes the call.
"""

from __future__ import annotations

from app.runtime.permission import ScopedTools


class ToolExecutor:
    """Agent-facing tool executor wrapping a :class:`ScopedTools`.

    The executor holds a :class:`~app.runtime.permission.ScopedTools`
    (which itself wraps a :class:`~app.data.store.ResourceStore` + a
    :class:`~app.runtime.permission.Permission`) and exposes the unified
    tool methods. The runtime constructs one ``ToolExecutor`` per agent
    per round, injecting the agent's scoped tools.

    Permission enforcement happens *inside* the wrapped ``ScopedTools``
    (a :class:`~app.runtime.permission.PermissionDenied` raised there
    propagates unchanged through this layer). This class adds no permission
    logic of its own — it is the agent-facing executor glue, not a
    re-implementation of the store or the permission gate.

    The methods mirror :meth:`ScopedTools.read` / :meth:`ScopedTools.write`
    / :meth:`ScopedTools.list_files` / :meth:`ScopedTools.glob_files` /
    :meth:`ScopedTools.grep_lines` / :meth:`ScopedTools.read_lines`
    one-for-one so a ``ToolExecutor`` can be used anywhere a ``ScopedTools``
    Protocol is expected (e.g. the
    :class:`~app.runtime.tool_dispatcher.ToolDispatcher`).
    """

    def __init__(self, scoped_tools: ScopedTools) -> None:
        self._scoped = scoped_tools

    @property
    def scoped_tools(self) -> ScopedTools:
        """The wrapped permission-scoped tool surface (exposed for wrapping/testing)."""
        return self._scoped

    # -- unified tools: read / write / list_files / glob_files / grep_lines / read_lines --

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

    def list_files(self, resource_type: str) -> list[str]:
        """List content files in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.

        Returns:
            A sorted list of content file names (excluding metadata files).

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.list_files(resource_type)

    def glob_files(self, resource_type: str, pattern: str) -> list[str]:
        """Glob-match content file names in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            pattern: fnmatch glob pattern.

        Returns:
            A list of matching file names.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.glob_files(resource_type, pattern)

    def grep_lines(
        self,
        resource_type: str,
        pattern: str,
        filename: str | None = None,
    ) -> list[tuple[str, int, str]]:
        """Regex search content files in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            pattern: Regex pattern to match.
            filename: Optional specific file to search; ``None`` searches all.

        Returns:
            A list of ``(filename, line_number, line_text)`` tuples.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.grep_lines(resource_type, pattern, filename)

    def read_lines(self, resource_type: str, filename: str, start: int, end: int) -> str:
        """Read a line range from a file in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            filename: File name within the resource directory.
            start: 1-based start line (inclusive).
            end: 1-based end line (inclusive).

        Returns:
            The selected lines joined by ``\\n``.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.read_lines(resource_type, filename, start, end)

    def write(self, resource_type: str, filename: str, content: str) -> bool:
        """Write content to a resource.

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
