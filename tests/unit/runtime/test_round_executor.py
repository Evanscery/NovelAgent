"""Unit tests for RoundExecutor — the runtime-layer tool-call loop.

Tests RoundExecutor in isolation against mock runners and a mock
registry. NO real LLM calls. NO ``Director`` class. The director is an
:class:`Agent` instance; RoundExecutor drives it in a tool-call loop.

Covers:

* Loop correctness: director -> tool call -> result -> director -> finalize.
* Budget exhaustion (iteration ceiling stops the round).
* Recursion control: ``allow_recursive`` flag + depth constraint.
* Standard tools (read/search/write) dispatched to :class:`ToolDispatcher`.
* ``call_agent`` resolves the target from the registry.
* ``finalize`` ends the round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest

from app.agents.agent import Agent
from app.agents.registry import AgentRegistry
from app.runtime.runners.base import (
    AgentResponse,
    AgentRunner,
    RunnerAgent,
    TokenUsage,
    ToolCall,
)
from app.runtime.runners.mock_runner import MockRunner
from app.agents.workflow import TreeNode, WorkflowTree
from app.runtime.budget import BudgetTracker
from app.runtime.permission import Permission, parse_permission
from app.runtime.round_executor import RoundExecutor
from app.runtime.runtime import Runtime
from app.runtime.tool_dispatcher import ScopedTools as ScopedToolsProtocol
from app.runtime.tool_dispatcher import ToolDispatcher

# ── Test doubles ─────────────────────────────────────────────────────────


def _make_agent(
    name: str = "director",
    *,
    allow_recursive: bool = True,
    tools: list[str] | None = None,
    permission: Permission | None = None,
) -> Agent:
    """Build a minimal agent for RoundExecutor tests."""
    if permission is None:
        permission = parse_permission({"read": ["state"], "write": []})
    return Agent(
        id=name,
        name=name,
        task="test task",
        input="test input",
        output="test output",
        permission=permission,
        model=None,
        skills=[],
        tools=tools if tools is not None else ["read", "search", "write", "call_agent", "await"],
        head=None,
        tail=None,
        allow_recursive=allow_recursive,
    )


def _make_registry(*agents: Agent) -> AgentRegistry:
    """Build a registry pre-loaded with the given agents."""
    reg = AgentRegistry()
    for a in agents:
        reg.register(a)
    return reg


def _make_tree() -> WorkflowTree:
    """Build a minimal 2-node tree: recaller -> writer.

    The director is NOT a node (it is a system agent). The tree is
    context for the director's prompt only; RoundExecutor does not
    traverse it.
    """
    recaller = TreeNode(
        id="recaller",
        agent_name="recaller",
        description="召回数据",
        params={},
        depth=0,
        parent_id=None,
    )
    writer = TreeNode(
        id="writer",
        agent_name="writer",
        description="文本生成",
        params={},
        depth=1,
        parent_id="recaller",
    )
    recaller.children.append(writer)
    return WorkflowTree(root=recaller, all_nodes={"recaller": recaller, "writer": writer})


@dataclass
class _StubAgent:
    """Minimal agent satisfying the RunnerAgent protocol (for runners)."""

    id: str
    name: str = ""
    model: str | None = None


class _ScriptedRunner(AgentRunner):
    """Runner whose director responses are scripted by a list of tool-call batches.

    Each entry of ``director_batches`` is a list of :class:`ToolCall`
    objects the director returns on successive turns. Sub-agent calls
    are delegated to a wrapped sub-runner (default :class:`MockRunner`).
    """

    def __init__(
        self,
        director_batches: list[list[ToolCall]],
        sub_runner: AgentRunner | None = None,
        director_texts: list[str] | None = None,
    ) -> None:
        self._batches = list(director_batches)
        self._sub = sub_runner if sub_runner is not None else MockRunner()
        self._texts = director_texts or [f"turn {i + 1}" for i in range(len(director_batches))]
        self._call_count = 0
        self.sub_calls: list[tuple[str, str]] = []

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        name = getattr(agent, "name", "")
        if name == "director":
            idx = min(self._call_count, len(self._batches) - 1)
            batch = self._batches[idx]
            text = self._texts[idx] if idx < len(self._texts) else f"turn {idx + 1}"
            self._call_count += 1
            return AgentResponse(
                text=text,
                tool_calls=batch,
                usage=TokenUsage(prompt_tokens=100, completion_tokens=20),
            )
        self.sub_calls.append((name, prompt))
        return await self._sub.run(agent, prompt)


def _make_executor(
    registry: AgentRegistry,
    runner: AgentRunner,
    budget: BudgetTracker | None = None,
    director_tools: ToolDispatcher | None = None,
    max_depth: int = 1,
) -> RoundExecutor:
    """Build a RoundExecutor with a standard Runtime and the given parts."""
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
    return RoundExecutor(
        runtime=runtime,
        runner=runner,
        registry=registry,
        budget=budget if budget is not None else BudgetTracker(max_iterations=20, max_tokens=10_000, max_tool_calls=50),
        director_tools=director_tools,
        maximal_recursive_calling_depth=max_depth,
    )


# ── 1. Loop correctness: director -> call_agent -> finalize ──────────────


@pytest.mark.asyncio
async def test_loop_director_calls_agent_then_finalizes() -> None:
    """Director calls ``recaller`` then finalizes. The executor loops
    twice (turn 1: call_agent, turn 2: finalize). ``recaller`` appears
    in ``completed_agents`` and ``finalize_reason`` is
    ``"explicit_finalize"``."""
    director = _make_agent("director")
    recaller = _make_agent("recaller")
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "召回"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "explicit_finalize"
    assert "director" in result.completed_agents
    assert "recaller" in result.completed_agents
    assert result.total_tokens > 0
    # The sub-agent was actually called.
    assert len(runner.sub_calls) == 1
    assert runner.sub_calls[0][0] == "recaller"


@pytest.mark.asyncio
async def test_loop_director_with_no_tool_calls_ends_after_one_turn() -> None:
    """When the director returns no tool calls, the round ends
    immediately with ``finalize_reason == "all_nodes_done"``."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    runner = _ScriptedRunner(director_batches=[[]], director_texts=["plain answer"])
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "all_nodes_done"
    assert result.director_text == "plain answer"
    assert "director" in result.completed_agents


