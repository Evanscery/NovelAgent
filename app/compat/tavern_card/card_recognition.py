"""Tavern card loading, recognition, and IR/plan inference.

Split out of the legacy monolithic ``card_migration.py``. Provides:

* :func:`load_card_payload` — read a card JSON (or fallback to text).
* :func:`is_recognized_card` — dispatch guard for ``/api/import``.
* :func:`infer_card_ir` — flatten v2/v3 nesting into a :class:`CardIR`.
* :func:`infer_runtime_plan` — derive a :class:`RuntimePlan` from the IR.
* Heuristic helpers (``_flatten_card_payload``, ``_extract_character_book``,
  ``_extract_character_book_full``, ``_infer_state_variables``,
  ``_infer_triggers``, ``_infer_relationships``, ``_suggest_modules``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.compat.tavern_card.ir_definition import CardIR, RuntimePlan

__all__ = [
    "infer_card_ir",
    "infer_runtime_plan",
    "is_recognized_card",
    "load_card_payload",
]


# ── 1. Load ──────────────────────────────────────────────────────────────


def load_card_payload(input_path: str | Path) -> dict[str, Any]:
    """Read a card file from *input_path* and return its raw dict payload.

    ``.json`` files are parsed as JSON (utf-8-sig tolerant). Any other
    extension is treated as plain text and wrapped in a minimal
    ``{name, description}`` payload so the downstream IR step still has
    something to work with.
    """
    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {"data": data}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"name": path.stem, "description": text}


# ── Recognition (used by /api/import to dispatch) ────────────────────────


def is_recognized_card(payload: dict[str, Any]) -> bool:
    """Return ``True`` if *payload* looks like a tavern card (v2 or v3).

    Checks for the canonical SillyTavern v2/v3 card fields. The check is
    intentionally permissive (any one strong signal suffices) so cards with
    partial data still route to the card-migration pipeline rather than
    being rejected as "not a recognized card format".
    """
    if not isinstance(payload, dict):
        return False
    flat = _flatten_card_payload(payload)
    strong_signals = ("name", "description", "personality", "scenario", "first_mes", "mes_example")
    has_strong = any(isinstance(flat.get(k), str) and flat.get(k) for k in strong_signals)
    has_book = isinstance(flat.get("character_book"), dict)
    has_spec = str(flat.get("spec") or "").lower() in {"chara_card_v2", "chara_card_v3"}
    return bool(has_strong or has_book or has_spec)


# ── 2. Infer IR ──────────────────────────────────────────────────────────


def infer_card_ir(card_payload: dict[str, Any]) -> CardIR:
    """Flatten a v2/v3 card payload into a :class:`CardIR` intermediate.

    SillyTavern v2/v3 cards nest the canonical fields under a ``data`` key;
    this function merges that nesting shallowly (``data.*`` wins over
    top-level for non-empty values) before extracting the IR.
    """
    flat = _flatten_card_payload(card_payload)
    name = str(flat.get("name") or flat.get("char_name") or "Unnamed Card")
    persona = str(
        flat.get("description") or flat.get("persona") or flat.get("char_persona") or ""
    )
    scenario = str(flat.get("scenario") or flat.get("world_scenario") or "")
    first_mes = str(flat.get("first_mes") or flat.get("first_message") or "")
    mes_example = str(flat.get("mes_example") or flat.get("example_dialogue") or "")
    personality = str(flat.get("personality") or "")
    alt_greetings = flat.get("alternate_greetings")
    alt_greetings = (
        [str(item) for item in alt_greetings] if isinstance(alt_greetings, list) else []
    )
    character_book = flat.get("character_book")
    if not isinstance(character_book, dict):
        character_book = {}
    worldbook_entries = _extract_character_book(character_book)

    combined_persona = "\n".join(part for part in [persona, personality] if part)

    visibility: dict[str, list[str]] = {
        "public": [line.strip() for line in combined_persona.splitlines()[:6] if line.strip()],
        "hidden": [
            line.strip()
            for line in scenario.splitlines()[:6]
            if line.strip() and line.strip() not in combined_persona
        ],
    }
    state_variables = _infer_state_variables(
        "\n".join([combined_persona, scenario, mes_example])
    )
    triggers = _infer_triggers(
        "\n".join([scenario, first_mes, mes_example, *worldbook_entries])
    )
    relationships = _infer_relationships(combined_persona)
    world_rules = (
        [line.strip() for line in scenario.splitlines()[:8] if line.strip()]
        + worldbook_entries[:8]
    )

    front_scripts_raw = flat.get("front_scripts")
    front_scripts = (
        [s for s in front_scripts_raw if isinstance(s, dict)]
        if isinstance(front_scripts_raw, list)
        else []
    )

    return CardIR(
        card_name=name,
        identity={"name": name, "persona": combined_persona},
        visibility=visibility,
        world_rules=world_rules,
        state_variables=state_variables,
        triggers=triggers,
        relationships=relationships,
        prompt_hints={
            "opening": first_mes,
            "examples": mes_example,
            "alternate_greetings": alt_greetings,
        },
        character_book=character_book,
        front_scripts=front_scripts,
    )


# ── 3. Runtime plan ──────────────────────────────────────────────────────


def infer_runtime_plan(card_ir: CardIR) -> RuntimePlan:
    """Derive a :class:`RuntimePlan` from *card_ir*.

    The plan records the recommended mode (``novel`` vs ``rp``), which
    state variables to persist, and which prompt modules to mount. The
    director / maintainer agents may still override this at runtime.
    """
    variable_names = {item["name"] for item in card_ir.get("state_variables", [])}
    has_hidden = bool(card_ir.get("visibility", {}).get("hidden"))
    dynamic_markers = variable_names.intersection(
        {"favorability", "quest", "time", "economy", "trust", "relationship"}
    )
    mode = "rp" if has_hidden or dynamic_markers else "novel"
    prompt_only = mode == "novel" and not dynamic_markers
    evented_runtime = mode == "rp"
    return RuntimePlan(
        recommended_mode=mode,
        prompt_only=prompt_only,
        evented_runtime=evented_runtime,
        needs_sub_agents=mode == "rp" and len(card_ir.get("relationships", [])) >= 2,
        persist_state=sorted(variable_names),
        mount_modules=_suggest_modules(mode, has_hidden),
        reasoning={
            "has_hidden_info": has_hidden,
            "dynamic_state_detected": sorted(dynamic_markers),
        },
    )


# ── Card-flattening + heuristic helpers (ported from legacy impl) ────────


def _flatten_card_payload(card_payload: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge a v2/v3 card's ``data`` nesting onto the top level.

    SillyTavern v2/v3 cards store the canonical fields under ``data``; the
    top level carries ``spec`` / ``spec_version``. ``data.*`` wins over the
    top level for non-empty values.
    """
    data = card_payload.get("data")
    if isinstance(data, dict):
        merged = dict(card_payload)
        merged.update({k: v for k, v in data.items() if v not in (None, "")})
        return merged
    return card_payload


