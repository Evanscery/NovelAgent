"""Tests for app.agents.parser — parse_agent_to_prompt(agent, context) -> str."""

from __future__ import annotations

from app.agents.agent import Agent
from app.agents.parser import parse_agent_to_prompt
from app.runtime.permission import Permission, parse_permission


def _make_permission(
    raw: dict[str, list[str]] | None = None,
) -> Permission:
    if raw is None:
        raw = {"read": ["state"], "write": ["short_goal"]}
    return parse_permission({k: v for k, v in raw.items()})


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "id": "director-001",
        "name": "director",
        "task": "决策与任务分配",
        "input": "当前状态、短期目标、世界书摘要",
        "output": "JSON 格式的下一步行动指令",
        "permission": _make_permission(),
        "model": "premium",
        "skills": ["scheduling"],
        "tools": ["read", "search", "write"],
        "head": None,
        "tail": None,
        "allow_recursive": True,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


# ── Prompt contains all required sections ──────────────────────────────


class TestPromptContainsAttributes:
    """parse_agent_to_prompt produces a prompt containing task, input, output,
    permission statement, skills, tools."""

    def test_prompt_contains_task(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert "## 你的任务" in prompt
        assert "决策与任务分配" in prompt

    def test_prompt_contains_input(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert "## 你将收到的输入" in prompt
        assert "当前状态、短期目标、世界书摘要" in prompt

    def test_prompt_contains_output(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert "## 你的输出格式" in prompt
        assert "JSON 格式的下一步行动指令" in prompt

    def test_prompt_contains_permission_section(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert "## 权限限制" in prompt

    def test_prompt_contains_skills(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent(skills=["scheduling", "dice_roll"]))
        assert "## 可用技能" in prompt
        assert "scheduling" in prompt
        assert "dice_roll" in prompt

    def test_prompt_contains_tools(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert "## 可用工具" in prompt
        assert "read" in prompt
        assert "search" in prompt
        assert "write" in prompt

    def test_prompt_is_markdown_with_double_hash_sections(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        # Each section starts with "## " (markdown H2)
        assert "## 你的任务" in prompt
        assert "## 你将收到的输入" in prompt
        assert "## 你的输出格式" in prompt
        assert "## 权限限制" in prompt
        assert "## 可用工具" in prompt


# ── Permission section correctness ─────────────────────────────────────


class TestPermissionSection:
    """Permission section correctly lists allowed read/write resources."""

    def test_lists_read_resources(self) -> None:
        agent = _make_agent(
            permission=_make_permission(
                {"read": ["state", "character_memory"], "write": ["short_goal"]}
            )
        )
        prompt = parse_agent_to_prompt(agent)
        assert "读取" in prompt
        assert "state" in prompt
        assert "character_memory" in prompt

    def test_lists_write_resources(self) -> None:
        agent = _make_agent(
            permission=_make_permission(
                {"read": ["state"], "write": ["short_goal", "notes"]}
            )
        )
        prompt = parse_agent_to_prompt(agent)
        assert "写入" in prompt
        assert "short_goal" in prompt
        assert "notes" in prompt

    def test_read_only_permission(self) -> None:
        agent = _make_agent(
            permission=_make_permission({"read": ["state", "worldbook"]})
        )
        prompt = parse_agent_to_prompt(agent)
        assert "读取" in prompt
        assert "state" in prompt
        assert "worldbook" in prompt
        # No write verb emitted because "write" key is absent — the line
        # becomes "你只能以下资源: " (no 写入 inserted).
        assert "你只能以下资源: " in prompt

    def test_write_only_permission(self) -> None:
        agent = _make_agent(
            permission=_make_permission({"write": ["short_goal"]})
        )
        prompt = parse_agent_to_prompt(agent)
        assert "写入" in prompt
        assert "short_goal" in prompt
        # No read verb emitted because "read" key is absent.
        assert "你只能以下资源: " in prompt

    def test_empty_permission_lists_no_resources(self) -> None:
        agent = _make_agent(permission=_make_permission({}))
        prompt = parse_agent_to_prompt(agent)
        assert "## 权限限制" in prompt
        # Both verbs absent, both lists empty.
        assert "你只能以下资源: " in prompt


# ── Determinism ────────────────────────────────────────────────────────


class TestPromptDeterministic:
    """Same agent + same context -> same prompt (byte-identical)."""

    def test_same_agent_same_context_same_prompt(self) -> None:
        agent = _make_agent()
        p1 = parse_agent_to_prompt(agent, "some context")
        p2 = parse_agent_to_prompt(agent, "some context")
        assert p1 == p2

    def test_same_agent_no_context_same_prompt(self) -> None:
        agent = _make_agent()
        p1 = parse_agent_to_prompt(agent)
        p2 = parse_agent_to_prompt(agent)
        assert p1 == p2

    def test_different_context_different_prompt(self) -> None:
        agent = _make_agent()
        p1 = parse_agent_to_prompt(agent, "context A")
        p2 = parse_agent_to_prompt(agent, "context B")
        assert p1 != p2

    def test_different_agent_different_prompt(self) -> None:
        a1 = _make_agent(id="agent-1", task="任务一")
        a2 = _make_agent(id="agent-2", task="任务二")
        assert parse_agent_to_prompt(a1) != parse_agent_to_prompt(a2)


# ── head / tail ────────────────────────────────────────────────────────


class TestHeadTail:
    """head is prepended when present, omitted when None; tail is appended when
    present, omitted when None."""

    def test_head_prepended_when_present(self) -> None:
        agent = _make_agent(head="你是一个资深小说编辑。")
        prompt = parse_agent_to_prompt(agent)
        assert prompt.startswith("你是一个资深小说编辑。")

    def test_head_omitted_when_none(self) -> None:
        agent = _make_agent(head=None)
        prompt = parse_agent_to_prompt(agent)
        assert not prompt.startswith("你是一个资深小说编辑。")
        # The first section is the task section.
        assert prompt.startswith("## 你的任务")

    def test_tail_appended_when_present(self) -> None:
        agent = _make_agent(tail="请严格遵守以上规则。")
        prompt = parse_agent_to_prompt(agent)
        assert prompt.endswith("请严格遵守以上规则。")

    def test_tail_omitted_when_none(self) -> None:
        agent = _make_agent(tail=None)
        prompt = parse_agent_to_prompt(agent)
        assert not prompt.endswith("请严格遵守以上规则。")
        # Without context and without tail, the last section is the tools section.
        assert prompt.rstrip().endswith("read, search, write")

    def test_head_and_tail_both_present(self) -> None:
        agent = _make_agent(head="HEAD", tail="TAIL")
        prompt = parse_agent_to_prompt(agent)
        assert prompt.startswith("HEAD")
        assert prompt.endswith("TAIL")


# ── Context section ────────────────────────────────────────────────────


class TestContextSection:
    """Context section included when non-empty, omitted when empty."""

    def test_context_included_when_non_empty(self) -> None:
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent, "这是运行时上下文。")
        assert "## 上下文" in prompt
        assert "这是运行时上下文。" in prompt

    def test_context_omitted_when_empty(self) -> None:
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent, "")
        assert "## 上下文" not in prompt

    def test_context_omitted_when_not_provided(self) -> None:
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent)
        assert "## 上下文" not in prompt

    def test_context_appears_after_tools(self) -> None:
        """Section order: tools comes before context."""
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent, "ctx")
        tools_idx = prompt.index("## 可用工具")
        ctx_idx = prompt.index("## 上下文")
        assert tools_idx < ctx_idx


# ── Skills section conditional ─────────────────────────────────────────


class TestSkillsSection:
    """Skills section only appears when agent.skills is non-empty."""

    def test_skills_section_present_when_non_empty(self) -> None:
        agent = _make_agent(skills=["scheduling", "dice_roll"])
        prompt = parse_agent_to_prompt(agent)
        assert "## 可用技能" in prompt
        assert "scheduling, dice_roll" in prompt

    def test_skills_section_absent_when_empty(self) -> None:
        agent = _make_agent(skills=[])
        prompt = parse_agent_to_prompt(agent)
        assert "## 可用技能" not in prompt


# ── Pure function: no side effects ─────────────────────────────────────


class TestParserIsPure:
    """parse_agent_to_prompt is a pure function — no side effects on the agent."""

    def test_does_not_mutate_agent(self) -> None:
        agent = _make_agent()
        before_task = agent.task
        before_skills = list(agent.skills)
        before_tools = list(agent.tools)
        _ = parse_agent_to_prompt(agent, "ctx")
        assert agent.task == before_task
        assert agent.skills == before_skills
        assert agent.tools == before_tools

    def test_returns_str(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert isinstance(prompt, str)

    def test_returns_non_empty_str(self) -> None:
        prompt = parse_agent_to_prompt(_make_agent())
        assert len(prompt) > 0


# ── Full prompt integration snapshot ───────────────────────────────────


class TestPromptIntegration:
    """End-to-end: a fully-populated agent produces a well-structured prompt."""

    def test_full_agent_prompt_has_all_sections_in_order(self) -> None:
        agent = _make_agent(
            head="你是一个资深小说编辑。",
            skills=["scheduling", "dice_roll"],
            tail="请严格遵守以上规则。",
        )
        prompt = parse_agent_to_prompt(agent, "运行时上下文")

        # Verify section ordering.
        sections = [
            "你是一个资深小说编辑。",
            "## 你的任务",
            "## 你将收到的输入",
            "## 你的输出格式",
            "## 权限限制",
            "## 可用技能",
            "## 可用工具",
            "## 上下文",
            "请严格遵守以上规则。",
        ]
        last_idx = -1
        for section in sections:
            idx = prompt.index(section)
            assert idx > last_idx, f"section {section!r} out of order"
            last_idx = idx

    def test_minimal_agent_prompt_has_core_sections(self) -> None:
        """An agent with no head/tail/skills still produces a valid prompt."""
        agent = _make_agent(head=None, tail=None, skills=[])
        prompt = parse_agent_to_prompt(agent)
        assert "## 你的任务" in prompt
        assert "## 你将收到的输入" in prompt
        assert "## 你的输出格式" in prompt
        assert "## 权限限制" in prompt
        assert "## 可用工具" in prompt
        assert "## 可用技能" not in prompt
        assert "## 上下文" not in prompt


# ── Flow sequence injection (todo 18) ──────────────────────────────────


class TestFlowSequenceSection:
    """parse_agent_to_prompt injects the 工作流执行顺序 section when flow_sequence is non-empty."""

    def test_flow_sequence_included_when_non_empty(self) -> None:
        agent = _make_agent()
        flow = "1. recaller — 召回数据 (depth=1)\n2. writer — 文本生成 (depth=2)"
        prompt = parse_agent_to_prompt(agent, flow_sequence=flow)
        assert "## 工作流执行顺序" in prompt
        assert "recaller" in prompt
        assert "writer" in prompt

    def test_flow_sequence_omitted_when_empty(self) -> None:
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent, flow_sequence="")
        assert "## 工作流执行顺序" not in prompt

    def test_flow_sequence_omitted_when_not_provided(self) -> None:
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent)
        assert "## 工作流执行顺序" not in prompt

    def test_flow_sequence_appears_after_tools_before_context(self) -> None:
        """Section order: tools < 工作流执行顺序 < 上下文."""
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent, context="ctx", flow_sequence="flow text")
        tools_idx = prompt.index("## 可用工具")
        flow_idx = prompt.index("## 工作流执行顺序")
        ctx_idx = prompt.index("## 上下文")
        assert tools_idx < flow_idx < ctx_idx

    def test_flow_sequence_with_context_both_present(self) -> None:
        agent = _make_agent()
        prompt = parse_agent_to_prompt(agent, context="运行时上下文", flow_sequence="flow")
        assert "## 工作流执行顺序" in prompt
        assert "## 上下文" in prompt
        assert "运行时上下文" in prompt

    def test_allow_recursive_never_in_prompt(self) -> None:
        """allow_recursive is runtime-only — must NEVER appear in the prompt."""
        agent = _make_agent(allow_recursive=False)
        prompt = parse_agent_to_prompt(agent, flow_sequence="flow")
        assert "allow_recursive" not in prompt
        assert "递归" not in prompt or "可递归召回" not in prompt  # task text may contain 递归; flag itself absent
