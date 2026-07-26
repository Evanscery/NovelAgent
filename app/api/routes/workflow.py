"""/api/workflow run/stop, per-round status.

Endpoints
---------
* ``POST /api/workflow/{project_id}/run``        — start a round in the
  background, returns ``round_id`` + ``202``.
* ``GET  /api/workflow/{project_id}/round/{rid}`` — round status / logs /
  :class:`RoundResult` (when completed).
* ``POST /api/workflow/{project_id}/stop``       — stop a running round
  (cancels the background ``asyncio.Task``).

Round status is kept **in-memory** (``dict[round_id, RoundStatus]`` —
simple, no DB). The registry lives on ``app.state.round_registry`` and
is created once by :func:`app.api.server.create_app`.

The round itself is executed by the Runtime layer via the factory function
:func:`~app.runtime.session.create_round_session` +
:func:`~app.runtime.session.run_session`. The API layer does NOT directly
construct ``Runtime``, ``BudgetTracker``, ``RoundExecutor``, or the
agent registry — that is the Runtime layer's responsibility.
The director agent is loaded from ``director.yaml`` inside the factory
function; it is a plain :class:`~app.agents.agent.Agent`, not a dedicated
orchestrator class.

The design invariant is one Turn = one Round = one git Commit. This
route only orchestrates round execution — it does NOT commit a Turn.
Agent writes during the round go through the data layer as plain file
writes; committing a Turn is left to the caller (the chat routes,
``app/api/routes/chat.py``, are where chat Turns are committed). The
transaction coordinator (``app.runtime.transaction.AtomicTurn``) exists
but is not wired into this production path.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, cast

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.agents.registry import build_project_registry
from app.agents.workflow import WorkflowTree, load_default_workflow, load_workflow
from app.api.routes._deps import ProjectIdPath, RootDep, resolve_project
from app.api.schemas import (
    RoundResultSummary,
    RoundState,
    RoundStatusResponse,
    RunWorkflowRequest,
)
from app.config_loader import ConfigLoader
from app.runtime.runner_factory import build_runner
from app.runtime.runners.base import AgentRunner
from app.runtime.session import (
    RoundSession,
    create_round_session,
    run_session,
    stop_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])

RoundIdPath = Annotated[str, FastPath(..., description="Round id returned by POST /run")]


# -- In-memory round registry -------------------------------------------------


def _to_response(session: RoundSession) -> RoundStatusResponse:
    """Build the wire :class:`RoundStatusResponse` from a session's state."""
    result_summary: RoundResultSummary | None = None
    if session.result is not None:
        result_summary = RoundResultSummary(
            completed_agents=list(session.result.completed_agents),
            finalize_reason=session.result.finalize_reason,
            total_tokens=session.result.total_tokens,
            recursive_calls=[
                {"agent": r.agent, "reason": r.reason, "depth": r.depth}
                for r in session.result.recursive_calls
            ],
            rejected_calls=[
                {"agent": r.agent, "reason": r.reason} for r in session.result.rejected_calls
            ],
        )
    return RoundStatusResponse(
        round_id=session.round_id,
        state=cast(RoundState, session.state),
        logs=list(session.logs),
        result=result_summary,
        error=session.error,
    )


class RoundRegistry:
    """In-memory store of active + completed round sessions.

    The session itself (:class:`~app.runtime.session.RoundSession`) is the
    single source of truth for round state/logs/result/error — the API
    layer only indexes sessions by round id and renders them to wire
    responses.

    One instance lives on ``app.state.round_registry`` for the lifetime of
    the FastAPI app. Thread-safety is not required — FastAPI runs the
    event loop in a single thread, and ``asyncio.Task`` creation / state
    mutations all happen on that loop.
    """

    def __init__(self) -> None:
        self._rounds: dict[str, RoundSession] = {}

    def add(self, session: RoundSession) -> None:
        self._rounds[session.round_id] = session

    def get(self, round_id: str) -> RoundSession | None:
        return self._rounds.get(round_id)

    def get_running_for_project(self, project_id: str) -> RoundSession | None:
        """Return the first running/pending round for *project_id*, if any."""
        for session in self._rounds.values():
            if session.project_id == project_id and session.state in ("pending", "running"):
                return session
        return None

    def all(self) -> dict[str, RoundSession]:
        return dict(self._rounds)


def _get_registry(request: Request) -> RoundRegistry:
    """Resolve the in-memory round registry from app state."""
    reg = getattr(request.app.state, "round_registry", None)
    if reg is None:  # pragma: no cover — create_app always sets it
        reg = RoundRegistry()
        request.app.state.round_registry = reg
    return reg


RegistryDep = Annotated[RoundRegistry, Depends(_get_registry)]


# -- Runner factory hook (for tests) -----------------------------------------


def _default_runner_factory(root: Path, project_id: str) -> AgentRunner:
    """Build the runner for a workflow round from configuration.

    Delegates to :func:`app.runtime.runner_factory.build_runner` with the
    project's merged config (``config/models.yaml`` + per-project
    overrides). The shipped default is ``runner: mock`` — LLM-credential
    free; switching ``config/models.yaml`` to ``runner: direct`` sends
    rounds to the configured OpenAI-compatible endpoint.
    """
    cfg = ConfigLoader(root).load_project(project_id)
    return build_runner(cfg.models, cfg.runtime)


