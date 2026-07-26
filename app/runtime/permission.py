"""Permission enforcement — apply an agent's Permission to live tool calls.

The permission *definition* (:class:`~app.agents.permission.Permission` and
its parser) is an agent attribute and lives in the agent layer. This module
is the runtime execution side:

* :class:`ScopedTools` wraps a :class:`~app.data.store.ResourceStore` with a
  ``Permission`` and gates every tool call on it.
* 越权访问 reject: when an agent calls a tool for a resource_type its
  permission does not cover, :class:`PermissionDenied` is raised (not a
  silent return).

This module owns no side effects of its own — the actual file reads/writes
happen in :class:`~app.data.store.ResourceStore`, which :class:`ScopedTools`
delegates to *after* the permission check passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.permission import Permission
from app.data.store import ResourceStore

if TYPE_CHECKING:
    from app.data.resource import Resource


class PermissionDenied(Exception):
    """Raised when an agent attempts an action its permission does not cover.

    越权访问 reject: this is a hard exception, never a silent return —
    callers must surface the rejection to the runtime / director so the
    offending tool call is not silently dropped.
    """

    def __init__(self, action: str, resource_type: str, allowed: tuple[str, ...]) -> None:
        self.action = action
        self.resource_type = resource_type
        self.allowed = allowed
        super().__init__(
            f"Permission denied: action={action!r} resource_type={resource_type!r} "
            f"not in allowed={list(allowed)}"
        )


def enforce(permission: Permission, action: str, resource_type: str) -> bool:
    """Pure permission check — return ``True`` if allowed, ``False`` if denied.

    The caller decides whether to raise :class:`PermissionDenied` on a
    ``False`` return. :class:`ScopedTools` does so; other callers may simply
    branch on the boolean.
    """
    return permission.allowed(action, resource_type)


class ScopedTools:
    """Wraps a :class:`ResourceStore` with a :class:`Permission`, enforcing
    scope on every tool call.

    Implements the unified tools: ``read`` / ``write`` / ``list_files`` /
    ``glob_files`` / ``grep_lines`` / ``read_lines``. Each method:

    1. Checks the agent's :class:`Permission` for the requested action and
       resource_type, raising :class:`PermissionDenied` on overreach.
    2. Resolves the resource_type string to a concrete ``Resource`` — the
       store owns the type→path resolution.
    3. Delegates the actual file operation to the wrapped ``ResourceStore``.
    """

    def __init__(self, store: ResourceStore, permission: Permission) -> None:
        self._store = store
        self._permission = permission

    @property
    def permission(self) -> Permission:
        """The frozen permission scope this tool set enforces."""
        return self._permission

    @property
    def store(self) -> ResourceStore:
        """The underlying ``ResourceStore`` (exposed for testing / wrapping)."""
        return self._store

    # ── unified tools: read / write / list_files / glob_files / grep_lines / read_lines ──

    def read(self, resource_type: str, filename: str | None = None) -> str:
        """Read content from a resource, gated by the ``read`` permission.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY`` (e.g. ``"state"``).
            filename: Optional specific file within the resource; ``None``
                reads all content files concatenated.

        Returns:
            The file content (str).

        Raises:
            PermissionDenied: If the permission does not cover ``read`` on
                *resource_type*.
        """
        self._check("read", resource_type)
        resource = self._resolve(resource_type)
        return self._store.read(resource, filename)

    def list_files(self, resource_type: str) -> list[str]:
        """List content files in a resource, gated by the ``read`` permission.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.

        Returns:
            A sorted list of content file names (excluding metadata files).

        Raises:
            PermissionDenied: If the permission does not cover ``read`` on
                *resource_type*.
        """
        self._check("read", resource_type)
        resource = self._resolve(resource_type)
        return self._store.list_files(resource)

    def glob_files(self, resource_type: str, pattern: str) -> list[str]:
        """Glob-match content file names, gated by the ``read`` permission.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            pattern: fnmatch glob pattern.

        Returns:
            A list of matching file names.

        Raises:
            PermissionDenied: If the permission does not cover ``read`` on
                *resource_type*.
        """
        self._check("read", resource_type)
        resource = self._resolve(resource_type)
        return self._store.glob_files(resource, pattern)

    def grep_lines(
        self,
        resource_type: str,
        pattern: str,
        filename: str | None = None,
    ) -> list[tuple[str, int, str]]:
        """Regex search content files, gated by the ``read`` permission.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            pattern: Regex pattern (case-insensitive).
            filename: Optional specific file to search; ``None`` searches all.

        Returns:
            A list of ``(filename, line_number, line_text)`` tuples.

        Raises:
            PermissionDenied: If the permission does not cover ``read`` on
                *resource_type*.
        """
        self._check("read", resource_type)
        resource = self._resolve(resource_type)
        return self._store.grep_lines(resource, pattern, filename)

    def read_lines(self, resource_type: str, filename: str, start: int, end: int) -> str:
        """Read a line range from a file, gated by the ``read`` permission.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            filename: File name within the resource directory.
            start: 1-based start line (inclusive).
            end: 1-based end line (inclusive).

        Returns:
            The selected lines joined by ``\\n``.

        Raises:
            PermissionDenied: If the permission does not cover ``read`` on
                *resource_type*.
        """
        self._check("read", resource_type)
        resource = self._resolve(resource_type)
        return self._store.read_lines(resource, filename, start, end)

    def write(self, resource_type: str, filename: str, content: str) -> bool:
        """Write content to a resource, gated by the ``write`` permission.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            filename: File name within the resource directory.
            content: The text to write.

        Returns:
            ``True`` on success (always — failure surfaces as an exception
            from the store).

        Raises:
            PermissionDenied: If the permission does not cover ``write`` on
                *resource_type*.
        """
        self._check("write", resource_type)
        resource = self._resolve(resource_type)
        self._store.write(resource, filename, content)
        return True

    # ── internals ───────────────────────────────────────────────────────

    def _check(self, action: str, resource_type: str) -> None:
        """Raise :class:`PermissionDenied` unless *action* is permitted."""
        if not self._permission.allowed(action, resource_type):
            allowed = self._permission.rules.get(action, ())
            raise PermissionDenied(action, resource_type, allowed)

    def _resolve(self, resource_type: str) -> Resource:
        """Resolve a resource_type string to its concrete ``Resource``.

        The permission layer only knows resource_type strings; the store
        owns the type→path resolution. If the resource does not yet exist
        in the project, it is scaffolded (mirroring how an agent would
        first touch a resource it has permission on).
        """
        return self._store.create_resource(resource_type, resource_type)


def inject_into_tools(store: ResourceStore, permission: Permission) -> ScopedTools:
    """Create a :class:`ScopedTools` wrapping *store* with *permission*.

    This is the runtime injection point — 将 agent 的 permission 实际映射到
    工具上: the runtime takes an agent's parsed ``permission`` attribute and
    calls this to obtain a scope-gated tool set the agent can use.
    """
    return ScopedTools(store=store, permission=permission)
