"""Mock runner — deterministic canned responses, NO LLM.

Used for tests and dry-runs. The same ``(agent.id, request)`` pair always
produces the same :class:`AgentResponse`; no randomness, no network.
"""

from __future__ import annotations

from app.runtime.prompt_builder import RequestSpec

from .base import AgentResponse, AgentRunner, RunnerAgent, TokenUsage


class MockRunner(AgentRunner):
    """Deterministic runner that returns a canned response derived from input.

    The response text is a stable function of ``agent.id`` and the
    request's :meth:`~app.runtime.prompt_builder.RequestSpec.fingerprint`:
    same inputs always yield the same output. Token usage is derived from
    the total request text length so it is likewise deterministic.
    """

    async def run(self, agent: RunnerAgent, request: RequestSpec) -> AgentResponse:
        request_hash = request.fingerprint()[:12]
        text = f"[mock:{agent.id}] Response for prompt {request_hash}"
        prompt_chars = len(request.system) + sum(len(m.content) for m in request.messages)
        usage = TokenUsage(
            prompt_tokens=prompt_chars // 4,
            completion_tokens=100,
        )
        return AgentResponse(text=text, tool_calls=[], usage=usage, raw={"mock": True})
