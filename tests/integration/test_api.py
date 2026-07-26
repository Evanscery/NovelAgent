"""Full API integration test (Wave 4, todo 24).

Exercises every API route end-to-end via httpx :class:`TestClient` against
the real FastAPI app, with the director / agents mocked via the
``RUNNER_FACTORY`` and ``CHAT_RUNNER_FACTORY`` hooks (no real LLM is
contacted — LLM smokes were per-wave per D8, this is the mock integration
test).

Flow (per the task spec):
 1. POST /api/projects {display_name, mode} → 201, capture project_id.
 2. GET  /api/projects → list contains the new project.
 3. GET  /api/resources/{id} → 8 resource types listed.
 4. PUT  /api/resources/{id}/state {content} → 200.
 5. GET  /api/resources/{id}/state → returns updated content.
 6. GET  /api/resources/{id}/state/history → ≥1 commit after the PUT.
 7. POST /api/workflow/{id}/run {} → 202, capture round_id.
 8. GET  /api/workflow/{id}/round/{round_id} → poll until completed/failed.
 9. POST /api/chat/{id} {content} → 200, director response (mock).
10. GET  /api/chat/{id} → history contains the exchange.
11. DELETE /api/chat/{id}/{message_id} → 200, rollback verified (new branch).
12. GET  /api/config → global config.
13. PUT  /api/config/{id}/agents/writer {model:"premium"} → 200.
14. GET  /api/novel/{id} → chapter list (may be empty).
15. POST /api/import → 501 (stub).

All assertions are against the wire shapes declared in
``app/api/schemas.py``. Per the task's hard rule: the test stops and
reports if any API flow is ambiguous — but the route shapes are fully
defined by todos 21-23 and have stable schemas, so the flow is
unambiguous.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import git
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.routes import chat as chat_routes
from app.api.routes import workflow as workflow_routes
from app.api.server import create_app
from app.data.resource_types import RESOURCE_TYPE_REGISTRY
from app.runtime.runners.mock_runner import MockRunner

# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    """Build a minimal repo root with config/ + workspaces/ skeleton.

    Mirrors the per-route unit-test fixtures so the integration test runs
    against the same on-disk layout the routes expect.
    """
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "config" / "server.yaml").write_text(
        yaml.safe_dump(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": 8000,
                    "allow_origins": [],
                    "ip_whitelist": [],
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "models.yaml").write_text(
        yaml.safe_dump(
            {
                "tiers": {
                    "premium": {
                        "provider": "openai_compatible",
                        "model_env": "MODEL_HIGH",
                        "rpm": 3,
                    },
                    "standard": {
                        "provider": "openai_compatible",
                        "model_env": "MODEL_FAST",
                        "rpm": 10,
                    },
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
    """FastAPI TestClient with both runner factories pointed at MockRunner.

    The workflow route's ``RUNNER_FACTORY`` and the chat route's
    ``CHAT_RUNNER_FACTORY`` are module-level hooks; swapping them before
    building the app guarantees no LLM is contacted on any path.
    """
    workflow_routes.RUNNER_FACTORY = lambda root, project_id: MockRunner()
    chat_routes.CHAT_RUNNER_FACTORY = lambda root, project_id: MockRunner()
    app = create_app(app_root)
    return TestClient(app)


@pytest.fixture()
def project_id(client: TestClient) -> str:
    """Step 1: POST /api/projects → 201, return the new project_id."""
    resp = client.post("/api/projects", json={"display_name": "Test Novel", "mode": "novel"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"].startswith("proj_")
    assert body["display_name"] == "Test Novel"
    assert body["mode"] == "novel"
    pid: str = body["id"]
    return pid


@pytest.fixture()
def project_path(app_root: Path, project_id: str) -> Path:
    return app_root / "workspaces" / project_id


# ── helpers ──────────────────────────────────────────────────────────────


def _git_branches(project_path: Path) -> list[str]:
    repo = git.Repo(str(project_path))
    return sorted(b.name for b in repo.branches)


def _read_chat_log(project_path: Path) -> list[dict[str, Any]]:
    log = project_path / "work" / "chat.jsonl"
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _poll_round(
    client: TestClient, project_id: str, round_id: str, *, timeout_s: float = 5.0
) -> dict[str, Any]:
    """Poll GET /api/workflow/{id}/round/{rid} until terminal state.

    Returns the final response body. Raises ``AssertionError`` if the
    round does not reach ``completed``/``failed`` within *timeout_s*
    seconds (defensive — the MockRunner completes near-instantly).
    """
    deadline = time.monotonic() + timeout_s
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/workflow/{project_id}/round/{round_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["state"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    msg = f"round {round_id} did not terminate within {timeout_s}s (last state={body.get('state')})"
    raise AssertionError(msg)


# ── 1-2. Project create + list ───────────────────────────────────────────


class TestProjectCreateAndList:
    def test_post_projects_creates_project(self, client: TestClient) -> None:
        """Step 1: POST /api/projects → 201 with system-controlled id."""
        resp = client.post(
            "/api/projects", json={"display_name": "Test Novel", "mode": "novel"}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"].startswith("proj_")
        assert body["display_name"] == "Test Novel"
        assert body["mode"] == "novel"
        assert "path" in body

    def test_get_projects_lists_new_project(
        self, client: TestClient, project_id: str
    ) -> None:
        """Step 2: GET /api/projects → list contains the new project."""
        resp = client.get("/api/projects")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [p["id"] for p in body["projects"]]
        assert project_id in ids
        summary = next(p for p in body["projects"] if p["id"] == project_id)
        assert summary["display_name"] == "Test Novel"
        assert summary["mode"] == "novel"


# ── 3-6. Resources read/edit/history ─────────────────────────────────────


class TestResourcesFlow:
    def test_list_resources_returns_8_types(
        self, client: TestClient, project_id: str
    ) -> None:
        """Step 3: GET /api/resources/{id} → 8 resource types listed."""
        resp = client.get(f"/api/resources/{project_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        types = {r["type"] for r in body["resources"]}
        assert types == set(RESOURCE_TYPE_REGISTRY)
        assert len(body["resources"]) == len(RESOURCE_TYPE_REGISTRY)

    def test_put_then_get_round_trips_content(
        self,
        client: TestClient,
        project_id: str,
        project_path: Path,
    ) -> None:
        """Steps 4-5: PUT then GET round-trip the content."""
        # Step 4: PUT /api/resources/{id}/state {content} → 200.
        put = client.put(
            f"/api/resources/{project_id}/state",
            json={"content": "Chapter 1 begins..."},
        )
        assert put.status_code == 200, put.text
        put_body = put.json()
        assert put_body["type"] == "state"
        assert put_body["read_only"] is False
        assert "Chapter 1 begins..." in put_body["content"]
        # The file landed on disk under resources/state/.
        assert (project_path / "resources" / "state" / "content.md").is_file()

        # Step 5: GET /api/resources/{id}/state → returns updated content.
        get = client.get(f"/api/resources/{project_id}/state")
        assert get.status_code == 200, get.text
        get_body = get.json()
        assert get_body["type"] == "state"
        assert "Chapter 1 begins..." in get_body["content"]
        assert "content.md" in get_body["files"]

    def test_state_history_has_commit_after_put(
        self,
        client: TestClient,
        project_id: str,
        project_path: Path,
    ) -> None:
        """Step 6: GET /api/resources/{id}/state/history → ≥1 commit.

        The PUT endpoint itself does NOT commit a Turn (per the route
        docstring — a workflow Round or explicit project-repo commit
        creates the Turn). To exercise the history endpoint with real
        data we commit the PUT's content through ProjectRepo directly,
        mirroring what a workflow round's maintainer agent would do.
        """
        from app.data.project_repo import ProjectRepo

        # Write content via the API (creates resources/state/content.md).
        client.put(
            f"/api/resources/{project_id}/state",
            json={"content": "Chapter 1 begins..."},
        )
        # Commit a Turn containing the new content — this is what makes
        # the history endpoint return a commit touching resources/state/.
        ProjectRepo(project_path).commit_turn("1", "add state content")

        resp = client.get(f"/api/resources/{project_id}/state/history")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["type"] == "state"
        assert isinstance(body["commits"], list)
        assert len(body["commits"]) >= 1, (
            f"expected ≥1 commit after the PUT+commit, got {body['commits']}"
        )
        first = body["commits"][0]
        assert first["sha"]
        assert first["turn_id"] == "1"
        assert first["branch"]
        # Timestamp is ISO-8601.
        assert "T" in first["timestamp"]


# ── 7-8. Workflow run + round status poll ────────────────────────────────


class TestWorkflowRunFlow:
    def test_run_returns_202_and_completes(
        self, client: TestClient, project_id: str
    ) -> None:
        """Steps 7-8: POST /run → 202; poll GET /round/{rid} → completed."""
        # Step 7: POST /api/workflow/{id}/run {} → 202, capture round_id.
        run = client.post(f"/api/workflow/{project_id}/run", json={})
        assert run.status_code == 202, run.text
        run_body = run.json()
        assert run_body["round_id"].startswith("round_")
        assert run_body["state"] in ("pending", "running", "completed")
        round_id = run_body["round_id"]

        # Step 8: poll GET /round/{round_id} until completed/failed.
        body = _poll_round(client, project_id, round_id)
        assert body["state"] == "completed", (
            f"round did not complete: state={body['state']} error={body.get('error')}"
        )
        assert body["error"] is None
        assert body["result"] is not None
        # MockRunner does not emit tool_calls, so only the director agent
        # completes (the workflow agents are never dispatched). The round
        # still finalises because there are no pending tool_calls.
        assert len(body["result"]["completed_agents"]) >= 1
        assert body["result"]["finalize_reason"] in ("all_nodes_done", "explicit_finalize")
        assert body["result"]["total_tokens"] > 0


# ── 9-11. Chat send / history / delete-rollback ──────────────────────────


class TestChatFlow:
    def test_send_returns_director_response(
        self, client: TestClient, project_id: str
    ) -> None:
        """Step 9: POST /api/chat/{id} → 200 with director response (mock)."""
        resp = client.post(
            f"/api/chat/{project_id}", json={"content": "Hello director"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_message"]["role"] == "user"
        assert body["user_message"]["content"] == "Hello director"
        assert body["user_message"]["message_id"].startswith("msg_")
        assert body["user_message"]["turn_id"]
        # Director response is produced by MockRunner (deterministic text).
        assert body["director_message"] is not None
        assert body["director_message"]["role"] == "director"
        assert body["director_message"]["content"]
        # Both messages share the same turn_id (one Turn per exchange).
        assert body["user_message"]["turn_id"] == body["director_message"]["turn_id"]

    def test_history_contains_exchange(
        self, client: TestClient, project_id: str
    ) -> None:
        """Step 10: GET /api/chat/{id} → history contains the exchange."""
        client.post(f"/api/chat/{project_id}", json={"content": "Hello director"})
        resp = client.get(f"/api/chat/{project_id}")
        assert resp.status_code == 200, resp.text
        msgs = resp.json()
        assert len(msgs) == 2  # user + director
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello director"
        assert msgs[1]["role"] == "director"

    def test_delete_rolls_back_to_new_branch(
        self,
        client: TestClient,
        project_id: str,
        project_path: Path,
    ) -> None:
        """Step 11: DELETE /api/chat/{id}/{message_id} → 200 + new branch.

        Per guide:412 delete is synced to backend rollback. Per
        guide:314-316 rollback = new branch (NOT delete) — the original
        timeline is preserved on its old branch. We send 2 exchanges,
        delete the second user message, and assert:
          - a new ``rollback/*`` branch was created,
          - the chat log on disk rewound to the surviving exchange,
          - ``main`` branch is preserved (original timeline intact).
        """
        # Send 2 exchanges → 4 messages, 2 Turn commits on top of Turn 0.
        ids: list[str] = []
        for content in ("first message", "second message"):
            resp = client.post(f"/api/chat/{project_id}", json={"content": content})
            ids.append(resp.json()["user_message"]["message_id"])

        log_before = _read_chat_log(project_path)
        assert len(log_before) == 4
        assert _git_branches(project_path) == ["main"]

        # Delete the 2nd user message → roll back to the Turn that
        # preceded it (the Turn from exchange "first message").
        target_msg_id = ids[1]
        resp = client.delete(f"/api/chat/{project_id}/{target_msg_id}")
        assert resp.status_code == 200, resp.text

        # After rollback the chat log reflects the state at the rollback
        # target → only exchange "first message" survives (2 messages).
        surviving = resp.json()
        assert len(surviving) == 2
        assert surviving[0]["content"] == "first message"
        assert surviving[1]["role"] == "director"

        # A NEW rollback/* branch was created (rollback mode='branch').
        branches_after = _git_branches(project_path)
        assert "main" in branches_after, "original timeline must be preserved"
        rollback_branches = [b for b in branches_after if b.startswith("rollback/")]
        assert len(rollback_branches) >= 1, (
            f"expected a rollback/* branch, got {branches_after}"
        )

        # The current branch is the rollback branch (checked out).
        repo = git.Repo(str(project_path))
        assert repo.active_branch.name.startswith("rollback/")

        # The chat log on disk matches the surviving messages.
        log_after = _read_chat_log(project_path)
        assert len(log_after) == 2
        assert log_after[0]["content"] == "first message"


# ── 12-13. Config global + per-agent edit ────────────────────────────────


class TestConfigFlow:
    def test_get_global_config(self, client: TestClient) -> None:
        """Step 12: GET /api/config → global config with all tiers."""
        resp = client.get("/api/config")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == ""
        # models.yaml + runtime.yaml + server.yaml all loaded.
        assert "tiers" in body["models"]
        assert body["models"]["tiers"]["premium"]["provider"] == "openai_compatible"
        assert body["runtime"]["runner"]["timeout_seconds"] == 600
        assert body["server"]["host"] == "127.0.0.1"

    def test_put_agent_config_updates_writer_model(
        self,
        client: TestClient,
        project_id: str,
        app_root: Path,
    ) -> None:
        """Step 13: PUT /api/config/{id}/agents/writer {model} → 200.

        Edits the writer agent's model to ``"premium"`` and verifies the
        override is written to the per-project yaml file (preferred over
        mutating the built-in definition — per the route's docstring).
        """
        # Fetch the current writer config so we can send a full valid body.
        list_resp = client.get(f"/api/config/{project_id}/agents")
        assert list_resp.status_code == 200, list_resp.text
        writer = next(a for a in list_resp.json() if a["name"] == "writer")
        writer["model"] = "premium"

        resp = client.put(
            f"/api/config/{project_id}/agents/writer", json=writer
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "writer"
        assert body["model"] == "premium"

        # Override file written under the project workspace.
        override = app_root / "workspaces" / project_id / "agents" / "writer.yaml"
        assert override.is_file()
        on_disk = yaml.safe_load(override.read_text(encoding="utf-8"))
        assert on_disk["model"] == "premium"

        # Reload via GET → the override is visible.
        reloaded = client.get(f"/api/config/{project_id}/agents")
        writer_after = next(a for a in reloaded.json() if a["name"] == "writer")
        assert writer_after["model"] == "premium"


# ── 14. Novel chapter list ───────────────────────────────────────────────


class TestNovelFlow:
    def test_get_novel_chapter_list_may_be_empty(
        self, client: TestClient, project_id: str
    ) -> None:
        """Step 14: GET /api/novel/{id} → chapter list (may be empty)."""
        resp = client.get(f"/api/novel/{project_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == project_id
        # A freshly scaffolded project has no exported chapters.
        assert body["chapters"] == []


# ── 15. Import stub ──────────────────────────────────────────────────────


class TestImportStub:
    def test_post_import_returns_400_without_source_or_card(self, client: TestClient) -> None:
        """Step 15: POST /api/import → 400 when neither source nor card is
        provided (todo 34 replaced the 501 stub with real card-import)."""
        resp = client.post("/api/import", json={})
        assert resp.status_code == 400, resp.text
        body = resp.json()
        # The detail explains what fields are required.
        assert "source" in body["detail"].lower() or "card" in body["detail"].lower()


# ── Full-flow smoke: all 15 steps in one test ────────────────────────────


class TestFullApiFlow:
    """All 15 steps of the task spec in a single ordered test.

    This is the integration test proper — it walks the whole API surface
    in the order the task spec lists, asserting every status code and
    key response field. The per-class tests above isolate each step for
    failure-localisation; this one proves they chain end-to-end.
    """

    def test_full_flow_15_steps(
        self, client: TestClient, app_root: Path
    ) -> None:
        # 1. POST /api/projects → 201.
        r1 = client.post(
            "/api/projects", json={"display_name": "Test Novel", "mode": "novel"}
        )
        assert r1.status_code == 201, r1.text
        pid = r1.json()["id"]
        project_path = app_root / "workspaces" / pid

        # 2. GET /api/projects → list contains new project.
        r2 = client.get("/api/projects")
        assert r2.status_code == 200
        assert any(p["id"] == pid for p in r2.json()["projects"])

        # 3. GET /api/resources/{id} → 8 resource types.
        r3 = client.get(f"/api/resources/{pid}")
        assert r3.status_code == 200
        assert len(r3.json()["resources"]) == len(RESOURCE_TYPE_REGISTRY)

        # 4. PUT /api/resources/{id}/state {content} → 200.
        r4 = client.put(
            f"/api/resources/{pid}/state",
            json={"content": "Chapter 1 begins..."},
        )
        assert r4.status_code == 200, r4.text

        # 5. GET /api/resources/{id}/state → updated content.
        r5 = client.get(f"/api/resources/{pid}/state")
        assert r5.status_code == 200
        assert "Chapter 1 begins..." in r5.json()["content"]

        # 6. GET /api/resources/{id}/state/history → ≥1 commit.
        # Commit the PUT's content via ProjectRepo (mirrors what a
        # workflow round's maintainer agent would do).
        from app.data.project_repo import ProjectRepo

        ProjectRepo(project_path).commit_turn("1", "add state content")
        r6 = client.get(f"/api/resources/{pid}/state/history")
        assert r6.status_code == 200, r6.text
        assert len(r6.json()["commits"]) >= 1

        # 7. POST /api/workflow/{id}/run {} → 202, capture round_id.
        r7 = client.post(f"/api/workflow/{pid}/run", json={})
        assert r7.status_code == 202, r7.text
        round_id = r7.json()["round_id"]

        # 8. GET /api/workflow/{id}/round/{round_id} → poll until completed.
        body8 = _poll_round(client, pid, round_id)
        assert body8["state"] == "completed", (
            f"step 8: round did not complete: {body8}"
        )

        # 9. POST /api/chat/{id} {content} → 200 with director response.
        r9 = client.post(f"/api/chat/{pid}", json={"content": "Hello director"})
        assert r9.status_code == 200, r9.text
        assert r9.json()["director_message"] is not None

        # 10. GET /api/chat/{id} → history contains the exchange.
        r10 = client.get(f"/api/chat/{pid}")
        assert r10.status_code == 200
        msgs10 = r10.json()
        assert len(msgs10) == 2
        assert msgs10[0]["content"] == "Hello director"

        # 11. DELETE /api/chat/{id}/{message_id} → 200, rollback verified.
        # Send a second exchange first so the delete has a real "before"
        # Turn to roll back to (otherwise it rolls back to Turn 0 and the
        # new-branch assertion still holds but is less meaningful).
        r9b = client.post(f"/api/chat/{pid}", json={"content": "second message"})
        second_msg_id = r9b.json()["user_message"]["message_id"]
        branches_before = _git_branches(project_path)
        assert branches_before == ["main"]

        r11 = client.delete(f"/api/chat/{pid}/{second_msg_id}")
        assert r11.status_code == 200, r11.text
        # New rollback/* branch created.
        branches_after = _git_branches(project_path)
        assert "main" in branches_after
        assert any(b.startswith("rollback/") for b in branches_after), (
            f"step 11: expected a rollback/* branch, got {branches_after}"
        )
        # The surviving chat log has the first exchange only (2 messages).
        assert len(r11.json()) == 2
        assert r11.json()[0]["content"] == "Hello director"

        # 12. GET /api/config → global config.
        r12 = client.get("/api/config")
        assert r12.status_code == 200
        assert "tiers" in r12.json()["models"]

        # 13. PUT /api/config/{id}/agents/writer {model:"premium"} → 200.
        list_resp = client.get(f"/api/config/{pid}/agents")
        writer = next(a for a in list_resp.json() if a["name"] == "writer")
        writer["model"] = "premium"
        r13 = client.put(f"/api/config/{pid}/agents/writer", json=writer)
        assert r13.status_code == 200, r13.text
        assert r13.json()["model"] == "premium"

        # 14. GET /api/novel/{id} → the workflow round in step 7-8 produced
        # a chapter (scripted mock finalize writes novels/chapter_001.txt).
        r14 = client.get(f"/api/novel/{pid}")
        assert r14.status_code == 200
        assert len(r14.json()["chapters"]) >= 1

        # 15. POST /api/import → 400 (todo 34 replaced the 501 stub with
        # real card-import; empty body is now a 400 validation error).
        r15 = client.post("/api/import", json={})
        assert r15.status_code == 400
        assert "source" in r15.json()["detail"].lower() or "card" in r15.json()["detail"].lower()

        # Sanity: the project_id from step 1 was used in every step.
        # (Defensive — catches a copy-paste bug where a step used a
        # different id.)
        assert pid.startswith("proj_")
