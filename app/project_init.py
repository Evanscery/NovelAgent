"""Scaffold a new project under ``workspaces/<system-id>/``.

Per refactor_guide:33-47 and the work plan (todo 21), a new project is
created with:

1. A **system-controlled** id via :func:`generate_project_id` (never
   user-supplied).
2. A ``config.yaml`` carrying ``display_name`` and ``mode`` (novel/rp).
3. A copy of the default workflow canvas (``default_workflow.yaml``).
4. The 8 resource directories, each with its default ``properties.md`` and a
   ``manifest.json``.
5. Empty ``front/`` and ``novels/`` directories.
6. An **independent** git repo (``ProjectRepo.init``) — per D6 each
   workspace is its own repo, ignored by the main repo.
7. An initial ``Turn 0`` commit so the project starts with a real history.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from app.data.manifest import ResourceManifest, write_manifest
from app.data.project_repo import ProjectRepo
from app.data.properties import serialize_properties_md
from app.data.resource_types import RESOURCE_TYPE_REGISTRY
from app.project_paths import generate_project_id, resolve_project_path

__all__ = ["scaffold_project"]

# Resource directory names in the canonical order used by scaffold_project.
_RESOURCE_TYPE_NAMES: list[str] = list(RESOURCE_TYPE_REGISTRY.keys())

# Path to the default workflow canvas shipped with the agent layer.
_DEFAULT_WORKFLOW_SRC = Path(__file__).parent / "agents" / "default_workflow.yaml"

VALID_MODES = {"novel", "rp"}


def scaffold_project(root: Path | str, display_name: str, mode: str = "novel") -> Path:
    """Scaffold a new project and return its workspace path.

    Args:
        root: Repo root (the directory that contains ``workspaces/``).
        display_name: Human-readable project name (stored in ``config.yaml``,
            NOT used as the directory name — per refactor_guide:40).
        mode: ``"novel"`` or ``"rp"`` (per refactor_guide:42-47). Defaults
            to ``"novel"``.

    Returns:
        The absolute path to the newly created ``workspaces/<id>/`` directory.

    Raises:
        ValueError: If *display_name* is empty or *mode* is not ``novel``/``rp``.
    """
    if not display_name or not display_name.strip():
        msg = "display_name must be a non-empty string"
        raise ValueError(msg)
    if mode not in VALID_MODES:
        msg = f"Invalid mode {mode!r}; must be one of {sorted(VALID_MODES)}"
        raise ValueError(msg)

    # 1. System-controlled id + path resolution.
    project_id = generate_project_id()
    project_path = resolve_project_path(root, project_id)
    # resolve_project_path guarantees the path is inside workspaces/ — but it
    # does NOT create the directory. Make it here.
    project_path.mkdir(parents=True, exist_ok=False)

    # 2. config.yaml — display_name + mode (+ empty overrides).
    _write_config_yaml(project_path, display_name=display_name, mode=mode)

    # 3. workflow.yaml — copy of the default canvas.
    workflow_dst = project_path / "workflow.yaml"
    if _DEFAULT_WORKFLOW_SRC.exists():
        shutil.copyfile(_DEFAULT_WORKFLOW_SRC, workflow_dst)
    else:
        # Defensive: the default workflow ships with the agent layer; if it
        # is missing we still create an empty file so the project is valid.
        workflow_dst.write_text("nodes: []\nwires: []\n", encoding="utf-8")

    # 4. Eight resource directories with properties.md + manifest.json.
    resources_dir = project_path / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    for type_name in _RESOURCE_TYPE_NAMES:
        type_cls = RESOURCE_TYPE_REGISTRY[type_name]
        res_dir = resources_dir / type_name
        res_dir.mkdir(parents=True, exist_ok=True)

        props = type_cls.default_properties()
        (res_dir / "properties.md").write_text(
            serialize_properties_md(props), encoding="utf-8"
        )

        manifest = ResourceManifest(
            type=type_name,
            properties_ref="properties.md",
            recent_commit=None,
            current_branch="main",
        )
        write_manifest(res_dir / "manifest.json", manifest)

    # 5. front/ and novels/ directories.
    (project_path / "front").mkdir(parents=True, exist_ok=True)
    (project_path / "novels").mkdir(parents=True, exist_ok=True)

    # 6. Independent git repo (per-workspace, D6).
    repo = ProjectRepo(project_path)
    repo.init()

    # 7. Initial Turn 0 commit so the project starts with a real history.
    repo.commit_turn(turn_id="0", message="project initialized")

    return project_path


def _write_config_yaml(project_path: Path, *, display_name: str, mode: str) -> None:
    """Write the per-project ``config.yaml``.

    Only the project-specific top-level fields are written here; global
    overrides (models/runtime/server) are intentionally omitted so the
    project inherits the global defaults unless a user explicitly adds them
    later (via the config UI / PATCH endpoint).
    """
    data = {"display_name": display_name, "mode": mode}
    (project_path / "config.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
