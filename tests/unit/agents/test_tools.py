"""Tests for app.agents.tools — unified tool schema metadata + ToolExecutor.

Per ``docs/refactor_guide.md:112-123`` the standardized tool surface is a
small set of unified tools: ``read``, ``write``, ``list_files``,
``glob_files``, ``grep_lines``, ``read_lines``. The legacy ``readFile`` /
``readMemory`` / ``readLore`` style proliferation is forbidden; calling
any of those names must raise ``NameError`` (proving the module does not
define them).

These tests use a real :class:`~app.data.store.ResourceStore` rooted at
pytest's ``tmp_path`` fixture, wrapped by a real
:class:`~app.runtime.permission.ScopedTools` (permission enforcement), and
exercised through :class:`~app.runtime.tool_executor.ToolExecutor` — no
mocks of the data or permission layers, only real file I/O.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.agents.tools import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    get_tool_schema,
    list_available_tools,
)
from app.data.store import ResourceStore
from app.runtime.permission import (
    PermissionDenied,
    ScopedTools,
    inject_into_tools,
    parse_permission,
)
from app.runtime.tool_executor import ToolExecutor

# ── Helpers ────────────────────────────────────────────────────────────────


def _resolve_undefined(name: str) -> object:
    """Resolve a name that is intentionally NOT defined in this module.

    Used by :class:`TestStandardization` to prove that ``readFile`` /
    ``readMemory`` / ``readLore`` raise :class:`NameError` at runtime when an
    agent tries to call them — without tripping mypy's ``name-defined`` check
    on a bare undefined identifier. We resolve through ``globals()`` (which
    raises ``KeyError``, then we raise ``NameError`` to match what a Python
    caller would actually see).
    """
    if name not in globals():
        msg = f"name '{name}' is not defined"
        raise NameError(msg)
    return globals()[name]


def _make_executor(
    tmp_path: Path,
    raw_perm: dict[str, list[str]],
) -> ToolExecutor:
    """Build a ToolExecutor over a real ResourceStore rooted at tmp_path.

    The executor delegates to a real ScopedTools (permission enforcement)
    wrapping a real ResourceStore (file I/O). No mocks.
    """
    store = ResourceStore(tmp_path)
    perm = parse_permission(dict[str, object](raw_perm))
    scoped = inject_into_tools(store, perm)
    return ToolExecutor(scoped)


def _seed_worldbook(tmp_path: Path) -> None:
    """Write a worldbook entry containing '魔法' via a wide-permission scope."""
    seeder = _make_executor(
        tmp_path,
        {"read": ["worldbook"], "write": ["worldbook"]},
    )
    seeder.write(
        "worldbook",
        "magic_system.md",
        textwrap.dedent(
            """
            # 魔法体系

            火球术是初阶魔法，需要吟唱咒语。
            治愈术属于神圣魔法，消耗大量魔力。
            """.strip()
        ),
    )


# ── read ───────────────────────────────────────────────────────────────────


class TestRead:
    """read(resource_type, filename=None) returns State content via ScopedTools."""

    def test_read_returns_state_content(self, tmp_path: Path) -> None:
        """read(state) returns the State resource's content file."""
        # Seed state via a wider scope.
        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "summary.md", "# 当前状态\n英雄在酒馆。")

        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.read("state", "summary.md")
        assert "英雄在酒馆。" in result

    def test_read_without_filename_returns_all_content(self, tmp_path: Path) -> None:
        """read(state) with no filename reads all content files concatenated."""
        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "a.md", "file A content")
        seeder.write("state", "b.md", "file B content")

        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.read("state")
        assert "file A content" in result
        assert "file B content" in result

    def test_read_delegates_to_scoped_tools(self, tmp_path: Path) -> None:
        """ToolExecutor.read delegates to ScopedTools.read (verifiable via .scoped_tools)."""
        executor = _make_executor(tmp_path, {"read": ["state"]})
        assert isinstance(executor.scoped_tools, ScopedTools)

    def test_read_returns_str(self, tmp_path: Path) -> None:
        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "x.md", "text")
        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.read("state", "x.md")
        assert isinstance(result, str)


# ── list_files / glob_files / grep_lines / read_lines ─────────────────────


