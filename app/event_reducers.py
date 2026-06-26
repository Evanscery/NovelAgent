from __future__ import annotations

import re
from typing import Callable

from app.event_types import RuntimeEvent
from app.state_tools import parse_story_position


StateReducer = Callable[[str, RuntimeEvent], str]
VisibleReducer = Callable[[str, RuntimeEvent, dict], str]


def reduce_state_advance_scene(state_text: str, event: RuntimeEvent) -> tuple[str, str]:
    state_position = parse_story_position(state_text)
    next_scene = _next_scene_id(state_position.scene_id)
    state_text = _replace_section(state_text, "## Last Scene Result", [f"- {event.summary}"])
    state_text = _append_list_item(state_text, "## Open Threads", f"- EVT-{next_scene}: {event.summary}")
    state_text = _replace_position_value(state_text, "Scene", next_scene)
    return state_text, next_scene


def reduce_player_visible_projection(player_visible_text: str, event: RuntimeEvent, response: dict) -> str:
    visible_lines = [
        f"- 玩家行动：{event.action or event.intent}",
        f"- GM 旁白：{response['gm_narration']}",
    ]
    if event.dialogue:
        visible_lines.append(f"- 对话：{event.dialogue}")
    for reaction in response["character_reactions"]:
        visible_lines.append(f"- {reaction['speaker']}：{reaction['text']}")
    player_visible_text = _replace_section(player_visible_text, "## What the Player / POV Character Knows", visible_lines)
    player_visible_text = _append_list_item(player_visible_text, "## Available Leads", f"- EVT-{response['scene_id']}")
    return player_visible_text


def build_reducer_registry() -> tuple[dict[str, Callable], dict[str, Callable]]:
    return (
        {
            "advance_scene_state": reduce_state_advance_scene,
        },
        {
            "player_visible_projection": reduce_player_visible_projection,
        },
    )


def _next_scene_id(scene_id: str) -> str:
    match = re.fullmatch(r"C(\d{2})S(\d{2})", scene_id)
    if not match:
        return scene_id or "C01S02"
    chapter = int(match.group(1))
    scene = int(match.group(2)) + 1
    return f"C{chapter:02d}S{scene:02d}"


def _replace_position_value(text: str, field_name: str, value: str) -> str:
    pattern = re.compile(rf"(^-\s+{re.escape(field_name)}:\s*)(.+)$", re.MULTILINE)
    return pattern.sub(lambda match: match.group(1) + value, text, count=1)


def _replace_section(text: str, heading: str, new_lines: list[str]) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return text
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    replacement = [heading, ""] + new_lines
    return "\n".join(lines[:start] + replacement + [""] + lines[end:]).rstrip() + "\n"


def _append_list_item(text: str, heading: str, item: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        return text
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    section = lines[start:end]
    if item not in section:
        insert_at = end
        lines.insert(insert_at, item)
    return "\n".join(lines).rstrip() + "\n"
