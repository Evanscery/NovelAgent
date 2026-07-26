"""Runtime — agent-agnostic execution infrastructure.

The Runtime wraps an :class:`AgentRunner` with:

* per-request timeout (``asyncio.timeout``),
* retry with backoff for ``TimeoutError`` and transient runner errors,
* concurrency primitives — ``await_all``, ``await_any``, ``run_concurrent``
  with a ``max_concurrent`` semaphore.

It does NOT call tools (that is the tool dispatcher's job), does NOT enforce
permission (that is the permission injector's job), and does NOT reference
any specific agent class — it only needs the :class:`RunnerAgent` protocol
fields ``id`` and ``model``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.runtime._coerce import as_float as _as_float
from app.runtime._coerce import as_int as _as_int
from app.runtime.prompt_builder import RequestSpec
from app.runtime.runners.base import AgentResponse, AgentRunner, RunnerAgent

logger = logging.getLogger(__name__)


class TransientRunnerError(Exception):
    """Marker base class for runner errors the Runtime should retry.

    A runner that wants its error retried should raise an exception that
    subclasses this. :class:`TimeoutError` is always retried regardless of
    type.
    """


@dataclass
class RuntimeResult:
    """Outcome of an ``await_all`` batch.

    Attributes:
        successes: AgentResponses for tasks that completed.
        failures:  Exceptions for tasks that raised.
    """

    successes: list[AgentResponse] = field(default_factory=list)
    failures: list[BaseException] = field(default_factory=list)


class Runtime:
    """Agent-agnostic execution coordinator.

    Args:
        runtime_policy: Policy dict. Recognized keys:
            - ``timeout_seconds`` : per-request timeout (float/int).
            - ``max_retries``     : retry attempts for transient failures.
            - ``backoff_seconds`` : list of wait seconds between retries.
            - ``max_concurrent``  : concurrency limit for ``run_concurrent``.
    """

    def __init__(self, runtime_policy: dict[str, object]) -> None:
        self._timeout: float = _as_float(runtime_policy.get("timeout_seconds"), 600.0)
        self._max_retries: int = _as_int(runtime_policy.get("max_retries"), 0)
        backoff = runtime_policy.get("backoff_seconds", [])
        if isinstance(backoff, Sequence):
            self._backoff: list[float] = [_as_float(x, 0.0) for x in backoff]
        else:
            self._backoff = []
        self._max_concurrent: int = _as_int(runtime_policy.get("max_concurrent"), 1)
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(self._max_concurrent)

    async def send_request(
        self,
        agent: RunnerAgent,
        runner: AgentRunner,
        request: RequestSpec,
    ) -> AgentResponse:
        """Send a single request through ``runner``, wrapped with timeout + retry.

        Retries on ``TimeoutError`` and :class:`TransientRunnerError` up to
        ``max_retries`` times, sleeping ``backoff_seconds[attempt]`` between
        attempts. Raises the last exception if all attempts fail.
        """
        last_exc: BaseException | None = None
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            try:
                async with asyncio.timeout(self._timeout):
                    return await runner.run(agent, request)
            except TimeoutError as exc:
                last_exc = exc
                logger.warning(
                    "Runtime: agent '%s' timed out (attempt %d/%d)",
                    agent.id,
                    attempt + 1,
                    attempts,
                )
            except TransientRunnerError as exc:
                last_exc = exc
                logger.warning(
                    "Runtime: agent '%s' transient error (attempt %d/%d): %s",
                    agent.id,
                    attempt + 1,
                    attempts,
                    exc,
                )
            else:
                # Should not reach here because the try block returns, but
                # kept for clarity.
                break

            if attempt + 1 < attempts:
                wait = self._backoff[min(attempt, len(self._backoff) - 1)] if self._backoff else 0.0
                if wait > 0:
                    await asyncio.sleep(wait)

        # Exhausted retries.
        if isinstance(last_exc, TimeoutError):
            raise TimeoutError(
                f"Runtime: agent '{agent.id}' timed out after {attempts} attempt(s)"
            ) from last_exc
        if last_exc is not None:
            raise last_exc
        # Defensive: loop exited without a result and without an exception.
        msg = f"Runtime: agent '{agent.id}' produced no result and no exception"
        raise RuntimeError(msg)

    async def await_all(
        self,
        futures: list[asyncio.Task[AgentResponse]],
    ) -> list[AgentResponse]:
        """Await all tasks concurrently, collecting successes.

        Uses ``asyncio.gather(..., return_exceptions=True)`` so a single
        failure does not cancel the others. Returns the list of successful
        :class:`AgentResponse` objects. Failures are logged; to inspect
        them use :meth:`await_all_with_failures`.
        """
        result = await self.await_all_with_failures(futures)
        return result.successes

    async def await_all_with_failures(
        self,
        futures: list[asyncio.Task[AgentResponse]],
    ) -> RuntimeResult:
        """Like :meth:`await_all` but also returns the failures."""
        if not futures:
            return RuntimeResult()
        raw = await asyncio.gather(*futures, return_exceptions=True)
        successes: list[AgentResponse] = []
        failures: list[BaseException] = []
        for item in raw:
            if isinstance(item, BaseException):
                failures.append(item)
            else:
                successes.append(item)
        return RuntimeResult(successes=successes, failures=failures)

    async def await_any(
        self,
        futures: list[asyncio.Task[AgentResponse]],
    ) -> AgentResponse:
        """Return the first completed result.

        Uses ``asyncio.wait(..., return_when=FIRST_COMPLETED)``. The other
        tasks are NOT cancelled — the caller decides whether to cancel them.
        """
        if not futures:
            msg = "await_any: no futures provided"
            raise ValueError(msg)
        done, _pending = await asyncio.wait(futures, return_when=asyncio.FIRST_COMPLETED)
        # The first completed task. (Sets are unordered, but FIRST_COMPLETED
        # guarantees at least one done task; pick the one that is actually
        # done and not in a cancelled state.)
        for task in done:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                raise exc
            return task.result()
        # All done tasks were cancelled or had exceptions — surface one.
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
        msg = "await_any: no completed task produced a result"
        raise RuntimeError(msg)

    async def run_concurrent(
        self,
        tasks: list[tuple[RunnerAgent, AgentRunner, RequestSpec]],
    ) -> list[AgentResponse]:
        """Create a Task per (agent, runner, request) tuple and await_all them.

        Respects ``max_concurrent`` via an :class:`asyncio.Semaphore`: at
        most ``max_concurrent`` requests run simultaneously.
        """
        if not tasks:
            return []
        loop = asyncio.get_running_loop()
        futures: list[asyncio.Task[AgentResponse]] = []
        for agent, runner, request in tasks:
            futures.append(loop.create_task(self._bounded_send(agent, runner, request)))
        return await self.await_all(futures)

    async def _bounded_send(
        self,
        agent: RunnerAgent,
        runner: AgentRunner,
        request: RequestSpec,
    ) -> AgentResponse:
        """``send_request`` gated by the concurrency semaphore."""
        async with self._semaphore:
            return await self.send_request(agent, runner, request)
