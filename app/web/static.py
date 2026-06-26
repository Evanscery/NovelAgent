"""静态资源托管：存在 ``web/dist`` 则服务构建后的 SPA，否则回退到内联最小页。

SPA 路由回退：未命中实体文件的非 /api 路径，返回 index.html（前端路由接管）。
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from app.web.paths import safe_resolve


def dist_dir(root: Path | str, static_dir: str | None = None) -> Path:
    root_path = Path(root).resolve()
    if static_dir:
        candidate = Path(static_dir)
        return candidate if candidate.is_absolute() else (root_path / candidate).resolve()
    return (root_path / "web" / "dist").resolve()


def has_spa(root: Path | str, static_dir: str | None = None) -> bool:
    return (dist_dir(root, static_dir) / "index.html").is_file()


def resolve_asset(root: Path | str, url_path: str, static_dir: str | None = None) -> tuple[bytes, str] | None:
    """把 URL 路径映射到 dist 内文件，返回 (data, content_type)。

    - 命中实体文件 → 该文件。
    - 未命中且非资源后缀 → index.html（SPA 路由回退）。
    - dist 不存在 → None（由调用方回退内联页）。
    """
    base = dist_dir(root, static_dir)
    index = base / "index.html"
    if not index.is_file():
        return None

    rel = url_path.lstrip("/")
    if not rel or rel.endswith("/"):
        rel = (rel + "index.html") if rel else "index.html"

    try:
        target = safe_resolve(base, rel)
    except ValueError:
        target = index

    if not target.is_file():
        # SPA 回退：交给前端路由。
        target = index

    data = target.read_bytes()
    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
        content_type += "; charset=utf-8"
    return data, content_type
