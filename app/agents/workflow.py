"""Facade module — re-exports public API from split submodules.

The original monolithic workflow.py (720 lines) has been split into:
- app/canvas/canvas_model.py: CanvasNode, CanvasWire, CanvasGraph (user-facing canvas model)
- tree_model.py: TreeNode, WorkflowTree (parser output tree model)
- canvas_parser.py: parse_canvas_to_tree + private helpers (canvas→tree parser)
- flow_sequence.py: generate_flow_sequence (flow sequence text generator)
- workflow_loader.py: load_workflow + coercion helpers (file loader)

All public symbols are re-exported here so existing imports
``from app.agents.workflow import X`` continue to work.
"""
from __future__ import annotations

from app.canvas.canvas_model import CanvasGraph, CanvasNode, CanvasWire
from app.agents.canvas_parser import parse_canvas_to_tree
from app.agents.flow_sequence import generate_flow_sequence
from app.agents.tree_model import TreeNode, WorkflowTree
from app.agents.workflow_loader import load_workflow

__all__ = [
    "CanvasGraph",
    "CanvasNode",
    "CanvasWire",
    "TreeNode",
    "WorkflowTree",
    "generate_flow_sequence",
    "load_workflow",
    "parse_canvas_to_tree",
]
