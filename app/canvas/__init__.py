"""Canvas user-layer module (app/canvas/).

The canvas is the user-editable workflow definition: nodes (agent
instantiations) + wires (directed edges). This package holds the
user-facing canvas model, extracted from the original monolithic
``app/agents/workflow.py``.

Importing from the package root:

    from app.canvas import CanvasGraph, CanvasNode, CanvasWire
"""

from __future__ import annotations

from app.canvas.canvas_model import CanvasGraph, CanvasNode, CanvasWire

__all__ = [
    "CanvasGraph",
    "CanvasNode",
    "CanvasWire",
]
