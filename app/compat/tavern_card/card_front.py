"""SillyTavern-style regex -> HTML front rendering (compat layer).

This is the **compat layer** port of the legacy ``card_front.py`` (archived at
``archive/legacy/app/card_front.py``). It implements the SillyTavern
"regex extension" front-rendering model used by RP mode:

* A :class:`FrontScript` carries a ``findRegex`` and a ``replaceString`` (an
  HTML/JS template with ``$1..$N`` placeholders for the regex capture groups).
* :func:`apply_front_script` substitutes every match of the script's regex
  with the template, expanding ``$1..$N`` from the match's capture groups.
* :func:`render_front_widgets` chains enabled scripts over a source text and
  reports per-script hit counts.
* :func:`build_card_view` + :func:`render_card_view_html` produce a safe,
  front-end-friendly card view from a ``card_ir`` dict (all card-derived
  strings are HTML-escaped).

Per ``docs/refactor_guide.md:27-29`` and decision D5, all SillyTavern naming
converges to ``app/compat/tavern_card/``. This module is one of the two
 sanctioned places where the SillyTavern regex-front model is implemented
(the other is ``card_migration.py``). The front-end RP view
(``web/src/views/RpView.tsx``) consumes the rendered HTML via an API route
that delegates here; it never references SillyTavern directly.

Per ``docs/refactor_guide.md:402-404``: the dynamic front (RP mode) renders
card-bound front scripts (regex -> html+css+js) and manages variables to
update the front dynamically.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "FrontScript",
    "apply_front_script",
    "build_card_view",
    "load_front_scripts",
    "parse_front_script",
    "render_card_view_html",
    "render_front_widgets",
]


@dataclass(frozen=True)
class FrontScript:
    """One SillyTavern "regex extension" front script.

    ``find_regex`` is applied to the source text; each match is replaced with
    ``replace_string`` (an HTML/JS template) after expanding ``$1..$N`` from
    the match's capture groups (``$0`` = whole match).

    Attributes:
        name:           Script display name.
        find_regex:     The regex pattern (may be ``/pat/flags`` form).
        replace_string: HTML/JS template with ``$1..$N`` placeholders.
        disabled:       When ``True``, :func:`render_front_widgets` skips it.
        source_path:    Path to the ``.json`` file the script was loaded from.
        metadata:       Extra fields from the source JSON (markdownOnly,
                        placement, etc.) — opaque to the renderer.
    """

    name: str
    find_regex: str
    replace_string: str
    disabled: bool = False
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_front_scripts(scripts_dir: str | Path) -> list[FrontScript]:
    """Load all ``.json`` front scripts from *scripts_dir* (sorted by name).

    Returns an empty list if the directory does not exist. Files that fail
    to parse as JSON or lack the required fields are silently skipped (a
    front-script dir is user-supplied content; one bad file must not break
    the whole render).
    """
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


def parse_front_script(
    payload: dict[str, Any], source_path: str | None = None
) -> FrontScript | None:
    """Parse one SillyTavern regex-script JSON payload into a :class:`FrontScript`.

    Returns ``None`` if *payload* is not a dict, or is missing a non-empty
    ``findRegex`` / ``replaceString``. The script name falls back to the
    source file stem, then to ``"front_script"``.
    """
    if not isinstance(payload, dict):
        return None
    find_regex = payload.get("findRegex")
    replace_string = payload.get("replaceString")
    if not isinstance(find_regex, str) or not find_regex:
        return None
    if not isinstance(replace_string, str):
        return None
    name = str(
        payload.get("scriptName")
        or payload.get("name")
        or (Path(source_path).stem if source_path else "front_script")
    )
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


def apply_front_script(source_text: str, script: FrontScript) -> tuple[str, int]:
    """Apply *script* to *source_text*; return ``(rendered_text, match_count)``.

    When the regex fails to compile, the text is returned unchanged with a
    zero count (a bad regex in one script must not abort the whole render).
    """
    pattern = _compile_regex(script.find_regex)
    if pattern is None:
        return source_text, 0
    counter = {"n": 0}

    def _replace(match: re.Match[str]) -> str:
        counter["n"] += 1
        return _substitute_dollars(script.replace_string, match)

    rendered = pattern.sub(_replace, source_text)
    return rendered, counter["n"]


def render_front_widgets(
    source_text: str, scripts: list[FrontScript]
) -> dict[str, Any]:
    """Chain all enabled *scripts* over *source_text*; return an aggregate report.

    The returned dict carries:

    * ``html``           — the fully rendered text after all enabled scripts.
    * ``scripts``        — per-script report (``{name, disabled, matched}``).
    * ``scripts_count``  — number of scripts applied (enabled ones).
    * ``total_matches``  — total regex matches across all enabled scripts.
    * ``source_chars``   — length of the input text (for diagnostics).
    """
    rendered = source_text
    script_reports: list[dict[str, Any]] = []
    total_matches = 0
    applied = 0
    for script in scripts:
        if script.disabled:
            script_reports.append({"name": script.name, "disabled": True, "matched": 0})
            continue
        rendered, matched = apply_front_script(rendered, script)
        total_matches += matched
        applied += 1
        script_reports.append({"name": script.name, "disabled": False, "matched": matched})
    return {
        "html": rendered,
        "scripts": script_reports,
        "scripts_count": applied,
        "total_matches": total_matches,
        "source_chars": len(source_text),
    }


def build_card_view(card_ir: dict[str, Any]) -> dict[str, Any]:
    """Build a front-end-friendly card view from a ``card_ir`` dict.

    All string fields are coerced to ``str`` and lists are filtered to
    strings — the result is safe to pass to :func:`render_card_view_html`
    (which HTML-escapes every value).
    """
    if not isinstance(card_ir, dict):
        return {}
    identity = card_ir.get("identity", {}) if isinstance(card_ir.get("identity"), dict) else {}
    prompt_hints = (
        card_ir.get("prompt_hints", {}) if isinstance(card_ir.get("prompt_hints"), dict) else {}
    )
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
    """Render a card view dict (from :func:`build_card_view`) as safe HTML.

    Every card-derived string is HTML-escaped; newlines become ``<br/>``.
    An empty/missing view yields a placeholder ``<div>``.
    """
    if not card_view:
        return '<div class="card-empty">未发现角色卡（缺少 card_ir 数据）。</div>'

    def esc(value: str) -> str:
        return html.escape(value).replace("\n", "<br/>")

    parts: list[str] = [
        '<div class="card-view" style="border:1px solid #ddd;border-radius:12px;padding:16px;max-width:640px;">'
    ]
    parts.append(f'<h2 style="margin:0 0 8px 0;">🪪 {esc(card_view.get("name", ""))}</h2>')
    if card_view.get("persona"):
        parts.append(
            f'<div class="card-section"><b>人设</b><div>{esc(card_view["persona"])}</div></div>'
        )
    if card_view.get("opening"):
        parts.append(
            f'<div class="card-section"><b>开场白</b><div>{esc(card_view["opening"])}</div></div>'
        )
    if card_view.get("alternate_greetings"):
        items = "".join(f"<li>{esc(item)}</li>" for item in card_view["alternate_greetings"])
        parts.append(f'<div class="card-section"><b>备选开场白</b><ul>{items}</ul></div>')
    if card_view.get("world_rules"):
        items = "".join(f"<li>{esc(item)}</li>" for item in card_view["world_rules"])
        parts.append(f'<div class="card-section"><b>世界规则</b><ul>{items}</ul></div>')
    parts.append("</div>")
    return "".join(parts)


# ── Internal helpers ────────────────────────────────────────────────────


def _compile_regex(raw: str) -> re.Pattern[str] | None:
    """Compile *raw*, tolerating SillyTavern's ``/pattern/flags`` form.

    Returns ``None`` if the pattern fails to compile (so a single bad regex
    does not abort the render). Recognised flags: ``i`` ``m`` ``s``.
    """
    pattern = raw
    flags = 0
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


def _substitute_dollars(template: str, match: re.Match[str]) -> str:
    r"""Expand ``$0..$N`` in *template* from *match*'s whole match / capture groups.

    ``$0`` = whole match, ``$1..$N`` = capture groups (1-indexed). Out-of-range
    indices are left as the literal ``$K`` token. ``\d+`` is greedy so ``$12``
    is not split into ``$1`` + ``"2"``.
    """
    groups = match.groups()

    def _expand(token: re.Match[str]) -> str:
        index = int(token.group(1))
        if index == 0:
            return match.group(0)
        if 1 <= index <= len(groups):
            return groups[index - 1] or ""
        return token.group(0)

    return re.sub(r"\$(\d+)", _expand, template)