# ── 2. Budget exhaustion ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_round() -> None:
    """With ``max_iterations=1``, the budget is exhausted after the
    first director turn. The round ends with
    ``finalize_reason == "budget_exhausted"``."""
    director = _make_agent("director")
    recaller = _make_agent("recaller")
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "召回"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    budget = BudgetTracker(max_iterations=1, max_tokens=10_000, max_tool_calls=50)
    executor = _make_executor(registry, runner, budget=budget)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "budget_exhausted"
    # The director was called once before budget ran out.
    assert "director" in result.completed_agents
    # The sub-agent call could not complete (budget checked before dispatch).
    assert "recaller" not in result.completed_agents


# ── 3. Recursion control ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recursion_allowed_when_flag_true() -> None:
    """Calling ``recaller`` twice with ``allow_recursive=True`` is
    allowed. The second call is recorded in ``recursive_calls``."""
    director = _make_agent("director")
    recaller = _make_agent("recaller", allow_recursive=True)
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "first"})],
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "second"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "explicit_finalize"
    assert len(result.recursive_calls) == 1
    assert result.recursive_calls[0].agent == "recaller"
    # Both calls completed.
    assert result.completed_agents.count("recaller") == 2


@pytest.mark.asyncio
async def test_recursion_rejected_when_flag_false() -> None:
    """Calling an agent with ``allow_recursive=False`` twice is rejected
    on the second call with reason
    ``"agent does not allow recursive call"``."""
    director = _make_agent("director")
    recaller = _make_agent("recaller", allow_recursive=False)
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "first"})],
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "second"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    # First call succeeded, second was rejected.
    assert result.finalize_reason == "explicit_finalize"
    rejected = [r for r in result.rejected_calls if r.agent == "recaller"]
    assert len(rejected) == 1
    assert rejected[0].reason == "agent does not allow recursive call"
    # Only one recaller completion (the first call).
    assert result.completed_agents.count("recaller") == 1


