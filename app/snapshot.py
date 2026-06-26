from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.file_io import ProjectFileIO


class SnapshotBuilder:
    """生成本轮冻结输入快照。"""

    def __init__(self, root: Path | str, paths_config: dict[str, Any], file_io: ProjectFileIO):
        self.root = Path(root).resolve()
        self.paths = paths_config
        self.file_io = file_io

    def write_snapshot(self, scene_id: str, input_paths: list[str], output_path: str) -> None:
        lines = [
            "# Frozen Run Input Snapshot",
            "",
            "## Scene",
            f"- Scene ID: {scene_id}",
            f"- Created At: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]
        for path in input_paths:
            if not self.file_io.exists(path):
                lines.extend([f"## Missing File: {path}", "", "该文件不存在。", ""])
                continue
            content = self.file_io.read_text(path).strip()
            lines.extend([f"## File: {path}", "", content, ""])
        self.file_io.write_text(output_path, "\n".join(lines))
