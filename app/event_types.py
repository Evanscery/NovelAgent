from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    actor: str
    target: str
    intent: str
    action: str
    dialogue: str
    visibility: str
    summary: str
    catalog_key: str = "fallback_turn"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EventApplicationResult:
    state_text: str
    player_visible_text: str
    event: RuntimeEvent
    response: dict[str, Any]
