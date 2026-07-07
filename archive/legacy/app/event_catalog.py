from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventCatalogEntry:
    key: str
    event_type: str
    intents: tuple[str, ...]
    visibility: str
    state_reducer: str
    response_builder: str
    visible_reducer: str
    metadata: dict[str, Any] = field(default_factory=dict)


EVENT_CATALOG: tuple[EventCatalogEntry, ...] = (
    EventCatalogEntry(
        key="dialogue_turn",
        event_type="player_turn",
        intents=("dialogue",),
        visibility="public",
        state_reducer="advance_scene_state",
        response_builder="layered_turn_response",
        visible_reducer="player_visible_projection",
        metadata={"layered": True, "advance_scene": True},
    ),
    EventCatalogEntry(
        key="inspect_turn",
        event_type="player_turn",
        intents=("inspect",),
        visibility="public",
        state_reducer="advance_scene_state",
        response_builder="layered_turn_response",
        visible_reducer="player_visible_projection",
        metadata={"layered": True, "advance_scene": True},
    ),
    EventCatalogEntry(
        key="move_turn",
        event_type="player_turn",
        intents=("move",),
        visibility="public",
        state_reducer="advance_scene_state",
        response_builder="layered_turn_response",
        visible_reducer="player_visible_projection",
        metadata={"layered": True, "advance_scene": True},
    ),
    EventCatalogEntry(
        key="act_turn",
        event_type="player_turn",
        intents=("act",),
        visibility="public",
        state_reducer="advance_scene_state",
        response_builder="layered_turn_response",
        visible_reducer="player_visible_projection",
        metadata={"layered": True, "advance_scene": True},
    ),
    EventCatalogEntry(
        key="fallback_turn",
        event_type="player_turn",
        intents=(),
        visibility="hidden",
        state_reducer="advance_scene_state",
        response_builder="layered_turn_response",
        visible_reducer="player_visible_projection",
        metadata={"layered": True, "advance_scene": True, "fallback": True},
    ),
)


def resolve_event_catalog_entry(intent: str, catalog_key: str | None = None) -> EventCatalogEntry:
    if catalog_key:
        for entry in EVENT_CATALOG:
            if entry.key == catalog_key:
                return entry
    normalized = (intent or "").strip().lower()
    for entry in EVENT_CATALOG:
        if normalized and normalized in entry.intents:
            return entry
    return EVENT_CATALOG[-1]
