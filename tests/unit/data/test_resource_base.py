"""Tests for Resource base class, properties.md parser/serializer, and manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.data.manifest import ResourceManifest, read_manifest, write_manifest
from app.data.properties import (
    ResourceProperties,
    ValidationError,
    parse_properties_md,
    serialize_properties_md,
)
from app.data.resource import Resource


# ── tests: properties.md round-trip ──────────────────────────────────


class TestPropertiesRoundTrip:
    """parse(serialize(props)) == props — and edge cases."""

    def test_basic_round_trip(self) -> None:
        """Full four-strategy properties round-trips correctly."""
        original = ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="按需由 Recaller Agent 主动请求",
            维护策略="每轮更新，覆盖维护",
            版本策略="增量版本控制，每轮产生新 commit",
        )
        text = serialize_properties_md(original)
        parsed = parse_properties_md(text)
        assert parsed == original

    def test_fields_with_empty_body(self) -> None:
        """Empty string body for each section is valid and round-trips."""
        original = ResourceProperties()
        text = serialize_properties_md(original)
        parsed = parse_properties_md(text)
        assert parsed == original

    def test_round_trip_with_multiline(self) -> None:
        """Multi-line body content is preserved across parse/serialize."""
        original = ResourceProperties(
            存储方式="文件存储\n- 每个资源一个独立目录\n- properties.md 和 manifest.json 并存",
            召回策略="工具调用\n  1. 阅读分级摘要\n  2. 发现相关回合\n  3. 调用工具召回正文",
            维护策略="由 maintainer agent 按 properties.md 策略执行\n根据更新频次分类维护",
            版本策略="git 版本管理\n- Turn = commit\n- Commit = 本轮所有修改\n- Rollback = 新分支",
        )
        text = serialize_properties_md(original)
        parsed = parse_properties_md(text)
        assert parsed == original

    def test_ignore_pre_heading_content(self) -> None:
        """Content before the first ## heading is ignored."""
        text = "这是前置说明，不是有效 section。\n\n## 存储方式\n按文件存储\n\n## 召回策略\n按需\n\n## 维护策略\n每轮\n\n## 版本策略\n覆盖\n"
        parsed = parse_properties_md(text)
        assert parsed.存储方式 == "按文件存储"
        assert parsed.召回策略 == "按需"

    def test_extra_headings_ignored(self) -> None:
        """Unrecognized heading sections are silently ignored."""
        text = (
            "## 存储方式\n文件\n\n"
            "## 召回策略\n按需\n\n"
            "## 维护策略\n每轮\n\n"
            "## 版本策略\n覆盖\n\n"
            "## 额外信息\n这个不会被解析\n"
        )
        parsed = parse_properties_md(text)
        assert parsed.存储方式 == "文件"
        assert parsed.维护策略 == "每轮"


class TestPropertiesParseErrors:
    """Missing sections raise clear ValidationError."""

    def test_missing_one_section(self) -> None:
        """Raise ValidationError naming the missing section."""
        text = "## 存储方式\n文件\n\n## 召回策略\n按需\n\n## 版本策略\n覆盖\n"
        with pytest.raises(ValidationError) as exc:
            parse_properties_md(text)
        assert "维护策略" in str(exc.value)

    def test_missing_all_sections(self) -> None:
        """Raise ValidationError listing first missing."""
        text = "空白内容，没有 section。"
        with pytest.raises(ValidationError) as exc:
            parse_properties_md(text)
        assert "存储方式" in str(exc.value)

    def test_empty_string(self) -> None:
        """Empty text raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            parse_properties_md("")
        assert "存储方式" in str(exc.value)


# ── tests: manifest read/write ───────────────────────────────────────


class TestManifestIO:
    """Read and write manifest.json round-trip."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """Write then read back produces an equal manifest."""
        original = ResourceManifest(
            type="outline",
            properties_ref="properties.md",
            recent_commit="abc123def456",
            current_branch="main",
        )
        path = tmp_path / "manifest.json"
        write_manifest(path, original)
        reloaded = read_manifest(path)
        assert reloaded == original

    def test_minimal_manifest(self, tmp_path: Path) -> None:
        """Manifest with optional fields at defaults round-trips."""
        original = ResourceManifest(
            type="state",
            properties_ref="properties.md",
        )
        path = tmp_path / "manifest.json"
        write_manifest(path, original)
        reloaded = read_manifest(path)
        assert reloaded == original
        assert reloaded.recent_commit is None
        assert reloaded.current_branch == "main"

    def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        """Reading a non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            read_manifest(tmp_path / "does_not_exist.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        """Reading malformed JSON raises json.JSONDecodeError."""
        p = tmp_path / "manifest.json"
        p.write_text("not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_manifest(p)


# ── tests: Resource abstract base ────────────────────────────────────


class TestResourceBase:
    """Resource ABC enforces contract and accepts concrete stubs."""

    def test_cannot_instantiate_directly(self) -> None:
        """Resource() raises TypeError because it's abstract."""
        with pytest.raises(TypeError):
            Resource(  # type: ignore[abstract]
                id="test",
                type="test",
                path=Path("/tmp"),
                properties=ResourceProperties(),
                manifest=ResourceManifest(type="test", properties_ref="props.md"),
            )

    def test_concrete_subclass(self) -> None:
        """A concrete ABC subclass can be instantiated with all fields."""

        class StubResource(Resource):
            @classmethod
            def default_properties(cls) -> ResourceProperties:
                return ResourceProperties(
                    存储方式="文件",
                    召回策略="按需",
                    维护策略="手动",
                    版本策略="覆盖",
                )

        r = StubResource(
            id="test-001",
            type="stub",
            path=Path("/tmp/resource"),
            properties=ResourceProperties(),
            manifest=ResourceManifest(type="stub", properties_ref="props.md"),
        )
        assert r.id == "test-001"
        assert r.type == "stub"
        assert isinstance(r.path, Path)
        assert isinstance(r.properties, ResourceProperties)
        assert isinstance(r.manifest, ResourceManifest)

    def test_default_properties_is_classmethod(self) -> None:
        """default_properties() can be called on the class directly."""

        class StubResource(Resource):
            @classmethod
            def default_properties(cls) -> ResourceProperties:
                return ResourceProperties(
                    存储方式="文件",
                    召回策略="按需",
                    维护策略="手动",
                    版本策略="覆盖",
                )

        default = StubResource.default_properties()
        assert isinstance(default, ResourceProperties)
        assert default.存储方式 == "文件"

    def test_frozen_dataclass_immutable(self) -> None:
        """Resource instances are frozen — field mutation raises FrozenInstanceError."""

        class StubResource(Resource):
            @classmethod
            def default_properties(cls) -> ResourceProperties:
                return ResourceProperties()

        r = StubResource(
            id="test-001",
            type="stub",
            path=Path("/tmp/resource"),
            properties=ResourceProperties(),
            manifest=ResourceManifest(type="stub", properties_ref="props.md"),
        )
        with pytest.raises(Exception):
            r.id = "changed"  # type: ignore[misc]
