from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import re
from pathlib import Path
from typing import Any


MAX_TARGET_LEN = 16


@dataclass(frozen=True)
class ParsedPlayerInput:
    mode: str
    raw_text: str
    intent: str
    target: str
    action: str
    dialogue: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_input_text(text: str) -> str:
    """把常见的畸形转义还原为真实换行，避免 target / body 被污染。

    live 验收发现：客户端可能把换行写成字面的 \\n 或反引号包裹的 n，
    导致字段抽取把整段文本当成 target。这里在解析前统一归一化。
    """
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\\n", "\n")
    normalized = re.sub(r"`+n`*", "\n", normalized)
    return normalized


def parse_player_input(text: str) -> ParsedPlayerInput:
    stripped = normalize_input_text(text).strip()
    fields = _extract_markdown_fields(stripped)
    body = fields.get("body", stripped)
    mode = fields.get("mode", "rp")
    target = _sanitize_target(fields.get("target", ""))

    dialogue = _extract_dialogue(body)
    action = _extract_action(body)
    intent = _infer_intent(body, dialogue=dialogue, action=action)
    if not target:
        target = _infer_target(body)

    return ParsedPlayerInput(
        mode=mode,
        raw_text=body,
        intent=intent,
        target=target,
        action=action,
        dialogue=dialogue,
        metadata={key: value for key, value in fields.items() if key not in {"body", "mode", "target"}},
    )


def load_player_input(path: str | Path) -> ParsedPlayerInput:
    return parse_player_input(Path(path).read_text(encoding="utf-8"))


def dump_player_input(parsed: ParsedPlayerInput, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_markdown_fields(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = text.splitlines()
    body_lines: list[str] = []
    field_pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_ -]*):\s*(.+)$")
    in_header = True
    for line in lines:
        if in_header:
            match = field_pattern.match(line.strip())
            if match:
                key, value = match.groups()
                result[key.strip().lower().replace(" ", "_")] = value.strip()
                continue
            if not line.strip():
                continue
            in_header = False
        body_lines.append(line)
    result["body"] = "\n".join(body_lines).strip() or text.strip()
    return result


def _extract_dialogue(text: str) -> str:
    quoted = re.findall(r"[“\"]([^”\"]+)[”\"]", text)
    if quoted:
        return " / ".join(part.strip() for part in quoted if part.strip())
    if text.startswith("说") or "对" in text and "说" in text:
        return text
    return ""


def _extract_action(text: str) -> str:
    action = re.sub(r"[“\"].*?[”\"]", "", text).strip()
    if action:
        return action
    return text.strip()


def _infer_intent(text: str, dialogue: str, action: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["查看", "观察", "inspect", "look"]):
        return "inspect"
    if dialogue:
        return "dialogue"
    if any(token in text for token in ["攻击", "出手", "刺", "砍", "劈", "射", "打", "strike", "attack"]):
        return "attack"
    if any(token in text for token in ["移动", "前往", "去", "walk", "move"]):
        return "move"
    if action:
        return "act"
    return "unknown"


def _infer_target(text: str) -> str:
    match = re.search(r"对([\w一-龥]{1,12})", text)
    if match:
        return _sanitize_target(match.group(1))
    match = re.search(r"去往?([\w一-龥]{1,12})", text)
    if match:
        return _sanitize_target(match.group(1))
    return ""


def _sanitize_target(target: str) -> str:
    """约束 target 边界：单行、去对话/标点、限长，避免整段文本污染 target。"""
    if not target:
        return ""
    first_line = target.splitlines()[0].strip()
    # 砍掉对话起始（出现引号/冒号即在此截断）
    first_line = re.split(r"[“\"：:]", first_line, maxsplit=1)[0].strip()
    # 只保留中英数字与少量连接符
    cleaned = re.sub(r"[^\w一-龥·\- ]", "", first_line).strip()
    if len(cleaned) > MAX_TARGET_LEN:
        cleaned = cleaned[:MAX_TARGET_LEN]
    return cleaned
