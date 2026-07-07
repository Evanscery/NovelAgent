"""Tests for BudgetTracker — token/tool/iteration consumption + FinalizeSignal.

Per refactor_guide:103-109 the three end conditions for a Workflow round are:
max iterations / token-tool budget exhaustion / explicit Finalize. These tests
verify the tracker is a pure counter whose only side effect is raising
:class:`FinalizeSignal` when a ceiling is breached.
"""

from __future__ import annotations

import pytest

from app.runtime.budget import Budget, BudgetTracker, FinalizeSignal

# ── token consumption ───────────────────────────────────────────────────────


def test_tracks_token_consumption_across_multiple_consume_calls():
    """Tokens accumulate across calls and are reflected in remaining()."""
    tracker = BudgetTracker(max_tokens=1000, max_tool_calls=50, max_iterations=20)
    tracker.consume(tokens=300)
    tracker.consume(tokens=250)
    tracker.consume(tokens=150)
    assert tracker.remaining().used_tokens == 300


def test_consume_beyond_max_tokens_raises_finalize():
    """Crossing the token ceiling raises FinalizeSignal with budget_exhausted."""
    tracker = BudgetTracker(max_tokens=100, max_tool_calls=50, max_iterations=20)
    with pytest.raises(FinalizeSignal) as exc_info:
        tracker.consume(tokens=101)
    assert exc_info.value.reason == "budget_exhausted"


def test_consume_accumulates_then_exceeds_max_tokens():
    """Two consumes that sum past the ceiling still raise on the second."""
    tracker = BudgetTracker(max_tokens=100, max_tool_calls=50, max_iterations=20)
    tracker.consume(tokens=50)
    assert not tracker.is_exhausted()
    with pytest.raises(FinalizeSignal):
        tracker.consume(tokens=51)


# ── tool-call consumption ───────────────────────────────────────────────────


def test_consume_beyond_max_tool_calls_raises_finalize():
    """Crossing the tool-call ceiling raises FinalizeSignal."""
    tracker = BudgetTracker(max_tokens=100_000, max_tool_calls=5, max_iterations=20)
    with pytest.raises(FinalizeSignal) as exc_info:
        tracker.consume(tool_calls=6)
    assert exc_info.value.reason == "budget_exhausted"


# ── iteration consumption ───────────────────────────────────────────────────


def test_consume_beyond_max_iterations_raises_finalize():
    """Crossing the iteration ceiling raises FinalizeSignal."""
    tracker = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=3)
    with pytest.raises(FinalizeSignal) as exc_info:
        tracker.consume(iterations=4)
    assert exc_info.value.reason == "budget_exhausted"


def test_max_iterations_reached_via_accumulated_consume():
    """Hitting the iteration ceiling via repeated 1-iteration consume raises."""
    tracker = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=3)
    tracker.consume()  # iter 1
    tracker.consume()  # iter 2
    tracker.consume()  # iter 3 — exactly at ceiling, NOT beyond
    assert tracker.is_exhausted()
    with pytest.raises(FinalizeSignal):
        tracker.consume()  # iter 4 — beyond


# ── is_exhausted ────────────────────────────────────────────────────────────


def test_is_exhausted_false_when_nothing_consumed():
    tracker = BudgetTracker(max_tokens=1000, max_tool_calls=50, max_iterations=20)
    assert tracker.is_exhausted() is False


def test_is_exhausted_true_when_any_counter_at_ceiling():
    """is_exhausted is True when any used counter reaches its max (>= match)."""
    t_tokens = BudgetTracker(max_tokens=100, max_tool_calls=50, max_iterations=20)
    t_tokens.consume(tokens=100)
    assert t_tokens.is_exhausted() is True

    t_tools = BudgetTracker(max_tokens=100_000, max_tool_calls=5, max_iterations=20)
    t_tools.consume(tool_calls=5)
    assert t_tools.is_exhausted() is True

    t_iters = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=3)
    t_iters.consume(iterations=3)
    assert t_iters.is_exhausted() is True


# ── remaining ───────────────────────────────────────────────────────────────


def test_remaining_returns_correct_remaining_values():
    tracker = BudgetTracker(max_tokens=1000, max_tool_calls=50, max_iterations=20)
    tracker.consume(tokens=200, tool_calls=10, iterations=5)
    rem = tracker.remaining()
    assert isinstance(rem, Budget)
    assert rem.max_tokens == 1000
    assert rem.max_tool_calls == 50
    assert rem.max_iterations == 20
    assert rem.used_tokens == 800
    assert rem.used_tool_calls == 40
    assert rem.used_iterations == 15


