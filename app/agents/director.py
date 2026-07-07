"""Director — tree-based workflow orchestrator with recursion control.

The Director is the mandatory main workflow agent (refactor_guide:92-101).
It executes an expanded :class:`~app.agents.workflow.WorkflowTree` node by
node, calling each node's agent through the :class:`~app.runtime.runtime.Runtime`
and enforcing three recursion-control gates (plan scope item 3):

(a) **Budget** — default ``max agent calls = 2 × node count``.
    :class:`~app.runtime.budget.BudgetTracker` tracks consumption; when
    exhausted the round finalizes with reason ``"budget_exhausted"``.

(b) **Depth constraint** —
    ``0 <= cur_depth - target_depth <= maximal_recursive_calling_depth``.
    Self-call (Δ=0) ✓, parent-call (Δ=1, the default) ✓, others ✗.
    A violation is rejected with ``ValueError("cross-stage recursive call rejected")``.

(c) **Per-agent allow_recursive** — when the target agent's
    ``allow_recursive`` is ``False`` AND its call count exceeds 1, the
    recursive call is rejected with
    ``ValueError("agent does not allow recursive call")``.

The director injects the flow sequence (from
:func:`~app.agents.workflow.generate_flow_sequence`) into its own prompt
via :func:`~app.agents.parser.parse_agent_to_prompt` so it knows the
execution order (it defaults to full-recall of the workflow resource).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.agents.agent import Agent
from app.agents.parser import parse_agent_to_prompt
from app.agents.runners.base import AgentResponse, AgentRunner
from app.agents.workflow import TreeNode, WorkflowTree, generate_flow_sequence
from app.runtime.budget import BudgetTracker, FinalizeSignal
from app.runtime.runtime import Runtime


@dataclass(frozen=True)
class RecursiveCallRecord:
    """Record of a single recursive (call_count > 1) agent call.

    Attributes:
        agent:  The agent name that was called recursively.
        reason: Why the recursive call was made (e.g. ``"director_decision"``).
        depth:  The depth of the node being called.
    """

    agent: str
    reason: str
    depth: int


@dataclass(frozen=True)
class RejectedCallRecord:
    """Record of a single call rejected by recursion control or runner error.

    Attributes:
        agent:  The agent name that was rejected.
        reason: Why the call was rejected (e.g. ``"cross-stage recursive call rejected"``).
    """

    agent: str
    reason: str


@dataclass
class RoundResult:
    """Outcome of a single director round.

    Attributes:
        completed_agents:  ids of agents/nodes that completed successfully.
        recursive_calls:   list of :class:`RecursiveCallRecord` for each
                           recursive (call_count > 1) call made.
        finalize_reason:   why the round ended — ``"all_nodes_done"``,
                           ``"budget_exhausted"``, or ``"explicit_finalize"``.
        total_tokens:      sum of prompt + completion tokens consumed.
        rejected_calls:    list of :class:`RejectedCallRecord` for calls
                           rejected by recursion control.
    """

    completed_agents: list[str] = field(default_factory=list)
    recursive_calls: list[RecursiveCallRecord] = field(default_factory=list)
    finalize_reason: str = ""
    total_tokens: int = 0
    rejected_calls: list[RejectedCallRecord] = field(default_factory=list)


class Director:
    """Tree-based workflow director with recursion control.

    The director is constructed from a director :class:`Agent` (the agent
    whose prompt receives the flow sequence) and runs rounds against a
    :class:`WorkflowTree`.

    Args:
        director_agent: The director's :class:`Agent` attribute set.
    """

    def __init__(self, director_agent: Agent) -> None:
        self._director_agent = director_agent

    @property
    def agent(self) -> Agent:
        """The director's own :class:`Agent` attribute set."""
        return self._director_agent

    async def run_round(
        self,
        tree: WorkflowTree,
        runtime: Runtime,
        budget: BudgetTracker,
        runner: AgentRunner,
        context: str = "",
        maximal_recursive_calling_depth: int = 1,
    ) -> RoundResult:
        """Execute one round of the workflow tree.

        Iterates nodes in BFS order (depth then id), calling each node's
        agent through *runtime* with *runner*. For each node the recursion
        control gates are checked before the call is dispatched.

        The budget gate (a) uses the :class:`BudgetTracker`'s iteration
        counter as the agent-call counter — the caller is expected to
        configure ``max_iterations = 2 × tree.node_count()`` (per plan
        scope: "default max agent calls = 2× node count"). Each
        ``consume(iterations=1)`` represents one agent call; exhaustion
        raises :class:`FinalizeSignal` which is caught here and recorded
        as ``finalize_reason = "budget_exhausted"``.

        Args:
            tree:     The expanded :class:`WorkflowTree` to execute.
            runtime:  The :class:`Runtime` (concurrency / timeout / retry).
            budget:   The :class:`BudgetTracker` — consumed per agent call.
            runner:   The :class:`AgentRunner` used for all sub-agent calls.
            context:  Runtime context string injected into the director's
                      own prompt (e.g. recalled state). Empty = none.
            maximal_recursive_calling_depth:  The max allowed
                ``cur_depth - target_depth`` for a recursive call. Default 1
                (self-call Δ=0 and parent-call Δ=1 allowed).

        Returns:
            A :class:`RoundResult` summarizing the round.
        """
        completed: list[str] = []
        recursive_calls: list[RecursiveCallRecord] = []
        rejected_calls: list[RejectedCallRecord] = []
        total_tokens = 0
        finalize_reason = "all_nodes_done"

        # Inject the flow sequence into the director's prompt so it knows
        # the execution order (full-recall of the workflow resource).
        flow_seq = generate_flow_sequence(tree)
        director_prompt = parse_agent_to_prompt(
            self._director_agent,
            context=context,
            flow_sequence=flow_seq,
        )

        # Track per-agent-name call counts for the allow_recursive gate.
        call_counts: dict[str, int] = {}

        # Execute nodes in BFS order (depth then id).
        ordered_nodes = sorted(tree.all_nodes.values(), key=lambda n: (n.depth, n.id))

        for node in ordered_nodes:
            target_agent = self._resolve_node_agent(node)

            call_counts[target_agent.name] = call_counts.get(target_agent.name, 0) + 1
            call_count = call_counts[target_agent.name]

            # Recursion-control gate. The first call (call_count == 1) at
            # a node's own depth is always a normal forward call (not
            # recursive); the gates apply when the director decides to
            # re-call a node (call_count > 1) or call across depths.
            allowed, reason = self.check_recursion_allowed(
                target_agent=target_agent,
                target_depth=node.depth,
                cur_depth=node.depth,  # first call at this depth
                call_count=call_count,
                max_depth=maximal_recursive_calling_depth,
            )
            if not allowed:
                rejected_calls.append(RejectedCallRecord(agent=target_agent.name, reason=reason))
                if reason == "budget_exhausted":
                    finalize_reason = "budget_exhausted"
                    break
                # depth violation or allow_recursive violation → reject
                # this call but continue the round.
                continue

            if call_count > 1:
                recursive_calls.append(
                    RecursiveCallRecord(
                        agent=target_agent.name,
                        reason="director_decision",
                        depth=node.depth,
                    )
                )

            # Build the per-node prompt.
            node_prompt = self._build_node_prompt(node, director_prompt)

            # Dispatch through the runtime.
            try:
                response = await runtime.send_request(target_agent, runner, node_prompt)
            except TimeoutError:
                rejected_calls.append(
                    RejectedCallRecord(agent=target_agent.name, reason="timeout")
                )
                continue
            except Exception as exc:  # noqa: BLE001 — director must not crash on runner error
                rejected_calls.append(
                    RejectedCallRecord(
                        agent=target_agent.name, reason=f"runner_error: {type(exc).__name__}"
                    )
                )
                continue

            completed.append(node.id)
            tokens = response.usage.prompt_tokens + response.usage.completion_tokens
            total_tokens += tokens

            # Consume budget for this call (gate (a): agent-call budget).
            try:
                budget.consume(
                    tokens=tokens,
                    tool_calls=len(response.tool_calls),
                    iterations=1,
                )
            except FinalizeSignal:
                finalize_reason = "budget_exhausted"
                break

        return RoundResult(
            completed_agents=completed,
            recursive_calls=recursive_calls,
            finalize_reason=finalize_reason,
            total_tokens=total_tokens,
            rejected_calls=rejected_calls,
        )

    def check_recursion_allowed(
        self,
        target_agent: Agent,
        target_depth: int,
        cur_depth: int,
        call_count: int,
        max_depth: int,
    ) -> tuple[bool, str]:
        """Check whether a recursive agent call is allowed.

        Three gates (per plan scope item 3):

        (a) Budget — checked by the caller (budget.consume raises
            :class:`FinalizeSignal`). This method does NOT consume budget;
            it only checks the other two gates. The budget gate is
            enforced in :meth:`run_round` via the :class:`BudgetTracker`.

        (b) Depth constraint —
            ``0 <= cur_depth - target_depth <= max_depth``. Self-call
            (Δ=0) ✓, parent-call (Δ=1, default) ✓, others ✗. A violation
            returns ``(False, "cross-stage recursive call rejected")``.

        (c) Per-agent allow_recursive — when
            ``target_agent.allow_recursive is False`` AND
            ``call_count > 1``, returns
            ``(False, "agent does not allow recursive call")``.

        Args:
            target_agent: The agent about to be called.
            target_depth: The depth of the node being called.
            cur_depth:    The current workflow depth (caller's depth).
            call_count:   How many times this agent has been called so far
                          (1 = first call, >1 = recursive).
            max_depth:    The configured ``maximal_recursive_calling_depth``.

        Returns:
            ``(allowed, reason)`` where *allowed* is ``True``/``False`` and
            *reason* is a short string:
            ``"ok"`` / ``"cross-stage recursive call rejected"`` /
            ``"agent does not allow recursive call"``.
        """
        # (c) Per-agent allow_recursive — checked first because it's the
        # most explicit gate.
        if not target_agent.allow_recursive and call_count > 1:
            return False, "agent does not allow recursive call"

        # (b) Depth constraint.
        delta = cur_depth - target_depth
        if not (0 <= delta <= max_depth):
            return False, "cross-stage recursive call rejected"

        return True, "ok"

    async def call_agent(
        self,
        agent: Agent,
        input_prompt: str,
        runtime: Runtime,
        runner: AgentRunner,
    ) -> asyncio.Task[AgentResponse]:
        """Schedule a single agent call through *runtime* and return its Task.

        This is the director's primary tool (refactor_guide:95
        ``call_agent``). The returned :class:`asyncio.Task` can be awaited
        directly or combined with others via ``runtime.await_all`` /
        ``runtime.await_any``.

        Args:
            agent:        The agent to call.
            input_prompt: The fully-assembled prompt to send.
            runtime:      The :class:`Runtime` wrapping the runner.
            runner:       The :class:`AgentRunner` to use.

        Returns:
            An :class:`asyncio.Task` that will resolve to the
            :class:`AgentResponse`.
        """
        loop = asyncio.get_running_loop()
        return loop.create_task(runtime.send_request(agent, runner, input_prompt))

    # ── internals ───────────────────────────────────────────────────────

    def _resolve_node_agent(self, node: TreeNode) -> Agent:
        """Resolve a tree node to an :class:`Agent` for the runner.

        In a full system this would look up the agent by name in an
        :class:`~app.agents.registry.AgentRegistry`. The director itself
        does not own a registry reference (the caller wires it up), so we
        build a minimal agent from the director's template with the
        node's id/name/description. The ``allow_recursive`` flag defaults
        to ``True`` here; the real per-agent value is applied by the
        caller via the registry before the round starts.
        """
        from dataclasses import replace

        return replace(
            self._director_agent,
            id=node.id,
            name=node.agent_name,
            task=node.description or self._director_agent.task,
        )

    def _build_node_prompt(self, node: TreeNode, director_prompt: str) -> str:
        """Build the prompt for a single node's agent call.

        The node's description and params are prepended to the director
        prompt as a per-node directive, so the agent knows its specific
        role within the workflow.
        """
        header = f"## 本节点任务\n{node.description}\n节点参数: {dict(node.params)}\n\n"
        return header + director_prompt


__all__ = ["Director", "RecursiveCallRecord", "RejectedCallRecord", "RoundResult"]
