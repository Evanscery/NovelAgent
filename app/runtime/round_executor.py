"""RoundExecutor — runtime-layer tool-call-driven agent execution loop.

The :class:`RoundExecutor` owns the per-round loop that drives the
director. The director is a *system agent* (loaded from
``director.yaml`` by the registry, an :class:`~app.agents.agent.Agent`
like any other); the executor is the *runtime loop*.

Per the correct design (refactor_guide:92-101):

* The director decides via LLM which agents to call. Its response
  carries ``tool_calls`` (a list of :class:`ToolCall`). The executor
  parses them and dispatches each.
* The workflow tree is injected into the director's prompt as context
  via :func:`~app.agents.workflow.generate_flow_sequence` — the
  runtime does NOT traverse it. The tree is information the director
  uses to decide what to call.
* Budget + recursion depth are soft constraints enforced here.

The loop::

    send director prompt  (with flow_sequence + context + tool results so far)
    ↓
    director response (text + tool_calls)
    ↓
    for each tool_call:
        call_agent → resolve from registry, run sub-agent via runtime, store handle
        await      → return the stored sub-agent response text
        finalize   → end the round with reason "explicit_finalize"
        read/write/list_files/glob_files/grep_lines/read_lines → dispatch to the director's ToolDispatcher (ScopedTools)
        <unknown>  → record RejectedCallRecord("unknown_tool")
    ↓
    feed tool results back into the next director prompt
    ↓
    repeat until finalize / budget exhausted / no tool calls

Three recursion-control gates (plan scope item 3) are enforced on each
``call_agent`` dispatch:

(a) **Budget** — :class:`~app.runtime.budget.BudgetTracker` is consumed
    per director iteration and per sub-agent call. When exhausted the
    round finalizes with reason ``"budget_exhausted"``.

(b) **Depth constraint** —
    ``0 <= cur_depth - target_depth <= maximal_recursive_calling_depth``.
    Self-call (Δ=0) allowed, parent-call (Δ=1, default) allowed, others
    rejected with ``"cross-stage recursive call rejected"``.

(c) **Per-agent allow_recursive** — when the target agent's
    ``allow_recursive`` is ``False`` AND its call count exceeds 1, the
    recursive call is rejected with
    ``"agent does not allow recursive call"``.

For chat mode (``tree=None``) no flow sequence is injected and only
the director agent is called (single-shot, no tool-call loop).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.agents.agent import Agent
from app.agents.parser import parse_agent_to_prompt
from app.agents.tree_model import AGENT_KIND
from app.agents.workflow import WorkflowTree, generate_flow_sequence
from app.runtime.budget import BudgetTracker, FinalizeSignal
from app.runtime.runners.base import (
    AgentRunner,
    ToolCall,
)
from app.runtime.runtime import Runtime
from app.runtime.tool_dispatcher import (
    ToolDispatcher,
    ToolResult,
    UnknownToolError,
)

if TYPE_CHECKING:
    from app.agents.registry import AgentRegistry


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
        reason: Why the call was rejected (e.g.
            ``"cross-stage recursive call rejected"``).
    """

    agent: str
    reason: str


@dataclass
class RoundResult:
    """Outcome of a single round.

    Attributes:
        completed_agents:  names of agents that completed successfully
                           (including the director and any sub-agents it
                           called via ``call_agent``).
        recursive_calls:   list of :class:`RecursiveCallRecord` for each
                           recursive (call_count > 1) call made.
        finalize_reason:   why the round ended -- ``"all_nodes_done"``,
                           ``"budget_exhausted"``, or ``"explicit_finalize"``.
        total_tokens:      sum of prompt + completion tokens consumed.
        rejected_calls:    list of :class:`RejectedCallRecord` for calls
                           rejected by recursion control or unknown tools.
        director_text:     The director agent's final response text. For
                           chat rounds this is the user-facing reply; for
                           full workflow rounds it is the director's last
                           textual output before finalize.
    """

    completed_agents: list[str] = field(default_factory=list)
    recursive_calls: list[RecursiveCallRecord] = field(default_factory=list)
    finalize_reason: str = ""
    total_tokens: int = 0
    rejected_calls: list[RejectedCallRecord] = field(default_factory=list)
    director_text: str = ""


