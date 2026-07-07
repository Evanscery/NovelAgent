"""Tests for app.runtime.permission — parse, enforce, ScopedTools delegation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.data.resource_types import RESOURCE_TYPE_REGISTRY
from app.data.store import ResourceStore
from app.runtime.permission import (
    Permission,
    PermissionDenied,
    ScopedTools,
    enforce,
    inject_into_tools,
    parse_permission,
)

# ── parse_permission ──────────────────────────────────────────────────────────


class TestParsePermission:
    """parse_permission validates dict format and produces a frozen Permission."""

    def test_parses_well_formed_dict(self) -> None:
        raw: dict[str, object] = {
            "read": ["state", "character_memory"],
            "write": ["short_goal"],
        }
        perm = parse_permission(raw)
        assert isinstance(perm, Permission)
        assert perm.rules["read"] == ("state", "character_memory")
        assert perm.rules["write"] == ("short_goal",)

    def test_rules_are_tuples_not_lists(self) -> None:
        # Frozen dataclass → values must be immutable.
        perm = parse_permission({"read": ["state"]})
        assert isinstance(perm.rules["read"], tuple)

    def test_empty_dict_yields_empty_permission(self) -> None:
        perm = parse_permission({})
        assert perm.rules == {}

    def test_empty_vector_yields_empty_tuple(self) -> None:
        perm = parse_permission({"read": []})
        assert perm.rules == {"read": ()}

    def test_rejects_non_dict_input(self) -> None:
        with pytest.raises(TypeError, match="expected dict"):
            parse_permission([("read", ["state"])])  # type: ignore[arg-type]

    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValueError, match="unknown action"):
            parse_permission({"delete": ["state"]})

    def test_rejects_non_list_value(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            parse_permission({"read": "state"})  # type: ignore[dict-item]

    def test_rejects_non_string_entry(self) -> None:
        with pytest.raises(TypeError, match="must be a str"):
            parse_permission({"read": [123]})  # type: ignore[dict-item]

    def test_rejects_unknown_resource_type(self) -> None:
        with pytest.raises(ValueError, match="unknown resource_type"):
            parse_permission({"read": ["nonexistent_type"]})

    def test_all_registry_types_accepted(self) -> None:
        """Every type in RESOURCE_TYPE_REGISTRY parses cleanly."""
        all_types = list(RESOURCE_TYPE_REGISTRY)
        perm = parse_permission({"read": all_types, "write": all_types})
        assert set(perm.rules["read"]) == set(all_types)
        assert set(perm.rules["write"]) == set(all_types)

    def test_permission_is_frozen(self) -> None:
        perm = parse_permission({"read": ["state"]})
        with pytest.raises(FrozenInstanceError):
            perm.rules = {}  # type: ignore[misc]


# ── enforce (pure function) ───────────────────────────────────────────────────


class TestEnforcePure:
    """enforce(permission, action, resource_type) -> bool — no side effects."""

    def test_allowed_returns_true(self) -> None:
        perm = parse_permission({"read": ["state"]})
        assert enforce(perm, "read", "state") is True

    def test_denied_returns_false(self) -> None:
        perm = parse_permission({"read": ["state"]})
        assert enforce(perm, "read", "worldbook") is False

    def test_missing_action_returns_false(self) -> None:
        perm = parse_permission({"read": ["state"]})
        assert enforce(perm, "write", "state") is False

    def test_empty_permission_denies_everything(self) -> None:
        perm = parse_permission({})
        assert enforce(perm, "read", "state") is False
        assert enforce(perm, "write", "state") is False

    def test_write_does_not_imply_read(self) -> None:
        """Per guide:77-78 'read' and 'write' are independent vectors."""
        perm = parse_permission({"write": ["short_goal"]})
        assert enforce(perm, "write", "short_goal") is True
        assert enforce(perm, "read", "short_goal") is False

    def test_does_not_mutate_permission(self) -> None:
        perm = parse_permission({"read": ["state"]})
        before = dict(perm.rules)
        enforce(perm, "read", "worldbook")
        enforce(perm, "write", "state")
        assert perm.rules == before


# ── ScopedTools: read permission gating ───────────────────────────────────────


def _make_scoped(
    tmp_path: Path, raw_perm: dict[str, list[str]]
) -> ScopedTools:
    """Build a ScopedTools over a real ResourceStore rooted at tmp_path."""
    store = ResourceStore(tmp_path)
    perm = parse_permission(raw_perm)
    return inject_into_tools(store, perm)


class TestScopedReadPermission:
    """Agent with {'read': ['state']} can read State, CANNOT read Worldbook."""

    def test_can_read_allowed_resource(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"read": ["state"]})
        # Write a file first via a wider-permission scope, then read via the
        # narrow one.
        wide = _make_scoped(
            tmp_path, {"read": ["state"], "write": ["state"]}
        )
        wide.write("state", "summary.md", "# Current state\nThe hero is at the inn.")
        result = tools.read("state", "summary.md")
        assert "The hero is at the inn" in result

    def test_cannot_read_disallowed_resource(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"read": ["state"]})
        # Seed a worldbook file with a wider scope so the resource exists.
        wide = _make_scoped(
            tmp_path, {"read": ["worldbook"], "write": ["worldbook"]}
        )
        wide.write("worldbook", "lore.md", "secret lore")
        with pytest.raises(PermissionDenied) as exc_info:
            tools.read("worldbook", "lore.md")
        assert exc_info.value.action == "read"
        assert exc_info.value.resource_type == "worldbook"

    def test_read_without_filename_reads_all(self, tmp_path: Path) -> None:
        tools = _make_scoped(
            tmp_path, {"read": ["state"], "write": ["state"]}
        )
        tools.write("state", "a.md", "file A")
        tools.write("state", "b.md", "file B")
        result = tools.read("state")
        assert "file A" in result
        assert "file B" in result

    def test_read_with_no_read_permission_at_all(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"write": ["state"]})
        with pytest.raises(PermissionDenied):
            tools.read("state")


# ── ScopedTools: write permission gating ──────────────────────────────────────


class TestScopedWritePermission:
    """Agent with {'write': ['short_goal']} can write ShortGoal, cannot write State."""

    def test_can_write_allowed_resource(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"write": ["short_goal"]})
        assert tools.write("short_goal", "plan.md", "# Plan\nWrite chapter 1.") is True

    def test_cannot_write_disallowed_resource(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"write": ["short_goal"]})
        with pytest.raises(PermissionDenied) as exc_info:
            tools.write("state", "summary.md", "mutated state")
        assert exc_info.value.action == "write"
        assert exc_info.value.resource_type == "state"

    def test_write_does_not_imply_read(self, tmp_path: Path) -> None:
        """Per guide:77-78 read/write are independent vectors."""
        tools = _make_scoped(tmp_path, {"write": ["short_goal"]})
        # write is allowed
        tools.write("short_goal", "p.md", "plan")
        # but read is not
        with pytest.raises(PermissionDenied):
            tools.read("short_goal", "p.md")

    def test_read_does_not_imply_write(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"read": ["state"]})
        with pytest.raises(PermissionDenied):
            tools.write("state", "s.md", "x")


# ── ScopedTools: search uses 'read' permission ────────────────────────────────


class TestScopedSearchPermission:
    """search is a read op — gated by 'read', not 'write'."""

    def test_search_allowed_with_read(self, tmp_path: Path) -> None:
        tools = _make_scoped(
            tmp_path, {"read": ["worldbook"], "write": ["worldbook"]}
        )
        tools.write("worldbook", "magic.md", "## 魔法体系\n火球术")
        hits = tools.search("worldbook", "魔法")
        assert len(hits) >= 1

    def test_search_denied_without_read(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"write": ["worldbook"]})
        # Even though write is allowed, search (a read op) is not.
        with pytest.raises(PermissionDenied) as exc_info:
            tools.search("worldbook", "anything")
        assert exc_info.value.action == "read"

    def test_search_denied_on_disallowed_resource(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"read": ["state"]})
        with pytest.raises(PermissionDenied):
            tools.search("worldbook", "anything")

    def test_search_returns_real_hits_from_store(self, tmp_path: Path) -> None:
        """ScopedTools delegates to ResourceStore.search after the check."""
        tools = _make_scoped(
            tmp_path, {"read": ["outline"], "write": ["outline"]}
        )
        tools.write("outline", "ch1.md", "# Chapter 1\n## Scene A\n## Scene B")
        hits = tools.search("outline", "Scene")
        assert len(hits) >= 2
        # Hit shape comes from the real ResourceStore.
        assert all(h.filename == "ch1.md" for h in hits)


# ── ScopedTools delegates to ResourceStore after permission check ─────────────


class TestScopedToolsDelegatesToStore:
    """ScopedTools delegates to ResourceStore's read/search/write after the check."""

    def test_read_returns_actual_store_content(self, tmp_path: Path) -> None:
        tools = _make_scoped(
            tmp_path, {"read": ["notes"], "write": ["notes"]}
        )
        tools.write("notes", "n.md", "real content from store")
        # The content comes from ResourceStore.read, not a stub.
        assert tools.read("notes", "n.md") == "real content from store"

    def test_write_persists_via_store(self, tmp_path: Path) -> None:
        """A write through ScopedTools lands on disk via ResourceStore.write."""
        tools = _make_scoped(tmp_path, {"write": ["facts"]})
        tools.write("facts", "truth.md", "gravity is real")
        # Read it back directly from the store (bypassing ScopedTools) to
        # prove delegation.
        store = ResourceStore(tmp_path)
        resource = store.create_resource("facts", "facts")
        assert store.read(resource, "truth.md") == "gravity is real"

    def test_index_updated_via_store(self, tmp_path: Path) -> None:
        """ResourceStore.write updates the .index — proving real delegation."""
        tools = _make_scoped(
            tmp_path, {"read": ["outline"], "write": ["outline"]}
        )
        tools.write("outline", "arc.md", "# Arc 1\n## Act 1\ncontent")
        store = ResourceStore(tmp_path)
        resource = store.create_resource("outline", "outline")
        index = (resource.path / ".index").read_text(encoding="utf-8")
        assert "# arc.md" in index
        assert "# Arc 1" in index

    def test_inject_into_tools_returns_scoped_tools(self, tmp_path: Path) -> None:
        store = ResourceStore(tmp_path)
        perm = parse_permission({"read": ["state"]})
        tools = inject_into_tools(store, perm)
        assert isinstance(tools, ScopedTools)
        assert tools.store is store
        assert tools.permission is perm


