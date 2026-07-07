"""工作区文件 API：列文件树 / 读单文件 / 写单文件。

只暴露工作区内「可编辑」的目录，所有读写经 ``safe_resolve`` 守卫，限制在工作区子树内。
"""
from __future__ import annotations

from pathlib import Path

from app.web.paths import resolve_workspace, safe_resolve

# 前端可浏览/编辑的目录（相对工作区根）。其它目录（如 work/）默认不暴露给文件编辑器。
EDITABLE_DIRS = ("prompts", "modules", "presets", "lore", "state", "front", "data", "outline")
# 允许编辑的文本扩展名。
TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".json", ".txt")
# 单文件写入上限（防误传超大文件）。
MAX_FILE_BYTES = 2 * 1024 * 1024


class FileApiError(ValueError):
    """文件操作失败。"""


def list_files(root: Path | str, ws_rel: str) -> dict[str, object]:
    """返回工作区内可编辑文件树（按 EDITABLE_DIRS 分组的扁平列表）。"""
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)
    entries: list[dict[str, object]] = []
    for sub in EDITABLE_DIRS:
        base = ws / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            rel = str(path.relative_to(ws)).replace("\\", "/")
            entries.append(
                {
                    "rel": rel,
                    "dir": sub,
                    "name": path.name,
                    "suffix": path.suffix.lower().lstrip("."),
                    "size": path.stat().st_size,
                }
            )
    return {"path": ws_rel, "files": entries, "editable_dirs": list(EDITABLE_DIRS)}


def read_file(root: Path | str, ws_rel: str, file_rel: str) -> dict[str, object]:
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)
    target = safe_resolve(ws, file_rel, must_exist=True)
    if not target.is_file():
        raise FileApiError(f"不是文件：{file_rel}")
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise FileApiError(f"不支持的文件类型：{file_rel}")
    return {
        "path": ws_rel,
        "rel": file_rel.replace("\\", "/"),
        "content": target.read_text(encoding="utf-8-sig"),
        "suffix": target.suffix.lower().lstrip("."),
    }


def write_file(root: Path | str, ws_rel: str, file_rel: str, content: str) -> dict[str, object]:
    if not isinstance(content, str):
        raise FileApiError("content must be a string")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise FileApiError("文件过大")
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)
    target = safe_resolve(ws, file_rel)
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise FileApiError(f"不支持的文件类型：{file_rel}")
    # 只允许写入可编辑目录之内。
    top = Path(file_rel.replace("\\", "/")).parts[0] if file_rel else ""
    if top not in EDITABLE_DIRS:
        raise FileApiError(f"不可写入该目录：{top or file_rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n")
    target.write_text(normalized, encoding="utf-8", newline="\n")
    return {
        "path": ws_rel,
        "rel": file_rel.replace("\\", "/"),
        "bytes": len(normalized.encode("utf-8")),
        "saved": True,
    }


def move_file(
    root: Path | str,
    ws_rel: str,
    src_rel: str,
    dst_rel: str,
    overwrite: bool = False,
) -> dict[str, object]:
    """在工作区内移动/重命名文件。两路径都必须落在 EDITABLE_DIRS 子树内。

    - ``safe_resolve`` 已防 ``..``/绝对路径/越界。
    - 额外校验：src 与 dst 的顶层目录必须在 EDITABLE_DIRS 中（与 write_file 一致）。
    - dst 已存在且 ``overwrite`` 为假 → ``FileApiError``。
    - 调用 ``Path.rename`` 完成移动；父目录自动创建。
    """
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)
    src = safe_resolve(ws, src_rel, must_exist=True)
    if not src.is_file():
        raise FileApiError(f"源不是文件：{src_rel}")
    if src.suffix.lower() not in TEXT_SUFFIXES:
        raise FileApiError(f"不支持的源文件类型：{src_rel}")
    src_top = Path(src_rel.replace("\\", "/")).parts[0] if src_rel else ""
    if src_top not in EDITABLE_DIRS:
        raise FileApiError(f"不可移动该目录内的文件：{src_top or src_rel}")

    dst = safe_resolve(ws, dst_rel)
    if dst.suffix.lower() not in TEXT_SUFFIXES:
        raise FileApiError(f"不支持的目标文件类型：{dst_rel}")
    dst_top = Path(dst_rel.replace("\\", "/")).parts[0] if dst_rel else ""
    if dst_top not in EDITABLE_DIRS:
        raise FileApiError(f"不可移动到该目录：{dst_top or dst_rel}")

    if dst.exists():
        if not overwrite:
            raise FileApiError(f"目标已存在，未指定 overwrite：{dst_rel}")
        # overwrite=True 时先删除目标（避免跨文件系统 rename 落到已存在路径上行为不一致）。
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {
        "path": ws_rel,
        "src": src_rel.replace("\\", "/"),
        "dst": dst_rel.replace("\\", "/"),
        "moved": True,
    }
