"""Runtime factory: create_round_session + run_session + stop_session.

This module decouples the API layer from direct construction of Runtime
components (Runtime, BudgetTracker, RoundExecutor, AgentRegistry). The API
routes call :func:`create_round_session` to get a :class:`RoundSession`
holding all wired-up components, then :func:`run_session` to execute the
round and :func:`stop_session` to cancel it.

This keeps the Runtime layer's internal construction details inside the
Runtime layer — the API layer never imports ``Runtime``, ``BudgetTracker``,
``RoundExecutor``, or ``build_project_registry`` directly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from app.agents.agent import Agent
from app.agents.registry import AgentRegistry, build_project_registry
from app.agents.tree_model import AGENT_KIND
from app.agents.workflow import WorkflowTree
from app.config_loader import RuntimeConfig
from app.data.store import ResourceStore
from app.runtime.budget import BudgetTracker
from app.runtime.mcp import load_mcp_tools
from app.runtime.permission import inject_into_tools
from app.runtime.prompt_builder import PromptBuilder
from app.runtime.round_executor import RoundExecutor, RoundResult
from app.runtime.runners.base import AgentRunner
from app.runtime.runners.mock_runner import MockRunner
from app.runtime.runtime import Runtime
from app.runtime.tool_catalog import build_default_catalog
from app.runtime.tool_dispatcher import ScopedTools as ScopedToolsProtocol
from app.runtime.tool_dispatcher import ToolDispatcher

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
    task: asyncio.Task[None] | None = None
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
    runtime_config: RuntimeConfig | None = None,
) -> RoundSession:
    """Construct a fully-wired :class:`RoundSession` without starting execution.

    Builds the project registry (builtins + per-project overrides),
    Runtime, BudgetTracker, and RoundExecutor. The caller decides when
    to start execution via :func:`run_session`.

    Args:
        project_path: Path to the project workspace; per-project agent
            overrides are loaded from ``<project_path>/agents/*.yaml``.
        project_id: Project identifier for logging / record-keeping.
        context: Context string passed to ``execute_round``.
        tree: The :class:`WorkflowTree` for workflow mode; ``None`` for chat mode.
        max_iterations: Override for budget max_iterations. If ``None``,
            defaults to ``max_calls_multiplier * tree.node_count()`` for
            workflow mode or ``4`` for chat mode.
        maximal_recursive_calling_depth: Max recursive call depth. If ``None``,
            defaults to the config's ``workflow.maximal_recursive_calling_depth``
            (``1`` without config).
        runner_factory: Optional factory for the :class:`AgentRunner`. If
            ``None``, uses :class:`MockRunner` (LLM-credential-free dry-run).
        runtime_config: The merged :class:`~app.config_loader.RuntimeConfig`
            (``config/runtime.yaml`` + project overrides). Supplies the
            Runtime execution policy and the round budget. ``None`` keeps
            the built-in defaults (unit-test friendly).

    Returns:
        A :class:`RoundSession` in ``"pending"`` state, ready for
        :func:`run_session`.
    """
    # Builtins + per-project overrides: an agent overridden in the
    # project's agents/ dir takes effect on the run path, not only on
    # the config surface.
    agent_registry = build_project_registry(project_path)
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
    # Execution policy and round budget come from user configuration
    # (config/runtime.yaml + project overrides); the values below are the
    # config-free fallbacks used by unit tests and ad-hoc callers.
    runner_policy: dict[str, object] = {
        "timeout_seconds": 600,
        "max_retries": 0,
        "max_concurrent": 3,
    }
    workflow_policy: dict[str, object] = {}
    if runtime_config is not None:
        runner_policy.update(runtime_config.runner)
        workflow_policy = runtime_config.workflow
    runtime = Runtime(runner_policy)

    multiplier = int(str(workflow_policy.get("max_calls_multiplier", 2)))
    if max_iterations is not None:
        effective_max_iterations = max_iterations
    elif tree is not None:
        effective_max_iterations = multiplier * tree.node_count()
    else:
        effective_max_iterations = 4

    budget = BudgetTracker(
        max_iterations=effective_max_iterations,
        max_tokens=int(str(workflow_policy.get("max_tokens", 100_000))),
        max_tool_calls=int(str(workflow_policy.get("max_tool_calls", 50))),
    )

    runner = runner_factory() if runner_factory is not None else MockRunner()

    if maximal_recursive_calling_depth is not None:
        depth = maximal_recursive_calling_depth
    else:
        depth = int(str(workflow_policy.get("maximal_recursive_calling_depth", 1)))

    # Tool surface: the default catalog (builtin schemas + runtime impls)
    # plus any MCP-mounted tools (seam only — no servers configured yet).
    catalog = build_default_catalog()
    load_mcp_tools(catalog, config=None)
    prompts = PromptBuilder(catalog)

    # Per-agent data tools: every agent (director and sub-agents alike)
    # gets a dispatcher scoped by its OWN permission over the project's
    # resource store — a writer's write permission is enforceable at
    # runtime, not just declared.
    store = ResourceStore(project_path)

    def tools_factory(agent: Agent) -> ToolDispatcher:
        scoped = inject_into_tools(store, agent.permission)
        return ToolDispatcher(cast(ScopedToolsProtocol, scoped), catalog)

    director_tools: ToolDispatcher | None = None
    if agent_registry.has("director"):
        director_tools = tools_factory(agent_registry.get("director"))

    executor = RoundExecutor(
        runtime=runtime,
        runner=runner,
        registry=agent_registry,
        budget=budget,
        director_tools=director_tools,
        maximal_recursive_calling_depth=depth,
        prompts=prompts,
        tools_factory=tools_factory,
    )

    # time.monotonic() rather than the event-loop clock: this factory is
    # callable outside a running loop (unit tests, future CLI paths).
    round_id = f"round_{time.monotonic():.0f}_{id(executor):x}"

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
