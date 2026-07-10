"""Parse agent tool-call requests, dispatch to read/search/write, reject overreach.

Per ``docs/refactor_guide.md:112-123`` the standardized tool surface is exactly
three tools — ``read(resource)``, ``search(resource)``, ``write(resource)``.
The legacy ``readFile`` / ``readMemory`` / ``readLore`` style proliferation is
forbidden; this dispatcher rejects any tool name outside the allowed set with
:class:`UnknownToolError`.

The dispatcher does NOT enforce permission itself — that is the job of the
``ScopedTools`` it is handed (produced by ``app.runtime.permission``'s
``inject_into_tools``). A ``PermissionDenied`` raised inside a scoped tool
propagates out of :meth:`ToolDispatcher.dispatch` unchanged so the runtime can
handle it at the appropriate layer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.runtime.runners.base import ToolCall

__all__ = [
    "ScopedTools",
    "ToolCall",
    "ToolDispatcher",
    "ToolResult",
    "UnknownToolError",
]


_ALLOWED_TOOLS: frozenset[str] = frozenset({"read", "search", "write"})


@runtime_checkable
class ScopedTools(Protocol):
    """Permission-scoped tool surface the dispatcher delegates to.

    todo 11 (``app/runtime/permission.py``) produces a concrete ``ScopedTools``
    via ``inject_into_tools``. Until that lands, this Protocol lets the
    dispatcher be built and tested against any object exposing the three
    standardized methods. Permission enforcement happens *inside* these
    methods — a scope violation raises ``PermissionDenied`` (defined by
    todo 11) which propagates through :meth:`ToolDispatcher.dispatch`.
    """

    def read(self, **kwargs: object) -> object: ...

    def search(self, **kwargs: object) -> object: ...

    def write(self, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class ToolResult:
    """Outcome of dispatching a :class:`ToolCall`.

    Attributes:
        ok:     ``True`` when the tool ran without raising.
        output: The value returned by the scoped tool (untyped — read returns
                ``str``, search returns ``list[SearchHit]``, write returns
                ``None``). Present when ``ok`` is ``True``.
        error:  Human-readable error message. Empty when ``ok`` is ``True``.
    """

    ok: bool
    output: Any = None
    error: str = ""


class UnknownToolError(Exception):
    """Raised when an agent calls a tool not in {read, search, write}."""


# ── parsing ────────────────────────────────────────────────────────────────

# Preferred format: a fenced code block tagged ``tool`` containing a JSON
# object with ``name`` and ``args`` keys, e.g.::
#
#     ```tool
#     {"name": "read", "args": {"resource_type": "state"}}
#     ```
_JSON_TOOL_BLOCK_RE = re.compile(
    r"```tool\s*\n(.*?)\n```",
    re.DOTALL,
)

# Fallback format: a line ``TOOL: name(args)`` where ``args`` is a
# comma-separated list of bare words or ``key=value`` pairs, e.g.::
#
#     TOOL: read(state)
#     TOOL: write(short_goal, chapter_01.md, Once upon a time...)
#     TOOL: search(resource_type=worldbook, query=tavern)
_TOOL_LINE_RE = re.compile(
    r"^\s*TOOL:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$",
    re.MULTILINE,
)


def _parse_tool_line_args(raw: str) -> dict[str, object]:
    """Parse the positional/key=value args from a ``TOOL: name(...)`` line.

    Bare words become positional args keyed by their 1-based index
    (``"1"``, ``"2"``, …) so a caller like ``read(state)`` still surfaces
    its argument. ``key=value`` pairs are keyed by ``key``. Values are
    not type-coerced — they stay strings, matching the simple format's
    contract. Callers needing typed args should use the JSON block.
    """
    if not raw.strip():
        return {}
    args: dict[str, object] = {}
    for i, piece in enumerate(_split_top_level(raw), start=1):
        token = piece.strip()
        if not token:
            continue
        if "=" in token:
            key, _, value = token.partition("=")
            args[key.strip()] = value.strip()
        else:
            args[str(i)] = token
    return args


def _split_top_level(text: str) -> list[str]:
    """Split ``text`` on top-level commas, ignoring commas inside () or []."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


class ToolDispatcher:
    """Parse agent output for tool calls and dispatch them to scoped tools.

    The dispatcher is the bridge between an agent's textual response and the
    permission-scoped tool surface. It owns *parsing* (two supported formats)
    and *routing* (only ``read`` / ``search`` / ``write`` are allowed); it
    owns neither permission enforcement (that is ``ScopedTools``' job) nor
    tool implementation (that is ``app.agents.tools``' job, todo 16).
    """

    def __init__(self, scoped_tools: ScopedTools) -> None:
        self._tools = scoped_tools

    # ── parsing ────────────────────────────────────────────────────────────

    def parse_tool_call(self, agent_response_text: str) -> ToolCall | None:
        """Extract a single :class:`ToolCall` from agent output.

        Two formats are supported (JSON code block preferred, simple
        parenthetical as fallback). Returns ``None`` when no tool call is
        present. When both formats appear, the JSON block wins because it
        carries typed args.
        """
        if not agent_response_text:
            return None

        # 1) Preferred: ```tool\n{...}\n``` JSON block.
        m = _JSON_TOOL_BLOCK_RE.search(agent_response_text)
        if m is not None:
            payload = m.group(1).strip()
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                # Malformed JSON block — fall through to the simple format
                # rather than silently returning None, so a fallback TOOL:
                # line can still be honored.
                obj = None
            if isinstance(obj, dict):
                name = obj.get("name")
                raw_args = obj.get("args", {})
                if isinstance(name, str) and isinstance(raw_args, dict):
                    return ToolCall(
                        name=name,
                        args=dict[str, object](raw_args),
                    )

        # 2) Fallback: TOOL: name(arg, key=val, ...)
        m = _TOOL_LINE_RE.search(agent_response_text)
        if m is not None:
            name = m.group(1)
            args = _parse_tool_line_args(m.group(2))
            return ToolCall(name=name, args=args)

        return None

    # ── dispatch ───────────────────────────────────────────────────────────

    def dispatch(self, tool_call: ToolCall) -> ToolResult:
        """Route ``tool_call`` to the matching scoped tool.

        Raises:
            UnknownToolError: if ``tool_call.name`` is not one of
                ``read`` / ``search`` / ``write``.
            PermissionDenied: (defined by todo 11) propagated unchanged from
                the scoped tool when the agent lacks permission.
        """
        name = tool_call.name
        if name not in _ALLOWED_TOOLS:
            msg = (
                f"Unknown tool: {name}. "
                "Only read/search/write are allowed."
            )
            raise UnknownToolError(msg)

        method = getattr(self._tools, name)
        result = method(**tool_call.args)
        return ToolResult(ok=True, output=result)

    # ── convenience ────────────────────────────────────────────────────────

    def dispatch_from_text(self, agent_response_text: str) -> ToolResult | None:
        """Parse + dispatch in one call. Returns ``None`` if no tool call."""
        tool_call = self.parse_tool_call(agent_response_text)
        if tool_call is None:
            return None
        return self.dispatch(tool_call)
