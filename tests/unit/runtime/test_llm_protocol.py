"""W1 protocol tests: assistant tool_calls, tier resolution, scripted mock.

Covers audit findings F-3 (assistant messages must carry tool_calls so
tool messages have a valid predecessor), F-7 (agent model tiers resolve
to real model names), and F-6 (the mock runner walks a full round).
"""

from __future__ import annotations

import pytest

from app.runtime.prompt_builder import Message, RequestSpec
from app.runtime.providers.openai_chat import OpenAIChatEncoder
from app.runtime.runners.base import ToolCall
from app.runtime.runners.direct_runner import DirectRunner
from app.runtime.runners.mock_runner import MockRunner
from app.runtime.tool_catalog import build_default_catalog


class _StubAgent:
    id = "agent-stub"
    name = "stub"
    model = None


_CATALOG = build_default_catalog()

_DIRECTOR_SYSTEM = (
    "## 你的任务\n调度\n\n"
    "## 权限限制\n你只能读取以下资源: state\n你只能写入以下资源: \n\n"
    "## 工作流执行顺序\n"
    "1. [depth=1] writer: 写正文\n"
    "2. [depth=1] maintainer: 维护状态\n"
)

_WRITER_SYSTEM = (
    "## 你的任务\n写作\n\n"
    "## 权限限制\n你只能读取以下资源: state, short_goal\n你只能写入以下资源: notes, state\n"
)


def _director_spec(history: list[Message]) -> RequestSpec:
    return RequestSpec(
        system=_DIRECTOR_SYSTEM,
        messages=history,
        tools=_CATALOG.schemas_for(["call_agent", "await", "finalize"]),
    )


# -- F-3: encoder emits assistant tool_calls ---------------------------------


class TestAssistantToolCalls:
    def test_assistant_message_carries_tool_calls(self) -> None:
        spec = RequestSpec(
            system="s",
            messages=[
                Message(
                    role="assistant",
                    content="calling",
                    tool_calls=(ToolCall(name="read", args={"resource_type": "state"}, id="call_7"),),
                ),
                Message(role="tool", content="ok", tool_call_id="call_7", name="read"),
            ],
        )
        body = OpenAIChatEncoder().encode(spec)
        messages = body["messages"]
        assert isinstance(messages, list)
        assistant = messages[1]
        assert assistant["tool_calls"] == [
            {
                "id": "call_7",
                "type": "function",
                "function": {"name": "read", "arguments": '{"resource_type": "state"}'},
            }
        ]
        tool_msg = messages[2]
        assert tool_msg["tool_call_id"] == "call_7"

    def test_plain_assistant_message_has_no_tool_calls_key(self) -> None:
        spec = RequestSpec(system="", messages=[Message(role="assistant", content="hi")])
        body = OpenAIChatEncoder().encode(spec)
        messages = body["messages"]
        assert isinstance(messages, list)
        assert "tool_calls" not in messages[0]

    def test_fingerprint_distinguishes_tool_calls(self) -> None:
        plain = RequestSpec(system="", messages=[Message(role="assistant", content="x")])
        with_calls = RequestSpec(
            system="",
            messages=[
                Message(
                    role="assistant",
                    content="x",
                    tool_calls=(ToolCall(name="read", args={}, id="c1"),),
                )
            ],
        )
        assert plain.fingerprint() != with_calls.fingerprint()


# -- F-7: model tier resolution ----------------------------------------------


class TestTierResolution:
    def _runner(self) -> DirectRunner:
        return DirectRunner(
            model_config={
                "provider": "openai_compatible",
                "model": "default-model",
                "api_key_env": "X_API_KEY",
                "base_url_env": "X_BASE_URL",
            },
            runtime_policy={},
            tier_models={"premium": "real-premium-model", "cheap": None},
        )

    def test_known_tier_resolves(self) -> None:
        assert self._runner()._resolve_model("premium") == "real-premium-model"

    def test_none_falls_back_to_default(self) -> None:
        assert self._runner()._resolve_model(None) == "default-model"

    def test_unknown_value_passes_through_as_literal(self) -> None:
        assert self._runner()._resolve_model("gpt-4o-mini") == "gpt-4o-mini"

    def test_known_tier_without_env_raises(self) -> None:
        with pytest.raises(RuntimeError, match="cheap"):
            self._runner()._resolve_model("cheap")


# -- F-6: scripted mock walks a full round -----------------------------------


class TestScriptedMock:
    @pytest.mark.asyncio
    async def test_director_calls_flow_agents_in_order(self) -> None:
        runner = MockRunner()
        first = await runner.run(_StubAgent(), _director_spec([]))
        assert len(first.tool_calls) == 1
        assert first.tool_calls[0].name == "call_agent"
        assert first.tool_calls[0].args["agent_name"] == "writer"
        assert first.tool_calls[0].id  # deterministic id present

        history = [
            Message(role="assistant", content="", tool_calls=tuple(first.tool_calls)),
            Message(role="tool", content="done", tool_call_id="mock_call_1", name="call_agent"),
        ]
        second = await runner.run(_StubAgent(), _director_spec(history))
        assert second.tool_calls[0].args["agent_name"] == "maintainer"

    @pytest.mark.asyncio
    async def test_director_finalizes_with_final_text_after_all_agents(self) -> None:
        runner = MockRunner()
        history = [
            Message(role="tool", content="a", tool_call_id="mock_call_1", name="call_agent"),
            Message(role="tool", content="b", tool_call_id="mock_call_2", name="call_agent"),
        ]
        resp = await runner.run(_StubAgent(), _director_spec(history))
        assert resp.tool_calls[0].name == "finalize"
        assert resp.tool_calls[0].args["final_text"]
        assert resp.tool_calls[0].args["summary"]

    @pytest.mark.asyncio
    async def test_chat_director_stays_plain_text(self) -> None:
        spec = RequestSpec(
            system="## 你的任务\n对话",  # no flow section
            messages=[Message(role="user", content="你好")],
            tools=_CATALOG.schemas_for(["call_agent", "finalize"]),
        )
        resp = await MockRunner().run(_StubAgent(), spec)
        assert resp.tool_calls == []

    @pytest.mark.asyncio
    async def test_writable_sub_agent_emits_write(self) -> None:
        spec = RequestSpec(
            system=_WRITER_SYSTEM,
            messages=[Message(role="user", content="写")],
            tools=_CATALOG.schemas_for(["read", "write"]),
        )
        resp = await MockRunner().run(_StubAgent(), spec)
        assert resp.tool_calls[0].name == "write"
        assert resp.tool_calls[0].args["resource_type"] == "notes"

    @pytest.mark.asyncio
    async def test_read_only_sub_agent_stays_plain_text(self) -> None:
        spec = RequestSpec(
            system="## 权限限制\n你只能读取以下资源: worldbook\n你只能写入以下资源: ",
            messages=[Message(role="user", content="召回")],
            tools=_CATALOG.schemas_for(["read", "grep_lines"]),
        )
        resp = await MockRunner().run(_StubAgent(), spec)
        assert resp.tool_calls == []

    @pytest.mark.asyncio
    async def test_unscripted_mode_is_inert(self) -> None:
        resp = await MockRunner(scripted=False).run(_StubAgent(), _director_spec([]))
        assert resp.tool_calls == []

    @pytest.mark.asyncio
    async def test_determinism(self) -> None:
        r1 = await MockRunner().run(_StubAgent(), _director_spec([]))
        r2 = await MockRunner().run(_StubAgent(), _director_spec([]))
        assert r1.text == r2.text
        assert r1.tool_calls == r2.tool_calls
