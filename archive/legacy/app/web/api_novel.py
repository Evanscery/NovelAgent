"""小说阅读 API（只读）：列出章节与场景、读取章节正文 / 场景全文本。

NOVEL-A1/A2：前端「作品」阅读标签需要能拿到实际正文，而现有 ``/api/story`` 只返回
``chapters`` / ``archives`` 的文件名列表，``/api/file`` 又被 ``EDITABLE_DIRS`` 挡在
``novels/`` 与 ``memory/fulltext/`` 之外。这里补一个**只读**、**严格限定可读根**的通道：

- 可读根仅 ``workspaces/<story>/novels`` 与 ``workspaces/<story>/memory/fulltext``。
- 复用 ``safe_resolve`` 防 ``..`` 穿越与盘符；只返回 ``.txt`` / ``.md``；不允许写入。
- 不调用任何 LLM。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.chapter_tools import chapter_body_from_final_text, chapter_title_from_final_text, count_chinese_chars
from app.web.paths import PathSafetyError, resolve_workspace, safe_resolve

# 章节文件名形如 chapter_01.txt / chapter_02.txt。
_CHAPTER_RE = re.compile(r"^chapter_(\d+)\.txt$", re.IGNORECASE)
# 场景 ID 形如 C01S01。
_SCENE_RE = re.compile(r"^[Cc]\d{2}[Ss]\d{2}$")
# 只允许这些扩展名被读取（只读，不暴露其它二进制 / 临时文件）。
READABLE_SUFFIXES = (".txt", ".md")


class NovelApiError(ValueError):
    """小说阅读操作失败。"""


def _novels_dir(ws: Path) -> Path:
    return ws / "novels"


def _fulltext_dir(ws: Path) -> Path:
    return ws / "memory" / "fulltext"


def list_novel(root: Path | str, ws_rel: str) -> dict[str, object]:
    """返回工作区的小说结构：章节列表 + 场景列表，按顺序排列。

    章节优先来自 ``novels/chapter_*.txt``（成书产物）；场景来自
    ``memory/fulltext/<C0xS0y>.md``。两者都只读、零 LLM。
    """
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)

    chapters: list[dict[str, object]] = []
    novels = _novels_dir(ws)
    if novels.is_dir():
        for path in sorted(novels.iterdir()):
            if not path.is_file():
                continue
            match = _CHAPTER_RE.match(path.name)
            if not match:
                continue
            num = int(match.group(1))
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            chapters.append(
                {
                    "number": num,
                    "file": path.name,
                    "title": chapter_title_from_final_text(text, num),
                    "char_count": count_chinese_chars(text),
                    "size": path.stat().st_size,
                }
            )
        chapters.sort(key=lambda c: c["number"])

    scenes: list[dict[str, object]] = []
    fulltext = _fulltext_dir(ws)
    if fulltext.is_dir():
        for path in sorted(fulltext.iterdir()):
            if not path.is_file() or path.suffix.lower() not in READABLE_SUFFIXES:
                continue
            scene_id = path.stem
            if not _SCENE_RE.match(scene_id):
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="replace")
            scenes.append(
                {
                    "scene_id": scene_id,
                    "chapter": int(scene_id[1:3]),
                    "char_count": count_chinese_chars(text),
                    "size": path.stat().st_size,
                }
            )
        scenes.sort(key=lambda s: s["scene_id"])

    # NOVEL-A7：按 scene_id 前缀（C01 -> 第 1 章）把场景归到对应章节，
    # 让作者在阅读页看到「第 N 章 ← C0xS0y 场景组成」。
    scenes_by_chapter: dict[int, list[str]] = {}
    for s in scenes:
        scenes_by_chapter.setdefault(s["chapter"], []).append(s["scene_id"])
    for ch in chapters:
        ch["scene_ids"] = scenes_by_chapter.get(ch["number"], [])

    return {
        "path": ws_rel,
        "chapters": chapters,
        "scenes": scenes,
        "has_novel": bool(chapters),
    }


def read_chapter(root: Path | str, ws_rel: str, chapter: str) -> dict[str, object]:
    """读取某章节正文：``chapter`` 接受章节序号（``01``/``1``）或文件名。

    可读根严格限定在 ``workspaces/<story>/novels`` 内，经 ``safe_resolve`` 防穿越。
    """
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)
    novels = _novels_dir(ws)

    # 把 chapter 归一为 chapter_NN.txt 文件名，拒绝任何含路径分隔符 / 盘符的输入。
    chapter = (chapter or "").strip()
    if not chapter:
        raise NovelApiError("chapter required")
    if "/" in chapter or "\\" in chapter or Path(chapter).drive:
        raise NovelApiError(f"非法章节标识：{chapter}")
    if chapter.isdigit():
        file_name = f"chapter_{int(chapter):02d}.txt"
    elif _CHAPTER_RE.match(chapter):
        file_name = chapter
    else:
        raise NovelApiError(f"非法章节标识：{chapter}")

    target = safe_resolve(novels, file_name, must_exist=True)
    if not target.is_file() or target.suffix.lower() not in READABLE_SUFFIXES:
        raise NovelApiError(f"不是可读章节文件：{file_name}")
    if novels not in target.parents and target != novels:
        raise PathSafetyError(f"路径越界：{file_name}")

    text = target.read_text(encoding="utf-8-sig")
    num_match = _CHAPTER_RE.match(target.name)
    num = int(num_match.group(1)) if num_match else 0
    return {
        "path": ws_rel,
        "chapter": num,
        "file": target.name,
        "title": chapter_title_from_final_text(text, num),
        "body": chapter_body_from_final_text(text),
        "char_count": count_chinese_chars(text),
    }


def read_scene(root: Path | str, ws_rel: str, scene_id: str) -> dict[str, object]:
    """读取某场景全文本：``scene_id`` 形如 ``C01S01``，取自 ``memory/fulltext/<id>.md``。

    可读根严格限定在 ``workspaces/<story>/memory/fulltext`` 内。
    """
    root_path = Path(root).resolve()
    ws = resolve_workspace(root_path, ws_rel, must_exist=True)
    fulltext = _fulltext_dir(ws)

    scene_id = (scene_id or "").strip()
    if not scene_id:
        raise NovelApiError("scene_id required")
    if "/" in scene_id or "\\" in scene_id or Path(scene_id).drive:
        raise NovelApiError(f"非法场景标识：{scene_id}")
    if not _SCENE_RE.match(scene_id):
        raise NovelApiError(f"非法场景标识：{scene_id}")

    file_name = f"{scene_id}.md"
    target = safe_resolve(fulltext, file_name, must_exist=True)
    if not target.is_file() or target.suffix.lower() not in READABLE_SUFFIXES:
        raise NovelApiError(f"不是可读场景文件：{file_name}")
    if fulltext not in target.parents and target != fulltext:
        raise PathSafetyError(f"路径越界：{file_name}")

    text = target.read_text(encoding="utf-8-sig")
    return {
        "path": ws_rel,
        "scene_id": scene_id,
        "chapter": int(scene_id[1:3]),
        "body": text.strip(),
        "char_count": count_chinese_chars(text),
    }
