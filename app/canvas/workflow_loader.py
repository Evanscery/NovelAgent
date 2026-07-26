"""Workflow file loader (user layer): load_workflow / load_default_workflow.

Loads a :class:`~app.agents.tree_model.WorkflowTree` from a yaml or json
file, accepting either tree-format or canvas-format input. Lives in the
canvas (user) layer because canvas-format acceptance and the default
canvas are user-layer concerns; the agent layer only consumes the
compiled tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.agents.tree_model import WorkflowTree, _coerce_int, _coerce_params_dict
from app.canvas.canvas_model import CanvasGraph, CanvasNode, CanvasWire
from app.canvas.compile import parse_canvas_to_tree


def load_workflow(path: str | Path) -> WorkflowTree:
    """Load a :class:`WorkflowTree` from a yaml or json file.

    Accepts either a **tree-format** file (``{"root_id": ..., "all_nodes": {...}}``,
    the shape produced by :meth:`WorkflowTree.to_dict`) or a **canvas-format** file
    (``{"nodes": [...], "wires": [...]}``); the latter is compiled via
    :func:`parse_canvas_to_tree`.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif p.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        msg = f"load_workflow: unsupported file extension {p.suffix!r}"
        raise ValueError(msg)

    if not isinstance(data, dict):
        msg = f"load_workflow: expected dict at top level, got {type(data).__name__}"
        raise ValueError(msg)

    if "root_id" in data:
        return WorkflowTree.from_dict(data)
    if "nodes" in data and "wires" in data:
        canvas = canvas_from_dict(data)
        return parse_canvas_to_tree(canvas)
    msg = (
        "load_workflow: expected 'root_id' (tree format) or 'nodes'+'wires' "
        "(canvas format) at top level"
    )
    raise ValueError(msg)


def load_default_workflow() -> WorkflowTree:
    """Load the built-in default workflow canvas.

    This is the canvas layer's own resource (``app/canvas/default_workflow.yaml``);
    callers use this entry point instead of reaching into the package
    directory with relative paths.
    """
    return load_workflow(Path(__file__).resolve().parent / "default_workflow.yaml")


def canvas_from_dict(data: dict[str, object]) -> CanvasGraph:
    """Build a :class:`CanvasGraph` from a canvas-format dict (public API for routes)."""
    nodes_data = data.get("nodes", [])
    wires_data = data.get("wires", [])
    if not isinstance(nodes_data, list):
        msg = f"canvas_from_dict: 'nodes' must be a list, got {type(nodes_data).__name__}"
        raise ValueError(msg)
    if not isinstance(wires_data, list):
        msg = f"canvas_from_dict: 'wires' must be a list, got {type(wires_data).__name__}"
        raise ValueError(msg)
    nodes: list[CanvasNode] = []
    for n in nodes_data:
        if not isinstance(n, dict):
            msg = f"canvas_from_dict: node entry must be a dict, got {type(n).__name__}"
            raise ValueError(msg)
        nodes.append(
            CanvasNode(
                id=str(n["id"]),
                agent_name=str(n["agent_name"]),
                description=str(n.get("description", "")),
                params=_coerce_params_dict(n.get("params", {})),
            )
        )
    wires: list[CanvasWire] = []
    for w in wires_data:
        if not isinstance(w, dict):
            msg = f"canvas_from_dict: wire entry must be a dict, got {type(w).__name__}"
            raise ValueError(msg)
        wires.append(
            CanvasWire(
                from_node=str(w["from_node"]),
                to_node=str(w["to_node"]),
                repeat_count=_coerce_int(w.get("repeat_count", 1)),
            )
        )
    return CanvasGraph(nodes=nodes, wires=wires)
