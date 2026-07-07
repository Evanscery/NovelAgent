"""End-to-end Agent Layer integration test (Wave 3, todo 20).

Exercises the full agent stack against a real per-workspace git repo +
the real data layer + the real runtime, using the deterministic
:class:`MockRunner` for sub-agents:

1. ``build_default_registry()`` → 5 built-in agents (recaller / scout /
   writer / critic / maintainer) + a :class:`WorkflowTree` compiled from
   ``default_workflow.yaml`` (6 nodes: root/director → recaller+scout →
   writer → critic → maintainer).
2. Create a tmp project, ``ProjectRepo.init()``, seed State + Outline +
   ShortGoal + Notes resources with real content (the director's
   context).
3. ``Director.run_round(tree, runtime, budget, MockRunner, context,
   maximal_recursive_calling_depth=1)``.
4. Assert DAG scheduling executes nodes per BFS tree order
   (root → recaller → scout → writer → critic → maintainer).
5. Assert permission enforcement: writer can't read ``facts``
   (``PermissionDenied``) — writer.read perms cover outline/short_goal/
   state/worldbook/character_memory/notes, NOT facts.
6. Assert tool dispatch: ``read`` / ``search`` / ``write`` work via
   :class:`ToolExecutor` wrapping :class:`ScopedTools`; ``readFile``
   raises :class:`UnknownToolError`.
7. Assert budget / Finalize: set ``max_iterations=2`` for a 6-node tree
   → ``FinalizeSignal`` raised and caught, ``finalize_reason ==
   "budget_exhausted"``.
8. Assert recursion control:
   - depth violation rejected (``cross-stage recursive call rejected``)
     when ``cur_depth - target_depth > maximal_recursive_calling_depth``;
   - ``allow_recursive=False`` + ``call_count > 1`` rejected
     (``agent does not allow recursive call``).
9. Assert :class:`RoundResult` records ``completed_agents``,
   ``finalize_reason``, ``rejected_calls``, ``recursive_calls``.

Then runs the Wave 3 real-LLM smoke (D8): use :class:`DirectRunner` for
the **Director ONLY** (sub-agents stay mock via a custom runner that
delegates Director → DirectRunner, others → MockRunner), give the
Director a real State + Outline + flow_sequence, assert the Director
produces a coherent round (calls ≥1 agent, finalizes). Per the task's
hard rule: if the API key is invalid/missing, SKIP with a recorded
reason — do NOT block, do NOT iterate on LLM failure. ONE round only
(D8 cost guard).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from app.agents.agent import Agent
from app.agents.director import (
    Director,
    RoundResult,
)
from app.agents.parser import parse_agent_to_prompt
from app.agents.registry import build_default_registry
from app.agents.runners.base import (
    AgentResponse,
    AgentRunner,
    RunnerAgent,
)
from app.agents.runners.direct_runner import DirectRunner
from app.agents.runners.mock_runner import MockRunner
from app.agents.tools import ToolExecutor
from app.agents.workflow import (
    WorkflowTree,
    generate_flow_sequence,
    load_workflow,
)
from app.data.project_repo import ProjectRepo
from app.data.store import ResourceStore
from app.runtime.budget import BudgetTracker
from app.runtime.permission import (
    PermissionDenied,
    inject_into_tools,
    parse_permission,
)
from app.runtime.runtime import Runtime
from app.runtime.tool_dispatcher import ScopedTools as ScopedToolsProtocol
from app.runtime.tool_dispatcher import ToolDispatcher, UnknownToolError

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


@pytest.fixture
def registry() -> object:
    """Default registry with the 5 built-in agents loaded."""
    return build_default_registry()


@pytest.fixture
def tree() -> WorkflowTree:
    """Default 6-node workflow tree compiled from default_workflow.yaml."""
    return load_workflow(Path(__file__).resolve().parents[2] / "app" / "agents" / "default_workflow.yaml")


def _make_director_agent(allow_recursive: bool = True) -> Agent:
    """Build a minimal director Agent for :class:`Director`.

    The director is the mandatory main workflow agent
    (refactor_guide:92-101). For the integration test we only need a
    valid :class:`Agent` instance to construct the Director; the
    per-node agents are resolved by the director via
    :meth:`Director._resolve_node_agent`, which clones this template
    with the node's id/name/description.
    """
    return Agent(
        id="director",
        name="director",
        task="决策与任务分配，调度其他 agent，控制流程结束。",
        input="当前状态、大纲、细纲、工作流执行顺序",
        output="调度决策与回合总结",
        permission=parse_permission({"read": ["state", "outline", "short_goal", "notes"]}),
        model=None,
        skills=[],
        tools=["read", "search", "write"],
        head=None,
        tail=None,
        allow_recursive=allow_recursive,
    )


def _seed_project(store: ResourceStore) -> dict[str, str]:
    """Seed the project with real State + Outline + ShortGoal + Notes content.

    Returns a dict of resource_type → seeded filename for assertions.
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


