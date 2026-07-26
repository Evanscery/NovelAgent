"""OpenAI chat-completions encoder — the one concrete provider encoding.

Encodes a :class:`~app.runtime.prompt_builder.RequestSpec` into the
``/chat/completions`` request body and decodes the response payload
(absorbing the parsing previously embedded in ``DirectRunner``).
"""

from __future__ import annotations

import json

from app.runtime.prompt_builder import RequestSpec
from app.runtime.runners.base import AgentResponse, TokenUsage, ToolCall

__all__ = ["OpenAIChatEncoder"]


def _as_int(value: object, default: int) -> int:
    """Coerce a usage value to int, falling back to ``default``."""
    if isinstance(value, bool | None):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _parse_arguments(args: object) -> dict[str, object]:
    """Parse an OpenAI ``function.arguments`` value into an args dict.

    OpenAI sends arguments as a JSON string; it is parsed here so the
    dispatcher always receives a plain dict. An unparseable string is
    preserved under ``"_raw"`` instead of being dropped.
    """
    if isinstance(args, dict):
        return dict(args)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": args}
        if isinstance(parsed, dict):
            return {str(k): v for k, v in parsed.items()}
        return {"_raw": args}
    return {}


def _parse_tool_calls(raw_tool_calls: list[object]) -> list[ToolCall]:
    """Extract :class:`ToolCall` objects from an OpenAI tool_calls array."""
    parsed: list[ToolCall] = []
    for entry in raw_tool_calls:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str):
            continue
        call_id = entry.get("id")
        parsed.append(
            ToolCall(
                name=name,
                args=_parse_arguments(function.get("arguments")),
                id=call_id if isinstance(call_id, str) else None,
            )
        )
    return parsed


def _parse_usage(raw_usage: object) -> TokenUsage:
    """Extract :class:`TokenUsage` from an OpenAI usage object."""
    if not isinstance(raw_usage, dict):
        return TokenUsage(0, 0)
    return TokenUsage(
        prompt_tokens=_as_int(raw_usage.get("prompt_tokens"), 0),
        completion_tokens=_as_int(raw_usage.get("completion_tokens"), 0),
    )


class OpenAIChatEncoder:
    """Encoder for OpenAI-compatible ``/chat/completions`` endpoints."""

    def encode(self, request: RequestSpec) -> dict[str, object]:
        """Render *request* as a chat-completions request body."""
        messages: list[dict[str, object]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for message in request.messages:
            entry: dict[str, object] = {"role": message.role, "content": message.content}
            if message.tool_call_id is not None:
                entry["tool_call_id"] = message.tool_call_id
            if message.name is not None:
                entry["name"] = message.name
            messages.append(entry)

        body: dict[str, object] = {"messages": messages}
        if request.tools:
            body["tools"] = [schema.to_openai() for schema in request.tools]
        if request.model is not None:
            body["model"] = request.model
        return body

    def decode(self, payload: object) -> AgentResponse:
        """Parse a chat-completions response JSON into an :class:`AgentResponse`."""
        if not isinstance(payload, dict):
            msg = "OpenAIChatEncoder: response payload is not a JSON object"
            raise RuntimeError(msg)

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            msg = "OpenAIChatEncoder: response has no 'choices' array"
            raise RuntimeError(msg)

        first = choices[0]
        if not isinstance(first, dict):
            msg = "OpenAIChatEncoder: first choice is not an object"
            raise RuntimeError(msg)

        message = first.get("message")
        if not isinstance(message, dict):
            msg = "OpenAIChatEncoder: first choice has no 'message' object"
            raise RuntimeError(msg)

        text = message.get("content")
        text_str = text if isinstance(text, str) else ""

        raw_tool_calls = message.get("tool_calls")
        tool_calls = _parse_tool_calls(raw_tool_calls) if isinstance(raw_tool_calls, list) else []

        return AgentResponse(
            text=text_str,
            tool_calls=tool_calls,
            usage=_parse_usage(payload.get("usage")),
            raw=payload,
        )
