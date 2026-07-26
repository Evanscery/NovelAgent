"""Tests for app.config_loader — global + project layering."""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config_loader import AgentsConfig, ConfigLoader, GlobalConfig, ProjectConfig

# ── fixtures ─────────────────────────────────────────────────────────────


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal repo skeleton with config/ + workspaces/ dirs."""
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    return tmp_path


def _write_global_configs(
    root: Path,
    *,
    models: dict | None = None,
    runtime: dict | None = None,
    agents: dict[str, object] | None = None,
    server: dict | None = None,
) -> None:
    if models is not None:
        (root / "config" / "models.yaml").write_text(
            yaml.safe_dump(models, allow_unicode=True), encoding="utf-8"
        )
    if runtime is not None:
        (root / "config" / "runtime.yaml").write_text(
            yaml.safe_dump(runtime, allow_unicode=True), encoding="utf-8"
        )
    if agents is not None:
        (root / "config" / "agents.yaml").write_text(
            yaml.safe_dump(agents, allow_unicode=True), encoding="utf-8"
        )
    if server is not None:
        (root / "config" / "server.yaml").write_text(
            yaml.safe_dump(server, allow_unicode=True), encoding="utf-8"
        )


def _make_project(root: Path, project_id: str, config: dict) -> Path:
    proj = root / "workspaces" / project_id
    proj.mkdir(parents=True)
    (proj / "config.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )
    return proj


# ── load_global ──────────────────────────────────────────────────────────


class TestLoadGlobal:
    def test_merges_models_runtime_agents_server(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        _write_global_configs(
            root,
            models={"tiers": {"premium": {"provider": "openai", "model_env": "X", "rpm": 5}}},
            runtime={"runner": {"timeout_seconds": 42}},
            agents={"default_tools": ["read", "write"]},
            server={"server": {"host": "0.0.0.0", "port": 9999, "allow_origins": ["*"]}},
        )
        cfg = ConfigLoader(root).load_global()
        assert isinstance(cfg, GlobalConfig)
        assert cfg.models.tiers["premium"].provider == "openai"
        assert cfg.models.tiers["premium"].rpm == 5
        assert cfg.runtime.runner["timeout_seconds"] == 42
        assert cfg.server.host == "0.0.0.0"
        assert cfg.server.port == 9999
        assert cfg.server.allow_origins == ["*"]
        assert isinstance(cfg.agents, AgentsConfig)
        assert cfg.agents.default_tools == ["read", "write"]

    def test_missing_files_yield_defaults(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        # No yaml files written.
        cfg = ConfigLoader(root).load_global()
        assert cfg.models.tiers == {}
        assert cfg.agents.default_tools == []  # AgentsConfig default is empty list
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 8000

    def test_agents_wrapper_stripped(self, tmp_path: Path) -> None:
        """agents.yaml may be written either as ``agents:`` wrapping or as the
        bare mapping — the loader handles both like models.yaml / runtime.yaml."""
        root = _make_repo(tmp_path)
        _write_global_configs(
            root, agents={"agents": {"default_tools": ["alpha"]}}
        )
        cfg = ConfigLoader(root).load_global()
        assert cfg.agents.default_tools == ["alpha"]

    def test_run_override_wins(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        _write_global_configs(root, server={"server": {"host": "1.1.1.1", "port": 1234}})
        cfg = ConfigLoader(root).load_global(
            run_override={"server": {"host": "9.9.9.9"}}
        )
        assert cfg.server.host == "9.9.9.9"
        assert cfg.server.port == 1234  # untouched from file


# ── load_project ─────────────────────────────────────────────────────────


class TestLoadProject:
    def test_merges_global_and_project(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        _write_global_configs(
            root,
            server={"server": {"host": "127.0.0.1", "port": 8000, "allow_origins": ["http://x"]}},
        )
        _make_project(
            root,
            "proj_aaaa1111",
            {"display_name": "My Novel", "mode": "novel"},
        )
        cfg = ConfigLoader(root).load_project("proj_aaaa1111")
        assert isinstance(cfg, ProjectConfig)
        assert cfg.display_name == "My Novel"
        assert cfg.mode == "novel"
        # Inherited from global:
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.allow_origins == ["http://x"]

    def test_project_overrides_global_field(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        _write_global_configs(
            root,
            server={"server": {"host": "127.0.0.1", "port": 8000, "allow_origins": []}},
        )
        _make_project(
            root,
            "proj_bbbb2222",
            {
                "display_name": "RP Test",
                "mode": "rp",
                "server": {"port": 9000},
            },
        )
        cfg = ConfigLoader(root).load_project("proj_bbbb2222")
        assert cfg.display_name == "RP Test"
        assert cfg.mode == "rp"
        # Override:
        assert cfg.server.port == 9000
        # Inherited (not overridden):
        assert cfg.server.host == "127.0.0.1"

    def test_missing_project_config_raises(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        # No project created.
        cfg = ConfigLoader(root).load_project("proj_nope000")
        # ProjectConfig has defaults for display_name/mode even with no file.
        assert cfg.display_name == ""
        assert cfg.mode == "novel"

    def test_run_override_wins_over_project(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        _make_project(root, "proj_cccc3333", {"display_name": "Original", "mode": "novel"})
        cfg = ConfigLoader(root).load_project(
            "proj_cccc3333",
            run_override={"display_name": "Overridden"},
        )
        assert cfg.display_name == "Overridden"
        assert cfg.mode == "novel"

    def test_project_overrides_agents_default_tools(self, tmp_path: Path) -> None:
        """Per-project ``agents.default_tools`` in config.yaml overrides the
        global ``config/agents.yaml`` value via deep-merge — list replaced
        wholesale (per :func:`app.config_loader._deep_merge` semantics)."""
        root = _make_repo(tmp_path)
        _write_global_configs(
            root, agents={"default_tools": ["read", "write"]}
        )
        _make_project(
            root,
            "proj_dddd4444",
            {
                "display_name": "P",
                "mode": "novel",
                "agents": {"default_tools": ["read"]},
            },
        )
        cfg = ConfigLoader(root).load_project("proj_dddd4444")
        assert isinstance(cfg, ProjectConfig)
        assert cfg.agents.default_tools == ["read"]  # project override wins
