"""Extract 文风 / jailbreak sections from a preset -> prompt fragments (compat layer).

Per ``docs/refactor_guide.md:29`` the system "允许从 sillytavern 的预设提取
用于 agent 的能力 (文风/jailbreak 等)". With the skill abstraction removed
(a skill IS an agent), extraction is a **pure function of the compat
layer**: it takes a raw SillyTavern preset (JSON, YAML, or markdown with
embedded sections) and returns :class:`PromptFragment` objects — plain
(kind, text) carriers a caller can inject into an agent's prompt (e.g.
as ``head`` / ``tail``).

Pipeline:

1. :func:`normalize_preset_to_markdown` — accept JSON/YAML/markdown preset
   payloads and reduce to a markdown string with ``##``-level sections.
2. :func:`extract_preset_fragments` — scan the markdown for style /
   jailbreak sections and wrap each as a :class:`PromptFragment`.

This module depends on no other app layer (in particular, NOT on
``app.agents``) — it is pure preset-format parsing.

Note: folding extracted fragments into a materialized agent's
``head`` / ``tail`` during card migration is deliberately NOT done here —
extraction stays a pure function; composition is the caller's decision.

Per decision D5, all SillyTavern naming converges to
``app/compat/tavern_card/``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import yaml

__all__ = [
    "PromptFragment",
    "extract_preset_fragments",
    "normalize_preset_to_markdown",
]


@dataclass(frozen=True)
class PromptFragment:
    """One extracted preset fragment.

    Attributes:
        kind: ``"style"`` (文风/写作风格) or ``"jailbreak"`` (越狱).
        text: The section body — the directive text to inject into a
              prompt.
    """

    kind: str
    text: str


# Markdown section headers recognised as extractable. The header text is
# matched case-insensitively after stripping whitespace; both Chinese
# (文风) and English (jailbreak / Jailbreak) forms are accepted.
_PRESET_SECTION_RE: re.Pattern[str] = re.compile(
    r"^##\s+(.+?)\s*$",
    re.MULTILINE,
)
_STYLE_HEADERS: frozenset[str] = frozenset({"文风", "style", "写作风格"})
_JAILBREAK_HEADERS: frozenset[str] = frozenset({"jailbreak", "越狱"})


def _split_sections(preset_text: str) -> list[tuple[str, str]]:
    """Split *preset_text* into ``[(header, body), ...]`` for ``##``-level sections.

    The body of each section runs from the line after the header to the line
    before the next ``##`` header (or end of text). ``#``-level (top-level)
    and ``###``+ (deeper) headers are NOT section boundaries here — only
    ``##`` sections are extractable sources.
    """
    sections: list[tuple[str, str]] = []
    matches = list(_PRESET_SECTION_RE.finditer(preset_text))
    for i, match in enumerate(matches):
        header = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(preset_text)
        body = preset_text[body_start:body_end].strip()
        sections.append((header, body))
    return sections

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

    The output is consumed by :func:`extract_preset_fragments`, which
    scans for ``##``-level sections whose header matches a known
    style/jailbreak label.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return _dict_to_markdown(raw)
    if isinstance(raw, list):
        return _list_to_markdown(raw)
    # Fallback: coerce to string so the seam still has something to scan.
    return str(raw)


def extract_preset_fragments(
    preset_text: str | dict[str, Any] | list[Any],
) -> list[PromptFragment]:
    """Extract 文风 / jailbreak fragments from a preset.

    Accepts the same payload shapes as :func:`normalize_preset_to_markdown`
    (markdown string, JSON/YAML dict, or list of section dicts). The
    payload is normalized to markdown, then every ``##`` section whose
    header matches a known style/jailbreak label becomes a
    :class:`PromptFragment`.

    Returns an empty list when no style/jailbreak sections are found.
    """
    markdown = normalize_preset_to_markdown(preset_text)
    fragments: list[PromptFragment] = []
    for header, body in _split_sections(markdown):
        header_lower = header.lower()
        if header_lower in _STYLE_HEADERS or header in _STYLE_HEADERS:
            fragments.append(PromptFragment(kind="style", text=body))
        elif header_lower in _JAILBREAK_HEADERS or header in _JAILBREAK_HEADERS:
            fragments.append(PromptFragment(kind="jailbreak", text=body))
    return fragments


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
