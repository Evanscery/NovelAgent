"""Tests for app.project_paths — id generation, resolution, listing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.project_paths import (
    ProjectPathError,
    generate_project_id,
    list_project_ids,
    resolve_project_path,
)

# ── generate_project_id ──────────────────────────────────────────────────


class TestGenerateProjectId:
    def test_format(self) -> None:
        pid = generate_project_id()
        assert pid.startswith("proj_")
        suffix = pid[len("proj_"):]
        assert len(suffix) == 8
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_unique(self) -> None:
        ids = {generate_project_id() for _ in range(1000)}
        assert len(ids) == 1000


# ── resolve_project_path ─────────────────────────────────────────────────


class TestResolveProjectPath:
    def test_resolves_inside_workspaces(self, tmp_path: Path) -> None:
        pid = generate_project_id()
        p = resolve_project_path(tmp_path, pid)
        assert p == (tmp_path / "workspaces" / pid).resolve()
        assert p.parent.name == "workspaces"

    def test_empty_id_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ProjectPathError):
            resolve_project_path(tmp_path, "")

    def test_traversal_dotdot_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ProjectPathError):
            resolve_project_path(tmp_path, "..")

    def test_traversal_semicolon_rejected(self, tmp_path: Path) -> None:
        # Path separators are not in the allowed alphabet.
        with pytest.raises(ProjectPathError):
            resolve_project_path(tmp_path, "proj_1234/../../etc")

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ProjectPathError):
            resolve_project_path(tmp_path, "/etc/passwd")

    def test_special_chars_rejected(self, tmp_path: Path) -> None:
        for bad in ("proj-1234", "proj.1234", "proj 1234", "proj!"):
            with pytest.raises(ProjectPathError):
                resolve_project_path(tmp_path, bad)

    def test_alphanumeric_underscore_accepted(self, tmp_path: Path) -> None:
        p = resolve_project_path(tmp_path, "proj_ABC123")
        assert p.name == "proj_ABC123"


# ── list_project_ids ─────────────────────────────────────────────────────


class TestListProjectIds:
    def test_empty_when_no_workspaces(self, tmp_path: Path) -> None:
        assert list_project_ids(tmp_path) == []

    def test_lists_only_dirs_with_config(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspaces"
        ws.mkdir()
        # Real project
        (ws / "proj_aaaa1111").mkdir()
        (ws / "proj_aaaa1111" / "config.yaml").write_text(
            "display_name: A\nmode: novel\n", encoding="utf-8"
        )
        # Bare dir without config.yaml — should be skipped
        (ws / "proj_bbbb2222").mkdir()
        # A loose file — should be skipped
        (ws / "loose.txt").write_text("ignore", encoding="utf-8")

        ids = list_project_ids(tmp_path)
        assert ids == ["proj_aaaa1111"]

    def test_sorted_lexicographically(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspaces"
        ws.mkdir()
        for pid in ("proj_zzzz9999", "proj_aaaa1111", "proj_mmmm5555"):
            d = ws / pid
            d.mkdir()
            (d / "config.yaml").write_text(
                f"display_name: {pid}\nmode: novel\n", encoding="utf-8"
            )
        assert list_project_ids(tmp_path) == [
            "proj_aaaa1111",
            "proj_mmmm5555",
            "proj_zzzz9999",
        ]
