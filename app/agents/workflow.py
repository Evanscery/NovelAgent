"""Canvas → Tree workflow model, parser, and flow-sequence generator.

This module realises the **AST-like tree** workflow design (todo 18 / plan
scope item 3, NEW tree-based design replacing the old DAG design).

The pipeline is:

1. **User canvas** — :class:`CanvasGraph` with :class:`CanvasNode` +
   :class:`CanvasWire`. The canvas is strictly acyclic *except* for
   **feedback wires**: a feedback wire is a REVERSE edge
   (``from_node=refiner, to_node=critics, repeat_count=5``). Non-feedback
   wires (``repeat_count == 1``) form a DAG; feedback wires
   (``repeat_count > 1``) are back-edges excluded from the topological sort.
   :meth:`CanvasGraph.validate` does a topological sort excluding feedback
   wires and verifies each feedback wire is a genuine back-edge (its target
   is topologically before its source).

2. **Parse canvas → tree** — :func:`parse_canvas_to_tree` expands feedback
   wires via standard **loop unrolling**: the path from the feedback target
   to the feedback source (inclusive of all intermediate nodes) is
   duplicated ``N`` times, each instance getting a unique id. The output is
   a :class:`WorkflowTree`.

3. **Tree** — :class:`WorkflowTree` is loosely called a "tree" but is
   structurally a DAG with depth annotation. :class:`TreeNode` has
   ``parent_id`` (the primary parent = first predecessor in BFS) PLUS
   ``dependency_ids`` (all other predecessors). ``depth`` is the BFS level.
   ``children`` is the forward adjacency (primary-tree children).

4. **Flow sequence** — :func:`generate_flow_sequence` produces a numbered
   list text with each node's agent name, description, depth, and
   "parallel with X" / "depends on X" annotations derived from
   ``dependency_ids``. This text is injected into the director prompt.

Per the confirmed design: "tree" is loose usage; the structure is a DAG
with depth annotation, not a strict tree.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ── Canvas model (user-facing) ──────────────────────────────────────────


@dataclass(frozen=True)
class CanvasNode:
    """A node on the user canvas.

    Attributes:
        id:         Unique node id within the canvas.
        agent_name: The agent name this node instantiates.
        description: Short human-readable description.
        params:     Free-form parameter dict.
    """

    id: str
    agent_name: str
    description: str
    params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CanvasWire:
    """A wire on the user canvas.

    Attributes:
        from_node:    Source node id.
        to_node:      Target node id.
        repeat_count: ``1`` for a forward wire; ``> 1`` for a feedback
                      wire (back-edge). The path target→source is unrolled
                      ``repeat_count`` times during parsing.
    """

    from_node: str
    to_node: str
    repeat_count: int = 1


@dataclass
class CanvasGraph:
    """The user-editable canvas: nodes + wires.

    Strictly acyclic except for feedback wires (``repeat_count > 1``),
    which are genuine back-edges excluded from the topological sort.
    """

    nodes: list[CanvasNode] = field(default_factory=list)
    wires: list[CanvasWire] = field(default_factory=list)

    def node_by_id(self, node_id: str) -> CanvasNode:
        """Return the node with id *node_id*."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        msg = f"CanvasGraph: no node with id {node_id!r}"
        raise KeyError(msg)

    def validate(self) -> None:
        """Validate the canvas.

        Topological sort EXCLUDES feedback wires (``repeat_count > 1``).
        Each feedback wire is verified to be a genuine back-edge: its
        ``to_node`` must appear *before* its ``from_node`` in the
        topological order. A non-feedback cycle raises :class:`ValueError`.

        Raises:
            ValueError: on a non-feedback cycle, dangling wire, self-loop,
                repeat_count < 1, or a feedback wire that is NOT a genuine
                back-edge.
        """
        self._topological_order()

    def _topological_order(self) -> list[str]:
        """Return the topological order (forward wires only). Internal."""
        forward_wires = [w for w in self.wires if w.repeat_count <= 1]
        feedback_wires = [w for w in self.wires if w.repeat_count > 1]

        node_ids = {n.id for n in self.nodes}
        for wire in self.wires:
            if wire.from_node not in node_ids:
                msg = f"CanvasGraph.validate: wire from_node {wire.from_node!r} not in nodes"
                raise ValueError(msg)
            if wire.to_node not in node_ids:
                msg = f"CanvasGraph.validate: wire to_node {wire.to_node!r} not in nodes"
                raise ValueError(msg)
            if wire.from_node == wire.to_node:
                msg = f"CanvasGraph.validate: self-loop wire {wire.from_node!r}->{wire.to_node!r}"
                raise ValueError(msg)
            if wire.repeat_count < 1:
                msg = f"CanvasGraph.validate: repeat_count must be >= 1, got {wire.repeat_count}"
                raise ValueError(msg)

        successors: dict[str, list[str]] = {nid: [] for nid in node_ids}
        in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
        for wire in forward_wires:
            successors[wire.from_node].append(wire.to_node)
            in_degree[wire.to_node] += 1

        queue: deque[str] = deque(sorted(nid for nid in node_ids if in_degree[nid] == 0))
        topo: list[str] = []
        while queue:
            nid = queue.popleft()
            topo.append(nid)
            for succ in sorted(successors[nid]):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(topo) != len(node_ids):
            remaining = sorted(nid for nid in node_ids if nid not in set(topo))
            msg = (
                f"CanvasGraph.validate: cycle detected (non-feedback) among nodes: {remaining}. "
                "Only feedback wires (repeat_count>1) may form back-edges."
            )
            raise ValueError(msg)

        topo_index = {nid: i for i, nid in enumerate(topo)}
        for wire in feedback_wires:
            if topo_index[wire.to_node] >= topo_index[wire.from_node]:
                msg = (
                    f"CanvasGraph.validate: feedback wire {wire.from_node!r}->{wire.to_node!r} "
                    "is not a genuine back-edge (target must be topologically before source)."
                )
                raise ValueError(msg)

        return topo


