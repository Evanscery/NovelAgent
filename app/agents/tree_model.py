"""Workflow tree model (parser output): NodeDefinition, TreeNode, WorkflowTree.
Extracted from the original monolithic ``workflow.py``.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from app.agents.registry import AgentRegistry

#: The only node kind implemented today. The serialization format is
#: kind-tagged so ``tool`` / ``mcp`` nodes can be added later
#: without changing the envelope: each carries its own
#: :class:`NodeDefinition` and unknown kinds round-trip untouched.
AGENT_KIND = "agent"


def definition_key(kind: str, definition_id: str) -> str:
    """Return the composite key identifying a definition across kinds."""
    return f"{kind}:{definition_id}"


@dataclass(frozen=True)
class NodeDefinition:
    """The self-contained definition of whatever a :class:`TreeNode` runs.

    A workflow tree that carries its definitions is portable: the
    recipient reconstructs the exact objects from the file alone,
    instead of resolving a display name against their own local
    registry (which may hold a different object under the same name,
    or none at all).

    Attributes:
        kind:    Node-kind discriminator -- ``"agent"`` today, with
                 ``"tool"`` / ``"mcp"`` as planned kinds.
        id:      Identifier within the *kind* namespace (for agents this
                 is ``Agent.id``, the control identifier per
                 refactor_guide:63).
        payload: The full attribute set of the defined object (for
                 agents, :meth:`~app.agents.agent.Agent.to_dict` output).
    """

    kind: str
    id: str
    payload: dict[str, object]

    @property
    def key(self) -> str:
        """The composite ``kind:id`` key used in :attr:`WorkflowTree.definitions`."""
        return definition_key(self.kind, self.id)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict (JSON/yaml-compatible)."""
        return {"kind": self.kind, "id": self.id, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, raw: object) -> NodeDefinition:
        """Reconstruct from :meth:`to_dict` output."""
        if not isinstance(raw, dict):
            msg = f"NodeDefinition.from_dict: expected a mapping, got {type(raw).__name__}"
            raise ValueError(msg)
        for required in ("kind", "id", "payload"):
            if required not in raw:
                msg = f"NodeDefinition.from_dict: missing required field {required!r}"
                raise ValueError(msg)
        payload = raw["payload"]
        if not isinstance(payload, dict):
            msg = f"NodeDefinition.from_dict: 'payload' must be a mapping, got {type(payload).__name__}"
            raise ValueError(msg)
        return cls(
            kind=str(raw["kind"]),
            id=str(raw["id"]),
            payload={str(k): v for k, v in payload.items()},
        )


@dataclass
class TreeNode:
    """A node in the expanded :class:`WorkflowTree`.

    "Tree" is loose usage -- the structure is a DAG with depth annotation.
    Each node has ``parent_id`` (primary parent) + ``dependency_ids``
    (other predecessors) + ``children`` (forward adjacency).

    Attributes:
        id:              Unique node id in the expanded tree.
        agent_name:      The agent name (carried from the canvas node).
                         Display-only: it is what the flow sequence shows
                         and what the director names in ``call_agent``. It
                         is NOT the node's identity -- see ``definition_id``.
        description:     Carried from the canvas node.
        params:          Carried from the canvas node.
        depth:           BFS level from the root (root = 0).
        parent_id:       Primary parent id (first predecessor in BFS);
                         ``None`` for the root.
        dependency_ids:  Other predecessor ids (excludes primary parent).
        children:        Forward-adjacency children (primary-tree edges).
        kind:            Node-kind discriminator (see :data:`AGENT_KIND`).
        definition_id:   Id of this node's :class:`NodeDefinition` inside
                         :attr:`WorkflowTree.definitions`. ``None`` until
                         :meth:`WorkflowTree.embed_definitions` resolves it.
    """
    id: str
    agent_name: str
    description: str
    params: dict[str, object]
    depth: int
    parent_id: str | None
    dependency_ids: list[str] = field(default_factory=list)
    children: list[TreeNode] = field(default_factory=list)
    kind: str = AGENT_KIND
    definition_id: str | None = None

    @property
    def definition_key(self) -> str | None:
        """The ``kind:definition_id`` key, or ``None`` if unresolved."""
        if self.definition_id is None:
            return None
        return definition_key(self.kind, self.definition_id)