# ── Part 1: end-to-end agent-layer integration ───────────────────────────


class TestAgentLayerIntegration:
    """End-to-end agent layer flow against the real data + runtime layers."""

    # ── 1. Registry + workflow tree load ──────────────────────────────

    def test_build_default_registry_loads_five_agents(
        self, registry: object
    ) -> None:
        """``build_default_registry()`` loads all 5 built-in agents
        (recaller / scout / writer / critic / maintainer)."""
        names = registry.list()  # type: ignore[attr-defined]
        assert set(names) == {"recaller", "scout", "writer", "critic", "maintainer"}

    def test_default_workflow_parses_to_six_node_tree(
        self, tree: WorkflowTree
    ) -> None:
        """``default_workflow.yaml`` compiles to a 6-node tree:
        root/director + 5 agents. BFS order is root → recaller → scout
        → writer → critic → maintainer."""
        assert tree.node_count() == 6
        ordered = sorted(tree.all_nodes.values(), key=lambda n: (n.depth, n.id))
        agent_names = [n.agent_name for n in ordered]
        assert agent_names == ["director", "recaller", "scout", "writer", "critic", "maintainer"]

    def test_flow_sequence_lists_all_six_nodes(
        self, tree: WorkflowTree
    ) -> None:
        """``generate_flow_sequence`` produces a numbered list with all
        6 nodes, director first."""
        seq = generate_flow_sequence(tree)
        assert seq.count("\n") == 5  # 6 lines
        assert "director" in seq
        assert "recaller" in seq
        assert "maintainer" in seq
        # First line is the director at depth 0.
        first_line = seq.split("\n", 1)[0]
        assert "director" in first_line
        assert "[depth=0]" in first_line

    # ── 2. Director.run_round executes all 6 nodes in BFS order ───────

    @pytest.mark.asyncio
    async def test_director_runs_all_nodes_in_bfs_order(
        self, project: Path, store: ResourceStore, tree: WorkflowTree
    ) -> None:
        """Director with a generous budget and :class:`MockRunner`
        completes all 6 nodes; ``completed_agents`` lists node ids in
        BFS order; ``finalize_reason == "all_nodes_done"``."""
        _seed_project(store)
        director = Director(_make_director_agent(allow_recursive=True))
        runtime = Runtime(
            {
                "timeout_seconds": 5,
                "max_retries": 0,
                "max_concurrent": 3,
            }
        )
        # 2 × node_count = 12 max agent calls; 6 nodes → plenty of headroom.
        budget = BudgetTracker(max_iterations=12, max_tokens=10_000, max_tool_calls=50)
        runner = MockRunner()

        result = await director.run_round(
            tree=tree,
            runtime=runtime,
            budget=budget,
            runner=runner,
            context=" seeded project state + outline + short_goal + notes ",
            maximal_recursive_calling_depth=1,
        )

        # All 6 nodes completed, in BFS order (depth, id).
        assert result.completed_agents == ["root", "recaller", "scout", "writer", "critic", "maintainer"]
        assert result.finalize_reason == "all_nodes_done"
        # No rejected calls in the happy path.
        assert result.rejected_calls == []
        # First-call (call_count == 1) for every node → no recursive calls.
        assert result.recursive_calls == []
        # Tokens were accumulated from the mock runner.
        assert result.total_tokens > 0

    # ── 3. Permission enforcement: writer can't read facts ────────────

    def test_writer_permission_denied_on_facts(
        self, project: Path, store: ResourceStore, registry: object
    ) -> None:
        """Writer's ``read`` permission does NOT cover ``facts``
        (writer.read = outline/short_goal/state/worldbook/
        character_memory/notes). Reading facts raises
        :class:`PermissionDenied`."""
        _seed_project(store)
        writer = registry.get("writer")  # type: ignore[attr-defined]
        scoped = inject_into_tools(store, writer.permission)
        # Allowed: writer can read state.
        state_text = scoped.read("state", "current.md")
        assert "城郊破庙" in state_text
        # Disallowed: writer can't read facts.
        with pytest.raises(PermissionDenied) as exc_info:
            scoped.read("facts", "truths.md")
        assert exc_info.value.action == "read"
        assert exc_info.value.resource_type == "facts"
        assert "facts" not in writer.permission.rules.get("read", ())

    # ── 4. Tool dispatch via ToolExecutor + ToolDispatcher ────────────

    def test_tool_executor_read_search_write(
        self, project: Path, store: ResourceStore, registry: object
    ) -> None:
        """``ToolExecutor`` (agent-facing) wraps :class:`ScopedTools` and
        exposes the three unified tools. read returns real content;
        search returns hits; write creates a file and updates the
        index."""
        _seed_project(store)
        # Use the maintainer's broad permission for this exercise
        # (read+write on many types) so we can test all three tools in
        # one scoped surface.
        maintainer = registry.get("maintainer")  # type: ignore[attr-defined]
        scoped = inject_into_tools(store, maintainer.permission)
        executor = ToolExecutor(scoped)

        # read(state) → real seeded content.
        state_text = executor.read("state", "current.md")
        assert "城郊破庙" in state_text

        # search(notes, "伏笔") → hits in observations.md.
        hits = executor.search("notes", "伏笔")
        assert len(hits) >= 1
        assert all(h.filename == "observations.md" for h in hits)

        # write(notes, "new.md", ...) → file created, index updated.
        ok = executor.write("notes", "new.md", "# 新笔记\n\n伏笔：反派徽记。")
        assert ok is True
        assert (store._resources_dir / "notes" / "new.md").read_text(encoding="utf-8").startswith("# 新笔记")

    def test_tool_dispatcher_rejects_readfile(
        self, project: Path, store: ResourceStore, registry: object
    ) -> None:
        """``ToolDispatcher`` dispatches ``read`` / ``search`` / ``write``
        via scoped tools and rejects ``readFile`` with
        :class:`UnknownToolError` (standardized tool surface)."""
        _seed_project(store)
        writer = registry.get("writer")  # type: ignore[attr-defined]
        scoped = inject_into_tools(store, writer.permission)
        dispatcher = ToolDispatcher(cast(ScopedToolsProtocol, scoped))

        from app.agents.runners.base import ToolCall

        # read(state) → real content.
        result = dispatcher.dispatch(
            ToolCall(name="read", args={"resource_type": "state", "filename": "current.md"})
        )
        assert result.ok is True
        assert "城郊破庙" in result.output

        # readFile(memory) → UnknownToolError (standardized surface enforced).
        with pytest.raises(UnknownToolError, match="Unknown tool: readFile"):
            dispatcher.dispatch(ToolCall(name="readFile", args={"resource": "memory"}))

    # ── 5. Budget / Finalize: tiny budget stops the round ─────────────

    @pytest.mark.asyncio
    async def test_budget_exhaustion_finalizes_round(
        self, project: Path, store: ResourceStore, tree: WorkflowTree
    ) -> None:
        """Set ``max_iterations=2`` for a 6-node tree. The director
        completes the first 2 nodes, then the third ``consume`` raises
        :class:`FinalizeSignal` which the director catches; the round
        ends with ``finalize_reason == "budget_exhausted"`` and only
        the first 2 nodes in ``completed_agents``.

        Note: the director consumes budget AFTER each node completes
        (see ``director.py:226-235``). So with ``max_iterations=2``:
          - node 1 (root) completes → consume(iterations=1) → used=1
          - node 2 (recaller) completes → consume(iterations=1) → used=2
          - node 3 (scout) completes → consume(iterations=1) → used=3
            → exceeds max_iterations=2 → FinalizeSignal → break.
        The third node's response is still collected (consume happens
        AFTER the response), so ``completed_agents`` includes the third
        node id. The round ends with 3 completed + budget_exhausted.
        """
        _seed_project(store)
        director = Director(_make_director_agent(allow_recursive=True))
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
        budget = BudgetTracker(max_iterations=2, max_tokens=10_000, max_tool_calls=50)
        runner = MockRunner()

        result = await director.run_round(
            tree=tree,
            runtime=runtime,
            budget=budget,
            runner=runner,
            context=" seeded project state + outline ",
            maximal_recursive_calling_depth=1,
        )

        assert result.finalize_reason == "budget_exhausted"
        # The first 3 nodes (root, recaller, scout) completed before the
        # third consume raised FinalizeSignal and broke the loop.
        assert result.completed_agents == ["root", "recaller", "scout"]
        assert result.rejected_calls == []

    # ── 6. Recursion control ──────────────────────────────────────────

    def test_check_recursion_allowed_depth_violation(
        self, registry: object
    ) -> None:
        """``Director.check_recursion_allowed`` rejects a cross-stage
        recursive call when ``cur_depth - target_depth`` exceeds
        ``maximal_recursive_calling_depth``.

        E.g. cur_depth=4, target_depth=0, max_depth=1 → delta=4 > 1 →
        rejected with ``"cross-stage recursive call rejected"``."""
        director = Director(_make_director_agent(allow_recursive=True))
        recaller = registry.get("recaller")  # type: ignore[attr-defined]
        allowed, reason = director.check_recursion_allowed(
            target_agent=recaller,
            target_depth=0,
            cur_depth=4,
            call_count=2,
            max_depth=1,
        )
        assert allowed is False
        assert reason == "cross-stage recursive call rejected"

    def test_check_recursion_allowed_self_call_ok(
        self, registry: object
    ) -> None:
        """A self-call (Δ=0) at call_count=2 is allowed when
        ``allow_recursive=True``."""
        director = Director(_make_director_agent(allow_recursive=True))
        recaller = registry.get("recaller")  # type: ignore[attr-defined]
        # recaller.allow_recursive == True per builtin yaml.
        allowed, reason = director.check_recursion_allowed(
            target_agent=recaller,
            target_depth=2,
            cur_depth=2,
            call_count=2,
            max_depth=1,
        )
        assert allowed is True
        assert reason == "ok"

    def test_check_recursion_allowed_parent_call_ok(
        self, registry: object
    ) -> None:
        """A parent-call (Δ=1) at call_count=2 is allowed when
        ``allow_recursive=True`` and ``max_depth=1``."""
        director = Director(_make_director_agent(allow_recursive=True))
        recaller = registry.get("recaller")  # type: ignore[attr-defined]
        allowed, reason = director.check_recursion_allowed(
            target_agent=recaller,
            target_depth=1,
            cur_depth=2,
            call_count=2,
            max_depth=1,
        )
        assert allowed is True
        assert reason == "ok"

    def test_check_recursion_allowed_allow_recursive_false_rejects(
        self, registry: object
    ) -> None:
        """``allow_recursive=False`` + ``call_count > 1`` → rejected
        with ``"agent does not allow recursive call"``.

        The maintainer agent has ``allow_recursive: false`` per its
        builtin yaml. However, the director's ``_resolve_node_agent``
        clones the DIRECTOR's template (not the registry's agent), so
        the gate uses the director's flag. To exercise the gate with
        ``allow_recursive=False`` we construct a director whose
        ``allow_recursive`` is False.
        """
        director = Director(_make_director_agent(allow_recursive=False))
        # Any agent will do for the gate check; the gate reads
        # target_agent.allow_recursive. Use a cloned agent with the
        # flag set False to mirror what _resolve_node_agent produces
        # when the director's flag is False.
        template = _make_director_agent(allow_recursive=False)
        target = replace(template, id="maintainer-clone", name="maintainer")
        allowed, reason = director.check_recursion_allowed(
            target_agent=target,
            target_depth=2,
            cur_depth=2,
            call_count=2,
            max_depth=1,
        )
        assert allowed is False
        assert reason == "agent does not allow recursive call"

    @pytest.mark.asyncio
    async def test_run_round_allows_recursive_self_call_under_budget(
        self, project: Path, store: ResourceStore, tree: WorkflowTree
    ) -> None:
        """When ``allow_recursive=True`` and the same agent is called
        twice (call_count=2) at the same depth (Δ=0), the
        :class:`RecursiveCallRecord` is recorded in
        ``result.recursive_calls``.

        We simulate this by using a 1-node tree (root only) and calling
        ``run_round`` with a budget that permits 2 iterations. The
        director's loop only calls each node ONCE per round, so to
        observe a recursive call we construct a custom tree with two
        nodes of the SAME agent_name at the same depth and call
        ``check_recursion_allowed`` directly to verify the gate. The
        round itself records ``recursive_calls`` only when
        ``call_count > 1`` for a node — which happens when the same
        agent_name appears at multiple nodes.
        """
        # Build a 2-node tree: root (director) and a child with the
        # SAME agent_name as root → call_count for "director" hits 2
        # on the second node → recursive_calls records it.
        from app.agents.workflow import TreeNode

        root = TreeNode(
            id="root",
            agent_name="director",
            description="root",
            params={},
            depth=0,
            parent_id=None,
        )
        child = TreeNode(
            id="child",
            agent_name="director",  # SAME agent_name → call_count=2
            description="second call",
            params={},
            depth=1,
            parent_id="root",
        )
        root.children.append(child)
        same_agent_tree = WorkflowTree(root=root, all_nodes={"root": root, "child": child})

        _seed_project(store)
        director = Director(_make_director_agent(allow_recursive=True))
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
        budget = BudgetTracker(max_iterations=4, max_tokens=10_000, max_tool_calls=50)
        runner = MockRunner()

        result = await director.run_round(
            tree=same_agent_tree,
            runtime=runtime,
            budget=budget,
            runner=runner,
            context=" seeded project state ",
            maximal_recursive_calling_depth=1,
        )

        # Both nodes completed.
        assert result.completed_agents == ["root", "child"]
        # The second call to "director" (call_count=2, Δ=1) is a
        # parent-call which is allowed under max_depth=1 → recorded as
        # a recursive call (call_count > 1).
        assert len(result.recursive_calls) == 1
        assert result.recursive_calls[0].agent == "director"
        assert result.finalize_reason == "all_nodes_done"

    # ── 7. RoundResult records completed_agents + finalize_reason ─────

    @pytest.mark.asyncio
    async def test_round_result_records_completed_and_reason(
        self, project: Path, store: ResourceStore, tree: WorkflowTree
    ) -> None:
        """RoundResult is a dataclass with completed_agents,
        recursive_calls, finalize_reason, total_tokens,
        rejected_calls — all populated by ``run_round``."""
        _seed_project(store)
        director = Director(_make_director_agent(allow_recursive=True))
        runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 3})
        budget = BudgetTracker(max_iterations=12, max_tokens=10_000, max_tool_calls=50)
        runner = MockRunner()

        result = await director.run_round(
            tree=tree,
            runtime=runtime,
            budget=budget,
            runner=runner,
            context=" seeded project state ",
        )

        assert isinstance(result, RoundResult)
        assert len(result.completed_agents) == 6
        assert result.finalize_reason == "all_nodes_done"
        assert result.total_tokens > 0
        assert isinstance(result.rejected_calls, list)
        assert isinstance(result.recursive_calls, list)

    # ── 8. Director prompt includes flow_sequence ─────────────────────

    def test_director_prompt_includes_flow_sequence(
        self, tree: WorkflowTree
    ) -> None:
        """``parse_agent_to_prompt`` with a non-empty ``flow_sequence``
        injects a ``## 工作流执行顺序`` section into the director's
        prompt — so the director knows the execution order (full-recall
        of the workflow resource)."""
        director_agent = _make_director_agent(allow_recursive=True)
        flow_seq = generate_flow_sequence(tree)
        prompt = parse_agent_to_prompt(
            director_agent, context="test context", flow_sequence=flow_seq
        )
        assert "## 工作流执行顺序" in prompt
        assert "director" in prompt
        assert "recaller" in prompt
        assert "## 上下文" in prompt
        # allow_recursive is runtime-only — NEVER emitted into the prompt.
        assert "allow_recursive" not in prompt


