"""Runtime factory: create_round_session + run_session + stop_session.

This module decouples the API layer from direct construction of Runtime
components (Runtime, BudgetTracker, RoundExecutor, AgentRegistry). The API
routes call :func:`create_round_session` to get a :class:`RoundSession`
holding all wired-up components, then :func:`run_session` to execute the
round and :func:`stop_session` to cancel it.

This keeps the Runtime layer's internal construction details inside the
Runtime layer — the API layer never imports ``Runtime``, ``BudgetTracker``,
``RoundExecutor``, or ``build_default_registry`` directly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.registry import AgentRegistry, build_default_registry
from app.agents.agent import Agent
from app.agents.tree_model import AGENT_KIND
from app.agents.workflow import WorkflowTree
from app.runtime.budget import BudgetTracker
from app.runtime.round_executor import RoundExecutor, RoundResult
from app.runtime.runners.base import AgentRunner
from app.runtime.runners.mock_runner import MockRunner
from app.runtime.runtime import Runtime

logger = logging.getLogger(__name__)


@dataclass
class RoundSession:
    """Holds all components for a single round execution.

    Attributes:
        round_id:  Unique round identifier.
        project_id: Project identifier.
        executor:  The :class:`RoundExecutor` wired with runtime/runner/registry/budget.
        budget:    The :class:`BudgetTracker` for this round.
        registry:  The :class:`AgentRegistry` with all agents loaded.
        tree:      The :class:`WorkflowTree` (None for chat mode).
        context:   The context string passed to ``execute_round``.
        task:      The background ``asyncio.Task`` (set by the caller after
                   :func:`run_session` is scheduled).
        state:     Current state: ``"pending"``, ``"running"``, ``"completed"``,
                   ``"failed"``, ``"stopped"``.
        result:    The :class:`RoundResult` when completed.
        error:     Error message when failed.
        logs:      Accumulated log lines.
    """

    round_id: str
    project_id: str
    executor: RoundExecutor
    budget: BudgetTracker
    registry: AgentRegistry
    tree: WorkflowTree | None
    context: str
    maximal_recursive_calling_depth: int
    task: asyncio.Task[RoundResult] | None = None
    state: str = "pending"
    result: RoundResult | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)


def create_round_session(
    project_path: Path,
    project_id: str,
    context: str,
    tree: WorkflowTree | None,
    max_iterations: int | None,
    maximal_recursive_calling_depth: int | None,
    runner_factory: Callable[[], AgentRunner] | None = None,
) -> RoundSession:
    """Construct a fully-wired :class:`RoundSession` without starting execution.

    Builds the default registry, Runtime, BudgetTracker, and RoundExecutor.
    The caller decides when to start execution via :func:`run_session`.

    Args:
        project_path: Path to the project workspace (unused by components
            currently, but reserved for future per-project config loading).
        project_id: Project identifier for logging / record-keeping.
        context: Context string passed to ``execute_round``.
        tree: The :class:`WorkflowTree` for workflow mode; ``None`` for chat mode.
        max_iterations: Override for budget max_iterations. If ``None``,
            defaults to ``2 * tree.node_count()`` for workflow mode or ``4``
            for chat mode.
        maximal_recursive_calling_depth: Max recursive call depth. If ``None``,
            defaults to ``1``.
        runner_factory: Optional factory for the :class:`AgentRunner`. If
            ``None``, uses :class:`MockRunner` (LLM-credential-free dry-run).

    Returns:
        A :class:`RoundSession` in ``"pending"`` state, ready for
        :func:`run_session`.
    """
    agent_registry = build_default_registry()
    # Register embedded agent definitions from an imported tree so the
    # workflow is portable: the tree carries its own definitions (keyed
    # "kind:id"), and the recipient's registry is populated from those
    # definitions rather than relying on name-mapping.
    if tree is not None and tree.definitions:
        for node_def in tree.definitions.values():
            if node_def.kind != AGENT_KIND:
                continue
            try:
                agent = Agent.from_dict(
                    node_def.payload, source=f"imported definition {node_def.key}"
                )
                agent_registry.register(agent, replace=True)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "create_round_session: skipping imported definition %s: %s",
                    node_def.key,
                    exc,
                )
    runtime = Runtime(
        {
            "timeout_seconds": 600,
            "max_retries": 0,
            "max_concurrent": 3,
        }
    )

    if max_iterations is not None:
        effective_max_iterations = max_iterations
    elif tree is not None:
        effective_max_iterations = 2 * tree.node_count()
    else:
        effective_max_iterations = 4

    budget = BudgetTracker(
        max_iterations=effective_max_iterations,
        max_tokens=100_000,
        max_tool_calls=50,
    )

    runner = runner_factory() if runner_factory is not None else MockRunner()

    depth = maximal_recursive_calling_depth if maximal_recursive_calling_depth is not None else 1

    executor = RoundExecutor(
        runtime=runtime,
        runner=runner,
        registry=agent_registry,
        budget=budget,
        maximal_recursive_calling_depth=depth,
    )

    round_id = f"round_{asyncio.get_event_loop().time():.0f}_{id(executor):x}"

    return RoundSession(
        round_id=round_id,
        project_id=project_id,
        executor=executor,
        budget=budget,
        registry=agent_registry,
        tree=tree,
        context=context,
        maximal_recursive_calling_depth=depth,
    )


async def run_session(session: RoundSession) -> RoundResult:
    """Execute the round described by *session* and update its state.

    Returns the :class:`RoundResult`. On exception, sets ``session.state``
    to ``"failed"`` and re-raises so the caller (e.g. an ``asyncio.Task``)
    can capture the error.
    """
    session.state = "running"
    session.logs.append(f"round {session.round_id} started for project {session.project_id}")
    try:
        director = session.registry.get("director")
        result = await session.executor.execute_round(
            director=director,
            tree=session.tree,
            context=session.context,
        )
        session.result = result
        session.state = "completed"
        session.logs.append(
            f"round {session.round_id} completed: "
            f"{len(result.completed_agents)} agents, reason={result.finalize_reason}"
        )
        return result
    except asyncio.CancelledError:
        session.state = "stopped"
        session.error = "round stopped by user"
        session.logs.append(f"round {session.round_id} cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 — background task must not crash loop
        session.state = "failed"
        session.error = f"{type(exc).__name__}: {exc}"
        session.logs.append(f"round {session.round_id} failed: {session.error}")
        logger.exception("round %s failed", session.round_id)
        raise


def stop_session(session: RoundSession) -> None:
    """Cancel the background task for *session* if it is running."""
    if session.task is not None and not session.task.done():
        session.task.cancel()
