from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.event_catalog import resolve_event_catalog_entry
from app.event_reducers import build_reducer_registry
from app.event_response_builders import build_response_registry
from app.event_types import EventApplicationResult, RuntimeEvent
from app.player_input import ParsedPlayerInput

__all__ = [
    "RuntimeEvent",
    "EventApplicationResult",
    "build_runtime_event",
    "apply_event_to_state",
    "build_rp_response",
    "dump_event",
    "dump_response",
]


STATE_REDUCERS, VISIBLE_REDUCERS = build_reducer_registry()
RESPONSE_BUILDERS = build_response_registry()


def build_runtime_event(parsed: ParsedPlayerInput, actor: str = "player") -> RuntimeEvent:
    entry = resolve_event_catalog_entry(parsed.intent)
    target = parsed.target or "environment"
    summary_parts = [actor, parsed.intent or "unknown"]
    if target:
        summary_parts.append(target)
    if parsed.action:
        summary_parts.append(parsed.action)
    summary = " | ".join(part for part in summary_parts if part)
    return RuntimeEvent(
        event_type=entry.event_type,
        actor=actor,
        target=target,
        intent=parsed.intent,
        action=parsed.action,
        dialogue=parsed.dialogue,
        visibility=entry.visibility,
        summary=summary,
        catalog_key=entry.key,
    )


def apply_event_to_state(state_text: str, player_visible_text: str, event: RuntimeEvent) -> EventApplicationResult:
    entry = resolve_event_catalog_entry(event.intent, event.catalog_key)
    state_reducer = STATE_REDUCERS[entry.state_reducer]
    visible_reducer = VISIBLE_REDUCERS[entry.visible_reducer]
    response_builder = RESPONSE_BUILDERS[entry.response_builder]

    state_text, next_scene = state_reducer(state_text, event)
    response = response_builder(event, next_scene)
    player_visible_text = visible_reducer(player_visible_text, event, response)
    return EventApplicationResult(state_text=state_text, player_visible_text=player_visible_text, event=event, response=response)


def build_rp_response(event: RuntimeEvent, next_scene_id: str) -> dict[str, Any]:
    entry = resolve_event_catalog_entry(event.intent, event.catalog_key)
    response_builder = RESPONSE_BUILDERS[entry.response_builder]
    return response_builder(event, next_scene_id)


def dump_event(event: RuntimeEvent, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(event.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def dump_response(response: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
