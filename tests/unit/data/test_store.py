"""Tests for ResourceStore CRUD, read/write/search, index, and permission check."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data.resource_types import RESOURCE_TYPE_REGISTRY, State, Worldbook
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
        assert (resource.path / ".index").exists()

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
        assert ".index" not in all_content

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


# ── search ────────────────────────────────────────────────────────────


class TestSearch:
    """search returns hits matching query in headings/content."""

    def test_search_matches_content(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("worldbook", "wb1")
        store.write(resource, "magic.md", "## 魔法体系\n\n火球术是最常见的攻击魔法。")

        hits = store.search(resource, "魔法")
        assert len(hits) >= 1
        found = [h for h in hits if "魔法" in h.matching_text]
        assert len(found) >= 1

    def test_search_matches_headings(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o3")
        store.write(resource, "chapters.md", "# Chapter 1\n## Scene 1\n## Scene 2")

        hits = store.search(resource, "Scene")
        assert len(hits) >= 2

    def test_search_case_insensitive(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("state", "s2")
        store.write(resource, "summary.md", "The Hero arrived at the Village.")

        hits = store.search(resource, "village")
        assert len(hits) == 1
        assert "Village" in hits[0].matching_text

    def test_search_no_match(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("facts", "f1")
        store.write(resource, "facts.md", "Some known facts.")

        hits = store.search(resource, "zzz_nonexistent")
        assert hits == []

    def test_search_returns_searchhit_shape(self, tmp_path: Path) -> None:
        """Each hit is a SearchHit with the expected fields."""
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n2")
        store.write(resource, "note.md", "## Observation\n\nNoted observation here.")

        hits = store.search(resource, "Observation")
        assert len(hits) >= 1
        hit = hits[0]
        assert isinstance(hit.filename, str)
        assert isinstance(hit.line_number, int)
        assert isinstance(hit.matching_text, str)
        assert isinstance(hit.context, str)
        assert hit.filename == "note.md"
        assert "Observation" in hit.matching_text

    def test_search_skips_metadata_files(self, tmp_path: Path) -> None:
        """properties.md, manifest.json, .index are not searched."""
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o4")
        # The index file has the filename "note.md" in it — this tests .index
        # isn't searched.
        store.write(resource, "note.md", "real content")

        hits = store.search(resource, "properties")
        # "properties" could appear in .index only (the heading line in index
        # doesn't have the word "properties", but let's verify no hit from
        # metadata files)
        for hit in hits:
            assert hit.filename not in {"properties.md", "manifest.json", ".index"}


# ── permission_check ─────────────────────────────────────────────────


class TestPermissionCheck:
    """permission_check returns bool based on agent_permission hash."""

    def test_agent_can_read_state(self) -> None:
        store = ResourceStore(Path("/tmp"))
        agent_perm: dict[str, list[str]] = {"read": ["state", "memory"]}
        resource = State(
            id="s1",
            type="state",
            path=Path("/tmp/resources/state"),
            properties=State.default_properties(),
            manifest=type(
                "Manifest",
                (),
                {"type": "state", "properties_ref": "props.md"},
            )(),  # type: ignore[arg-type]
        )

        assert store.permission_check(agent_perm, resource) is True

    def test_agent_cannot_read_worldbook(self) -> None:
        store = ResourceStore(Path("/tmp"))
        agent_perm: dict[str, list[str]] = {"read": ["state", "memory"]}
        resource = Worldbook(
            id="wb1",
            type="worldbook",
            path=Path("/tmp/resources/worldbook"),
            properties=Worldbook.default_properties(),
            manifest=type(
                "Manifest",
                (),
                {"type": "worldbook", "properties_ref": "props.md"},
            )(),  # type: ignore[arg-type]
        )

        assert store.permission_check(agent_perm, resource) is False

    def test_agent_can_write_allowed_type(self) -> None:
        store = ResourceStore(Path("/tmp"))
        agent_perm: dict[str, list[str]] = {"write": ["short_goal"]}
        resource = State(
            id="sg1",
            type="short_goal",
            path=Path("/tmp/resources/short_goal"),
            properties=State.default_properties(),
            manifest=type(
                "Manifest",
                (),
                {"type": "short_goal", "properties_ref": "props.md"},
            )(),  # type: ignore[arg-type]
        )

        # 'write' permission to 'short_goal' should allow visibility
        assert store.permission_check(agent_perm, resource) is True

    def test_empty_permission_returns_false(self) -> None:
        store = ResourceStore(Path("/tmp"))
        agent_perm: dict[str, list[str]] = {}
        resource = State(
            id="s1",
            type="state",
            path=Path("/tmp/resources/state"),
            properties=State.default_properties(),
            manifest=type(
                "Manifest",
                (),
                {"type": "state", "properties_ref": "props.md"},
            )(),  # type: ignore[arg-type]
        )

        assert store.permission_check(agent_perm, resource) is False

    def test_no_side_effects(self) -> None:
        """permission_check does not mutate the input dict."""
        store = ResourceStore(Path("/tmp"))
        agent_perm: dict[str, list[str]] = {"read": ["state"]}
        resource = State(
            id="s1",
            type="state",
            path=Path("/tmp/resources/state"),
            properties=State.default_properties(),
            manifest=type(
                "Manifest",
                (),
                {"type": "state", "properties_ref": "props.md"},
            )(),  # type: ignore[arg-type]
        )

        before = str(agent_perm)
        store.permission_check(agent_perm, resource)
        assert str(agent_perm) == before


# ── list_resources ────────────────────────────────────────────────────


class TestListResources:
    """list_resources returns all created resources."""

    def test_empty_project(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.list_resources() == []

    def test_returns_created_resources(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        store.create_resource("outline", "o1")
        store.create_resource("state", "s1")
        store.create_resource("notes", "n1")

        resources = store.list_resources()
        types = {r.type for r in resources}
        assert types == {"outline", "state", "notes"}

    def test_skips_non_resource_dirs(self, tmp_path: Path) -> None:
        """Directories without manifest.json are skipped."""
        store = _make_store(tmp_path)
        store.create_resource("outline", "o1")
        # Create a non-resource directory
        (tmp_path / "resources" / "junk_dir").mkdir(parents=True, exist_ok=True)

        resources = store.list_resources()
        assert len(resources) == 1
        assert resources[0].type == "outline"


# ── Index maintenance ─────────────────────────────────────────────────


class TestIndex:
    """.index is updated after write and contains headings."""

    def test_index_created_on_create(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o1")
        index_content = (resource.path / ".index").read_text(encoding="utf-8")
        # Empty index on fresh create
        assert isinstance(index_content, str)

    def test_index_updated_after_write(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("outline", "o2")
        store.write(resource, "arc.md", "# Arc 1\n## Act 1\n\nContent here.")

        index_content = (resource.path / ".index").read_text(encoding="utf-8")
        assert "# arc.md" in index_content
        assert "# Arc 1" in index_content
        assert "## Act 1" in index_content

    def test_index_includes_multiple_files(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        resource = store.create_resource("notes", "n1")
        store.write(resource, "a.md", "# Heading A\nContent A")
        store.write(resource, "b.md", "# Heading B\nContent B")

        index_content = (resource.path / ".index").read_text(encoding="utf-8")
        assert "# a.md" in index_content
        assert "# b.md" in index_content
        assert "# Heading A" in index_content
        assert "# Heading B" in index_content
