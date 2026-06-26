from __future__ import annotations

from pathlib import Path

LEGACY_PROJECT_ROOT = "novel_project/"
PROJECT_ANCHORS = (
    "PROJECT.md",
    "archive",
    "evaluation",
    "lore",
    "memory",
    "modules",
    "novels",
    "outline",
    "presets",
    "prompts",
    "state",
    "work",
)


def as_posix(path: str | Path) -> str:
    return Path(path).as_posix() if isinstance(path, Path) else str(path).replace("\\", "/")


def infer_project_prefix(path: str | Path) -> str | None:
    normalized = as_posix(path).strip("/")
    for anchor in PROJECT_ANCHORS:
        needle = f"/{anchor}/"
        if needle in normalized:
            return normalized.split(needle, 1)[0]
        if normalized.endswith(f"/{anchor}"):
            return normalized[: -len(f"/{anchor}")]
    if normalized.endswith("/PROJECT.md"):
        return normalized[: -len("/PROJECT.md")]
    return None


def normalize_project_path(path: str, current_project_prefix: str | None) -> str:
    if not current_project_prefix:
        return path
    if path.startswith(LEGACY_PROJECT_ROOT):
        return path.replace(LEGACY_PROJECT_ROOT, current_project_prefix.rstrip("/") + "/", 1)
    return path


def rewrite_legacy_project_paths(text: str, source_path: str | Path) -> str:
    current_project_prefix = infer_project_prefix(source_path)
    if not current_project_prefix or current_project_prefix == LEGACY_PROJECT_ROOT.rstrip("/"):
        return text
    return text.replace(LEGACY_PROJECT_ROOT, current_project_prefix.rstrip("/") + "/")
