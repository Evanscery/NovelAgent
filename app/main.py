"""CLI entry — ``serve`` subcommand only.

In keeping with the 傻瓜式 default mode, the only
CLI subcommand is ``serve``: it boots the FastAPI app via uvicorn.
``init-project`` / ``run-round`` / ``import-card`` are frontend-driven
(they are user-facing flows, not developer CLI tasks), so they are NOT
exposed as CLI subcommands.

Usage::

    python -m app.main serve --host 127.0.0.1 --port 8000
    python -m app.main serve --help
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.main",
        description="NovelAgent CLI. Default mode is frontend-driven (傻瓜式); "
        "the only CLI subcommand is `serve`.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the FastAPI server via uvicorn.")
    serve.add_argument(
        "--host",
        default=None,
        help="Bind host (overrides config/server.yaml). Default: 127.0.0.1.",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (overrides config/server.yaml). Default: 8000.",
    )
    serve.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root (defaults to the current working directory).",
    )
    serve.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (dev only).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve(args)
    # argparse with required=True + subparsers guarantees we never get here.
    parser.error(f"Unknown command: {args.command!r}")
    return 2  # unreachable


def _serve(args: argparse.Namespace) -> int:
    # Lazy import so `--help` and unrelated imports stay fast.
    import uvicorn

    from app.api.server import create_app
    from app.config_loader import ConfigLoader

    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    cfg = ConfigLoader(root).load_global()
    host = args.host or cfg.server.host
    port = args.port if args.port is not None else cfg.server.port

    # create_app wires the config-driven agent defaults (set_default_tools)
    # — the single wiring point for every entry path.
    app = create_app(root)
    uvicorn.run(app, host=host, port=port, reload=args.reload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
