"""Parse agent attributes -> prompt at runtime (config static, prompt dynamic).

Per ``docs/refactor_guide.md:75``: "这些属性硬存储在数据结构中，发送agent请求时，
会调用parser将这些参数解析并组合成prompt". And per guide:378-384:
"配置是静态的，Prompt 是动态生成的".

This module is a **pure function** — no side effects, no I/O, deterministic.
The same ``(agent, context)`` pair always produces byte-identical output.
"""

from __future__ import annotations

from .agent import Agent

_SECTION_SEPARATOR = "\n\n"


def _format_permission_section(agent: Agent) -> str:
    """Format the 权限限制 section from the agent's ``Permission``.

    Lists the read-allowed and write-allowed resource types. The verb
    (读取 / 写入) is only emitted when the corresponding action key is
    present in the permission rules — an absent key yields an empty
    resource list with no verb, mirroring refactor_guide:77-78.
    """
    read_verb = "读取" if "read" in agent.permission.rules else ""
    write_verb = "写入" if "write" in agent.permission.rules else ""
    read_resources = ", ".join(agent.permission.rules.get("read", ()))
    write_resources = ", ".join(agent.permission.rules.get("write", ()))
    return (
        "## 权限限制\n"
        f"你只能{read_verb}以下资源: {read_resources}\n"
        f"你只能{write_verb}以下资源: {write_resources}"
    )


def parse_agent_to_prompt(agent: Agent, context: str = "", flow_sequence: str = "") -> str:
    """Assemble a prompt string from the agent's attributes at runtime.

    The prompt is built dynamically from the agent's attributes (NOT
    loaded from a static ``.md`` file). Section order:

    1. ``head``        (prepended if present)
    2. ``## 你的任务``    (always — task is the agent's core)
    3. ``## 你将收到的输入``  (always)
    4. ``## 你的输出格式``   (always)
    5. ``## 权限限制``    (always — context isolation is mandatory)
    6. ``## 可用技能``    (only if ``agent.skills`` is non-empty)
    7. ``## 可用工具``    (always — read/search/write)
    8. ``## 工作流执行顺序`` (only if *flow_sequence* is non-empty — director-only)
    9. ``## 上下文``     (only if *context* is non-empty)
    10. ``tail``        (appended if present)

    The ``flow_sequence`` parameter (todo 18) is the linear execution-order
    text generated from the workflow tree by
    :func:`app.agents.workflow.generate_flow_sequence`. It is injected here
    so the director — which defaults to full-recall of the workflow
    resource — knows the execution order. Per the todo 18 design,
    ``allow_recursive`` is a runtime-only attribute and is NEVER emitted
    into the prompt.

    The function is deterministic: the same ``agent`` + ``context`` +
    ``flow_sequence`` always produce byte-identical output.

    Args:
        agent:         The :class:`Agent` whose attributes drive the prompt.
        context:       Optional runtime context string (e.g. recalled memory,
            current state). Empty string means no context section.
        flow_sequence: Optional workflow execution-order text (director-only).
            Empty string means no 工作流执行顺序 section.

    Returns:
        The assembled prompt as a markdown string with ``##`` sections.
    """
    sections: list[str] = []

    if agent.head is not None:
        sections.append(agent.head)

    sections.append(f"## 你的任务\n{agent.task}")
    sections.append(f"## 你将收到的输入\n{agent.input}")
    sections.append(f"## 你的输出格式\n{agent.output}")
    sections.append(_format_permission_section(agent))

    if agent.skills:
        sections.append(f"## 可用技能\n{', '.join(agent.skills)}")

    sections.append(f"## 可用工具\n{', '.join(agent.tools)}")

    if flow_sequence:
        sections.append(f"## 工作流执行顺序\n{flow_sequence}")

    if context:
        sections.append(f"## 上下文\n{context}")

    if agent.tail is not None:
        sections.append(agent.tail)

    return _SECTION_SEPARATOR.join(sections)