# ── Part 2: D8 Wave 3 LLM smoke ──────────────────────────────────────────


def _load_env_local(project_root: Path) -> dict[str, str]:
    """Load ``.env.local`` (and ``.env``) into a dict if present.

    ``.env.local`` takes precedence over ``.env`` (matches the
    .gitignore convention that real credentials live in
    ``.env.local``).
    """
    env: dict[str, str] = {}
    for name in (".env", ".env.local"):
        path = project_root / name
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _env_has_credentials(env: dict[str, str]) -> bool:
    """True if the env dict has both an API key and a base URL set and
    the key is not the placeholder."""
    key = env.get("TEST_API_KEY", "").strip()
    base = env.get("TEST_BASE_URL", "").strip()
    return bool(key) and bool(base) and "your-api-key-here" not in key


def _write_evidence(evidence_path: Path, body: str) -> None:
    """Write the LLM smoke outcome to the evidence file (atomic)."""
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(body, encoding="utf-8")


class _DirectorDirectRunner(AgentRunner):
    """Composite runner: DirectRunner for the director agent, MockRunner
    for all other agents.

    Used by the Wave 3 LLM smoke to send the Director's prompt to a real
    LLM while keeping the sub-agent calls deterministic (D8 cost guard:
    ONE real-LLM round, sub-agents stay mock).

    Attributes:
        direct_exc: The exception raised by the real-LLM call, if it
            failed. ``None`` if the call succeeded or was never made.
            The smoke test inspects this after the round to decide
            SKIP (401/auth) vs PASS vs engineering-bug.
        direct_called: True if the real-LLM call was attempted.
        direct_response: The :class:`AgentResponse` from the real-LLM
            call, if it succeeded. ``None`` if it failed or was never
            made.
    """

    def __init__(self, direct: DirectRunner, mock: MockRunner) -> None:
        self._direct = direct
        self._mock = mock
        self.direct_exc: BaseException | None = None
        self.direct_called: bool = False
        self.direct_response: AgentResponse | None = None

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        # The director's agent id is "director" (per _make_director_agent);
        # _resolve_node_agent clones it with node.id, but the NAME stays
        # "director" only for the root node. For the smoke we treat the
        # FIRST call (root node, agent_name=="director") as the real-LLM
        # call and all others as mock. This gives the Director exactly
        # one real-LLM call (D8 cost guard).
        if agent.id == "root" and getattr(agent, "name", "") == "director":
            self.direct_called = True
            try:
                resp = await self._direct.run(agent, prompt)
            except BaseException as exc:
                # Capture the exception so the smoke test can inspect it
                # after the round. The director's run_round will also
                # catch this and record a rejected_call; we re-raise so
                # the director's own error handling takes effect.
                self.direct_exc = exc
                raise
            self.direct_response = resp
            return resp
        return await self._mock.run(agent, prompt)


