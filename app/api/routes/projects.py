"""/api/projects CRUD — system-controlled id, display-name in config.yaml.

Endpoints
---------
* ``POST   /api/projects``      — create a project (server generates the id,
  scaffolds the workspace) → 201 :class:`ProjectResponse`.
* ``GET    /api/projects``      — list all known projects →
  :class:`ProjectListResponse`.
* ``GET    /api/projects/{id}`` — project detail → :class:`ProjectResponse`.
* ``PATCH  /api/projects/{id}`` — update ``display_name`` and/or ``mode`` in
  the project's ``config.yaml``.
* ``DELETE /api/projects/{id}`` — remove the workspace directory.

Per refactor_guide:39 the id is **system-controlled**: the POST body carries
only ``display_name`` and ``mode``; any user-supplied ``id`` field is
ignored (and rejected if present, to make the contract explicit).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.api.schemas import (
    CreateProjectRequest,
    PatchProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectSummary,
)
from app.config_loader import ConfigLoader
from app.project_init import scaffold_project
from app.project_paths import (
    ProjectPathError,
    list_project_ids,
    resolve_project_path,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])

_VALID_MODES = {"novel", "rp"}


ProjectIdPath = Annotated[str, FastPath(..., description="System-controlled project id")]


def _root_dep(request: Request) -> Path:
    """Resolve the repo root from app state (set by ``create_app``)."""
    root = getattr(request.app.state, "root", None)
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server root not initialised",
        )
    return Path(root)


RootDep = Annotated[Path, Depends(_root_dep)]


# ── Helpers ──────────────────────────────────────────────────────────────


def _loader_for(root: Path) -> ConfigLoader:
    return ConfigLoader(root)


def _project_response(root: Path, project_id: str) -> ProjectResponse:
    """Build a :class:`ProjectResponse` by reading the project's config.yaml."""
    try:
        path = resolve_project_path(root, project_id)
    except ProjectPathError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not path.exists() or not (path / "config.yaml").exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id!r} not found",
        )
    cfg = _loader_for(root).load_project(project_id)
    return ProjectResponse(
        id=project_id,
        display_name=cfg.display_name,
        mode=cfg.mode,
        path=str(path),
    )


# ── Routes ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(req: CreateProjectRequest, root: RootDep) -> ProjectResponse:
    """Create a new project. The id is generated server-side."""
    if req.mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode {req.mode!r}; must be one of {sorted(_VALID_MODES)}",
        )

    project_path = scaffold_project(root, display_name=req.display_name, mode=req.mode)
    project_id = project_path.name
    return _project_response(root, project_id)


@router.get("", response_model=ProjectListResponse)
def list_projects(root: RootDep) -> ProjectListResponse:
    """List all known projects (sorted by id)."""
    ids = list_project_ids(root)
    loader = _loader_for(root)
    summaries: list[ProjectSummary] = []
    for pid in ids:
        try:
            cfg = loader.load_project(pid)
        except Exception:  # noqa: BLE001 — skip malformed projects in list
            continue
        summaries.append(
            ProjectSummary(id=pid, display_name=cfg.display_name, mode=cfg.mode)
        )
    return ProjectListResponse(projects=summaries)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: ProjectIdPath, root: RootDep) -> ProjectResponse:
    """Get a single project's detail."""
    return _project_response(root, project_id)


@router.patch("/{project_id}", response_model=ProjectResponse)
def patch_project(
    project_id: ProjectIdPath,
    req: PatchProjectRequest,
    root: RootDep,
) -> ProjectResponse:
    """Update display_name and/or mode in the project's config.yaml."""
    if req.mode is not None and req.mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode {req.mode!r}; must be one of {sorted(_VALID_MODES)}",
        )

    try:
        path = resolve_project_path(root, project_id)
    except ProjectPathError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    config_path = path / "config.yaml"
    if not config_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id!r} not found",
        )

    if not req.has_updates():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update (provide display_name and/or mode)",
        )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    if req.display_name is not None:
        raw["display_name"] = req.display_name
    if req.mode is not None:
        raw["mode"] = req.mode
    config_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    return _project_response(root, project_id)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: ProjectIdPath, root: RootDep) -> None:
    """Remove a project's workspace directory entirely."""
    try:
        path = resolve_project_path(root, project_id)
    except ProjectPathError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id!r} not found",
        )
    _rmtree_force(path)


def _rmtree_force(path: Path) -> None:
    """``shutil.rmtree`` that clears read-only bits and retries on Windows.

    Git creates read-only object files (breaks ``shutil.rmtree`` on
    Windows), and ``git.Repo`` instances may briefly hold file handles
    that have not yet been reclaimed by the GC. We clear the read-only
    bit via ``onerror`` and retry a few times with a short sleep to let
    any lingering handles close.
    """
    import gc
    import os
    import stat
    import time

    def _on_error(
        func: Callable[[str], None],
        target: str,
        exc_info: tuple[type[BaseException], BaseException, Any],
    ) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    last_err: Exception | None = None
    for _ in range(5):
        gc.collect()
        try:
            shutil.rmtree(path, onerror=_on_error)
            return
        except PermissionError as exc:
            last_err = exc
            time.sleep(0.1)
    if last_err is not None:
        raise last_err
