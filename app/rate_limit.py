from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic


@dataclass
class SimpleRateLimiter:
    rpm: int
    _last_call_at: float = 0.0

    async def wait(self) -> None:
        if self.rpm <= 0:
            return
        min_interval = 60.0 / self.rpm
        now = monotonic()
        wait_seconds = min_interval - (now - self._last_call_at)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        self._last_call_at = monotonic()
