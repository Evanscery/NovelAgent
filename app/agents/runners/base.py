"""Abstract AgentRunner base class — the LLM-call boundary.

A runner takes an agent and a prompt and returns an ``AgentResponse``. The
Runtime layer (``app.runtime.runtime``) wraps a runner with concurrency,
timeout, and retry — the runner itself only concerns itself with producing
a single response from a single call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class RunnerAgent(Protocol):
    """Minimal agent view a runner needs.

    The full ``Agent`` class is defined in todo 15 (``app/agents/agent.py``)
    and is not yet implemented. A runner only reads ``id`` and ``model``
    from the agent, so we depend on this narrow Protocol to avoid a circular
    import and to keep the runner agent-agnostic.
    """

    id: str
    model: str | None


@dataclass(frozen=True)
class ToolCall:
    """A single tool call parsed from a model response.

    Attributes:
        name: Tool name (e.g. ``"read"``, ``"search"``, ``"write"``).
        args: Tool arguments as a JSON-like dict.
    """

    name: str
    args: dict[str, object]


@dataclass(frozen=True)
class TokenUsage:
    """Token accounting for a single model response."""

    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class AgentResponse:
    """The normalized result of a single runner invocation.

    Attributes:
        text:        The textual content of the model response.
        tool_calls:  Any tool calls the model requested (empty for plain text).
        usage:       Token accounting (zeros if the provider did not report).
        raw:         Provider-specific raw response payload, for debugging /
                     advanced consumers. Untyped on purpose.
    """

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=lambda: TokenUsage(0, 0))
    raw: dict[str, object] = field(default_factory=dict)


class AgentRunner(ABC):
    """Abstract base class for all agent runners.

    Subclasses implement :meth:`run`, which takes an agent and a prompt and
    returns an :class:`AgentResponse`. Implementations MUST be deterministic
    for a given input except where they genuinely contact an external service
    (e.g. :class:`DirectRunner`).
    """

    @abstractmethod
    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        """Execute a single agent request and return the normalized response.

        Args:
            agent:  The agent whose attributes (model, id, …) drive the call.
            prompt: The fully-assembled prompt string to send.

        Returns:
            An :class:`AgentResponse`.
        """
        ...
