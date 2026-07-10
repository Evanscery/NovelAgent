"""Workflow tree model (parser output): TreeNode, WorkflowTree.

"Tree" is loose usage -- the structure is a DAG with depth annotation.
Each node has ``parent_id`` (primary parent) + ``dependency_ids``
(other predecessors) + ``children`` (forward adjacency).

Extracted from the original monolithic ``workflow.py``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TreeNode:
    """A node in the expanded :class:`WorkflowTree`.

    "Tree" is loose usage -- the structure is a DAG with depth annotation.
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
        all_nodes:  Mapping from node id -> :class:`TreeNode`. Auto-built
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
        # Lazy import to avoid a circular dependency: workflow_loader
        # imports WorkflowTree at module load, and from_dict needs the
        # coercion helpers defined in workflow_loader.
        from app.agents.workflow_loader import (
            _coerce_int,
            _coerce_params_dict,
            _coerce_str_list,
        )

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
