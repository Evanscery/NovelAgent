"""Mock runner — deterministic canned responses, NO LLM.

Used for tests and dry-runs. The same ``(agent.id, prompt)`` pair always
produces the same :class:`AgentResponse`; no randomness, no network.
"""

from __future__ import annotations

import hashlib

from .base import AgentResponse, AgentRunner, RunnerAgent, TokenUsage


class MockRunner(AgentRunner):
    """Deterministic runner that returns a canned response derived from input.

    The response text is a stable function of ``agent.id`` and ``prompt``:
    same inputs always yield the same output. Token usage is derived from
    the prompt length so it is likewise deterministic.
    """

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        text = f"[mock:{agent.id}] Response for prompt {prompt_hash}"
        usage = TokenUsage(
            prompt_tokens=len(prompt) // 4,
            completion_tokens=100,
        )
        return AgentResponse(text=text, tool_calls=[], usage=usage, raw={"mock": True})
