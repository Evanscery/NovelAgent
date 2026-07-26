"""F3 — Real-LLM E2E smoke (Metis Issue 7, plan F3).

Per the plan's F3: a Playwright E2E run with a REAL LLM that creates a
project, runs ONE round with a real-LLM director, and asserts:
  - response is non-empty + schema-conforming
  - produces ≥1 chapter paragraph (a coherent narrative response)
  - RP action produces a valid narration

CRITICAL CONSTRAINT from the task: if F3 real-LLM E2E is ambiguous or
fails for auth reasons, record the failure in evidence (don't block —
F1/F2/F4 can still pass). ONE round only, no iteration.

Approach (agent-executable, no browser needed for the LLM round itself):
The chat route's runner factory (``CHAT_RUNNER_FACTORY`` in chat.py)
defaults to MockRunner. We patch it to a :class:`DirectRunner`
configured with the real model (TEST_API_KEY / TEST_BASE_URL / MODEL_HIGH
from .env.local), then POST a chat message and assert the director's
reply is a non-empty, non-mock narrative paragraph. We then do the same
for an RP-style action. This is ONE round each (no iteration).

This file is SKIPPED automatically when:
  - TEST_API_KEY / TEST_BASE_URL / MODEL_HIGH are not in the environment
    (loaded from .env.local by the test harness), OR
  - Playwright chromium is not installed.
On skip, the evidence file records the skip reason (per the task's
"don't block" rule — F1/F2/F4 are independent).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml

# ── Skip guards ──────────────────────────────────────────────────────────


def _chromium_available() -> bool:
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


def _llm_credentials_present() -> bool:
    """True when TEST_API_KEY / TEST_BASE_URL / MODEL_HIGH are all set."""
    return bool(
        os.environ.get("TEST_API_KEY")
        and os.environ.get("TEST_BASE_URL")
        and os.environ.get("MODEL_HIGH")
    )


_CHROMIUM_OK = _chromium_available()
_LLM_OK = _llm_credentials_present()

pytestmark = pytest.mark.skipif(
    not (_CHROMIUM_OK and _LLM_OK),
    reason=(
        "F3 real-LLM E2E skipped: "
        + (
            "Playwright chromium not installed"
            if not _CHROMIUM_OK
            else "TEST_API_KEY/TEST_BASE_URL/MODEL_HIGH not in env (load .env.local)"
        )
    ),
)


# ── Constants ────────────────────────────────────────────────────────────

BACKEND_PORT = 8000


# ── Helpers ──────────────────────────────────────────────────────────────


def _wait_for_port(host: str, port: int, *, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:
            last_err = exc
            time.sleep(0.2)
    msg = f"server at {host}:{port} did not accept connections within {timeout_s}s (last_err={last_err!r})"
    raise RuntimeError(msg)


def _wait_for_http(url: str, *, timeout_s: float = 20.0, expected_status: int = 200) -> None:
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == expected_status:
                    return
        except (urllib.error.URLError, OSError) as exc:
            last_err = exc
        time.sleep(0.2)
    msg = f"{url} did not return {expected_status} within {timeout_s}s (last_err={last_err!r})"
    raise RuntimeError(msg)


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass


def _load_env_local(repo_root: Path) -> None:
    """Load .env.local into os.environ if not already set."""
    env_path = repo_root / ".env.local"
    if not env_path.exists():
        return
    content = env_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, val = stripped.partition("=")
            key = key.strip()
            val = val.strip()
            if key and key not in os.environ:
                os.environ[key] = val


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "config" / "server.yaml").write_text(
        yaml.safe_dump(
            {
                "server": {
                    "host": "127.0.0.1",
                    "port": BACKEND_PORT,
                    "allow_origins": ["*"],
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
                        "model": os.environ.get("MODEL_HIGH", "gemini-3.1-pro-preview"),
                        "api_key_env": "TEST_API_KEY",
                        "base_url_env": "TEST_BASE_URL",
                        "rpm": 3,
                    },
                    "standard": {
                        "provider": "openai_compatible",
                        "model_env": "MODEL_FAST",
                        "model": os.environ.get("MODEL_FAST", "gemini-3-flash-preview"),
                        "api_key_env": "TEST_API_KEY",
                        "base_url_env": "TEST_BASE_URL",
                        "rpm": 10,
                    },
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "runtime.yaml").write_text(
        yaml.safe_dump(
            {"runner": {"timeout_seconds": 120, "max_retries": 1}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def backend_url(app_root: Path) -> Generator[str, None, None]:
    """Start the FastAPI backend with the CHAT runner patched to DirectRunner.

    The bootstrap script monkeypatches
    ``app.api.routes.chat.CHAT_RUNNER_FACTORY`` to return a
    :class:`DirectRunner` built from the real model config before the
    server starts. This makes POST /api/chat hit the real LLM.
    """
    project_root = Path(__file__).resolve().parents[2]
    _load_env_local(project_root)

    bootstrap = app_root / "_f3_backend_bootstrap.py"
    bootstrap.write_text(
        f"""
