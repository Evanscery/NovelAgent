"""Unit tests for runtime tool implementations (:mod:`app.runtime.runtime_tools`).

Covers the ``dice_roll`` runtime tool: notation parsing, explicit
parameters, seed determinism, and ValueError on illegal input (runtime
tools raise — they do not return ok=False result objects).
"""

from __future__ import annotations

import pytest

from app.runtime.runtime_tools import dice_roll


class TestDiceRollNotation:
    def test_simple_notation(self) -> None:
        result = dice_roll(notation="1d6", seed=42)
        rolls = result["rolls"]
        assert isinstance(rolls, list)
        assert len(rolls) == 1
        assert 1 <= rolls[0] <= 6
        assert result["total"] == rolls[0]
        assert result["notation"] == "1d6"
        assert result["modifier"] == 0

    def test_count_defaults_to_one(self) -> None:
        result = dice_roll(notation="d20", seed=1)
        rolls = result["rolls"]
        assert isinstance(rolls, list)
        assert len(rolls) == 1

    def test_notation_with_modifier(self) -> None:
        result = dice_roll(notation="3d6+2", seed=7)
        rolls = result["rolls"]
        assert isinstance(rolls, list)
        assert len(rolls) == 3
        assert result["modifier"] == 2
        assert result["total"] == sum(rolls) + 2
        assert result["notation"] == "3d6+2"

    def test_negative_modifier(self) -> None:
        result = dice_roll(notation="2d8-1", seed=7)
        rolls = result["rolls"]
        assert isinstance(rolls, list)
        assert result["modifier"] == -1
        assert result["total"] == sum(rolls) - 1


class TestDiceRollExplicitArgs:
    def test_sides_count_modifier(self) -> None:
        result = dice_roll(sides=10, count=2, modifier=3, seed=5)
        rolls = result["rolls"]
        assert isinstance(rolls, list)
        assert len(rolls) == 2
        assert all(1 <= r <= 10 for r in rolls)
        assert result["total"] == sum(rolls) + 3

    def test_sides_only(self) -> None:
        result = dice_roll(sides=100, seed=5)
        rolls = result["rolls"]
        assert isinstance(rolls, list)
        assert len(rolls) == 1
        assert 1 <= rolls[0] <= 100


class TestDiceRollDeterminism:
    def test_same_seed_same_result(self) -> None:
        assert dice_roll(notation="3d6+2", seed=99) == dice_roll(notation="3d6+2", seed=99)

    def test_different_seed_can_differ(self) -> None:
        results = {dice_roll(notation="10d100", seed=s)["total"] for s in range(5)}
        assert len(results) > 1


class TestDiceRollInvalidInput:
    def test_unparseable_notation_raises(self) -> None:
        with pytest.raises(ValueError, match="无法解析"):
            dice_roll(notation="not-dice")

    def test_missing_notation_and_sides_raises(self) -> None:
        with pytest.raises(ValueError, match="缺少"):
            dice_roll()

    def test_sides_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="非法"):
            dice_roll(sides=0)

    def test_count_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="非法"):
            dice_roll(sides=6, count=0)

    def test_count_above_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="非法"):
            dice_roll(sides=6, count=1001)
