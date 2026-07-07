"""/api/config — global models/providers + per-project + per-agent (refactor_guide:362-384).

Endpoints
---------
* ``GET  /api/config``                            — global config
  (``config/models.yaml`` + ``config/runtime.yaml`` + ``config/server.yaml``).
* ``PUT  /api/config``                            — write back one or more
  global tier files.
* ``GET  /api/config/{project_id}``               — per-project merged
  config (``workspaces/<id>/config.yaml`` layered on the global tier).
* ``PUT  /api/config/{project_id}``               — update the project's
  ``config.yaml`` (display_name / mode / per-project overrides).
* ``GET  /api/config/{project_id}/agents``        — list all 5 built-in
  agents' attribute sets (per guide:368-384).
* ``PUT  /api/config/{project_id}/agents/{name}`` — edit one agent's
  attribute set. Writes to a per-project override file
  ``workspaces/<id>/agents/<name>.yaml`` (preferred over mutating the
  built-in definition).

The handler reads/writes the yaml files directly so the front-end sees
the exact on-disk structure; :class:`~app.config_loader.ConfigLoader`
remains the read-side merger for the runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as FastPath

from app.agents.agent import Agent
from app.agents.registry import AgentRegistry, build_default_registry
from app.api.schemas import (
    AgentConfigResponse,
    ConfigResponse,
    PutAgentConfigRequest,
    PutGlobalConfigRequest,
    PutProjectConfigRequest,
)
from app.config_loader import ConfigLoader
from app.project_paths import ProjectPathError, resolve_project_path
from app.runtime.permission import Permission, parse_permission

router = APIRouter(prefix="/api/config", tags=["config"])

_VALID_MODES = {"novel", "rp"}

# Global tier files: name → (relative path, top-level wrapper key).
# models.yaml and runtime.yaml are stored without a wrapper (the dict IS
# the tier); server.yaml uses a ``server:`` wrapper to match the existing
# config/ layout written by todo 3.
_GLOBAL_TIER_FILES: dict[str, tuple[Path, str | None]] = {
    "models": (Path("config") / "models.yaml", None),
    "runtime": (Path("config") / "runtime.yaml", None),
    "server": (Path("config") / "server.yaml", "server"),
}


ProjectIdPath = Annotated[str, FastPath(..., description="System-controlled project id")]
AgentNamePath = Annotated[str, FastPath(..., description="Agent name")]


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


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Config file {path!s} is not a mapping",
        )
    return raw


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _global_tier_blob(root: Path, name: str) -> dict[str, Any]:
    rel, wrapper = _GLOBAL_TIER_FILES[name]
    raw = _read_yaml(root / rel)
    if wrapper is None:
        return raw
    return raw.get(wrapper, {}) if isinstance(raw.get(wrapper), dict) else {}


def _dump_agent_to_dict(agent: Agent) -> dict[str, Any]:
    """Serialise an :class:`Agent` back to its yaml dict shape."""
    return {
        "name": agent.name,
        "task": agent.task,
        "input": agent.input,
        "output": agent.output,
        "permission": {
            action: list(vector) for action, vector in agent.permission.rules.items()
        },
        "model": agent.model,
        "skills": list(agent.skills),
        "tools": list(agent.tools),
        "head": agent.head,
        "tail": agent.tail,
        "allow_recursive": agent.allow_recursive,
    }


def _agent_to_response(agent: Agent) -> AgentConfigResponse:
    return AgentConfigResponse(
        name=agent.name,
        task=agent.task,
        input=agent.input,
        output=agent.output,
        permission={
            action: list(vector) for action, vector in agent.permission.rules.items()
        },
        model=agent.model,
        skills=list(agent.skills),
        tools=list(agent.tools),
        head=agent.head,
        tail=agent.tail,
        allow_recursive=agent.allow_recursive,
    )


def _load_project_registry(project_path: Path) -> AgentRegistry:
    """Build an :class:`AgentRegistry` for *project_path*.

    Loads the built-in agents first, then overlays any per-project
    override files in ``workspaces/<id>/agents/*.yaml``.
    """
    registry = build_default_registry()
    override_dir = project_path / "agents"
    if override_dir.is_dir():
        for yaml_path in sorted(override_dir.glob("*.yaml")):
            raw = _read_yaml(yaml_path)
            if not raw:
                continue
            try:
                agent = _dict_to_agent(raw, fallback_id=yaml_path.stem)
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Project agent override {yaml_path!s} is invalid: {exc}",
                ) from exc
            registry.register(agent)
    return registry


def _dict_to_agent(raw: dict[str, Any], *, fallback_id: str) -> Agent:
    """Build an :class:`Agent` from a yaml dict (validates required fields)."""
    for required in ("name", "task", "input", "output", "permission"):
        if required not in raw:
            msg = f"missing required field {required!r}"
            raise ValueError(msg)
    permission = parse_permission(dict[str, object](raw["permission"]))
    return Agent(
        id=raw.get("id", fallback_id),
        name=raw["name"],
        task=raw["task"],
        input=raw["input"],
        output=raw["output"],
        permission=permission,
        model=raw.get("model"),
        skills=list(raw.get("skills", [])),
        tools=list(raw.get("tools", ["read", "search", "write"])),
        head=raw.get("head"),
        tail=raw.get("tail"),
        allow_recursive=bool(raw.get("allow_recursive", True)),
    )


# ── Global config ────────────────────────────────────────────────────────


@router.get("", response_model=ConfigResponse)
def get_global_config(root: RootDep) -> ConfigResponse:
    """Return the global config (models + runtime + server tiers)."""
    return ConfigResponse(
        project_id="",
        models=_global_tier_blob(root, "models"),
        runtime=_global_tier_blob(root, "runtime"),
        server=_global_tier_blob(root, "server"),
    )


@router.put("", response_model=ConfigResponse)
def put_global_config(req: PutGlobalConfigRequest, root: RootDep) -> ConfigResponse:
    """Write back one or more global tier files.

    Each provided blob replaces that tier file's content wholesale; the
    on-disk wrapper (if any) is preserved. Omitted tiers are untouched.
    """
    if req.models is None and req.runtime is None and req.server is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update (provide models, runtime, and/or server)",
        )

    for name, blob in (
        ("models", req.models),
        ("runtime", req.runtime),
        ("server", req.server),
    ):
        if blob is None:
            continue
        rel, wrapper = _GLOBAL_TIER_FILES[name]
        path = root / rel
        if wrapper is None:
            _write_yaml(path, dict(blob))
        else:
            existing = _read_yaml(path)
            existing[wrapper] = dict(blob)
            _write_yaml(path, existing)

    return ConfigResponse(
        project_id="",
        models=_global_tier_blob(root, "models"),
        runtime=_global_tier_blob(root, "runtime"),
        server=_global_tier_blob(root, "server"),
    )


# ── Per-agent config (declared BEFORE /{project_id} so FastAPI's path
#    matcher hits the more specific /{project_id}/agents routes first) ────


@router.get("/{project_id}/agents", response_model=list[AgentConfigResponse])
def list_project_agents(
    project_id: ProjectIdPath, root: RootDep
) -> list[AgentConfigResponse]:
    """List all agents visible to *project_id* (built-in + project overrides)."""
    path = _resolve_project(root, project_id)
    registry = _load_project_registry(path)
    return [_agent_to_response(registry.get(name)) for name in registry.list()]


@router.put("/{project_id}/agents/{name}", response_model=AgentConfigResponse)
def put_project_agent(
    project_id: ProjectIdPath,
    name: AgentNamePath,
    req: PutAgentConfigRequest,
    root: RootDep,
) -> AgentConfigResponse:
    """Edit one agent's attribute set (guide:368-384).

    Writes a per-project override file at
    ``workspaces/<id>/agents/<name>.yaml``. Built-in definitions are
    never mutated (project-level override preferred).
    """
    if req.name != name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Body name {req.name!r} does not match path name {name!r}",
        )

    path = _resolve_project(root, project_id)
    registry = _load_project_registry(path)
    if not registry.has(name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {name!r} is not registered in project {project_id!r}",
        )

    # Validate the permission structure before writing.
    try:
        permission: Permission = parse_permission(
            dict[str, object](req.permission)
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid permission: {exc}",
        ) from exc

    existing = registry.get(name)
    new_agent = Agent(
        id=existing.id,
        name=req.name,
        task=req.task,
        input=req.input,
        output=req.output,
        permission=permission,
        model=req.model,
        skills=list(req.skills),
        tools=list(req.tools),
        head=req.head,
        tail=req.tail,
        allow_recursive=req.allow_recursive,
    )

    override_dir = path / "agents"
    override_path = override_dir / f"{name}.yaml"
    _write_yaml(override_path, _dump_agent_to_dict(new_agent))

    return _agent_to_response(new_agent)


# ── Per-project config ───────────────────────────────────────────────────


@router.get("/{project_id}", response_model=ConfigResponse)
def get_project_config(project_id: ProjectIdPath, root: RootDep) -> ConfigResponse:
    """Return the merged per-project config (global + project overrides)."""
    _resolve_project(root, project_id)
    loader = ConfigLoader(root)
    cfg = loader.load_project(project_id)
    return ConfigResponse(
        project_id=project_id,
        display_name=cfg.display_name,
        mode=cfg.mode,
        models=cfg.models.model_dump(),
        runtime=cfg.runtime.model_dump(),
        server=cfg.server.model_dump(),
    )


@router.put("/{project_id}", response_model=ConfigResponse)
def put_project_config(
    project_id: ProjectIdPath,
    req: PutProjectConfigRequest,
    root: RootDep,
) -> ConfigResponse:
    """Update a project's ``config.yaml`` (display_name / mode / overrides)."""
    if not req.has_updates():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update (provide display_name, mode, models, runtime, and/or server)",
        )
    if req.mode is not None and req.mode not in _VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode {req.mode!r}; must be one of {sorted(_VALID_MODES)}",
        )

    path = _resolve_project(root, project_id)
    config_path = path / "config.yaml"
    raw = _read_yaml(config_path)
    if req.display_name is not None:
        raw["display_name"] = req.display_name
    if req.mode is not None:
        raw["mode"] = req.mode
    for name in ("models", "runtime", "server"):
        blob = getattr(req, name)
        if blob is not None:
            raw[name] = dict(blob)
    _write_yaml(config_path, raw)

    return get_project_config(project_id, root)


__all__ = [
    "get_global_config",
    "put_global_config",
    "get_project_config",
    "put_project_config",
    "list_project_agents",
    "put_project_agent",
    "router",
]
