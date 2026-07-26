"""/api/import — delegates to app/compat/tavern_card (todo 34).

End-to-end card import flow:

1. Resolve the card payload — either from ``req.source`` (a path on disk)
   or from ``req.card`` (an inline dict). One of the two is required.
2. :func:`~app.compat.tavern_card.card_migration.is_recognized_card` guards
   the pipeline: payloads that do not look like a character card are rejected
   with ``400 "not a recognized card format"`` (general import is future
   work).
3. :func:`~app.compat.tavern_card.card_migration.infer_card_ir` +
   :func:`~app.compat.tavern_card.card_migration.infer_runtime_plan`
   produce the IR + plan.
4. A target project is resolved: if ``req.project_id`` is given, the
   existing workspace at that id is reused (must already exist → 404
   otherwise); otherwise a fresh project is scaffolded via
   :func:`~app.project_init.scaffold_project`.
5. :func:`~app.compat.tavern_card.card_migration.materialize_project_from_card`
   writes the card-derived content into the 8 resource dirs + ``front/``.
6. The project's ``config.yaml`` is patched so ``display_name`` /
   ``mode`` reflect the card (unless the request overrode them).
7. ``201`` :class:`ImportResponse` is returned.

Per ``docs/refactor_guide.md:27-29`` + D5, all character-card-compat naming
converges to ``app/compat/tavern_card/``. This route is the API seam; it
uses the project's own terms (角色卡 / 卡导入) in user-facing messages and
delegates all card-format specifics to the compat layer.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request, status

from app.api.routes._deps import _root_dep
from app.api.schemas import ImportRequest, ImportResponse
from app.compat.tavern_card.card_migration import (
    infer_card_ir,
    infer_runtime_plan,
    is_recognized_card,
    load_card_payload,
    materialize_project_from_card,
)
from app.project_init import VALID_MODES, scaffold_project
from app.project_paths import ProjectPathError, resolve_project_path

router = APIRouter(prefix="/api/import", tags=["import"])


# ── POST /api/import ─────────────────────────────────────────────────────


@router.post("", response_model=ImportResponse, status_code=status.HTTP_201_CREATED)
def import_card(req: ImportRequest, request: Request) -> ImportResponse:
    """Import a card file / inline card payload as a new (or existing) project."""
    root = _root_dep(request)

    # 1. Resolve card payload.
    if req.card is not None:
        payload = req.card
    elif req.source:
        source_path = Path(req.source)
        if not source_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source file not found: {req.source!r}",
            )
        try:
            payload = load_card_payload(source_path)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to read card file: {exc}",
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'source' (path to a card file) or 'card' (inline payload) is required",
        )

    # 2. Recognize.
    if not is_recognized_card(payload):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a recognized card format (general import is not yet supported)",
        )

    # 3. IR + plan.
    card_ir = infer_card_ir(payload)
    runtime_plan = infer_runtime_plan(card_ir)

    # 4. Resolve target project.
    if req.project_id:
        try:
            project_path = resolve_project_path(root, req.project_id)
        except ProjectPathError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        if not project_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {req.project_id!r} not found",
            )
        project_id = req.project_id
    else:
        display_name_for_scaffold = req.display_name or card_ir.get("card_name") or "Imported Card"
        mode_for_scaffold = req.mode or runtime_plan.get("recommended_mode", "novel")
        if mode_for_scaffold not in VALID_MODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid mode {mode_for_scaffold!r}; must be one of {sorted(VALID_MODES)}",
            )
        project_path = scaffold_project(
            root, display_name=display_name_for_scaffold, mode=mode_for_scaffold
        )
        project_id = project_path.name

    # 5. Materialize 8 resources + front scripts.
    result = materialize_project_from_card(project_path, card_ir, runtime_plan)

    # 6. Patch config.yaml so display_name / mode reflect the card (unless
    #    the caller is reusing an existing project and did not override).
    display_name_final = req.display_name or card_ir.get("card_name") or "Imported Card"
    mode_final = req.mode or runtime_plan.get("recommended_mode", "novel")
    if mode_final not in VALID_MODES:
        # Defensive: the runtime plan should always produce a valid mode.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Runtime plan produced invalid mode {mode_final!r}",
        )
    _patch_project_config(project_path, display_name_final, mode_final, override=bool(req.project_id))

    return ImportResponse(
        project_id=project_id,
        display_name=display_name_final,
        mode=mode_final,
        resources_created=result.resources_created,
        front_scripts_written=result.front_scripts_written,
        paths=result.paths,
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _patch_project_config(
    project_path: Path, display_name: str, mode: str, *, override: bool
) -> None:
    """Update ``workspaces/<id>/config.yaml`` with the card-derived name/mode.

    When *override* is ``False`` (a fresh project was just scaffolded), the
    config already carries the scaffolded values — we still rewrite to
    guarantee they match the card. When *override* is ``True`` (reusing an
    existing project), we only update the fields the caller explicitly
    provided via the request — but since the caller is the import flow,
    both display_name and mode are always set here; the existing project's
    prior values are overwritten to reflect the new card.
    """
    config_path = project_path / "config.yaml"
    if not config_path.exists():
        # Scaffolded projects always have a config.yaml; this is defensive.
        raw: dict[str, object] = {}
    else:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        raw = loaded if isinstance(loaded, dict) else {}
    raw["display_name"] = display_name
    raw["mode"] = mode
    config_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


__all__ = ["import_card", "router"]
