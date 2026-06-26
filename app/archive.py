from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.chapter_tools import chapter_body_from_final_text, chapter_title_from_final_text, count_chinese_chars
from app.file_io import ProjectFileIO


@dataclass(frozen=True)
class MemoryEntry:
    scene_id: str
    title: str
    summary: str
    char_count: int
    fulltext_path: str | None = None
    archived_at: str | None = None


class ArchiveManager:
    """管理场景归档和工作区清理。"""

    def __init__(self, root, paths_config: dict[str, Any], file_io: ProjectFileIO):
        self.root = file_io.resolve(root)
        self.paths = paths_config
        self.file_io = file_io

    @property
    def work_dir(self):
        return self.file_io.resolve(self.paths["work"]["dir"])

    @property
    def archive_dir(self):
        return self.file_io.resolve(self.paths["archive"]["dir"])

    @property
    def fulltext_dir(self):
        return self.file_io.resolve(self.paths["memory"]["fulltext_dir"])

    @property
    def structured_memory_path(self):
        """IP-002：结构化 memory 主存；Markdown summaries/index 只是投影视图。"""
        summaries_path = self.file_io.resolve(self.paths["memory"]["summaries"])
        return summaries_path.parent / "scenes.json"

    def archive_scene(self, scene_id: str, overwrite: bool = False):
        target = self.archive_dir / scene_id
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"归档目录已存在：{target}")
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        if self.work_dir.exists():
            for item in self.work_dir.iterdir():
                if item.name == ".gitkeep":
                    continue
                destination = target / item.name
                if item.is_dir():
                    shutil.copytree(item, destination, ignore=shutil.ignore_patterns(".gitkeep"))
                else:
                    shutil.copy2(item, destination)

        state_path = self.file_io.resolve(self.paths["state"]["main"])
        if state_path.exists():
            shutil.copy2(state_path, target / "state_after.md")

        final_path = self.file_io.resolve(self.paths["work"]["final"])
        if final_path.exists():
            self.fulltext_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(final_path, self.fulltext_dir / f"{scene_id}.md")

        manifest = {
            "scene_id": scene_id,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "work_source": str(self.work_dir.relative_to(self.root)),
            "archive_path": str(target.relative_to(self.root)),
            "fulltext_path": str((self.fulltext_dir / f"{scene_id}.md").relative_to(self.root)) if final_path.exists() else None,
        }
        (target / "archive_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def append_memory_summary(self, scene_id: str) -> None:
        final_path = self.file_io.resolve(self.paths["work"]["final"])
        summaries_path = self.file_io.resolve(self.paths["memory"]["summaries"])
        index_path = self.file_io.resolve(self.paths["memory"]["index"])
        if not final_path.exists():
            return

        final_text = final_path.read_text(encoding="utf-8").strip()
        entry = self._build_memory_entry(scene_id, final_text)
        self._upsert_structured_memory(entry)
        self._write_structured_summaries(summaries_path, entry)
        self._write_structured_index(index_path, entry)

    def reset_work(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        keep_dirs = {"run_journal", "checkpoints"}
        for item in self.work_dir.iterdir():
            if item.name == ".gitkeep":
                continue
            if item.is_dir():
                if item.name in keep_dirs:
                    continue
                shutil.rmtree(item)
            else:
                item.unlink()
        reports = self.work_dir / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (self.work_dir / ".gitkeep").write_text("", encoding="utf-8")
        (reports / ".gitkeep").write_text("", encoding="utf-8")

    def _build_memory_entry(self, scene_id: str, final_text: str) -> MemoryEntry:
        title = chapter_title_from_final_text(final_text, 0)
        body = chapter_body_from_final_text(final_text)
        excerpt = body[:500].replace("\n", " ").strip() or "（空）"
        char_count = count_chinese_chars(body)
        fulltext = self.fulltext_dir / f"{scene_id}.md"
        fulltext_path = str(fulltext.relative_to(self.root)) if fulltext.exists() else None
        return MemoryEntry(
            scene_id=scene_id,
            title=title,
            summary=excerpt,
            char_count=char_count,
            fulltext_path=fulltext_path,
            archived_at=datetime.now(timezone.utc).isoformat(),
        )

    def normalize_memory_files(self) -> dict[str, int]:
        """把历史遗留的混合 summaries/index 归一到结构化格式（幂等）。

        早期 mock 阶段会向 summaries.md / index.md 追加非结构化文本块，
        以及重复 scene 块。本方法只保留每个 scene 的结构化块，去重并排序。
        """
        summaries_path = self.file_io.resolve(self.paths["memory"]["summaries"])
        index_path = self.file_io.resolve(self.paths["memory"]["index"])
        result = {"summaries": 0, "index": 0}

        if summaries_path.exists():
            blocks = self._parse_scene_blocks(summaries_path.read_text(encoding="utf-8"))
            self.file_io.write_text(summaries_path, self._render_scene_blocks("# Summaries", blocks))
            self._write_structured_memory_from_summary_blocks(blocks)
            result["summaries"] = len(blocks)

        if index_path.exists():
            blocks = self._parse_scene_blocks(index_path.read_text(encoding="utf-8"), prefix="## Scene ")
            self.file_io.write_text(index_path, self._render_scene_blocks("# Memory Index", blocks))
            result["index"] = len(blocks)

        return result

    def _write_structured_memory_from_summary_blocks(self, blocks: dict[str, list[str]]) -> None:
        payload = {"schema_version": 1, "entries": []}
        for scene_id, lines in sorted(blocks.items()):
            fields = self._parse_bullet_fields(lines)
            entry = {
                "scene_id": scene_id,
                "title": fields.get("Title", "初始化" if scene_id == "C01S00" else scene_id),
                "summary": fields.get("Summary", self._summary_from_block_lines(lines)),
                "char_count": self._parse_char_count(fields.get("Length", "0")),
                "fulltext_path": None,
                "archived_at": None,
            }
            payload["entries"].append(entry)
        self.structured_memory_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _parse_bullet_fields(self, lines: list[str]) -> dict[str, str]:
        fields: dict[str, str] = {}
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("- ") or ":" not in stripped:
                continue
            key, value = stripped[2:].split(":", 1)
            fields[key.strip()] = value.strip()
        return fields

    def _summary_from_block_lines(self, lines: list[str]) -> str:
        for line in lines[1:]:
            stripped = line.strip()
            if stripped and not stripped.startswith("-"):
                return stripped
        return ""

    def _parse_char_count(self, value: str) -> int:
        match = re.search(r"\d+", value)
        return int(match.group(0)) if match else 0

    def _upsert_structured_memory(self, entry: MemoryEntry) -> None:
        path = self.structured_memory_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._load_structured_memory(path)
        entries = payload.setdefault("entries", [])
        entries = [item for item in entries if item.get("scene_id") != entry.scene_id]
        entries.append(asdict(entry))
        entries.sort(key=lambda item: str(item.get("scene_id", "")))
        payload["entries"] = entries
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_structured_memory(self, path) -> dict[str, Any]:
        if not path.exists():
            return {"schema_version": 1, "entries": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"schema_version": 1, "entries": []}
        if not isinstance(payload, dict):
            return {"schema_version": 1, "entries": []}
        entries = payload.get("entries")
        if not isinstance(entries, list):
            payload["entries"] = []
        payload.setdefault("schema_version", 1)
        return payload

    def _write_structured_summaries(self, path, entry: MemoryEntry) -> None:
        existing = path.read_text(encoding="utf-8") if path.exists() else "# Summaries\n"
        blocks = self._parse_scene_blocks(existing)
        blocks[entry.scene_id] = [
            f"## {entry.scene_id}",
            "",
            f"- Title: {entry.title}",
            f"- Length: {entry.char_count} 中文字符",
            f"- Summary: {entry.summary}",
        ]
        self.file_io.write_text(path, self._render_scene_blocks("# Summaries", blocks))

    def _write_structured_index(self, path, entry: MemoryEntry) -> None:
        existing = path.read_text(encoding="utf-8") if path.exists() else "# Memory Index\n"
        blocks = self._parse_scene_blocks(existing, prefix="## Scene ")
        blocks[entry.scene_id] = [
            f"## Scene {entry.scene_id}",
            "",
            f"- Title: {entry.title}",
            "- Status: archived",
            f"- Summary Ref: {entry.scene_id}",
        ]
        self.file_io.write_text(path, self._render_scene_blocks("# Memory Index", blocks))

    def _parse_scene_blocks(self, text: str, prefix: str = "## ") -> dict[str, list[str]]:
        blocks: dict[str, list[str]] = {}
        current_id: str | None = None
        current_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith(prefix):
                if current_id is not None:
                    blocks[current_id] = current_lines
                current_id = line[len(prefix):].strip()
                if prefix == "## Scene ":
                    current_id = current_id
                current_lines = [line]
                continue
            if current_id is not None:
                current_lines.append(line)
        if current_id is not None:
            blocks[current_id] = current_lines

        normalized: dict[str, list[str]] = {}
        for key, lines in blocks.items():
            scene_id = key.removeprefix("Scene ").strip()
            if scene_id.upper().startswith("C"):
                normalized[scene_id] = self._clean_existing_block(lines)
        return dict(sorted(normalized.items()))

    def _clean_existing_block(self, lines: list[str]) -> list[str]:
        if not lines:
            return lines
        cleaned = [lines[0]]
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                cleaned.append(line)
                continue
            if stripped.startswith("-"):
                cleaned.append(line)
                continue
            # 丢弃混入 scene block 的非结构化噪声（如旧 mock 残留标题）
            break
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
        return cleaned

    def _render_scene_blocks(self, title: str, blocks: dict[str, list[str]]) -> str:
        rendered = [title, ""]
        for scene_id, lines in blocks.items():
            rendered.extend(lines)
            rendered.extend(["", ""])
        return "\n".join(rendered).rstrip() + "\n"