# ── PermissionDenied exception shape ──────────────────────────────────────────


class TestPermissionDenied:
    """PermissionDenied is a clear exception, not a silent return."""

    def test_is_exception_subclass(self) -> None:
        assert issubclass(PermissionDenied, Exception)

    def test_carries_action_and_resource_type(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"read": ["state"]})
        with pytest.raises(PermissionDenied) as exc_info:
            tools.read("worldbook")
        err = exc_info.value
        assert err.action == "read"
        assert err.resource_type == "worldbook"
        assert "worldbook" in str(err)

    def test_message_mentions_allowed_scope(self, tmp_path: Path) -> None:
        tools = _make_scoped(tmp_path, {"read": ["state", "notes"]})
        with pytest.raises(PermissionDenied, match="state") as exc_info:
            tools.read("worldbook")
        # The error surfaces what WAS allowed, so the caller can debug.
        assert "state" in exc_info.value.allowed
        assert "notes" in exc_info.value.allowed

    def test_not_silent_return(self, tmp_path: Path) -> None:
        """A denied call raises — it never returns None or False silently."""
        tools = _make_scoped(tmp_path, {"read": ["state"]})
        # Use a flag to prove the exception was raised, not that the call
        # returned a falsy value.
        raised = False
        try:
            tools.read("worldbook")
        except PermissionDenied:
            raised = True
        assert raised, "PermissionDenied must be raised, not silently returned"
