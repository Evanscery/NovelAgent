"""Frontend integration test — full flow via Playwright against a mock backend.

Todo 33 (.omo/plans/refactor-to-guide.md): exercise every React view end-to-end
against a FastAPI backend whose runner factories return :class:`MockRunner`
(NO real LLM is contacted). The flow per the task spec:

  1. Start FastAPI (uvicorn subprocess on port 8000, MockRunner patched in).
  2. Start vite dev server (``npm run dev`` on :5173, proxies /api → :8000).
  3. Playwright Chromium:
     - Open http://localhost:5173/ → OverviewView renders.
     - Click 「+ 新建项目」 → modal → enter display_name + select mode → submit.
     - Project appears in the project list (OverviewView re-renders).
     - Click 工作流 tab → WorkflowCanvasView renders with default nodes.
     - Click 对话 tab → send "Hello director" → director mock response appears.
     - Click 资源 tab → 8 types listed → select 当前状态 → editor loads
       content → edit → save.
     - Click 配置 tab → model config visible → edit writer agent's Model → save.
     - Click 作品 tab → empty state (no chapters yet).
     - Click RP tab → action input visible.
     - Click 运行 tab → 「开始一轮」 button visible.
     - Console zero errors throughout.
  4. Cleanup: stop servers, remove test project.

Per the task's CRITICAL CONSTRAINT: if serving frontend + backend together is
ambiguous or the vite dev server won't start, STOP and report. We chose option
(b) from the task — start vite dev server + backend, Playwright navigates to
vite, /api proxied to backend — and verify both come up before the test runs.

If the Playwright chromium binary is not installed, every test is skipped with
a recorded reason (mirrors tests/e2e/test_api_skeleton.py).
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

from tests.e2e._procutil import kill_port_listener
from tests.e2e._procutil import kill_process_tree as _kill_process_tree

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
        "Run `python -m playwright install chromium` to enable this test."
    ),
)


# ── Constants ────────────────────────────────────────────────────────────

#: Vite dev server port (matches web/vite.config.ts).
VITE_PORT = 5173
#: FastAPI backend port (matches the proxy target in web/vite.config.ts).
BACKEND_PORT = 8000
#: Project display name used in the test (cleaned up at the end).
TEST_PROJECT_NAME = "Playwright Flow Test"


# ── Helpers ──────────────────────────────────────────────────────────────


def _free_port() -> int:
    """Return an OS-assigned free TCP port (used only to probe; the actual
    servers use the fixed VITE_PORT / BACKEND_PORT so the vite proxy works)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_port(host: str, port: int, *, timeout_s: float = 20.0) -> None:
    """Poll a TCP port until it accepts a connection or raise ``RuntimeError``.

    Vite can take a few seconds to bind (esbuild pre-bundle + dependency
    optimisation on first start). We poll up to *timeout_s* seconds.
    """
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:
            last_err = exc
            time.sleep(0.2)
    msg = (
        f"server at {host}:{port} did not accept connections within {timeout_s}s "
        f"(last_err={last_err!r})"
    )
    raise RuntimeError(msg)