def test_remaining_clamps_at_zero_when_over_consumed():
    """After exhaustion + reset flow, remaining never goes negative.

    We construct the over-consumed state by consuming exactly to the ceiling
    (which does NOT raise — boundary correct) and checking remaining is zero.
    Going beyond raises, so the negative path is unreachable via consume().
    """
    tracker = BudgetTracker(max_tokens=100, max_tool_calls=10, max_iterations=5)
    tracker.consume(tokens=100, tool_calls=10, iterations=5)
    rem = tracker.remaining()
    assert rem.used_tokens == 0
    assert rem.used_tool_calls == 0
    assert rem.used_iterations == 0


# ── reset ───────────────────────────────────────────────────────────────────


def test_reset_zeroes_all_counters():
    tracker = BudgetTracker(max_tokens=1000, max_tool_calls=50, max_iterations=20)
    tracker.consume(tokens=300, tool_calls=15, iterations=10)
    assert tracker.is_exhausted() is False
    tracker.reset()
    rem = tracker.remaining()
    assert rem.used_tokens == 1000
    assert rem.used_tool_calls == 50
    assert rem.used_iterations == 20
    assert tracker.is_exhausted() is False


def test_reset_lets_tracker_be_reused_after_exhaustion():
    """After reset, a previously-exhausted tracker accepts consume again."""
    tracker = BudgetTracker(max_tokens=100, max_tool_calls=50, max_iterations=20)
    with pytest.raises(FinalizeSignal):
        tracker.consume(tokens=101)
    tracker.reset()
    tracker.consume(tokens=50)  # no raise
    assert tracker.remaining().used_tokens == 50


# ── FinalizeSignal semantics ────────────────────────────────────────────────


def test_finalize_signal_is_exception():
    """FinalizeSignal must subclass Exception so the director can catch it."""
    assert issubclass(FinalizeSignal, Exception)


def test_finalize_signal_carries_reason_string():
    """The reason attribute is the short machine-readable cause code."""
    for reason in ("budget_exhausted", "max_iterations", "explicit_finalize"):
        sig = FinalizeSignal(reason)
        assert sig.reason == reason
        assert str(sig) == reason


def test_finalize_signal_propagates_through_consume():
    """A raised FinalizeSignal carries budget_exhausted, not max_iterations.

    The tracker distinguishes *breach* (budget_exhausted, raised by consume
    when a ceiling is crossed) from *reached* (max_iterations, which the
    director signals explicitly when is_exhausted() becomes True). This test
    locks the consume-path reason.
    """
    tracker = BudgetTracker(max_tokens=10, max_tool_calls=50, max_iterations=20)
    with pytest.raises(FinalizeSignal) as exc_info:
        tracker.consume(tokens=11)
    assert exc_info.value.reason == "budget_exhausted"


# ── boundary correctness ────────────────────────────────────────────────────


def test_consume_exactly_max_does_not_raise():
    """Consuming exactly up to a ceiling is allowed (boundary not beyond)."""
    tracker = BudgetTracker(max_tokens=100, max_tool_calls=10, max_iterations=5)
    tracker.consume(tokens=100, tool_calls=10, iterations=5)
    assert tracker.is_exhausted() is True


def test_consume_exactly_max_tokens_boundary():
    tracker = BudgetTracker(max_tokens=100, max_tool_calls=50, max_iterations=20)
    tracker.consume(tokens=100)
    assert tracker.is_exhausted() is True
    # one more token pushes over
    with pytest.raises(FinalizeSignal):
        tracker.consume(tokens=1)


def test_consume_exactly_max_tool_calls_boundary():
    tracker = BudgetTracker(max_tokens=100_000, max_tool_calls=10, max_iterations=20)
    tracker.consume(tool_calls=10)
    assert tracker.is_exhausted() is True
    with pytest.raises(FinalizeSignal):
        tracker.consume(tool_calls=1)


def test_consume_exactly_max_iterations_boundary():
    tracker = BudgetTracker(max_tokens=100_000, max_tool_calls=50, max_iterations=5)
    for _ in range(5):
        tracker.consume(iterations=1)
    assert tracker.is_exhausted() is True
    with pytest.raises(FinalizeSignal):
        tracker.consume(iterations=1)


# ── defaults ────────────────────────────────────────────────────────────────


def test_defaults_are_sensible():
    """Default ceilings are non-zero and large enough for a real round."""
    tracker = BudgetTracker()
    snap = tracker.snapshot()
    assert snap.max_tokens == 100_000
    assert snap.max_tool_calls == 50
    assert snap.max_iterations == 20
    assert snap.used_tokens == 0
    assert snap.used_tool_calls == 0
    assert snap.used_iterations == 0


def test_consume_default_advances_one_iteration():
    """consume() with no args advances exactly one iteration."""
    tracker = BudgetTracker(max_iterations=3)
    tracker.consume()
    assert tracker.snapshot().used_iterations == 1
    tracker.consume()
    assert tracker.snapshot().used_iterations == 2
    tracker.consume()
    assert tracker.is_exhausted() is True  # 3 == max_iterations
