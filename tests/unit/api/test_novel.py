"""Tests for /api/novel routes (httpx TestClient against FastAPI).

Covers the todo-23 acceptance criteria for the novel viewer:
* GET /api/novel/{project_id} lists chapters in novels/.
* GET /api/novel/{project_id}/{chapter} reads chapter content
  (by filename, bare stem, or numeric chapter).
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


def _make_project(client: TestClient, display_name: str = "Test") -> str:
    resp = client.post("/api/projects", json={"display_name": display_name, "mode": "novel"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _write_chapter(app_root: Path, pid: str, filename: str, content: str) -> Path:
    novels = app_root / "workspaces" / pid / "novels"
    novels.mkdir(parents=True, exist_ok=True)
    path = novels / filename
    path.write_text(content, encoding="utf-8")
    return path


# ── GET /api/novel/{project_id} ──────────────────────────────────────────


class TestListChapters:
    def test_empty_when_no_chapters(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/novel/{pid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == pid
        assert body["chapters"] == []

    def test_lists_chapter_files(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        _write_chapter(app_root, pid, "chapter_01.txt", "Chapter 1 content")
        _write_chapter(app_root, pid, "chapter_02.txt", "Chapter 2 content")
        # Non-txt file should be skipped.
        (app_root / "workspaces" / pid / "novels" / "notes.md").write_text(
            "ignore me", encoding="utf-8"
        )
        resp = client.get(f"/api/novel/{pid}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["chapters"]) == 2
        filenames = [c["filename"] for c in body["chapters"]]
        assert filenames == ["chapter_01.txt", "chapter_02.txt"]
        assert body["chapters"][0]["chapter_number"] == 1
        assert body["chapters"][1]["chapter_number"] == 2
        assert body["chapters"][0]["size_bytes"] > 0

    def test_non_numbered_chapter_has_null_number(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        _write_chapter(app_root, pid, "epilogue.txt", "Epilogue content")
        resp = client.get(f"/api/novel/{pid}")
        body = resp.json()
        assert len(body["chapters"]) == 1
        assert body["chapters"][0]["chapter_number"] is None
        assert body["chapters"][0]["filename"] == "epilogue.txt"

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.get("/api/novel/proj_nope000")
        assert resp.status_code == 404


# ── GET /api/novel/{project_id}/{chapter} ────────────────────────────────


class TestReadChapter:
    def test_read_by_filename(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        _write_chapter(app_root, pid, "chapter_01.txt", "The beginning.")
        resp = client.get(f"/api/novel/{pid}/chapter_01.txt")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["filename"] == "chapter_01.txt"
        assert body["chapter_number"] == 1
        assert body["content"] == "The beginning."

    def test_read_by_stem(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        _write_chapter(app_root, pid, "chapter_01.txt", "Stem lookup works.")
        resp = client.get(f"/api/novel/{pid}/chapter_01")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Stem lookup works."

    def test_read_by_number_padded(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        _write_chapter(app_root, pid, "chapter_01.txt", "Numeric lookup.")
        resp = client.get(f"/api/novel/{pid}/1")
        assert resp.status_code == 200
        assert resp.json()["content"] == "Numeric lookup."
        assert resp.json()["chapter_number"] == 1

    def test_read_by_number_unpadded(self, client: TestClient, app_root: Path) -> None:
        pid = _make_project(client)
        _write_chapter(app_root, pid, "chapter_5.txt", "Unpadded numeric.")
        resp = client.get(f"/api/novel/{pid}/5")
        assert resp.status_code == 200
        assert resp.json()["filename"] == "chapter_5.txt"

    def test_read_missing_chapter_404(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/novel/{pid}/chapter_99.txt")
        assert resp.status_code == 404

    def test_read_traversal_rejected_400(self, client: TestClient) -> None:
        pid = _make_project(client)
        # Starlette's router rejects ``..`` and ``%2F`` at the URL layer
        # (returns 404 before the handler runs), so the project_id 404
        # covers HTTP-layer traversal. The handler's own traversal guard
        # is exercised directly in test_resolve_chapter_path_rejects_traversal.
        resp = client.get(f"/api/novel/{pid}/..")
        # FastAPI returns 404 for ``..`` path segments at the routing layer.
        assert resp.status_code in (400, 404)

    def test_read_traversal_with_separator_400(self, client: TestClient) -> None:
        pid = _make_project(client)
        resp = client.get(f"/api/novel/{pid}/sub%2Fchapter_01.txt")
        # %2F is rejected by Starlette's router before the handler.
        assert resp.status_code in (400, 404)

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.get("/api/novel/proj_nope000/chapter_01.txt")
        assert resp.status_code == 404


# ── Direct unit tests for the chapter-path traversal guard ───────────────


class TestResolveChapterPathGuard:
    """The handler's own traversal guard is defense-in-depth: Starlette's
    router rejects ``..`` / ``/`` in path params at the URL layer, so we
    exercise the guard directly to prove it rejects traversal inputs that
    would reach it via other front-ends or future route changes.
    """

    def test_rejects_dotdot(self, tmp_path: Path) -> None:
        from app.api.routes.novel import _resolve_chapter_path

        with pytest.raises(Exception):  # noqa: PT011 — HTTPException subclass
            _resolve_chapter_path(tmp_path, "..")

    def test_rejects_separator(self, tmp_path: Path) -> None:
        from app.api.routes.novel import _resolve_chapter_path

        with pytest.raises(Exception):  # noqa: PT011
            _resolve_chapter_path(tmp_path, "sub/chapter_01.txt")

    def test_rejects_null_byte(self, tmp_path: Path) -> None:
        from app.api.routes.novel import _resolve_chapter_path

        with pytest.raises(Exception):  # noqa: PT011
            _resolve_chapter_path(tmp_path, "chapter\x00.txt")
