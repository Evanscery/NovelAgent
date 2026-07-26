"""Facade module — the agent layer's workflow API in one import surface.

Re-exports the canvas model, the tree model, the canvas→tree parser, the
flow-sequence generator and the workflow loaders, so callers can use
``from app.agents.workflow import X`` without tracking submodule layout.
"""
from __future__ import annotations

from app.agents.canvas_parser import parse_canvas_to_tree
from app.agents.flow_sequence import generate_flow_sequence
from app.agents.tree_model import TreeNode, WorkflowTree
from app.agents.workflow_loader import load_default_workflow, load_workflow
from app.canvas.canvas_model import CanvasGraph, CanvasNode, CanvasWire

__all__ = [
    "CanvasGraph",
    "CanvasNode",
    "CanvasWire",
    "TreeNode",
    "WorkflowTree",
    "generate_flow_sequence",
    "load_default_workflow",
    "load_workflow",
    "parse_canvas_to_tree",
]
