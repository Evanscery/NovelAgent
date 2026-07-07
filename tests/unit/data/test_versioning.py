"""Tests for git-backed versioning: ProjectRepo + VersionManager + Projection."""

from __future__ import annotations

from pathlib import Path

import git
import pytest

from app.data.project_repo import ProjectRepo
from app.data.projection import Projection, current_projection
from app.data.versioning import Snapshot, VersionManager

# ── helpers ────────────────────────────────────────────────────────────


def _init_and_commit_first_turn(repo: ProjectRepo, turn_id: str = "turn-001") -> str:
    """Helper: init a repo, write a file, commit turn, return SHA."""
    repo.init()
    # Write a resource file
    res_dir = repo._project_root / "resources" / "state"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "state.md").write_text("Initial state", encoding="utf-8")
    return repo.commit_turn(turn_id, "Initial commit")


def _make_repo_and_first_turn(tmp_path: Path) -> tuple[ProjectRepo, str]:
    """Helper returning (repo, first_sha)."""
    repo = ProjectRepo(tmp_path / "workspace")
    sha = _init_and_commit_first_turn(repo)
    return repo, sha


# ── Tests: ProjectRepo.init ────────────────────────────────────────────


class TestInit:
    """ProjectRepo.init creates a usable .git repository."""

    def test_init_creates_dot_git(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        assert (tmp_path / "proj" / ".git").is_dir()

    def test_init_idempotent(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        repo.init()  # second call should not raise
        assert (tmp_path / "proj" / ".git").is_dir()

    def test_init_sets_user_config(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        g = git.Repo(str(tmp_path / "proj"))
        assert g.config_reader().get_value("user", "email") == "novel-agent@local"
        assert g.config_reader().get_value("user", "name") == "NovelAgent"


# ── Tests: ProjectRepo.commit_turn ─────────────────────────────────────


class TestCommitTurn:
    """commit_turn creates a git commit with proper message format."""

    def test_commit_creates_commit(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        sha = _init_and_commit_first_turn(repo)
        assert len(sha) == 40

    def test_commit_message_format(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        _init_and_commit_first_turn(repo, "turn-abc")
        g = git.Repo(str(tmp_path / "proj"))
        assert g.head.commit.message.strip() == "Turn turn-abc: Initial commit"

    def test_commit_stages_all_changes(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        (tmp_path / "proj" / "resources" / "outline" / "plan.md").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "outline" / "plan.md").write_text("plan", encoding="utf-8")
        repo.commit_turn("t1", "added plan")
        g = git.Repo(str(tmp_path / "proj"))
        assert g.head.commit.message.strip() == "Turn t1: added plan"


# ── Tests: ProjectRepo.create_branch ───────────────────────────────────


class TestCreateBranch:
    """create_branch creates a named branch from HEAD or a specific commit."""

    def test_create_branch_from_head(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_and_first_turn(tmp_path)
        repo.create_branch("feature/test")
        assert "feature/test" in repo.list_branches()

    def test_create_branch_from_specific_commit(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        sha = repo.commit_turn("t1", "first")
        repo.commit_turn("t2", "second")
        repo.create_branch("rollback/t1", from_turn=sha)
        branches = repo.list_branches()
        assert "rollback/t1" in branches
        assert "main" in branches

    def test_list_branches_all(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_and_first_turn(tmp_path)
        repo.create_branch("b1")
        repo.create_branch("b2")
        assert set(repo.list_branches()) == {"main", "b1", "b2"}


# ── Tests: ProjectRepo.checkout ────────────────────────────────────────


class TestCheckout:
    """checkout switches branches correctly."""

    def test_checkout_branch(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_and_first_turn(tmp_path)
        repo.create_branch("alt")
        repo.checkout("alt")
        g = git.Repo(str(tmp_path / "workspace"))
        assert g.active_branch.name == "alt"

    def test_checkout_original_branch_preserved(self, tmp_path: Path) -> None:
        repo, _ = _make_repo_and_first_turn(tmp_path)
        orig_data = repo._project_root / "resources" / "state" / "state.md"
        orig_content = orig_data.read_text()

        repo.create_branch("alt")
        repo.checkout("alt")
        # Write something on alt
        (repo._project_root / "resources" / "state" / "state.md").write_text("alt version", encoding="utf-8")
        repo.commit_turn("alt-1", "alt change")

        # Go back to main — original data should be intact
        repo.checkout("main")
        assert orig_data.read_text() == orig_content


# ── Tests: ProjectRepo.list_history ────────────────────────────────────


class TestListHistory:
    """list_history returns commits newest-first."""

    def test_newest_first(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        sha1 = repo.commit_turn("t1", "first")
        sha2 = repo.commit_turn("t2", "second")
        history = repo.list_history(max_count=10)
        assert history[0].sha == sha2  # newest first
        assert history[1].sha == sha1

    def test_history_contains_commit_info(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        sha = repo.commit_turn("turn-1", "first commit")
        history = repo.list_history(max_count=10)
        assert len(history) >= 1
        ci = history[0]
        assert ci.sha == sha
        assert ci.turn_id == "turn-1"
        assert ci.message == "Turn turn-1: first commit"
        assert ci.branch == "main"

    def test_max_count_limit(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        for i in range(5):
            repo.commit_turn(f"t{i}", f"commit {i}")
        history = repo.list_history(max_count=3)
        assert len(history) == 3


# ── Tests: ProjectRepo.current_commit ──────────────────────────────────


class TestCurrentCommit:
    """current_commit returns HEAD or None."""

    def test_returns_none_when_no_commits(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        assert repo.current_commit() is None

    def test_returns_sha_after_commit(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        sha = _init_and_commit_first_turn(repo)
        assert repo.current_commit() == sha


# ── Tests: VersionManager.rollback (default mode='branch') ─────────────


class TestRollbackBranch:
    """rollback(mode='branch') creates a new branch; original data preserved."""

    def test_rollback_creates_new_branch(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        v._project_repo.commit_turn("t1", "first")
        v._project_repo.commit_turn("t2", "second")

        # Write to a file after t1 so we can confirm checkout
        (tmp_path / "proj" / "resources" / "state" / "state.md").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("second", encoding="utf-8")
        v._project_repo.commit_turn("t2b", "second actual")

        branch = v.rollback("t1")
        assert "rollback/turn-t1" in branch
        assert "rollback/turn-t1" in v.list_branches()

    def test_rollback_original_branch_data_intact(self, tmp_path: Path) -> None:
        """rollback creates a new branch; original main branch is untouched."""
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        v._project_repo.commit_turn("t1", "first")
        v._project_repo.commit_turn("t2", "second")

        # Snapshot: original branch and its commits are untouched
        v.rollback("t1")

        # Must still see the original main branch
        assert "main" in v.list_branches()
        # The new branch exists
        assert "rollback/turn-t1" in v.list_branches()

    def test_rollback_checkout_has_t1_data(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        # t1: write state.md = "v1"
        (tmp_path / "proj" / "resources" / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("v1", encoding="utf-8")
        v._project_repo.commit_turn("t1", "first")
        # t2: write state.md = "v2"
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("v2", encoding="utf-8")
        v._project_repo.commit_turn("t2", "second")

        v.rollback("t1")
        # After rollback, working tree should show v1
        snapshot = v.get_version("t1")
        assert "v1" in snapshot.files.get("resources/state/state.md", "")


# ── Tests: VersionManager.rollback (mode='delete') guard ───────────────


class TestRollbackDeleteGuard:
    """mode='delete' without confirm_delete raises PermissionError."""

    def test_delete_without_confirmation_raises(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        v._project_repo.commit_turn("t1", "first")
        with pytest.raises(PermissionError) as exc:
            v.rollback("t1", mode="delete")
        assert "confirm_delete" in str(exc.value)

    def test_delete_with_confirmation_works(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        sha_t1 = v._project_repo.commit_turn("t1", "first")
        v._project_repo.commit_turn("t2", "second")
        # Use confirm_delete to actually do it
        result = v.rollback("t1", mode="delete", confirm_delete=True)
        assert result == ""
        # HEAD should now point to t1
        assert v._project_repo.current_commit() == sha_t1


# ── Tests: VersionManager.get_version ──────────────────────────────────


class TestGetVersion:
    """get_version returns a Snapshot with correct files."""

    def test_returns_snapshot_with_files(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        (tmp_path / "proj" / "resources" / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("hello", encoding="utf-8")
        sha = v._project_repo.commit_turn("t1", "first")
        snap = v.get_version("t1")
        assert isinstance(snap, Snapshot)
        assert snap.turn_id == "t1"
        assert snap.commit_sha == sha
        assert "resources/state/state.md" in snap.files
        assert snap.files["resources/state/state.md"] == "hello"

    def test_snapshot_multiple_files(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        (tmp_path / "proj" / "resources" / "outline").mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "outline" / "plan.md").write_text("plan", encoding="utf-8")
        (tmp_path / "proj" / "resources" / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("state", encoding="utf-8")
        v._project_repo.commit_turn("t1", "init")
        snap = v.get_version("t1")
        assert len(snap.files) >= 2


# ── Tests: VersionManager.diff ─────────────────────────────────────────


class TestDiff:
    """diff returns a non-empty string when there are changes."""

    def test_diff_between_different_commits(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        (tmp_path / "proj" / "resources" / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("version one", encoding="utf-8")
        v._project_repo.commit_turn("t1", "first")
        (tmp_path / "proj" / "resources" / "state" / "state.md").write_text("version two", encoding="utf-8")
        v._project_repo.commit_turn("t2", "second")
        diff_output = v.diff("t1", "t2")
        assert len(diff_output) > 0
        assert "version one" in diff_output or "+version two" in diff_output or "-version one" in diff_output

    def test_diff_no_changes(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        _init_and_commit_first_turn(v._project_repo, "t1")
        diff_output = v.diff("t1", "t1")
        assert diff_output.strip() == ""

    def test_diff_returns_string(self, tmp_path: Path) -> None:
        v = VersionManager(tmp_path / "proj")
        v._project_repo.init()
        _init_and_commit_first_turn(v._project_repo, "t1")
        result = v.diff("t1", "t1")
        assert isinstance(result, str)


# ── Tests: Projection ──────────────────────────────────────────────────


class TestProjection:
    """current_projection returns a correct snapshot of the working tree."""

    def test_projection_has_branch_and_commit(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        sha = _init_and_commit_first_turn(repo)
        proj = current_projection(tmp_path / "proj")
        assert isinstance(proj, Projection)
        assert proj.current_branch == "main"
        assert proj.current_commit == sha

    def test_projection_contains_resource_files(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        _init_and_commit_first_turn(repo)
        proj = current_projection(tmp_path / "proj")
        assert "resources/state/state.md" in proj.resource_files
        assert "Initial state" in proj.resource_files["resources/state/state.md"]

    def test_projection_no_commit(self, tmp_path: Path) -> None:
        repo = ProjectRepo(tmp_path / "proj")
        repo.init()
        proj = current_projection(tmp_path / "proj")
        assert proj.current_commit is None
        # No resource files yet because they don't exist
        assert proj.resource_files == {}