@pytest.mark.asyncio
async def test_llm_smoke_wave3(tmp_path: Path) -> None:
    """D8 Wave 3 real-LLM smoke: ONE real Director call via
    :class:`DirectRunner`, sub-agents stay mock.

    Per the task's hard rule: if the API key is invalid/missing, SKIP
    with a recorded reason — do NOT block the todo, do NOT iterate on
    LLM failure. ONE round only (D8 cost guard).
    """
    project_root = Path(__file__).resolve().parents[2]
    evidence_dir = project_root / ".omo" / "evidence"
    evidence_path = evidence_dir / "wave-3-llm-smoke.txt"

    env = _load_env_local(project_root)
    # Also pick up anything already in os.environ.
    for k in ("TEST_API_KEY", "TEST_BASE_URL", "MODEL_HIGH", "MODEL_FAST"):
        if k in os.environ and k not in env:
            env[k] = os.environ[k]

    # --- Skip path: no credentials ------------------------------------
    if not _env_has_credentials(env):
        reason = (
            "SKIPPED: API key invalid/missing (no .env or no TEST_API_KEY/"
            "TEST_BASE_URL). Agent layer verified via integration test only.\n"
        )
        _write_evidence(evidence_path, reason)
        pytest.skip(reason)

    api_key = env["TEST_API_KEY"]
    base_url = env["TEST_BASE_URL"]
    model = env.get("MODEL_FAST") or env.get("MODEL_HIGH") or "gemini-3-flash-preview"

    # Set up a seeded project for the Director's context.
    root = tmp_path / "smoke-proj"
    root.mkdir()
    ProjectRepo(root).init()
    store = ResourceStore(root)
    _seed_project(store)

    # Build the workflow tree + director.
    tree = load_workflow(project_root / "app" / "agents" / "default_workflow.yaml")
    director_agent = _make_director_agent(allow_recursive=True)
    director = Director(director_agent)

    runtime = Runtime(
        {
            "timeout_seconds": 120,
            "max_retries": 0,
            "max_concurrent": 3,
        }
    )
    # Budget: 2 × node_count = 12 max agent calls; plenty for one round.
    budget = BudgetTracker(max_iterations=12, max_tokens=50_000, max_tool_calls=50)

    direct = DirectRunner(
        model_config={
            "provider": "openai_compatible",
            "model": model,
            "api_key_env": "WAVE3_SMOKE_API_KEY",
            "base_url_env": "WAVE3_SMOKE_BASE_URL",
        },
        runtime_policy={"timeout_seconds": 120, "max_retries": 0},
    )
    composite_runner = _DirectorDirectRunner(direct=direct, mock=MockRunner())

    # The director's prompt is built inside run_round from the agent +
    # flow_sequence + context. Give it real context from the seeded
    # State + Outline so the LLM has something concrete to reason about.
    state_text = store.read(store.create_resource("state", "state-001"), "current.md")
    outline_text = store.read(store.create_resource("outline", "outline-001"), "arc.md")
    context = f"当前状态:\n{state_text}\n\n大纲:\n{outline_text}"

    # Persist the env vars DirectRunner will read via _resolve_env.
    saved: dict[str, str | None] = {
        "WAVE3_SMOKE_API_KEY": os.environ.get("WAVE3_SMOKE_API_KEY"),
        "WAVE3_SMOKE_BASE_URL": os.environ.get("WAVE3_SMOKE_BASE_URL"),
    }
    os.environ["WAVE3_SMOKE_API_KEY"] = api_key
    os.environ["WAVE3_SMOKE_BASE_URL"] = base_url

    # --- Pre-flight auth check (ONE tiny LLM ping) -------------------
    # The director's run_round swallows runner errors via `except
    # Exception` and records them as rejected_calls, so a 401 would
    # NOT surface as a test failure — the mock sub-agents would still
    # complete and the round would "pass" without ever validating the
    # real LLM. To honor D8's "valid response OR skipped with recorded
    # reason" contract, we send a tiny pre-flight ping to validate auth
    # BEFORE the round. If auth fails (401/invalid_api_key), SKIP with
    # a recorded reason. This ping is the ONE real-LLM call for D8 (the
    # round itself uses the mock runner for sub-agents and the same
    # real LLM for the director, so it's still one logical round).
    preflight_agent: RunnerAgent = _PreflightAgent(id="wave3-preflight", model=model)
    preflight_prompt = "Reply with the single word: OK"
    try:
        preflight_resp = await direct.run(preflight_agent, preflight_prompt)
        preflight_text = (preflight_resp.text or "").strip()
    except Exception as exc:  # noqa: BLE001 — D8: record any failure, no iterate
        msg = f"{type(exc).__name__}: {exc}"
        if "401" in msg or "invalid API key" in msg or "invalid_api_key" in msg:
            reason = (
                "SKIPPED: API key invalid (HTTP 401). Agent layer verified via "
                "integration test only.\n"
                f"  detail: {msg}\n"
            )
            _write_evidence(evidence_path, reason)
            pytest.skip(reason)
        # Non-auth failure → engineering bug note + surface as failure.
        note = (
            "ENGINEERING-BUG (NOT LLM-iterated per D8):\n"
            f"  Wave 3 LLM smoke pre-flight ping failed: {msg}\n"
            "  Diagnose as engineering bug first (mock repro); do NOT re-run LLM.\n"
            "  Agent layer itself verified via the integration test in this file.\n"
        )
        _write_evidence(evidence_path, note)
        # Restore env before re-raising.
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        raise

    try:
        result = await director.run_round(
            tree=tree,
            runtime=runtime,
            budget=budget,
            runner=composite_runner,
            context=context,
            maximal_recursive_calling_depth=1,
        )
    finally:
        # Restore the env.
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # --- Validate the round ------------------------------------------
    completed = len(result.completed_agents)
    # The director's real-LLM call should have succeeded (preflight
    # passed). If the composite runner's direct call captured an
    # exception, surface it as an engineering bug.
    if composite_runner.direct_exc is not None:
        msg = f"{type(composite_runner.direct_exc).__name__}: {composite_runner.direct_exc}"
        note = (
            "ENGINEERING-BUG (NOT LLM-iterated per D8):\n"
            f"  Wave 3 LLM smoke: pre-flight OK but director call failed: {msg}\n"
            "  Diagnose as engineering bug first (mock repro); do NOT re-run LLM.\n"
            "  Agent layer itself verified via the integration test in this file.\n"
        )
        _write_evidence(evidence_path, note)
        raise AssertionError(note)

    outcome_body = (
        f"WAVE 3 LLM SMOKE (D8)\n"
        f"model: {model}\n"
        f"endpoint: {base_url.rstrip('/')}/chat/completions\n"
        f"director: real-LLM via DirectRunner (sub-agents stay mock)\n"
        f"tree: 6 nodes (root/director + 5 agents)\n"
        f"preflight_response: {preflight_text!r}\n"
        f"director_real_response: {_dr_text(composite_runner.direct_response)}\n"
        f"completed_agents: {result.completed_agents}\n"
        f"completed_count: {completed}\n"
        f"finalize_reason: {result.finalize_reason}\n"
        f"total_tokens: {result.total_tokens}\n"
        f"rejected_calls: {len(result.rejected_calls)}\n"
        f"recursive_calls: {len(result.recursive_calls)}\n"
        f"outcome: {'PASS' if completed >= 1 else 'FAIL'} — "
        f"{'Director produced a coherent round' if completed >= 1 else 'no agents called'}\n"
    )
    _write_evidence(evidence_path, outcome_body)

    assert completed >= 1, (
        f"Wave 3 LLM smoke: Director completed {completed} agents, expected ≥1.\n"
        f"result={result!r}"
    )
    assert result.finalize_reason in {"all_nodes_done", "budget_exhausted"}


