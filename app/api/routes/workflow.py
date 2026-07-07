"""/api/workflow run/stop, per-round status.

Endpoints
---------
* ``POST /api/workflow/{project_id}/run``        — start a round in the
  background, returns ``round_id`` + ``202``.
* ``GET  /api/workflow/{project_id}/round/{rid}`` — round status / logs /
  :class:`RoundResult` (when completed).
* ``POST /api/workflow/{project_id}/stop``       — stop a running round
  (cancels the background ``asyncio.Task``).

Round status is kept **in-memory** (per todo 22: "Store round status in
memory (dict[round_id, RoundStatus]) — simple, no DB"). The registry
lives on ``app.state.round_registry`` and is created once by
:func:`app.api.server.create_app`.

The director round itself is executed by
:meth:`app.agents.director.Director.run_round`. We load the default
registry + workflow tree, build a :class:`~app.runtime.budget.BudgetTracker`
(``max_iterations = 2 × node_count`` per plan scope item 3) and a
:class:`~app.runtime.runtime.Runtime` from the project's runtime config,
then schedule ``run_round`` as a background ``asyncio.Task``. The task
handle is stored alongside the status so ``/stop`` can cancel it.

Per refactor_guide:298-300 one Turn = one Round = one git Commit. The
director's maintainer agent performs the actual data writes; the chat
routes (``app/api/routes/chat.py``) are responsible for committing chat
Turns. A workflow round does NOT auto-commit a Turn here — that is the
caller's / maintainer's responsibility (the director's tool surface
includes ``write`` which goes through the data layer). This route only
orchestrates the round execution; the data-layer commit happens inside
the round via the maintainer agent's writes + the transaction coordinator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.agents.director import Director, RoundResult
from app.agents.registry import AgentRegistry, build_default_registry
from app.agents.runners.base import AgentRunner
from app.agents.runners.mock_runner import MockRunner
from app.agents.workflow import WorkflowTree, load_workflow
from app.api.schemas import (
    RoundResultSummary,
    RoundState,
    RoundStatusResponse,
    RunWorkflowRequest,
)
from app.project_paths import ProjectPathError, resolve_project_path
from app.runtime.budget import BudgetTracker
from app.runtime.runtime import Runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])

ProjectIdPath = Annotated[str, FastPath(..., description="System-controlled project id")]
RoundIdPath = Annotated[str, FastPath(..., description="Round id returned by POST /run")]


# ── In-memory round registry ──────────────────────────────────────────────


@dataclass
class RoundRecord:
    """Mutable per-round record kept in :class:`RoundRegistry`."""

    round_id: str
    project_id: str
    state: RoundState = "pending"
    logs: list[str] = field(default_factory=list)
    result: RoundResult | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = None

    def to_response(self) -> RoundStatusResponse:
        """Build the wire :class:`RoundStatusResponse`."""
        result_summary: RoundResultSummary | None = None
        if self.result is not None:
            result_summary = RoundResultSummary(
                completed_agents=list(self.result.completed_agents),
                finalize_reason=self.result.finalize_reason,
                total_tokens=self.result.total_tokens,
                recursive_calls=[
                    {"agent": r.agent, "reason": r.reason, "depth": r.depth}
                    for r in self.result.recursive_calls
                ],
                rejected_calls=[
                    {"agent": r.agent, "reason": r.reason} for r in self.result.rejected_calls
                ],
            )
        return RoundStatusResponse(
            round_id=self.round_id,
            state=self.state,
            logs=list(self.logs),
            result=result_summary,
            error=self.error,
        )


class RoundRegistry:
    """In-memory store of active + completed rounds.

    One instance lives on ``app.state.round_registry`` for the lifetime of
    the FastAPI app. Thread-safety is not required — FastAPI runs the
    event loop in a single thread, and ``asyncio.Task`` creation / state
    mutations all happen on that loop.
    """

    def __init__(self) -> None:
        self._rounds: dict[str, RoundRecord] = {}

    def create(self, round_id: str, project_id: str) -> RoundRecord:
        record = RoundRecord(round_id=round_id, project_id=project_id)
        self._rounds[round_id] = record
        return record

    def get(self, round_id: str) -> RoundRecord | None:
        return self._rounds.get(round_id)

    def get_running_for_project(self, project_id: str) -> RoundRecord | None:
        """Return the first running/pending round for *project_id*, if any."""
        for record in self._rounds.values():
            if record.project_id == project_id and record.state in ("pending", "running"):
                return record
        return None

    def all(self) -> dict[str, RoundRecord]:
        return dict(self._rounds)


def _get_registry(request: Request) -> RoundRegistry:
    """Resolve the in-memory round registry from app state."""
    reg = getattr(request.app.state, "round_registry", None)
    if reg is None:  # pragma: no cover — create_app always sets it
        reg = RoundRegistry()
        request.app.state.round_registry = reg
    return reg


def _root_dep(request: Request) -> Path:
    root = getattr(request.app.state, "root", None)
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server root not initialised",
        )
    return Path(root)


RootDep = Annotated[Path, Depends(_root_dep)]
RegistryDep = Annotated[RoundRegistry, Depends(_get_registry)]


# ── Runner factory hook (for tests) ──────────────────────────────────────


def _default_runner_factory() -> AgentRunner:
    """Build the default runner for a workflow round.

    The API layer uses the :class:`MockRunner` by default so that
    ``POST /run`` is safe to call without LLM credentials (per the
    task's "Mock the Director/agents for tests" constraint and the
    guide's 傻瓜式 default — a round with the mock runner is a dry-run
    that exercises the full pipeline without spending tokens). The
    frontend RunView can switch to a real runner via a future config
    route; for now the runner is hard-wired to MockRunner.
    """
    return MockRunner()


# Module-level hook so tests can monkeypatch the runner factory.
RUNNER_FACTORY = _default_runner_factory


# ── Helpers ──────────────────────────────────────────────────────────────


def _resolve_project(root: Path, project_id: str) -> Path:
    """Resolve *project_id* to its workspace path or 404."""
    try:
        path = resolve_project_path(root, project_id)
    except ProjectPathError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not path.exists() or not (path / "config.yaml").exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id!r} not found",
        )
    return path


def _load_workflow_tree(project_path: Path) -> WorkflowTree:
    """Load the project's ``workflow.yaml`` (or the default workflow)."""
    wf_path = project_path / "workflow.yaml"
    if wf_path.exists():
        return load_workflow(wf_path)
    # Fall back to the built-in default workflow shipped with the agent layer.
    return load_workflow(Path(__file__).resolve().parents[2] / "app" / "agents" / "default_workflow.yaml")


