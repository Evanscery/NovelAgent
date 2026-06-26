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
