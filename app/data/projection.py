"""Working-tree projection of commit history (current state = history applied).

Per refactor_guide:310-312 — the working tree IS the projection of
commit history applied to the initial state.  Every checkout is a
projection, and the current working tree is the latest projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .project_repo import ProjectRepo


@dataclass(frozen=True)
class Projection:
    """The current working tree, viewed as a projection of commit history.

    Attributes:
        current_branch:   Name of the currently checked-out branch.
        current_commit:   SHA of the current ``HEAD`` (``None`` if no
                          commits exist yet).
        resource_files:   Map of relative file paths → current content
                          for every tracked (resource) file in the
                          working tree.
    """

    current_branch: str
    current_commit: str | None
    resource_files: dict[str, str] = field(default_factory=dict)


_RESOURCE_DIRS: tuple[str, ...] = (
    "resources/outline",
    "resources/short_goal",
    "resources/state",
    "resources/variables",
    "resources/worldbook",
    "resources/facts",
    "resources/character_memory",
    "resources/notes",
)


def current_projection(project_root: Path) -> Projection:
    """Return the current working-tree projection of commit history.

    Scans the standard resource directories and reads every file found
    there (recursively), building a ``Projection`` that captures the
    full working-tree content.
    """
    repo = ProjectRepo(project_root)
    head_sha = repo.current_commit()

    # Determine the current branch name
    try:
        import git as _git

        g = _git.Repo(str(project_root))
        branch = g.active_branch.name
    except (ValueError, _git.exc.InvalidGitRepositoryError, TypeError):
        branch = "main"

    # Collect resource files from the working tree
    files: dict[str, str] = {}
    for rel_dir in _RESOURCE_DIRS:
        base = project_root / rel_dir
        if not base.is_dir():
            continue
        _walk_and_read(base, rel_dir, files)

    return Projection(
        current_branch=branch,
        current_commit=head_sha,
        resource_files=files,
    )


def _walk_and_read(
    base: Path, prefix: str, out: dict[str, str]
) -> None:
    """Recursively read every file under *base*, indexing by *prefix*."""
    for entry in sorted(base.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            _walk_and_read(entry, f"{prefix}/{entry.name}", out)
        elif entry.is_file():
            rel = f"{prefix}/{entry.name}"
            try:
                content = entry.read_text(encoding="utf-8")
                out[rel] = content
            except (UnicodeDecodeError, OSError):
                continue
