"""System-controlled project id → path resolution.

Per refactor_guide:39 the project id is **system-controlled** (not
user-supplied) and lives under ``workspaces/<id>/``. This module is the
single source of truth for that mapping: it generates ids, resolves them to
paths, validates their format, and lists known projects.

Security: ids are restricted to ``[A-Za-z0-9_]`` and must not resolve outside
``workspaces/`` (no ``..``, no absolute paths, no separators). Any attempt to
use a malformed id raises :class:`ProjectPathError`.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

__all__ = [
    "ProjectPathError",
    "generate_project_id",
    "list_project_ids",
    "resolve_project_path",
]

# ── Id format ────────────────────────────────────────────────────────────

# System-controlled ids look like ``proj_<uuid8>`` (8 hex chars). The
# validation regex is intentionally strict so ids can never contain a path
# separator, a ``..`` segment, or any shell-unfriendly character.
_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
_ID_PREFIX = "proj_"
_WORKSPACES_DIR = "workspaces"


class ProjectPathError(Exception):
    """Raised for invalid project ids or path-traversal attempts."""


def generate_project_id() -> str:
    """Generate a fresh, unique-looking project id.

    Format: ``proj_<uuid8>`` — 8 hex characters from :func:`uuid.uuid4`.
    The id is system-controlled (per refactor_guide:39); callers must NOT
    accept user-supplied ids.
    """
    suffix = uuid.uuid4().hex[:8]
    return f"{_ID_PREFIX}{suffix}"


def resolve_project_path(root: Path | str, project_id: str) -> Path:
    """Resolve *project_id* to its absolute workspace path.

    The returned path is ``<root>/workspaces/<project_id>/``. The id is
    validated against the strict format above and the resolved path is
    checked to actually live inside ``<root>/workspaces/`` — this blocks
    path-traversal attempts (``..``, absolute paths, etc.).

    Raises:
        ProjectPathError: If *project_id* is empty, contains characters
            outside ``[A-Za-z0-9_]``, or would resolve outside the
            workspaces directory.
    """
    if not project_id:
        msg = "project_id must be a non-empty string"
        raise ProjectPathError(msg)

    if not _ID_RE.match(project_id):
        msg = (
            f"Invalid project_id {project_id!r}: only alphanumeric characters "
            "and underscore are allowed"
        )
        raise ProjectPathError(msg)

    root_path = Path(root).resolve()
    workspaces_dir = root_path / _WORKSPACES_DIR
    candidate = (workspaces_dir / project_id).resolve()

    # Defensive: ensure the resolved candidate is inside workspaces_dir.
    try:
        candidate.relative_to(workspaces_dir)
    except ValueError as exc:
        msg = f"project_id {project_id!r} resolves outside the workspaces directory"
        raise ProjectPathError(msg) from exc

    return candidate


def list_project_ids(root: Path | str) -> list[str]:
    """List all known project ids under ``<root>/workspaces/``.

    A directory is considered a project if it contains a ``config.yaml``
    (the per-project config file written by :func:`app.project_init.scaffold_project`).
    Returned ids are sorted lexicographically.
    """
    workspaces_dir = Path(root).resolve() / _WORKSPACES_DIR
    if not workspaces_dir.exists():
        return []

    ids: list[str] = []
    for child in sorted(workspaces_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "config.yaml").exists():
            continue
        ids.append(child.name)
    return ids
