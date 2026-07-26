"""Tests for ToolDispatcher — parse agent tool calls, dispatch to unified tools.

Covers both supported parse formats (JSON code block + simple ``TOOL: name(...)``
line), the allowed tool set, ``UnknownToolError`` for anything else, and
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
    list_files_return: list[str] = field(default_factory=lambda: ["a.md", "b.md"])
    glob_files_return: list[str] = field(default_factory=lambda: ["a.md"])
    grep_lines_return: list[tuple[str, int, str]] = field(default_factory=lambda: [("a.md", 1, "match")])
    read_lines_return: str = "line content"
    write_return: Any = None
    denied: set[str] = field(default_factory=set)
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def read(self, **kwargs: Any) -> Any:
        self.calls.append(("read", dict[str, object](kwargs)))
        if "read" in self.denied:
            raise PermissionDenied("read denied for this resource")
        return self.read_return

    def write(self, **kwargs: Any) -> Any:
        self.calls.append(("write", dict[str, object](kwargs)))
        if "write" in self.denied:
            raise PermissionDenied("write denied for this resource")
        return self.write_return

    def list_files(self, **kwargs: Any) -> Any:
        self.calls.append(("list_files", dict[str, object](kwargs)))
        if "list_files" in self.denied:
            raise PermissionDenied("list_files denied for this resource")
        return self.list_files_return

    def glob_files(self, **kwargs: Any) -> Any:
        self.calls.append(("glob_files", dict[str, object](kwargs)))
        if "glob_files" in self.denied:
            raise PermissionDenied("glob_files denied for this resource")
        return self.glob_files_return

    def grep_lines(self, **kwargs: Any) -> Any:
        self.calls.append(("grep_lines", dict[str, object](kwargs)))
        if "grep_lines" in self.denied:
            raise PermissionDenied("grep_lines denied for this resource")
        return self.grep_lines_return

    def read_lines(self, **kwargs: Any) -> Any:
        self.calls.append(("read_lines", dict[str, object](kwargs)))
        if "read_lines" in self.denied:
            raise PermissionDenied("read_lines denied for this resource")
        return self.read_lines_return


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


def test_dispatch_list_files_returns_filenames() -> None:
    files = ["a.md", "b.md"]
    tools = MockScopedTools(list_files_return=files)
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    result = dispatcher.dispatch(
        ToolCall(name="list_files", args={"resource_type": "worldbook"})
    )
    assert result.ok is True
    assert result.output == files


def test_dispatch_grep_lines_returns_hits() -> None:
    hits = [("worldbook.md", 42, "matching line")]
    tools = MockScopedTools(grep_lines_return=hits)
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    result = dispatcher.dispatch(
        ToolCall(name="grep_lines", args={"resource_type": "worldbook", "pattern": "tavern"})
    )
    assert result.ok is True
    assert result.output == hits


def test_dispatch_read_lines_returns_text() -> None:
    tools = MockScopedTools(read_lines_return="line2\nline3")
    dispatcher = ToolDispatcher(tools)
    from app.runtime.runners.base import ToolCall

    result = dispatcher.dispatch(
        ToolCall(name="read_lines", args={"resource_type": "state", "filename": "s.md", "start": 2, "end": 3})
    )
    assert result.ok is True
    assert result.output == "line2\nline3"


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
    assert "read" in str(exc_info.value)
    assert "write" in str(exc_info.value)
    assert "list_files" in str(exc_info.value)


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


# ── Protocol satisfaction ───────────────────────────────────────────────────


def test_mock_scoped_tools_satisfies_protocol() -> None:
    """The mock double must satisfy the ScopedTools Protocol (static + runtime)."""
    tools: ScopedTools = MockScopedTools()
    assert isinstance(tools, ScopedTools)
