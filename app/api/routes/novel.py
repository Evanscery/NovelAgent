"""/api/novel — read chapters/scenes (小说查看器).

Endpoints
---------
* ``GET /api/novel/{project_id}``         — list exported chapters in
  ``workspaces/<id>/novels/`` (filenames ``chapter_*.txt``).
* ``GET /api/novel/{project_id}/{chapter}`` — read one chapter's content.
  *chapter* may be a filename (``chapter_01.txt``), a bare stem
  (``chapter_01``), or a numeric chapter number (``1`` →
  ``chapter_01.txt``).

The novel viewer is read-only here; editing/zoom is a front-end concern
(允许编辑/缩放等编辑器经典行为).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from fastapi import Path as FastPath

from app.api.routes._deps import ProjectIdPath, RootDep, resolve_project
from app.api.schemas import (
    NovelChapterListResponse,
    NovelChapterResponse,
    NovelChapterSummary,
)

router = APIRouter(prefix="/api/novel", tags=["novel"])

_CHAPTER_FILE_RE = re.compile(r"^chapter_(\d+)\.txt$")
_TRAVERSAL_RE = re.compile(r"[\\/]|\.\.|\x00")


ChapterPath = Annotated[str, FastPath(..., description="Chapter filename, stem, or number")]






def _parse_chapter_number(filename: str) -> int | None:
    m = _CHAPTER_FILE_RE.match(filename)
    return int(m.group(1)) if m else None


def _list_chapters(novels_dir: Path) -> list[NovelChapterSummary]:
    if not novels_dir.is_dir():
        return []
    out: list[NovelChapterSummary] = []
    for child in sorted(novels_dir.iterdir()):
        if not child.is_file() or not child.name.endswith(".txt"):
            continue
        out.append(
            NovelChapterSummary(
                filename=child.name,
                chapter_number=_parse_chapter_number(child.name),
                size_bytes=child.stat().st_size,
            )
        )
    return out


def _resolve_chapter_path(novels_dir: Path, chapter: str) -> Path:
    """Resolve *chapter* (filename / stem / number) to a real file path.

    Rejects any input containing path separators / traversal sequences
    before touching the filesystem.
    """
    if _TRAVERSAL_RE.search(chapter):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chapter identifier {chapter!r}",
        )

    candidate: Path | None = None
    # 1. Direct filename.
    direct = novels_dir / chapter
    if direct.is_file():
        candidate = direct
    # 2. Bare stem → append .txt.
    if candidate is None and not chapter.endswith(".txt"):
        stem_path = novels_dir / f"{chapter}.txt"
        if stem_path.is_file():
            candidate = stem_path
    # 3. Numeric → chapter_NN.txt (zero-padded to 2, the existing convention).
    if candidate is None and chapter.isdigit():
        num = int(chapter)
        padded = f"{num:02d}"
        for fname in (f"chapter_{padded}.txt", f"chapter_{num}.txt"):
            numbered = novels_dir / fname
            if numbered.is_file():
                candidate = numbered
                break

    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chapter {chapter!r} not found in project novels/",
        )
    return candidate


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/{project_id}", response_model=NovelChapterListResponse)
def list_chapters(project_id: ProjectIdPath, root: RootDep) -> NovelChapterListResponse:
    """List exported chapters in ``workspaces/<id>/novels/``."""
    path = resolve_project(root, project_id)
    chapters = _list_chapters(path / "novels")
    return NovelChapterListResponse(project_id=project_id, chapters=chapters)


@router.get("/{project_id}/{chapter}", response_model=NovelChapterResponse)
def read_chapter(
    project_id: ProjectIdPath,
    chapter: ChapterPath,
    root: RootDep,
) -> NovelChapterResponse:
    """Read one chapter's content (filename, stem, or number)."""
    path = resolve_project(root, project_id)
    file_path = _resolve_chapter_path(path / "novels", chapter)
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read chapter {file_path.name!r}: {exc}",
        ) from exc
    return NovelChapterResponse(
        project_id=project_id,
        filename=file_path.name,
        chapter_number=_parse_chapter_number(file_path.name),
        content=content,
    )


__all__ = ["list_chapters", "read_chapter", "router"]
