"""Tests for ResourceStore CRUD, read/write, and file I/O helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data.resource_types import RESOURCE_TYPE_REGISTRY, State
from app.data.store import ResourceStore

# ── Helpers ───────────────────────────────────────────────────────────


def _make_store(tmp_path: Path) -> ResourceStore:
    return ResourceStore(tmp_path)


# ── create_resource ───────────────────────────────────────────────────


class TestCreateResource:
    """create_resource scaffolds dir + properties.md + manifest.json."""

    def test_scaffolds_directory_and_files(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "my-outline")

        assert resource.path.exists()
        assert (resource.path / "properties.md").exists()
        assert (resource.path / "manifest.json").exists()

    def test_returns_correct_type(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")

        assert isinstance(resource, State)
        assert resource.type == "state"

    def test_idempotent_create(self, tmp_path: Path) -> None:
        """Calling create_resource twice doesn't overwrite files."""
        store = _make_store(tmp_path)
        r1 = store.create_resource("notes", "n1")
        props_content_1 = (r1.path / "properties.md").read_text(encoding="utf-8")

        r2 = store.create_resource("notes", "n1")
        props_content_2 = (r2.path / "properties.md").read_text(encoding="utf-8")

        assert props_content_1 == props_content_2

    def test_all_registered_types_scaffold(self, tmp_path: Path) -> None:
        """Every type in RESOURCE_TYPE_REGISTRY scaffolds without error."""
        store = _make_store(tmp_path)
        for type_name in RESOURCE_TYPE_REGISTRY:
            resource = store.create_resource(type_name, f"{type_name}-001")
            assert resource.path.exists()
            assert (resource.path / "properties.md").exists()
            assert (resource.path / "manifest.json").exists()

    def test_unknown_type_raises_keyerror(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        with pytest.raises(KeyError, match="Unknown resource type"):
            store.create_resource("nonexistent_type", "bad")


# ── read / write ──────────────────────────────────────────────────────


class TestReadWrite:
    """write then read returns same content."""

    def test_write_then_read_specific_file(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o1")
        content = "# Chapter 1\n\nThis is the outline."

        store.write(resource, "chapter1.md", content)
        result = store.read(resource, "chapter1.md")

        assert result == content

    def test_read_all_files(self, tmp_path: Path) -> None:
        """read() without filename returns concatenation of all content files."""
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o2")

        store.write(resource, "a.md", "File A content")
        store.write(resource, "b.md", "File B content")

        all_content = store.read(resource)
        assert "File A content" in all_content
        assert "File B content" in all_content
        # Metadata files should not appear
        assert "properties.md" not in all_content
        assert "manifest.json" not in all_content

    def test_read_nonexistent_file_raises(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")

        with pytest.raises(FileNotFoundError):
            store.read(resource, "no_such_file.md")

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        """write() creates subdirectory structure if needed."""
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")

        store.write(resource, "sub/deep/file.md", "deep content")
        result = store.read(resource, "sub/deep/file.md")
        assert result == "deep content"


# ── list_files ────────────────────────────────────────────────────────


class TestListFiles:
    """list_files returns content file names, excluding metadata."""

    def test_list_files_returns_sorted_content_files(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o1")
        store.write(resource, "b.md", "b")
        store.write(resource, "a.md", "a")

        result = store.list_files(resource)
        assert result == ["a.md", "b.md"]

    def test_list_files_excludes_metadata(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")

        result = store.list_files(resource)
        assert "properties.md" not in result
        assert "manifest.json" not in result

    def test_list_files_empty_when_no_content(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")

        assert store.list_files(resource) == []


# ── glob_files ────────────────────────────────────────────────────────


class TestGlobFiles:
    """glob_files matches file names against an fnmatch pattern."""

    def test_glob_matches_pattern(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o1")
        store.write(resource, "chapter_01.md", "c1")
        store.write(resource, "chapter_02.md", "c2")
        store.write(resource, "notes.md", "notes")

        result = store.glob_files(resource, "chapter_*.md")
        assert "chapter_01.md" in result
        assert "chapter_02.md" in result
        assert "notes.md" not in result

    def test_glob_no_match_returns_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")
        store.write(resource, "only.md", "content")

        assert store.glob_files(resource, "nonexistent_*") == []


# ── grep_lines ────────────────────────────────────────────────────────


class TestGrepLines:
    """grep_lines returns (filename, lineno, text) tuples for regex matches."""

    def test_grep_matches_content(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("worldbook", "wb1")
        store.write(resource, "magic.md", "## 魔法体系\n\n火球术是最常见的攻击魔法。")

        hits = store.grep_lines(resource, "魔法")
        assert len(hits) >= 1
        assert all(isinstance(h, tuple) and len(h) == 3 for h in hits)
        assert any(h[0] == "magic.md" for h in hits)

    def test_grep_case_insensitive(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")
        store.write(resource, "summary.md", "The Hero arrived at the Village.")

        hits = store.grep_lines(resource, "(?i)village")
        assert len(hits) == 1
        assert "Village" in hits[0][2]

    def test_grep_no_match(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("facts", "f1")
        store.write(resource, "facts.md", "Some known facts.")

        assert store.grep_lines(resource, "zzz_nonexistent") == []

    def test_grep_specific_filename(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        store.write(resource, "a.md", "target line")
        store.write(resource, "b.md", "target line")

        hits = store.grep_lines(resource, "target", filename="a.md")
        assert len(hits) == 1
        assert all(h[0] == "a.md" for h in hits)

    def test_grep_skips_metadata_files(self, tmp_path: Path) -> None:
        """properties.md, manifest.json are not searched."""
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o1")
        store.write(resource, "note.md", "real content")

        hits = store.grep_lines(resource, "properties")
        for hit in hits:
            assert hit[0] not in {"properties.md", "manifest.json", ".index"}


# ── read_lines ────────────────────────────────────────────────────────


class TestReadLines:
    """read_lines returns a 1-based line range from a file."""

    def test_read_lines_returns_range(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")
        store.write(resource, "multi.md", "line1\nline2\nline3\nline4\nline5")

        result = store.read_lines(resource, "multi.md", 2, 4)
        assert result == "line2\nline3\nline4"

    def test_read_lines_single_line(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")
        store.write(resource, "multi.md", "line1\nline2\nline3")

        result = store.read_lines(resource, "multi.md", 2, 2)
        assert result == "line2"

    def test_read_lines_full_range(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s1")
        store.write(resource, "f.md", "a\nb\nc")

        result = store.read_lines(resource, "f.md", 1, 3)
        assert result == "a\nb\nc"




# -- filename path-traversal guard -------------------------------------


class TestFilenameTraversalGuard:
    """read/write/grep_lines/read_lines reject filenames escaping the resource dir."""

    TRAVERSAL_NAMES = [
        "../escape.md",
        "sub/../../escape.md",
        "/etc/passwd",
        "\windows\system32\drivers\etc\hosts",
        "C:/Windows/win.ini",
        "..",
        "   ",
    ]

    def test_write_rejects_traversal(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        for name in self.TRAVERSAL_NAMES:
            with pytest.raises(ValueError):
                store.write(resource, name, "x")

    def test_read_rejects_traversal(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        for name in self.TRAVERSAL_NAMES:
            with pytest.raises(ValueError):
                store.read(resource, name)

    def test_grep_rejects_traversal(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        with pytest.raises(ValueError):
            store.grep_lines(resource, "x", filename="../../config.yaml")

    def test_read_lines_rejects_traversal(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        with pytest.raises(ValueError):
            store.read_lines(resource, "../secret.md", 1, 2)

    def test_traversal_leaves_no_file_outside(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        with pytest.raises(ValueError):
            store.write(resource, "../escape.md", "leaked")
        assert not (resource.path.parent / "escape.md").exists()

    def test_nested_relative_path_still_allowed(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("worldbook", "w1")
        store.write(resource, "chapters/magic.md", "fireball")
        assert store.read(resource, "chapters/magic.md") == "fireball"
