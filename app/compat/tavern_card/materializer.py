"""Materialize a :class:`CardIR` + :class:`RuntimePlan` into project files.

Split out of the legacy monolithic ``card_migration.py``. Provides:

* :class:`MaterializeResult` — frozen dataclass outcome of materialization.
* :func:`materialize_project_from_card` — write the 8 resource dirs + front scripts.
* File I/O helpers: ``_write_front_script``, ``_safe_filename``,
  ``_write_resource_file``, ``_write_json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.compat.tavern_card.content_builders import (
    _build_character_memory_md,
    _build_notes_md,
    _build_outline_md,
    _build_state_md,
    _build_variables_md,
    _build_worldbook_md,
)
from app.compat.tavern_card.ir_definition import CardIR, RuntimePlan

__all__ = ["MaterializeResult", "materialize_project_from_card"]


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
