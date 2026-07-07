"""Tests for AtomicTurn — all-or-nothing Turn commit coordinator."""

from __future__ import annotations

import git
import pytest

from app.data.project_repo import ProjectRepo
from app.runtime.transaction import AtomicTurn


@pytest.fixture
def repo_with_initial_commit(tmp_path):
    """Create a ProjectRepo with an initial commit so HEAD is non-null."""
    repo = ProjectRepo(tmp_path)
    repo.init()
    # Write a first file so we have an initial commit to snapshot.
    (tmp_path / "initial.md").write_text("project seed", encoding="utf-8")
    repo.commit_turn("seed", "Initial project state")
    return repo


# ── happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_turn_commits_all_writes(repo_with_initial_commit):
    """When no exception occurs, every write lands as one atomic commit."""
    repo = repo_with_initial_commit
    root = repo.project_root

    async with AtomicTurn(repo, "turn-001", "Write two resources"):
        (root / "a.md").write_text("resource A", encoding="utf-8")
        (root / "b.md").write_text("resource B", encoding="utf-8")

    # Exactly one new commit.
    history = repo.list_history()
    assert history[0].message == "Turn turn-001: Write two resources"

    # Both files are committed and present.
    assert (root / "a.md").read_text(encoding="utf-8") == "resource A"
    assert (root / "b.md").read_text(encoding="utf-8") == "resource B"
    assert (root / "initial.md").read_text(encoding="utf-8") == "project seed"


@pytest.mark.asyncio
async def test_atomic_turn_single_commit_contains_both_files(repo_with_initial_commit):
    """Verify the single commit includes both files (inspection via git)."""
    repo = repo_with_initial_commit
    root = repo.project_root

    async with AtomicTurn(repo, "turn-002", "Two files in one commit"):
        (root / "x.txt").write_text("file x", encoding="utf-8")
        (root / "y.txt").write_text("file y", encoding="utf-8")

    history = repo.list_history(max_count=2)
    assert len(history) == 2  # seed + this one
    assert history[0].message == "Turn turn-002: Two files in one commit"

    # Verify both files exist in the commit tree (not just working tree).
    g = git.Repo(str(root))
    commit = g.commit(history[0].sha)
    tree = commit.tree
    assert "x.txt" in tree  # raises KeyError on failure with helpful trace
    assert "y.txt" in tree


# ── exception / rollback ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_turn_rolls_back_all_writes_on_exception(repo_with_initial_commit):
    """When an exception escapes the ``async with`` block, no write is committed."""
    repo = repo_with_initial_commit
    root = repo.project_root
    history_before = repo.list_history()
    sha_before = history_before[0].sha

    with pytest.raises(ValueError, match="mid-turn failure"):
        async with AtomicTurn(repo, "turn-bad", "This should not commit"):
            (root / "bad_a.md").write_text("should not exist", encoding="utf-8")
            raise ValueError("mid-turn failure")

    # No new commit.
    history_after = repo.list_history()
    assert history_after == history_before
    assert history_after[0].sha == sha_before

    # Files created mid-turn are gone.
    assert not (root / "bad_a.md").exists()
    # Original file untouched.
    assert (root / "initial.md").read_text(encoding="utf-8") == "project seed"


@pytest.mark.asyncio
async def test_atomic_turn_rolls_back_partial_writes(repo_with_initial_commit):
    """Writing only one file before an exception still causes a full rollback."""
    repo = repo_with_initial_commit
    root = repo.project_root
    history_before = repo.list_history()
    sha_before = history_before[0].sha

    with pytest.raises(RuntimeError, match="partial failure"):
        async with AtomicTurn(repo, "turn-partial", "Partial writes"):
            (root / "only_a.md").write_text("only this one was written", encoding="utf-8")
            raise RuntimeError("partial failure")

    # No new commit.
    history_after = repo.list_history()
    assert history_after == history_before
    assert history_after[0].sha == sha_before

    # The partial file is not present.
    assert not (root / "only_a.md").exists()


# ── edge — no pre-existing HEAD ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_turn_no_initial_commit(tmp_path):
    """AtomicTurn works even when there are ZERO commits yet."""
    repo = ProjectRepo(tmp_path)
    repo.init()  # git init, nothing committed
    root = repo.project_root

    async with AtomicTurn(repo, "turn-first", "First ever commit"):
        (root / "first_resource.md").write_text("first content", encoding="utf-8")

    history = repo.list_history()
    assert len(history) == 1
    assert history[0].message == "Turn turn-first: First ever commit"
    assert (root / "first_resource.md").read_text(encoding="utf-8") == "first content"


@pytest.mark.asyncio
async def test_atomic_turn_no_initial_commit_rollback(tmp_path):
    """If no commit exists yet and an exception happens, the turn dir is clean."""
    repo = ProjectRepo(tmp_path)
    repo.init()  # git init, nothing committed
    root = repo.project_root

    with pytest.raises(ValueError):
        async with AtomicTurn(repo, "turn-noop", "Should not commit"):
            (root / "should_not_exist.md").write_text("gone", encoding="utf-8")
            raise ValueError("oops")

    # No commit was created.
    assert repo.current_commit() is None
    # Untracked file created during the turn is cleaned up.
    assert not (root / "should_not_exist.md").exists()
