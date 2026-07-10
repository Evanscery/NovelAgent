"""Tests for app.agents.workflow — Canvas → Tree parser + flow-sequence generator.

Per the todo 18 / plan scope design (AST-like tree, REPLACING the old DAG
design) and the user-confirmed resolutions:

- (A) Feedback wire is a REVERSE edge; CanvasGraph.validate() excludes
  feedback wires from the topological sort and verifies they are genuine
  back-edges.
- (B) Standard loop unrolling: the feedback path target→source (inclusive
  of all intermediate nodes) is duplicated N times with unique ids.
- (c) "Tree" is loose usage — TreeNode has parent_id + dependency_ids;
  the structure is a DAG with depth annotation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.workflow import (
    CanvasGraph,
    CanvasNode,
    CanvasWire,
    TreeNode,
    WorkflowTree,
    generate_flow_sequence,
    load_workflow,
    parse_canvas_to_tree,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _node(nid: str, agent: str = "agent", desc: str = "", params: dict[str, str] | None = None) -> CanvasNode:
    return CanvasNode(id=nid, agent_name=agent, description=desc, params=params or {})


def _wire(f: str, t: str, repeat: int = 1) -> CanvasWire:
    return CanvasWire(from_node=f, to_node=t, repeat_count=repeat)


def _linear_canvas() -> CanvasGraph:
    """A→B→C linear canvas (no feedback)."""
    g = CanvasGraph()
    g.nodes = [_node("a", "alpha", "A node"), _node("b", "beta", "B node"), _node("c", "gamma", "C node")]
    g.wires = [_wire("a", "b"), _wire("b", "c")]
    return g


# ── CanvasGraph.validate ────────────────────────────────────────────────────


class TestCanvasGraphValidate:
    """CanvasGraph.validate enforces strict-acyclic (modulo feedback)."""

    def test_validate_returns_none_on_valid_canvas(self) -> None:
        g = _linear_canvas()
        assert g.validate() is None

    def test_validate_rejects_forward_cycle(self) -> None:
        """A cycle among forward edges (repeat_count==1) raises ValueError."""
        g = CanvasGraph()
        g.nodes = [_node("a"), _node("b"), _node("c")]
        g.wires = [_wire("a", "b"), _wire("b", "c"), _wire("c", "a")]  # cycle a→b→c→a
        with pytest.raises(ValueError, match="cycle detected"):
            g.validate()

    def test_validate_rejects_self_loop(self) -> None:
        g = CanvasGraph()
        g.nodes = [_node("a")]
        g.wires = [_wire("a", "a")]
        with pytest.raises(ValueError, match="self-loop"):
            g.validate()

    def test_validate_rejects_unknown_from_node(self) -> None:
        g = CanvasGraph()
        g.nodes = [_node("a")]
        g.wires = [_wire("x", "a")]
        with pytest.raises(ValueError, match="from_node"):
            g.validate()

    def test_validate_rejects_unknown_to_node(self) -> None:
        g = CanvasGraph()
        g.nodes = [_node("a")]
        g.wires = [_wire("a", "x")]
        with pytest.raises(ValueError, match="to_node"):
            g.validate()

    def test_validate_rejects_repeat_count_lt_1(self) -> None:
        g = CanvasGraph()
        g.nodes = [_node("a"), _node("b")]
        g.wires = [_wire("a", "b", repeat=0)]
        with pytest.raises(ValueError, match="repeat_count"):
            g.validate()

    def test_validate_rejects_non_back_edge_feedback(self) -> None:
        """A feedback wire where to_node is NOT before from_node is rejected."""
        g = CanvasGraph()
        g.nodes = [_node("a"), _node("b"), _node("c")]
        # Forward: a→b→c. Feedback a→c (repeat=2) where c is AFTER a → not a
        # back-edge. The forward sort is a,b,c; to_node=c (pos 2),
        # from_node=a (pos 0); 2 >= 0 → reject.
        g.wires = [_wire("a", "b"), _wire("b", "c"), _wire("a", "c", repeat=2)]
        with pytest.raises(ValueError, match="not a genuine back-edge"):
            g.validate()

    def test_validate_accepts_genuine_back_edge_feedback(self) -> None:
        """A feedback wire where to_node IS before from_node is accepted."""
        g = CanvasGraph()
        g.nodes = [_node("critics"), _node("refiner")]
        g.wires = [_wire("critics", "refiner"), _wire("refiner", "critics", repeat=5)]
        g.validate()  # should not raise


# ── parse_canvas_to_tree: linear ────────────────────────────────────────────


class TestParseCanvasToTreeLinear:
    """parse_canvas_to_tree on a linear (no-feedback) canvas."""

    def test_linear_tree_has_three_nodes(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        assert tree.node_count() == 3

    def test_linear_tree_depths_are_0_1_2(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        assert tree.all_nodes["a"].depth == 0
        assert tree.all_nodes["b"].depth == 1
        assert tree.all_nodes["c"].depth == 2

    def test_linear_tree_parent_ids(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        assert tree.all_nodes["a"].parent_id is None
        assert tree.all_nodes["b"].parent_id == "a"
        assert tree.all_nodes["c"].parent_id == "b"

    def test_linear_tree_root_is_a(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        assert tree.root.id == "a"

    def test_linear_tree_no_dependency_ids(self) -> None:
        """A linear chain has no multi-parent nodes → no dependency_ids."""
        tree = parse_canvas_to_tree(_linear_canvas())
        for node in tree.all_nodes.values():
            assert node.dependency_ids == []


# ── parse_canvas_to_tree: feedback unrolling ───────────────────────────────


class TestParseCanvasToTreeFeedbackUnrolling:
    """parse_canvas_to_tree expands 'repeat N' feedback into N node instances.

    Per user-confirmed resolution (B): standard loop unrolling — the
    feedback path target→source (inclusive of all intermediate nodes) is
    duplicated N times with unique ids.
    """

    def test_repeat_3_expands_critics_refiner_into_6_instances(self) -> None:
        """critics→refiner with repeat=3 → critics_u1, refiner_u1, critics_u2,
        refiner_u2, critics_u3, refiner_u3 (6 instances total, no originals)."""
        g = CanvasGraph()
        g.nodes = [_node("critics", "critic", "审查"), _node("refiner", "refiner", "修订")]
        g.wires = [
            _wire("critics", "refiner"),  # forward
            _wire("refiner", "critics", repeat=3),  # feedback: unroll 3 times
        ]
        tree = parse_canvas_to_tree(g)
        # 2 agents × 3 unrolls = 6 expanded nodes
        assert tree.node_count() == 6
        for i in (1, 2, 3):
            assert f"critics_u{i}" in tree.all_nodes
            assert f"refiner_u{i}" in tree.all_nodes

    def test_repeat_3_chains_instances_in_order(self) -> None:
        """The unrolled instances chain c_u1→r_u1→c_u2→r_u2→c_u3→r_u3."""
        g = CanvasGraph()
        g.nodes = [_node("critics", "critic"), _node("refiner", "refiner")]
        g.wires = [_wire("critics", "refiner"), _wire("refiner", "critics", repeat=3)]
        tree = parse_canvas_to_tree(g)
        assert tree.all_nodes["refiner_u1"].parent_id == "critics_u1"
        assert tree.all_nodes["critics_u2"].parent_id == "refiner_u1"
        assert tree.all_nodes["refiner_u2"].parent_id == "critics_u2"
        assert tree.all_nodes["critics_u3"].parent_id == "refiner_u2"
        assert tree.all_nodes["refiner_u3"].parent_id == "critics_u3"

    def test_repeat_with_intermediate_node_unrolls_all(self) -> None:
        """critics→X→refiner with repeat=2 unrolls the whole path 2x.

        Per resolution (B): the path target→source INCLUDING all
        intermediate nodes is duplicated. So critics, X, refiner each
        get _u1 and _u2 instances (6 total).
        """
        g = CanvasGraph()
        g.nodes = [
            _node("critics", "critic"),
            _node("middle", "middle_agent"),
            _node("refiner", "refiner"),
        ]
        g.wires = [
            _wire("critics", "middle"),
            _wire("middle", "refiner"),
            _wire("refiner", "critics", repeat=2),
        ]
        tree = parse_canvas_to_tree(g)
        assert tree.node_count() == 6
        for i in (1, 2):
            assert f"critics_u{i}" in tree.all_nodes
            assert f"middle_u{i}" in tree.all_nodes
            assert f"refiner_u{i}" in tree.all_nodes

    def test_unrolled_tree_is_acyclic(self) -> None:
        """The expanded tree has no cycles (every loop was unrolled)."""
        g = CanvasGraph()
        g.nodes = [_node("critics", "critic"), _node("refiner", "refiner")]
        g.wires = [_wire("critics", "refiner"), _wire("refiner", "critics", repeat=3)]
        tree = parse_canvas_to_tree(g)
        ids = list(tree.all_nodes.keys())
        assert len(ids) == len(set(ids))

    def test_each_unrolled_instance_has_unique_id(self) -> None:
        g = CanvasGraph()
        g.nodes = [_node("a", "alpha"), _node("b", "beta")]
        g.wires = [_wire("a", "b"), _wire("b", "a", repeat=4)]
        tree = parse_canvas_to_tree(g)
        ids = list(tree.all_nodes.keys())
        assert len(ids) == len(set(ids))
        assert tree.node_count() == 8  # 2 agents × 4 unrolls

    def test_unrolled_depths_increase_along_chain(self) -> None:
        """In the chain c_u1→r_u1→c_u2→r_u2→..., depths increase by 1 each."""
        g = CanvasGraph()
        g.nodes = [_node("critics", "critic"), _node("refiner", "refiner")]
        g.wires = [_wire("critics", "refiner"), _wire("refiner", "critics", repeat=3)]
        tree = parse_canvas_to_tree(g)
        assert tree.all_nodes["critics_u1"].depth == 0
        assert tree.all_nodes["refiner_u1"].depth == 1
        assert tree.all_nodes["critics_u2"].depth == 2
        assert tree.all_nodes["refiner_u2"].depth == 3
        assert tree.all_nodes["critics_u3"].depth == 4
        assert tree.all_nodes["refiner_u3"].depth == 5


# ── parse_canvas_to_tree: multi-parent (dependency_ids) ────────────────────


class TestParseCanvasToTreeMultiParent:
    """Per resolution (c): multi-parent nodes get parent_id + dependency_ids."""

    def test_writer_with_two_predecessors_has_dependency_ids(self) -> None:
        """root→recaller→writer, root→scout→writer: writer has parent_id
        (first predecessor in BFS) + dependency_ids (the other)."""
        g = CanvasGraph()
        g.nodes = [
            _node("root", "director"),
            _node("recaller", "recaller"),
            _node("scout", "scout"),
            _node("writer", "writer"),
        ]
        g.wires = [
            _wire("root", "recaller"),
            _wire("root", "scout"),
            _wire("recaller", "writer"),
            _wire("scout", "writer"),
        ]
        tree = parse_canvas_to_tree(g)
        writer = tree.all_nodes["writer"]
        assert writer.parent_id in ("recaller", "scout")
        assert len(writer.dependency_ids) == 1
        assert writer.dependency_ids[0] in ("recaller", "scout")
        assert writer.dependency_ids[0] != writer.parent_id

    def test_single_parent_node_has_no_dependency_ids(self) -> None:
        g = CanvasGraph()
        g.nodes = [_node("a", "alpha"), _node("b", "beta")]
        g.wires = [_wire("a", "b")]
        tree = parse_canvas_to_tree(g)
        assert tree.all_nodes["b"].dependency_ids == []


# ── generate_flow_sequence ──────────────────────────────────────────────────


class TestGenerateFlowSequence:
    """generate_flow_sequence produces the numbered list text for the director."""

    def test_linear_flow_sequence_format(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        seq = generate_flow_sequence(tree)
        lines = seq.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("1. [depth=0] alpha: A node")
        assert lines[1].startswith("2. [depth=1] beta: B node")
        assert lines[2].startswith("3. [depth=2] gamma: C node")

    def test_flow_sequence_contains_depth_annotation(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        seq = generate_flow_sequence(tree)
        assert "[depth=0]" in seq
        assert "[depth=1]" in seq
        assert "[depth=2]" in seq

    def test_flow_sequence_numbered_list(self) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        seq = generate_flow_sequence(tree)
        assert seq.startswith("1.")
        assert "2." in seq
        assert "3." in seq

    def test_flow_sequence_with_dependency_annotation(self) -> None:
        """A node with dependency_ids gets a (depends on X) / (parallel with X) annotation."""
        g = CanvasGraph()
        g.nodes = [
            _node("root", "director", "决策"),
            _node("recaller", "recaller", "召回"),
            _node("scout", "scout", "灵感"),
            _node("writer", "writer", "生成"),
        ]
        g.wires = [
            _wire("root", "recaller"),
            _wire("root", "scout"),
            _wire("recaller", "writer"),
            _wire("scout", "writer"),
        ]
        tree = parse_canvas_to_tree(g)
        seq = generate_flow_sequence(tree)
        writer_line = [ln for ln in seq.split("\n") if "writer" in ln][0]
        assert "parallel with" in writer_line or "depends on" in writer_line


# ── save / load round-trip ─────────────────────────────────────────────────


class TestWorkflowTreeSaveLoad:
    """WorkflowTree.save/load round-trip via yaml and json."""

    def test_yaml_round_trip(self, tmp_path: Path) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        p = tmp_path / "tree.yaml"
        tree.save(p)
        loaded = WorkflowTree.load(p)
        assert loaded.node_count() == tree.node_count()
        assert set(loaded.all_nodes) == set(tree.all_nodes)
        for nid in tree.all_nodes:
            assert loaded.all_nodes[nid].depth == tree.all_nodes[nid].depth
            assert loaded.all_nodes[nid].parent_id == tree.all_nodes[nid].parent_id

    def test_json_round_trip(self, tmp_path: Path) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        p = tmp_path / "tree.json"
        tree.save(p)
        loaded = WorkflowTree.load(p)
        assert loaded.node_count() == tree.node_count()
        assert set(loaded.all_nodes) == set(tree.all_nodes)

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        p = tmp_path / "tree.txt"
        with pytest.raises(ValueError, match="unsupported file extension"):
            tree.save(p)


# ── load_workflow (file-level) ──────────────────────────────────────────────


class TestLoadWorkflow:
    """load_workflow supports both tree-format and canvas-format files."""

    def test_load_workflow_tree_format(self, tmp_path: Path) -> None:
        tree = parse_canvas_to_tree(_linear_canvas())
        p = tmp_path / "tree.yaml"
        tree.save(p)
        loaded = load_workflow(p)
        assert loaded.node_count() == tree.node_count()

    def test_load_workflow_canvas_format(self, tmp_path: Path) -> None:
        """A canvas-format yaml (nodes + wires) is compiled to a tree."""
        import yaml

        canvas_data = {
            "nodes": [
                {"id": "a", "agent_name": "alpha", "description": "A"},
                {"id": "b", "agent_name": "beta", "description": "B"},
            ],
            "wires": [
                {"from_node": "a", "to_node": "b", "repeat_count": 1},
            ],
        }
        p = tmp_path / "canvas.yaml"
        p.write_text(yaml.safe_dump(canvas_data, allow_unicode=True), encoding="utf-8")
        loaded = load_workflow(p)
        assert loaded.node_count() == 2
        assert loaded.all_nodes["a"].depth == 0
        assert loaded.all_nodes["b"].depth == 1

    def test_load_workflow_unsupported_extension_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "wf.txt"
        p.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported file extension"):
            load_workflow(p)


# ── default_workflow.yaml integration ──────────────────────────────────────


class TestDefaultWorkflowFile:
    """The shipped default_workflow.yaml parses to a valid tree."""

    def test_default_workflow_loads(self) -> None:
        default_path = Path(__file__).resolve().parents[3] / "app" / "agents" / "default_workflow.yaml"
        tree = load_workflow(default_path)
        # recaller, scout, writer, critic, maintainer = 5 nodes
        # (director is a system agent, NOT in the workflow tree)
        assert tree.node_count() == 5
        for name in ("recaller", "scout", "writer", "critic", "maintainer"):
            assert name in tree.all_nodes

    def test_default_workflow_root_depth_0(self) -> None:
        default_path = Path(__file__).resolve().parents[3] / "app" / "agents" / "default_workflow.yaml"
        tree = load_workflow(default_path)
        # Director is NOT in the tree; root is a workflow agent (recaller or scout).
        assert tree.root.agent_name in ("recaller", "scout")
        assert tree.root.depth == 0

    def test_default_workflow_writer_has_dependency_ids(self) -> None:
        """writer has two predecessors (recaller, scout) → one dependency_id."""
        default_path = Path(__file__).resolve().parents[3] / "app" / "agents" / "default_workflow.yaml"
        tree = load_workflow(default_path)
        writer = tree.all_nodes["writer"]
        assert writer.parent_id in ("recaller", "scout")
        assert len(writer.dependency_ids) == 1


# ── TreeNode / WorkflowTree dataclasses ─────────────────────────────────────


class TestTreeNodeDataclass:
    def test_treenode_to_dict_and_from_dict(self) -> None:
        root = TreeNode(
            id="root",
            agent_name="director",
            description="决策",
            params={},
            depth=0,
            parent_id=None,
            dependency_ids=[],
        )
        child = TreeNode(
            id="child",
            agent_name="writer",
            description="生成",
            params={"mode": "deep"},
            depth=1,
            parent_id="root",
            dependency_ids=[],
        )
        root.children.append(child)
        tree = WorkflowTree(root=root)
        d = tree.to_dict()
        loaded = WorkflowTree.from_dict(d)
        assert loaded.root.id == "root"
        assert loaded.all_nodes["child"].depth == 1
        assert loaded.all_nodes["child"].parent_id == "root"


class TestWorkflowTreeDuplicateIdDetection:
    def test_duplicate_ids_raise(self) -> None:
        """WorkflowTree raises if the same id appears twice in the tree."""
        n1 = TreeNode(id="dup", agent_name="a", description="", params={}, depth=0, parent_id=None)
        n2 = TreeNode(id="dup", agent_name="b", description="", params={}, depth=1, parent_id="dup")
        n1.children.append(n2)
        with pytest.raises(ValueError, match="duplicate node id"):
            WorkflowTree(root=n1)