# Module-level hook so tests can monkeypatch the runner factory.
RUNNER_FACTORY: Callable[[Path, str], AgentRunner] = _default_runner_factory


# -- Helpers -----------------------------------------------------------------




def _load_workflow_tree(project_path: Path) -> WorkflowTree:
    """Load the project's ``workflow.yaml`` (or the default workflow)."""
    wf_path = project_path / "workflow.yaml"
    if wf_path.exists():
        return load_workflow(wf_path)
    # Fall back to the built-in default workflow shipped with the agent layer.
    return load_default_workflow()


async def _run_round_background(session: RoundSession) -> None:
    """Background coroutine: run a round via :func:`run_session`.

    :func:`run_session` owns all state/log/result/error bookkeeping on the
    session; this wrapper only prevents the exception from crashing the
    event loop's task machinery.
    """
    try:
        await run_session(session)
    except asyncio.CancelledError:
        # run_session already marked the session "stopped".
        raise
    except Exception:  # noqa: BLE001 — background task must not crash loop
        # run_session already marked the session "failed" and logged it.
        pass


# -- Routes ------------------------------------------------------------------


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
    project_path = resolve_project(root, project_id)

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

    tree = _load_workflow_tree(project_path)

    try:
        cfg = ConfigLoader(root).load_project(project_id)
        runner_factory = RUNNER_FACTORY

        session = create_round_session(
            project_path=project_path,
            project_id=project_id,
            context=req.context,
            tree=tree,
            max_iterations=req.max_iterations,
            maximal_recursive_calling_depth=req.maximal_recursive_calling_depth,
            runner_factory=lambda: runner_factory(root, project_id),
            runtime_config=cfg.runtime,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Round configuration invalid: {exc}",
        ) from exc
    registry.add(session)

    session.task = asyncio.create_task(_run_round_background(session))
    return _to_response(session)


@router.get("/{project_id}/round/{round_id}", response_model=RoundStatusResponse)
def get_round_status(
    project_id: ProjectIdPath,
    round_id: RoundIdPath,
    root: RootDep,
    registry: RegistryDep,
) -> RoundStatusResponse:
    """Get the status / logs / result of a round."""
    resolve_project(root, project_id)  # 404 if project missing
    session = registry.get(round_id)
    if session is None or session.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Round {round_id!r} not found for project {project_id!r}",
        )
    return _to_response(session)


@router.post("/{project_id}/stop", response_model=RoundStatusResponse)
def stop_workflow(
    project_id: ProjectIdPath,
    root: RootDep,
    registry: RegistryDep,
) -> RoundStatusResponse:
    """Stop the running round for *project_id* (cancel its background task).

    Returns the (now ``stopped`` / stopping) round status. If no round is
    running, returns ``409``.
    """
    resolve_project(root, project_id)
    session = registry.get_running_for_project(project_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {project_id!r} has no running round to stop.",
        )
    stop_session(session)
    session.logs.append(f"stop requested for round {session.round_id}")
    return _to_response(session)


@router.get("/{project_id}/export")
def export_workflow(
    project_id: ProjectIdPath,
    root: RootDep,
) -> dict[str, Any]:
    """Export the project's workflow as a self-contained portable dict.

    The tree is serialized with every agent node's full definition
    embedded (resolved against the project registry: builtins +
    per-project overrides), so the recipient reconstructs the exact
    same workflow instead of binding node names to whatever agents they
    happen to have locally.

    Returns ``422`` when a node's agent name cannot be resolved in this
    project (exporting a dangling reference would produce an unusable
    workflow).
    """
    project_path = resolve_project(root, project_id)
    tree = _load_workflow_tree(project_path)
    try:
        registry = build_project_registry(project_path)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project agent override is invalid: {exc}",
        ) from exc
    try:
        return tree.to_dict(registry=registry)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/{project_id}/import")
def import_workflow(
    project_id: ProjectIdPath,
    root: RootDep,
    payload: Annotated[dict[str, Any], Body(...)],
) -> dict[str, Any]:
    """Import a portable workflow (produced by ``GET .../export``).

    Validates the tree structure (``400`` on malformed input), requires
    every node to carry an embedded definition (``422`` listing the
    unresolved nodes otherwise), and saves the tree as the project's
    ``workflow.yaml``. The embedded definitions are registered into the
    round registry at run time (see
    :func:`app.runtime.session.create_round_session`), so the imported
    workflow runs with its own agents regardless of name collisions.
    """
    project_path = resolve_project(root, project_id)
    try:
        tree = WorkflowTree.from_dict(payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid workflow tree: {exc}",
        ) from exc

    undefined = tree.undefined_nodes()
    if undefined:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "workflow import requires embedded definitions for every node",
                "undefined_nodes": undefined,
            },
        )

    # The agent layer only serializes (to_dict); persisting the file is
    # this route's responsibility.
    (project_path / "workflow.yaml").write_text(
        yaml.safe_dump(tree.to_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {
        "imported": True,
        "node_count": tree.node_count(),
        "definition_count": len(tree.definitions),
    }


__all__ = [
    "RoundRegistry",
    "router",
]
