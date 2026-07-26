"""Pure runtime tools — implementations invoked via the ToolCatalog.

The schema metadata (:data:`app.agents.tools.BUILTIN_TOOL_SCHEMAS`) stays
in the Agent layer; the implementations live here in the Runtime layer.
Storage tools (``read`` / ``write`` / …) are NOT implemented here — they
are dispatched to the permission-scoped ``ScopedTools`` surface by the
:class:`~app.runtime.tool_dispatcher.ToolDispatcher`.
"""

from __future__ import annotations

import random
import re

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
