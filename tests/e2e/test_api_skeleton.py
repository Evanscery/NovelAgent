"""Playwright skeleton proving the API is browser-reachable (Wave 4, todo 25).

This is NOT the full E2E (todo 35) — it only proves the FastAPI server
runs and a real Chromium browser can reach ``/api/projects`` over HTTP
and parse the JSON response. The frontend does not exist yet (Wave 5),
so we navigate directly to the API endpoint and assert the JSON body
renders in the browser.

Per the task spec:
1. Start FastAPI server (subprocess with uvicorn on a test port).
2. Navigate to http://localhost:<port>/api/projects.
3. Assert JSON response renders (200, valid JSON with a ``projects`` array).
4. Console zero errors.

If the Playwright chromium browser is not installed, the module-level
``pytest.playwright`` plugin skips every test with a recorded reason
(per the task's hard rule: don't block todo 24 on a Playwright install
failure on Windows). We also guard against the browser binary missing
at runtime via a ``skipif`` on a pre-flight launch probe.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml

# ── Skip-if-Playwright-unavailable guard ──────────────────────────────────


def _chromium_available() -> bool:
    """Pre-flight probe: can Playwright actually launch chromium?

    The ``playwright`` Python module can be installed while the browser
    binary is missing (``playwright install`` not yet run). We attempt a
    real headless launch here; on any error we return False so the
    module-level mark skips every test with a recorded reason rather
    than failing the suite.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


_CHROMIUM_OK = _chromium_available()

pytestmark = pytest.mark.skipif(
    not _CHROMIUM_OK,
    reason=(
        "Playwright chromium browser not installed. "
        "Run `python -m playwright install chromium` to enable this test. "
        "Todo 24 (mock API integration test) is not blocked by this skip."
    ),
)


# ── fixtures ─────────────────────────────────────────────────────────────


def _free_port() -> int:
    """Return an OS-assigned free TCP port for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    """Build a minimal repo root with config/ + workspaces/ skeleton."""
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "config" / "server.yaml").write_text(
        yaml.safe_dump(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": 8000,
                    "allow_origins": ["*"],
                    "ip_whitelist": [],
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "models.yaml").write_text(
        yaml.safe_dump({"tiers": {}}, allow_unicode=True),
        encoding="utf-8",
    )
    (tmp_path / "config" / "runtime.yaml").write_text(
        yaml.safe_dump({"runner": {"timeout_seconds": 30}}, allow_unicode=True),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def server_url(app_root: Path) -> Generator[str, None, None]:
    """Start a real uvicorn server on a free port and yield its base URL.

    Uses ``uvicorn.run`` in a subprocess so the server has its own event
    loop + port (not the TestClient's in-process portal). The server is
    started with a tiny bootstrap script that constructs the FastAPI app
    via ``create_app(app_root)`` and serves it. We poll the port until
    it accepts a TCP connection (max ~10s) before yielding.
    """
    port = _free_port()
    # Inline bootstrap script — avoids needing a separate entrypoint file
    # and keeps the test self-contained. The script imports create_app
    # from the installed package and runs uvicorn with the app instance.
    # The project root (where the ``app`` package lives) must be on
    # sys.path so the subprocess can import ``app.api.server`` — we
    # resolve it from this test file's location (tests/e2e/ → repo root).
    project_root = Path(__file__).resolve().parents[2]
    bootstrap = app_root / "_e2e_server_bootstrap.py"
    bootstrap.write_text(
        f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(project_root)!r})
import uvicorn
from app.api.server import create_app
app = create_app(Path({str(app_root)!r}))
uvicorn.run(app, host="127.0.0.1", port={port}, log_level="warning")
""",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(bootstrap)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        # Wait for the server to accept a TCP connection (max ~10s).
        deadline = time.monotonic() + 10.0
        connected = False
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    connected = True
                    break
            except OSError as exc:
                last_err = exc
                time.sleep(0.1)
        if not connected:
            stderr = ""
            if proc.stderr is not None:
                stderr = proc.stderr.read()
            msg = (
                f"server did not start on port {port} within 10s. "
                f"last_err={last_err!r} stderr={stderr!r}"
            )
            raise RuntimeError(msg)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5.0)
        bootstrap.unlink(missing_ok=True)


