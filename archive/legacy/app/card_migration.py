from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_card_payload(input_path: str | Path) -> dict[str, Any]:
    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8-sig"))
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"name": path.stem, "description": text}


def _flatten_card_payload(card_payload: dict[str, Any]) -> dict[str, Any]:
    """兼容 SillyTavern v2/v3：字段可能嵌在 data 下，这里做浅合并。

    顶层字段优先级低于 data.*（v2/v3 规范以 data 为准），但顶层缺失时回退到顶层。
    """
    data = card_payload.get("data")
    if isinstance(data, dict):
        merged = dict(card_payload)
        merged.update({key: value for key, value in data.items() if value not in (None, "")})
        return merged
    return card_payload


def infer_card_ir(card_payload: dict[str, Any]) -> dict[str, Any]:
    card_payload = _flatten_card_payload(card_payload)
    name = str(card_payload.get("name") or card_payload.get("char_name") or "Unnamed Card")
    persona = str(card_payload.get("description") or card_payload.get("persona") or card_payload.get("char_persona") or "")
    scenario = str(card_payload.get("scenario") or card_payload.get("world_scenario") or "")
    first_mes = str(card_payload.get("first_mes") or card_payload.get("first_message") or "")
    mes_example = str(card_payload.get("mes_example") or card_payload.get("example_dialogue") or "")
    personality = str(card_payload.get("personality") or "")
    alt_greetings = card_payload.get("alternate_greetings")
    alt_greetings = [str(item) for item in alt_greetings] if isinstance(alt_greetings, list) else []
    worldbook_entries = _extract_character_book(card_payload.get("character_book"))

    combined_persona = "\n".join(part for part in [persona, personality] if part)

    visibility = {
        "public": [line.strip() for line in combined_persona.splitlines()[:6] if line.strip()],
        "hidden": [line.strip() for line in scenario.splitlines()[:6] if line.strip() and line.strip() not in combined_persona],
    }
    state_variables = _infer_state_variables("\n".join([combined_persona, scenario, mes_example]))
    triggers = _infer_triggers("\n".join([scenario, first_mes, mes_example] + worldbook_entries))
    relationships = _infer_relationships(combined_persona)
    world_rules = [line.strip() for line in scenario.splitlines()[:8] if line.strip()] + worldbook_entries[:8]

    return {
        "card_name": name,
        "identity": {
            "name": name,
            "persona": combined_persona,
        },
        "visibility": visibility,
        "world_rules": world_rules,
        "state_variables": state_variables,
        "triggers": triggers,
        "relationships": relationships,
        "prompt_hints": {
            "opening": first_mes,
            "examples": mes_example,
            "alternate_greetings": alt_greetings,
        },
    }


def _extract_character_book(character_book: Any) -> list[str]:
    """从 ST character_book / lorebook 抽取常驻设定条目（仅取文本内容）。"""
    if not isinstance(character_book, dict):
        return []
    entries = character_book.get("entries")
    result: list[str] = []
    iterable: list[Any] = []
    if isinstance(entries, list):
        iterable = entries
    elif isinstance(entries, dict):
        iterable = list(entries.values())
    for entry in iterable:
        if isinstance(entry, dict):
            content = str(entry.get("content") or "").strip()
            if content:
                result.append(content.splitlines()[0].strip())
    return result[:12]


def infer_runtime_plan(card_ir: dict[str, Any]) -> dict[str, Any]:
    variable_names = {item["name"] for item in card_ir.get("state_variables", [])}
    has_hidden = bool(card_ir.get("visibility", {}).get("hidden"))
    dynamic_markers = variable_names.intersection({"favorability", "quest", "time", "economy", "trust", "relationship"})
    mode = "rp" if has_hidden or dynamic_markers else "novel"
    prompt_only = mode == "novel" and not dynamic_markers
    evented_runtime = mode == "rp"
    return {
        "recommended_mode": mode,
        "prompt_only": prompt_only,
        "evented_runtime": evented_runtime,
        "needs_sub_agents": mode == "rp" and len(card_ir.get("relationships", [])) >= 2,
        "persist_state": sorted(variable_names),
        "mount_modules": _suggest_modules(mode, has_hidden),
        "reasoning": {
            "has_hidden_info": has_hidden,
            "dynamic_state_detected": sorted(dynamic_markers),
        },
    }


