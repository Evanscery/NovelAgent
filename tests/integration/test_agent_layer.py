"""Integration tests for the RoundExecutor-based agent-layer architecture.

Verifies the CORRECT design (per refactor_guide:92-101):

* The director is a *system agent* -- an :class:`Agent` loaded from
  ``director.yaml`` by the registry, NOT a special ``Director`` class.
* :class:`RoundExecutor` (in ``app/runtime/round_executor.py``) is the
  runtime loop: it sends the director prompt, parses the director's
  ``tool_calls``, dispatches them (``call_agent`` / ``await`` /
  ``finalize`` / ``read`` / ``search`` / ``write``), feeds the results
  back, and loops until ``finalize`` or budget exhaustion.
* The workflow tree is injected into the director's prompt as context
  (via :func:`generate_flow_sequence`) -- the runtime does NOT traverse
  it. The director decides via LLM which agents to call.
* Budget + recursion depth are soft constraints enforced by
  :class:`RoundExecutor`.

NO test constructs a ``Director()`` object. NO test calls
``director.run_round()``. All LLM calls are mocked via
:class:`MockRunner` or custom mock runners.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from app.agents.registry import build_default_registry
from app.canvas.workflow_loader import load_workflow
from app.data.project_repo import ProjectRepo
from app.data.store import ResourceStore
from app.runtime.budget import BudgetTracker
from app.runtime.permission import (
    PermissionDenied,
    inject_into_tools,
)
from app.runtime.round_executor import (
    RoundExecutor,
    RoundResult,
)
from app.runtime.runners.base import (
    AgentResponse,
    AgentRunner,
    RunnerAgent,
    TokenUsage,
    ToolCall,
)
from app.runtime.runners.mock_runner import MockRunner
from app.runtime.runtime import Runtime
from app.runtime.tool_dispatcher import (
    ScopedTools as ScopedToolsProtocol,
)
from app.runtime.tool_dispatcher import ToolDispatcher, UnknownToolError

DEFAULT_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "canvas"
    / "default_workflow.yaml"
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A freshly git-initialised project root."""
    root = tmp_path / "proj"
    root.mkdir()
    ProjectRepo(root).init()
    return root


@pytest.fixture
def store(project: Path) -> ResourceStore:
    return ResourceStore(project)


def _seed_project(store: ResourceStore) -> dict[str, str]:
    """Seed the project with real State + Outline + ShortGoal + Notes + Facts content.

    Returns a dict of resource_type -> seeded filename for assertions.
    """
    r_state = store.create_resource("state", "state-001")
    store.write(r_state, "current.md", "# 当前状态\n\n场景：城郊破庙，深夜。主角林安刚觉醒「时回」能力。")

    r_outline = store.create_resource("outline", "outline-001")
    store.write(r_outline, "arc.md", "# 主线\n\n第一卷：觉醒。主角发现能力，导师白川登场。")

    r_short_goal = store.create_resource("short_goal", "sg-001")
    store.write(r_short_goal, "turn1_plan.md", "# 本回合计划\n\n1. 揭示主角能力\n2. 引入导师角色")

    r_notes = store.create_resource("notes", "notes-001")
    store.write(r_notes, "observations.md", "# 创作笔记\n\n节奏需要放慢，伏笔待埋。")

    r_facts = store.create_resource("facts", "facts-001")
    store.write(r_facts, "truths.md", "# 客观事实\n\n世界存在三大帝国。")

    return {
        "state": "current.md",
        "outline": "arc.md",
        "short_goal": "turn1_plan.md",
        "notes": "observations.md",
        "facts": "truths.md",
    }


# ── 1. Registry loads 6 agents including director ────────────────────────


def test_build_default_registry_loads_six_agents() -> None:
    """``build_default_registry()`` loads all 6 built-in agents
    (director + recaller + scout + writer + critic + maintainer)."""
    registry = build_default_registry()
    names = registry.list_ids()
    assert set(names) == {"director", "recaller", "scout", "writer", "critic", "maintainer"}


# ── 2. Default workflow has 5 nodes (no director/root node) ──────────────


def test_default_workflow_has_five_nodes() -> None:
    """``default_workflow.yaml`` compiles to a 5-node tree:
    recaller + scout + writer + critic + maintainer. The director is a
    system agent and does NOT appear as a workflow node."""
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)
    assert tree.node_count() == 5
    agent_names = [n.agent_name for n in tree.all_nodes.values()]
    assert "director" not in agent_names
    assert set(agent_names) == {"recaller", "scout", "writer", "critic", "maintainer"}


# ── 3. Director agent has correct tools ──────────────────────────────────


