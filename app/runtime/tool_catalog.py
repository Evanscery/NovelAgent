"""Runtime tool catalog — schemas + implementations, one lookup surface.

The :class:`ToolCatalog` binds the agent layer's declarative
:data:`~app.agents.tools.BUILTIN_TOOL_SCHEMAS` to runtime
implementations. Three kinds of tools live side by side:

* **Storage tools** (``read`` / ``write`` / ...): schema only — their
  execution goes through the per-agent permission-scoped ``ScopedTools``
  surface, so the catalog carries no impl for them.
* **Director tools** (``call_agent`` / ``await`` / ``finalize``): schema
  only — the round executor dispatches them itself.
* **Runtime tools** (``dice_roll``): schema + impl; invoked directly via
  :meth:`ToolCatalog.invoke`.

MCP / imported tools plug in at runtime via :meth:`ToolCatalog.register`
(see :func:`app.runtime.mcp.load_mcp_tools`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence

from app.agents.tools import BUILTIN_TOOL_SCHEMAS, ToolSchema
from app.runtime.runtime_tools import dice_roll

logger = logging.getLogger(__name__)

__all__ = [
    "ToolCatalog",
    "ToolImpl",
    "build_default_catalog",
]

#: A tool implementation: keyword arguments in, JSON-compatible value out.
ToolImpl = Callable[..., object]


class ToolCatalog:
    """Lookup surface for tool schemas and (optional) implementations.

    Args:
        schemas: Tool name -> :class:`ToolSchema`. The prompt builder
            resolves agent tool lists against this.
        impls:   Tool name -> callable, for tools the runtime executes
            directly (as opposed to storage tools dispatched through
            ``ScopedTools`` and director tools handled by the executor).
    """

    def __init__(
        self,
        schemas: Mapping[str, ToolSchema],
        impls: Mapping[str, ToolImpl] | None = None,
    ) -> None:
        self._schemas: dict[str, ToolSchema] = dict(schemas)
        self._impls: dict[str, ToolImpl] = dict(impls) if impls is not None else {}

    def schemas_for(self, names: Sequence[str]) -> list[ToolSchema]:
        """Resolve *names* to schemas, skipping unknown names with a warning.

        An agent config naming a tool this runtime does not know must not
        break the round — the name is dropped from the advertised tool
        surface instead.
        """
        schemas: list[ToolSchema] = []
        for name in names:
            schema = self._schemas.get(name)
            if schema is None:
                logger.warning("ToolCatalog: unknown tool %r skipped", name)
                continue
            schemas.append(schema)
        return schemas

    def has(self, name: str) -> bool:
        """True if a schema is registered under *name*."""
        return name in self._schemas

    def has_impl(self, name: str) -> bool:
        """True if the catalog can :meth:`invoke` *name* directly."""
        return name in self._impls

    def invoke(self, name: str, **kwargs: object) -> object:
        """Invoke the implementation registered under *name*.

        Raises:
            KeyError: If no implementation is registered under *name*
                (schema-only tools are dispatched elsewhere).
        """
        if name not in self._impls:
            msg = f"ToolCatalog: no implementation registered for tool {name!r}"
            raise KeyError(msg)
        return self._impls[name](**kwargs)

    def register(self, schema: ToolSchema, impl: ToolImpl | None = None) -> None:
        """Register (or replace) a tool schema, optionally with an impl.

        This is the runtime mount point for imported / MCP tools.
        """
        self._schemas[schema.name] = schema
        if impl is not None:
            self._impls[schema.name] = impl

    def impl_names(self) -> list[str]:
        """Sorted names of tools with a registered implementation."""
        return sorted(self._impls)


def build_default_catalog() -> ToolCatalog:
    """Build the default catalog: all builtin schemas + runtime impls.

    Only ``dice_roll`` carries an implementation — storage tools execute
    through ``ScopedTools`` and director tools are executor-owned, so
    both are schema-only here.
    """
    return ToolCatalog(
        schemas=BUILTIN_TOOL_SCHEMAS,
        impls={"dice_roll": dice_roll},
    )
