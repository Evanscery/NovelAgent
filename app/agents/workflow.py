"""Facade module — the agent layer's workflow API in one import surface.

Re-exports the tree model and the flow-sequence generator. Canvas
compilation and workflow-file loading live in the canvas (user) layer
(:mod:`app.canvas.compile` / :mod:`app.canvas.workflow_loader`) — the
agent layer consumes compiled trees and never imports the canvas package.
"""
from __future__ import annotations

from app.agents.flow_sequence import generate_flow_sequence
from app.agents.tree_model import TreeNode, WorkflowTree

__all__ = [
    "TreeNode",
    "WorkflowTree",
    "generate_flow_sequence",
]
