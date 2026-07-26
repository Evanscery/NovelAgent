"""Runtime prompt builder — assembles provider-neutral request specs.

The agent layer's parser renders an agent's **system prompt** (static
per-agent config). Everything conversational — history messages, the
user message, injected reminders — is runtime state, assembled here into
a :class:`RequestSpec`. Provider encoders (:mod:`app.runtime.providers`)
turn a spec into a concrete wire format; the spec itself never commits
to one.

Layering: runtime imports agents (parser, tool schemas); the agent layer
never imports this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from app.agents.parser import render_agent_system_prompt
from app.agents.tools import ToolSchema

if TYPE_CHECKING:
    from app.agents.agent import Agent
    from app.runtime.runners.base import ToolCall

__all__ = [
    "Message",
    "PromptBuilder",
    "RequestSpec",
    "Role",
    "ToolSchemaSource",
]

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    """One conversation message, provider-neutral.

    Attributes:
        role:         ``"system"`` / ``"user"`` / ``"assistant"`` / ``"tool"``.
        content:      The message text.
        tool_call_id: For ``tool`` messages: the id of the tool call this
                      message answers (mirrors the OpenAI chat shape).
        name:         For ``tool`` messages: the tool name that produced
                      this result.
        tool_calls:   For ``assistant`` messages: the tool calls the model
                      emitted in this turn. Required by OpenAI-compatible
                      endpoints — a ``tool`` message is only valid after an
                      assistant message carrying the matching call id.
    """

    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: tuple[ToolCall, ...] | None = None


@dataclass(frozen=True)
class RequestSpec:
    """A fully-assembled, provider-neutral model request.

    Attributes:
        system:   The system prompt (empty string for none).
        messages: Conversation messages in order (excluding the system
                  prompt, which is carried separately so encoders can
                  place it per-provider).
        tools:    Tool schemas advertised to the model.
        model:    Model identifier, or ``None`` to use the runner default.

    Deliberately minimal: no sampling parameters (temperature / top_p /
    ...) until a concrete consumer needs them.
    """

    system: str
    messages: list[Message] = field(default_factory=list)
    tools: list[ToolSchema] = field(default_factory=list)
    model: str | None = None

    def fingerprint(self) -> str:
        """Return a canonical sha256 hex digest of this spec.

        Deterministic across processes: the digest is computed over a
        canonical JSON encoding (sorted keys, no whitespace) of every
        semantic field. Two specs with identical content always share a
        fingerprint; any change to system / messages / tools / model
        changes it.
        """
        canonical: dict[str, object] = {
            "system": self.system,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_call_id": m.tool_call_id,
                    "name": m.name,
                    "tool_calls": None
                    if m.tool_calls is None
                    else [
                        {"id": tc.id, "name": tc.name, "args": tc.args}
                        for tc in m.tool_calls
                    ],
                }
                for m in self.messages
            ],
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "source": t.source,
                }
                for t in self.tools
            ],
            "model": self.model,
        }
        payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ToolSchemaSource(Protocol):
    """Anything that resolves tool names to :class:`ToolSchema` objects.

    Implemented by the runtime :class:`~app.runtime.tool_catalog.ToolCatalog`.
    Unknown names are skipped with a warning, never raised — an agent
    config naming a tool this runtime doesn't know must not break the
    round.
    """

    def schemas_for(self, names: Sequence[str]) -> list[ToolSchema]: ...


class PromptBuilder:
    """Builds :class:`RequestSpec` objects for agent requests.

    Args:
        catalog: The tool-schema source used to resolve each agent's
            ``tools`` name list into schemas.
    """

    def __init__(self, catalog: ToolSchemaSource) -> None:
        self._catalog = catalog

    def build(
        self,
        agent: Agent,
        *,
        history: Sequence[Message] = (),
        user_text: str | None = None,
        reminders: Sequence[str] = (),
        flow_sequence: str = "",
    ) -> RequestSpec:
        """Assemble the request spec for one agent call.

        Args:
            agent:         The agent whose config drives the system prompt,
                           tool surface, and model.
            history:       Prior conversation messages, in order.
            user_text:     The new user message, if any.
            reminders:     Runtime reminder strings; each is appended to the
                           trailing user message as a ``<system-reminder>``
                           block (a new user message is created when there
                           is none to append to).
            flow_sequence: Workflow execution-order text (director-only);
                           rendered into the system prompt.
        """
        system = render_agent_system_prompt(agent, flow_sequence=flow_sequence)

        messages: list[Message] = list(history)
        if user_text is not None:
            messages.append(Message(role="user", content=user_text))

        if reminders:
            blocks = "\n\n".join(
                f"<system-reminder>\n{reminder}\n</system-reminder>" for reminder in reminders
            )
            if messages and messages[-1].role == "user":
                last = messages[-1]
                messages[-1] = Message(
                    role="user",
                    content=f"{last.content}\n\n{blocks}",
                    tool_call_id=last.tool_call_id,
                    name=last.name,
                )
            else:
                messages.append(Message(role="user", content=blocks))

        return RequestSpec(
            system=system,
            messages=messages,
            tools=self._catalog.schemas_for(agent.tools),
            model=agent.model,
        )