@pytest.fixture()
def console_errors() -> list[str]:
    """Collect browser console error messages (per the task's
    "console zero errors" assertion)."""
    return []


# ── Tests ────────────────────────────────────────────────────────────────


def test_api_projects_reachable_via_browser(
    server_url: str,
    console_errors: list[str],
) -> None:
    """Navigate to /api/projects in a real Chromium browser; assert
    200 + valid JSON with a ``projects`` array; console zero errors.

    This proves the server runs as a real HTTP process and a browser
    can reach the API endpoint — the minimal skeleton todo 25 requires
    (NOT the full E2E, which lands in todo 35 once the React frontend
    exists).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Capture console messages of level "error" into the fixture list
        # so we can assert "console zero errors" at the end.
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # Navigate to /api/projects. FastAPI serves JSON with
        # ``application/json`` content-type; Chromium renders the raw
        # JSON body as text (no DOM parsing) — so we read the response
        # via ``page.goto``'s return value and also assert the page body
        # contains the JSON text.
        response = page.goto(f"{server_url}/api/projects", wait_until="networkidle")
        assert response is not None, "page.goto returned None (no response)"

        # 3a. Assert HTTP 200.
        assert response.status == 200, (
            f"expected 200, got {response.status}: {response.status_text}"
        )

        # 3b. Assert the response is valid JSON with a ``projects`` array.
        # FastAPI returns ``{"projects": []}`` for an empty workspace.
        body_text = page.evaluate("() => document.body.innerText")
        assert body_text, "page body is empty — expected JSON"
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"response body is not valid JSON: {exc}. body[:200]={body_text[:200]!r}"
            ) from exc
        assert isinstance(body, dict), (
            f"expected a JSON object at top level, got {type(body).__name__}"
        )
        assert "projects" in body, (
            f"expected 'projects' key in response, got keys={list(body.keys())}"
        )
        assert isinstance(body["projects"], list), (
            f"expected 'projects' to be a list, got {type(body['projects']).__name__}"
        )

        browser.close()

    # 4. Console zero errors.
    assert console_errors == [], (
        f"expected zero console errors, got: {console_errors}"
    )


def test_api_projects_after_create_shows_project(
    server_url: str,
    console_errors: list[str],
) -> None:
    """Create a project via HTTP first, then navigate to /api/projects
    in the browser and assert the new project appears in the JSON.

    This is a slightly richer skeleton check than the bare "endpoint
    returns JSON" test above — it proves the browser can observe a
    project that was created via the same server process, so the
    reachability is real (not a cached empty response).
    """
    import urllib.request

    # Create a project via a plain HTTP POST (not via TestClient — we
    # must hit the real server process so the browser sees the same
    # state).
    req = urllib.request.Request(
        f"{server_url}/api/projects",
        data=json.dumps({"display_name": "Browser Test", "mode": "novel"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 201, f"create project failed: {resp.status}"
        created = json.loads(resp.read().decode("utf-8"))
    pid = created["id"]
    display_name = created["display_name"]

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )

        response = page.goto(f"{server_url}/api/projects", wait_until="networkidle")
        assert response is not None
        assert response.status == 200, (
            f"expected 200, got {response.status}: {response.status_text}"
        )

        body_text = page.evaluate("() => document.body.innerText")
        body = json.loads(body_text)
        assert "projects" in body
        ids = [p["id"] for p in body["projects"]]
        assert pid in ids, (
            f"created project {pid!r} not in browser-observed list {ids}"
        )
        names = [p["display_name"] for p in body["projects"]]
        assert display_name in names

        browser.close()

    assert console_errors == [], f"expected zero console errors, got: {console_errors}"


# ── Sanity: the server fixture actually starts a real port ───────────────


def test_server_fixture_starts_real_port(server_url: str) -> None:
    """Defensive: the ``server_url`` fixture binds a real port and the
    URL is reachable via a plain socket connection. This catches a
    regression in the fixture itself (e.g. bootstrap script path
    mismatch) before the Playwright tests run.
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(server_url)
    host = parsed.hostname
    port = parsed.port
    assert host is not None and port is not None, (
        f"server_url did not parse to host:port: {server_url!r}"
    )
    with socket.create_connection((host, port), timeout=2.0):
        pass  # connection succeeded — the port is live.