def materialize_story_from_card(story_root: str | Path, card_ir: dict[str, Any], runtime_plan: dict[str, Any]) -> dict[str, str]:
    root = Path(story_root)
    lore_dir = root / "lore"
    state_dir = root / "state"
    work_dir = root / "work"
    data_dir = root / "data"

    lore_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    premise = _build_premise(card_ir, runtime_plan)
    characters = _build_characters(card_ir)
    worldbook = _build_worldbook(card_ir)
    state = _build_state(card_ir, runtime_plan)
    visible = _build_player_visible(card_ir)

    paths = {
        "premise": str(write_text(lore_dir / "premise.md", premise)),
        "characters": str(write_text(lore_dir / "characters.md", characters)),
        "worldbook": str(write_text(lore_dir / "worldbook.md", worldbook)),
        "state": str(write_text(state_dir / "state.md", state)),
        "player_visible": str(write_text(state_dir / "player_visible.md", visible)),
        "card_ir": str(write_json(data_dir / "card_ir.json", card_ir)),
        "runtime_plan": str(write_json(data_dir / "runtime_plan.json", runtime_plan)),
    }
    return paths


def write_json(output_path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_text(output_path: str | Path, content: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def _build_premise(card_ir: dict[str, Any], runtime_plan: dict[str, Any]) -> str:
    return (
        f"# Premise\n\n"
        f"## Source Card\n\n- Name: {card_ir['card_name']}\n- Recommended Mode: {runtime_plan['recommended_mode']}\n\n"
        f"## Core Setup\n\n{card_ir['identity']['persona'] or '待补充设定'}\n"
    )


def _build_characters(card_ir: dict[str, Any]) -> str:
    lines = ["# Characters", "", f"## {card_ir['identity']['name']}", "", card_ir['identity']['persona'] or "待补充角色信息", ""]
    if card_ir.get("relationships"):
        lines.extend(["## Relationships", ""])
        for relation in card_ir["relationships"]:
            lines.append(f"- {relation['summary']}")
        lines.append("")
    return "\n".join(lines)


def _build_worldbook(card_ir: dict[str, Any]) -> str:
    lines = ["# Worldbook", ""]
    if card_ir.get("world_rules"):
        lines.append("## Rules")
        lines.append("")
        for rule in card_ir["world_rules"]:
            lines.append(f"- {rule}")
        lines.append("")
    return "\n".join(lines)


def _build_state(card_ir: dict[str, Any], runtime_plan: dict[str, Any]) -> str:
    vars_text = ", ".join(runtime_plan.get("persist_state", [])) or "none"
    hidden = card_ir.get("visibility", {}).get("hidden", [])
    hidden_text = "\n".join(f"- {item}" for item in hidden) or "- 无"
    return f"""# Current State

## Position

- Chapter: 1
- Scene: C01S01
- Time: 初始化
- Location: 待定
- POV: {card_ir['identity']['name']}

## Current Situation

根据导入角色卡初始化故事运行时。

## Active Characters

- {card_ir['identity']['name']}: 已导入。

## Character Knowledge

### {card_ir['identity']['name']}

Knows:
- 已知公开设定。

Does Not Know:
{hidden_text}

## Open Threads

- CARD-INIT: 根据 card_ir 初始化。\n- Persist State: {vars_text}

## Constraints

- 运行模式：{runtime_plan['recommended_mode']}

## Last Scene Result

- 完成卡片导入初始化。
"""


def _build_player_visible(card_ir: dict[str, Any]) -> str:
    public = card_ir.get("visibility", {}).get("public", [])
    public_text = "\n".join(f"- {item}" for item in public) or "- 暂无"
    return f"""# Player Visible State

## What the Player / POV Character Knows

{public_text}

## Available Leads

- CARD-INIT

## Hidden Information

此文件不包含隐藏设定。
"""


def _infer_state_variables(text: str) -> list[dict[str, str]]:
    keywords = {
        "好感": "favorability",
        "任务": "quest",
        "时间": "time",
        "金钱": "economy",
        "经济": "economy",
        "关系": "relationship",
        "trust": "trust",
        "favor": "favorability",
    }
    found = []
    lowered = text.lower()
    seen = set()
    for token, name in keywords.items():
        if token.lower() in lowered and name not in seen:
            seen.add(name)
            found.append({"name": name, "source": token})
    return found


def _infer_triggers(text: str) -> list[str]:
    triggers = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(keyword in stripped for keyword in ["如果", "当", " whenever ", " if "]):
            triggers.append(stripped)
    return triggers[:8]


def _infer_relationships(text: str) -> list[dict[str, str]]:
    relations = []
    for line in text.splitlines():
        stripped = line.strip("- *")
        if any(marker in stripped for marker in ["朋友", "敌人", "恋人", "搭档", "姐姐", "妹妹"]):
            relations.append({"summary": stripped})
    return relations[:8]


def _suggest_modules(mode: str, has_hidden: bool) -> list[str]:
    modules = ["core/identity", "core/knowledge_boundary"]
    if mode == "rp":
        modules.append("modes/rp")
    else:
        modules.append("modes/novel")
    if has_hidden:
        modules.append("output_contracts/state_update")
    return modules
