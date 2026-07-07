from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


POSITION_FIELDS = ("Chapter", "Scene", "Time", "Location", "POV")


@dataclass(frozen=True)
class StoryPosition:
    chapter: int
    scene_id: str
    time_label: str
    location: str
    pov: str


def parse_story_position(text: str) -> StoryPosition:
    values = _extract_position_block(text)
    chapter_raw = values.get("Chapter", "0")
    scene_id = values.get("Scene", "")
    time_label = values.get("Time", "")
    location = values.get("Location", "")
    pov = values.get("POV", "")

    chapter = int(re.search(r"\d+", chapter_raw).group(0)) if re.search(r"\d+", chapter_raw) else 0
    return StoryPosition(
        chapter=chapter,
        scene_id=scene_id,
        time_label=time_label,
        location=location,
        pov=pov,
    )


def validate_story_progression(previous_text: str, current_text: str) -> None:
    previous = parse_story_position(previous_text)
    current = parse_story_position(current_text)

    if not current.scene_id:
        raise ValueError("state.md 缺少 Scene 字段，无法验证状态推进。")
    if current.chapter < previous.chapter:
        raise ValueError(f"章节倒退：{current.chapter} < {previous.chapter}")
    if current.chapter - previous.chapter > 1:
        raise ValueError(f"章节跳跃过大：{previous.chapter} -> {current.chapter}")
    if current.chapter == previous.chapter and current.scene_id == previous.scene_id:
        raise ValueError(f"场景未推进：仍然是 {current.scene_id}")


def set_story_position(text: str, chapter: int, scene_id: str) -> str:
    text = _replace_position_field(text, "Chapter", str(chapter))
    text = _replace_position_field(text, "Scene", scene_id)
    return text


def _extract_position_block(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_position = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "## Position":
            in_position = True
            continue
        if in_position and stripped.startswith("## "):
            break
        if in_position and stripped.startswith("-") and ":" in stripped:
            key, value = stripped[1:].split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _replace_position_field(text: str, field_name: str, value: str) -> str:
    pattern = re.compile(rf"(^-\s+{re.escape(field_name)}:\s*)(.+)$", re.MULTILINE)
    if not pattern.search(text):
        raise ValueError(f"state.md 缺少 Position 字段：{field_name}")
    return pattern.sub(lambda match: match.group(1) + value, text, count=1)