def test_director_agent_has_call_agent_and_await_tools() -> None:
    """The director agent (loaded from ``director.yaml``) has
    ``call_agent`` and ``await`` (its primary orchestration tools) plus
    the standard ``read`` tool."""
    registry = build_default_registry()
    director = registry.get("director")
    assert "call_agent" in director.tools
    assert "await" in director.tools
    assert "read" in director.tools  # also has standard tools


# ── 4. RoundExecutor executes a round with MockRunner ────────────────────


class _DirectorMockRunner(AgentRunner):
    """Mock runner that simulates director calling call_agent then finalize.

    First director turn: director decides to call ``recaller``.
    Second director turn: director finalizes the round.

    Sub-agent calls (``recaller``) are delegated to a wrapped sub-runner
    (typically :class:`MockRunner`).
    """

    def __init__(self, sub_runner: AgentRunner) -> None:
        self._sub = sub_runner
        self._call_count = 0

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        if getattr(agent, "name", "") == "director":
            self._call_count += 1
            if self._call_count == 1:
                # First turn: director decides to call recaller.
                return AgentResponse(
                    text="我需要先召回数据",
                    tool_calls=[
                        ToolCall(
                            name="call_agent",
                            args={"agent_name": "recaller", "prompt": "召回相关记忆"},
                        )
                    ],
                    usage=TokenUsage(prompt_tokens=100, completion_tokens=20),
                )
            else:
                # Second turn: director finalizes.
                return AgentResponse(
                    text="回合完成",
                    tool_calls=[ToolCall(name="finalize", args={})],
                    usage=TokenUsage(prompt_tokens=50, completion_tokens=10),
                )
        # Sub-agent calls delegate to the wrapped runner.
        return await self._sub.run(agent, prompt)


@pytest.mark.asyncio
async def test_round_executor_calls_sub_agent_via_tool_call(
    project: Path, store: ResourceStore
) -> None:
    """RoundExecutor dispatches a ``call_agent`` tool call from the
    director to ``recaller``, then the director finalizes.

    The round ends with ``finalize_reason == "explicit_finalize"``,
    ``recaller`` appears in ``completed_agents``, and tokens were
    accumulated from both the director and the sub-agent.
    """
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)

    sub_runner = MockRunner()
    runner = _DirectorMockRunner(sub_runner)
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    budget = BudgetTracker(max_iterations=10, max_tokens=10_000, max_tool_calls=50)

    executor = RoundExecutor(runtime, runner, registry, budget)
    result = await executor.execute_round(director=director, tree=tree, context="test context")

    assert result.finalize_reason == "explicit_finalize"
    assert "recaller" in result.completed_agents
    assert result.total_tokens > 0


# ── 5. Budget exhaustion test ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_round_executor_budget_exhaustion(
    project: Path, store: ResourceStore
) -> None:
    """With ``max_iterations=1``, the budget is exhausted after the
    first director turn. The round ends with
    ``finalize_reason == "budget_exhausted"`` and no sub-agent was
    called (the director's ``call_agent`` tool call could not complete
    before the budget ran out)."""
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)

    sub_runner = MockRunner()
    runner = _DirectorMockRunner(sub_runner)
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    budget = BudgetTracker(max_iterations=1, max_tokens=10_000, max_tool_calls=50)

    executor = RoundExecutor(runtime, runner, registry, budget)
    result = await executor.execute_round(director=director, tree=tree, context="test context")

    assert result.finalize_reason == "budget_exhausted"
    # The director was called once (the first turn consumed the iteration).
    assert "director" in result.completed_agents


# ── 6. Recursion control test ────────────────────────────────────────────


class _DoubleCallRunner(AgentRunner):
    """Mock runner where the director calls the same agent twice.

    First turn: call ``recaller`` (call_count=1, allowed).
    Second turn: call ``recaller`` again (call_count=2). Whether this
    is allowed depends on ``recaller.allow_recursive``.
    Third turn: finalize.
    """

    def __init__(self, sub_runner: AgentRunner) -> None:
        self._sub = sub_runner
        self._call_count = 0

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        if getattr(agent, "name", "") == "director":
            self._call_count += 1
            if self._call_count == 1:
                return AgentResponse(
                    text="第一次召回",
                    tool_calls=[
                        ToolCall(
                            name="call_agent",
                            args={"agent_name": "recaller", "prompt": "召回"},
                        )
                    ],
                    usage=TokenUsage(prompt_tokens=50, completion_tokens=10),
                )
            elif self._call_count == 2:
                return AgentResponse(
                    text="再次召回",
                    tool_calls=[
                        ToolCall(
                            name="call_agent",
                            args={"agent_name": "recaller", "prompt": "再次召回"},
                        )
                    ],
                    usage=TokenUsage(prompt_tokens=50, completion_tokens=10),
                )
            else:
                return AgentResponse(
                    text="完成",
                    tool_calls=[ToolCall(name="finalize", args={})],
                    usage=TokenUsage(prompt_tokens=30, completion_tokens=5),
                )
        return await self._sub.run(agent, prompt)