@pytest.mark.asyncio
async def test_recursion_rejected_on_depth_violation() -> None:
    """A call_agent that would exceed the depth limit is rejected with
    ``"cross-stage recursive call rejected"``.

    The executor's depth constraint limits how deep the director may
    reach: a forward call to ``director_depth + 1`` is allowed when
    ``max_depth >= 1``. With ``max_depth=0``, even a single-level
    forward call (``forward_delta=1 > 0``) is rejected."""
    director = _make_agent("director")
    recaller = _make_agent("recaller")
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "召回"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    # max_depth=0 -> even a depth-1 forward call is rejected.
    executor = _make_executor(registry, runner, max_depth=0)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    rejected = [r for r in result.rejected_calls if r.agent == "recaller"]
    assert len(rejected) == 1
    assert rejected[0].reason == "cross-stage recursive call rejected"
    assert "recaller" not in result.completed_agents


# ── 4. Standard tools dispatched to ToolDispatcher ───────────────────────


@dataclass
class _MockScopedTools:
    """Minimal scoped-tools double for ToolDispatcher."""

    read_return: object = "STATE-CONTENT"
    write_return: object = None
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def read(self, **kwargs: object) -> object:
        self.calls.append(("read", dict[str, object](kwargs)))
        return self.read_return

    def search(self, **kwargs: object) -> object:
        self.calls.append(("search", dict[str, object](kwargs)))
        return []

    def write(self, **kwargs: object) -> object:
        self.calls.append(("write", dict[str, object](kwargs)))
        return self.write_return


