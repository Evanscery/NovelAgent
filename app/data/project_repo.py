"""Per-workspace git init/commit/branch/checkout; main repo .gitignore aware."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import git

_TURN_PREFIX_RE = re.compile(r"^Turn\s+(\S+):")


@dataclass(frozen=True)
class CommitInfo:
    """Metadata about a single Turn commit."""

    sha: str
    turn_id: str
    message: str
    timestamp: datetime
    branch: str


class ProjectRepo:
    """Wraps per-workspace git operations using GitPython.

    Operates on a *project root* directory that has (or will have) its own
    ``.git`` — independent from the main repository.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()

    @property
    def project_root(self) -> Path:
        """Return the resolved project root path."""
        return self._project_root

    # --- init ----------------------------------------------------------------

    def init(self) -> None:
        """Initialise a git repository at ``project_root``.

        - ``git init`` if ``.git`` does not already exist.
        - Set ``user.email`` / ``user.name`` if they are not already
          configured (required for commits to succeed).
        """
        dot_git = self._project_root / ".git"
        if not dot_git.exists():
            repo = git.Repo.init(str(self._project_root))
        else:
            repo = git.Repo(str(self._project_root))

        with repo.config_writer() as cfg:
            # Ensure git user config is set; commits require it.
            if not cfg.has_section("user"):
                cfg.add_section("user")
            if not cfg.has_option("user", "email"):
                cfg.set_value("user", "email", "novel-agent@local")
            if not cfg.has_option("user", "name"):
                cfg.set_value("user", "name", "NovelAgent")

        # Rename the default branch to "main" for consistency.
        try:
            cur = repo.git.symbolic_ref("HEAD", short=True)
            if cur == "master":
                repo.git.branch("-m", "master", "main")
        except git.GitCommandError:
            pass

    # --- commit --------------------------------------------------------------

    def commit_turn(self, turn_id: str, message: str) -> str:
        """Stage all resource changes (``git add -A``) and commit.

        The commit message is formatted as::

            Turn <turn_id>: <message>

        Returns the commit SHA.
        """
        repo = git.Repo(str(self._project_root))
        repo.git.add("-A")
        full_message = f"Turn {turn_id}: {message}"
        commit = repo.index.commit(full_message)
        return commit.hexsha

    # --- branches ------------------------------------------------------------

    def create_branch(self, branch_name: str, from_turn: str | None = None) -> None:
        """Create a new git branch.

        Args:
            branch_name: Name of the new branch.
            from_turn:   Turn ID to branch *from* (SHA or turn-id).
                         ``None`` means current ``HEAD``.
        """
        repo = git.Repo(str(self._project_root))
        if from_turn is not None:
            rev = self.resolve_turn(from_turn)
        else:
            rev = "HEAD"
        repo.create_head(branch_name, commit=rev)

    def list_branches(self) -> list[str]:
        """Return all branch names (local branches)."""
        repo = git.Repo(str(self._project_root))
        return sorted(b.name for b in repo.branches)

    def checkout(self, ref: str) -> None:
        """Checkout a branch or commit (detached HEAD if a commit SHA)."""
        repo = git.Repo(str(self._project_root))
        repo.git.checkout(ref)

    # --- history & state -----------------------------------------------------

    def list_history(self, max_count: int = 50) -> list[CommitInfo]:
        """Return commits newest-first.

        Each commit's ``branch`` field lists the first local branch that
        contains it; if none is found it falls back to ``"detached"``.
        """
        repo = git.Repo(str(self._project_root))
        out: list[CommitInfo] = []
        for commit in repo.iter_commits(rev="HEAD", max_count=max_count):
            out.append(self._build_commit_info(repo, commit))
        return out

    def list_history_for_path(
        self, path: str, max_count: int = 50
    ) -> list[CommitInfo]:
        """Return commits newest-first that touched files under *path*.

        Uses ``git log -- <path>`` so only commits whose diff includes
        at least one file under the given relative path are returned.
        """
        repo = git.Repo(str(self._project_root))
        out: list[CommitInfo] = []
        for commit in repo.iter_commits(
            rev="HEAD", max_count=max_count, paths=path
        ):
            out.append(self._build_commit_info(repo, commit))
        return out

    def current_commit(self) -> str | None:
        """Return the current ``HEAD`` SHA, or ``None`` if no commits exist."""
        try:
            repo = git.Repo(str(self._project_root))
            return repo.head.commit.hexsha
        except (ValueError, git.exc.InvalidGitRepositoryError):
            return None

    def restore_to(self, commit_sha: str | None) -> None:
        """Restore the working tree to the state at *commit_sha*.

        Used by :class:`app.runtime.transaction.AtomicTurn` to discard
        partial writes when a Turn fails. Per refactor_guide:334-336 a
        failed Turn must leave NO partial state behind.

        Args:
            commit_sha: The pre-Turn HEAD SHA to restore to. ``None``
                means no commit existed before the Turn — every tracked
                file is removed and the index is cleared, returning the
                working tree to an empty (pre-first-commit) state.

        Restores via ``git checkout <sha> -- .`` + ``git clean -fd`` so
        that:
        - files modified mid-Turn revert to their pre-Turn content;
        - files newly created mid-Turn (untracked) are removed by
          ``git clean -fd``;
        - the ``HEAD`` ref itself is NOT moved (this is a working-tree
          restore, not a branch rollback — atomicity only).
        """
        repo = git.Repo(str(self._project_root))
        if commit_sha is None:
            # No prior commit: remove every tracked file & clear the index
            # so the working tree is empty again.
            tracked = repo.git.ls_files().splitlines()
            if tracked:
                repo.git.rm("-r", "--cached", "--quiet", "--", *tracked)
            for rel in tracked:
                abs_path = self._project_root / rel
                if abs_path.exists():
                    abs_path.unlink()
            # Sweep any untracked files/dirs left from the failed Turn.
            repo.git.clean("-fd")
            return
        # Re-checkout every path at the target commit, then drop untracked.
        repo.git.checkout(commit_sha, "--", ".")
        repo.git.clean("-fd")

    # --- internal helpers ----------------------------------------------------

    def resolve_turn(self, turn_id_or_sha: str) -> str:
        """Convert a turn-id or short-SHA to a full commit SHA.

        If *turn_id_or_sha* already looks like a hex digest (>=6 hex
        chars) it is resolved directly via ``repo.rev_parse``.  Otherwise
        every commit reachable from ``HEAD`` is searched for a matching
        ``Turn <turn_id>:`` prefix.
        """
        repo = git.Repo(str(self._project_root))

        # Try direct rev-parse first (catches short/long SHAs)
        if len(turn_id_or_sha) >= 6 and all(
            c in "0123456789abcdef" for c in turn_id_or_sha
        ):
            try:
                return repo.rev_parse(turn_id_or_sha).hexsha
            except (git.BadName, ValueError):
                pass

        # Search commit messages for Turn <turn_id>:
        for commit in repo.iter_commits(rev="HEAD"):
            raw_msg = commit.message or b""
            msg_str = raw_msg if isinstance(raw_msg, str) else raw_msg.decode("utf-8", errors="replace")
            m = _TURN_PREFIX_RE.match(msg_str)
            if m and m.group(1) == turn_id_or_sha:
                return commit.hexsha

        raise LookupError(f"Turn not found: {turn_id_or_sha}")

    @staticmethod
    def _build_commit_info(repo: git.Repo, commit: git.objects.Commit) -> CommitInfo:
        """Build a :class:`CommitInfo` from a git Commit object."""
        raw_msg = commit.message or b""
        msg: str = raw_msg if isinstance(raw_msg, str) else raw_msg.decode("utf-8", errors="replace")
        msg = msg.strip()
        m = _TURN_PREFIX_RE.match(msg)
        turn_id = m.group(1) if m else ""

        # Determine the branch this commit belongs to.
        branch = _detect_branch_for_commit(repo, commit.hexsha)

        return CommitInfo(
            sha=commit.hexsha,
            turn_id=turn_id,
            message=msg,
            timestamp=datetime.fromtimestamp(commit.committed_date),
            branch=branch,
        )


def _detect_branch_for_commit(repo: git.Repo, sha: str) -> str:
    """Return the first local branch that contains *sha*, or ``"detached"``."""
    try:
        raw = repo.git.branch("--contains", sha, format="%(refname:short)")
    except git.GitCommandError:
        return "detached"
    candidates = [b.strip() for b in raw.splitlines() if b.strip()]
    return candidates[0] if candidates else "detached"
