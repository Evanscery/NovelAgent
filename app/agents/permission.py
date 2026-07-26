"""Agent permission definition — ``hash<string, vector>`` model + parser.

Permission is an *agent attribute*: each agent declares which resource types
it may ``read`` / ``write``. This module owns the definition and validation
of that attribute only. Enforcement (checking a live tool call against a
permission and rejecting overreach) is a runtime concern and lives in
``app.runtime.permission``.

* ``permission`` is a ``hash<string, vector>`` — a dict mapping an action
  string (``"read"`` / ``"write"``) to a vector of resource-type names
  (the directory/file names from ``RESOURCE_TYPE_REGISTRY``).
* The permission layer only ever reasons about resource_type strings —
  never raw paths. The type→path resolution belongs to the data layer
  (``app.data.store.ResourceStore``).

This module must not import from ``app.runtime`` — the agent layer defines
intent; the runtime executes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.resource_types import RESOURCE_TYPE_REGISTRY

# Actions recognised by the permission hash. The only standardised tool
# verbs are ``read`` / ``write`` (the file I/O tools ``list_files`` /
# ``glob_files`` / ``grep_lines`` / ``read_lines`` are all read ops), so
# the permission hash itself only needs ``read`` and ``write`` keys.
_VALID_ACTIONS: frozenset[str] = frozenset({"read", "write"})


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
