"""Resource content builders for the 8-resource materialization.

Split out of the legacy monolithic ``card_migration.py``. Each ``_build_*_md``
function turns a slice of a :class:`CardIR` into the markdown body written
to one of the 8 canonical resource directories.
"""

from __future__ import annotations

from app.compat.tavern_card.card_recognition import _extract_character_book_full
from app.compat.tavern_card.ir_definition import CardIR, RuntimePlan

__all__ = [
    "_build_character_memory_md",
    "_build_notes_md",
    "_build_outline_md",
    "_build_state_md",
    "_build_variables_md",
    "_build_worldbook_md",
]


def _build_worldbook_md(card_ir: CardIR) -> str:
    """worldbook <- character_book entries + scenario rules."""
    lines: list[str] = ["# 世界书", ""]
    rules = card_ir.get("world_rules", [])
    if rules:
        lines += ["## 规则", ""]
        lines += [f"- {rule}" for rule in rules]
        lines.append("")
    book = card_ir.get("character_book") or {}
    # Pull full content for the worldbook body (the short first-line
    # summaries are already in `rules` above via card_ir["world_rules"]).
    full_entries = _extract_character_book_full(book) if isinstance(book, dict) else []
    if full_entries:
        lines += ["## 角色书条目", ""]
        for entry in full_entries:
            lines.append(f"### {entry['name']}")
            lines.append("")
            lines.append(entry["content"])
            lines.append("")
    return "\n".join(lines).strip()


def _build_character_memory_md(card_ir: CardIR) -> str:
    """character_memory <- personality + relationships (character-isolated)."""
    identity = card_ir.get("identity", {}) or {}
    name = str(identity.get("name") or "未命名角色")
    persona = str(identity.get("persona") or "")
    lines: list[str] = [f"# 人物记忆 — {name}", ""]
    if persona:
        lines += ["## 人设", "", persona, ""]
    relationships = card_ir.get("relationships", [])
    if relationships:
        lines += ["## 关系", ""]
        for rel in relationships:
            lines.append(f"- {rel.get('summary', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def _build_state_md(card_ir: CardIR, runtime_plan: RuntimePlan) -> str:
    """state <- first_mes (initial state)."""
    prompt_hints = card_ir.get("prompt_hints", {}) or {}
    opening = str(prompt_hints.get("opening") or "")
    identity = card_ir.get("identity", {}) or {}
    name = str(identity.get("name") or "未命名角色")
    persist = runtime_plan.get("persist_state", [])
    persist_text = ", ".join(persist) if persist else "无"
    lines: list[str] = ["# 当前状态", "", "## 位置", "", "- Chapter: 1", "- Scene: C01S01"]
    lines += [f"- POV: {name}", "", "## 当前情境", ""]
    if opening:
        lines += [opening, ""]
    else:
        lines.append("根据导入角色卡初始化故事运行时。")
        lines.append("")
    lines += ["## 活跃角色", "", f"- {name}: 已导入。", ""]
    lines += ["## 持久状态", "", f"- {persist_text}", ""]
    return "\n".join(lines).strip()


def _build_notes_md(card_ir: CardIR) -> str:
    """notes <- description + creator notes."""
    identity = card_ir.get("identity", {}) or {}
    name = str(identity.get("name") or "未命名角色")
    persona = str(identity.get("persona") or "")
    lines: list[str] = ["# 创作笔记", "", f"## 来源卡片 — {name}", ""]
    if persona:
        lines += ["### 描述", "", persona, ""]
    return "\n".join(lines).strip()


def _build_outline_md(card_ir: CardIR) -> str:
    """outline <- scenario-derived plot outline (if available).

    Only written when the card carries a non-empty scenario; otherwise the
    outline resource stays empty (the maintainer agent fills it later).
    """
    rules = card_ir.get("world_rules", [])
    if not rules:
        return ""
    identity = card_ir.get("identity", {}) or {}
    name = str(identity.get("name") or "未命名角色")
    lines: list[str] = [f"# 大纲 — {name}", "", "## 主线", ""]
    for rule in rules[:8]:
        lines.append(f"- {rule}")
    lines.append("")
    return "\n".join(lines).strip()


def _build_variables_md(card_ir: CardIR) -> str:
    """variables <- inferred state variables (front-end display, not AI-injected)."""
    variables = card_ir.get("state_variables", [])
    if not variables:
        return ""
    lines: list[str] = ["# 变量", "", "| 名称 | 来源 |", "| --- | --- |"]
    for var in variables:
        lines.append(f"| {var.get('name', '')} | {var.get('source', '')} |")
    lines.append("")
    return "\n".join(lines).strip()