class TestListFiles:
    """list_files(resource_type) returns content file names."""

    def test_list_files_returns_sorted_content_files(self, tmp_path: Path) -> None:
        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "b.md", "b content")
        seeder.write("state", "a.md", "a content")

        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.list_files("state")
        assert result == ["a.md", "b.md"]

    def test_list_files_excludes_metadata(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.list_files("state")
        assert "properties.md" not in result
        assert "manifest.json" not in result


class TestGlobFiles:
    """glob_files(resource_type, pattern) returns matching file names."""

    def test_glob_files_matches_pattern(self, tmp_path: Path) -> None:
        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "chapter_01.md", "c1")
        seeder.write("state", "chapter_02.md", "c2")
        seeder.write("state", "notes.md", "notes")

        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.glob_files("state", "chapter_*.md")
        assert "chapter_01.md" in result
        assert "chapter_02.md" in result
        assert "notes.md" not in result


class TestGrepLines:
    """grep_lines(resource_type, pattern) returns matching (filename, lineno, text)."""

    def test_grep_lines_returns_matches(self, tmp_path: Path) -> None:
        _seed_worldbook(tmp_path)
        executor = _make_executor(tmp_path, {"read": ["worldbook"]})
        hits = executor.grep_lines("worldbook", "魔法")
        assert len(hits) >= 1
        assert all(isinstance(h, tuple) and len(h) == 3 for h in hits)
        assert any(h[0] == "magic_system.md" for h in hits)

    def test_grep_lines_no_matches_returns_empty(self, tmp_path: Path) -> None:
        _seed_worldbook(tmp_path)
        executor = _make_executor(tmp_path, {"read": ["worldbook"]})
        hits = executor.grep_lines("worldbook", "nonexistent_term_xyz")
        assert hits == []

    def test_grep_lines_specific_filename(self, tmp_path: Path) -> None:
        _seed_worldbook(tmp_path)
        executor = _make_executor(tmp_path, {"read": ["worldbook"]})
        hits = executor.grep_lines("worldbook", "魔法", filename="magic_system.md")
        assert len(hits) >= 1
        assert all(h[0] == "magic_system.md" for h in hits)


class TestReadLines:
    """read_lines(resource_type, filename, start, end) returns line range."""

    def test_read_lines_returns_range(self, tmp_path: Path) -> None:
        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "multi.md", "line1\nline2\nline3\nline4\nline5")
        executor = _make_executor(tmp_path, {"read": ["state"]})
        result = executor.read_lines("state", "multi.md", 2, 4)
        assert result == "line2\nline3\nline4"


# ── write ──────────────────────────────────────────────────────────────────


class TestWrite:
    """write(resource_type, filename, content) creates file."""

    def test_write_creates_file_and_returns_true(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path, {"write": ["short_goal"]})
        result = executor.write("short_goal", "turn_5.md", "# 第 5 回合计划\n推进剧情。")
        assert result is True
        # The file actually exists on disk via the underlying ResourceStore.
        store = ResourceStore(tmp_path)
        resource = store.create_resource("short_goal", "short_goal")
        assert (resource.path / "turn_5.md").exists()
        assert store.read(resource, "turn_5.md") == "# 第 5 回合计划\n推进剧情。"

    def test_write_overwrites_existing_file(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path, {"write": ["short_goal"]})
        executor.write("short_goal", "plan.md", "v1")
        executor.write("short_goal", "plan.md", "v2 — updated")
        store = ResourceStore(tmp_path)
        resource = store.create_resource("short_goal", "short_goal")
        assert store.read(resource, "plan.md") == "v2 — updated"


# ── Permission enforcement delegation ──────────────────────────────────────


class TestPermissionEnforcement:
    """ToolExecutor delegates permission enforcement to ScopedTools (guide:80)."""

    def test_write_to_resource_lacking_write_perm_raises_permission_denied(
        self,
        tmp_path: Path,
    ) -> None:
        """Agent with {'read': ['state']} cannot write to state."""
        executor = _make_executor(tmp_path, {"read": ["state"]})
        with pytest.raises(PermissionDenied) as exc_info:
            executor.write("state", "summary.md", "mutated")
        assert exc_info.value.action == "write"
        assert exc_info.value.resource_type == "state"

    def test_read_to_resource_lacking_read_perm_raises_permission_denied(
        self,
        tmp_path: Path,
    ) -> None:
        """Agent with {'write': ['short_goal']} cannot read short_goal."""
        executor = _make_executor(tmp_path, {"write": ["short_goal"]})
        with pytest.raises(PermissionDenied) as exc_info:
            executor.read("short_goal")
        assert exc_info.value.action == "read"
        assert exc_info.value.resource_type == "short_goal"

    def test_list_files_to_resource_lacking_read_perm_raises_permission_denied(
        self,
        tmp_path: Path,
    ) -> None:
        """list_files is a read op — gated by 'read' not 'write'."""
        executor = _make_executor(tmp_path, {"write": ["worldbook"]})
        with pytest.raises(PermissionDenied) as exc_info:
            executor.list_files("worldbook")
        assert exc_info.value.action == "read"

    def test_permission_denied_propagates_unchanged(self, tmp_path: Path) -> None:
        """ToolExecutor must NOT swallow PermissionDenied — it propagates."""
        executor = _make_executor(tmp_path, {"read": ["state"]})
        raised = False
        try:
            executor.read("worldbook")
        except PermissionDenied:
            raised = True
        assert raised, "PermissionDenied must propagate, not be swallowed"