def _wait_for_http(
    url: str,
    *,
    timeout_s: float = 20.0,
    expected_status: int = 200,
) -> None:
    """Poll *url* with a plain HTTP GET until it returns *expected_status*."""
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


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def app_root(tmp_path: Path) -> Path:
    """Build a minimal repo root with config/ + workspaces/ skeleton.

    Mirrors the per-route unit-test fixtures so the integration test runs
    against the same on-disk layout the routes expect. The repo root is
    placed under pytest's tmp_path so it is cleaned up automatically.
    """
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
        yaml.safe_dump(
            {"runner": {"timeout_seconds": 600, "max_retries": 3}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def backend_url(app_root: Path) -> Generator[str, None, None]:
    """Start the FastAPI backend on BACKEND_PORT and yield its base URL.

    Uses a bootstrap script so the subprocess can import ``app.api.server``
    with the right repo root on sys.path. The runner factories already
    default to :class:`MockRunner` (see ``app/api/routes/workflow.py`` and
    ``app/api/routes/chat.py``), so no monkeypatching is required — the
    backend is LLM-credential-free by default (guide 傻瓜式 dry-run).
    """
    project_root = Path(__file__).resolve().parents[2]
    bootstrap = app_root / "_e2e_backend_bootstrap.py"
    bootstrap.write_text(
        f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(project_root)!r})
import uvicorn
from app.api.server import create_app
app = create_app(Path({str(app_root)!r}))
uvicorn.run(app, host='127.0.0.1', port={BACKEND_PORT}, log_level='warning')
""",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(bootstrap)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port("127.0.0.1", BACKEND_PORT, timeout_s=20.0)
        _wait_for_http(f"http://127.0.0.1:{BACKEND_PORT}/api/projects", timeout_s=10.0)
        yield f"http://127.0.0.1:{BACKEND_PORT}"
    finally:
        _kill_process_tree(proc)
        kill_port_listener(BACKEND_PORT)
        bootstrap.unlink(missing_ok=True)


@pytest.fixture()
def frontend_url(app_root: Path) -> Generator[str, None, None]:
    """Start the vite dev server on VITE_PORT and yield its base URL.

    ``npm run dev`` runs ``vite`` which serves the React app and proxies
    ``/api`` → ``http://localhost:8000`` (web/vite.config.ts). The backend
    must already be up on BACKEND_PORT (this fixture depends on
    ``backend_url`` indirectly via the test signature).

    Per the task's CRITICAL CONSTRAINT: if the vite dev server won't start,
    we raise a clear error (the test reports rather than silently failing).
    """
    web_dir = Path(__file__).resolve().parents[2] / "web"
    if not (web_dir / "node_modules").is_dir():
        msg = (
            f"web/node_modules not found at {web_dir}. "
            "Run `cd web && npm install` before this E2E test."
        )
        raise RuntimeError(msg)
    if not (web_dir / "package.json").is_file():
        msg = f"web/package.json not found at {web_dir}; cannot start vite."
        raise RuntimeError(msg)

    # ``npm.cmd`` is the Windows wrapper that resolves the npm.ps1 / npm bin.
    # We pass --port explicitly to be robust against vite.config.ts changes.
    # A vite orphaned by a previous run would squat on the strict port and
    # serve a half-dead app — clear it before binding.
    kill_port_listener(VITE_PORT)

    env = os.environ.copy()
    proc = subprocess.Popen(
        ["npm.cmd", "run", "dev", "--", "--port", str(VITE_PORT), "--strictPort"],
        cwd=str(web_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        shell=False,
    )
    try:
        _wait_for_port("127.0.0.1", VITE_PORT, timeout_s=30.0)
        _wait_for_http(f"http://127.0.0.1:{VITE_PORT}/", timeout_s=20.0)
        yield f"http://127.0.0.1:{VITE_PORT}"
    finally:
        _kill_process_tree(proc)
        kill_port_listener(VITE_PORT)


@pytest.fixture()
def console_errors() -> list[str]:
    """Collect browser console error messages (per the task's
    "console zero errors" assertion)."""
    return []


# ── Tests ────────────────────────────────────────────────────────────────


def test_full_frontend_flow(
    backend_url: str,
    frontend_url: str,
    console_errors: list[str],
) -> None:
    """Walk every React view end-to-end against the mock backend.

    Per the task spec, the flow is: OverviewView → create project →
    WorkflowCanvas → Chat → Resources → Config → Novel → RP → Run,
    with console zero errors throughout.
    """
    from playwright.sync_api import sync_playwright

    created_project_id: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Capture every console message of type "error" — the task's hard
        # rule is "console zero errors throughout". We also capture
        # pageerror events (uncaught exceptions) as console errors.
        def _on_console(msg) -> None:  # type: ignore[no-untyped-def]
            if msg.type == "error":
                console_errors.append(f"console.error: {msg.text}")

        def _on_pageerror(err) -> None:  # type: ignore[no-untyped-def]
            console_errors.append(f"pageerror: {err}")

        page.on("console", _on_console)
        page.on("pageerror", _on_pageerror)

        # ── 1. Open the app → OverviewView renders ──────────────────────
        page.goto(frontend_url, wait_until="networkidle")
        # The OverviewView header is "项目概览".
        page.wait_for_selector("h1.view__title", timeout=10_000)
        overview_title = page.locator("h1.view__title").first.inner_text()
        assert overview_title == "项目概览", (
            f"expected OverviewView title '项目概览', got {overview_title!r}"
        )

        # ── 2. Create a project via the modal ──────────────────────────
        # The 「+ 新建项目」 button is in the OverviewView header.
        create_btn = page.locator("button.btn--primary", has_text="+ 新建项目").first
        create_btn.click()
        # Modal opens with a form containing the title "新建项目".
        modal_title = page.locator("#create-project-title")
        modal_title.wait_for(state="visible", timeout=5_000)
        assert modal_title.inner_text() == "新建项目"

        # Fill in the display_name.
        name_input = page.locator(".modal__form .field__input").first
        name_input.fill(TEST_PROJECT_NAME)
        # Mode defaults to "novel" — no need to change it.
        # Submit the form. The submit button is the one with text "创建".
        submit_btn = page.locator(".modal__actions button[type='submit']").first
        submit_btn.click()

        # The modal closes and the new project card appears in the list.
        # Wait for a project card whose name matches TEST_PROJECT_NAME.
        project_card = page.locator(
            ".project-card", has_text=TEST_PROJECT_NAME
        ).first
        project_card.wait_for(state="visible", timeout=15_000)
        # The project's id is shown in the card footer area (.project-card__id).
        card_id_el = project_card.locator(".project-card__id").first
        created_project_id = card_id_el.inner_text().strip()
        assert created_project_id.startswith("proj_"), (
            f"expected project id 'proj_*', got {created_project_id!r}"
        )

        # Click the project card to select it (sets activeProject in the store).
        project_card.click()
        # The active project card gets the --active modifier.
        page.wait_for_selector(
            f".project-card--active .project-card__id:has-text('{created_project_id}')",
            timeout=5_000,
        )

        # ── 3. WorkflowCanvas tab → canvas renders with default nodes ─
        _click_nav_tab(page, "工作流")
        page.wait_for_url(f"{frontend_url}/workflow", timeout=5_000)
        # The WorkflowCanvasView header is "工作流画布".
        page.wait_for_selector("h1.view__title:has-text('工作流画布')", timeout=10_000)
        # react-flow renders nodes with the .react-flow__node class.
        # The default canvas is built from the agent registry (5 built-in
        # agents), so at least 1 node should be present.
        page.wait_for_selector(".react-flow__node", timeout=10_000)
        node_count = page.locator(".react-flow__node").count()
        assert node_count >= 1, (
            f"expected ≥1 react-flow node in the default canvas, got {node_count}"
        )

        # ── 4. Chat tab → send "Hello director" → director response ────
        _click_nav_tab(page, "对话")
        page.wait_for_url(f"{frontend_url}/chat", timeout=5_000)
        page.wait_for_selector("h1.view__title:has-text('Director 对话')", timeout=10_000)
        # The chat textarea is the input box.
        chat_textarea = page.locator(".chat-view__textarea").first
        chat_textarea.wait_for(state="visible", timeout=5_000)
        chat_textarea.fill("Hello director")
        # The send button is the form's submit button.
        send_btn = page.locator(".chat-view__input button[type='submit']").first
        send_btn.click()
        # The director's response bubble appears with class chat-msg--director.
        # MockRunner returns "[mock:director] Response for prompt <hash>".
        director_msg = page.locator(".chat-msg--director").first
        director_msg.wait_for(state="visible", timeout=15_000)
        director_text = director_msg.locator(".chat-msg__body").inner_text()
        assert "[mock:" in director_text, (
            f"expected mock director response, got {director_text!r}"
        )

        # ── 5. Resources tab → 8 types → select 当前状态 → edit → save ─
        _click_nav_tab(page, "资源")
        page.wait_for_url(f"{frontend_url}/resources", timeout=5_000)
        page.wait_for_selector("h1.view__title:has-text('资源编辑器')", timeout=10_000)
        # The resource tree lists 8 types.
        tree_items = page.locator(".resource-tree__item")
        tree_items.first.wait_for(state="visible", timeout=10_000)
        type_count = tree_items.count()
        assert type_count == 8, (
            f"expected 8 resource types in the tree, got {type_count}"
        )
        # Click the 当前状态 (state) type.
        state_item = page.locator(".resource-tree__item", has_text="当前状态").first
        state_item.click()
        # The editor area loads; the CodeMirror host renders.
        cm_host = page.locator(".resource-view__editor .cm-host").first
        cm_host.wait_for(state="visible", timeout=10_000)
        # The save button is disabled until the content is dirty.
        save_btn = page.locator(
            ".resource-view__toolbar button.btn--primary"
        ).first
        # Type into the CodeMirror editor. CodeMirror 6 uses a hidden
        # textarea (.cm-contentEditable contenteditable) — we focus it
        # and type via the keyboard.
        _type_into_codemirror(page, cm_host, "Playwright edited state content.")
        # The save button should now be enabled (dirty).
        page.wait_for_function(
            """() => {
                const btn = document.querySelector(
                    '.resource-view__toolbar button.btn--primary'
                );
                return btn && !btn.disabled;
            }""",
            timeout=5_000,
        )
        save_btn.click()
        # After save, the dirty indicator disappears. We wait for the
        # "有未保存的更改" hint to go away (or just confirm no error
        # appeared). The store flips dirty=false on a successful save.
        page.wait_for_function(
            """() => {
                const hint = document.querySelector(
                    '.resource-view__editor .overview__loading'
                );
                return !hint || !hint.textContent.includes('未保存');
            }""",
            timeout=10_000,
        )

        # ── 6. Config tab → edit writer agent's Model → save ───────────
        _click_nav_tab(page, "配置")
        page.wait_for_url(f"{frontend_url}/config", timeout=5_000)
        page.wait_for_selector("h1.view__title:has-text('配置')", timeout=10_000)
        # The Agent config section has one card per agent. Find the writer.
        writer_card = page.locator(
            ".config-view__agents .config-section", has_text="Agent · writer"
        ).first
        writer_card.wait_for(state="visible", timeout=10_000)
        # The Model input is the one whose preceding label is "Model".
        model_input = writer_card.locator(
            "label.field:has(span.field__label:has-text('Model')) input.field__input"
        ).first
        model_input.fill("premium")
        # Save the writer agent.
        writer_save = writer_card.locator(
            ".agent-form__actions button[type='submit']"
        ).first
        writer_save.click()
        # After save, the config store reloads agents; the writer's model
        # should still read "premium" after the reload. We walk the DOM
        # with plain CSS + textContent checks (Playwright's :has-text
        # pseudo-selector is NOT a real CSS selector and can't be used
        # inside page.evaluate / wait_for_function).
        page.wait_for_function(
            """() => {
                const cards = document.querySelectorAll(
                    '.config-view__agents .config-section'
                );
                for (const c of cards) {
                    if (!c.textContent.includes('Agent · writer')) continue;
                    const labels = c.querySelectorAll('label.field');
                    for (const lbl of labels) {
                        const lblText = lbl.querySelector('.field__label');
                        if (lblText && lblText.textContent.trim() === 'Model') {
                            const inp = lbl.querySelector('input.field__input');
                            return inp && inp.value === 'premium';
                        }
                    }
                }
                return false;
            }""",
            timeout=10_000,
        )

        # ── 7. Novel tab → empty state (no chapters yet) ───────────────
        _click_nav_tab(page, "作品")
        page.wait_for_url(f"{frontend_url}/novel", timeout=5_000)
        page.wait_for_selector("h1.view__title:has-text('作品阅读')", timeout=10_000)
        # A freshly scaffolded project has no exported chapters → empty hint.
        empty_novel_hint = page.locator(
            ".overview__empty-hint:has-text('还没有导出的章节')"
        ).first
        empty_novel_hint.wait_for(state="visible", timeout=5_000)

        # ── 8. RP tab → action input visible ───────────────────────────
        _click_nav_tab(page, "RP")
        page.wait_for_url(f"{frontend_url}/rp", timeout=5_000)
        page.wait_for_selector("h1.view__title:has-text('RP 互动')", timeout=10_000)
        rp_textarea = page.locator(".rp-view__input textarea.field__input").first
        rp_textarea.wait_for(state="visible", timeout=5_000)
        # The submit action button is visible.
        rp_submit = page.locator(
            ".rp-view__input button[type='submit']"
        ).first
        assert rp_submit.is_visible(), "RP submit action button not visible"

        # ── 9. Run tab → 「开始一轮」 button visible ───────────────────
        _click_nav_tab(page, "运行")
        page.wait_for_url(f"{frontend_url}/run", timeout=5_000)
        page.wait_for_selector("h1.view__title:has-text('运行面板')", timeout=10_000)
        start_btn = page.locator(
            "button.btn--primary:has-text('开始一轮')"
        ).first
        start_btn.wait_for(state="visible", timeout=5_000)
        assert start_btn.is_visible(), "「开始一轮」 button not visible"

        browser.close()

    # ── 10. Console zero errors ─────────────────────────────────────────
    assert console_errors == [], (
        f"expected zero console errors, got: {console_errors}"
    )

    # ── 11. Cleanup: remove the test project via the API ───────────────
    if created_project_id is not None:
        import urllib.error
        import urllib.request

        try:
            req = urllib.request.Request(
                f"{backend_url}/api/projects/{created_project_id}",
                method="DELETE",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                # 204 No Content on success.
                assert resp.status in (204, 200), (
                    f"delete project {created_project_id} returned {resp.status}"
                )
        except urllib.error.URLError as exc:
            # Cleanup failure is non-fatal — the project lives under
            # pytest's tmp_path which is cleaned up automatically. We
            # surface it so the test output records the failure.
            print(f"WARNING: cleanup delete failed for {created_project_id}: {exc}")


# ── View-level helper functions ──────────────────────────────────────────


def _click_nav_tab(page, label: str) -> None:
    """Click a NavRail tab by its visible label (e.g. "工作流", "对话").

    The NavRail buttons have ``title=<label>`` and a ``.navrail__label``
    span with the label text (visible when the rail is expanded, which
    is the default). We match on the title attribute for robustness —
    the label span is hidden when collapsed.
    """
    tab = page.locator(f".navrail__tab[title='{label}']").first
    tab.wait_for(state="visible", timeout=5_000)
    tab.click()


def _type_into_codemirror(page, cm_host_locator, text: str) -> None:
    """Type *text* into a CodeMirror 6 editor host element.

    CodeMirror 6 renders a ``.cm-content`` contenteditable div inside the
    host. We focus it, select-all (Ctrl+A) so the new text replaces any
    pre-loaded content, then use ``page.keyboard.type`` with a small
    per-key delay. The delay is important: CodeMirror 6's updateListener
    fires on docChanged transactions, and ``keyboard.type`` without a
    delay can coalesce the keydown events in a way that CodeMirror's
    keymap intercepts (defaultKeymap binds letters to nothing, but the
    transaction still needs to flush). ``keyboard.insert_text`` does
    NOT work here — it fires a single ``insertText`` beforeinput event
    that CodeMirror does not route through its transaction pipeline
    (verified empirically: the doc stays at its previous content).
    """
    cm_content = cm_host_locator.locator(".cm-content").first
    cm_content.wait_for(state="visible", timeout=5_000)
    # Focus + select-all (Ctrl+A) so the typed text replaces whatever is there.
    cm_content.click()
    page.keyboard.press("Control+a")
    # Small delay to let CodeMirror process the select-all before the type.
    page.wait_for_timeout(50)
    # delay=20ms per key — lets CodeMirror flush each transaction + onChange.
    page.keyboard.type(text, delay=20)
    # Give React + CodeMirror a tick to flush the onChange callback.
    page.wait_for_timeout(150)


# ── Sanity: the server fixtures actually start ───────────────────────────


def test_backend_fixture_starts_real_port(backend_url: str) -> None:
    """Defensive: the ``backend_url`` fixture binds a real port and the
    URL is reachable via a plain socket connection."""
    import urllib.parse

    parsed = urllib.parse.urlparse(backend_url)
    host = parsed.hostname
    port = parsed.port
    assert host is not None and port is not None, (
        f"backend_url did not parse to host:port: {backend_url!r}"
    )
    with socket.create_connection((host, port), timeout=2.0):
        pass  # connection succeeded — the port is live.


def test_frontend_fixture_serves_html(frontend_url: str) -> None:
    """Defensive: the ``frontend_url`` fixture serves a real HTML page
    (vite dev server returns the React app shell)."""
    import urllib.request

    req = urllib.request.Request(frontend_url, method="GET")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200, f"expected 200, got {resp.status}"
        body = resp.read().decode("utf-8", errors="replace")
        # The vite dev server returns an HTML shell with a #root div
        # and a script tag pointing to /src/main.tsx.
        assert "<div id=\"root\"" in body or "<div id='root'" in body, (
            f"expected an HTML shell with #root, got body[:200]={body[:200]!r}"
        )


def test_backend_creates_project_via_api(backend_url: str) -> None:
    """Defensive: the backend can create + list + delete a project via
    the API. This catches a backend bootstrap regression before the
    Playwright flow runs (which depends on a working backend)."""
    import urllib.error
    import urllib.request

    # POST /api/projects.
    req = urllib.request.Request(
        f"{backend_url}/api/projects",
        data=json.dumps({"display_name": "Sanity Project", "mode": "novel"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 201, f"create project failed: {resp.status}"
        created = json.loads(resp.read().decode("utf-8"))
    pid = created["id"]
    assert pid.startswith("proj_")

    # GET /api/projects → list contains the new project.
    with urllib.request.urlopen(f"{backend_url}/api/projects", timeout=5.0) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    ids = [p["id"] for p in body["projects"]]
    assert pid in ids

    # DELETE /api/projects/{pid}.
    del_req = urllib.request.Request(
        f"{backend_url}/api/projects/{pid}", method="DELETE"
    )
    with urllib.request.urlopen(del_req, timeout=5.0) as resp:
        assert resp.status in (204, 200)
