"""Tests for app.agents.director — tree-based scheduling + recursion control.

Per the todo 18 design, the Director executes a :class:`WorkflowTree`
node-by-node through the :class:`Runtime`, enforcing three recursion-control
gates:

(a) Budget — ``max agent calls = 2 × node count``; BudgetTracker raises
    :class:`FinalizeSignal` on exhaustion.
(b) Depth constraint — ``0 <= cur_depth - target_depth <= maximal_recursive_calling_depth``
    (default 1): self-call (Δ=0) and parent-call (Δ=1) allowed, others
    rejected with ``"cross-stage recursive call rejected"``.
(c) Per-agent ``allow_recursive`` — when False AND call_count > 1,
    rejected with ``"agent does not allow recursive call"``.
"""

from __future__ import annotations

import pytest

from app.agents.agent import Agent
from app.agents.director import Director, RoundResult
from app.agents.runners.base import AgentResponse, AgentRunner, RunnerAgent, TokenUsage
from app.agents.workflow import CanvasGraph, CanvasNode, CanvasWire, parse_canvas_to_tree
from app.runtime.budget import BudgetTracker, FinalizeSignal
from app.runtime.permission import parse_permission
from app.runtime.runtime import Runtime


# ── test doubles ────────────────────────────────────────────────────────────


def _make_permission(raw: dict[str, list[str]] | None = None) -> object:
    if raw is None:
        raw = {"read": ["state"], "write": ["short_goal"]}
    return parse_permission({k: v for k, v in raw.items()})


def _make_director_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "id": "director-001",
        "name": "director",
        "task": "决策与任务分配",
        "input": "当前状态、短期目标、世界书摘要",
        "output": "JSON 格式的下一步行动指令",
        "permission": _make_permission(),
        "model": "premium",
        "skills": [],
        "tools": ["read", "search", "write"],
        "head": None,
        "tail": None,
        "allow_recursive": True,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _CountingRunner(AgentRunner):
    """Runner that returns a canned AgentResponse and records calls."""

    def __init__(self, responses: list[AgentResponse] | None = None) -> None:
        self._responses = responses or []
        self.calls: list[tuple[str, str]] = []
        self.call_count = 0

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        self.calls.append((agent.id, prompt))
        self.call_count += 1
        if self._responses:
            idx = min(self.call_count - 1, len(self._responses) - 1)
            return self._responses[idx]
        return AgentResponse(
            text=f"[mock:{agent.id}] ok",
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            raw={"mock": True},
        )


def _resp(tokens: int = 15) -> AgentResponse:
    return AgentResponse(text="ok", usage=TokenUsage(10, tokens - 10))


def _five_node_tree() -> object:
    """Build a 5-node tree: root→recaller, root→scout, recaller→writer, scout→writer, writer→critic, critic→maintainer."""
    g = CanvasGraph()
    g.nodes = [
        CanvasNode(id="root", agent_name="director", description="决策"),
        CanvasNode(id="recaller", agent_name="recaller", description="召回"),
        CanvasNode(id="scout", agent_name="scout", description="灵感"),
        CanvasNode(id="writer", agent_name="writer", description="生成"),
        CanvasNode(id="critic", agent_name="critic", description="审查"),
        CanvasNode(id="maintainer", agent_name="maintainer", description="维护"),
    ]
    g.wires = [
        CanvasWire(from_node="root", to_node="recaller"),
        CanvasWire(from_node="root", to_node="scout"),
        CanvasWire(from_node="recaller", to_node="writer"),
        CanvasWire(from_node="scout", to_node="writer"),
        CanvasWire(from_node="writer", to_node="critic"),
        CanvasWire(from_node="critic", to_node="maintainer"),
    ]
    return parse_canvas_to_tree(g)


# ── happy path: Director runs 5-node tree in order, finalizes ───────────────


class TestDirectorHappyPath:
    """Director runs all nodes and finalizes with reason 'all_nodes_done'."""

    @pytest.mark.asyncio
    async def test_runs_all_six_nodes_and_finalizes(self) -> None:
        tree = _five_node_tree()  # 6 nodes (root + 5)
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        budget = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=20)
        runner = _CountingRunner()

        result = await director.run_round(tree, runtime, budget, runner)

        assert result.finalize_reason == "all_nodes_done"
        assert len(result.completed_agents) == 6
        assert runner.call_count == 6

    @pytest.mark.asyncio
    async def test_round_result_records_total_tokens(self) -> None:
        tree = _five_node_tree()
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        budget = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=20)
        runner = _CountingRunner()

        result = await director.run_round(tree, runtime, budget, runner)

        # 6 calls × 15 tokens each = 90 tokens
        assert result.total_tokens == 90

    @pytest.mark.asyncio
    async def test_round_result_type(self) -> None:
        tree = _five_node_tree()
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        budget = BudgetTracker(max_iterations=20)
        runner = _CountingRunner()

        result = await director.run_round(tree, runtime, budget, runner)

        assert isinstance(result, RoundResult)
        assert result.recursive_calls == []
        assert result.rejected_calls == []


# ── recursion control: budget exhaustion → FinalizeSignal ──────────────────


