"""Tests for app.agents.registry — load built-in agents, default workflow, build_default_registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.agent import Agent, get_default_tools, set_default_tools
from app.agents.permission import Permission
from app.agents.registry import (
    AgentRegistry,
    _load_agent_yaml,
    build_default_registry,
)
from app.agents.workflow import WorkflowTree
from app.canvas.workflow_loader import load_default_workflow

# ── AgentRegistry basic ops ────────────────────────────────────────────


class TestAgentRegistry:
    """AgentRegistry register/get/list/has."""

    def test_register_and_get_by_id(self) -> None:
        registry = AgentRegistry()
        agent = Agent(
            id="a-1",
            name="recaller",
            task="t",
            input="i",
            output="o",
            permission=Permission(rules={}),
        )
        registry.register(agent)
        assert registry.has("a-1")
        assert registry.get("a-1") is agent

    def test_get_by_name_resolves_display_name(self) -> None:
        registry = AgentRegistry()
        agent = Agent(
            id="a-1",
            name="recaller",
            task="t",
            input="i",
            output="o",
            permission=Permission(rules={}),
        )
        registry.register(agent)
        assert registry.has_by_name("recaller")
        assert registry.get_by_name("recaller") is agent

    def test_get_missing_id_raises_key_error(self) -> None:
        registry = AgentRegistry()
        with pytest.raises(KeyError, match="no agent with id"):
            registry.get("nonexistent")

    def test_get_by_name_missing_raises_key_error(self) -> None:
        registry = AgentRegistry()
        with pytest.raises(KeyError, match="no agent named"):
            registry.get_by_name("nonexistent")

    def test_list_returns_sorted_ids(self) -> None:
        registry = AgentRegistry()
        for name in ["writer", "recaller", "critic"]:
            registry.register(
                Agent(
                    id=f"id-{name}",
                    name=name,
                    task="t",
                    input="i",
                    output="o",
                    permission=Permission(rules={}),
                )
            )
        assert registry.list_ids() == ["id-critic", "id-recaller", "id-writer"]

    def test_list_names_returns_sorted_names(self) -> None:
        registry = AgentRegistry()
        for name in ["writer", "recaller", "critic"]:
            registry.register(
                Agent(
                    id=f"id-{name}",
                    name=name,
                    task="t",
                    input="i",
                    output="o",
                    permission=Permission(rules={}),
                )
            )
        assert registry.list_names() == ["critic", "recaller", "writer"]

    def test_register_duplicate_id_raises(self) -> None:
        registry = AgentRegistry()
        a1 = Agent(
            id="a-1", name="x", task="t1", input="i", output="o", permission=Permission(rules={})
        )
        a2 = Agent(
            id="a-1", name="y", task="t2", input="i", output="o", permission=Permission(rules={})
        )
        registry.register(a1)
        with pytest.raises(ValueError, match="duplicate agent id"):
            registry.register(a2)

    def test_register_replace_overwrites_at_same_id(self) -> None:
        registry = AgentRegistry()
        a1 = Agent(
            id="a-1", name="x", task="t1", input="i", output="o", permission=Permission(rules={})
        )
        a2 = Agent(
            id="a-1", name="x", task="t2", input="i", output="o", permission=Permission(rules={})
        )
        registry.register(a1)
        registry.register(a2, replace=True)
        assert registry.get("a-1").task == "t2"

    def test_get_by_name_ambiguous_raises(self) -> None:
        registry = AgentRegistry()
        a1 = Agent(
            id="a-1", name="x", task="t1", input="i", output="o", permission=Permission(rules={})
        )
        a2 = Agent(
            id="a-2", name="x", task="t2", input="i", output="o", permission=Permission(rules={})
        )
        registry.register(a1)
        registry.register(a2)
        with pytest.raises(KeyError, match="ambiguous"):
            registry.get_by_name("x")

    def test_has_by_name_false_for_ambiguous(self) -> None:
        registry = AgentRegistry()
        a1 = Agent(
            id="a-1", name="x", task="t1", input="i", output="o", permission=Permission(rules={})
        )
        a2 = Agent(
            id="a-2", name="x", task="t2", input="i", output="o", permission=Permission(rules={})
        )
        registry.register(a1)
        registry.register(a2)
        assert not registry.has_by_name("x")


# ── Built-in agents loading ────────────────────────────────────────────


class TestBuiltinAgents:
    """load_builtin loads the 6 built-in agent yaml files (5 workflow + director)."""

    def test_load_builtin_loads_5_agents(self) -> None:
        registry = build_default_registry()
        names = registry.list_ids()
        assert "recaller" in names
        assert "scout" in names
        assert "writer" in names
        assert "critic" in names
        assert "maintainer" in names
        assert len(names) == 6
        assert set(names) == {"director", "recaller", "scout", "writer", "critic", "maintainer"}

    def test_maintainer_allow_recursive_is_false(self) -> None:
        """maintainer is the only built-in with allow_recursive=False."""
        registry = build_default_registry()
        maintainer = registry.get("maintainer")
        assert maintainer.allow_recursive is False

    def test_other_agents_allow_recursive_is_true(self) -> None:
        registry = build_default_registry()
        for name in ["recaller", "scout", "writer", "critic"]:
            assert registry.get(name).allow_recursive is True, f"{name} should allow_recursive=True"

    def test_writer_permission_cannot_write_worldbook(self) -> None:
        registry = build_default_registry()
        writer = registry.get("writer")
        assert not writer.permission.allowed("write", "worldbook")
        assert writer.permission.allowed("write", "notes")

    def test_maintainer_can_write_state(self) -> None:
        registry = build_default_registry()
        maintainer = registry.get("maintainer")
        assert maintainer.permission.allowed("write", "state")
        assert maintainer.permission.allowed("write", "short_goal")
        assert maintainer.permission.allowed("write", "variables")
        assert maintainer.permission.allowed("write", "character_memory")
        assert maintainer.permission.allowed("write", "notes")

    def test_recaller_tools_are_read_and_file_io(self) -> None:
        registry = build_default_registry()
        recaller = registry.get("recaller")
        assert recaller.tools == ["read", "list_files", "glob_files", "grep_lines", "read_lines"]
        assert "write" not in recaller.tools

    def test_recaller_cannot_write_anything(self) -> None:
        registry = build_default_registry()
        recaller = registry.get("recaller")
        assert recaller.permission.rules.get("write", ()) == ()

    def test_critic_can_write_notes(self) -> None:
        registry = build_default_registry()
        critic = registry.get("critic")
        assert critic.permission.allowed("write", "notes")
        assert not critic.permission.allowed("write", "state")

    def test_scout_is_read_only(self) -> None:
        registry = build_default_registry()
        scout = registry.get("scout")
        assert scout.permission.rules.get("write", ()) == ()
        assert scout.tools == ["read", "list_files", "glob_files", "grep_lines", "read_lines"]


# ── _load_agent_yaml ───────────────────────────────────────────────────


class TestLoadAgentYaml:
    """_load_agent_yaml parses a single agent yaml file."""

    def test_load_minimal_agent_yaml(self, tmp_path: Path) -> None:
        yaml_content = """