def _extract_character_book(character_book: Any) -> list[str]:
    """Extract short (first-line) summaries from a character_book / lorebook.

    Used for the worldbook rules list and the runtime-plan trigger scan.
    """
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


def _extract_character_book_full(character_book: dict[str, Any]) -> list[dict[str, str]]:
    """Extract full-content entries from a character_book for the worldbook body.

    Returns ``[{name, content}, ...]`` with ``name`` falling back to a
    1-based index when the entry has no ``comment`` / ``name`` field.
    """
    entries = character_book.get("entries")
    out: list[dict[str, str]] = []
    iterable: list[Any] = []
    if isinstance(entries, list):
        iterable = entries
    elif isinstance(entries, dict):
        iterable = list(entries.values())
    for i, entry in enumerate(iterable, start=1):
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        name = str(entry.get("comment") or entry.get("name") or f"entry_{i}")
        out.append({"name": name, "content": content})
    return out[:24]


def _infer_state_variables(text: str) -> list[dict[str, str]]:
    """Heuristic: detect known variable tokens (favorability/quest/...) in *text*."""
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
    found: list[dict[str, str]] = []
    lowered = text.lower()
    seen: set[str] = set()
    for token, var_name in keywords.items():
        if token.lower() in lowered and var_name not in seen:
            seen.add(var_name)
            found.append({"name": var_name, "source": token})
    return found


def _infer_triggers(text: str) -> list[str]:
    """Heuristic: pull "if/when" lines as event triggers (capped at 8)."""
    triggers: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(keyword in stripped for keyword in ("如果", "当", " whenever ", " if ")):
            triggers.append(stripped)
    return triggers[:8]


def _infer_relationships(text: str) -> list[dict[str, str]]:
    """Heuristic: detect relationship markers (朋友/敌人/恋人/...) in *text*."""
    relations: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip("- *")
        if any(marker in stripped for marker in ("朋友", "敌人", "恋人", "搭档", "姐姐", "妹妹")):
            relations.append({"summary": stripped})
    return relations[:8]


def _suggest_modules(mode: str, has_hidden: bool) -> list[str]:
    """Suggest prompt modules to mount based on mode + hidden-info presence."""
    modules = ["core/identity", "core/knowledge_boundary"]
    modules.append("modes/rp" if mode == "rp" else "modes/novel")
    if has_hidden:
        modules.append("output_contracts/state_update")
    return modules
