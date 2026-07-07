"""路径安全守卫：把一切文件读写限制在允许的根目录内，防目录穿越。

所有 web 写 API 必须经 ``safe_resolve`` 解析相对路径，绝不直接拼接用户输入。
"""
from __future__ import annotations

from pathlib import Path


class PathSafetyError(ValueError):
    """目标路径越出允许范围。"""


def safe_resolve(base: Path | str, rel: str, *, must_exist: bool = False) -> Path:
    """把 ``rel`` 解析为 ``base`` 之内的绝对路径，越界则抛 ``PathSafetyError``。

    - 拒绝绝对路径与盘符（``rel`` 必须是 base 内的相对路径）。
    - 解析后必须仍位于 ``base`` 子树内（含 ``..`` 穿越防护）。
    """
    base_path = Path(base).resolve()
    if rel is None:
        raise PathSafetyError("路径为空")
    candidate = Path(rel)
    if candidate.is_absolute() or candidate.drive:
        raise PathSafetyError(f"不允许绝对路径：{rel}")
    target = (base_path / candidate).resolve()
    if target != base_path and base_path not in target.parents:
        raise PathSafetyError(f"路径越界：{rel}")
    if must_exist and not target.exists():
        raise PathSafetyError(f"路径不存在：{rel}")
    return target


def resolve_workspace(root: Path | str, rel_path: str, *, must_exist: bool = True) -> Path:
    """把 ``rel_path``（如 ``workspaces/foo``）解析为 root 下的工作区目录。"""
    root_path = Path(root).resolve()
    target = safe_resolve(root_path, rel_path)
    workspaces_base = (root_path / "workspaces").resolve()
    if target != workspaces_base and workspaces_base not in target.parents:
        raise PathSafetyError(f"不是合法工作区路径：{rel_path}")
    if must_exist and not target.is_dir():
        raise PathSafetyError(f"工作区不存在：{rel_path}")
    return target
