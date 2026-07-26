"""Workflow loader: load_workflow + coercion helpers.

Loads a :class:`~app.agents.tree_model.WorkflowTree` from a yaml or json
file, accepting either tree-format or canvas-format input.

Extracted from the original monolithic ``workflow.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.agents.canvas_parser import parse_canvas_to_tree
from app.agents.tree_model import WorkflowTree
from app.canvas.canvas_model import CanvasGraph, CanvasNode, CanvasWire


def load_workflow(path: str | Path) -> WorkflowTree:
    """Load a :class:`WorkflowTree` from a yaml or json file.

    Accepts either a **tree-format** file (``{"root_id": ..., "all_nodes": {...}}``,
    produced by :meth:`WorkflowTree.save`) or a **canvas-format** file
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
        canvas = _canvas_from_dict(data)
        return parse_canvas_to_tree(canvas)
    msg = (
        "load_workflow: expected 'root_id' (tree format) or 'nodes'+'wires' "
        "(canvas format) at top level"
    )
    raise ValueError(msg)


def _canvas_from_dict(data: dict[str, object]) -> CanvasGraph:
    """Build a :class:`CanvasGraph` from a canvas-format dict."""
    nodes_data = data.get("nodes", [])
    wires_data = data.get("wires", [])
    if not isinstance(nodes_data, list):
        msg = f"_canvas_from_dict: 'nodes' must be a list, got {type(nodes_data).__name__}"
        raise ValueError(msg)
    if not isinstance(wires_data, list):
        msg = f"_canvas_from_dict: 'wires' must be a list, got {type(wires_data).__name__}"
        raise ValueError(msg)
    nodes: list[CanvasNode] = []
    for n in nodes_data:
        if not isinstance(n, dict):
            msg = f"_canvas_from_dict: node entry must be a dict, got {type(n).__name__}"
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
            msg = f"_canvas_from_dict: wire entry must be a dict, got {type(w).__name__}"
            raise ValueError(msg)
        wires.append(
            CanvasWire(
                from_node=str(w["from_node"]),
                to_node=str(w["to_node"]),
                repeat_count=_coerce_int(w.get("repeat_count", 1)),
            )
        )
    return CanvasGraph(nodes=nodes, wires=wires)


def _coerce_params_dict(raw: object) -> dict[str, object]:
    """Coerce a raw params value into ``dict[str, object]``.

    The params dict is heterogeneous (user-supplied values can be str /
    int / float / bool / None / nested dict), so ``object`` is the value
    type. This helper validates the outer shape (must be a dict).
    """
    if not isinstance(raw, dict):
        msg = f"_coerce_params_dict: expected dict, got {type(raw).__name__}"
        raise TypeError(msg)
    result: dict[str, object] = {}
    for k, v in raw.items():
        result[str(k)] = v
    return result


def _coerce_str_list(raw: object) -> list[str]:
    """Coerce a raw list value into ``list[str]`` with isinstance narrowing."""
    if not isinstance(raw, list):
        msg = f"_coerce_str_list: expected list, got {type(raw).__name__}"
        raise TypeError(msg)
    return [str(x) for x in raw]


def _coerce_int(raw: object) -> int:
    """Coerce a raw value into ``int`` with isinstance narrowing."""
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    msg = f"_coerce_int: expected int-like, got {type(raw).__name__}"
    raise TypeError(msg)
