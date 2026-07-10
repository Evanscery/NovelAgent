"""Canvas model (user-facing): CanvasNode, CanvasWire, CanvasGraph.

The canvas is the user-editable workflow definition: nodes (agent
instantiations) + wires (directed edges). Strictly acyclic except for
feedback wires (``repeat_count > 1``), which are genuine back-edges
excluded from the topological sort.

Extracted from the original monolithic ``workflow.py``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


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
                      wire (back-edge). The path target->source is unrolled
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