@pytest.mark.asyncio
async def test_round_executor_recursive_call_allowed_when_flag_true(
    project: Path, store: ResourceStore
) -> None:
    """When ``recaller.allow_recursive=True`` (per its builtin yaml),
    calling recaller twice is allowed. The second call is recorded in
    ``recursive_calls`` and the round finalizes normally."""
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)

    sub_runner = MockRunner()
    runner = _DoubleCallRunner(sub_runner)
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    budget = BudgetTracker(max_iterations=20, max_tokens=10_000, max_tool_calls=50)

    executor = RoundExecutor(runtime, runner, registry, budget)
    result = await executor.execute_round(director=director, tree=tree, context="test")

    # recaller.allow_recursive is True per builtin yaml.
    recaller = registry.get("recaller")
    assert recaller.allow_recursive is True

    assert result.finalize_reason == "explicit_finalize"
    # recaller was called twice -> recorded as a recursive call.
    assert len(result.recursive_calls) == 1
    assert result.recursive_calls[0].agent == "recaller"


@pytest.mark.asyncio
async def test_round_executor_recursive_call_rejected_when_flag_false(
    project: Path, store: ResourceStore
) -> None:
    """When the target agent's ``allow_recursive=False`` and it is
    called twice, the second call is rejected with reason
    ``"agent does not allow recursive call"``.

    We register a clone of ``recaller`` with ``allow_recursive=False``
    under a distinct name so the director's second ``call_agent`` to it
    is rejected."""
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)

    # Clone recaller with allow_recursive=False, registered under a new
    # name so the director targets it.
    from dataclasses import replace

    recaller = registry.get("recaller")
    no_recurse_recaller = replace(
        recaller, id="recaller-norecurse", name="recaller_norecurse", allow_recursive=False
    )
    registry.register(no_recurse_recaller)

    class _DoubleCallNoRecurseRunner(AgentRunner):
        def __init__(self, sub_runner: AgentRunner) -> None:
            self._sub = sub_runner
            self._call_count = 0

        async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
            if getattr(agent, "name", "") == "director":
                self._call_count += 1
                if self._call_count <= 2:
                    return AgentResponse(
                        text=f"调用 {self._call_count}",
                        tool_calls=[
                            ToolCall(
                                name="call_agent",
                                args={
                                    "agent_name": "recaller_norecurse",
                                    "prompt": "召回",
                                },
                            )
                        ],
                        usage=TokenUsage(prompt_tokens=40, completion_tokens=8),
                    )
                return AgentResponse(
                    text="完成",
                    tool_calls=[ToolCall(name="finalize", args={})],
                    usage=TokenUsage(prompt_tokens=20, completion_tokens=5),
                )
            return await self._sub.run(agent, prompt)

    sub_runner = MockRunner()
    runner = _DoubleCallNoRecurseRunner(sub_runner)
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    budget = BudgetTracker(max_iterations=20, max_tokens=10_000, max_tool_calls=50)

    executor = RoundExecutor(runtime, runner, registry, budget)
    result = await executor.execute_round(director=director, tree=tree, context="test")

    # The second call to recaller_norecurse (call_count=2) was rejected.
    rejected_for_norecurse = [
        r for r in result.rejected_calls if r.agent == "recaller_norecurse"
    ]
    assert len(rejected_for_norecurse) == 1
    assert rejected_for_norecurse[0].reason == "agent does not allow recursive call"


# ── 7. Permission isolation test ─────────────────────────────────────────


def test_writer_permission_denied_on_facts(
    project: Path, store: ResourceStore, 
) -> None:
    """Writer's ``read`` permission does NOT cover ``facts``
    (writer.read = outline/short_goal/state/worldbook/character_memory/
    notes). Reading facts raises :class:`PermissionDenied`."""
    _seed_project(store)
    registry = build_default_registry()
    writer = registry.get("writer")
    scoped = inject_into_tools(store, writer.permission)

    # Allowed: writer can read state.
    state_text = scoped.read("state", "current.md")
    assert "城郊破庙" in state_text

    # Disallowed: writer cannot read facts.
    with pytest.raises(PermissionDenied) as exc_info:
        scoped.read("facts", "truths.md")
    assert exc_info.value.action == "read"
    assert exc_info.value.resource_type == "facts"
    assert "facts" not in writer.permission.rules.get("read", ())


