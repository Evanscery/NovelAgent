"""Tests for /api/import route (httpx TestClient against FastAPI).

The import endpoint (todo 34) delegates to ``app/compat/tavern_card/``:

* A valid card file / inline payload -> ``201`` with ``project_id`` +
  ``resources_created``.
* A non-card payload -> ``400 "not a recognized card format"``.
* Missing both ``source`` and ``card`` -> ``400``.
* Non-existent ``source`` path -> ``400``.
* Non-existent ``project_id`` target -> ``404``.

The old stub (todo 23) returned ``501`` for every request; those
expectations are replaced here by the real card-import flow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.server import create_app

# ── Sample card ─────────────────────────────────────────────────────────


_SAMPLE_CARD_V2: dict[str, object] = {
    "spec": "chara_card_v2",
    "spec_version": "2.0",
    "data": {
        "name": "Aria",
        "description": "A lone wanderer with a hidden past.",
        "personality": "Stoic, observant, fiercely loyal to friends.",
        "scenario": "A desert trading post. Aria owes favorability to the innkeeper.",
        "first_mes": "*The wind howls.* \"Water. And a room.\"",
        "mes_example": "*Example dialogue.*",
        "alternate_greetings": ["*Alt opening.*"],
        "character_book": {
            "entries": [
                {"name": "world_rule", "content": "Magic is rare and feared."},
            ]
        },
    },
}


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
    return tmp_path


@pytest.fixture()
def client(app_root: Path) -> TestClient:
    app = create_app(app_root)
    return TestClient(app)


@pytest.fixture()
def card_file(app_root: Path) -> Path:
    """Write the sample card to a temp file inside the repo root."""
    card_path = app_root / "sample_card.json"
    card_path.write_text(json.dumps(_SAMPLE_CARD_V2, ensure_ascii=False), encoding="utf-8")
    return card_path


# ── POST /api/import — happy path ────────────────────────────────────────


class TestImportCard:
    def test_import_inline_card_returns_201(self, client: TestClient) -> None:
        resp = client.post("/api/import", json={"card": _SAMPLE_CARD_V2})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"].startswith("proj_")
        assert body["display_name"] == "Aria"
        assert "worldbook" in body["resources_created"]
        assert "state" in body["resources_created"]

    def test_import_card_file_returns_201(self, client: TestClient, card_file: Path) -> None:
        resp = client.post("/api/import", json={"source": str(card_file)})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"].startswith("proj_")

    def test_import_creates_workspace_dir(self, client: TestClient, app_root: Path) -> None:
        resp = client.post("/api/import", json={"card": _SAMPLE_CARD_V2})
        assert resp.status_code == 201
        pid = resp.json()["project_id"]
        workspace = app_root / "workspaces" / pid
        assert workspace.exists()
        assert (workspace / "config.yaml").exists()
        # 8 resource dirs scaffolded.
        resources = workspace / "resources"
        assert resources.is_dir()
        for type_name in (
            "outline",
            "short_goal",
            "state",
            "variables",
            "worldbook",
            "facts",
            "character_memory",
            "notes",
        ):
            assert (resources / type_name).is_dir()

    def test_import_writes_card_content_to_resources(
        self, client: TestClient, app_root: Path
    ) -> None:
        resp = client.post("/api/import", json={"card": _SAMPLE_CARD_V2})
        assert resp.status_code == 201
        pid = resp.json()["project_id"]
        state = (app_root / "workspaces" / pid / "resources" / "state" / "content.md").read_text(
            encoding="utf-8"
        )
        assert "wind howls" in state

    def test_import_with_display_name_override(self, client: TestClient) -> None:
        resp = client.post(
            "/api/import",
            json={"card": _SAMPLE_CARD_V2, "display_name": "Custom Name"},
        )
        assert resp.status_code == 201
        assert resp.json()["display_name"] == "Custom Name"

    def test_import_with_mode_override(self, client: TestClient) -> None:
        resp = client.post(
            "/api/import",
            json={"card": _SAMPLE_CARD_V2, "mode": "novel"},
        )
        assert resp.status_code == 201
        assert resp.json()["mode"] == "novel"

    def test_import_into_existing_project(
        self, client: TestClient, app_root: Path
    ) -> None:
        # First create a project via /api/projects.
        create = client.post("/api/projects", json={"display_name": "Target"})
        assert create.status_code == 201
        target_id = create.json()["id"]

        # Now import into it.
        resp = client.post(
            "/api/import",
            json={"card": _SAMPLE_CARD_V2, "project_id": target_id},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["project_id"] == target_id


# ── POST /api/import — error paths ──────────────────────────────────────


class TestImportErrors:
    def test_missing_source_and_card_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/import", json={})
        assert resp.status_code == 400
        assert "source" in resp.json()["detail"].lower() or "card" in resp.json()["detail"].lower()

    def test_non_card_payload_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/import", json={"card": {"foo": "bar"}})
        assert resp.status_code == 400
        assert "not a recognized card format" in resp.json()["detail"].lower()

    def test_nonexistent_source_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/import", json={"source": "/no/such/card.json"})
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    def test_nonexistent_project_id_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/import",
            json={"card": _SAMPLE_CARD_V2, "project_id": "proj_nope000"},
        )
        assert resp.status_code == 404

    def test_invalid_mode_override_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/import",
            json={"card": _SAMPLE_CARD_V2, "mode": "bogus"},
        )
        assert resp.status_code == 400
        assert "mode" in resp.json()["detail"].lower()
