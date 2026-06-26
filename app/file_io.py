from __future__ import annotations

from pathlib import Path


class ProjectFileIO:
    """统一管理项目内文本读写，避免写出项目根目录。"""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def resolve(self, path: Path | str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"路径越界，拒绝访问：{path}")
        return resolved

    def read_text(self, path: Path | str) -> str:
        resolved = self.resolve(path)
        if not resolved.exists():
            raise FileNotFoundError(f"文件不存在：{resolved}")
        if not resolved.is_file():
            raise IsADirectoryError(f"不是文件：{resolved}")
        return resolved.read_text(encoding="utf-8")

    def write_text(self, path: Path | str, content: str) -> Path:
        resolved = self.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8", newline="\n")
        return resolved

    def append_text(self, path: Path | str, content: str) -> Path:
        resolved = self.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("a", encoding="utf-8", newline="\n") as file:
            file.write(content)
        return resolved

    def exists(self, path: Path | str) -> bool:
        return self.resolve(path).exists()

    def ensure_dir(self, path: Path | str) -> Path:
        resolved = self.resolve(path)
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
