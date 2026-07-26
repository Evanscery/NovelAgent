"""Tool schema metadata — the agent layer's declarative tool surface.

This module owns the **schemas** of every built-in tool: the six storage
tools (dispatched to the data layer via ``ScopedTools``), the three
director tools (``call_agent`` / ``await`` / ``finalize``, executed by
the runtime's round executor itself), and ``dice_roll`` (a pure runtime
tool). It contains no execution code — implementations live in the
Runtime layer (``app.runtime.runtime_tools`` and the round executor),
keyed by the same names. The agent layer must not import the runtime
layer.

The schemas are provider-neutral: :class:`ToolSchema.parameters` is a
JSON-Schema object, and :meth:`ToolSchema.to_openai` renders the
OpenAI-chat function-calling shape. Other encodings belong to the
runtime's provider encoders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "BUILTIN_TOOL_SCHEMAS",
    "ToolSchema",
]


@dataclass(frozen=True)
class ToolSchema:
    """Declarative schema of one tool.

    Attributes:
        name:        The unique tool name (what the LLM calls).
        description: Human/LLM-facing description of what the tool does.
        parameters:  JSON-Schema object describing the arguments.
        source:      Where the tool comes from — ``"builtin"`` today;
                     imported/MCP tools will carry their own source tag.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    source: str = "builtin"

    def to_openai(self) -> dict[str, Any]:
        """Render the OpenAI chat-completions function-calling shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> ToolSchema:
    """Build a builtin :class:`ToolSchema` with an object parameter block."""
    return ToolSchema(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


_RESOURCE_TYPE_PROP: dict[str, Any] = {
    "type": "string",
    "description": "资源类型（如 state / notes / outline / worldbook 等）",
}

#: Every built-in tool schema, keyed by tool name. This is the single
#: source of truth for "what tools exist": prompt assembly, the runtime
#: tool catalog, and config validation all consult it.
BUILTIN_TOOL_SCHEMAS: dict[str, ToolSchema] = {
    schema.name: schema
    for schema in (
        # -- storage tools (dispatched to ScopedTools) --------------------
        _schema(
            "read",
            "读取指定资源类型下的文件内容。",
            {
                "resource_type": _RESOURCE_TYPE_PROP,
                "filename": {
                    "type": ["string", "null"],
                    "description": "文件名；省略时读取该资源类型的默认文件",
                },
            },
            ["resource_type"],
        ),
        _schema(
            "write",
            "写入内容到指定资源类型下的文件。",
            {
                "resource_type": _RESOURCE_TYPE_PROP,
                "filename": {"type": "string", "description": "目标文件名"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            ["resource_type", "filename", "content"],
        ),
        _schema(
            "list_files",
            "列出指定资源类型下的所有文件名。",
            {"resource_type": _RESOURCE_TYPE_PROP},
            ["resource_type"],
        ),
        _schema(
            "glob_files",
            "按通配符模式匹配指定资源类型下的文件名。",
            {
                "resource_type": _RESOURCE_TYPE_PROP,
                "pattern": {"type": "string", "description": "通配符模式，如 '*.md'"},
            },
            ["resource_type", "pattern"],
        ),
        _schema(
            "grep_lines",
            "在指定资源类型的文件内容中按正则搜索行。",
            {
                "resource_type": _RESOURCE_TYPE_PROP,
                "pattern": {"type": "string", "description": "正则表达式"},
                "filename": {
                    "type": ["string", "null"],
                    "description": "限定搜索的文件名；省略时搜索全部文件",
                },
            },
            ["resource_type", "pattern"],
        ),
        _schema(
            "read_lines",
            "读取指定文件的行区间（1 起始，含端点）。",
            {
                "resource_type": _RESOURCE_TYPE_PROP,
                "filename": {"type": "string", "description": "目标文件名"},
                "start": {"type": "integer", "description": "起始行号（1 起始）"},
                "end": {"type": "integer", "description": "结束行号（含）"},
            },
            ["resource_type", "filename", "start", "end"],
        ),
        # -- director tools (executed by the round executor) --------------
        _schema(
            "call_agent",
            "调用一个子 agent 执行任务，返回结果 handle。",
            {
                "agent_name": {"type": "string", "description": "目标 agent 的显示名（流程序列所示）"},
                "prompt": {"type": "string", "description": "交给子 agent 的任务说明"},
            },
            ["agent_name", "prompt"],
        ),
        _schema(
            "await",
            "按 handle 取回先前 call_agent 的结果。",
            {"handle": {"type": "string", "description": "call_agent 返回的任务 handle"}},
            ["handle"],
        ),
        _schema(
            "finalize",
            "结束本轮执行。工作流轮应携带本轮正文与摘要：final_text 落盘为新章节，summary 归档为轮次摘要。",
            {
                "reason": {"type": ["string", "null"], "description": "结束原因（可选）"},
                "final_text": {
                    "type": ["string", "null"],
                    "description": "本轮产出的章节正文（工作流轮必填；落盘 novels/）",
                },
                "summary": {
                    "type": ["string", "null"],
                    "description": "本轮摘要（归档到 turn_summary 资源，供后续召回定位）",
                },
            },
            [],
        ),
        # -- runtime tools ------------------------------------------------
        _schema(
            "dice_roll",
            "掷骰：支持 NdM(+/-K) 表示法，如 1d10、1d100、3d6+2。提供 seed 可复现。",
            {
                "notation": {
                    "type": ["string", "null"],
                    "description": "骰子表达式，如 '1d100'（与 sides/count/modifier 二选一）",
                },
                "sides": {"type": ["integer", "null"], "description": "骰面数（可替代 notation）"},
                "count": {"type": "integer", "description": "骰子数量，默认 1"},
                "modifier": {"type": "integer", "description": "总值加减，默认 0"},
                "seed": {"type": ["integer", "null"], "description": "随机种子（提供则可复现）"},
            },
            [],
        ),
    )
}