@pytest.mark.asyncio
async def test_standard_tool_read_dispatched_to_tool_dispatcher() -> None:
    """A ``read`` tool call from the director is dispatched to the
    director's :class:`ToolDispatcher` (wrapping ScopedTools)."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    scoped = _MockScopedTools(read_return="STATE-CONTENT")
    dispatcher = ToolDispatcher(cast(ScopedToolsProtocol, scoped))

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="read", args={"resource_type": "state", "filename": "current.md"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner, director_tools=dispatcher)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "explicit_finalize"
    # The scoped tool was actually called.
    assert len(scoped.calls) == 1
    assert scoped.calls[0][0] == "read"
    assert scoped.calls[0][1] == {"resource_type": "state", "filename": "current.md"}


@pytest.mark.asyncio
async def test_standard_tool_write_dispatched_to_tool_dispatcher() -> None:
    """A ``write`` tool call from the director is dispatched to the
    director's :class:`ToolDispatcher`."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    scoped = _MockScopedTools()
    dispatcher = ToolDispatcher(cast(ScopedToolsProtocol, scoped))

    runner = _ScriptedRunner(
        director_batches=[
            [
                ToolCall(
                    name="write",
                    args={
                        "resource_type": "notes",
                        "filename": "new.md",
                        "content": "hello",
                    },
                )
            ],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner, director_tools=dispatcher)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "explicit_finalize"
    assert len(scoped.calls) == 1
    assert scoped.calls[0][0] == "write"


@pytest.mark.asyncio
async def test_standard_tool_without_dispatcher_is_rejected() -> None:
    """When ``director_tools`` is None (no tool surface configured), a
    ``read`` tool call is rejected with a ``"no_tools_surface"`` reason."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="read", args={"resource_type": "state"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner, director_tools=None)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    rejected = [r for r in result.rejected_calls if "no_tools_surface" in r.reason]
    assert len(rejected) == 1
    assert result.finalize_reason == "explicit_finalize"


# ── 5. call_agent resolves from registry ─────────────────────────────────


@pytest.mark.asyncio
async def test_call_agent_resolves_target_from_registry() -> None:
    """``call_agent`` resolves the target agent by name from the
    registry and runs it through the runtime. The sub-agent's response
    text is stored under a handle for a later ``await``."""
    director = _make_agent("director")
    recaller = _make_agent("recaller")
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [
                ToolCall(name="call_agent", args={"agent_name": "recaller", "prompt": "召回"}),
            ],
            # Second turn: await the handle, then finalize.
            [
                ToolCall(name="await", args={"handle": "task_1"}),
            ],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "explicit_finalize"
    assert "recaller" in result.completed_agents
    # The await did not produce a rejected call (handle was valid).
    await_rejected = [r for r in result.rejected_calls if "unknown_handle" in r.reason]
    assert len(await_rejected) == 0


@pytest.mark.asyncio
async def test_call_agent_unknown_agent_rejected() -> None:
    """``call_agent`` with a name not in the registry is rejected with
    ``"agent_not_in_registry"``."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="call_agent", args={"agent_name": "ghost", "prompt": "boo"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    rejected = [r for r in result.rejected_calls if r.agent == "ghost"]
    assert len(rejected) == 1
    assert rejected[0].reason == "agent_not_in_registry"
    assert result.finalize_reason == "explicit_finalize"


# ── 6. finalize ends the round ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_ends_round_immediately() -> None:
    """A ``finalize`` tool call ends the round immediately with
    ``finalize_reason == "explicit_finalize"``. No further tool calls
    in the same batch are dispatched."""
    director = _make_agent("director")
    recaller = _make_agent("recaller")
    registry = _make_registry(director, recaller)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            # finalize is the first (and only processed) tool call.
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    assert result.finalize_reason == "explicit_finalize"
    # No sub-agent was called.
    assert "recaller" not in result.completed_agents
    assert len(runner.sub_calls) == 0


# ── 7. await with unknown handle ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_await_unknown_handle_rejected() -> None:
    """``await`` with a handle that was never produced by a prior
    ``call_agent`` is rejected with ``"unknown_handle"``."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="await", args={"handle": "task_99"})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    rejected = [r for r in result.rejected_calls if "unknown_handle" in r.reason]
    assert len(rejected) == 1
    assert result.finalize_reason == "explicit_finalize"


# ── 8. Chat mode (tree=None) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_mode_calls_director_once_no_loop() -> None:
    """With ``tree=None`` (chat mode), the executor calls the director
    once and captures its text. No tool-call loop runs."""
    director = _make_agent("director")
    registry = _make_registry(director)

    runner = MockRunner()
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=None, context="hello")

    assert result.finalize_reason == "all_nodes_done"
    assert result.completed_agents == ["director"]
    assert result.director_text != ""
    assert result.total_tokens > 0


# ── 9. Unknown tool rejection ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_tool_recorded_as_rejected_call() -> None:
    """A tool call with a name not in the allowed set is recorded as a
    rejected call with ``"unknown_tool"`` in the reason. The round
    continues and the director can finalize next turn."""
    director = _make_agent("director")
    registry = _make_registry(director)
    tree = _make_tree()

    runner = _ScriptedRunner(
        director_batches=[
            [ToolCall(name="bogus_tool", args={})],
            [ToolCall(name="finalize", args={})],
        ],
    )
    executor = _make_executor(registry, runner)
    result = await executor.execute_round(director=director, tree=tree, context="ctx")

    rejected = [r for r in result.rejected_calls if "unknown_tool" in r.reason]
    assert len(rejected) == 1
    assert "bogus_tool" in rejected[0].reason
    assert result.finalize_reason == "explicit_finalize"