# ── Helpers for the LLM smoke ────────────────────────────────────────────


def _dr_text(resp: AgentResponse | None) -> str:
    """Render the director's real-LLM response text for evidence, or
    ``"<None>"`` if the response was never set."""
    return repr(resp.text) if resp is not None else "<None>"


@dataclass(frozen=True)
class _PreflightAgent:
    """Minimal agent satisfying the ``RunnerAgent`` protocol for the
    pre-flight auth ping. Frozen so it structurally satisfies the
    Protocol's read-only ``id`` / ``model`` contract."""

    id: str
    model: str | None


# ── Sanity: the smoke's credential detection is mockable ────────────────


def test_smoke_skip_writes_evidence_when_no_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If no .env is configured, the Wave 3 smoke skips and writes a
    SKIPPED reason to the evidence file. This test forces the no-env
    path via patching so it runs deterministically in CI without real
    credentials."""
    project_root = Path(__file__).resolve().parents[2]
    evidence_path = project_root / ".omo" / "evidence" / "wave-3-llm-smoke.txt"
    pre = evidence_path.read_text(encoding="utf-8") if evidence_path.exists() else None

    try:
        with patch(
            "tests.integration.test_agent_layer._load_env_local",
            return_value={},
        ):
            with patch.dict(os.environ, {}, clear=True):
                with pytest.raises(pytest.skip.Exception):
                    asyncio.run(test_llm_smoke_wave3(tmp_path))
        assert evidence_path.exists()
        assert "SKIPPED" in evidence_path.read_text(encoding="utf-8")
    finally:
        # Restore the prior evidence content so we don't clobber a real
        # run's evidence with the forced-skip body.
        if pre is not None:
            evidence_path.write_text(pre, encoding="utf-8")
        elif evidence_path.exists():
            evidence_path.unlink()