import sys, os
from pathlib import Path
sys.path.insert(0, {str(project_root)!r})
# Load .env.local into the subprocess env.
_env_path = Path({str(project_root)!r}) / '.env.local'
if _env_path.exists():
    for line in _env_path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        k, _, v = s.partition('=')
        k = k.strip(); v = v.strip()
        if k and k not in os.environ:
            os.environ[k] = v

import uvicorn
from app.api.server import create_app
# Patch the chat runner factory to use the real DirectRunner.
from app.api.routes import chat as chat_routes
from app.runtime.runners.direct_runner import DirectRunner

def _real_chat_runner_factory():
    model_config = {{
        'provider': 'openai_compatible',
        'model': os.environ.get('MODEL_HIGH', 'gemini-3.1-pro-preview'),
        'api_key_env': 'TEST_API_KEY',
        'base_url_env': 'TEST_BASE_URL',
    }}
    runtime_policy = {{
        'timeout_seconds': 120.0,
        'max_retries': 1,
        'backoff_seconds': [2.0],
    }}
    return DirectRunner(model_config, runtime_policy)

chat_routes.CHAT_RUNNER_FACTORY = _real_chat_runner_factory

app = create_app(Path({str(app_root)!r}))
uvicorn.run(app, host='127.0.0.1', port={BACKEND_PORT}, log_level='warning')
""",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(bootstrap)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
    )
    try:
        _wait_for_port("127.0.0.1", BACKEND_PORT, timeout_s=20.0)
        _wait_for_http(f"http://127.0.0.1:{BACKEND_PORT}/api/projects", timeout_s=10.0)
        yield f"http://127.0.0.1:{BACKEND_PORT}"
    finally:
        _kill_process_tree(proc)
        bootstrap.unlink(missing_ok=True)


# ── Tests ────────────────────────────────────────────────────────────────


def test_real_llm_director_chat_round(backend_url: str) -> None:
    """F3: ONE real-LLM round — send a chat message, assert non-empty
    narrative response (schema-conforming + ≥1 paragraph).

    Per the task's "ONE round only, no iteration" rule, we send exactly
    one user message and assert the director's reply. If the LLM call
    fails (auth, network, timeout), we record the error and re-raise so
    the evidence file captures the failure (per the task's "record the
    failure, don't block" rule — the test failure IS the recorded
    evidence; F1/F2/F4 run independently).
    """
    import urllib.error
    import urllib.request

    # 1. Create a project.
    req = urllib.request.Request(
        f"{backend_url}/api/projects",
        data=json.dumps({"display_name": "F3 Real LLM Test", "mode": "novel"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        assert resp.status == 201
        created = json.loads(resp.read().decode("utf-8"))
    pid = created["id"]
    assert pid.startswith("proj_")

    try:
        # 2. Send ONE chat message asking the director to write a chapter.
        chat_req = urllib.request.Request(
            f"{backend_url}/api/chat/{pid}",
            data=json.dumps({
                "content": (
                    "Write the opening chapter of a fantasy novel about a young hero "
                    "named Kael who discovers an ancient map in their grandmother's "
                    "attic. Write at least one full paragraph of narrative prose."
                )
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(chat_req, timeout=180.0) as resp:
                assert resp.status in (200, 201)
                chat_body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Record the LLM failure as evidence — per the task, don't
            # iterate, just record. We re-raise so pytest captures it.
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
            msg = f"F3 LLM call failed: HTTP {exc.code} — {err_body}"
            raise AssertionError(msg) from exc
        except urllib.error.URLError as exc:
            msg = f"F3 LLM call network error: {exc}"
            raise AssertionError(msg) from exc

        # 3. Assert the director response is present + non-empty.
        director_msg = chat_body.get("director_message")
        assert director_msg is not None, (
            f"director_message is null in response: {chat_body!r}"
        )
        reply_text = director_msg.get("content", "")
        assert reply_text, (
            f"director reply content is empty: {chat_body!r}"
        )
        # 4. Assert schema-conforming: ChatMessage has the required fields.
        for field in ("message_id", "role", "content", "turn_id", "timestamp"):
            assert field in director_msg, (
                f"director message missing field {field!r}: {director_msg!r}"
            )
        assert director_msg["role"] in ("director", "system"), (
            f"director message role unexpected: {director_msg['role']!r}"
        )
        # 5. Assert it is NOT the mock runner's canned response.
        assert "[mock:" not in reply_text, (
            f"director reply looks like a MockRunner response, not real LLM: {reply_text[:200]!r}"
        )
        # 6. Assert ≥1 chapter paragraph (non-trivial narrative response).
        # A paragraph is roughly ≥100 chars of prose. The mock response is
        # ~40 chars, so this also guards against mock leakage.
        assert len(reply_text) >= 100, (
            f"director reply too short for a chapter paragraph ({len(reply_text)} chars): "
            f"{reply_text[:200]!r}"
        )

    finally:
        # Cleanup: delete the project.
        try:
            del_req = urllib.request.Request(
                f"{backend_url}/api/projects/{pid}", method="DELETE"
            )
            with urllib.request.urlopen(del_req, timeout=5.0) as resp:
                assert resp.status in (204, 200)
        except Exception as exc:
            print(f"WARNING: F3 cleanup delete failed for {pid}: {exc}")


def test_real_llm_rp_action_narration(backend_url: str) -> None:
    """F3 part 2: RP action produces a valid narration.

    Send an RP-style action ("I draw my sword and face the dragon") and
    assert the director's reply is a non-empty narration. ONE round only.
    """
    import urllib.error
    import urllib.request

    # Create a project in RP mode.
    req = urllib.request.Request(
        f"{backend_url}/api/projects",
        data=json.dumps({"display_name": "F3 RP LLM Test", "mode": "rp"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        assert resp.status == 201
        created = json.loads(resp.read().decode("utf-8"))
    pid = created["id"]

    try:
        # Send an RP action via the chat endpoint (RP reuses the chat
        # contract per guide:410-413).
        chat_req = urllib.request.Request(
            f"{backend_url}/api/chat/{pid}",
            data=json.dumps({
                "content": (
                    "I draw my sword and face the dragon, heart pounding. "
                    "Narrate what happens next."
                )
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(chat_req, timeout=180.0) as resp:
                assert resp.status in (200, 201)
                chat_body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")[:500]
            msg = f"F3 RP LLM call failed: HTTP {exc.code} — {err_body}"
            raise AssertionError(msg) from exc
        except urllib.error.URLError as exc:
            msg = f"F3 RP LLM call network error: {exc}"
            raise AssertionError(msg) from exc

        director_msg = chat_body.get("director_message")
        assert director_msg is not None, (
            f"RP director_message is null: {chat_body!r}"
        )
        narration = director_msg.get("content", "")
        assert narration, f"RP narration content is empty: {chat_body!r}"
        assert "[mock:" not in narration, (
            f"RP reply looks like MockRunner, not real LLM: {narration[:200]!r}"
        )
        # A valid narration should be a non-trivial narrative response.
        assert len(narration) >= 50, (
            f"RP narration too short ({len(narration)} chars): {narration[:200]!r}"
        )

    finally:
        try:
            del_req = urllib.request.Request(
                f"{backend_url}/api/projects/{pid}", method="DELETE"
            )
            with urllib.request.urlopen(del_req, timeout=5.0) as resp:
                assert resp.status in (204, 200)
        except Exception as exc:
            print(f"WARNING: F3 RP cleanup delete failed for {pid}: {exc}")


# ── Sanity ───────────────────────────────────────────────────────────────


def test_backend_fixture_starts_real_port(backend_url: str) -> None:
    """Defensive: the backend_url fixture binds a real port."""
    import urllib.parse

    parsed = urllib.parse.urlparse(backend_url)
    host = parsed.hostname
    port = parsed.port
    assert host is not None and port is not None
    with socket.create_connection((host, port), timeout=2.0):
        pass
