"""/api/resources read/edit/version-history per type (refactor_guide:386-400).

Endpoints
---------
* ``GET /api/resources/{project_id}``              — list all 8 resource
  types (with content summary).
* ``GET /api/resources/{project_id}/{type}``        — read a type's full
  content.
* ``PUT /api/resources/{project_id}/{type}``        — edit (write) a
  resource. **Rejected for the ``variables`` type** with ``403`` per
  refactor_guide:210-211 (variables are front-end display only, not
  editor-editable via the API).
* ``GET /api/resources/{project_id}/{type}/history`` — git commit history
  filtered to ``resources/<type>/`` (via
  :meth:`VersionManager.list_history_for_resource`).

All handlers resolve the project path via the shared ``_root_dep``
pattern from :mod:`app.api.routes.projects`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import git
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.api.schemas import (
    PutResourceRequest,
    ResourceContentResponse,
    ResourceHistoryEntry,
    ResourceHistoryResponse,
    ResourceListEntry,
    ResourceListResponse,
)
from app.data.resource_types import RESOURCE_TYPE_REGISTRY, get_resource_type
from app.data.store import ResourceStore
from app.data.versioning import VersionManager
from app.project_paths import ProjectPathError, resolve_project_path

router = APIRouter(prefix="/api/resources", tags=["resources"])

# Per refactor_guide:210-211 variables are front-end display only — the
# API editor refuses to PUT them. GET still works.
_READ_ONLY_TYPES: frozenset[str] = frozenset({"variables"})

# Friendly Chinese titles for the 8 types (refactor_guide:167).
_TYPE_TITLES: dict[str, str] = {
    "outline": "大纲",
    "short_goal": "细纲",
    "state": "当前状态",
    "variables": "变量",
    "worldbook": "世界书",
    "facts": "客观事实",
    "character_memory": "人物记忆",
    "notes": "创作笔记",
}

_SUMMARY_MAX_CHARS = 240


ProjectIdPath = Annotated[str, FastPath(..., description="System-controlled project id")]
ResourceTypePath = Annotated[str, FastPath(..., description="Resource type key")]


def _root_dep(request: Request) -> Path:
    root = getattr(request.app.state, "root", None)
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server root not initialised",
        )
    return Path(root)


RootDep = Annotated[Path, Depends(_root_dep)]


def _resolve_project(root: Path, project_id: str) -> Path:
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


def _validate_type(type_name: str) -> str:
    if type_name not in RESOURCE_TYPE_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid resource type {type_name!r}; valid types: "
                f"{sorted(RESOURCE_TYPE_REGISTRY)}"
            ),
        )
    return type_name


def _title_for(type_name: str) -> str:
    return _TYPE_TITLES.get(type_name, type_name)


def _list_content_files(res_dir: Path) -> list[Path]:
    skip = {"properties.md", "manifest.json", ".index"}
    if not res_dir.is_dir():
        return []
    return sorted(
        c for c in res_dir.iterdir() if c.is_file() and c.name not in skip
    )


def _build_summary(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    return text[:_SUMMARY_MAX_CHARS].rstrip() + "…"


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/{project_id}", response_model=ResourceListResponse)
def list_resources(project_id: ProjectIdPath, root: RootDep) -> ResourceListResponse:
    """List all 8 resource types for *project_id* with a content summary.

    The returned list ALWAYS has one entry per registered type, even when
    the project has not written any content yet — the front-end renders
    an editor tab for every type (refactor_guide:388-400).
    """
    path = _resolve_project(root, project_id)

    entries: list[ResourceListEntry] = []
    for type_name in sorted(RESOURCE_TYPE_REGISTRY):
        res_dir = path / "resources" / type_name
        files = _list_content_files(res_dir)
        summary = ""
        if files:
            try:
                # Build a preview from the first file's leading content.
                first = files[0].read_text(encoding="utf-8")
                summary = _build_summary(first)
            except (OSError, UnicodeDecodeError):
                summary = ""
        entries.append(
            ResourceListEntry(
                type=type_name,
                title=_title_for(type_name),
                exists=bool(files),
                file_count=len(files),
                content_summary=summary,
            )
        )
    return ResourceListResponse(project_id=project_id, resources=entries)


@router.get("/{project_id}/{type}", response_model=ResourceContentResponse)
def read_resource(
    project_id: ProjectIdPath,
    type: ResourceTypePath,
    root: RootDep,
) -> ResourceContentResponse:
    """Read the full content of resource *type* in *project_id*."""
    _validate_type(type)
    path = _resolve_project(root, project_id)
    store = ResourceStore(path)
    # create_resource is idempotent — ensures the dir/properties/manifest exist.
    resource = store.create_resource(type, type)
    content = store.read(resource)
    files = [f.name for f in _list_content_files(resource.path)]
    return ResourceContentResponse(
        project_id=project_id,
        type=type,
        title=_title_for(type),
        read_only=type in _READ_ONLY_TYPES,
        content=content,
        files=files,
    )


@router.put("/{project_id}/{type}", response_model=ResourceContentResponse)
def put_resource(
    project_id: ProjectIdPath,
    type: ResourceTypePath,
    req: PutResourceRequest,
    root: RootDep,
) -> ResourceContentResponse:
    """Edit (write) a resource's content.

    Rejected with ``403`` for the ``variables`` type (front-end display
    only — refactor_guide:210-211). The write is **not** committed by
    this endpoint; a workflow Round or explicit project-repo commit
    creates the Turn commit (per refactor_guide:300 one commit per
    Round, not per API call).
    """
    _validate_type(type)
    if type in _READ_ONLY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Resource type {type!r} is read-only via the API editor "
                "(variables are front-end display only, per guide:210-211)."
            ),
        )
    path = _resolve_project(root, project_id)
    store = ResourceStore(path)
    resource = store.create_resource(type, type)
    filename = req.filename or "content.md"
    store.write(resource, filename, req.content)
    content = store.read(resource)
    files = [f.name for f in _list_content_files(resource.path)]
    return ResourceContentResponse(
        project_id=project_id,
        type=type,
        title=_title_for(type),
        read_only=False,
        content=content,
        files=files,
    )


@router.get(
    "/{project_id}/{type}/history",
    response_model=ResourceHistoryResponse,
)
def resource_history(
    project_id: ProjectIdPath,
    type: ResourceTypePath,
    root: RootDep,
) -> ResourceHistoryResponse:
    """Return the git commit history filtered to ``resources/<type>/``.

    Per refactor_guide:388-400 each data type exposes its own version
    history. We use ``git log -- resources/<type>`` so only commits
    whose diff actually touches that subtree are listed (newest first).
    """
    _validate_type(type)
    path = _resolve_project(root, project_id)
    vm = VersionManager(path)

    try:
        commits = vm.list_history_for_resource(type, max_count=50)
    except git.exc.InvalidGitRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {project_id!r} has no git repository",
        ) from exc

    entries = [
        ResourceHistoryEntry(
            sha=c.sha,
            turn_id=c.turn_id,
            message=c.message,
            timestamp=c.timestamp.isoformat(),
            branch=c.branch,
        )
        for c in commits
    ]
    return ResourceHistoryResponse(
        project_id=project_id, type=type, commits=entries
    )


# Re-export so callers can ``from app.api.routes.resources import get_resource_type``
__all__ = [
    "get_resource_type",
    "read_resource",
    "put_resource",
    "resource_history",
    "list_resources",
    "router",
]
