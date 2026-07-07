"""Tests for app.agents.agent — Agent dataclass with all 12 attributes (11 refactor_guide + allow_recursive)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace

import pytest

from app.agents.agent import Agent
from app.agents.runners.base import RunnerAgent
from app.runtime.permission import Permission, parse_permission


def _make_permission(
    raw: dict[str, list[str]] | None = None,
) -> Permission:
    """Build a Permission for tests; defaults to a read-state / write-short_goal scope."""
    if raw is None:
        raw = {"read": ["state"], "write": ["short_goal"]}
    return parse_permission({k: v for k, v in raw.items()})


def _make_agent(**overrides: object) -> Agent:
    """Build a fully-populated Agent for tests; override fields via kwargs."""
    defaults: dict[str, object] = {
        "id": "director-001",
        "name": "director",
        "task": "决策与任务分配",
        "input": "当前状态、短期目标、世界书摘要",
        "output": "JSON 格式的下一步行动指令",
        "permission": _make_permission(),
        "model": "premium",
        "skills": ["scheduling"],
        "tools": ["read", "search", "write"],
        "head": None,
        "tail": None,
        "allow_recursive": True,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


_AGENT_FIELD_NAMES = {f.name for f in fields(Agent)}


# ── 12 attributes present ──────────────────────────────────────────────


class TestAgentHasAllTwelveAttributes:
    """Agent must carry all 12 attributes: 11 refactor_guide:62-73 + allow_recursive (todo 18)."""

    def test_has_id(self) -> None:
        assert "id" in _AGENT_FIELD_NAMES

    def test_has_name(self) -> None:
        assert "name" in _AGENT_FIELD_NAMES

    def test_has_task(self) -> None:
        assert "task" in _AGENT_FIELD_NAMES

    def test_has_input(self) -> None:
        assert "input" in _AGENT_FIELD_NAMES

    def test_has_output(self) -> None:
        assert "output" in _AGENT_FIELD_NAMES

    def test_has_permission(self) -> None:
        assert "permission" in _AGENT_FIELD_NAMES

    def test_has_model(self) -> None:
        assert "model" in _AGENT_FIELD_NAMES

    def test_has_skills(self) -> None:
        assert "skills" in _AGENT_FIELD_NAMES

    def test_has_tools(self) -> None:
        assert "tools" in _AGENT_FIELD_NAMES

    def test_has_head(self) -> None:
        assert "head" in _AGENT_FIELD_NAMES

    def test_has_tail(self) -> None:
        assert "tail" in _AGENT_FIELD_NAMES

    def test_has_allow_recursive(self) -> None:
        assert "allow_recursive" in _AGENT_FIELD_NAMES

    def test_field_count_is_twelve(self) -> None:
        assert len(_AGENT_FIELD_NAMES) == 12

    def test_all_twelve_fields_populated(self) -> None:
        agent = _make_agent()
        assert agent.id == "director-001"
        assert agent.name == "director"
        assert agent.task == "决策与任务分配"
        assert agent.input == "当前状态、短期目标、世界书摘要"
        assert agent.output == "JSON 格式的下一步行动指令"
        assert isinstance(agent.permission, Permission)
        assert agent.model == "premium"
        assert agent.skills == ["scheduling"]
        assert agent.tools == ["read", "search", "write"]
        assert agent.head is None
        assert agent.tail is None
        assert agent.allow_recursive is True


# ── id validation ──────────────────────────────────────────────────────


class TestAgentIdValidation:
    """id is read-only, created-init, unique — validated non-empty."""

    def test_empty_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Agent.id must be non-empty"):
            _make_agent(id="")

    def test_whitespace_only_id_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Agent.id must be non-empty"):
            _make_agent(id="   ")

    def test_non_empty_id_accepted(self) -> None:
        agent = _make_agent(id="agent-x")
        assert agent.id == "agent-x"

    def test_id_is_read_only_via_frozen(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.id = "changed"  # type: ignore[misc]


# ── frozen dataclass ───────────────────────────────────────────────────


class TestAgentIsFrozen:
    """Agent is frozen — direct field mutation raises FrozenInstanceError."""

    def test_cannot_mutate_name(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.name = "changed"  # type: ignore[misc]

    def test_cannot_mutate_task(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.task = "changed"  # type: ignore[misc]

    def test_cannot_mutate_input(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.input = "changed"  # type: ignore[misc]

    def test_cannot_mutate_output(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.output = "changed"  # type: ignore[misc]

    def test_cannot_mutate_permission(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.permission = _make_permission({"read": ["worldbook"]})  # type: ignore[misc]

    def test_cannot_mutate_model(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.model = "cheap"  # type: ignore[misc]

    def test_cannot_mutate_skills(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.skills = ["new_skill"]  # type: ignore[misc]

    def test_cannot_mutate_tools(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.tools = ["read"]  # type: ignore[misc]

    def test_cannot_mutate_head(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.head = "new head"  # type: ignore[misc]

    def test_cannot_mutate_tail(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.tail = "new tail"  # type: ignore[misc]

    def test_cannot_mutate_allow_recursive(self) -> None:
        agent = _make_agent()
        with pytest.raises(FrozenInstanceError):
            agent.allow_recursive = False  # type: ignore[misc]


# ── replace() returns new Agent ─────────────────────────────────────────


class TestAgentReplace:
    """replace() returns a new Agent with changed field; id is never changed."""

    def test_replace_returns_new_instance(self) -> None:
        agent = _make_agent()
        new_agent = replace(agent, name="scout")
        assert new_agent is not agent
        assert new_agent.name == "scout"

    def test_replace_preserves_id(self) -> None:
        """id must NEVER change — replace() does not touch it unless explicitly set."""
        agent = _make_agent(id="director-001")
        new_agent = replace(agent, name="scout", task="侦察")
        assert new_agent.id == "director-001"

    def test_replace_can_change_task(self) -> None:
        agent = _make_agent()
        new_agent = replace(agent, task="写作正文")
        assert new_agent.task == "写作正文"
        assert agent.task == "决策与任务分配"

    def test_replace_can_change_model(self) -> None:
        agent = _make_agent(model="premium")
        new_agent = replace(agent, model="cheap")
        assert new_agent.model == "cheap"
        assert agent.model == "premium"

    def test_replace_can_change_skills(self) -> None:
        agent = _make_agent(skills=["scheduling"])
        new_agent = replace(agent, skills=["scheduling", "dice_roll"])
        assert new_agent.skills == ["scheduling", "dice_roll"]
        assert agent.skills == ["scheduling"]

    def test_replace_can_change_permission(self) -> None:
        agent = _make_agent()
        new_perm = _make_permission({"read": ["worldbook"], "write": ["notes"]})
        new_agent = replace(agent, permission=new_perm)
        assert new_agent.permission is new_perm
        assert agent.permission is not new_perm

    def test_replace_can_change_head_and_tail(self) -> None:
        agent = _make_agent(head=None, tail=None)
        new_agent = replace(agent, head="HEAD", tail="TAIL")
        assert new_agent.head == "HEAD"
        assert new_agent.tail == "TAIL"
        assert agent.head is None
        assert agent.tail is None

    def test_replace_can_change_allow_recursive(self) -> None:
        agent = _make_agent(allow_recursive=True)
        new_agent = replace(agent, allow_recursive=False)
        assert new_agent.allow_recursive is False
        assert agent.allow_recursive is True


# ── RunnerAgent Protocol structural compatibility ──────────────────────


class TestAgentSatisfiesRunnerAgentProtocol:
    """Agent must structurally satisfy RunnerAgent (id: str, model: str | None)."""

    def test_isinstance_runner_agent(self) -> None:
        """runtime_checkable Protocol — isinstance works for structural match."""
        agent = _make_agent()
        assert isinstance(agent, RunnerAgent)

    def test_isinstance_runner_agent_with_none_model(self) -> None:
        agent = _make_agent(model=None)
        assert isinstance(agent, RunnerAgent)

    def test_id_is_str(self) -> None:
        agent = _make_agent()
        assert isinstance(agent.id, str)

    def test_model_is_str_or_none(self) -> None:
        agent_with_model = _make_agent(model="premium")
        agent_without_model = _make_agent(model=None)
        assert isinstance(agent_with_model.model, str)
        assert agent_without_model.model is None


# ── Default tools ──────────────────────────────────────────────────────


class TestAgentDefaultTools:
    """Default tools = ['read', 'search', 'write'] — the unified tool set."""

    def test_default_tools_is_read_search_write(self) -> None:
        agent = Agent(
            id="a",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert agent.tools == ["read", "search", "write"]

    def test_default_tools_is_a_new_list_each_instance(self) -> None:
        """default_factory must produce a fresh list per instance (no shared mutable default)."""
        a1 = Agent(
            id="a1",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        a2 = Agent(
            id="a2",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert a1.tools == a2.tools
        assert a1.tools is not a2.tools

    def test_custom_tools_override_default(self) -> None:
        agent = _make_agent(tools=["read"])
        assert agent.tools == ["read"]


# ── Default skills ─────────────────────────────────────────────────────


class TestAgentDefaultSkills:
    """Default skills is an empty list (inherits global, dynamically mountable)."""

    def test_default_skills_is_empty_list(self) -> None:
        agent = Agent(
            id="a",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert agent.skills == []

    def test_default_skills_is_a_new_list_each_instance(self) -> None:
        a1 = Agent(
            id="a1",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        a2 = Agent(
            id="a2",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert a1.skills is not a2.skills


# ── Default head / tail ────────────────────────────────────────────────


class TestAgentDefaultHeadTail:
    """head / tail default to None (inherits global, nullable)."""

    def test_default_head_is_none(self) -> None:
        agent = Agent(
            id="a",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert agent.head is None

    def test_default_tail_is_none(self) -> None:
        agent = Agent(
            id="a",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert agent.tail is None


# ── Default model ──────────────────────────────────────────────────────


class TestAgentDefaultModel:
    """model defaults to None (nullable — runner default applies)."""

    def test_default_model_is_none(self) -> None:
        agent = Agent(
            id="a",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert agent.model is None


# ── Permission integration ─────────────────────────────────────────────


class TestAgentPermissionField:
    """Agent.permission uses the Permission class from app/runtime/permission.py."""

    def test_permission_is_permission_instance(self) -> None:
        agent = _make_agent()
        assert isinstance(agent.permission, Permission)

    def test_permission_can_be_empty(self) -> None:
        """An agent with no permission scope is valid (deny-all context isolation)."""
        empty_perm = parse_permission({})
        agent = _make_agent(permission=empty_perm)
        assert agent.permission.rules == {}


# ── allow_recursive (12th attribute, todo 18) ──────────────────────────


class TestAgentAllowRecursive:
    """allow_recursive: runtime-only flag, default True, serializable to yaml."""

    def test_default_allow_recursive_is_true(self) -> None:
        agent = Agent(
            id="a",
            name="n",
            task="t",
            input="i",
            output="o",
            permission=_make_permission(),
        )
        assert agent.allow_recursive is True

    def test_allow_recursive_can_be_false(self) -> None:
        agent = _make_agent(allow_recursive=False)
        assert agent.allow_recursive is False

    def test_allow_recursive_is_bool(self) -> None:
        agent = _make_agent()
        assert isinstance(agent.allow_recursive, bool)
