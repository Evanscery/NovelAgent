"""Tests for /api/projects routes (httpx TestClient against FastAPI).

Covers the todo-21 acceptance criteria:
* POST creates a project with a system-generated id.
* The project has 8 resource dirs, each with properties.md.
* GET returns the list.
* PATCH updates display_name.
* DELETE removes the workspace.
* POST with a user-supplied id is ignored (id is system-controlled).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.data.resource_types import RESOURCE_TYPE_REGISTRY
from app.project_paths import resolve_project_path

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    """Build a minimal repo root with config/ + workspaces/ skeleton."""
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    # Minimal server.yaml so create_app boots with sane defaults.
    (tmp_path / "config" / "server.yaml").write_text(
        yaml.safe_dump(
            {"server": {"host": "127.0.0.1", "port": 8000, "allow_origins": [], "ip_whitelist": []}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def client(app_root: Path) -> TestClient:
    app = create_app(app_root)
    return TestClient(app)


# ── POST /api/projects ───────────────────────────────────────────────────


class TestCreateProject:
    def test_create_returns_201_with_system_id(self, client: TestClient, app_root: Path) -> None:
        resp = client.post("/api/projects", json={"display_name": "My Novel", "mode": "novel"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"].startswith("proj_")
        assert body["display_name"] == "My Novel"
        assert body["mode"] == "novel"
        # Workspace dir actually exists.
        proj_path = resolve_project_path(app_root, body["id"])
        assert proj_path.exists()
        assert (proj_path / "config.yaml").exists()

    def test_create_scaffolds_8_resource_dirs(self, client: TestClient, app_root: Path) -> None:
        resp = client.post("/api/projects", json={"display_name": "Scaffold Test"})
        assert resp.status_code == 201
        pid = resp.json()["id"]
        resources = app_root / "workspaces" / pid / "resources"
        assert resources.is_dir()
        for type_name in RESOURCE_TYPE_REGISTRY:
            d = resources / type_name
            assert d.is_dir(), f"Missing resource dir: {type_name}"
            assert (d / "properties.md").is_file(), f"Missing properties.md in {type_name}"
            assert (d / "manifest.json").is_file(), f"Missing manifest.json in {type_name}"

    def test_create_copies_default_workflow(self, client: TestClient, app_root: Path) -> None:
        resp = client.post("/api/projects", json={"display_name": "WF"})
        assert resp.status_code == 201
        pid = resp.json()["id"]
        wf = app_root / "workspaces" / pid / "workflow.yaml"
        assert wf.is_file()
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        assert "nodes" in data and "wires" in data

    def test_create_inits_independent_git(self, client: TestClient, app_root: Path) -> None:
        resp = client.post("/api/projects", json={"display_name": "Git Test"})
        pid = resp.json()["id"]
        dot_git = app_root / "workspaces" / pid / ".git"
        assert dot_git.is_dir()

    def test_create_rp_mode(self, client: TestClient, app_root: Path) -> None:
        resp = client.post("/api/projects", json={"display_name": "RP", "mode": "rp"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["mode"] == "rp"
        cfg = yaml.safe_load(
            (app_root / "workspaces" / body["id"] / "config.yaml").read_text(encoding="utf-8")
        )
        assert cfg["mode"] == "rp"

    def test_create_invalid_mode_400(self, client: TestClient) -> None:
        resp = client.post("/api/projects", json={"display_name": "X", "mode": "bogus"})
        assert resp.status_code == 400

    def test_create_empty_display_name_422(self, client: TestClient) -> None:
        resp = client.post("/api/projects", json={"display_name": "", "mode": "novel"})
        assert resp.status_code == 422

    def test_user_supplied_id_is_ignored(self, client: TestClient) -> None:
        # The schema does not declare `id`, so pydantic ignores extra fields
        # by default. The server always generates the id.
        resp = client.post(
            "/api/projects",
            json={"display_name": "Ignored Id", "mode": "novel", "id": "user_attempt"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"].startswith("proj_")
        assert body["id"] != "user_attempt"


# ── GET /api/projects ────────────────────────────────────────────────────


class TestListProjects:
    def test_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == {"projects": []}

    def test_list_includes_created(self, client: TestClient) -> None:
        client.post("/api/projects", json={"display_name": "A"})
        client.post("/api/projects", json={"display_name": "B", "mode": "rp"})
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        names = {p["display_name"] for p in resp.json()["projects"]}
        assert names == {"A", "B"}


# ── GET /api/projects/{id} ───────────────────────────────────────────────


class TestGetProject:
    def test_get_existing(self, client: TestClient) -> None:
        create = client.post("/api/projects", json={"display_name": "Detail"})
        pid = create.json()["id"]
        resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Detail"

    def test_get_missing_404(self, client: TestClient) -> None:
        resp = client.get("/api/projects/proj_nope000")
        assert resp.status_code == 404

    def test_get_traversal_404(self, client: TestClient) -> None:
        resp = client.get("/api/projects/..")
        assert resp.status_code == 404


# ── PATCH /api/projects/{id} ─────────────────────────────────────────────


class TestPatchProject:
    def test_update_display_name(self, client: TestClient, app_root: Path) -> None:
        create = client.post("/api/projects", json={"display_name": "Old"})
        pid = create.json()["id"]
        resp = client.patch(f"/api/projects/{pid}", json={"display_name": "New"})
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "New"
        # Persisted to config.yaml:
        cfg = yaml.safe_load(
            (app_root / "workspaces" / pid / "config.yaml").read_text(encoding="utf-8")
        )
        assert cfg["display_name"] == "New"

    def test_update_mode(self, client: TestClient) -> None:
        create = client.post("/api/projects", json={"display_name": "M", "mode": "novel"})
        pid = create.json()["id"]
        resp = client.patch(f"/api/projects/{pid}", json={"mode": "rp"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "rp"

    def test_update_invalid_mode_400(self, client: TestClient) -> None:
        create = client.post("/api/projects", json={"display_name": "M"})
        pid = create.json()["id"]
        resp = client.patch(f"/api/projects/{pid}", json={"mode": "bogus"})
        assert resp.status_code == 400

    def test_update_no_fields_400(self, client: TestClient) -> None:
        create = client.post("/api/projects", json={"display_name": "M"})
        pid = create.json()["id"]
        resp = client.patch(f"/api/projects/{pid}", json={})
        assert resp.status_code == 400

    def test_update_missing_404(self, client: TestClient) -> None:
        resp = client.patch("/api/projects/proj_nope000", json={"display_name": "X"})
        assert resp.status_code == 404


# ── DELETE /api/projects/{id} ────────────────────────────────────────────


class TestDeleteProject:
    def test_delete_removes_workspace(self, client: TestClient, app_root: Path) -> None:
        create = client.post("/api/projects", json={"display_name": "Doomed"})
        pid = create.json()["id"]
        ws = app_root / "workspaces" / pid
        assert ws.exists()
        resp = client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 204
        assert not ws.exists()

    def test_delete_then_get_404(self, client: TestClient) -> None:
        create = client.post("/api/projects", json={"display_name": "X"})
        pid = create.json()["id"]
        client.delete(f"/api/projects/{pid}")
        resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 404

    def test_delete_missing_404(self, client: TestClient) -> None:
        resp = client.delete("/api/projects/proj_nope000")
        assert resp.status_code == 404