name: test_agent
id: test_agent
task: 测试任务
input: 输入
output: 输出
permission:
  read: [state]
  write: []
"""
        path = tmp_path / "test_agent.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        # The minimal yaml omits `tools:`. Pre-populate the module-level
        # default-tools cache so the fallback behaviour is exercised; restore
        # the prior cache state afterwards to keep tests isolated.
        prior = get_default_tools()
        set_default_tools(
            ["read", "write", "list_files", "glob_files", "grep_lines", "read_lines"]
        )
        try:
            agent = _load_agent_yaml(path)
        finally:
            set_default_tools(prior)
        assert agent.name == "test_agent"
        assert agent.id == "test_agent"
        assert agent.task == "测试任务"
        assert agent.allow_recursive is True
        assert agent.tools == ["read", "write", "list_files", "glob_files", "grep_lines", "read_lines"]

    def test_load_agent_yaml_with_allow_recursive_false(self, tmp_path: Path) -> None:
        yaml_content = """
name: maintainer
id: maintainer
task: 维护
input: 输入
output: 输出
permission:
  read: [state]
  write: [state]
allow_recursive: false
"""
        path = tmp_path / "maintainer.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        agent = _load_agent_yaml(path)
        assert agent.allow_recursive is False

    def test_load_agent_yaml_missing_required_field_raises(self, tmp_path: Path) -> None:
        yaml_content = """
name: test_agent
task: 测试任务
"""
        path = tmp_path / "bad.yaml"
        path.write_text(yaml_content, encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field"):
            _load_agent_yaml(path)


# ── Default workflow → tree ────────────────────────────────────────────


class TestDefaultWorkflow:
    """load_default_workflow parses default_workflow.yaml into a valid WorkflowTree."""

    def test_default_workflow_loads_to_valid_tree(self) -> None:
        tree = load_default_workflow()
        assert isinstance(tree, WorkflowTree)
        assert len(tree.all_nodes) == 5

    def test_default_workflow_has_all_agents(self) -> None:
        tree = load_default_workflow()
        agent_names = {n.agent_name for n in tree.all_nodes.values()}
        assert agent_names == {"recaller", "scout", "writer", "critic", "maintainer"}

    def test_default_workflow_root_is_not_director(self) -> None:
        """Director is a system agent NOT in the workflow tree; the root is a workflow agent."""
        tree = load_default_workflow()
        assert tree.root.agent_name != "director"
        assert tree.root.agent_name in ("recaller", "scout")
        assert tree.root.depth == 0

    def test_default_workflow_writer_has_two_predecessors(self) -> None:
        """writer receives from both recaller and scout → has dependency_ids."""
        tree = load_default_workflow()
        writer = next(n for n in tree.all_nodes.values() if n.agent_name == "writer")
        assert writer.parent_id in {"recaller", "scout"}
        assert len(writer.dependency_ids) == 1
        other = "scout" if writer.parent_id == "recaller" else "recaller"
        assert writer.dependency_ids[0] == other


# ── build_default_registry integration ─────────────────────────────────


class TestBuildDefaultRegistry:
    """build_default_registry produces a working registry + workflow."""

    def test_build_default_registry_works(self) -> None:
        registry = build_default_registry()
        assert isinstance(registry, AgentRegistry)
        assert len(registry.list_ids()) == 6

    def test_registry_and_workflow_together(self) -> None:
        """Every agent_name in the default workflow exists in the registry."""
        registry = build_default_registry()
        tree = load_default_workflow()
        for node in tree.all_nodes.values():
            if node.agent_name == "director":
                continue
            assert registry.has_by_name(node.agent_name), f"agent {node.agent_name!r} missing from registry"
