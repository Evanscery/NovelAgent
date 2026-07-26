"""Agent package facade -- re-exports the public agent-layer API.

The agent layer is split into focused submodules (agent, registry,
tree_model, workflow, parser, etc.). This module re-exports the
commonly-used public symbols so callers can write
``from app.agents import Agent, AgentRegistry`` without knowing the
internal module layout.
"""
from __future__ import annotations

from app.agents.agent import (
    Agent,
    get_default_tools,
    set_default_tools,
    validate_agent_id,
)
from app.agents.registry import (
    AgentRegistry,
    build_default_registry,
    load_workflow,
)
from app.agents.tree_model import TreeNode, WorkflowTree
from app.agents.workflow import (
    CanvasGraph,
    CanvasNode,
    CanvasWire,
    generate_flow_sequence,
    parse_canvas_to_tree,
)

__all__ = [
    "Agent",
    "AgentRegistry",
    "CanvasGraph",
    "CanvasNode",
    "CanvasWire",
    "TreeNode",
    "WorkflowTree",
    "build_default_registry",
    "generate_flow_sequence",
    "get_default_tools",
    "load_workflow",
    "parse_canvas_to_tree",
    "set_default_tools",
    "validate_agent_id",
]