# ── Workflow tree (parser output) ───────────────────────────────────────


@dataclass
class TreeNode:
    """A node in the expanded :class:`WorkflowTree`.

    "Tree" is loose usage — the structure is a DAG with depth annotation.
    Each node has ``parent_id`` (primary parent) + ``dependency_ids``
    (other predecessors) + ``children`` (forward adjacency).

    Attributes:
        id:              Unique node id in the expanded tree.
        agent_name:      The agent name (carried from the canvas node).
        description:     Carried from the canvas node.
        params:          Carried from the canvas node.
        depth:           BFS level from the root (root = 0).
        parent_id:       Primary parent id (first predecessor in BFS);
                         ``None`` for the root.
        dependency_ids:  Other predecessor ids (excludes primary parent).
        children:        Forward-adjacency children (primary-tree edges).
    """

    id: str
    agent_name: str
    description: str
    params: dict[str, object]
    depth: int
    parent_id: str | None
    dependency_ids: list[str] = field(default_factory=list)
    children: list[TreeNode] = field(default_factory=list)


@dataclass
class WorkflowTree:
    """Expanded workflow tree (DAG with depth annotation).

    Attributes:
        root:       The root :class:`TreeNode` (depth 0, parent_id None).
        all_nodes:  Mapping from node id → :class:`TreeNode`. Auto-built
                    from ``root.children`` traversal if not provided.
    """

    root: TreeNode
    all_nodes: dict[str, TreeNode] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.all_nodes:
            self.all_nodes = self._collect_all_nodes()
        else:
            collected = self._collect_all_nodes()
            for nid, node in collected.items():
                if nid not in self.all_nodes:
                    self.all_nodes[nid] = node
        if self.root.id not in self.all_nodes:
            self.all_nodes[self.root.id] = self.root
        self._check_duplicate_ids()

    def _collect_all_nodes(self) -> dict[str, TreeNode]:
        """Walk root.children to build all_nodes (BFS)."""
        result: dict[str, TreeNode] = {self.root.id: self.root}
        queue: deque[TreeNode] = deque([self.root])
        while queue:
            cur = queue.popleft()
            for child in cur.children:
                if child.id not in result:
                    result[child.id] = child
                    queue.append(child)
        return result

    def _check_duplicate_ids(self) -> None:
        """Raise if the same id appears more than once across root.children."""
        seen: set[str] = set()
        queue: deque[TreeNode] = deque([self.root])
        while queue:
            cur = queue.popleft()
            if cur.id in seen:
                msg = f"WorkflowTree: duplicate node id {cur.id!r}"
                raise ValueError(msg)
            seen.add(cur.id)
            for child in cur.children:
                queue.append(child)

    def node_count(self) -> int:
        """Return the number of nodes in the tree."""
        return len(self.all_nodes)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict (JSON/yaml-compatible)."""
        return {
            "root_id": self.root.id,
            "all_nodes": {
                nid: {
                    "id": n.id,
                    "agent_name": n.agent_name,
                    "description": n.description,
                    "params": dict(n.params),
                    "depth": n.depth,
                    "parent_id": n.parent_id,
                    "dependency_ids": list(n.dependency_ids),
                }
                for nid, n in self.all_nodes.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> WorkflowTree:
        """Reconstruct from :meth:`to_dict` output."""
        raw_nodes_obj = data["all_nodes"]
        if not isinstance(raw_nodes_obj, dict):
            msg = f"WorkflowTree.from_dict: all_nodes must be a dict, got {type(raw_nodes_obj).__name__}"
            raise ValueError(msg)
        nodes: dict[str, TreeNode] = {}
        for raw in raw_nodes_obj.values():
            if not isinstance(raw, dict):
                msg = f"WorkflowTree.from_dict: node entry must be a dict, got {type(raw).__name__}"
                raise ValueError(msg)
            d: dict[str, object] = raw
            parent_raw = d.get("parent_id")
            parent_id = parent_raw if parent_raw is None else str(parent_raw)
            nodes[str(d["id"])] = TreeNode(
                id=str(d["id"]),
                agent_name=str(d["agent_name"]),
                description=str(d.get("description", "")),
                params=_coerce_params_dict(d.get("params", {})),
                depth=_coerce_int(d["depth"]),
                parent_id=parent_id,
                dependency_ids=_coerce_str_list(d.get("dependency_ids", [])),
            )
        root_id = str(data["root_id"])
        root = nodes[root_id]
        for _nid, node in nodes.items():
            if node.parent_id is not None and node.parent_id in nodes:
                parent_node = nodes[node.parent_id]
                if node not in parent_node.children:
                    parent_node.children.append(node)
        return cls(root=root, all_nodes=nodes)

    def save(self, path: str | Path) -> None:
        """Serialize to a yaml or json file (by extension)."""
        p = Path(path)
        data = self.to_dict()
        if p.suffix.lower() in (".yaml", ".yml"):
            p.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        elif p.suffix.lower() == ".json":
            p.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            msg = f"WorkflowTree.save: unsupported file extension {p.suffix!r}"
            raise ValueError(msg)

    @classmethod
    def load(cls, path: str | Path) -> WorkflowTree:
        """Reconstruct from a yaml or json file written by :meth:`save`."""
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            data = yaml.safe_load(text)
        elif p.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            msg = f"WorkflowTree.load: unsupported file extension {p.suffix!r}"
            raise ValueError(msg)
        if not isinstance(data, dict) or "root_id" not in data:
            msg = f"WorkflowTree.load: expected dict with 'root_id', got {type(data).__name__}"
            raise ValueError(msg)
        return cls.from_dict(data)


# ── Parser: canvas → tree ───────────────────────────────────────────────


def _build_successors(canvas: CanvasGraph, include_feedback: bool = False) -> dict[str, list[str]]:
    """Build a successors adjacency map from the canvas wires."""
    succ: dict[str, list[str]] = {n.id: [] for n in canvas.nodes}
    for wire in canvas.wires:
        if not include_feedback and wire.repeat_count > 1:
            continue
        succ[wire.from_node].append(wire.to_node)
    return succ


def _find_path(successors: dict[str, list[str]], src: str, dst: str) -> list[str]:
    """Find a path from *src* to *dst* along forward edges, BFS."""
    if src == dst:
        return [src]
    queue: deque[str] = deque([src])
    came_from: dict[str, str] = {}
    visited: set[str] = {src}
    while queue:
        cur = queue.popleft()
        for nxt in successors.get(cur, []):
            if nxt in visited:
                continue
            came_from[nxt] = cur
            if nxt == dst:
                path = [dst]
                while path[-1] != src:
                    path.append(came_from[path[-1]])
                path.reverse()
                return path
            visited.add(nxt)
            queue.append(nxt)
    msg = f"parse_canvas_to_tree: no forward path {src!r}->{dst!r} for feedback unrolling"
    raise ValueError(msg)


def _unroll_id(base_id: str, k: int) -> str:
    """Build the unique id for the k-th unrolled instance of *base_id*."""
    return f"{base_id}_u{k}"


def parse_canvas_to_tree(canvas: CanvasGraph) -> WorkflowTree:
    """Compile a :class:`CanvasGraph` into an expanded :class:`WorkflowTree`.

    1. Validate the canvas (topo sort excluding feedback; verify feedback
       are genuine back-edges).
    2. Unroll each feedback wire's forward path target→source (inclusive)
       ``N`` times with unique ids. Original path nodes are REPLACED by
       the unrolled instances.
    3. BFS to compute depth, parent_id, dependency_ids, children.

    Args:
        canvas: The user canvas (validated inside).

    Returns:
        A :class:`WorkflowTree`.

    Raises:
        ValueError: on canvas validation failure or unrollable feedback.
    """
    canvas.validate()
    canvas._topological_order()

    expanded_nodes: dict[str, CanvasNode] = {n.id: n for n in canvas.nodes}
    expanded_edges: list[tuple[str, str]] = []
    feedback_wires: list[CanvasWire] = []

    for wire in canvas.wires:
        if wire.repeat_count > 1:
            feedback_wires.append(wire)
        else:
            expanded_edges.append((wire.from_node, wire.to_node))

    forward_succ = _build_successors(canvas, include_feedback=False)

    for fb in feedback_wires:
        target = fb.to_node
        source = fb.from_node
        n_repeats = fb.repeat_count

        path = _find_path(forward_succ, target, source)
        path_set = set(path)

        # Capture external in/out edges BEFORE removing path nodes.
        external_in: list[tuple[str, str]] = []
        external_out: list[tuple[str, str]] = []
        for wire in canvas.wires:
            if wire.repeat_count > 1:
                continue
            f, t = wire.from_node, wire.to_node
            if t == target and f not in path_set:
                external_in.append((f, t))
            if f == source and t not in path_set:
                external_out.append((f, t))

        # Remove original path nodes — superseded by unrolled instances.
        for base in path:
            expanded_nodes.pop(base, None)

        # Remove all edges touching the path.
        kept_edges: list[tuple[str, str]] = []
        for f, t in expanded_edges:
            if f in path_set or t in path_set:
                continue
            kept_edges.append((f, t))
        expanded_edges = kept_edges

        # Unroll each instance.
        new_edges: list[tuple[str, str]] = []
        prev_last_id: str | None = None
        for k in range(1, n_repeats + 1):
            instance_ids: dict[str, str] = {base: _unroll_id(base, k) for base in path}
            for base in path:
                base_node = canvas.node_by_id(base)
                uid = instance_ids[base]
                expanded_nodes[uid] = CanvasNode(
                    id=uid,
                    agent_name=base_node.agent_name,
                    description=base_node.description,
                    params=dict(base_node.params),
                )
            for i in range(len(path) - 1):
                new_edges.append((instance_ids[path[i]], instance_ids[path[i + 1]]))
            if prev_last_id is not None:
                new_edges.append((prev_last_id, instance_ids[path[0]]))
            prev_last_id = instance_ids[path[-1]]

        # Rewire external in-edges to first unrolled target.
        first_target_uid = _unroll_id(target, 1)
        for f, _t in external_in:
            expanded_edges.append((f, first_target_uid))

        # Rewire external out-edges from last unrolled source.
        last_source_uid = _unroll_id(source, n_repeats)
        for _f, t in external_out:
            expanded_edges.append((last_source_uid, t))

        expanded_edges.extend(new_edges)

    # Build predecessors + successors over expanded graph.
    predecessors: dict[str, list[str]] = {nid: [] for nid in expanded_nodes}
    successors_exp: dict[str, list[str]] = {nid: [] for nid in expanded_nodes}
    for f, t in expanded_edges:
        predecessors[t].append(f)
        successors_exp[f].append(t)

    roots = sorted(nid for nid in expanded_nodes if not predecessors[nid])
    if not roots:
        msg = "parse_canvas_to_tree: no root node (all nodes have predecessors — cycle?)"
        raise ValueError(msg)
    root_id = roots[0]

    # BFS for depth + parent assignment.
    depth: dict[str, int] = {root_id: 0}
    parent: dict[str, str | None] = {root_id: None}
    children_map: dict[str, list[str]] = {root_id: []}
    queue: deque[str] = deque([root_id])
    visited: set[str] = {root_id}
    while queue:
        cur = queue.popleft()
        for nxt in sorted(successors_exp[cur]):
            if nxt in visited:
                continue
            visited.add(nxt)
            depth[nxt] = depth[cur] + 1
            parent[nxt] = cur
            children_map.setdefault(cur, []).append(nxt)
            children_map.setdefault(nxt, [])
            queue.append(nxt)

    # Defensive: disconnected nodes.
    if len(visited) != len(expanded_nodes):
        for nid in expanded_nodes:
            if nid not in visited:
                depth[nid] = 0
                parent[nid] = None
                children_map.setdefault(nid, [])

    # Build TreeNodes.
    tree_nodes: dict[str, TreeNode] = {}
    for nid, cnode in expanded_nodes.items():
        preds = sorted(predecessors[nid])
        primary_parent = parent[nid]
        deps = [p for p in preds if p != primary_parent]
        tree_nodes[nid] = TreeNode(
            id=nid,
            agent_name=cnode.agent_name,
            description=cnode.description,
            params=dict(cnode.params),
            depth=depth[nid],
            parent_id=primary_parent,
            dependency_ids=deps,
        )

    # Wire up children references.
    for nid, node in tree_nodes.items():
        for child_id in children_map.get(nid, []):
            if child_id in tree_nodes:
                node.children.append(tree_nodes[child_id])

    root_node = tree_nodes[root_id]
    return WorkflowTree(root=root_node, all_nodes=tree_nodes)


# ── Flow sequence generator ─────────────────────────────────────────────


def generate_flow_sequence(tree: WorkflowTree) -> str:
    """Generate the numbered execution-order text for the director prompt.

    Format (one node per line, BFS order)::

        1. [depth=0] agent_name: description
        2. [depth=1] agent_name: description (parallel with X, depends on Y)

    Annotations (only when ``dependency_ids`` is non-empty):

    * ``(parallel with X, Y)`` — dependencies at the SAME depth.
    * ``(depends on X, Y)`` — dependencies at a DIFFERENT depth.
    * Both can appear comma-separated when both kinds exist.

    Args:
        tree: The expanded :class:`WorkflowTree`.

    Returns:
        A newline-separated numbered list string. Empty tree → empty str.
    """
    if not tree.all_nodes:
        return ""

    ordered = sorted(tree.all_nodes.values(), key=lambda n: (n.depth, n.id))

    lines: list[str] = []
    for i, node in enumerate(ordered, start=1):
        annotation = ""
        if node.dependency_ids:
            same_depth = [d for d in node.dependency_ids if tree.all_nodes[d].depth == node.depth]
            diff_depth = [d for d in node.dependency_ids if tree.all_nodes[d].depth != node.depth]
            parts: list[str] = []
            if same_depth:
                parts.append("parallel with " + ", ".join(same_depth))
            if diff_depth:
                parts.append("depends on " + ", ".join(diff_depth))
            annotation = f" ({', '.join(parts)})"
        desc = f": {node.description}" if node.description else ""
        lines.append(f"{i}. [depth={node.depth}] {node.agent_name}{desc}{annotation}")
    return "\n".join(lines)


# ── Loader ──────────────────────────────────────────────────────────────


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
