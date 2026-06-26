from __future__ import annotations

from pathlib import Path

from app.file_io import ProjectFileIO


REQUIRED_HEADINGS = {
    "state": ["# Current State", "## Position", "## Current Situation"],
    "outline": ["Required Beats"],
    "arc_outline": ["Required Events"],
    "critic": ["# Critic Report", "## Verdict"],
    "snapshot": ["# Frozen Run Input Snapshot", "## Scene"],
}


class Validator:
    """轻量文件校验。"""

    def __init__(self, file_io: ProjectFileIO):
        self.file_io = file_io

    def require_non_empty(self, path: str | Path) -> None:
        content = self.file_io.read_text(path).strip()
        if not content:
            raise ValueError(f"文件为空：{path}")

    def require_contains(self, path: str | Path, headings: list[str]) -> None:
        content = self.file_io.read_text(path)
        missing = [heading for heading in headings if heading not in content]
        if missing:
            raise ValueError(f"文件 {path} 缺少必要标题：{', '.join(missing)}")

    def validate_output(self, agent_name: str, output_path: str) -> None:
        if agent_name in {"archivist", "memory_archivist"}:
            return
        self.require_non_empty(output_path)
        if agent_name in {"statekeeper", "state_manifest_keeper", "state_initializer"}:
            self.require_contains(output_path, REQUIRED_HEADINGS["state"])
        elif agent_name == "run_snapshotter":
            self.require_contains(output_path, REQUIRED_HEADINGS["snapshot"])
        elif agent_name.endswith("_guard"):
            self.require_contains(output_path, REQUIRED_HEADINGS["critic"])
        elif "current_arc" in output_path:
            self.require_contains(output_path, REQUIRED_HEADINGS["arc_outline"])
        elif "outline" in output_path or "master_outline" in output_path:
            self.require_contains(output_path, REQUIRED_HEADINGS["outline"])
