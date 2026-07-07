from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.card_migration import infer_card_ir, infer_runtime_plan, materialize_story_from_card


TAVERN_MARKERS = ("first_mes", "char_name", "mes_example", "char_persona", "first_message", "alternate_greetings", "character_book", "personality")
TAVERN_SPECS = ("chara_card_v2", "chara_card_v3")


def detect_source_kind(input_path: str | Path, payload: dict[str, Any] | None = None) -> str:
    """检测导入来源类型，决定走哪条管线。

    返回值：
    - "tavern_card"：酒馆角色卡（专用管线）
    - "generic_json"：普通 JSON 设定（通用管线）
    - "screenplay"：剧本/对白脚本（通用管线，剧本子类型）
    - "novel"：小说全文（通用管线，小说子类型）
    - "setting"：世界观/设定集 Markdown 或纯文本（通用管线）
    """
    path = Path(input_path)
    suffix = path.suffix.lower()

    if payload is not None and _looks_like_tavern(payload):
        return "tavern_card"
    if suffix == ".json":
        if isinstance(payload, dict) and _looks_like_tavern(payload):
            return "tavern_card"
        return "generic_json"

    text = _safe_read_text(path)
    lowered = text.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        if _looks_like_screenplay(text):
            return "screenplay"
        if _looks_like_novel(text):
            return "novel"
        return "setting"
    if "coc" in lowered or "克苏鲁" in text or "调查员" in text:
        # 专用 COC 管线尚未实现 → 降级到通用 screenplay/setting
        return "screenplay" if _looks_like_screenplay(text) else "setting"
    return "setting"


def run_import(story_root: str | Path, input_path: str | Path) -> dict[str, Any]:
    """通用导入入口：分发到酒馆专用管线或通用管线，统一收敛到同一 workspace IR。"""
    path = Path(input_path)
    payload = _load_payload(path)
    kind = detect_source_kind(path, payload if isinstance(payload, dict) else None)

    if kind == "tavern_card":
        card_ir = infer_card_ir(payload)
        pipeline = "tavern"
    else:
        card_ir = build_generic_card_ir(path, payload, kind)
        pipeline = "generic"

    runtime_plan = infer_runtime_plan(card_ir)
    paths = materialize_story_from_card(story_root, card_ir, runtime_plan)
    return {
        "pipeline": pipeline,
        "source_kind": kind,
        "card_name": card_ir.get("card_name", ""),
        "paths": paths,
    }


def build_generic_card_ir(input_path: str | Path, payload: Any, kind: str) -> dict[str, Any]:
    """通用管线：尽力从任意剧本/设定/小说抽取 card_ir 兼容结构。

    缺少专用管线时，所有非酒馆来源都收敛到这里，保证下游一致、能跑。
    """
    path = Path(input_path)
    if isinstance(payload, dict):
        name = str(payload.get("name") or payload.get("title") or path.stem)
        persona = str(payload.get("description") or payload.get("persona") or payload.get("summary") or "")
        scenario = str(payload.get("scenario") or payload.get("world") or payload.get("setting") or "")
        first_mes = str(payload.get("first_mes") or payload.get("opening") or "")
        body = "\n".join(part for part in [persona, scenario, first_mes] if part)
    else:
        text = str(payload or "")
        name = _extract_title(text) or path.stem
        body = text
        persona, scenario, first_mes = _split_generic_text(text, kind)

    characters = _extract_characters(body)
    world_rules = _extract_world_rules(body)
    opening = first_mes or _first_paragraph(body)

    combined_persona = persona or _first_paragraph(body)
    visibility = {
        "public": [line.strip() for line in combined_persona.splitlines()[:6] if line.strip()],
        "hidden": [line.strip() for line in scenario.splitlines()[:6] if line.strip() and line.strip() not in combined_persona],
    }
    return {
        "card_name": name,
        "identity": {"name": name, "persona": combined_persona},
        "visibility": visibility,
        "world_rules": world_rules,
        "state_variables": _generic_state_variables(body),
        "triggers": _generic_triggers(body),
        "relationships": [{"summary": item} for item in characters[1:7]],
        "prompt_hints": {
            "opening": opening,
            "examples": "",
            "alternate_greetings": [],
            "source_kind": kind,
            "characters": characters[:8],
        },
    }


# --- detection helpers ---

def _looks_like_tavern(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if str(payload.get("spec", "")).lower() in TAVERN_SPECS:
        return True
    data = payload.get("data")
    fields = payload
    if isinstance(data, dict):
        fields = {**payload, **data}
    # first_mes/first_message 是聊天卡的强特征单信号
    if "first_mes" in fields or "first_message" in fields:
        return True
    return sum(1 for marker in TAVERN_MARKERS if marker in fields) >= 2


def _looks_like_screenplay(text: str) -> bool:
    # 角色名带冒号的对白行（中文/英文冒号），或场景标记
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    dialogue_lines = sum(1 for line in lines if re.match(r"^[\w一-龥·\- ]{1,12}[：:]", line))
    scene_markers = sum(1 for line in lines if re.match(r"^(场景|幕|第.{1,3}场|INT\.|EXT\.|场\s*\d)", line, re.IGNORECASE))
    return dialogue_lines >= max(3, len(lines) // 4) or scene_markers >= 2


def _looks_like_novel(text: str) -> bool:
    # 长段落、章节标记、引号对白多 → 小说
    has_chapter = bool(re.search(r"(^|\n)\s*第[一-龥\d]{1,8}[章回]", text))
    long_paragraphs = sum(1 for para in text.split("\n\n") if len(para.strip()) > 120)
    return has_chapter or long_paragraphs >= 2


# --- extraction helpers ---

def _split_generic_text(text: str, kind: str) -> tuple[str, str, str]:
    paragraphs = [para.strip() for para in re.split(r"\n\s*\n", text) if para.strip()]
    # persona 取首个非标题正文段
    persona = _first_paragraph(text)
    scenario = "\n".join(paragraphs[1:3]) if len(paragraphs) > 1 else ""
    first_mes = ""
    if kind == "screenplay":
        for line in text.splitlines():
            if re.match(r"^[\w一-龥·\- ]{1,12}[：:]", line.strip()):
                first_mes = line.strip()
                break
    return persona, scenario, first_mes


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("# ").strip()
        if stripped.startswith(("标题：", "标题:", "Title:", "title:")):
            return stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
    return ""


def _extract_characters(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^[-*]?\s*([\w一-龥·]{1,12})[：:]", stripped)
        if match:
            name = match.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _extract_world_rules(text: str) -> list[str]:
    rules: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*", "•")) and len(stripped) > 2:
            rules.append(stripped.lstrip("-*• ").strip())
        elif re.match(r"^规则[：:]", stripped) or re.match(r"^设定[：:]", stripped):
            rules.append(stripped)
    return rules[:8]


def _first_paragraph(text: str) -> str:
    for para in re.split(r"\n\s*\n", text):
        stripped = para.strip()
        if not stripped:
            continue
        # 跳过纯标题段（如 "# 标题"），优先取正文
        non_heading = "\n".join(line for line in stripped.splitlines() if not line.strip().startswith("#")).strip()
        if non_heading:
            return non_heading[:500]
    return text.strip()[:500]


def _generic_state_variables(text: str) -> list[dict[str, str]]:
    from app.card_migration import _infer_state_variables

    return _infer_state_variables(text)


def _generic_triggers(text: str) -> list[str]:
    from app.card_migration import _infer_triggers

    return _infer_triggers(text)


def _load_payload(path: Path) -> Any:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            return {}
    return _safe_read_text(path)


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