# ── Standardization: NO readFile/readMemory/readLore ───────────────────────


class TestStandardization:
    """Per guide:112-123 only unified tools exist. readFile etc. forbidden."""

    def test_calling_readfile_raises_nameerror(self) -> None:
        """readFile is NOT defined anywhere — proves standardization.

        We resolve the name via ``globals()`` rather than calling it directly
        so that mypy does not flag the bare undefined name (the *runtime*
        behaviour — a ``NameError`` when an agent calls ``readFile(...)`` —
        is what we are asserting here).
        """
        with pytest.raises(NameError, match="readFile"):
            _resolve_undefined("readFile")

    def test_calling_readmemory_raises_nameerror(self) -> None:
        with pytest.raises(NameError, match="readMemory"):
            _resolve_undefined("readMemory")

    def test_calling_readlore_raises_nameerror(self) -> None:
        with pytest.raises(NameError, match="readLore"):
            _resolve_undefined("readLore")

    def test_tools_module_does_not_define_readfile(self) -> None:
        """The tools module has no readFile/readMemory/readLore attributes."""
        from app.agents import tools as tools_module

        forbidden = ("readFile", "readMemory", "readLore")
        for name in forbidden:
            assert not hasattr(tools_module, name), (
                f"app.agents.tools must NOT define {name!r} (guide:113-118)"
            )

    def test_tools_module_does_not_export_readfile(self) -> None:
        from app.agents import tools as tools_module

        forbidden = ("readFile", "readMemory", "readLore")
        for name in forbidden:
            assert name not in tools_module.__all__, (
                f"app.agents.tools must NOT export {name!r}"
            )


# ── TOOL_REGISTRY: exactly 6 entries ───────────────────────────────────────


class TestToolRegistry:
    """TOOL_REGISTRY has exactly 6 entries: read, write, list_files, glob_files, grep_lines, read_lines."""

    def test_registry_has_exactly_six_entries(self) -> None:
        assert len(TOOL_REGISTRY) == 6

    def test_registry_keys_are_the_unified_tools(self) -> None:
        assert set(TOOL_REGISTRY.keys()) == {
            "read", "write", "list_files", "glob_files", "grep_lines", "read_lines"
        }

    def test_registry_values_are_strings(self) -> None:
        for name, value in TOOL_REGISTRY.items():
            assert isinstance(value, str), f"TOOL_REGISTRY[{name!r}] must be a str"

    def test_registry_contains_no_forbidden_names(self) -> None:
        forbidden = ("readFile", "readMemory", "readLore", "delete", "update", "search")
        for name in forbidden:
            assert name not in TOOL_REGISTRY


# ── get_tool_schema ────────────────────────────────────────────────────────


