from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML。请先运行：pip install -e .") from exc

from app.file_io import ProjectFileIO
from app.project_paths import rewrite_legacy_project_paths


@dataclass(frozen=True)
class PromptModule:
    path: str
    title: str
    content: str


class PromptModuleLoader:
    """加载 preset 与 prompt 模块。"""

    def __init__(self, file_io: ProjectFileIO):
        self.file_io = file_io

    def load_for_agent(self, agent_name: str, preset_path: str | None, extra_modules: list[str]) -> list[PromptModule]:
        module_paths: list[str] = []
        if preset_path:
            preset = self._load_yaml(preset_path)
            modules = preset.get("modules", {})
            module_paths.extend(modules.get("global", []) or [])
            module_paths.extend(modules.get("style", []) or [])
            agent_modules = (preset.get("agents", {}).get(agent_name, {}) or {}).get("modules", [])
            module_paths.extend(agent_modules or [])
        module_paths.extend(extra_modules or [])
        return [self._load_module(path) for path in self._dedupe(module_paths)]

    def _load_yaml(self, path: str) -> dict[str, Any]:
        text = rewrite_legacy_project_paths(self.file_io.read_text(path), path)
        return yaml.safe_load(text) or {}

    def _load_module(self, path: str) -> PromptModule:
        text = self.file_io.read_text(path)
        title = self._module_title(path, text)
        body = self._strip_frontmatter(text).strip()
        return PromptModule(path=path, title=title, content=body)

    def _module_title(self, path: str, text: str) -> str:
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                header = text[3:end]
                for line in header.splitlines():
                    if line.strip().startswith("id:"):
                        return line.split(":", 1)[1].strip()
        return Path(path).stem

    def _strip_frontmatter(self, text: str) -> str:
        if not text.startswith("---"):
            return text
        end = text.find("---", 3)
        if end == -1:
            return text
        return text[end + 3 :]

    def _dedupe(self, paths: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for path in paths:
            if path not in seen:
                seen.add(path)
                result.append(path)
        return result
