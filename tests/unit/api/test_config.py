"""Tests for /api/config routes (httpx TestClient against FastAPI).

Covers the todo-23 acceptance criteria for the config page:
* GET global config returns models/runtime/agents/server tiers.
* PUT global config writes back to the yaml files (including agents tier).
* GET project config returns the merged per-project config.
* PUT project config updates display_name / mode / overrides
  (including agents overrides).
* GET project agents lists all 6 built-in agents (5 workflow + director).
* PUT project agent edits one agent's attribute set (writer's model).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.server import create_app

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "config" / "server.yaml").write_text(
        yaml.safe_dump(
            {"server": {"host": "127.0.0.1", "port": 8000, "allow_origins": [], "ip_whitelist": []}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "models.yaml").write_text(
        yaml.safe_dump(
            {
                "tiers": {
                    "premium": {"provider": "openai_compatible", "model_env": "MODEL_HIGH", "rpm": 3},
                    "standard": {"provider": "openai_compatible", "model_env": "MODEL_FAST", "rpm": 10},
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "runtime.yaml").write_text(
        yaml.safe_dump({"runner": {"timeout_seconds": 600, "max_retries": 3}}, allow_unicode=True),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def client(app_root: Path) -> TestClient:
    app = create_app(app_root)
    return TestClient(app)


@pytest.fixture()
def agents_root(tmp_path: Path) -> Path:
    """Like ``app_root`` but also writes ``config/agents.yaml`` with default_tools."""
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "config" / "server.yaml").write_text(
        yaml.safe_dump(
            {"server": {"host": "127.0.0.1", "port": 8000, "allow_origins": [], "ip_whitelist": []}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "models.yaml").write_text(
        yaml.safe_dump({"tiers": {}}, allow_unicode=True),
        encoding="utf-8",
    )
    (tmp_path / "config" / "runtime.yaml").write_text(
        yaml.safe_dump({"runner": {"timeout_seconds": 600}}, allow_unicode=True),
        encoding="utf-8",
    )
    (tmp_path / "config" / "agents.yaml").write_text(
        yaml.safe_dump(
            {"default_tools": ["read", "write", "list_files", "glob_files", "grep_lines", "read_lines"]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return tmp_path


def _make_project(client: TestClient, display_name: str = "Test") -> str:
    resp = client.post("/api/projects", json={"display_name": display_name, "mode": "novel"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── GET /api/config ──────────────────────────────────────────────────────


class TestGetGlobalConfig:
    def test_returns_all_tiers(self, client: TestClient) -> None:
        resp = client.get("/api/config")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == ""
        assert "tiers" in body["models"]
        assert body["models"]["tiers"]["premium"]["provider"] == "openai_compatible"
        assert body["runtime"]["runner"]["timeout_seconds"] == 600
        assert body["server"]["host"] == "127.0.0.1"

    def test_returns_defaults_when_files_missing(self, tmp_path: Path) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "workspaces").mkdir()
        (tmp_path / "config" / "server.yaml").write_text(
            yaml.safe_dump({"server": {"host": "127.0.0.1", "port": 8000}}),
            encoding="utf-8",
        )
        c = TestClient(create_app(tmp_path))
        resp = c.get("/api/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["models"] == {}
        assert body["runtime"] == {}


# ── PUT /api/config ──────────────────────────────────────────────────────


class TestPutGlobalConfig:
    def test_put_models_writes_file(self, client: TestClient, app_root: Path) -> None:
        new_models = {"tiers": {"cheap": {"provider": "anthropic", "model_env": "X", "rpm": 5}}}
        resp = client.put("/api/config", json={"models": new_models})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["models"]["tiers"]["cheap"]["provider"] == "anthropic"
        on_disk = yaml.safe_load((app_root / "config" / "models.yaml").read_text(encoding="utf-8"))
        assert on_disk["tiers"]["cheap"]["provider"] == "anthropic"

    def test_put_server_preserves_wrapper(self, client: TestClient, app_root: Path) -> None:
        resp = client.put(
            "/api/config",
            json={"server": {"host": "0.0.0.0", "port": 9000, "allow_origins": [], "ip_whitelist": []}},
        )
        assert resp.status_code == 200
        on_disk = yaml.safe_load((app_root / "config" / "server.yaml").read_text(encoding="utf-8"))
        assert on_disk["server"]["host"] == "0.0.0.0"
        assert on_disk["server"]["port"] == 9000

    def test_put_no_fields_400(self, client: TestClient) -> None:
        resp = client.put("/api/config", json={})
        assert resp.status_code == 400

    def test_put_omitted_tiers_preserved(self, client: TestClient, app_root: Path) -> None:
        resp = client.put("/api/config", json={"runtime": {"runner": {"timeout_seconds": 30}}})
        assert resp.status_code == 200
        # models.yaml untouched.
        on_disk = yaml.safe_load((app_root / "config" / "models.yaml").read_text(encoding="utf-8"))
        assert "premium" in on_disk["tiers"]


# ── GET /api/config/{project_id} ─────────────────────────────────────────


class TestGetProjectConfig:
    def test_returns_merged_config(self, client: TestClient) -> None:
        pid = _make_project(client, "My Novel")
        resp = client.get(f"/api/config/{pid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == pid
        assert body["display_name"] == "My Novel"
        assert body["mode"] == "novel"
        # Inherited from global.
        assert body["server"]["host"] == "127.0.0.1"
        assert "tiers" in body["models"]

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.get("/api/config/proj_nope000")
        assert resp.status_code == 404


# ── PUT /api/config/{project_id} ─────────────────────────────────────────


class TestPutProjectConfig:
    def test_update_display_name(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client, "Old")
        resp = client.put(f"/api/config/{pid}", json={"display_name": "New"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["display_name"] == "New"
        cfg = yaml.safe_load(
            (app_root / "workspaces" / pid / "config.yaml").read_text(encoding="utf-8")
        )
        assert cfg["display_name"] == "New"

    def test_update_mode(self, client: TestClient) -> None:
        pid = _make_project(client, "M")
        resp = client.put(f"/api/config/{pid}", json={"mode": "rp"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "rp"

    def test_update_invalid_mode_400(self, client: TestClient) -> None:
        pid = _make_project(client, "M")
        resp = client.put(f"/api/config/{pid}", json={"mode": "bogus"})
        assert resp.status_code == 400

    def test_update_no_fields_400(self, client: TestClient) -> None:
        pid = _make_project(client, "M")
        resp = client.put(f"/api/config/{pid}", json={})
        assert resp.status_code == 400

    def test_update_with_models_override(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client, "C")
        resp = client.put(
            f"/api/config/{pid}",
            json={"models": {"agent_models": {"writer": "premium"}}},
        )
        assert resp.status_code == 200
        cfg = yaml.safe_load(
            (app_root / "workspaces" / pid / "config.yaml").read_text(encoding="utf-8")
        )
        assert cfg["models"]["agent_models"]["writer"] == "premium"

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.put("/api/config/proj_nope000", json={"display_name": "X"})
        assert resp.status_code == 404


# ── GET /api/config/{project_id}/agents ──────────────────────────────────


class TestListProjectAgents:
    def test_lists_6_builtin_agents(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/config/{pid}/agents")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        names = {a["name"] for a in body}
        # 6 built-in agents: 5 workflow agents + director (system agent).
        assert names == {"director", "recaller", "scout", "writer", "critic", "maintainer"}

    def test_agent_has_all_attributes(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/config/{pid}/agents")
        body = resp.json()
        writer = next(a for a in body if a["name"] == "writer")
        for attr in ("name", "task", "input", "output", "permission", "model", "tools",
                     "head", "tail", "allow_recursive"):
            assert attr in writer, f"Missing attribute {attr!r}"

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.get("/api/config/proj_nope000/agents")
        assert resp.status_code == 404


# ── PUT /api/config/{project_id}/agents/{name} ───────────────────────────


class TestPutProjectAgent:
    def test_edit_writer_model(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        # Fetch the current writer config.
        resp = client.get(f"/api/config/{pid}/agents")
        writer = next(a for a in resp.json() if a["name"] == "writer")
        writer["model"] = "cheap"  # change the model
        resp = client.put(f"/api/config/{pid}/agents/writer", json=writer)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "writer"
        assert body["model"] == "cheap"
        # Override file written under the project workspace (preferred over
        # mutating the built-in definition).
        override = app_root / "workspaces" / pid / "agents" / "writer.yaml"
        assert override.is_file()
        on_disk = yaml.safe_load(override.read_text(encoding="utf-8"))
        assert on_disk["model"] == "cheap"
        # Built-in definition untouched — resolve from this test file's
        # location (the repo's app/agents/builtin/).
        builtin = Path(__file__).resolve().parents[3] / "app" / "agents" / "builtin" / "writer.yaml"
        builtin_disk = yaml.safe_load(builtin.read_text(encoding="utf-8"))
        assert builtin_disk["model"] == "premium"

    def test_edit_task(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/config/{pid}/agents")
        writer = next(a for a in resp.json() if a["name"] == "writer")
        writer["task"] = "新任务描述"
        resp = client.put(f"/api/config/{pid}/agents/writer", json=writer)
        assert resp.status_code == 200
        assert resp.json()["task"] == "新任务描述"

    def test_edit_name_mismatch_400(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/config/{pid}/agents")
        writer = next(a for a in resp.json() if a["name"] == "writer")
        writer["name"] = "renamed"
        resp = client.put(f"/api/config/{pid}/agents/writer", json=writer)
        assert resp.status_code == 400

    def test_edit_unknown_agent_404(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.put(
            f"/api/config/{pid}/agents/ghost",
            json={
                "name": "ghost",
                "task": "nope",
                "input": "none",
                "output": "none",
                "permission": {"read": [], "write": []},
            },
        )
        assert resp.status_code == 404

    def test_edit_invalid_permission_400(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/config/{pid}/agents")
        writer = next(a for a in resp.json() if a["name"] == "writer")
        # 'bogus_action' is not a valid permission action.
        writer["permission"] = {"bogus_action": ["state"]}
        resp = client.put(f"/api/config/{pid}/agents/writer", json=writer)
        assert resp.status_code == 400

    def test_edit_persists_across_reload(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/config/{pid}/agents")
        writer = next(a for a in resp.json() if a["name"] == "writer")
        writer["model"] = "cheap"
        client.put(f"/api/config/{pid}/agents/writer", json=writer)
        # Re-fetch the list — the override should be visible.
        resp = client.get(f"/api/config/{pid}/agents")
        writer_after = next(a for a in resp.json() if a["name"] == "writer")
        assert writer_after["model"] == "cheap"

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.put(
            "/api/config/proj_nope000/agents/writer",
            json={
                "name": "writer",
                "task": "x",
                "input": "x",
                "output": "x",
                "permission": {"read": [], "write": []},
            },
        )
        assert resp.status_code == 404


# ── /api/config — agents tier (config/agents.yaml) ───────────────────────


class TestGlobalAgentsTier:
    """Global config now also surfaces the agents tier (config/agents.yaml)."""

    def test_get_returns_agents_tier_when_file_present(self, agents_root: Path) -> None:
        c = TestClient(create_app(agents_root))
        resp = c.get("/api/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agents"] == {
            "default_tools": ["read", "write", "list_files", "glob_files", "grep_lines", "read_lines"]
        }

    def test_get_returns_empty_agents_tier_when_file_missing(self, app_root: Path) -> None:
        """No agents.yaml on disk → empty agents blob, route still 200."""
        c = TestClient(create_app(app_root))
        resp = c.get("/api/config")
        body = resp.json()
        assert body["agents"] == {}

    def test_put_agents_writes_file(self, agents_root: Path) -> None:
        c = TestClient(create_app(agents_root))
        new_agents = {"default_tools": ["read", "write"]}
        resp = c.put("/api/config", json={"agents": new_agents})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["agents"]["default_tools"] == ["read", "write"]
        on_disk = yaml.safe_load((agents_root / "config" / "agents.yaml").read_text(encoding="utf-8"))
        assert on_disk["default_tools"] == ["read", "write"]

    def test_put_no_models_runtime_agents_server_400(self, client: TestClient) -> None:
        resp = client.put("/api/config", json={})
        assert resp.status_code == 400