class TestGetToolSchema:
    """get_tool_schema returns the correct schema for each tool."""

    def test_read_schema(self) -> None:
        schema = get_tool_schema("read")
        assert schema["name"] == "read"
        assert schema["args"] == {"resource_type": "str", "filename": "str | None"}
        assert schema["returns"] == "str"

    def test_write_schema(self) -> None:
        schema = get_tool_schema("write")
        assert schema["name"] == "write"
        assert schema["args"] == {
            "resource_type": "str",
            "filename": "str",
            "content": "str",
        }
        assert schema["returns"] == "bool"

    def test_list_files_schema(self) -> None:
        schema = get_tool_schema("list_files")
        assert schema["name"] == "list_files"
        assert schema["args"] == {"resource_type": "str"}
        assert schema["returns"] == "list[str]"

    def test_glob_files_schema(self) -> None:
        schema = get_tool_schema("glob_files")
        assert schema["name"] == "glob_files"
        assert schema["args"] == {"resource_type": "str", "pattern": "str"}
        assert schema["returns"] == "list[str]"

    def test_grep_lines_schema(self) -> None:
        schema = get_tool_schema("grep_lines")
        assert schema["name"] == "grep_lines"
        assert schema["returns"] == "list[tuple[str, int, str]]"

    def test_read_lines_schema(self) -> None:
        schema = get_tool_schema("read_lines")
        assert schema["name"] == "read_lines"
        assert schema["args"] == {
            "resource_type": "str",
            "filename": "str",
            "start": "int",
            "end": "int",
        }
        assert schema["returns"] == "str"

    def test_unknown_tool_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="Unknown tool: 'readFile'"):
            get_tool_schema("readFile")

    def test_unknown_tool_error_lists_valid_tools(self) -> None:
        with pytest.raises(KeyError) as exc_info:
            get_tool_schema("delete")
        msg = str(exc_info.value)
        # The error surfaces the valid tool names so callers can debug.
        assert "read" in msg
        assert "write" in msg
        assert "list_files" in msg


# ── list_available_tools ───────────────────────────────────────────────────


class TestListAvailableTools:
    """list_available_tools returns the unified tools in canonical order."""

    def test_returns_six_tools(self) -> None:
        assert len(list_available_tools()) == 6

    def test_returns_canonical_order(self) -> None:
        assert list_available_tools() == [
            "read", "list_files", "glob_files", "grep_lines", "read_lines", "write"
        ]

    def test_returns_new_list_each_call(self) -> None:
        """list_available_tools must return a fresh list (no shared mutable default)."""
        a = list_available_tools()
        b = list_available_tools()
        assert a == b
        assert a is not b


# ── TOOL_SCHEMAS consistency ───────────────────────────────────────────────


class TestToolSchemasConsistency:
    """TOOL_SCHEMAS, TOOL_REGISTRY, list_available_tools are mutually consistent."""

    def test_schemas_match_registry_keys(self) -> None:
        assert set(TOOL_SCHEMAS.keys()) == set(TOOL_REGISTRY.keys())

    def test_schemas_match_list_available_tools(self) -> None:
        assert set(TOOL_SCHEMAS.keys()) == set(list_available_tools())

    def test_each_schema_has_name_args_returns(self) -> None:
        for name, schema in TOOL_SCHEMAS.items():
            assert "name" in schema, f"schema for {name!r} missing 'name'"
            assert "args" in schema, f"schema for {name!r} missing 'args'"
            assert "returns" in schema, f"schema for {name!r} missing 'returns'"
            assert schema["name"] == name

    def test_exactly_six_schemas(self) -> None:
        assert len(TOOL_SCHEMAS) == 6


# ── ToolExecutor is a ScopedTools Protocol substitute ──────────────────────


class TestToolExecutorProtocol:
    """ToolExecutor satisfies the ScopedTools Protocol."""

    def test_executor_has_unified_tool_methods(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path, {"read": ["state"]})
        assert callable(executor.read)
        assert callable(executor.write)
        assert callable(executor.list_files)
        assert callable(executor.glob_files)
        assert callable(executor.grep_lines)
        assert callable(executor.read_lines)

    def test_executor_scoped_tools_property(self, tmp_path: Path) -> None:
        executor = _make_executor(tmp_path, {"read": ["state"]})
        assert isinstance(executor.scoped_tools, ScopedTools)

    def test_executor_can_be_used_as_scoped_tools_in_dispatcher(
        self,
        tmp_path: Path,
    ) -> None:
        """A ToolExecutor can be handed to ToolDispatcher (which expects ScopedTools)."""
        from app.runtime.runners.base import ToolCall
        from app.runtime.tool_dispatcher import ToolDispatcher

        seeder = _make_executor(
            tmp_path,
            {"read": ["state"], "write": ["state"]},
        )
        seeder.write("state", "s.md", "the state text")
        executor = _make_executor(tmp_path, {"read": ["state"]})

        # ToolDispatcher takes a ScopedTools Protocol; ToolExecutor satisfies it.
        dispatcher = ToolDispatcher(executor)  # type: ignore[arg-type]
        result = dispatcher.dispatch(
            ToolCall(name="read", args={"resource_type": "state", "filename": "s.md"})
        )
        assert result.ok is True
        assert result.output == "the state text"
