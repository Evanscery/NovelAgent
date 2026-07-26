"""Parser: canvas -> tree (parse_canvas_to_tree + private helpers).

Compiles a :class:`~app.canvas.canvas_model.CanvasGraph` into an expanded
:class:`~app.agents.tree_model.WorkflowTree` via loop unrolling of feedback
wires.

Extracted from the original monolithic ``workflow.py``.
"""

from __future__ import annotations

from collections import deque

from app.agents.tree_model import TreeNode, WorkflowTree
from app.canvas.canvas_model import CanvasGraph, CanvasNode, CanvasWire


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
    2. Unroll each feedback wire's forward path target->source (inclusive)
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

        # Remove original path nodes -- superseded by unrolled instances.
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
        msg = "parse_canvas_to_tree: no root node (all nodes have predecessors -- cycle?)"
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
