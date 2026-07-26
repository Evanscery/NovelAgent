"""Token/tool budget tracker; Finalize on budget exhaustion / max iterations.

A Workflow round ends under exactly three conditions:

1. the maximum iteration count is reached,
2. the token or tool-call budget is exhausted, or
3. the director explicitly calls ``Finalize``.

This module is a **pure counter**: it accumulates consumption and raises
:class:`FinalizeSignal` the moment any ceiling is breached. The Runtime /
director catch the signal to terminate the round cleanly. It has no other
side effects.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Budget:
    """Snapshot of budget ceilings and current consumption.

    ``max_*`` fields are the ceilings; ``used_*`` fields are the counters that
    grow as the workflow runs. ``BudgetTracker`` owns the mutable state; this
    dataclass is the immutable view returned by ``remaining()`` and similar
    accessors.
    """

    max_tokens: int
    max_tool_calls: int
    max_iterations: int
    used_tokens: int = 0
    used_tool_calls: int = 0
    used_iterations: int = 0


@dataclass(frozen=True)
class BudgetRemaining:
    """Per-counter remaining headroom (``max - used``, clamped at zero)."""

    tokens: int
    tool_calls: int
    iterations: int


class FinalizeSignal(Exception):
    """Raised to terminate the current Workflow round.

    The Runtime / director catches this to end the round cleanly. It carries a
    short machine-readable ``reason`` describing *why* the round is ending.
    This module raises it with reason ``"budget_exhausted"`` when a token /
    tool-call / iteration ceiling is breached during ``consume``. Other
    round-end reasons (e.g. an explicit ``finalize`` tool call) are produced
    by the round executor directly, without going through this exception.
    """

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def __str__(self) -> str:
        return self.reason


class BudgetTracker:
    """Pure counter for token / tool-call / iteration consumption.

    The tracker is the single source of truth for "how much of the budget has
    the current Workflow round spent". ``consume`` is called after each agent
    step; ``is_exhausted`` lets the director poll the budget; ``remaining``
    reports what is left. The tracker performs no I/O and mutates only its own
    counters — its sole side effect is raising :class:`FinalizeSignal` when a
    ceiling is breached.
    """

    __slots__ = (
        "_max_tokens",
        "_max_tool_calls",
        "_max_iterations",
        "_used_tokens",
        "_used_tool_calls",
        "_used_iterations",
    )

    def __init__(
        self,
        max_tokens: int = 100_000,
        max_tool_calls: int = 50,
        max_iterations: int = 20,
    ) -> None:
        self._max_tokens = max_tokens
        self._max_tool_calls = max_tool_calls
        self._max_iterations = max_iterations
        self._used_tokens = 0
        self._used_tool_calls = 0
        self._used_iterations = 0

    # --- consumption --------------------------------------------------------

    def consume(self, tokens: int = 0, tool_calls: int = 0, iterations: int = 1) -> None:
        """Add to the used counters and raise ``FinalizeSignal`` if exceeded.

        Args:
            tokens: Tokens consumed by this step (e.g. from ``TokenUsage``).
            tool_calls: Tool calls dispatched during this step.
            iterations: Workflow iterations advanced. Defaults to ``1`` so a
                single ``consume()`` call with no args advances one iteration,
                which is the common case for a director step.

        Raises:
            FinalizeSignal: if any counter crosses its ceiling as a result of
                this call.
        """
        self._used_tokens += tokens
        self._used_tool_calls += tool_calls
        self._used_iterations += iterations

        exceeded: list[str] = []
        if self._used_tokens > self._max_tokens:
            exceeded.append("tokens")
        if self._used_tool_calls > self._max_tool_calls:
            exceeded.append("tool_calls")
        if self._used_iterations > self._max_iterations:
            exceeded.append("iterations")

        if exceeded:
            raise FinalizeSignal("budget_exhausted")

    # --- queries ------------------------------------------------------------

    def is_exhausted(self) -> bool:
        """True if any used counter has reached or exceeded its ceiling."""
        return (
            self._used_tokens >= self._max_tokens
            or self._used_tool_calls >= self._max_tool_calls
            or self._used_iterations >= self._max_iterations
        )

    def remaining(self) -> BudgetRemaining:
        """Return the remaining headroom per counter (clamped at zero)."""
        return BudgetRemaining(
            tokens=max(self._max_tokens - self._used_tokens, 0),
            tool_calls=max(self._max_tool_calls - self._used_tool_calls, 0),
            iterations=max(self._max_iterations - self._used_iterations, 0),
        )

    def snapshot(self) -> Budget:
        """Return a :class:`Budget` snapshot of the *current* ceilings and used values."""
        return Budget(
            max_tokens=self._max_tokens,
            max_tool_calls=self._max_tool_calls,
            max_iterations=self._max_iterations,
            used_tokens=self._used_tokens,
            used_tool_calls=self._used_tool_calls,
            used_iterations=self._used_iterations,
        )

    # --- lifecycle ----------------------------------------------------------

    def reset(self) -> None:
        """Reset all used counters to zero (begin a fresh round)."""
        self._used_tokens = 0
        self._used_tool_calls = 0
        self._used_iterations = 0
