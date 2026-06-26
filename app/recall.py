from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.file_io import ProjectFileIO


CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS recall_fts
USING fts5(
  scene_id,
  source_type,
  path,
  title,
  content
);
"""


class RecallStore:
    """基于 SQLite FTS5 的轻量召回库。"""

    def __init__(self, root: Path | str, recall_config: dict[str, Any], file_io: ProjectFileIO):
        self.root = Path(root).resolve()
        self.config = recall_config
        self.file_io = file_io
        self.db_path = self.file_io.resolve(recall_config.get("db_path", "data/recall.db"))
        self.top_k = int(recall_config.get("top_k", 8))
        self.snippet_chars = int(recall_config.get("snippet_chars", 800))

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(CREATE_FTS_SQL)
            conn.commit()

    def clear(self) -> None:
        self.init_db()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM recall_fts")
            conn.commit()

    def index_memory(self) -> int:
        self.clear()
        count = 0
        for source in self.config.get("sources", []):
            source_path = self.file_io.resolve(source)
            if not source_path.exists():
                continue
            if source_path.is_dir():
                for file_path in sorted(source_path.glob("*.md")):
                    self._index_file(file_path)
                    count += 1
            elif source_path.is_file():
                self._index_file(source_path)
                count += 1
        return count

    def _index_file(self, file_path: Path) -> None:
        relative = file_path.relative_to(self.root).as_posix()
        content = file_path.read_text(encoding="utf-8")
        scene_id = self._scene_id_from_path_or_content(file_path, content)
        source_type = self._source_type(file_path)
        title = self._title_from_content(content) or file_path.stem
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO recall_fts(scene_id, source_type, path, title, content) VALUES (?, ?, ?, ?, ?)",
                (scene_id, source_type, relative, title, content),
            )
            conn.commit()

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, str]]:
        self.init_db()
        limit = top_k or self.top_k
        safe_query = self._safe_query(query)
        if not safe_query:
            return []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT scene_id, source_type, path, title, snippet(recall_fts, 4, '[', ']', ' ... ', 20) AS snippet
                FROM recall_fts
                WHERE recall_fts MATCH ?
                LIMIT ?
                """,
                (safe_query, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def write_report(self, query: str, output_path: str) -> None:
        results = self.search(query)
        lines = [
            "# Recall Report",
            "",
            "## Query",
            "",
            query or "无显式关键词，使用当前状态与大纲。",
            "",
            "## Retrieved Snippets",
            "",
        ]
        if not results:
            lines.append("未检索到相关历史片段。")
        for index, row in enumerate(results, start=1):
            snippet = row.get("snippet", "")[: self.snippet_chars]
            lines.extend(
                [
                    f"### Result {index}",
                    f"- Source: {row.get('path', '')}",
                    f"- Scene: {row.get('scene_id', '')}",
                    f"- Type: {row.get('source_type', '')}",
                    f"- Title: {row.get('title', '')}",
                    "- Content:",
                    "",
                    snippet,
                    "",
                ]
            )
        lines.extend(["## Knowledge Boundaries", "", "请结合 characters.md 和 state.md 判断角色认知边界。", ""])
        self.file_io.write_text(output_path, "\n".join(lines))

    def default_query_from_files(self, paths: list[str]) -> str:
        parts: list[str] = []
        for path in paths:
            if self.file_io.exists(path):
                text = self.file_io.read_text(path)
                parts.append(text[:1000])
        return " ".join(parts).strip() or "当前场景"

    def _safe_query(self, query: str) -> str:
        words = re.findall(r"[\w一-鿿]+", query)
        words = [word for word in words if len(word) > 1 or "一" <= word <= "鿿"]
        quoted = [f'"{word}"' for word in words[:20]]
        return " OR ".join(quoted)

    def _scene_id_from_path_or_content(self, file_path: Path, content: str) -> str:
        stem = file_path.stem
        if stem.upper().startswith("C") and "S" in stem.upper():
            return stem
        for line in content.splitlines():
            stripped = line.strip("# -")
            if stripped.upper().startswith("C") and "S" in stripped.upper():
                return stripped.split()[0]
        return "GLOBAL"

    def _source_type(self, file_path: Path) -> str:
        parts = {part.lower() for part in file_path.parts}
        if "fulltext" in parts:
            return "fulltext"
        if file_path.name == "summaries.md":
            return "summary"
        if file_path.name == "index.md":
            return "index"
        return "memory"

    def _title_from_content(self, content: str) -> str | None:
        for line in content.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
        return None
