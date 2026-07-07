"""Extract 文风 / jailbreak sections from a preset -> agent Skills (compat layer).

This is the **compat layer** half of preset skill extraction. Per
``docs/refactor_guide.md:29`` the system "允许从 sillytavern 的预设提取用于
agent 的 skill (文风/jailbreak 等)". The agent-layer seam
(:func:`app.agents.skills.extract_skills_from_preset`) lives in
``app/agents/skills.py`` and wraps extracted text as :class:`Skill` objects
with stable, content-hashed names. This module is the **parser** half: it
takes a raw SillyTavern preset (which may be JSON, YAML, or markdown with
embedded sections) and reduces it to the canonical markdown-section form
that the agent-layer seam already consumes.

Pipeline:

1. :func:`normalize_preset_to_markdown` — accept JSON/YAML/markdown preset
   payloads and reduce to a markdown string with ``##``-level sections.
2. :func:`extract_preset_skills` — call the normalizer, then delegate to
   :func:`app.agents.skills.extract_skills_from_preset` to produce
   ``list[Skill]``.

The split keeps SillyTavern preset-format knowledge in the compat layer
(here) and the Skill abstraction in the agent layer (``app/agents/skills.py``)
— the only import direction is ``compat -> agents``, never the reverse.

Per decision D5, all SillyTavern naming converges to
``app/compat/tavern_card/``. The agent-layer seam mentions "SillyTavern
preset" in its docstring as the authoritative reference
(``docs/refactor_guide.md:29``); that mention is intentional and points
back here.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from app.agents.skills import Skill
from app.agents.skills import extract_skills_from_preset as _seam_extract

__all__ = [
    "extract_preset_skills",
    "normalize_preset_to_markdown",
]

# Recognised SillyTavern preset "section" keys when the preset is a JSON/YAML
# mapping (the values are usually strings or lists of strings). Matched
# case-insensitively after stripping whitespace; both Chinese (文风) and
# English (jailbreak / Jailbreak) forms are accepted.
_PRESET_SECTION_KEYS: tuple[str, ...] = (
    "文风",
    "style",
    "写作风格",
    "jailbreak",
    "越狱",
    "system",
    "system_prompt",
    "prompt",
)


def normalize_preset_to_markdown(raw: str | dict[str, Any] | list[Any]) -> str:
    """Reduce a preset payload to markdown with ``##``-level sections.

    Accepts:

    * ``str``   — assumed to already be markdown (returned as-is).
    * ``dict``  — JSON/YAML preset mapping; each recognised section key
                  becomes a ``## <key>`` header with the value as the body.
                  Unrecognised keys are dropped (not extracted as skills).
    * ``list``  — a list of ``{name, content}`` / ``{title, text}`` dicts;
                  each becomes a ``## <name>`` section.

    The output is consumed by
    :func:`app.agents.skills.extract_skills_from_preset`, which scans for
    ``##``-level sections whose header matches a known style/jailbreak label.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return _dict_to_markdown(raw)
    if isinstance(raw, list):
        return _list_to_markdown(raw)
    # Fallback: coerce to string so the seam still has something to scan.
    return str(raw)


def extract_preset_skills(preset_text: str | dict[str, Any] | list[Any]) -> list[Skill]:
    """Extract 文风 / jailbreak skills from a preset.

    Accepts the same payload shapes as :func:`normalize_preset_to_markdown`
    (markdown string, JSON/YAML dict, or list of section dicts). The
    payload is normalized to markdown, then
    :func:`app.agents.skills.extract_skills_from_preset` wraps each matching
    ``##`` section as a :class:`~app.agents.skills.PresetStyleSkill` with a
    stable, content-hashed name (``style_<hash8>`` or
    ``jailbreak_<hash8>``).

    Returns an empty list when no style/jailbreak sections are found.
    """
    markdown = normalize_preset_to_markdown(preset_text)
    return _seam_extract(markdown)


# ── Internal: payload -> markdown ────────────────────────────────────────


def _dict_to_markdown(payload: dict[str, Any]) -> str:
    """Convert a JSON/YAML preset dict to ``##``-level markdown sections.

    Recognised section keys (see :data:`_PRESET_SECTION_KEYS`) become
    sections. Values may be strings or lists of strings (joined by
    newlines). The original key text is used as the header (so Chinese
    "文风" is preserved exactly — the agent-layer seam matches both Chinese
    and English forms).
    """
    parts: list[str] = []
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        if not _is_section_key(key):
            continue
        body = _value_to_body(value)
        if not body:
            continue
        parts.append(f"## {key}\n\n{body}")
    return "\n\n".join(parts)


def _list_to_markdown(items: list[Any]) -> str:
    """Convert a list-of-sections preset to ``##``-level markdown.

    Each item is expected to be a dict with a ``name`` / ``title`` key and
    a ``content`` / ``text`` / ``body`` key. Items without a recognised
    name are skipped.
    """
    parts: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").strip()
        if not name:
            continue
        body = _value_to_body(
            item.get("content") or item.get("text") or item.get("body") or ""
        )
        if not body:
            continue
        parts.append(f"## {name}\n\n{body}")
    return "\n\n".join(parts)


def _value_to_body(value: Any) -> str:
    """Coerce a preset section value (str / list / dict) to a markdown body."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            if isinstance(item, str):
                lines.append(item)
            else:
                # Nested non-string items: JSON-encode for traceability.
                lines.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(lines).strip()
    if isinstance(value, dict):
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
    if value is None:
        return ""
    return str(value).strip()


def _is_section_key(key: str) -> bool:
    """Return ``True`` if *key* matches a known preset section label.

    Comparison is case-insensitive after stripping whitespace for the
    English forms; the Chinese forms are matched exactly (case is not
    meaningful for CJK).
    """
    stripped = key.strip()
    lower = stripped.lower()
    for candidate in _PRESET_SECTION_KEYS:
        if stripped == candidate or lower == candidate.lower():
            return True
    return False
