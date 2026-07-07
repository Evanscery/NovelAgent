"""FastAPI app — CORS, IP whitelist, lifespan, router wiring.

``create_app(root)`` builds a :class:`fastapi.FastAPI` instance anchored at
a repo *root*. The root is stored in app state (``request.app.state.root``)
so route handlers can resolve project paths without global state.

Security middleware
-------------------
* **CORS** — origins from ``config/server.yaml`` (``server.allow_origins``).
* **IP whitelist** — if ``server.ip_whitelist`` is non-empty, every request
  whose client IP is not on the list is rejected with ``403``. An empty
  whitelist disables the check (open access, intended for local dev).

Routers from todos 22-23 are wired here as stubs (each router module is
imported only if it has real routes; the project router from todo 21 is
always included).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import projects as projects_routes
from app.config_loader import ConfigLoader

__all__ = ["create_app"]


def create_app(root: Path | str) -> FastAPI:
    """Build the FastAPI application anchored at *root*.

    Args:
        root: Repo root containing ``config/`` and ``workspaces/``.
    """
    root_path = Path(root).resolve()
    cfg = ConfigLoader(root_path).load_global()
    server_cfg = cfg.server

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Startup: nothing to spin up yet (no DB, no background workers).
        app.state.root = root_path
        yield
        # Shutdown: nothing to tear down yet.

    app = FastAPI(
        title="NovelAgent API",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.root = root_path  # also set eagerly so TestClient works without lifespan

    # ── CORS ──────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(server_cfg.allow_origins) or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── IP whitelist ──────────────────────────────────────────────────
    whitelist = list(server_cfg.ip_whitelist)

    @app.middleware("http")
    async def _ip_whitelist(request: Request, call_next):  # type: ignore[no-untyped-def]
        if whitelist:
            client = request.client
            client_ip = client.host if client else None
            if client_ip is None or client_ip not in whitelist:
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"IP {client_ip!r} not allowed"},
                )
        return await call_next(request)

    # ── Routers ───────────────────────────────────────────────────────
    app.include_router(projects_routes.router)
    # Todos 22-23 will include workflow/chat/resources/config/import/novel
    # routers here once they carry real routes.

    return app
