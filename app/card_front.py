from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import re
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrontScript:
    """对齐 SillyTavern「正则扩展」脚本：findRegex 抓变量，replaceString 是 HTML+JS 模板。"""

    name: str
    find_regex: str
    replace_string: str
    disabled: bool = False
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_front_scripts(scripts_dir: str | Path) -> list[FrontScript]:
    """从目录加载所有 ST 风格正则前端脚本（每个 .json 一个脚本）。"""
    directory = Path(scripts_dir)
    if not directory.exists():
        return []
    scripts: list[FrontScript] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue
        script = parse_front_script(payload, source_path=str(path))
        if script is not None:
            scripts.append(script)
    return scripts


def parse_front_script(payload: dict[str, Any], source_path: str | None = None) -> FrontScript | None:
    if not isinstance(payload, dict):
        return None
    find_regex = payload.get("findRegex")
    replace_string = payload.get("replaceString")
    if not isinstance(find_regex, str) or not find_regex:
        return None
    if not isinstance(replace_string, str):
        return None
    name = str(payload.get("scriptName") or payload.get("name") or (Path(source_path).stem if source_path else "front_script"))
    return FrontScript(
        name=name,
        find_regex=find_regex,
        replace_string=replace_string,
        disabled=bool(payload.get("disabled", False)),
        source_path=source_path,
        metadata={
            "markdownOnly": payload.get("markdownOnly"),
            "placement": payload.get("placement"),
        },
    )


def apply_front_script(text: str, script: FrontScript) -> tuple[str, int]:
    """对文本应用一个脚本，返回 (渲染后文本, 命中次数)。命中为 0 时文本不变。"""
    pattern = _compile_regex(script.find_regex)
    if pattern is None:
        return text, 0
    counter = {"n": 0}

    def _replace(match: re.Match) -> str:
        counter["n"] += 1
        return _substitute_dollars(script.replace_string, match)

    rendered = pattern.sub(_replace, text)
    return rendered, counter["n"]


def render_front_widgets(text: str, scripts: list[FrontScript]) -> dict[str, Any]:
    """对文本依次应用所有启用脚本，聚合渲染结果与命中信息。"""
    rendered = text
    script_reports: list[dict[str, Any]] = []
    total_matches = 0
    for script in scripts:
        if script.disabled:
            script_reports.append({"name": script.name, "disabled": True, "matched": 0})
            continue
        rendered, matched = apply_front_script(rendered, script)
        total_matches += matched
        script_reports.append({"name": script.name, "disabled": False, "matched": matched})
    return {
        "html": rendered,
        "scripts": script_reports,
        "total_matches": total_matches,
        "source_chars": len(text),
    }


def build_card_view(card_ir: dict[str, Any]) -> dict[str, Any]:
    """从 card_ir 构造一个前端友好的「角色卡」基础视图（已转义，安全展示）。"""
    if not isinstance(card_ir, dict):
        return {}
    identity = card_ir.get("identity", {}) if isinstance(card_ir.get("identity"), dict) else {}
    prompt_hints = card_ir.get("prompt_hints", {}) if isinstance(card_ir.get("prompt_hints"), dict) else {}
    name = str(card_ir.get("card_name") or identity.get("name") or "未命名角色")
    persona = str(identity.get("persona") or "")
    opening = str(prompt_hints.get("opening") or "")
    alternates = prompt_hints.get("alternate_greetings")
    alternates = [str(item) for item in alternates] if isinstance(alternates, list) else []
    world_rules = card_ir.get("world_rules")
    world_rules = [str(item) for item in world_rules] if isinstance(world_rules, list) else []
    return {
        "name": name,
        "persona": persona,
        "opening": opening,
        "alternate_greetings": alternates,
        "world_rules": world_rules,
    }


def render_card_view_html(card_view: dict[str, Any]) -> str:
    """把基础卡片视图渲染成安全 HTML（card_ir 字段一律转义）。"""
    if not card_view:
        return '<div class="card-empty">未发现角色卡（缺少 data/card_ir.json）。</div>'

    def esc(value: str) -> str:
        return html.escape(value).replace("\n", "<br/>")

    parts = ['<div class="card-view" style="border:1px solid #ddd;border-radius:12px;padding:16px;max-width:640px;">']
    parts.append(f'<h2 style="margin:0 0 8px 0;">🪪 {esc(card_view.get("name", ""))}</h2>')
    if card_view.get("persona"):
        parts.append(f'<div class="card-section"><b>人设</b><div>{esc(card_view["persona"])}</div></div>')
    if card_view.get("opening"):
        parts.append(f'<div class="card-section"><b>开场白</b><div>{esc(card_view["opening"])}</div></div>')
    if card_view.get("alternate_greetings"):
        items = "".join(f"<li>{esc(item)}</li>" for item in card_view["alternate_greetings"])
        parts.append(f'<div class="card-section"><b>备选开场白</b><ul>{items}</ul></div>')
    if card_view.get("world_rules"):
        items = "".join(f"<li>{esc(item)}</li>" for item in card_view["world_rules"])
        parts.append(f'<div class="card-section"><b>世界规则</b><ul>{items}</ul></div>')
    parts.append("</div>")
    return "".join(parts)


def _compile_regex(raw: str) -> re.Pattern | None:
    pattern = raw
    flags = 0
    # 兼容 ST 可能存储的 /pattern/flags 形式
    if len(raw) >= 2 and raw.startswith("/"):
        last = raw.rfind("/")
        if last > 0:
            body = raw[1:last]
            flag_str = raw[last + 1 :]
            flag_map = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}
            for ch in flag_str:
                flags |= flag_map.get(ch, 0)
            pattern = body
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def _substitute_dollars(template: str, match: re.Match) -> str:
    groups = match.groups()

    def _expand(token: re.Match) -> str:
        index = int(token.group(1))
        if index == 0:
            return match.group(0)
        if 1 <= index <= len(groups):
            return groups[index - 1] or ""
        return token.group(0)

    # \d+ 是贪婪的，因此 $12 不会被 $1 截断
    return re.sub(r"\$(\d+)", _expand, template)
