from __future__ import annotations

from typing import Callable

from app.event_types import RuntimeEvent


ResponseBuilder = Callable[[RuntimeEvent, str], dict]


def build_layered_turn_response(event: RuntimeEvent, next_scene_id: str) -> dict:
    narration = f"场景推进到 {next_scene_id}。{event.actor} 针对 {event.target} 采取了行动：{event.action or event.intent}。"
    if event.intent == "dialogue" and event.dialogue:
        narration += f" 对话内容是：{event.dialogue}。"
    reactions = [
        {
            "speaker": "GM",
            "role": "narrator",
            "text": narration,
        },
        {
            "speaker": event.target or "环境",
            "role": "character",
            "text": _character_reply(event),
        },
    ]
    return {
        "scene_id": next_scene_id,
        "gm_narration": narration,
        "character_reactions": reactions,
    }


def build_response_registry() -> dict[str, Callable]:
    return {
        "layered_turn_response": build_layered_turn_response,
    }


def _character_reply(event: RuntimeEvent) -> str:
    if event.intent == "dialogue" and event.dialogue:
        return f"{event.target} 听完后给出回应，并把话题推回当前冲突。"
    if event.intent == "inspect":
        return f"{event.target} 注意到你的观察，并露出一丝新的反应。"
    if event.intent == "move":
        return f"{event.target} 随着你的移动而调整站位。"
    return f"{event.target} 对这一行动做出即时反馈。"