def _build_director(registry: AgentRegistry) -> Director:
    """Build a :class:`Director` from the registry.

    The director agent is constructed inline (matching the pattern in
    ``tests/integration/test_agent_layer.py``) because the built-in
    registry (todo 19) only ships the 5 sub-agents — the director itself
    is the mandatory main agent that orchestrates them. We build a
    minimal director :class:`Agent` with a read permission broad enough
    to assemble its prompt.
    """
    from app.agents.agent import Agent
    from app.runtime.permission import parse_permission

    director_agent = Agent(
        id="director",
        name="director",
        task="决策与任务分配，调度其他 agent，控制流程结束。",
        input="当前状态、大纲、细纲、工作流执行顺序",
        output="调度决策与回合总结",
        permission=parse_permission(
            {"read": ["state", "outline", "short_goal", "notes"], "write": []}
        ),
        model=None,
        skills=[],
        tools=["read", "search", "write"],
        head=None,
        tail=None,
        allow_recursive=True,
    )
    # Ensure all built-in sub-agents are registered (the director resolves
    # node agents via name through the registry in a full system; here we
    # use the director's _resolve_node_agent which clones the template, so
    # the registry is loaded primarily for completeness / future use).
    _ = registry  # registry loaded for side-effect of validation if needed
    return Director(director_agent)


