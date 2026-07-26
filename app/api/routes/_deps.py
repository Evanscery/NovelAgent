"""Shared FastAPI dependencies for the /api routes.

Every route module needs the repo root (from app state) and project-id
resolution; they live here once instead of being copy-pasted per module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.project_paths import ProjectPathError, resolve_project_path

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


def resolve_project(root: Path, project_id: str) -> Path:
    """Resolve *project_id* to its workspace path or raise a 404."""
    try:
        path = resolve_project_path(root, project_id)
    except ProjectPathError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not path.exists() or not (path / "config.yaml").exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id!r} not found",
        )
    return path


__all__ = ["ProjectIdPath", "RootDep", "resolve_project"]
