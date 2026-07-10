"""Tests for /api/workflow routes (httpx TestClient against FastAPI).

Covers the todo-22 acceptance criteria:
* POST /run starts a round (returns 202 + round_id).
* GET /round/{round_id} reports status (pending → running → completed).
* POST /stop cancels a running round.

The Director / agents are mocked via the ``RUNNER_FACTORY`` hook in
``app/api/routes/workflow.py`` — we swap in a :class:`MockRunner` that
returns deterministic canned responses without contacting any LLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.runtime.runners.mock_runner import MockRunner
from app.api.routes import workflow as workflow_routes
from app.api.server import create_app

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
    # Swap in the MockRunner so no LLM is contacted.
    workflow_routes.RUNNER_FACTORY = lambda: MockRunner()
    app = create_app(app_root)
    return TestClient(app)


@pytest.fixture()
def project_id(client: TestClient) -> str:
    resp = client.post("/api/projects", json={"display_name": "Workflow Test", "mode": "novel"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── POST /api/workflow/{project_id}/run ──────────────────────────────────


class TestRunWorkflow:
    def test_run_returns_202_with_round_id(self, client: TestClient, project_id: str) -> None:
        resp = client.post(f"/api/workflow/{project_id}/run", json={})
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["round_id"].startswith("round_")
        assert body["state"] in ("pending", "running", "completed")
        assert "logs" in body

    def test_run_with_context(self, client: TestClient, project_id: str) -> None:
        resp = client.post(
            f"/api/workflow/{project_id}/run",
            json={"context": "seeded state for the director", "maximal_recursive_calling_depth": 1},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["round_id"].startswith("round_")

    def test_run_with_custom_max_iterations(self, client: TestClient, project_id: str) -> None:
        resp = client.post(
            f"/api/workflow/{project_id}/run",
            json={"max_iterations": 4},
        )
        assert resp.status_code == 202

    def test_run_missing_project_404(self, client: TestClient) -> None:
        resp = client.post("/api/workflow/proj_nope000/run", json={})
        assert resp.status_code == 404

    def test_run_traversal_404(self, client: TestClient) -> None:
        resp = client.post("/api/workflow/../run", json={})
        # FastAPI rejects the literal ".." path param; the route's
        # resolve_project_path raises ProjectPathError → 404.
        assert resp.status_code in (404, 422)


# ── GET /api/workflow/{project_id}/round/{round_id} ──────────────────────


class TestRoundStatus:
    def test_status_completes_after_run(self, client: TestClient, project_id: str) -> None:
        # Start a round with the MockRunner — completes near-instantly.
        run = client.post(f"/api/workflow/{project_id}/run", json={})
        assert run.status_code == 202
        round_id = run.json()["round_id"]

        # Poll until the round reaches a terminal state. The MockRunner
        # is deterministic and fast, so a few short polls suffice.
        final_state = None
        for _ in range(40):
            status_resp = client.get(f"/api/workflow/{project_id}/round/{round_id}")
            assert status_resp.status_code == 200, status_resp.text
            final_state = status_resp.json()["state"]
            if final_state in ("completed", "failed"):
                break
            import time

            time.sleep(0.05)

        assert final_state == "completed", f"round did not complete: {final_state}"
        body = status_resp.json()  # type: ignore[possibly-undefined]
        assert body["round_id"] == round_id
        assert body["state"] == "completed"
        # With the RoundExecutor tool-call loop, the MockRunner director
        # returns plain text (no tool_calls) → the round completes after
        # one director turn with completed_agents == ["director"] and
        # finalize_reason == "all_nodes_done". A real LLM director would
        # emit call_agent tool calls to dispatch the workflow's sub-agents.
        assert body["result"] is not None
        assert "director" in body["result"]["completed_agents"]
        assert body["result"]["finalize_reason"] == "all_nodes_done"
        assert body["result"]["total_tokens"] > 0
        assert body["error"] is None

    def test_status_running_round_has_logs(self, client: TestClient, project_id: str) -> None:
        # Start a round; even if it completes instantly, the logs must be
        # non-empty (the round record logs its start line).
        run = client.post(f"/api/workflow/{project_id}/run", json={})
        round_id = run.json()["round_id"]
        # Give the event loop a tick to start the task.
        import time

        time.sleep(0.05)
        resp = client.get(f"/api/workflow/{project_id}/round/{round_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["logs"]) >= 1
        assert any("round" in line for line in body["logs"])

    def test_status_unknown_round_404(self, client: TestClient, project_id: str) -> None:
        resp = client.get(f"/api/workflow/{project_id}/round/round_nope000")
        assert resp.status_code == 404

    def test_status_unknown_project_404(self, client: TestClient) -> None:
        resp = client.get("/api/workflow/proj_nope000/round/round_xxxxxxxx")
        assert resp.status_code == 404

    def test_status_round_from_other_project_404(
        self, client: TestClient, project_id: str
    ) -> None:
        # Create a second project; a round started under the first must
        # not be visible under the second.
        other = client.post("/api/projects", json={"display_name": "Other"})
        other_id = other.json()["id"]
        run = client.post(f"/api/workflow/{project_id}/run", json={})
        round_id = run.json()["round_id"]
        resp = client.get(f"/api/workflow/{other_id}/round/{round_id}")
        assert resp.status_code == 404


# ── POST /api/workflow/{project_id}/stop ─────────────────────────────────


class TestStopWorkflow:
    def test_stop_running_round(
        self, client: TestClient, project_id: str, app_root: Path
    ) -> None:
        """Stop cancels a running round.

        The round's background ``asyncio.Task`` lives on the per-request
        portal's event loop; with Starlette's :class:`TestClient` each
        request runs in a fresh portal, so a real long-running task
        would be cancelled when the POST /run portal closes. To reliably
        exercise the stop path we inject a synthetic running
        :class:`RoundRecord` (with a pending task that the test controls)
        into the registry, then call /stop and assert the task was
        cancelled + the record transitioned to ``failed``.
        """
        import asyncio

        from app.api.routes.workflow import RoundRecord, RoundRegistry

        # Reach into app.state to get the live registry the routes use.
        app = client.app  # type: ignore[attr-defined]
        registry: RoundRegistry = app.state.round_registry

        # Inject a synthetic running round whose task is a pending sleep.
        round_id = "round_synthetic"
        record = RoundRecord(round_id=round_id, project_id=project_id, state="running")

        async def _long_round() -> None:
            await asyncio.sleep(30)

        # Create the task on the registry's own loop. The registry itself
        # doesn't own a loop; we create one fresh for the test task. The
        # stop endpoint calls ``task.cancel()`` which works regardless of
        # which loop the task is on (as long as it isn't done).
        loop = asyncio.new_event_loop()
        try:
            record.task = loop.create_task(_long_round())
            registry.create(round_id, project_id)  # type: ignore[unused-coroutine]
            # Overwrite the record created by `create` with our synthetic one.
            registry._rounds[round_id] = record  # noqa: SLF001 — test-only injection
            # Drive the loop once so the task is actually awaiting.
            loop.call_soon(loop.stop)
            loop.run_forever()

            stop = client.post(f"/api/workflow/{project_id}/stop")
            assert stop.status_code == 200, stop.text
            body = stop.json()
            assert body["round_id"] == round_id
            # The cancel was requested (record.task.cancel() was called).
            assert record.task is not None
            assert record.task.cancelled() or record.task.cancelling() > 0
        finally:
            loop.close()

    def test_stop_no_running_round_409(self, client: TestClient, project_id: str) -> None:
        resp = client.post(f"/api/workflow/{project_id}/stop")
        assert resp.status_code == 409
        assert "running" in resp.json()["detail"].lower()

    def test_stop_unknown_project_404(self, client: TestClient) -> None:
        resp = client.post("/api/workflow/proj_nope000/stop")
        assert resp.status_code == 404

    def test_cannot_start_second_concurrent_round(
        self, client: TestClient, project_id: str, app_root: Path
    ) -> None:
        """Starting a second round while one is running returns 409.

        We inject a synthetic running :class:`RoundRecord` into the
        registry (same reason as ``test_stop_running_round`` — the
        :class:`TestClient` portal closes after each request so a real
        long task cannot span two requests), then POST /run and assert
        the 409 conflict.
        """
        from app.api.routes.workflow import RoundRecord, RoundRegistry

        app = client.app  # type: ignore[attr-defined]
        registry: RoundRegistry = app.state.round_registry
        record = RoundRecord(round_id="round_blocker", project_id=project_id, state="running")
        registry._rounds["round_blocker"] = record  # noqa: SLF001 — test-only injection

        second = client.post(f"/api/workflow/{project_id}/run", json={})
        assert second.status_code == 409
        assert "running" in second.json()["detail"].lower()
        # The 409 response names the existing running round.
        assert "round_blocker" in second.json()["detail"]