class TestDirectorBudgetExhaustion:
    """Budget exhaustion (max_iterations = 2×node_count) finalizes the round."""

    @pytest.mark.asyncio
    async def test_budget_exhaustion_finalizes_with_budget_exhausted(self) -> None:
        tree = _five_node_tree()  # 6 nodes → max_calls = 12
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        # Set max_iterations to 3: calls 1,2,3 consume to exactly the ceiling
        # (is_exhausted=True but not beyond), call 4's consume raises
        # FinalizeSignal. So 4 calls complete before exhaustion.
        budget = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=3)
        runner = _CountingRunner()

        result = await director.run_round(tree, runtime, budget, runner)

        assert result.finalize_reason == "budget_exhausted"
        # 4 calls completed (the 4th's consume triggers the raise).
        assert len(result.completed_agents) == 4


# ── recursion control: depth violation ─────────────────────────────────────


class TestDirectorDepthConstraint:
    """check_recursion_allowed enforces 0 <= cur_depth - target_depth <= max."""

    def test_self_call_allowed(self) -> None:
        """Δ=0 (cur_depth == target_depth) is always allowed."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=True)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=3,
            cur_depth=3,
            call_count=2,
            max_depth=1,
        )
        assert allowed is True
        assert reason == "ok"

    def test_parent_call_allowed(self) -> None:
        """Δ=1 (cur_depth - target_depth == 1) is allowed when max_depth >= 1."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=True)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=2,
            cur_depth=3,
            call_count=2,
            max_depth=1,
        )
        assert allowed is True
        assert reason == "ok"

    def test_depth_violation_cur_3_target_0_max_1_rejected(self) -> None:
        """cur_depth=3, target_depth=0, max=1: Δ=3 > 1 → rejected."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=True)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=0,
            cur_depth=3,
            call_count=2,
            max_depth=1,
        )
        assert allowed is False
        assert reason == "cross-stage recursive call rejected"

    def test_depth_violation_negative_delta_rejected(self) -> None:
        """cur_depth=0, target_depth=3: Δ=-3 < 0 → rejected (can't call forward)."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=True)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=3,
            cur_depth=0,
            call_count=2,
            max_depth=1,
        )
        assert allowed is False
        assert reason == "cross-stage recursive call rejected"

    def test_max_depth_2_allows_grandparent_call(self) -> None:
        """With max_depth=2, Δ=2 (grandparent) is allowed."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=True)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=1,
            cur_depth=3,
            call_count=2,
            max_depth=2,
        )
        assert allowed is True
        assert reason == "ok"


# ── recursion control: allow_recursive=False + call_count>1 ────────────────


class TestDirectorAllowRecursive:
    """allow_recursive=False + call_count > 1 → rejected."""

    def test_allow_recursive_false_first_call_allowed(self) -> None:
        """call_count == 1 is NOT recursive → always allowed regardless of flag."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=False)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=3,
            cur_depth=3,
            call_count=1,
            max_depth=1,
        )
        assert allowed is True
        assert reason == "ok"

    def test_allow_recursive_false_recursive_call_rejected(self) -> None:
        """call_count > 1 + allow_recursive=False → rejected."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=False)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=3,
            cur_depth=3,
            call_count=2,
            max_depth=1,
        )
        assert allowed is False
        assert reason == "agent does not allow recursive call"

    def test_allow_recursive_true_recursive_call_allowed(self) -> None:
        """call_count > 1 + allow_recursive=True → allowed (depth permitting)."""
        director = Director(_make_director_agent())
        agent = _make_director_agent(allow_recursive=True)
        allowed, reason = director.check_recursion_allowed(
            target_agent=agent,
            target_depth=3,
            cur_depth=3,
            call_count=2,
            max_depth=1,
        )
        assert allowed is True
        assert reason == "ok"


# ── RoundResult records completed / recursive / rejected ────────────────────


class TestRoundResultRecords:
    """RoundResult records completed agents, recursive calls, rejected calls."""

    @pytest.mark.asyncio
    async def test_completed_agents_listed(self) -> None:
        tree = _five_node_tree()
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        budget = BudgetTracker(max_iterations=20)
        runner = _CountingRunner()

        result = await director.run_round(tree, runtime, budget, runner)

        assert "root" in result.completed_agents
        assert "recaller" in result.completed_agents
        assert "writer" in result.completed_agents

    def test_round_result_default_fields(self) -> None:
        r = RoundResult()
        assert r.completed_agents == []
        assert r.recursive_calls == []
        assert r.rejected_calls == []
        assert r.finalize_reason == ""
        assert r.total_tokens == 0


# ── director.call_agent ─────────────────────────────────────────────────────


class TestDirectorCallAgent:
    """call_agent schedules an async task through the runtime."""

    @pytest.mark.asyncio
    async def test_call_agent_returns_task_that_resolves(self) -> None:
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        runner = _CountingRunner()
        agent = _make_director_agent(id="target-1", name="target")

        task = await director.call_agent(agent, "do something", runtime, runner)
        result = await task

        assert isinstance(result, AgentResponse)
        assert result.text.startswith("[mock:target-1]")


# ── director prompt injection (flow_sequence) ───────────────────────────────


class TestDirectorPromptInjection:
    """The director's prompt includes the flow sequence."""

    @pytest.mark.asyncio
    async def test_flow_sequence_injected_into_director_prompt(self) -> None:
        tree = _five_node_tree()
        director = Director(_make_director_agent())
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
        budget = BudgetTracker(max_iterations=20)
        runner = _CountingRunner()

        await director.run_round(tree, runtime, budget, runner)

        # The director_prompt is passed to each node call; the CountingRunner
        # recorded the prompts. At least one should contain the flow sequence
        # section header "## 工作流执行顺序".
        all_prompts = "\n".join(p for _, p in runner.calls)
        assert "## 工作流执行顺序" in all_prompts
