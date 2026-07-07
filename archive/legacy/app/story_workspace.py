from __future__ import annotations

import shutil
from pathlib import Path

from app.file_io import ProjectFileIO


class StoryWorkspaceManager:
    """管理独立故事工作区。"""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.template_root = self._detect_template_root()
        self.stories_root = self.root / "stories"
        self.file_io = ProjectFileIO(self.root)

    def init_story(self, story_root: Path | str, theme: str) -> Path:
        target = self._resolve_story_root(story_root)
        if target.exists():
            raise FileExistsError(f"故事目录已存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.template_root, target, ignore=shutil.ignore_patterns("archive", "novels", "evaluation", "work", "memory/fulltext"))
        for relative in ("novels", "evaluation", "archive", "work", "work/reports", "memory/fulltext"):
            (target / relative).mkdir(parents=True, exist_ok=True)
        (target / "archive" / ".gitkeep").write_text("", encoding="utf-8")
        (target / "work" / ".gitkeep").write_text("", encoding="utf-8")
        (target / "work" / "reports" / ".gitkeep").write_text("", encoding="utf-8")
        self._reset_memory_files(target)
        self._write_theme(target, theme)
        return target

    def export_chapter_txt(self, story_root: Path | str, chapter_number: int, title: str, content: str) -> Path:
        root = self._resolve_story_root(story_root)
        novels = root / "novels"
        novels.mkdir(parents=True, exist_ok=True)
        path = novels / f"chapter_{chapter_number:02d}.txt"
        text = f"{title}\n\n{content.strip()}\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def reset_story_work(self, story_root: Path | str) -> None:
        root = self._resolve_story_root(story_root)
        work = root / "work"
        reports = work / "reports"
        if work.exists():
            for item in work.iterdir():
                if item.name == ".gitkeep":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        work.mkdir(parents=True, exist_ok=True)
        reports.mkdir(parents=True, exist_ok=True)
        (work / ".gitkeep").write_text("", encoding="utf-8")
        (reports / ".gitkeep").write_text("", encoding="utf-8")

    def _detect_template_root(self) -> Path:
        preferred = self.root / "novel_project"
        if preferred.exists():
            return preferred
        workspaces = sorted(path for path in (self.root / "workspaces").glob("*") if path.is_dir())
        if workspaces:
            return workspaces[0]
        raise FileNotFoundError("未找到可用的故事模板目录：novel_project/ 或 workspaces/*")

    def _reset_memory_files(self, story_root: Path) -> None:
        memory_dir = story_root / "memory"
        summaries = memory_dir / "summaries.md"
        index = memory_dir / "index.md"
        structured = memory_dir / "scenes.json"
        fulltext = memory_dir / "fulltext"
        summaries.write_text("# Summaries\n\n## C01S00\n\n项目刚初始化，尚未产生正式正文。\n", encoding="utf-8", newline="\n")
        index.write_text("# Memory Index\n\n## Scene C01S00\n\n- Title: 初始化\n- Status: bootstrap\n- Summary Ref: C01S00\n", encoding="utf-8", newline="\n")
        structured.write_text(
            '{\n  "schema_version": 1,\n  "entries": [\n    {\n      "scene_id": "C01S00",\n      "title": "初始化",\n      "summary": "项目刚初始化，尚未产生正式正文。",\n      "char_count": 0,\n      "fulltext_path": null,\n      "archived_at": null\n    }\n  ]\n}\n',
            encoding="utf-8",
            newline="\n",
        )
        if fulltext.exists():
            for file in fulltext.glob("*.md"):
                file.unlink()
        fulltext.mkdir(parents=True, exist_ok=True)

    def _write_theme(self, story_root: Path, theme: str) -> None:
        project_path = story_root / "PROJECT.md"
        original = project_path.read_text(encoding="utf-8")
        project_path.write_text(original + f"\n\n## Theme\n\n{theme}\n", encoding="utf-8", newline="\n")
        premise = story_root / "lore" / "premise.md"
        premise.write_text(
            premise.read_text(encoding="utf-8") + f"\n\n## Theme Seed\n\n{theme}\n",
            encoding="utf-8",
            newline="\n",
        )

    def _resolve_story_root(self, story_root: Path | str) -> Path:
        path = Path(story_root)
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()
