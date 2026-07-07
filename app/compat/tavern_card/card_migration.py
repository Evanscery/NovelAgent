"""Tavern card -> project (8-resource model) migration (compat layer).

This is the **compat layer** port of the legacy ``card_migration.py``
(archived at ``archive/legacy/app/card_migration.py``), adapted to the new
8-resource architecture (``app/data/resource_types.py``):

* **Legacy** mapped a card to ``lore/`` + ``state/`` + ``work/`` + ``data/``
  (the old flat workspace layout).
* **New** maps a card to the 8 canonical resource directories under
  ``resources/`` (outline / short_goal / state / variables / worldbook /
  facts / character_memory / notes), plus ``front/`` for the card's regex
  front scripts. This aligns with ``docs/refactor_guide.md:167`` (8 data
  instances) and decision D5 (ST naming converges to the compat layer).

Pipeline:

1. :func:`load_card_payload` — read the card JSON (or fallback to text).
2. :func:`infer_card_ir` — flatten v2/v3 nesting and produce an
   intermediate :class:`CardIR` (a typed dict) carrying the card's
   identity / world / state / prompt-hint fields.
3. :func:`infer_runtime_plan` — derive a :class:`RuntimePlan` from the IR
   (recommended mode, persisted state vars, suggested modules).
4. :func:`materialize_project_from_card` — write the 8 resource dirs with
   card-derived content + the ``front/`` scripts, and return a manifest of
   what was created.

The 8-resource mapping (per the task spec and guide:167):

* ``worldbook``      <- character_book entries + scenario rules
* ``character_memory``<- personality + inferred relationships (character-isolated)
* ``state``          <- first_mes (initial state)
* ``notes``          <- description + creator notes
* ``outline``        <- scenario-derived plot outline (when available)
* ``variables``      <- inferred state variables (favorability / quest / ...)
* ``facts``          <- (left empty — facts come from web search at runtime)
* ``short_goal``     <- (left empty — maintainer agent fills per round)

Per ``docs/refactor_guide.md:27-29`` and decision D5, all SillyTavern naming
converges here. The ``/api/import`` route delegates to this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

__all__ = [
    "CardIR",
    "RuntimePlan",
    "infer_card_ir",
    "infer_runtime_plan",
    "is_recognized_card",
    "load_card_payload",
    "materialize_project_from_card",
]

# ── Typed dicts (IR + runtime plan) ──────────────────────────────────────


class CardIR(TypedDict, total=False):
    """Intermediate representation of a parsed tavern card.

    Produced by :func:`infer_card_ir`; consumed by
    :func:`infer_runtime_plan` and :func:`materialize_project_from_card`.
    All fields are optional (a card may omit any of them).
    """

    card_name: str
    identity: dict[str, Any]
    visibility: dict[str, list[str]]
    world_rules: list[str]
    state_variables: list[dict[str, str]]
    triggers: list[str]
    relationships: list[dict[str, str]]
    prompt_hints: dict[str, Any]
    character_book: dict[str, Any]
    front_scripts: list[dict[str, Any]]


class RuntimePlan(TypedDict, total=False):
    """How a :class:`CardIR` maps onto the runtime (mode + persisted state)."""

    recommended_mode: str
    prompt_only: bool
    evented_runtime: bool
    needs_sub_agents: bool
    persist_state: list[str]
    mount_modules: list[str]
    reasoning: dict[str, Any]


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


# ── 4. Materialize → 8 resources ─────────────────────────────────────────


@dataclass(frozen=True)
class MaterializeResult:
    """Outcome of :func:`materialize_project_from_card`.

    ``resources_created`` lists the resource type names that received
    card-derived content (a subset of the 8 canonical types — the rest are
    scaffolded empty by :func:`scaffold_project` and not listed here).
    ``front_scripts_written`` is the count of front scripts copied to
    ``front/``. ``paths`` maps a logical name to the file path written.
    """

    project_id: str
    project_path: str
    resources_created: list[str] = field(default_factory=list)
    front_scripts_written: int = 0
    paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_path": self.project_path,
            "resources_created": list(self.resources_created),
            "front_scripts_written": self.front_scripts_written,
            "paths": dict(self.paths),
        }


def materialize_project_from_card(
    project_root: str | Path,
    card_ir: CardIR,
    runtime_plan: RuntimePlan,
) -> MaterializeResult:
    """Write card-derived content into the 8 resource dirs of *project_root*.

    Pre-condition: *project_root* must already be a scaffolded project (i.e.
    :func:`app.project_init.scaffold_project` has been called). This
    function only fills in content; it does NOT create the project or the
    resource directories themselves.

    Mapping (see module docstring):

    * ``worldbook``        <- character_book + scenario rules
    * ``character_memory`` <- personality + relationships
    * ``state``            <- first_mes (initial state)
    * ``notes``            <- description + creator notes
    * ``outline``          <- scenario-derived plot outline (if non-empty)
    * ``variables``        <- inferred state variables
    * ``facts``            <- (left empty — populated at runtime)
    * ``short_goal``       <- (left empty — maintainer fills per round)

    The card's front scripts (regex) are written to ``front/``.
    """
    root = Path(project_root)
    resources_dir = root / "resources"
    front_dir = root / "front"
    front_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, str] = {}
    created: list[str] = []

    # worldbook <- character_book + scenario rules
    worldbook_md = _build_worldbook_md(card_ir)
    if worldbook_md.strip():
        p = _write_resource_file(resources_dir / "worldbook" / "content.md", worldbook_md)
        paths["worldbook"] = str(p)
        created.append("worldbook")

    # character_memory <- personality + relationships (character-isolated)
    memory_md = _build_character_memory_md(card_ir)
    if memory_md.strip():
        p = _write_resource_file(
            resources_dir / "character_memory" / "content.md", memory_md
        )
        paths["character_memory"] = str(p)
        created.append("character_memory")

    # state <- first_mes (initial state)
    state_md = _build_state_md(card_ir, runtime_plan)
    if state_md.strip():
        p = _write_resource_file(resources_dir / "state" / "content.md", state_md)
        paths["state"] = str(p)
        created.append("state")

    # notes <- description + creator notes
    notes_md = _build_notes_md(card_ir)
    if notes_md.strip():
        p = _write_resource_file(resources_dir / "notes" / "content.md", notes_md)
        paths["notes"] = str(p)
        created.append("notes")

    # outline <- scenario-derived plot outline (if available)
    outline_md = _build_outline_md(card_ir)
    if outline_md.strip():
        p = _write_resource_file(resources_dir / "outline" / "content.md", outline_md)
        paths["outline"] = str(p)
        created.append("outline")

    # variables <- inferred state variables (front-end display, not injected to AI)
    variables_md = _build_variables_md(card_ir)
    if variables_md.strip():
        p = _write_resource_file(resources_dir / "variables" / "content.md", variables_md)
        paths["variables"] = str(p)
        created.append("variables")

    # front scripts (regex) -> front/
    front_written = 0
    for script in card_ir.get("front_scripts", []):
        front_written += _write_front_script(front_dir, script)

    # Persist the IR + plan next to the resources (under data/) for audit.
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    paths["card_ir"] = str(_write_json(data_dir / "card_ir.json", dict(card_ir)))
    paths["runtime_plan"] = str(_write_json(data_dir / "runtime_plan.json", dict(runtime_plan)))

    return MaterializeResult(
        project_id=root.name,
        project_path=str(root),
        resources_created=created,
        front_scripts_written=front_written,
        paths=paths,
    )


# ── Resource content builders ────────────────────────────────────────────


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


# ── Front scripts ────────────────────────────────────────────────────────


def _write_front_script(front_dir: Path, script: dict[str, Any]) -> int:
    """Write one front-script JSON to ``front/``; return 1 on success, 0 on skip."""
    if not isinstance(script, dict):
        return 0
    name = str(script.get("scriptName") or script.get("name") or "")
    if not name:
        return 0
    safe_name = _safe_filename(name)
    if not safe_name:
        return 0
    try:
        (front_dir / f"{safe_name}.json").write_text(
            json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return 0
    return 1


def _safe_filename(name: str) -> str:
    """Reduce *name* to a filesystem-safe stem (alphanumeric + ``_``)."""
    keep = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return keep.strip("_")[:64]


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


# ── File I/O helpers ─────────────────────────────────────────────────────


def _write_resource_file(path: Path, content: str) -> Path:
    """Write *content* to *path* (creating parents); return *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write *payload* as UTF-8 JSON to *path* (creating parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