# ── 8. Unknown tool rejection ────────────────────────────────────────────


class _UnknownToolRunner(AgentRunner):
    """Mock runner where the director calls a non-existent tool ``foo``."""

    def __init__(self) -> None:
        self._call_count = 0

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        if getattr(agent, "name", "") == "director":
            self._call_count += 1
            if self._call_count == 1:
                return AgentResponse(
                    text="调用未知工具",
                    tool_calls=[ToolCall(name="foo", args={})],
                    usage=TokenUsage(prompt_tokens=30, completion_tokens=5),
                )
            return AgentResponse(
                text="完成",
                tool_calls=[ToolCall(name="finalize", args={})],
                usage=TokenUsage(prompt_tokens=20, completion_tokens=5),
            )
        return AgentResponse(text="sub", usage=TokenUsage(10, 5))


@pytest.mark.asyncio
async def test_round_executor_rejects_unknown_tool(
    project: Path, store: ResourceStore
) -> None:
    """When the director calls a non-existent tool ``foo``, the call is
    rejected and recorded in ``rejected_calls`` with reason
    ``"unknown_tool: foo"``. The round continues and the director can
    finalize on the next turn."""
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)

    runner = _UnknownToolRunner()
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    budget = BudgetTracker(max_iterations=10, max_tokens=10_000, max_tool_calls=50)

    # Unknown-tool detection is owned by the ToolDispatcher, so the
    # executor needs a real tool surface (as production wiring provides).
    scoped = inject_into_tools(store, director.permission)
    dispatcher = ToolDispatcher(cast(ScopedToolsProtocol, scoped))
    executor = RoundExecutor(runtime, runner, registry, budget, director_tools=dispatcher)
    result = await executor.execute_round(director=director, tree=tree, context="test")

    # The unknown tool call was rejected.
    unknown_rejected = [r for r in result.rejected_calls if "unknown_tool" in r.reason]
    assert len(unknown_rejected) == 1
    assert "foo" in unknown_rejected[0].reason
    # The director finalized on the next turn.
    assert result.finalize_reason == "explicit_finalize"


# ── Bonus: standard tools dispatch via ToolDispatcher ────────────────────


def test_director_standard_tools_dispatch_via_tool_dispatcher(
    project: Path, store: ResourceStore
) -> None:
    """The director's ``read``/``search``/``write`` tool calls are
    dispatched to a :class:`ToolDispatcher` wrapping the director's
    :class:`ScopedTools`. read returns real content; an unknown tool
    raises :class:`UnknownToolError`."""
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    scoped = inject_into_tools(store, director.permission)
    dispatcher = ToolDispatcher(cast(ScopedToolsProtocol, scoped))

    # read(state) -> real seeded content (director can read state).
    result = dispatcher.dispatch(
        ToolCall(name="read", args={"resource_type": "state", "filename": "current.md"})
    )
    assert result.ok is True
    assert "城郊破庙" in str(result.output)

    # Unknown tool -> UnknownToolError.
    with pytest.raises(UnknownToolError, match="Unknown tool: foo"):
        dispatcher.dispatch(ToolCall(name="foo", args={}))


# ── Bonus: RoundResult is a dataclass with expected fields ───────────────


@pytest.mark.asyncio
async def test_round_result_has_expected_fields(
    project: Path, store: ResourceStore
) -> None:
    """RoundResult is a dataclass with completed_agents,
    recursive_calls, finalize_reason, total_tokens, rejected_calls,
    director_text -- all populated by ``execute_round``."""
    _seed_project(store)
    registry = build_default_registry()
    director = registry.get("director")
    tree = load_workflow(DEFAULT_WORKFLOW_PATH)

    sub_runner = MockRunner()
    runner = _DirectorMockRunner(sub_runner)
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    budget = BudgetTracker(max_iterations=10, max_tokens=10_000, max_tool_calls=50)

    executor = RoundExecutor(runtime, runner, registry, budget)
    result = await executor.execute_round(director=director, tree=tree, context="test")

    assert isinstance(result, RoundResult)
    assert isinstance(result.completed_agents, list)
    assert isinstance(result.recursive_calls, list)
    assert isinstance(result.rejected_calls, list)
    assert isinstance(result.finalize_reason, str)
    assert isinstance(result.total_tokens, int)
    assert isinstance(result.director_text, str)
    assert result.finalize_reason == "explicit_finalize"
