"""W2 acceptance: a mock workflow round walks the full creation chain.

End-to-end via the real FastAPI app + scripted MockRunner:
POST run → director dispatches every flow agent → writable sub-agents
write through their own permission surface → finalize(final_text,
summary) → chapter lands in ``novels/`` → summary archived in
``turn_summary`` → everything commits as ONE ``Turn <id>:`` git commit
(audit findings F-1 / F-2 / F-6, plus Q-1 sub-agent tool loop).
"""

from __future__ import annotations

import time
from pathlib import Path

import git
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.routes import chat as chat_routes
from app.api.routes import workflow as workflow_routes
from app.api.server import create_app
from app.runtime.runners.mock_runner import MockRunner


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
        yaml.safe_dump({"runner": "mock"}, allow_unicode=True), encoding="utf-8"
    )
    (tmp_path / "config" / "runtime.yaml").write_text(
        yaml.safe_dump({"runner": {"timeout_seconds": 600}}, allow_unicode=True),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def client(app_root: Path) -> TestClient:
    workflow_routes.RUNNER_FACTORY = lambda root, project_id: MockRunner()
    chat_routes.CHAT_RUNNER_FACTORY = lambda root, project_id: MockRunner()
    return TestClient(create_app(app_root))


def _run_round(client: TestClient, pid: str) -> dict:
    run = client.post(f"/api/workflow/{pid}/run", json={})
    assert run.status_code == 202, run.text
    round_id = run.json()["round_id"]
    for _ in range(80):
        status = client.get(f"/api/workflow/{pid}/round/{round_id}").json()
        if status["state"] in ("completed", "failed", "stopped"):
            return status
        time.sleep(0.05)
    pytest.fail(f"round never finished: {status}")


class TestMockRoundEndToEnd:
    def test_full_creation_chain(self, client: TestClient, app_root: Path) -> None:
        created = client.post(
            "/api/projects", json={"display_name": "e2e", "mode": "novel"}
        )
        assert created.status_code == 201, created.text
        pid = created.json()["id"]
        project_path = app_root / "workspaces" / pid

        repo = git.Repo(str(project_path))
        commits_before = sum(1 for _ in repo.iter_commits("HEAD"))

        status = _run_round(client, pid)
        assert status["state"] == "completed", status
        result = status["result"]
        assert result["finalize_reason"] == "explicit_finalize"
        # Director dispatched the whole default workflow.
        assert len(result["completed_agents"]) > 1

        # F-1: the chapter landed where the novel viewer reads.
        chapters = sorted((project_path / "novels").glob("chapter_*.txt"))
        assert chapters, "no chapter file was written"
        assert "mock 章节" in chapters[0].read_text(encoding="utf-8")

        # F-1: the summary was archived into turn_summary.
        summaries = list((project_path / "resources" / "turn_summary").glob("turn_*.md"))
        assert summaries, "no turn summary was archived"

        # Sub-agent writes went through their own permission surface.
        state_files = list((project_path / "resources" / "state").glob("mock_output.md"))
        assert state_files, "maintainer mock write did not land in state"

        # F-2: exactly one new Turn commit holds the whole round.
        commits_after = list(repo.iter_commits("HEAD"))
        assert len(commits_after) == commits_before + 1
        head_message = str(repo.head.commit.message)
        assert head_message.startswith("Turn ")

        # The novel viewer sees the chapter through the API too.
        novel = client.get(f"/api/novel/{pid}")
        assert novel.status_code == 200
        assert novel.json()["chapters"], "novel API lists no chapters"

    def test_second_round_appends_chapter(self, client: TestClient, app_root: Path) -> None:
        pid = client.post(
            "/api/projects", json={"display_name": "e2e2", "mode": "novel"}
        ).json()["id"]
        project_path = app_root / "workspaces" / pid

        assert _run_round(client, pid)["state"] == "completed"
        assert _run_round(client, pid)["state"] == "completed"

        chapters = sorted((project_path / "novels").glob("chapter_*.txt"))
        assert [c.name for c in chapters] == ["chapter_001.txt", "chapter_002.txt"]
        summaries = list((project_path / "resources" / "turn_summary").glob("turn_*.md"))
        assert len(summaries) == 2
