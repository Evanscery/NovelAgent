from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Step:
    id: str
    agent: str
    scene_id: str
    prompt_path: str
    output_path: str
    inputs: list[str]
    runner: str
    raw: dict[str, Any]
    preset_path: str | None = None
    modules: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    profile: str | None = None


class AgentRunner:
    """所有运行器的统一接口。"""

    async def run(self, step: Step, context: str) -> str:
        raise NotImplementedError
