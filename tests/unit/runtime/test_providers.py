"""Unit tests for the provider encoder seam (:mod:`app.runtime.providers`).

Covers the OpenAIChatEncoder: request-body golden encoding and response
decoding (text, tool_calls with JSON-string arguments and call ids,
usage).
"""

from __future__ import annotations

from app.agents.tools import BUILTIN_TOOL_SCHEMAS
from app.runtime.prompt_builder import Message, RequestSpec
from app.runtime.providers import OpenAIChatEncoder, RequestEncoder


class TestEncoderProtocol:
    def test_openai_chat_encoder_satisfies_protocol(self) -> None:
        assert isinstance(OpenAIChatEncoder(), RequestEncoder)


class TestEncode:
    def test_golden_full_request(self) -> None:
        spec = RequestSpec(
            system="SYSTEM PROMPT",
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
                Message(role="tool", content="result", tool_call_id="call_1", name="read"),
            ],
            tools=[BUILTIN_TOOL_SCHEMAS["read"]],
            model="premium",
        )
        body = OpenAIChatEncoder().encode(spec)
        assert body == {
            "messages": [
                {"role": "system", "content": "SYSTEM PROMPT"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {
                    "role": "tool",
                    "content": "result",
                    "tool_call_id": "call_1",
                    "name": "read",
                },
            ],
            "tools": [BUILTIN_TOOL_SCHEMAS["read"].to_openai()],
            "model": "premium",
        }

    def test_empty_system_omitted(self) -> None:
        body = OpenAIChatEncoder().encode(
            RequestSpec(system="", messages=[Message(role="user", content="hi")])
        )
        messages = body["messages"]
        assert isinstance(messages, list)
        assert messages[0]["role"] == "user"

    def test_no_tools_key_when_empty(self) -> None:
        body = OpenAIChatEncoder().encode(RequestSpec(system="s"))
        assert "tools" not in body

    def test_no_model_key_when_none(self) -> None:
        body = OpenAIChatEncoder().encode(RequestSpec(system="s", model=None))
        assert "model" not in body


class TestDecode:
    def _payload(self, message: dict[str, object]) -> dict[str, object]:
        return {
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    def test_decodes_text_and_usage(self) -> None:
        response = OpenAIChatEncoder().decode(self._payload({"content": "你好"}))
        assert response.text == "你好"
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5

    def test_decodes_tool_calls_with_json_string_arguments(self) -> None:
        payload = self._payload(
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": '{"resource_type": "state"}',
                        },
                    }
                ],
            }
        )
        response = OpenAIChatEncoder().decode(payload)
        assert len(response.tool_calls) == 1
        call = response.tool_calls[0]
        assert call.name == "read"
        assert call.args == {"resource_type": "state"}
        assert call.id == "call_abc"

    def test_decodes_dict_arguments(self) -> None:
        payload = self._payload(
            {
                "tool_calls": [
                    {"id": "c1", "function": {"name": "write", "arguments": {"a": 1}}}
                ]
            }
        )
        call = OpenAIChatEncoder().decode(payload).tool_calls[0]
        assert call.args == {"a": 1}

    def test_unparseable_argument_string_preserved_as_raw(self) -> None:
        payload = self._payload(
            {
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read", "arguments": "{not json"}}
                ]
            }
        )
        call = OpenAIChatEncoder().decode(payload).tool_calls[0]
        assert call.args == {"_raw": "{not json"}

    def test_missing_id_yields_none(self) -> None:
        payload = self._payload(
            {"tool_calls": [{"function": {"name": "read", "arguments": "{}"}}]}
        )
        call = OpenAIChatEncoder().decode(payload).tool_calls[0]
        assert call.id is None

    def test_malformed_payload_raises(self) -> None:
        import pytest

        with pytest.raises(RuntimeError):
            OpenAIChatEncoder().decode({"no_choices": True})
        with pytest.raises(RuntimeError):
            OpenAIChatEncoder().decode("not a dict")

    def test_raw_payload_carried(self) -> None:
        payload = self._payload({"content": "x"})
        assert OpenAIChatEncoder().decode(payload).raw is payload
