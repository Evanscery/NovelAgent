"""Parse agent.permission hash<string,vector>, inject into tool scope, enforce.

Per ``docs/refactor_guide.md:77-80``:

* ``permission`` is a ``hash<string, vector>`` — a dict mapping an action
  string (``"read"`` / ``"write"``) to a vector of resource-type names
  (the directory/file names from ``RESOURCE_TYPE_REGISTRY``).
* The parser maintains a mapping (``'data/memory'``) to decouple the
  resource_type name from the actual on-disk path. In this codebase that
  mapping is realised by :class:`~app.data.store.ResourceStore`, which
  resolves a resource_type string to the concrete ``Resource`` (and its
  ``path``) via ``RESOURCE_TYPE_REGISTRY``. The permission layer therefore
  only ever reasons about resource_type strings — never raw paths.
* 越权访问 reject: when an agent calls a tool for a resource_type its
  permission does not cover, :class:`PermissionDenied` is raised (not a
  silent return).

This module is a pure data structure + enforcement layer. It owns no
side effects of its own — the actual file reads/writes happen in
:class:`~app.data.store.ResourceStore`, which :class:`ScopedTools` delegates
to *after* the permission check passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.data.resource_types import RESOURCE_TYPE_REGISTRY
from app.data.store import ResourceStore

if TYPE_CHECKING:
    from app.data.resource import Resource

# Actions recognised by the permission hash. Per refactor_guide:77-80 the
# only standardised tool verbs are ``read`` / ``search`` / ``write`` (guide:120-124),
# and ``search`` is a read op (it does not mutate state), so the permission
# hash itself only needs ``read`` and ``write`` keys.
_VALID_ACTIONS: frozenset[str] = frozenset({"read", "write"})


class PermissionDenied(Exception):
    """Raised when an agent attempts an action its permission does not cover.

    Per refactor_guide:80 — 越权访问 reject.  This is a hard exception, never
    a silent return: callers must surface the rejection to the runtime /
    director so the offending tool call is not silently dropped.
    """

    def __init__(self, action: str, resource_type: str, allowed: tuple[str, ...]) -> None:
        self.action = action
        self.resource_type = resource_type
        self.allowed = allowed
        super().__init__(
            f"Permission denied: action={action!r} resource_type={resource_type!r} "
            f"not in allowed={list(allowed)}"
        )


@dataclass(frozen=True)
class Permission:
    """An agent's permission scope — ``hash<string, vector>``.

    Attributes:
        rules: Mapping from action (``"read"`` / ``"write"``) to the tuple of
            resource_type names that action is allowed on. Tuples (not lists)
            because the dataclass is frozen and the rules must be hashable /
            immutable.
    """

    rules: dict[str, tuple[str, ...]]

    def allowed(self, action: str, resource_type: str) -> bool:
        """True iff *resource_type* is permitted under *action*."""
        return resource_type in self.rules.get(action, ())


def parse_permission(raw: dict[str, object]) -> Permission:
    """Validate and parse a raw permission dict into a :class:`Permission`.

    The raw dict shape is ``{action: [resource_type, ...]}``. Only the
    ``read`` and ``write`` actions are recognised; other keys are rejected
    to surface misconfiguration early rather than silently dropping scope.

    Args:
        raw: The raw permission dict (e.g. ``{'read': ['state', 'memory'],
            'write': ['short_goal']}``).

    Returns:
        A frozen :class:`Permission` with tuple-valued rules.

    Raises:
        TypeError:  If *raw* is not a dict, or a value is not a list, or a
                    list element is not a string.
        ValueError: If an action key is not in ``{"read", "write"}``, or a
                    resource_type is not in ``RESOURCE_TYPE_REGISTRY``.
    """
    if not isinstance(raw, dict):
        msg = f"parse_permission: expected dict, got {type(raw).__name__}"
        raise TypeError(msg)

    rules: dict[str, tuple[str, ...]] = {}
    for action, vector in raw.items():
        if action not in _VALID_ACTIONS:
            msg = (
                f"parse_permission: unknown action {action!r}. "
                f"Valid actions: {sorted(_VALID_ACTIONS)}"
            )
            raise ValueError(msg)
        if not isinstance(vector, list):
            msg = (
                f"parse_permission: value for {action!r} must be a list, "
                f"got {type(vector).__name__}"
            )
            raise TypeError(msg)

        entries: list[str] = []
        for entry in vector:
            if not isinstance(entry, str):
                msg = (
                    f"parse_permission: entry in {action!r} must be a str, "
                    f"got {type(entry).__name__} ({entry!r})"
                )
                raise TypeError(msg)
            if entry not in RESOURCE_TYPE_REGISTRY:
                valid = ", ".join(sorted(RESOURCE_TYPE_REGISTRY))
                msg = (
                    f"parse_permission: unknown resource_type {entry!r} in {action!r}. "
                    f"Valid types: {valid}"
                )
                raise ValueError(msg)
            entries.append(entry)

        rules[action] = tuple(entries)

    return Permission(rules=rules)


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

    Implements the three unified tools from refactor_guide:120-124
    (``read`` / ``search`` / ``write``). Each method:

    1. Checks the agent's :class:`Permission` for the requested action and
       resource_type, raising :class:`PermissionDenied` on overreach.
    2. Resolves the resource_type string to a concrete ``Resource`` (the
       ``'data/memory'`` decoupling mapping from guide:79 — the store owns
       the path resolution).
    3. Delegates the actual file operation to the wrapped ``ResourceStore``.

    The interface intentionally mirrors what todo 16's unified tools layer
    (``app/agents/tools.py``) will expose, so it can wrap or be wrapped by
    that layer without churn.
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

    # ── unified tools: read / search / write ────────────────────────────

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

    def search(self, resource_type: str, query: str) -> list[tuple[str, int, str]]:
        """Grep-style search within a resource, gated by the ``read`` permission.

        ``search`` is a read op (it does not mutate state), so it checks the
        ``read`` scope — there is no separate ``search`` action in the
        permission hash.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            query: Substring to search for (case-insensitive).

        Returns:
            A list of ``(filename, line_number, line_text)`` tuples.

        Raises:
            PermissionDenied: If the permission does not cover ``read`` on
                *resource_type*.
        """
        self._check("read", resource_type)
        resource = self._resolve(resource_type)
        return self._store.search(resource, query)

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

        This is the ``'data/memory'`` decoupling mapping (guide:79): the
        permission layer only knows resource_type strings; the store owns
        the type→path resolution. If the resource does not yet exist in the
        project, it is scaffolded (mirroring how an agent would first
        touch a resource it has permission on).
        """
        return self._store.create_resource(resource_type, resource_type)


def inject_into_tools(store: ResourceStore, permission: Permission) -> ScopedTools:
    """Create a :class:`ScopedTools` wrapping *store* with *permission*.

    This is the runtime injection point described in refactor_guide:137
    ("解析并注入，比如将agent的permission实际映射到工具上去"): the runtime
    parses an agent's ``permission`` attribute via :func:`parse_permission`,
    then calls this to obtain a scope-gated tool set the agent can use.
    """
    return ScopedTools(store=store, permission=permission)
