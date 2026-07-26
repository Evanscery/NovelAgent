"""Tests for /api/chat routes (httpx TestClient against FastAPI).

Covers the todo-22 acceptance criteria:
* GET history returns the chronological message list.
* POST message appends user + director messages and commits a Turn.
* DELETE message rolls back the project's git to the Turn *before* the
  message (verified via git log — the rollback creates a NEW branch per
  guide:314-316, the original timeline is preserved).
* POST retry rolls back + re-sends, returning the new reply + branch name.

The director reply path is mocked via ``CHAT_RUNNER_FACTORY`` so no LLM
is contacted (the chat path uses :class:`MockRunner` by default, which
returns deterministic canned text).
"""

from __future__ import annotations

import json
from pathlib import Path

import git
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.routes import chat as chat_routes
from app.api.server import create_app
from app.runtime.runners.mock_runner import MockRunner

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    """Build a minimal repo root with config/ + workspaces/ skeleton."""
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
    chat_routes.CHAT_RUNNER_FACTORY = lambda root, project_id: MockRunner()
    app = create_app(app_root)
    return TestClient(app)


@pytest.fixture()
def project_id(client: TestClient) -> str:
    resp = client.post("/api/projects", json={"display_name": "Chat Test", "mode": "novel"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture()
def project_path(app_root: Path, project_id: str) -> Path:
    return app_root / "workspaces" / project_id


def _git_log_messages(project_path: Path) -> list[str]:
    """Return the commit messages of the project's git log (newest-first)."""
    repo = git.Repo(str(project_path))
    return [c.message.strip() for c in repo.iter_commits()]


def _git_branches(project_path: Path) -> list[str]:
    repo = git.Repo(str(project_path))
    return sorted(b.name for b in repo.branches)


def _read_chat_log(project_path: Path) -> list[dict[str, object]]:
    log = project_path / "work" / "chat.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── GET /api/chat/{project_id} ───────────────────────────────────────────


class TestGetChatHistory:
    def test_empty_history(self, client: TestClient, project_id: str) -> None:
        resp = client.get(f"/api/chat/{project_id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_after_send(self, client: TestClient, project_id: str) -> None:
        client.post(f"/api/chat/{project_id}", json={"content": "hello director"})
        resp = client.get(f"/api/chat/{project_id}")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 2  # user + director
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello director"
        assert msgs[1]["role"] == "director"

    def test_missing_project_404(self, client: TestClient) -> None:
        resp = client.get("/api/chat/proj_nope000")
        assert resp.status_code == 404


# ── POST /api/chat/{project_id} ──────────────────────────────────────────


class TestSendChatMessage:
    def test_send_returns_user_and_director_messages(
        self, client: TestClient, project_id: str
    ) -> None:
        resp = client.post(f"/api/chat/{project_id}", json={"content": "hi"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_message"]["role"] == "user"
        assert body["user_message"]["content"] == "hi"
        assert body["user_message"]["message_id"].startswith("msg_")
        assert body["user_message"]["turn_id"]
        assert body["director_message"] is not None
        assert body["director_message"]["role"] == "director"
        # Both messages share the same turn_id (one Turn per exchange).
        assert body["user_message"]["turn_id"] == body["director_message"]["turn_id"]

    def test_send_appends_to_chat_log(
        self, client: TestClient, project_id: str, project_path: Path
    ) -> None:
        client.post(f"/api/chat/{project_id}", json={"content": "first"})
        client.post(f"/api/chat/{project_id}", json={"content": "second"})
        log = _read_chat_log(project_path)
        assert len(log) == 4  # 2 exchanges × (user + director)
        assert log[0]["content"] == "first"
        assert log[2]["content"] == "second"

    def test_send_commits_turn(
        self, client: TestClient, project_id: str, project_path: Path
    ) -> None:
        # Initial Turn 0 commit from scaffold_project.
        before = _git_log_messages(project_path)
        assert any("Turn 0" in m for m in before)
        client.post(f"/api/chat/{project_id}", json={"content": "hello"})
        after = _git_log_messages(project_path)
        # One new Turn commit was added (newest first).
        assert len(after) == len(before) + 1
        assert "Turn " in after[0]

    def test_send_empty_content_422(self, client: TestClient, project_id: str) -> None:
        resp = client.post(f"/api/chat/{project_id}", json={"content": ""})
        assert resp.status_code == 422

    def test_send_missing_project_404(self, client: TestClient) -> None:
        resp = client.post("/api/chat/proj_nope000", json={"content": "hi"})
        assert resp.status_code == 404


# ── DELETE /api/chat/{project_id}/{message_id} ───────────────────────────


class TestDeleteChatMessage:
    def test_delete_rolls_back_to_before_message(
        self, client: TestClient, project_id: str, project_path: Path
    ) -> None:
        """Send 3 messages, delete #2, assert state rolled back to after #1.

        Per guide:412 delete is synced to backend rollback. Per
        guide:314-316 rollback = new branch (NOT delete) — the original
        timeline is preserved on its old branch.
        """
        # Send 3 exchanges → 6 messages in the log, 3 Turn commits on top
        # of the initial Turn 0.
        ids: list[str] = []
        for content in ("one", "two", "three"):
            resp = client.post(f"/api/chat/{project_id}", json={"content": content})
            ids.append(resp.json()["user_message"]["message_id"])

        log_before = _read_chat_log(project_path)
        assert len(log_before) == 6
        branches_before = _git_branches(project_path)
        assert branches_before == ["main"]

        # Delete the 2nd user message → roll back to the Turn that
        # preceded it (the Turn from exchange "one").
        target_msg_id = ids[1]
        resp = client.delete(f"/api/chat/{project_id}/{target_msg_id}")
        assert resp.status_code == 200, resp.text

        # After rollback the chat log on disk reflects the state at the
        # rollback target → only exchange "one" survives (2 messages).
        surviving = resp.json()
        assert len(surviving) == 2
        assert surviving[0]["content"] == "one"
        assert surviving[1]["role"] == "director"

        # A NEW branch was created (rollback mode='branch', guide:314-316).
        branches_after = _git_branches(project_path)
        assert "main" in branches_after, "original timeline must be preserved"
        rollback_branches = [b for b in branches_after if b.startswith("rollback/")]
        assert len(rollback_branches) >= 1, f"expected a rollback/* branch, got {branches_after}"

        # The current branch is the rollback branch (checked out).
        repo = git.Repo(str(project_path))
        assert repo.active_branch.name.startswith("rollback/")

        # The chat log on disk matches the surviving messages.
        log_after = _read_chat_log(project_path)
        assert len(log_after) == 2
        assert log_after[0]["content"] == "one"

    def test_delete_first_message_rolls_back_to_turn_0(
        self, client: TestClient, project_id: str, project_path: Path
    ) -> None:
        """Deleting the first message rolls back to the initial Turn 0
        (written by scaffold_project) — the chat log becomes empty."""
        resp = client.post(f"/api/chat/{project_id}", json={"content": "first"})
        first_id = resp.json()["user_message"]["message_id"]
        delete = client.delete(f"/api/chat/{project_id}/{first_id}")
        assert delete.status_code == 200
        surviving = delete.json()
        # Turn 0 has an empty chat log.
        assert surviving == []
        log_after = _read_chat_log(project_path)
        assert log_after == []

    def test_delete_unknown_message_404(
        self, client: TestClient, project_id: str
    ) -> None:
        resp = client.delete(f"/api/chat/{project_id}/msg_nope0000")
        assert resp.status_code == 404

    def test_delete_missing_project_404(self, client: TestClient) -> None:
        resp = client.delete("/api/chat/proj_nope000/msg_nope0000")
        assert resp.status_code == 404


# ── POST /api/chat/{project_id}/{message_id}/retry ───────────────────────


class TestRetryChatMessage:
    def test_retry_rolls_back_and_resends(
        self, client: TestClient, project_id: str, project_path: Path
    ) -> None:
        """Send 2 messages, retry #1 → rolls back to Turn 0, re-sends #1,
        returns the new reply + a branch name."""
        ids: list[str] = []
        for content in ("alpha", "beta"):
            resp = client.post(f"/api/chat/{project_id}", json={"content": content})
            ids.append(resp.json()["user_message"]["message_id"])

        log_before = _read_chat_log(project_path)
        assert len(log_before) == 4  # 2 exchanges

        # Retry the FIRST user message ("alpha").
        resp = client.post(f"/api/chat/{project_id}/{ids[0]}/retry")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["branch"].startswith("rollback/")
        assert body["user_message"]["content"] == "alpha"
        assert body["user_message"]["message_id"] != ids[0]  # new message id
        assert body["director_message"] is not None
        assert body["director_message"]["role"] == "director"

        # After retry: the chat log reflects Turn 0 (empty) + the new
        # "alpha" exchange → 2 messages.
        log_after = _read_chat_log(project_path)
        assert len(log_after) == 2
        assert log_after[0]["content"] == "alpha"
        assert log_after[1]["role"] == "director"

        # A rollback branch was created and is now the active branch.
        repo = git.Repo(str(project_path))
        assert repo.active_branch.name.startswith("rollback/")

    def test_retry_unknown_message_404(
        self, client: TestClient, project_id: str
    ) -> None:
        resp = client.post(f"/api/chat/{project_id}/msg_nope0000/retry")
        assert resp.status_code == 404

    def test_retry_director_message_400(
        self, client: TestClient, project_id: str
    ) -> None:
        """Retry is only allowed on user messages — a director message
        returns 400."""
        resp = client.post(f"/api/chat/{project_id}", json={"content": "hi"})
        director_id = resp.json()["director_message"]["message_id"]
        retry = client.post(f"/api/chat/{project_id}/{director_id}/retry")
        assert retry.status_code == 400
        assert "user" in retry.json()["detail"].lower()

    def test_retry_missing_project_404(self, client: TestClient) -> None:
        resp = client.post("/api/chat/proj_nope000/msg_nope0000/retry")
        assert resp.status_code == 404