@dataclass
class WorkflowTree:
    """Expanded workflow tree (DAG with depth annotation).

    Attributes:
        root:        The root :class:`TreeNode` (depth 0, parent_id None).
        all_nodes:   Mapping from node id -> :class:`TreeNode`. Auto-built
                     from ``root.children`` traversal if not provided.
        definitions: Mapping from ``kind:id`` -> :class:`NodeDefinition`.
                     Populated by :meth:`embed_definitions`; serialized by
                     :meth:`to_dict` and restored by :meth:`from_dict` so
                     an exported tree reconstructs its own objects instead
                     of depending on the recipient's name mapping.
    """

    root: TreeNode
    all_nodes: dict[str, TreeNode] = field(default_factory=dict)
    definitions: dict[str, NodeDefinition] = field(default_factory=dict)

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

    # -- definitions (portability) ------------------------------------------

    def definition_for(self, node: TreeNode) -> NodeDefinition | None:
        """Return the :class:`NodeDefinition` *node* resolves to, if embedded."""
        key = node.definition_key
        if key is None:
            return None
        return self.definitions.get(key)

    def undefined_nodes(self) -> list[str]:
        """Return the ids of nodes with no embedded definition (sorted)."""
        return sorted(
            nid for nid, node in self.all_nodes.items() if self.definition_for(node) is None
        )

    def embed_definitions(self, registry: AgentRegistry) -> None:
        """Resolve every agent node against *registry* and embed its definition.

        This is the step that makes an export portable: after it, the tree
        carries the full attribute set of each agent it references, so a
        recipient reconstructs the exact same workflow rather than binding
        the node's display name to whatever agent they happen to have under
        that name.

        Nodes whose definition is already embedded (e.g. a tree that was
        itself imported) are left untouched, so re-exporting an imported
        tree preserves the original definitions. Nodes of a kind other than
        ``"agent"`` are left to their own (future) resolvers.

        Raises:
            ValueError: If an agent node's name does not resolve to exactly
                one agent in *registry*. Exporting a tree with a dangling
                reference would silently produce an unusable workflow, so
                it fails loudly instead.
        """
        unresolved: list[str] = []
        for node in self.all_nodes.values():
            if node.kind != AGENT_KIND or self.definition_for(node) is not None:
                continue
            try:
                agent = registry.get_by_name(node.agent_name)
            except KeyError:
                unresolved.append(f"{node.id} (agent_name={node.agent_name!r})")
                continue
            node.definition_id = agent.id
            definition = NodeDefinition(kind=AGENT_KIND, id=agent.id, payload=agent.to_dict())
            self.definitions[definition.key] = definition
        if unresolved:
            msg = (
                "WorkflowTree.embed_definitions: cannot resolve agent for nodes: "
                + ", ".join(unresolved)
            )
            raise ValueError(msg)

    # -- serialization ------------------------------------------------------

    def to_dict(self, registry: AgentRegistry | None = None) -> dict[str, object]:
        """Serialize to a plain dict (JSON/yaml-compatible).

        When *registry* is given, :meth:`embed_definitions` runs first so
        the result is self-contained. Without it, only the definitions
        already embedded on the tree are written -- the output then
        describes the tree's shape but not what its nodes run.
        """
        if registry is not None:
            self.embed_definitions(registry)
        return {
            "root_id": self.root.id,
            "all_nodes": {
                nid: {
                    "id": n.id,
                    "kind": n.kind,
                    "agent_name": n.agent_name,
                    "definition_id": n.definition_id,
                    "description": n.description,
                    "params": dict(n.params),
                    "depth": n.depth,
                    "parent_id": n.parent_id,
                    "dependency_ids": list(n.dependency_ids),
                }
                for nid, n in self.all_nodes.items()
            },
            "definitions": [d.to_dict() for d in self.definitions.values()],
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
            definition_raw = d.get("definition_id")
            nodes[str(d["id"])] = TreeNode(
                id=str(d["id"]),
                agent_name=str(d["agent_name"]),
                description=str(d.get("description", "")),
                params=_coerce_params_dict(d.get("params", {})),
                depth=_coerce_int(d["depth"]),
                parent_id=parent_id,
                dependency_ids=_coerce_str_list(d.get("dependency_ids", [])),
                kind=str(d.get("kind", AGENT_KIND)),
                definition_id=definition_raw if definition_raw is None else str(definition_raw),
            )
        root_id = str(data["root_id"])
        root = nodes[root_id]
        for _nid, node in nodes.items():
            if node.parent_id is not None and node.parent_id in nodes:
                parent_node = nodes[node.parent_id]
                if node not in parent_node.children:
                    parent_node.children.append(node)

        raw_definitions = data.get("definitions", [])
        if not isinstance(raw_definitions, list):
            msg = f"WorkflowTree.from_dict: 'definitions' must be a list, got {type(raw_definitions).__name__}"
            raise ValueError(msg)
        definitions: dict[str, NodeDefinition] = {}
        for raw_def in raw_definitions:
            definition = NodeDefinition.from_dict(raw_def)
            definitions[definition.key] = definition

        return cls(root=root, all_nodes=nodes, definitions=definitions)

    def save(self, path: str | Path, registry: AgentRegistry | None = None) -> None:
        """Serialize to a yaml or json file (by extension).

        Pass *registry* to write a portable export (see :meth:`to_dict`).
        """
        p = Path(path)
        data = self.to_dict(registry=registry)
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
