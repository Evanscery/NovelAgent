"""Unit tests for the runtime prompt builder (:mod:`app.runtime.prompt_builder`).

Covers RequestSpec.fingerprint (stability + sensitivity) and
PromptBuilder.build (system prompt, history, user message, reminder
injection, tool resolution via the schema source).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.agent import Agent
from app.agents.tools import BUILTIN_TOOL_SCHEMAS, ToolSchema
from app.runtime.permission import parse_permission
from app.runtime.prompt_builder import Message, PromptBuilder, RequestSpec


class _StubSchemaSource:
    """Minimal ToolSchemaSource: resolves against BUILTIN_TOOL_SCHEMAS,
    silently skipping unknown names (the ToolCatalog contract)."""

    def schemas_for(self, names: Sequence[str]) -> list[ToolSchema]:
        return [BUILTIN_TOOL_SCHEMAS[n] for n in names if n in BUILTIN_TOOL_SCHEMAS]


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "id": "writer",
        "name": "writer",
        "task": "写作",
        "input": "细纲",
        "output": "正文",
        "permission": parse_permission({"read": ["state"], "write": ["notes"]}),
        "model": None,
        "skills": [],
        "tools": ["read", "write"],
        "head": None,
        "tail": None,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _build(agent: Agent, **kwargs: object) -> RequestSpec:
    return PromptBuilder(_StubSchemaSource()).build(agent, **kwargs)  # type: ignore[arg-type]


# ── fingerprint ─────────────────────────────────────────────────────────


class TestFingerprint:
    def test_stable_across_calls(self) -> None:
        spec = _build(_make_agent(), user_text="hello")
        assert spec.fingerprint() == spec.fingerprint()

    def test_stable_across_equal_specs(self) -> None:
        a = _build(_make_agent(), user_text="hello")
        b = _build(_make_agent(), user_text="hello")
        assert a.fingerprint() == b.fingerprint()

    def test_sensitive_to_system(self) -> None:
        a = _build(_make_agent(task="任务一"), user_text="hello")
        b = _build(_make_agent(task="任务二"), user_text="hello")
        assert a.fingerprint() != b.fingerprint()

    def test_sensitive_to_messages(self) -> None:
        a = _build(_make_agent(), user_text="hello")
        b = _build(_make_agent(), user_text="world")
        assert a.fingerprint() != b.fingerprint()

    def test_sensitive_to_tools(self) -> None:
        a = _build(_make_agent(tools=["read"]))
        b = _build(_make_agent(tools=["read", "write"]))
        assert a.fingerprint() != b.fingerprint()

    def test_sensitive_to_model(self) -> None:
        a = _build(_make_agent(model=None))
        b = _build(_make_agent(model="premium"))
        assert a.fingerprint() != b.fingerprint()

    def test_sensitive_to_message_role(self) -> None:
        spec_user = RequestSpec(system="s", messages=[Message(role="user", content="x")])
        spec_asst = RequestSpec(system="s", messages=[Message(role="assistant", content="x")])
        assert spec_user.fingerprint() != spec_asst.fingerprint()

    def test_is_sha256_hex(self) -> None:
        fp = _build(_make_agent()).fingerprint()
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


# ── build ───────────────────────────────────────────────────────────────


class TestBuild:
    def test_system_prompt_from_parser(self) -> None:
        spec = _build(_make_agent())
        assert "## 你的任务" in spec.system
        assert "写作" in spec.system

    def test_flow_sequence_rendered_into_system(self) -> None:
        spec = _build(_make_agent(), flow_sequence="1. writer")
        assert "## 工作流执行顺序" in spec.system
        assert "1. writer" in spec.system

    def test_history_preserved_in_order(self) -> None:
        history = [
            Message(role="user", content="第一"),
            Message(role="assistant", content="第二"),
        ]
        spec = _build(_make_agent(), history=history)
        assert spec.messages == history

    def test_user_text_appended_after_history(self) -> None:
        history = [Message(role="assistant", content="prior")]
        spec = _build(_make_agent(), history=history, user_text="新消息")
        assert spec.messages[-1] == Message(role="user", content="新消息")

    def test_no_user_message_when_user_text_none(self) -> None:
        spec = _build(_make_agent())
        assert spec.messages == []

    def test_reminders_appended_to_trailing_user_message(self) -> None:
        spec = _build(_make_agent(), user_text="正文", reminders=["注意格式"])
        assert len(spec.messages) == 1
        content = spec.messages[0].content
        assert content.startswith("正文")
        assert "<system-reminder>\n注意格式\n</system-reminder>" in content

    def test_multiple_reminders_each_get_a_block(self) -> None:
        spec = _build(_make_agent(), user_text="正文", reminders=["一", "二"])
        content = spec.messages[0].content
        assert content.count("<system-reminder>") == 2

    def test_reminders_without_user_message_create_one(self) -> None:
        history = [Message(role="assistant", content="prior")]
        spec = _build(_make_agent(), history=history, reminders=["提醒"])
        assert spec.messages[-1].role == "user"
        assert "<system-reminder>" in spec.messages[-1].content

    def test_tools_resolved_from_catalog(self) -> None:
        spec = _build(_make_agent(tools=["read", "write"]))
        assert [t.name for t in spec.tools] == ["read", "write"]

    def test_unknown_tool_names_skipped(self) -> None:
        spec = _build(_make_agent(tools=["read", "no_such_tool"]))
        assert [t.name for t in spec.tools] == ["read"]

    def test_model_carried_from_agent(self) -> None:
        assert _build(_make_agent(model="premium")).model == "premium"
        assert _build(_make_agent(model=None)).model is None

    def test_history_input_not_mutated(self) -> None:
        history = [Message(role="user", content="原始")]
        _build(_make_agent(), history=history, reminders=["提醒"])
        assert history == [Message(role="user", content="原始")]
