"""Tests for /api/import route (httpx TestClient against FastAPI).

The import endpoint is a stub in todo 23 — the actual card-migration
logic lands in todo 34 (``app/compat/tavern_card/card_migration.py``).
The handler must return ``501 Not Implemented`` with a clear message
regardless of the request body, so the front-end can wire its button
against a stable contract today.
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
    return tmp_path


@pytest.fixture()
def client(app_root: Path) -> TestClient:
    app = create_app(app_root)
    return TestClient(app)


# ── POST /api/import ─────────────────────────────────────────────────────


class TestImportStub:
    def test_returns_501_with_empty_body(self, client: TestClient) -> None:
        resp = client.post("/api/import", json={})
        assert resp.status_code == 501, resp.text
        body = resp.json()
        assert "todo 34" in body["detail"].lower()

    def test_returns_501_with_full_body(self, client: TestClient) -> None:
        resp = client.post(
            "/api/import",
            json={
                "source": "card.json",
                "project_id": "proj_abc12345",
                "format": "tavern_card",
            },
        )
        assert resp.status_code == 501
        body = resp.json()
        # Message must point at todo 34 so a developer reading the error
        # knows where the real implementation lands.
        assert "todo 34" in body["detail"].lower()
        # And mention the compat layer so the contract is clear.
        assert "compat" in body["detail"].lower() or "tavern" in body["detail"].lower()

    def test_returns_501_regardless_of_body(self, client: TestClient) -> None:
        # Even a "valid-looking" request must not partially import — the
        # stub always returns 501 until todo 34 implements the logic.
        for body in (
            {"source": None, "project_id": None, "format": None},
            {"source": "https://example.com/card.json"},
            {"format": "tavern_card", "project_id": "proj_x"},
        ):
            resp = client.post("/api/import", json=body)
            assert resp.status_code == 501, f"body={body} got {resp.status_code}"
