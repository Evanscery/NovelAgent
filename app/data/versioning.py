"""Git-backed version operations: Turn rollback + per-resource history."""

from __future__ import annotations

from pathlib import Path

import git

from .project_repo import CommitInfo, ProjectRepo


class VersionManager:
    """High-level versioning operations backed by a :class:`ProjectRepo`.

    All methods operate on the workspace at *project_root*.
    """

    def __init__(self, project_root: Path) -> None:
        self._repo = ProjectRepo(project_root)

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(
        self,
        to_turn: str,
        mode: str = "branch",
        confirm_delete: bool = False,
    ) -> str:
        """Roll back to a previous turn.

        Args:
            to_turn: Turn ID or commit SHA to roll back to.
            mode:
                ``"branch"`` (default) — create a **new branch** from the
                target commit and check it out.  The original branch and
                all its data are preserved intact (per refactor_guide:314-316
                回滚=切换版本非删除=新Branch).

                ``"delete"`` —  **DESTRUCTIVE**: permanently discard all
                commits after the target on the current branch via
                ``git reset --hard``.  Requires ``confirm_delete=True``.

            confirm_delete:
                MUST be ``True`` when ``mode="delete"``.  Guards against
                accidental destructive operations.

        Returns:
            The branch name that was created (for mode ``"branch"``).
            For mode ``"delete"`` returns an empty string (the checkout
            stays on the same branch, but commits are discarded).

        Raises:
            PermissionError: If ``mode="delete"`` is called without
                ``confirm_delete=True``.
        """
        if mode == "delete":
            if not confirm_delete:
                raise PermissionError(
                    "Destructive rollback (mode='delete') requires "
                    "confirm_delete=True on this call. "
                    "Use mode='branch' (default) for safe rollback."
                )
            repo = git.Repo(str(self._repo.project_root))
            sha = self._repo.resolve_turn(to_turn)
            repo.git.reset("--hard", sha)
            return ""

        if mode != "branch":
            raise ValueError(
                f"Unsupported rollback mode: {mode!r}. Use 'branch' or 'delete'."
            )

        # Resolve the target commit SHA from turn_id
        sha = self._repo.resolve_turn(to_turn)

        # Build a deterministic branch name
        branch_name = f"rollback/turn-{to_turn}"

        # Create a branch from the target commit (if it doesn't already exist)
        branches = self._repo.list_branches()
        if branch_name not in branches:
            self._repo.create_branch(branch_name, from_turn=sha)

        # Check out the new branch
        self._repo.checkout(branch_name)
        return branch_name

    def list_history_for_resource(
        self, resource_type: str, max_count: int = 50
    ) -> list[CommitInfo]:
        """Return commits newest-first that touched ``resources/<resource_type>/``.

        The per-type editor exposes this as its version-history list (per
        refactor_guide:388-400 每类数据…历史版本查看).
        """
        rel = f"resources/{resource_type}"
        return self._repo.list_history_for_path(rel, max_count=max_count)