class RoundExecutor:
    """Runtime-layer tool-call-driven execution loop.

    The executor is constructed once per round with the runtime
    infrastructure (runtime, runner, registry, budget), the director's
    scoped tools (for read/write/list_files/glob_files/grep_lines/read_lines dispatch), and the recursion
    depth limit. :meth:`execute_round` then drives the director in a
    tool-call loop: send prompt -> parse tool_calls -> dispatch ->
    feed back -> repeat until finalize.

    Args:
        runtime:  The :class:`Runtime` (concurrency / timeout / retry).
        runner:   The :class:`AgentRunner` used for all agent calls
                  (director + sub-agents).
        registry: The :class:`AgentRegistry` used to resolve
                  ``call_agent`` targets by name. The director agent
                  MUST be registered under the name ``"director"``.
        budget:   The :class:`BudgetTracker` -- consumed per director
                  iteration and per sub-agent call.
        director_tools: The director's :class:`ToolDispatcher` (wrapping
                  a :class:`ScopedTools` with the director's permission)
                  for dispatching read/write/list_files/glob_files/grep_lines/read_lines tool calls. May be
                  ``None`` for chat-only rounds where the director has
                  no data tools.
        maximal_recursive_calling_depth: The max allowed
                  ``cur_depth - target_depth`` for a recursive
                  ``call_agent`` call. Default 1 (self-call Δ=0 and
                  parent-call Δ=1 allowed).
    """

    def __init__(
        self,
        runtime: Runtime,
        runner: AgentRunner,
        registry: AgentRegistry,
        budget: BudgetTracker,
        director_tools: ToolDispatcher | None = None,
        maximal_recursive_calling_depth: int = 1,
    ) -> None:
        self._runtime = runtime
        self._runner = runner
        self._registry = registry
        self._budget = budget
        self._director_tools = director_tools
        self._max_depth = maximal_recursive_calling_depth

    async def execute_round(
        self,
        director: Agent,
        tree: WorkflowTree | None,
        context: str = "",
    ) -> RoundResult:
        """Execute one round of the workflow (or a chat-only round).

        When *tree* is ``None`` (chat mode), only the director agent is
        called once and its response text is captured in
        :attr:`RoundResult.director_text`. No flow sequence is injected
        and no tool-call loop runs.

        When *tree* is provided, the director's prompt receives the flow
        sequence (so it knows the execution order) and the executor
        drives the tool-call loop: each director response's
        ``tool_calls`` are dispatched (``call_agent`` / ``await`` /
        ``finalize`` / ``read`` / ``write`` / ``list_files`` / ``glob_files`` /
        ``grep_lines`` / ``read_lines``), results are
        fed back, and the loop repeats until ``finalize`` or budget
        exhaustion.

        Args:
            director: The director :class:`Agent` (loaded from
                ``director.yaml`` by the registry).
            tree:     The :class:`WorkflowTree` to provide as context to
                the director, or ``None`` for a chat-only round.
            context:  Runtime context string injected into the director's
                prompt (e.g. the user's chat message or recalled state).

        Returns:
            A :class:`RoundResult` summarizing the round.
        """
        # Chat mode: no tree, no tool-call loop -- single director call.
        if tree is None:
            return await self._execute_chat_round(director, context)

        return await self._execute_workflow_round(director, tree, context)

    # ── workflow round (tool-call loop) ────────────────────────────────

    async def _execute_workflow_round(
        self,
        director: Agent,
        tree: WorkflowTree,
        context: str,
    ) -> RoundResult:
        """Drive the director in a tool-call loop until finalize/budget."""
        completed: list[str] = []
        recursive_calls: list[RecursiveCallRecord] = []
        rejected_calls: list[RejectedCallRecord] = []
        total_tokens = 0
        finalize_reason = "all_nodes_done"
        director_text = ""

        flow_seq = generate_flow_sequence(tree)
        # Name -> definition_id mapping from the tree's nodes. The director
        # names call_agent targets by display name (what the flow sequence
        # shows), but display names are not identities: an imported
        # workflow may carry an agent whose name collides with a local
        # one. Nodes that resolved a definition (definition_id set) pin
        # their name to that id, so dispatch is id-first and collisions
        # cannot reroute the call.
        name_to_definition_id: dict[str, str] = {}
        for node in tree.all_nodes.values():
            if node.kind == AGENT_KIND and node.definition_id is not None:
                name_to_definition_id.setdefault(node.agent_name, node.definition_id)
        # Per-agent-name call counts for the allow_recursive gate.
        call_counts: dict[str, int] = {}
        # Pending sub-agent results keyed by handle (call_agent returns a
        # handle; await retrieves the result). In this synchronous loop
        # call_agent completes immediately, so the handle maps directly
        # to the sub-agent's response text.
        pending: dict[str, str] = {}

        # The running "tool results so far" block appended to each
        # subsequent director prompt so the director sees prior outputs.
        tool_feedback: list[str] = []

        # The director's own depth is 0 (it is the system agent, not a
        # workflow node). Sub-agents called via call_agent are at depth 1
        # by default; the director may pass an explicit depth via the
        # tool args, but the simple loop treats all call_agent targets
        # as depth-1 children.
        director_depth = 0

        while True:
            # Budget check: consume one iteration for this director turn.
            if self._budget.is_exhausted():
                finalize_reason = "budget_exhausted"
                break

            # Assemble the director prompt: base prompt + tool feedback.
            feedback_block = (
                "\n\n## 工具调用结果\n" + "\n".join(tool_feedback)
                if tool_feedback
                else ""
            )
            director_prompt = parse_agent_to_prompt(
                director,
                context=context,
                flow_sequence=flow_seq,
            ) + feedback_block

            # Send the director request through the runtime.
            try:
                response = await self._runtime.send_request(
                    director, self._runner, director_prompt
                )
            except TimeoutError:
                rejected_calls.append(
                    RejectedCallRecord(agent="director", reason="timeout")
                )
                finalize_reason = "runner_error"
                break
            except Exception as exc:  # noqa: BLE001 -- loop must not crash
                rejected_calls.append(
                    RejectedCallRecord(
                        agent="director",
                        reason=f"runner_error: {type(exc).__name__}",
                    )
                )
                finalize_reason = "runner_error"
                break

            director_text = response.text
            tokens = response.usage.prompt_tokens + response.usage.completion_tokens
            total_tokens += tokens
            completed.append("director")

            # Consume budget for the director turn.
            try:
                self._budget.consume(
                    tokens=tokens,
                    tool_calls=len(response.tool_calls),
                    iterations=1,
                )
            except FinalizeSignal:
                finalize_reason = "budget_exhausted"
                break

            # No tool calls -> director produced a plain-text answer.
            # The round ends (nothing more to dispatch).
            if not response.tool_calls:
                break

            # Dispatch each tool call. If any is `finalize`, the round
            # ends immediately after processing the batch.
            finalized = False
            for tc in response.tool_calls:
                # Budget may have been exhausted mid-batch by a prior
                # tool call's consume; check before each dispatch.
                if self._budget.is_exhausted():
                    finalize_reason = "budget_exhausted"
                    finalized = True
                    break

                outcome = await self._dispatch_tool_call(
                    tc,
                    director_depth=director_depth,
                    call_counts=call_counts,
                    recursive_calls=recursive_calls,
                    rejected_calls=rejected_calls,
                    pending=pending,
                    name_to_definition_id=name_to_definition_id,
                )

                if outcome.finalized:
                    finalize_reason = "explicit_finalize"
                    finalized = True
                    break

                if outcome.completed_agent is not None:
                    completed.append(outcome.completed_agent)
                    total_tokens += outcome.tokens

                # Consume budget for a sub-agent call (call_agent).
                if outcome.tokens > 0 or outcome.tool_calls > 0:
                    try:
                        self._budget.consume(
                            tokens=outcome.tokens,
                            tool_calls=outcome.tool_calls,
                            iterations=0,  # sub-agent call, not a director turn
                        )
                    except FinalizeSignal:
                        finalize_reason = "budget_exhausted"
                        finalized = True
                        break

                # Feed the tool result back to the director.
                if outcome.feedback:
                    tool_feedback.append(outcome.feedback)

            if finalized:
                break

        return RoundResult(
            completed_agents=completed,
            recursive_calls=recursive_calls,
            finalize_reason=finalize_reason,
            total_tokens=total_tokens,
            rejected_calls=rejected_calls,
            director_text=director_text,
        )

    # ── chat round (single director call, no loop) ────────────────────

    async def _execute_chat_round(
        self,
        director: Agent,
        context: str,
    ) -> RoundResult:
        """Run a chat-only round: call only the director, capture its text.

        No workflow tree, no flow sequence, no tool-call loop -- the
        director is the sole agent and its response text is the
        user-facing reply.
        """
        prompt = parse_agent_to_prompt(director, context=context, flow_sequence="")
        try:
            response = await self._runtime.send_request(director, self._runner, prompt)
        except Exception as exc:  # noqa: BLE001 -- chat must not crash
            return RoundResult(
                completed_agents=[],
                recursive_calls=[],
                finalize_reason=f"runner_error: {type(exc).__name__}",
                total_tokens=0,
                rejected_calls=[
                    RejectedCallRecord(
                        agent="director",
                        reason=f"runner_error: {type(exc).__name__}",
                    )
                ],
                director_text="",
            )

        tokens = response.usage.prompt_tokens + response.usage.completion_tokens
        try:
            self._budget.consume(
                tokens=tokens,
                tool_calls=len(response.tool_calls),
                iterations=1,
            )
        except FinalizeSignal:
            pass  # budget exhausted after a single chat call -- acceptable

        return RoundResult(
            completed_agents=["director"],
            recursive_calls=[],
            finalize_reason="all_nodes_done",
            total_tokens=tokens,
            rejected_calls=[],
            director_text=response.text,
        )

    # ── tool-call dispatch ─────────────────────────────────────────────

    async def _dispatch_tool_call(
        self,
        tool_call: ToolCall,
        *,
        director_depth: int,
        call_counts: dict[str, int],
        recursive_calls: list[RecursiveCallRecord],
        rejected_calls: list[RejectedCallRecord],
        pending: dict[str, str],
        name_to_definition_id: dict[str, str] | None = None,
    ) -> _ToolDispatchOutcome:
        """Dispatch a single director tool call.

        Routes ``call_agent`` / ``await`` / ``finalize`` to the
        executor's own handlers and ``read`` / ``write`` / ``list_files`` /
        ``glob_files`` / ``grep_lines`` / ``read_lines``
        to the director's :class:`ToolDispatcher`. Unknown tools are
        recorded as rejected calls.

        Returns a :class:`_ToolDispatchOutcome` describing what happened
        (whether the round was finalized, which agent completed, token
        usage, and a feedback string for the next director prompt).
        """
        name = tool_call.name
        args = tool_call.args

        # ── finalize: end the round ───────────────────────────────────
        if name == "finalize":
            return _ToolDispatchOutcome(finalized=True)

        # ── call_agent: run a sub-agent via the runtime ───────────────
        if name == "call_agent":
            return await self._dispatch_call_agent(
                args,
                director_depth=director_depth,
                call_counts=call_counts,
                recursive_calls=recursive_calls,
                rejected_calls=rejected_calls,
                pending=pending,
                name_to_definition_id=name_to_definition_id or {},
            )

        # ── await: retrieve a previously scheduled sub-agent result ──
        if name == "await":
            return self._dispatch_await(args, pending=pending, rejected_calls=rejected_calls)

        # ── read / write / list_files / glob_files / grep_lines / read_lines: delegate to the director's tools ──
        if name in ("read", "write", "list_files", "glob_files", "grep_lines", "read_lines"):
            return self._dispatch_standard_tool(
                tool_call,
                rejected_calls=rejected_calls,
            )

        # ── unknown tool ──────────────────────────────────────────────
        rejected_calls.append(
            RejectedCallRecord(
                agent="director",
                reason=f"unknown_tool: {name}",
            )
        )
        return _ToolDispatchOutcome(
            feedback=f"[tool {name}] 拒绝: 未知工具",
        )

    async def _dispatch_call_agent(
        self,
        args: dict[str, object],
        *,
        director_depth: int,
        call_counts: dict[str, int],
        recursive_calls: list[RecursiveCallRecord],
        rejected_calls: list[RejectedCallRecord],
        pending: dict[str, str],
        name_to_definition_id: dict[str, str],
    ) -> _ToolDispatchOutcome:
        """Resolve and run a sub-agent named by ``call_agent``.

        Resolution is id-first: when the workflow tree pinned the display
        name to a ``definition_id``, that id is looked up directly (so an
        imported same-name agent cannot reroute or break the dispatch).
        Only unpinned names fall back to display-name resolution.

        Applies the recursion-control gates (allow_recursive + depth
        constraint) before running the sub-agent through the runtime.
        """
        agent_name = str(args.get("agent_name", ""))
        prompt = str(args.get("prompt", ""))

        # Resolve the target agent: id-first via the tree's pinned
        # definition_id, name-based fallback otherwise.
        definition_id = name_to_definition_id.get(agent_name)
        try:
            if definition_id is not None:
                target_agent = self._registry.get(definition_id)
            else:
                target_agent = self._registry.get_by_name(agent_name)
        except KeyError:
            rejected_calls.append(
                RejectedCallRecord(agent=agent_name, reason="agent_not_in_registry")
            )
            return _ToolDispatchOutcome(
                feedback=f"[call_agent {agent_name}] 拒绝: 未注册的 agent",
            )

        # Track call count for the allow_recursive gate.
        call_counts[agent_name] = call_counts.get(agent_name, 0) + 1
        call_count = call_counts[agent_name]

        # Recursion-control gate (c): per-agent allow_recursive.
        if not target_agent.allow_recursive and call_count > 1:
            rejected_calls.append(
                RejectedCallRecord(agent=agent_name, reason="agent does not allow recursive call")
            )
            return _ToolDispatchOutcome(
                feedback=f"[call_agent {agent_name}] 拒绝: 该 agent 不允许递归调用",
            )

        # Recursion-control gate (b): depth constraint.
        # The director may call agents up to ``max_depth`` levels deeper
        # than itself. A forward call to ``director_depth + 1`` is the
        # default and always allowed (when ``max_depth >= 1``). Calls
        # that would exceed the depth limit are rejected.
        target_depth = director_depth + 1
        forward_delta = target_depth - director_depth
        if forward_delta > self._max_depth:
            rejected_calls.append(
                RejectedCallRecord(agent=agent_name, reason="cross-stage recursive call rejected")
            )
            return _ToolDispatchOutcome(
                feedback=f"[call_agent {agent_name}] 拒绝: 跨阶段递归调用",
            )

        # Record recursive calls (call_count > 1) for observability.
        if call_count > 1:
            recursive_calls.append(
                RecursiveCallRecord(
                    agent=agent_name,
                    reason="director_decision",
                    depth=target_depth,
                )
            )

        # Run the sub-agent through the runtime.
        try:
            response = await self._runtime.send_request(
                target_agent, self._runner, prompt
            )
        except TimeoutError:
            rejected_calls.append(
                RejectedCallRecord(agent=agent_name, reason="timeout")
            )
            return _ToolDispatchOutcome(
                feedback=f"[call_agent {agent_name}] 拒绝: 超时",
            )
        except Exception as exc:  # noqa: BLE001 -- loop must not crash
            rejected_calls.append(
                RejectedCallRecord(
                    agent=agent_name,
                    reason=f"runner_error: {type(exc).__name__}",
                )
            )
            return _ToolDispatchOutcome(
                feedback=f"[call_agent {agent_name}] 拒绝: {type(exc).__name__}",
            )

        tokens = response.usage.prompt_tokens + response.usage.completion_tokens

        # Store the result under a handle so a later `await` can retrieve it.
        handle = f"task_{len(pending) + 1}"
        pending[handle] = response.text

        return _ToolDispatchOutcome(
            completed_agent=agent_name,
            tokens=tokens,
            tool_calls=len(response.tool_calls),
            feedback=f"[call_agent {agent_name}] -> handle={handle}: {response.text}",
            handle=handle,
        )

    def _dispatch_await(
        self,
        args: dict[str, object],
        *,
        pending: dict[str, str],
        rejected_calls: list[RejectedCallRecord],
    ) -> _ToolDispatchOutcome:
        """Retrieve a previously scheduled sub-agent result by handle."""
        handle = str(args.get("handle", ""))
        if handle not in pending:
            rejected_calls.append(
                RejectedCallRecord(agent="director", reason=f"unknown_handle: {handle}")
            )
            return _ToolDispatchOutcome(
                feedback=f"[await {handle}] 拒绝: 未知 handle",
            )
        text = pending[handle]
        return _ToolDispatchOutcome(
            feedback=f"[await {handle}] -> {text}",
        )

    def _dispatch_standard_tool(
        self,
        tool_call: ToolCall,
        *,
        rejected_calls: list[RejectedCallRecord],
    ) -> _ToolDispatchOutcome:
        """Dispatch standard tools to the director's ToolDispatcher."""
        if self._director_tools is None:
            rejected_calls.append(
                RejectedCallRecord(
                    agent="director",
                    reason=f"no_tools_surface: {tool_call.name}",
                )
            )
            return _ToolDispatchOutcome(
                feedback=f"[{tool_call.name}] 拒绝: 无工具表面",
            )

        try:
            result: ToolResult = self._director_tools.dispatch(tool_call)
        except UnknownToolError as exc:
            rejected_calls.append(
                RejectedCallRecord(
                    agent="director",
                    reason=f"unknown_tool: {tool_call.name}",
                )
            )
            return _ToolDispatchOutcome(
                feedback=f"[{tool_call.name}] 拒绝: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 -- PermissionDenied etc.
            # PermissionDenied propagates as a rejected call (the
            # director tried to read a resource it lacks permission for).
            rejected_calls.append(
                RejectedCallRecord(
                    agent="director",
                    reason=f"tool_error: {type(exc).__name__}",
                )
            )
            return _ToolDispatchOutcome(
                feedback=f"[{tool_call.name}] 拒绝: {type(exc).__name__}: {exc}",
            )

        output = result.output if result.ok else result.error
        return _ToolDispatchOutcome(
            feedback=f"[{tool_call.name}] -> {output}",
        )


@dataclass
class _ToolDispatchOutcome:
    """Internal outcome of dispatching a single director tool call.

    Attributes:
        finalized:         True if this was a `finalize` call (round ends).
        completed_agent:   Name of the sub-agent that completed (for
                           `call_agent`), else None.
        tokens:            Tokens consumed by a sub-agent call (for budget).
        tool_calls:        Tool calls produced by the sub-agent (for budget).
        feedback:          String fed back into the next director prompt.
        handle:            Task handle (for `call_agent`), for later `await`.
    """

    finalized: bool = False
    completed_agent: str | None = None
    tokens: int = 0
    tool_calls: int = 0
    feedback: str = ""
    handle: str | None = None


__all__ = [
    "RecursiveCallRecord",
    "RejectedCallRecord",
    "RoundExecutor",
    "RoundResult",
]
