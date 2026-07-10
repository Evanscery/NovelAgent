"""Tests for ToolDispatcher — parse agent tool calls, dispatch to read/search/write.

Covers both supported parse formats (JSON code block + simple ``TOOL: name(...)``
line), the three allowed tools, ``UnknownToolError`` for anything else, and
propagation of ``PermissionDenied`` from the scoped tools (permission
enforcement lives inside ``ScopedTools``, not the dispatcher).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.runtime.tool_dispatcher import (
    ScopedTools,
    ToolDispatcher,
    ToolResult,
    UnknownToolError,
)

# ── test doubles ────────────────────────────────────────────────────────────


class PermissionDenied(Exception):
    """Raised by the mock scoped tool when an agent lacks permission.

    Mirrors the exception todo 11 (``app/runtime/permission.py``) will
    define. Kept local to avoid importing an unfinished module.
    """


@dataclass
class MockScopedTools:
    """Minimal scoped-tools double satisfying the :class:`ScopedTools` Protocol.

    Records every call and returns canned outputs. ``denied`` is a set of
    tool names that should raise :class:`PermissionDenied` to exercise
    propagation.
    """

    read_return: Any = "STATE-CONTENT"
    search_return: list[Any] = field(default_factory=lambda: [{"filename": "state.md"}])
    write_return: Any = None
    denied: set[str] = field(default_factory=set)
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def read(self, **kwargs: Any) -> Any:
        self.calls.append(("read", dict[str, object](kwargs)))
        if "read" in self.denied:
            raise PermissionDenied("read denied for this resource")
        return self.read_return

    def search(self, **kwargs: Any) -> Any:
        self.calls.append(("search", dict[str, object](kwargs)))
        if "search" in self.denied:
            raise PermissionDenied("search denied for this resource")
        return self.search_return

    def write(self, **kwargs: Any) -> Any:
        self.calls.append(("write", dict[str, object](kwargs)))
        if "write" in self.denied:
            raise PermissionDenied("write denied for this resource")
        return self.write_return


# ── parse: JSON code block ──────────────────────────────────────────────────


def test_parse_json_code_block_extracts_name_and_args() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = 'Some prose first.\n```tool\n{"name": "read", "args": {"resource_type": "state"}}\n```\nMore prose.'
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    assert call.args == {"resource_type": "state"}


def test_parse_json_block_with_extra_whitespace() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = '```tool\n\n  {"name": "search", "args": {"query": "tavern", "resource_type": "worldbook"}}  \n\n```'
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "search"
    assert call.args == {"query": "tavern", "resource_type": "worldbook"}


def test_parse_json_block_with_empty_args() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = '```tool\n{"name": "read", "args": {}}\n```'
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    assert call.args == {}


def test_parse_json_block_missing_args_key_defaults_to_empty() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = '```tool\n{"name": "read"}\n```'
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    assert call.args == {}


# ── parse: simple TOOL: name(...) line ──────────────────────────────────────


def test_parse_simple_parenthetical_single_positional() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "TOOL: read(state)"
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    # Bare word → positional arg keyed by 1-based index.
    assert call.args == {"1": "state"}


def test_parse_simple_parenthetical_multiple_positionals() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "TOOL: write(short_goal, chapter_01.md, Once upon a time...)"
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "write"
    assert call.args == {
        "1": "short_goal",
        "2": "chapter_01.md",
        "3": "Once upon a time...",
    }


def test_parse_simple_parenthetical_key_value_pairs() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "TOOL: search(resource_type=worldbook, query=tavern)"
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "search"
    assert call.args == {"resource_type": "worldbook", "query": "tavern"}


def test_parse_simple_parenthetical_empty_args() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "TOOL: read()"
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    assert call.args == {}


def test_parse_simple_parenthetical_indented_line() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "  leading prose\n    TOOL: read(state)\n  trailing"
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    assert call.args == {"1": "state"}


# ── parse: no tool call → None ──────────────────────────────────────────────


def test_parse_returns_none_when_no_tool_call_in_text() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    assert dispatcher.parse_tool_call("just a normal agent response, no tool") is None


def test_parse_returns_none_for_empty_text() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    assert dispatcher.parse_tool_call("") is None


def test_parse_ignores_unrelated_code_block() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "```python\nprint('not a tool')\n```"
    assert dispatcher.parse_tool_call(text) is None


def test_parse_json_block_preferred_over_tool_line_when_both_present() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = (
        "TOOL: read(state)\n"
        '```tool\n{"name": "write", "args": {"resource_type": "short_goal", "filename": "ch1.md"}}\n```'
    )
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "write"
    assert call.args == {"resource_type": "short_goal", "filename": "ch1.md"}


def test_parse_falls_back_to_tool_line_when_json_block_malformed() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = "```tool\n{not valid json}\n```\nTOOL: read(state)"
    call = dispatcher.parse_tool_call(text)
    assert call is not None
    assert call.name == "read"
    assert call.args == {"1": "state"}


# ── dispatch: read ──────────────────────────────────────────────────────────


def test_dispatch_read_returns_content() -> None:
    tools = MockScopedTools(read_return="THE-STATE-TEXT")
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    result = dispatcher.dispatch(ToolCall(name="read", args={"resource_type": "state"}))
    assert result.ok is True
    assert result.output == "THE-STATE-TEXT"
    assert result.error == ""
    assert tools.calls == [("read", {"resource_type": "state"})]


def test_dispatch_write_returns_success() -> None:
    tools = MockScopedTools()
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    result = dispatcher.dispatch(
        ToolCall(
            name="write",
            args={
                "resource_type": "short_goal",
                "filename": "chapter_01.md",
                "content": "Once upon a time...",
            },
        )
    )
    assert result.ok is True
    assert result.output is None
    assert tools.calls == [
        (
            "write",
            {
                "resource_type": "short_goal",
                "filename": "chapter_01.md",
                "content": "Once upon a time...",
            },
        )
    ]


def test_dispatch_search_returns_hits() -> None:
    hits = [{"filename": "worldbook.md", "line": 42}]
    tools = MockScopedTools(search_return=hits)
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    result = dispatcher.dispatch(
        ToolCall(name="search", args={"resource_type": "worldbook", "query": "tavern"})
    )
    assert result.ok is True
    assert result.output == hits


# ── dispatch: unknown tool → UnknownToolError ──────────────────────────────


def test_dispatch_readfile_raises_unknown_tool_error() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    from app.runtime.runners.base import ToolCall

    with pytest.raises(UnknownToolError, match="Unknown tool: readFile"):
        dispatcher.dispatch(ToolCall(name="readFile", args={"resource": "memory"}))


def test_dispatch_readmemory_raises_unknown_tool_error() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    from app.runtime.runners.base import ToolCall

    with pytest.raises(UnknownToolError, match="Unknown tool: readMemory"):
        dispatcher.dispatch(ToolCall(name="readMemory", args={"resource": "memory"}))


def test_dispatch_readlore_raises_unknown_tool_error() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    from app.runtime.runners.base import ToolCall

    with pytest.raises(UnknownToolError, match="Unknown tool: readLore"):
        dispatcher.dispatch(ToolCall(name="readLore", args={"resource": "lore"}))


def test_dispatch_unknown_tool_error_message_lists_allowed_tools() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    from app.runtime.runners.base import ToolCall

    with pytest.raises(UnknownToolError) as exc_info:
        dispatcher.dispatch(ToolCall(name="delete", args={}))
    assert "read/search/write" in str(exc_info.value)


# ── dispatch: permission propagation ────────────────────────────────────────


def test_dispatch_propagates_permission_denied_from_scoped_read() -> None:
    tools = MockScopedTools(denied={"read"})
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    with pytest.raises(PermissionDenied, match="read denied"):
        dispatcher.dispatch(ToolCall(name="read", args={"resource_type": "worldbook"}))
    # The scoped tool was actually called (permission is enforced inside it).
    assert tools.calls == [("read", {"resource_type": "worldbook"})]


def test_dispatch_propagates_permission_denied_from_scoped_write() -> None:
    tools = MockScopedTools(denied={"write"})
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    with pytest.raises(PermissionDenied, match="write denied"):
        dispatcher.dispatch(
            ToolCall(name="write", args={"resource_type": "outline", "filename": "x.md", "content": "y"})
        )


def test_dispatch_does_not_swallow_permission_denied_as_tool_result() -> None:
    """PermissionDenied must propagate, not become ToolResult(ok=False)."""
    tools = MockScopedTools(denied={"read"})
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    # If it were swallowed, dispatch would return a ToolResult instead of raising.
    result_or_exc: ToolResult | BaseException
    try:
        result_or_exc = dispatcher.dispatch(ToolCall(name="read", args={"resource_type": "state"}))
    except BaseException as exc:  # noqa: BLE001 — re-raised below for assertion
        result_or_exc = exc
    assert isinstance(result_or_exc, PermissionDenied)


# ── dispatch_from_text: end-to-end convenience ──────────────────────────────


def test_dispatch_from_text_json_block_end_to_end() -> None:
    tools = MockScopedTools(read_return="E2E-STATE")
    dispatcher = ToolDispatcher(tools)
    text = 'I will now read the state.\n```tool\n{"name": "read", "args": {"resource_type": "state"}}\n```'
    result = dispatcher.dispatch_from_text(text)
    assert result is not None
    assert result.ok is True
    assert result.output == "E2E-STATE"
    assert tools.calls == [("read", {"resource_type": "state"})]


def test_dispatch_from_text_simple_line_end_to_end() -> None:
    tools = MockScopedTools()
    dispatcher = ToolDispatcher(tools)
    result = dispatcher.dispatch_from_text("TOOL: write(short_goal, ch1.md, hello)")
    assert result is not None
    assert result.ok is True
    assert tools.calls == [("write", {"1": "short_goal", "2": "ch1.md", "3": "hello"})]


def test_dispatch_from_text_returns_none_when_no_tool_call() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    assert dispatcher.dispatch_from_text("no tool here") is None


def test_dispatch_from_text_propagates_unknown_tool_error() -> None:
    dispatcher = ToolDispatcher(MockScopedTools())
    text = '```tool\n{"name": "readFile", "args": {"resource": "memory"}}\n```'
    with pytest.raises(UnknownToolError, match="readFile"):
        dispatcher.dispatch_from_text(text)


def test_dispatch_from_text_propagates_permission_denied() -> None:
    tools = MockScopedTools(denied={"read"})
    dispatcher = ToolDispatcher(tools)
    text = '```tool\n{"name": "read", "args": {"resource_type": "worldbook"}}\n```'
    with pytest.raises(PermissionDenied):
        dispatcher.dispatch_from_text(text)


# ── Protocol satisfaction ───────────────────────────────────────────────────


def test_mock_scoped_tools_satisfies_protocol() -> None:
    """The mock double must satisfy the ScopedTools Protocol (static + runtime)."""
    tools: ScopedTools = MockScopedTools()
    assert isinstance(tools, ScopedTools)