async def _execute_round(
    record: RoundRecord,
    tree: WorkflowTree,
    runtime: Runtime,
    budget: BudgetTracker,
    runner: AgentRunner,
    director: Director,
    context: str,
    maximal_recursive_calling_depth: int,
) -> None:
    """Background coroutine: run the director round and update the record.

    Wrapped so any exception is captured into ``record.error`` and the
    state transitions to ``"failed"`` rather than propagating (the
    background task must never crash the event loop).
    """
    record.state = "running"
    record.logs.append(f"round {record.round_id} started for project {record.project_id}")
    try:
        result = await director.run_round(
            tree=tree,
            runtime=runtime,
            budget=budget,
            runner=runner,
            context=context,
            maximal_recursive_calling_depth=maximal_recursive_calling_depth,
        )
        record.result = result
        record.state = "completed"
        record.logs.append(
            f"round {record.round_id} completed: "
            f"{len(result.completed_agents)} agents, reason={result.finalize_reason}"
        )
    except asyncio.CancelledError:
        record.state = "failed"
        record.error = "round stopped by user"
        record.logs.append(f"round {record.round_id} cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 — background task must not crash loop
        record.state = "failed"
        record.error = f"{type(exc).__name__}: {exc}"
        record.logs.append(f"round {record.round_id} failed: {record.error}")
        logger.exception("workflow round %s failed", record.round_id)


# ── Routes ───────────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/run",
    response_model=RoundStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_workflow(
    project_id: ProjectIdPath,
    req: RunWorkflowRequest,
    root: RootDep,
    registry: RegistryDep,
) -> RoundStatusResponse:
    """Start a workflow round in the background.

    Returns ``202`` with the initial ``pending`` :class:`RoundStatusResponse`.
    The client polls ``GET /round/{round_id}`` for completion.
    """
    project_path = _resolve_project(root, project_id)

    # Refuse to start a second concurrent round for the same project.
    existing = registry.get_running_for_project(project_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Project {project_id!r} already has a running round "
                f"{existing.round_id!r}; stop it before starting a new one."
            ),
        )

    # Load workflow tree + build director + runtime + budget.
    tree = _load_workflow_tree(project_path)
    agent_registry = build_default_registry()
    director = _build_director(agent_registry)
    runtime = Runtime(
        {
            "timeout_seconds": 600,
            "max_retries": 0,
            "max_concurrent": 3,
        }
    )
    # Per plan scope item 3: default max agent calls = 2 × node count.
    default_max_iterations = 2 * tree.node_count()
    max_iterations = req.max_iterations if req.max_iterations is not None else default_max_iterations
    budget = BudgetTracker(max_iterations=max_iterations, max_tokens=100_000, max_tool_calls=50)
    runner = RUNNER_FACTORY()

    round_id = f"round_{uuid.uuid4().hex[:8]}"
    record = registry.create(round_id, project_id)

    # Schedule the background round. asyncio.create_task requires a running
    # loop, which FastAPI provides inside an async endpoint.
    task = asyncio.create_task(
        _execute_round(
            record=record,
            tree=tree,
            runtime=runtime,
            budget=budget,
            runner=runner,
            director=director,
            context=req.context,
            maximal_recursive_calling_depth=req.maximal_recursive_calling_depth,
        )
    )
    record.task = task
    return record.to_response()


@router.get("/{project_id}/round/{round_id}", response_model=RoundStatusResponse)
def get_round_status(
    project_id: ProjectIdPath,
    round_id: RoundIdPath,
    root: RootDep,
    registry: RegistryDep,
) -> RoundStatusResponse:
    """Get the status / logs / result of a round."""
    _resolve_project(root, project_id)  # 404 if project missing
    record = registry.get(round_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Round {round_id!r} not found for project {project_id!r}",
        )
    return record.to_response()


@router.post("/{project_id}/stop", response_model=RoundStatusResponse)
def stop_workflow(
    project_id: ProjectIdPath,
    root: RootDep,
    registry: RegistryDep,
) -> RoundStatusResponse:
    """Stop the running round for *project_id* (cancel its background task).

    Returns the (now ``failed`` / cancelled) round status. If no round is
    running, returns ``409``.
    """
    _resolve_project(root, project_id)
    record = registry.get_running_for_project(project_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {project_id!r} has no running round to stop.",
        )
    if record.task is not None and not record.task.done():
        record.task.cancel()
        record.logs.append(f"stop requested for round {record.round_id}")
    return record.to_response()


__all__ = [
    "RoundRecord",
    "RoundRegistry",
    "router",
]
