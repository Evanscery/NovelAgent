"""Provider encoder seam — RequestSpec <-> provider wire format.

A :class:`RequestEncoder` turns a provider-neutral
:class:`~app.runtime.prompt_builder.RequestSpec` into a concrete request
body and decodes the provider's response payload back into the
normalized :class:`~app.runtime.runners.base.AgentResponse`.

Only the OpenAI chat-completions encoder exists today
(:class:`~app.runtime.providers.openai_chat.OpenAIChatEncoder`); other
providers (Anthropic messages, OpenAI responses, ...) plug in by
implementing this Protocol — no runner changes required.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.runtime.prompt_builder import RequestSpec
from app.runtime.runners.base import AgentResponse

__all__ = ["RequestEncoder"]


@runtime_checkable
class RequestEncoder(Protocol):
    """Encodes requests for — and decodes responses from — one provider."""

    def encode(self, request: RequestSpec) -> dict[str, object]:
        """Render *request* as the provider's JSON request body.

        The body carries messages / tools / model as the provider expects
        them. Callers may still override ``body["model"]`` (e.g. a runner
        applying its configured default when the spec has none).
        """
        ...

    def decode(self, payload: object) -> AgentResponse:
        """Parse the provider's response JSON into an :class:`AgentResponse`.

        Raises:
            RuntimeError: If the payload does not have the provider's
                expected shape.
        """
        ...
