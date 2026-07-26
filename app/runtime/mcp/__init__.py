"""MCP (Model Context Protocol) tool loading — the external-tools seam.

External MCP servers are, from the runtime's point of view, just another
source of tools: each server tool becomes a
:class:`~app.agents.tools.ToolSchema` (+ invoker) registered into the
round's :class:`~app.runtime.tool_catalog.ToolCatalog`.

Only the loader seam exists today: :func:`load_mcp_tools` is called by
the session factory with the (currently empty) MCP config and registers
nothing. When a real MCP client lands, it plugs in here — no session or
catalog changes required.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.runtime.tool_catalog import ToolCatalog

__all__ = ["load_mcp_tools"]


def load_mcp_tools(catalog: ToolCatalog, config: Mapping[str, object] | None = None) -> list[str]:
    """Register tools from configured MCP servers into *catalog*.

    Args:
        catalog: The round's tool catalog to register into.
        config:  MCP configuration; the ``"servers"`` entry lists server
            configs. ``None`` / empty / no servers registers nothing.

    Returns:
        The names of the tools registered (empty today).

    Raises:
        NotImplementedError: If servers ARE configured — the MCP client
            is not implemented yet, and silently ignoring configured
            servers would hide the gap.
    """
    if not config:
        return []
    servers = config.get("servers")
    if not servers:
        return []
    msg = "MCP servers are configured but the MCP client is not implemented yet"
    raise NotImplementedError(msg)
