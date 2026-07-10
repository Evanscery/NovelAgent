"""Tests for Runtime — concurrent exec / timeout / retry / await primitives."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.runtime.runners.base import AgentResponse, AgentRunner, RunnerAgent, TokenUsage
from app.runtime.runtime import Runtime, TransientRunnerError

# ── test doubles ─────────────────────────────────────────────────────────────


@dataclass
class StubAgent:
    """Minimal agent satisfying the RunnerAgent protocol."""

    id: str
    model: str | None = None


class _CountingRunner(AgentRunner):
    """Runner whose behavior is scripted by a list of outcomes.

    Each entry of ``outcomes`` is either:
      - an ``AgentResponse`` (returned), or
      - an ``Exception`` instance (raised), or
      - a float (seconds to sleep before returning a canned response — used
        to test timeout).
    """

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []
        self.call_count = 0

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        self.calls.append((agent.id, prompt))
        self.call_count += 1
        idx = min(self.call_count - 1, len(self._outcomes) - 1)
        outcome = self._outcomes[idx]
        if isinstance(outcome, float):
            await asyncio.sleep(outcome)
            return AgentResponse(text=f"slept {outcome}s", usage=TokenUsage(0, 0))
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, AgentResponse):
            return outcome
        msg = f"_CountingRunner: outcome {outcome!r} is not an AgentResponse"
        raise TypeError(msg)


def _resp(text: str) -> AgentResponse:
    return AgentResponse(text=text, usage=TokenUsage(10, 5))


# ── happy: concurrent send of 3 mock agents completes within timeout ──────


@pytest.mark.asyncio
async def test_three_concurrent_mock_agents_complete_within_timeout() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
    runner = _CountingRunner([_resp("a"), _resp("b"), _resp("c")])
    agents: list[RunnerAgent] = [StubAgent(id=f"agent-{i}") for i in range(3)]
    runners: list[AgentRunner] = [runner] * 3
    tasks: list[tuple[RunnerAgent, AgentRunner, str]] = list(
        zip(agents, runners, ["p"] * 3, strict=False)
    )

    start = time.monotonic()
    results = await runtime.run_concurrent(tasks)
    elapsed = time.monotonic() - start

    assert len(results) == 3
    assert {r.text for r in results} == {"a", "b", "c"}
    # Three near-instant mock calls should complete well under the 5s timeout.
    assert elapsed < 5.0


# ── timeout: an agent that sleeps longer than timeout raises TimeoutError ──


@pytest.mark.asyncio
async def test_agent_exceeding_timeout_raises_timeout_error() -> None:
    runtime = Runtime({"timeout_seconds": 0.1, "max_retries": 0, "max_concurrent": 1})
    runner = _CountingRunner([1.0])  # sleep 1.0s → exceeds 0.1s timeout
    agent = StubAgent(id="slow")

    with pytest.raises(TimeoutError):
        await runtime.send_request(agent, runner, "p")


# ── retry: an agent that fails twice then succeeds retries and returns ────


@pytest.mark.asyncio
async def test_retry_then_success() -> None:
    runtime = Runtime(
        {
            "timeout_seconds": 5,
            "max_retries": 2,
            "backoff_seconds": [0.0, 0.0],
            "max_concurrent": 1,
        }
    )
    runner = _CountingRunner(
        [
            TransientRunnerError("fail 1"),
            TransientRunnerError("fail 2"),
            _resp("ok"),
        ]
    )
    agent = StubAgent(id="flaky")

    result = await runtime.send_request(agent, runner, "p")

    assert result.text == "ok"
    assert runner.call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises_last_error() -> None:
    runtime = Runtime(
        {
            "timeout_seconds": 5,
            "max_retries": 1,
            "backoff_seconds": [0.0],
            "max_concurrent": 1,
        }
    )
    runner = _CountingRunner(
        [
            TransientRunnerError("fail 1"),
            TransientRunnerError("fail 2"),
        ]
    )
    agent = StubAgent(id="always-fails")

    with pytest.raises(TransientRunnerError, match="fail 2"):
        await runtime.send_request(agent, runner, "p")
    assert runner.call_count == 2


@pytest.mark.asyncio
async def test_timeout_is_retried() -> None:
    """TimeoutError is treated as transient and retried."""
    runtime = Runtime(
        {
            "timeout_seconds": 0.05,
            "max_retries": 1,
            "backoff_seconds": [0.0],
            "max_concurrent": 1,
        }
    )
    # First call sleeps (times out), second returns immediately.
    runner = _CountingRunner([1.0, _resp("recovered")])
    agent = StubAgent(id="slow-then-fast")

    result = await runtime.send_request(agent, runner, "p")
    assert result.text == "recovered"
    assert runner.call_count == 2


# ── await_all ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_await_all_all_succeed() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})

    loop = asyncio.get_running_loop()

    async def make(text: str) -> AgentResponse:
        return _resp(text)

    futures = [loop.create_task(make("r1")), loop.create_task(make("r2")), loop.create_task(make("r3"))]

    results = await runtime.await_all(futures)
    assert len(results) == 3
    assert {r.text for r in results} == {"r1", "r2", "r3"}


@pytest.mark.asyncio
async def test_await_all_one_failure_two_successes_collected() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
    loop = asyncio.get_running_loop()

    async def ok(text: str) -> AgentResponse:
        return _resp(text)

    async def boom() -> AgentResponse:
        raise ValueError("boom")

    futures: list[asyncio.Task[AgentResponse]] = [
        loop.create_task(ok("ok-1")),
        loop.create_task(boom()),
        loop.create_task(ok("ok-2")),
    ]

    results = await runtime.await_all(futures)
    # Two successes collected; the failure did not cancel them.
    assert len(results) == 2
    assert {r.text for r in results} == {"ok-1", "ok-2"}


@pytest.mark.asyncio
async def test_await_all_with_failures_exposes_exceptions() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
    loop = asyncio.get_running_loop()

    async def ok() -> AgentResponse:
        return _resp("ok")

    async def boom() -> AgentResponse:
        raise ValueError("boom")

    futures: list[asyncio.Task[AgentResponse]] = [loop.create_task(ok()), loop.create_task(boom())]
    result = await runtime.await_all_with_failures(futures)
    assert len(result.successes) == 1
    assert result.successes[0].text == "ok"
    assert len(result.failures) == 1
    assert isinstance(result.failures[0], ValueError)


@pytest.mark.asyncio
async def test_await_all_empty_returns_empty() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 1})
    results = await runtime.await_all([])
    assert results == []


# ── await_any ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_await_any_returns_first_completed() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 5})
    loop = asyncio.get_running_loop()

    async def fast() -> AgentResponse:
        await asyncio.sleep(0.01)
        return _resp("fast")

    async def slow() -> AgentResponse:
        await asyncio.sleep(1.0)
        return _resp("slow")

    futures: list[asyncio.Task[AgentResponse]] = [loop.create_task(slow()), loop.create_task(fast())]
    result = await runtime.await_any(futures)
    assert result.text == "fast"
    # Clean up the pending task.
    for f in futures:
        if not f.done():
            f.cancel()


@pytest.mark.asyncio
async def test_await_any_empty_raises() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 1})
    with pytest.raises(ValueError, match="no futures"):
        await runtime.await_any([])


# ── run_concurrent respects max_concurrent ───────────────────────────────────


@dataclass
class _ConcurrencyTracker(AgentRunner):
    """Tracks the peak number of simultaneous run() calls."""

    max_seen: int = 0
    _current: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    responses: list[AgentResponse] = field(default_factory=list)

    async def run(self, agent: RunnerAgent, prompt: str) -> AgentResponse:
        async with self._lock:
            self._current += 1
            if self._current > self.max_seen:
                self.max_seen = self._current
        await asyncio.sleep(0.05)  # hold the slot briefly so overlap is observable
        async with self._lock:
            self._current -= 1
        return _resp(f"{agent.id}-done")


@pytest.mark.asyncio
async def test_run_concurrent_respects_max_concurrent() -> None:
    runtime = Runtime(
        {
            "timeout_seconds": 5,
            "max_retries": 0,
            "max_concurrent": 2,
        }
    )
    tracker = _ConcurrencyTracker()
    agents: list[RunnerAgent] = [StubAgent(id=f"a{i}") for i in range(6)]
    runners: list[AgentRunner] = [tracker] * 6
    tasks: list[tuple[RunnerAgent, AgentRunner, str]] = list(
        zip(agents, runners, ["p"] * 6, strict=False)
    )

    results = await runtime.run_concurrent(tasks)

    assert len(results) == 6
    # With max_concurrent=2 and 6 tasks, peak simultaneous in-flight calls
    # must never exceed 2.
    assert tracker.max_seen <= 2
    assert tracker.max_seen == 2  # and we expect it to actually reach 2


@pytest.mark.asyncio
async def test_run_concurrent_empty_returns_empty() -> None:
    runtime = Runtime({"timeout_seconds": 5, "max_retries": 0, "max_concurrent": 2})
    results = await runtime.run_concurrent([])
    assert results == []
