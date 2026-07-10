"""Four-tier layered config: global < profile < project < run-override.

Per refactor_guide §项目目录与配置控制 (lines 31-47) and the four-tier
priority described in the work plan (global < profile < project < run-override):

* **global**   — ``config/models.yaml``, ``config/runtime.yaml``,
  ``config/server.yaml`` at the repo root. Shared defaults for every project.
* **profile**  — optional named profile layer (reserved; not yet exposed in
  the UI — returns the global config unchanged when no profile is given).
* **project**  — ``workspaces/<id>/config.yaml``; carries ``display_name``,
  ``mode`` (novel/rp) and any per-project override of models/runtime/server.
* **run-override** — an optional dict passed at runtime that wins over
  everything else (e.g. CLI flags or per-request overrides).

The loader merges layers by *deep-merging* dicts (per-key, nested) so a
project can override a single field of a global tier without redeclaring the
whole tier. Lists are replaced wholesale (not concatenated) to keep the
semantics predictable for users.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ── Pydantic models ──────────────────────────────────────────────────────


class TierConfig(BaseModel):
    """One model tier (premium/standard/cheap)."""

    provider: str = "openai_compatible"
    model_env: str = "MODEL_HIGH"
    rpm: int = 10
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(BaseModel):
    """config/models.yaml — provider types + per-agent model tier."""

    tiers: dict[str, TierConfig] = Field(default_factory=dict)
    agent_models: dict[str, str] = Field(default_factory=dict)


class RuntimeConfig(BaseModel):
    """config/runtime.yaml — timeout/retry/budget/finalize policies."""

    runner: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)


class ServerConfig(BaseModel):
    """config/server.yaml — FastAPI host/port/CORS/whitelist."""

    host: str = "127.0.0.1"
    port: int = 8000
    open_browser: bool = False
    allow_origins: list[str] = Field(default_factory=list)
    ip_whitelist: list[str] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    """Merged global configuration (models + runtime + server).

    This is the **global** layer only — no project-specific fields. Use
    :func:`load_project` to obtain a :class:`ProjectConfig` that merges a
    project's ``config.yaml`` on top.
    """

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


class ProjectConfig(BaseModel):
    """Merged per-project configuration (global + project config.yaml).

    Carries the project-specific fields ``display_name`` and ``mode`` from
    ``workspaces/<id>/config.yaml`` (refactor_guide:40-47) plus the merged
    global layers that the project is allowed to override.
    """

    display_name: str = ""
    mode: str = "novel"
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


# ── Loader ───────────────────────────────────────────────────────────────


class ConfigLoader:
    """Load and merge the four config layers.

    The loader is anchored at a repo *root*. It reads the three global yaml
    files lazily (missing files yield empty defaults rather than errors, so
    a fresh checkout without ``config/models.yaml`` still boots).

    Profile layer is a stub — not yet implemented. Reserved for future use.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ── global ──────────────────────────────────────────────────────────

    def load_global(self, run_override: dict[str, Any] | None = None) -> GlobalConfig:
        """Load the global layer (models + runtime + server).

        Args:
            run_override: Optional run-override dict whose keys mirror the
                :class:`GlobalConfig` shape (``models``, ``runtime``,
                ``server``); values here win over the file layer.
        """
        models_raw = self._load_yaml(self._root / "config" / "models.yaml") or {}
        runtime_raw = self._load_yaml(self._root / "config" / "runtime.yaml") or {}
        server_raw = self._load_yaml(self._root / "config" / "server.yaml") or {}

        merged: dict[str, Any] = {
            "models": models_raw.get("models", models_raw) if isinstance(models_raw, dict) else {},
            "runtime": runtime_raw.get("runtime", runtime_raw) if isinstance(runtime_raw, dict) else {},
            "server": server_raw.get("server", server_raw) if isinstance(server_raw, dict) else {},
        }
        if run_override:
            merged = _deep_merge(merged, run_override)
        return GlobalConfig.model_validate(merged)

    # ── project ─────────────────────────────────────────────────────────

    def load_project(
        self,
        project_id: str,
        run_override: dict[str, Any] | None = None,
    ) -> ProjectConfig:
        """Load a merged :class:`ProjectConfig` for *project_id*.

        Merges the global layer with ``workspaces/<id>/config.yaml`` and the
        optional *run_override*. The project config.yaml may override any of
        the global sub-configs (models/runtime/server) and must declare
        ``display_name`` and ``mode``.
        """
        global_cfg = self.load_global()
        global_dict = global_cfg.model_dump()

        project_path = self._root / "workspaces" / project_id / "config.yaml"
        project_raw = self._load_yaml(project_path) or {}
        if not isinstance(project_raw, dict):
            msg = f"Project config {project_path!s}: expected mapping, got {type(project_raw).__name__}"
            raise ValueError(msg)

        merged = _deep_merge(global_dict, project_raw)
        if run_override:
            merged = _deep_merge(merged, run_override)
        return ProjectConfig.model_validate(merged)

    # ── internals ───────────────────────────────────────────────────────

    @staticmethod
    def _load_yaml(path: Path) -> Any:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── Module-level helpers ─────────────────────────────────────────────────


def load_global(root: Path | str, run_override: dict[str, Any] | None = None) -> GlobalConfig:
    """Convenience wrapper around :meth:`ConfigLoader.load_global`."""
    return ConfigLoader(root).load_global(run_override=run_override)


def load_project(
    root: Path | str,
    project_id: str,
    run_override: dict[str, Any] | None = None,
) -> ProjectConfig:
    """Convenience wrapper around :meth:`ConfigLoader.load_project`."""
    return ConfigLoader(root).load_project(project_id=project_id, run_override=run_override)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*.

    - Dict values are merged key-by-key (nested).
    - Non-dict values (including lists) are replaced wholesale.
    - ``base`` is never mutated.
    """
    result = deepcopy(base)
    for key, ov_val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(ov_val, dict):
            result[key] = _deep_merge(result[key], ov_val)
        else:
            result[key] = deepcopy(ov_val)
    return result


__all__ = [
    "ConfigLoader",
    "GlobalConfig",
    "ModelsConfig",
    "ProjectConfig",
    "RuntimeConfig",
    "ServerConfig",
    "TierConfig",
    "load_global",
    "load_project",
]
