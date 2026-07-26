"""Runtime-layer tool implementations — ToolExecutor + pure runtime tools.

The schema metadata (:data:`app.agents.tools.BUILTIN_TOOL_SCHEMAS`) stays
in the Agent layer; the execution glue lives here in the Runtime layer:
:class:`ToolExecutor` wraps the permission-scoped storage tools, and
:func:`dice_roll` is a pure runtime tool invoked via the
:class:`~app.runtime.tool_catalog.ToolCatalog`.

The executor holds a :class:`~app.runtime.permission.ScopedTools` (which
wraps a :class:`~app.data.store.ResourceStore` + a
:class:`~app.runtime.permission.Permission`) and exposes the unified tool
methods: ``read``, ``write``, ``list_files``, ``glob_files``,
``grep_lines``, ``read_lines``. Permission enforcement happens *inside*
the wrapped ``ScopedTools`` — this layer adds no permission logic of its
own, it only routes the call.
"""

from __future__ import annotations

import random
import re

from app.runtime.permission import ScopedTools

# Matches NdM(+/-K) notation: 1d10, 1d100, 3d6+2, d20, 2d8-1.
# Group 1 = count (optional, defaults to 1), group 2 = sides, group 3 = modifier.
_DICE_RE: re.Pattern[str] = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


def _parse_dice_args(kwargs: dict[str, object]) -> tuple[int, int, int]:
    """Parse notation or sides/count/modifier into (count, sides, modifier).

    Raises:
        ValueError: If notation is unparseable or both notation and sides
            are missing.
    """
    notation = kwargs.get("notation")
    if isinstance(notation, str) and notation.strip():
        match = _DICE_RE.match(notation)
        if not match:
            msg = f"无法解析骰子表达式：{notation!r}"
            raise ValueError(msg)
        count = int(match.group(1)) if match.group(1) else 1
        sides = int(match.group(2))
        modifier = int(match.group(3).replace(" ", "")) if match.group(3) else 0
        return count, sides, modifier
    if kwargs.get("sides") is None:
        msg = "缺少 notation 或 sides 参数"
        raise ValueError(msg)
    count = int(str(kwargs.get("count", 1)))
    sides = int(str(kwargs["sides"]))
    modifier = int(str(kwargs.get("modifier", 0)))
    return count, sides, modifier


def dice_roll(**kwargs: object) -> dict[str, object]:
    """DnD-style dice roll — a pure runtime tool (no LLM, RNG only).

    Supports ``NdM(+/-K)`` notation (``1d10``, ``3d6+2``, ``d20``) via
    ``notation``, or explicit ``sides`` / ``count`` / ``modifier``
    arguments. Deterministic when ``seed`` is provided.

    Returns:
        ``{"total": int, "rolls": list[int], "modifier": int, "notation": str}``

    Raises:
        ValueError: On unparseable notation or illegal parameters
            (``sides < 1``, ``count < 1``, ``count > 1000``).
    """
    count, sides, modifier = _parse_dice_args(dict(kwargs))
    if sides < 1 or count < 1 or count > 1000:
        msg = "非法掷骰参数（要求 sides>=1, 1<=count<=1000）"
        raise ValueError(msg)

    seed = kwargs.get("seed")
    if seed is not None and not isinstance(seed, int | float | str | bytes | bytearray):
        msg = f"非法 seed 类型：{type(seed).__name__}"
        raise ValueError(msg)
    rng = random.Random(seed) if seed is not None else random.Random()
    rolls = [rng.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    notation = f"{count}d{sides}" + (f"{modifier:+d}" if modifier else "")
    return {"total": total, "rolls": rolls, "modifier": modifier, "notation": notation}


class ToolExecutor:
    """Agent-facing tool executor wrapping a :class:`ScopedTools`.

    The executor holds a :class:`~app.runtime.permission.ScopedTools`
    (which itself wraps a :class:`~app.data.store.ResourceStore` + a
    :class:`~app.runtime.permission.Permission`) and exposes the unified
    tool methods. The runtime constructs one ``ToolExecutor`` per agent
    per round, injecting the agent's scoped tools.

    Permission enforcement happens *inside* the wrapped ``ScopedTools``
    (a :class:`~app.runtime.permission.PermissionDenied` raised there
    propagates unchanged through this layer). This class adds no permission
    logic of its own — it is the agent-facing executor glue, not a
    re-implementation of the store or the permission gate.

    The methods mirror :meth:`ScopedTools.read` / :meth:`ScopedTools.write`
    / :meth:`ScopedTools.list_files` / :meth:`ScopedTools.glob_files` /
    :meth:`ScopedTools.grep_lines` / :meth:`ScopedTools.read_lines`
    one-for-one so a ``ToolExecutor`` can be used anywhere a ``ScopedTools``
    Protocol is expected (e.g. the
    :class:`~app.runtime.tool_dispatcher.ToolDispatcher`).
    """

    def __init__(self, scoped_tools: ScopedTools) -> None:
        self._scoped = scoped_tools

    @property
    def scoped_tools(self) -> ScopedTools:
        """The wrapped permission-scoped tool surface (exposed for wrapping/testing)."""
        return self._scoped

    # -- unified tools: read / write / list_files / glob_files / grep_lines / read_lines --

    def read(self, resource_type: str, filename: str | None = None) -> str:
        """Read content from a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY`` (e.g. ``"state"``).
            filename: Optional specific file within the resource; ``None``
                reads all content files concatenated.

        Returns:
            The file content (str).

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.read(resource_type, filename)

    def list_files(self, resource_type: str) -> list[str]:
        """List content files in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.

        Returns:
            A sorted list of content file names (excluding metadata files).

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.list_files(resource_type)

    def glob_files(self, resource_type: str, pattern: str) -> list[str]:
        """Glob-match content file names in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            pattern: fnmatch glob pattern.

        Returns:
            A list of matching file names.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.glob_files(resource_type, pattern)

    def grep_lines(
        self,
        resource_type: str,
        pattern: str,
        filename: str | None = None,
    ) -> list[tuple[str, int, str]]:
        """Regex search content files in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            pattern: Regex pattern to match.
            filename: Optional specific file to search; ``None`` searches all.

        Returns:
            A list of ``(filename, line_number, line_text)`` tuples.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.grep_lines(resource_type, pattern, filename)

    def read_lines(self, resource_type: str, filename: str, start: int, end: int) -> str:
        """Read a line range from a file in a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            filename: File name within the resource directory.
            start: 1-based start line (inclusive).
            end: 1-based end line (inclusive).

        Returns:
            The selected lines joined by ``\\n``.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``read`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.read_lines(resource_type, filename, start, end)

    def write(self, resource_type: str, filename: str, content: str) -> bool:
        """Write content to a resource.

        Args:
            resource_type: One of ``RESOURCE_TYPE_REGISTRY``.
            filename: File name within the resource directory.
            content: The text to write.

        Returns:
            ``True`` on success.

        Raises:
            PermissionDenied: If the agent's permission does not cover
                ``write`` on *resource_type* (propagated from ``ScopedTools``).
        """
        return self._scoped.write(resource_type, filename, content)
