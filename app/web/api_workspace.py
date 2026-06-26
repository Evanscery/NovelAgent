"""工作区 API：创建 / 列举 / 删除自包含 story 工作区。

创建复用 ``StoryWorkspaceManager.init_story``（与 CLI ``init-story`` 同一套脚手架），
保证项目间隔离与目录一致性。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.story_workspace import StoryWorkspaceManager
from app.web.paths import resolve_workspace

_NAME_RE = re.compile(r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_\-一-鿿]{0,63}$")


class WorkspaceError(ValueError):
    """工作区操作失败（参数非法 / 已存在 / 不存在）。"""


def list_workspaces(root: Path | str) -> list[dict[str, str]]:
    root_path = Path(root).resolve()
    base = root_path / "workspaces"
    stories: list[dict[str, str]] = []
    if base.exists():
        for story in sorted(path for path in base.iterdir() if path.is_dir()):
            stories.append({"name": story.name, "path": str(story.relative_to(root_path)).replace("\\", "/")})
    return stories


def create_workspace(root: Path | str, name: str, theme: str = "") -> dict[str, str]:
    """新建工作区。``name`` 为目录名，``theme`` 写入 PROJECT.md/premise。"""
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceError("name required")
    clean = name.strip()
    if not _NAME_RE.match(clean):
        raise WorkspaceError("name 仅允许字母/数字/下划线/连字符/中文，长度 1-64，且不以连字符开头")
    root_path = Path(root).resolve()
    target = root_path / "workspaces" / clean
    if target.exists():
        raise WorkspaceError(f"工作区已存在：{clean}")
    manager = StoryWorkspaceManager(root_path)
    story_root = manager.init_story(target, theme or clean)
    rel = str(story_root.relative_to(root_path)).replace("\\", "/")
    return {"name": clean, "path": rel}


def delete_workspace(root: Path | str, rel_path: str) -> dict[str, str]:
    """删除工作区（危险操作，前端须二次确认）。"""
    root_path = Path(root).resolve()
    target = resolve_workspace(root_path, rel_path, must_exist=True)
    if target == (root_path / "workspaces").resolve():
        raise WorkspaceError("不能删除 workspaces 根目录")
    name = target.name
    shutil.rmtree(target)
    return {"name": name, "path": rel_path, "deleted": True}
