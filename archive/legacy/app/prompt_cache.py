from __future__ import annotations

import hashlib
from pathlib import Path

from app.file_io import ProjectFileIO


class PromptCache:
    def __init__(self, file_io: ProjectFileIO, cache_dir: str, enabled: bool = True):
        self.file_io = file_io
        self.cache_dir = cache_dir
        self.enabled = enabled

    def make_key(self, agent_name: str, scene_id: str, context: str) -> str:
        digest = hashlib.sha256(f"{agent_name}\n{scene_id}\n{context}".encode("utf-8")).hexdigest()
        return digest

    def load(self, key: str) -> str | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def store(self, key: str, value: str) -> None:
        if not self.enabled:
            return
        self.file_io.write_text(path := str(self._path(key)), value)

    def _path(self, key: str) -> Path:
        return Path(self.file_io.resolve(str(Path(self.cache_dir) / f"{key}.md")))
