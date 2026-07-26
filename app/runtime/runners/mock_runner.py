"""Mock runner — deterministic canned responses, NO LLM.

Used for tests and dry-runs. The same ``(agent.id, request)`` pair always
produces the same :class:`AgentResponse`; no randomness, no network.

Scripted mode (default) makes the mock walk a real round instead of
answering with inert text:

* A request whose tool surface includes ``call_agent`` AND whose system
  prompt carries a ``## 工作流执行顺序`` section is treated as a workflow
  director turn: the runner calls each flow agent once, in order (one per
  turn, resuming from the tool messages already in history), then emits
  ``finalize`` with a deterministic ``final_text`` / ``summary``.
* A request whose tool surface includes ``write`` and whose system prompt
  grants at least one writable resource type is treated as a working
  sub-agent: it emits one ``write`` tool call into its first writable
  resource.
* Anything else (chat director turns, read-only sub-agents) falls back to
  the classic deterministic text response.

Everything is derived from the request content (both sections are rendered
by :mod:`app.agents.parser`, so their shapes are stable), keeping the mock
fully deterministic while exercising dispatch, per-agent permission tools,
tool messages, and finalize.
"""

from __future__ import annotations

import re

from app.runtime.prompt_builder import RequestSpec

from .base import AgentResponse, AgentRunner, RunnerAgent, TokenUsage, ToolCall

# Matches lines rendered by app.agents.flow_sequence.generate_flow_sequence:
#   "1. [depth=0] writer: description (annotation)"
_FLOW_LINE_RE = re.compile(r"^\d+\.\s+\[depth=\d+\]\s+([^:(\n]+)", re.MULTILINE)

# Matches the write line rendered by app.agents.parser._format_permission_section:
#   "你只能写入以下资源: state, notes"
_WRITE_PERM_RE = re.compile(r"^你只能写入以下资源:\s*(.+)$", re.MULTILINE)

_FLOW_SECTION_HEADER = "## 工作流执行顺序"


class MockRunner(AgentRunner):
    """Deterministic runner that returns a canned response derived from input.

    The response is a stable function of ``agent.id`` and the request's
    :meth:`~app.runtime.prompt_builder.RequestSpec.fingerprint`: same
    inputs always yield the same output. Token usage is derived from the
    total request text length so it is likewise deterministic.

    Args:
        scripted: When ``True`` (default), workflow director turns and
            writable sub-agents produce scripted tool calls (see module
            docstring) so a mock round covers dispatch, permission tools,
            and finalize. ``False`` restores the inert text-only behavior.
    """

    def __init__(self, scripted: bool = True) -> None:
        self._scripted = scripted

    async def run(self, agent: RunnerAgent, request: RequestSpec) -> AgentResponse:
        usage = self._usage(request)
        if self._scripted:
            tool_names = {schema.name for schema in request.tools}
            if "call_agent" in tool_names:
                scripted = self._director_step(agent, request, usage)
                if scripted is not None:
                    return scripted
            elif "write" in tool_names:
                scripted = self._writer_step(agent, request, usage)
                if scripted is not None:
                    return scripted

        request_hash = request.fingerprint()[:12]
        text = f"[mock:{agent.id}] Response for prompt {request_hash}"
        return AgentResponse(text=text, tool_calls=[], usage=usage, raw={"mock": True})

    # -- scripted steps ----------------------------------------------------

    def _director_step(
        self,
        agent: RunnerAgent,
        request: RequestSpec,
        usage: TokenUsage,
    ) -> AgentResponse | None:
        """Scripted workflow-director turn: call the next flow agent, then finalize."""
        if _FLOW_SECTION_HEADER not in request.system:
            return None  # chat mode — no flow to walk
        flow_section = request.system.split(_FLOW_SECTION_HEADER, 1)[1]
        flow_agents = [m.strip() for m in _FLOW_LINE_RE.findall(flow_section)]
        if not flow_agents:
            return None

        done = sum(
            1
            for message in request.messages
            if message.role == "tool" and message.name == "call_agent"
        )
        if done < len(flow_agents):
            target = flow_agents[done]
            call = ToolCall(
                name="call_agent",
                args={
                    "agent_name": target,
                    "prompt": f"[mock director] 请执行你的职责（工作流第 {done + 1} 步）。",
                },
                id=f"mock_call_{done + 1}",
            )
            text = f"[mock:{agent.id}] 调度 {target}（第 {done + 1}/{len(flow_agents)} 步）"
            return AgentResponse(text=text, tool_calls=[call], usage=usage, raw={"mock": True})

        request_hash = request.fingerprint()[:12]
        call = ToolCall(
            name="finalize",
            args={
                "reason": "all workflow agents completed",
                "final_text": (
                    f"[mock 章节 {request_hash}]\n\n"
                    "这是 mock 轮产出的确定性章节正文，用于验证正文落盘与提交链路。"
                ),
                "summary": f"[mock 摘要 {request_hash}] 本轮完成 {len(flow_agents)} 个工作流节点。",
            },
            id="mock_finalize",
        )
        text = f"[mock:{agent.id}] 所有节点完成，收束本轮"
        return AgentResponse(text=text, tool_calls=[call], usage=usage, raw={"mock": True})

    def _writer_step(
        self,
        agent: RunnerAgent,
        request: RequestSpec,
        usage: TokenUsage,
    ) -> AgentResponse | None:
        """Scripted working sub-agent: write once into the first writable resource."""
        match = _WRITE_PERM_RE.search(request.system)
        if match is None:
            return None
        writable = [part.strip() for part in match.group(1).split(",") if part.strip()]
        if not writable:
            return None

        target = writable[0]
        request_hash = request.fingerprint()[:12]
        call = ToolCall(
            name="write",
            args={
                "resource_type": target,
                "filename": "mock_output.md",
                "content": f"[mock:{agent.id}] 写入 {target} 的确定性内容 {request_hash}",
            },
            id="mock_write_1",
        )
        text = f"[mock:{agent.id}] 已向 {target} 写入本轮产出"
        return AgentResponse(text=text, tool_calls=[call], usage=usage, raw={"mock": True})

    @staticmethod
    def _usage(request: RequestSpec) -> TokenUsage:
        prompt_chars = len(request.system) + sum(len(m.content) for m in request.messages)
        return TokenUsage(prompt_tokens=prompt_chars // 4, completion_tokens=100)
