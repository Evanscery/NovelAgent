"""Tests for Resource base class, properties.md serializer, and manifest."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.data.manifest import ResourceManifest, write_manifest
from app.data.properties import ResourceProperties, serialize_properties_md
from app.data.resource import Resource

# ── tests: properties.md serialization ──────────────────────────────


class TestPropertiesSerialize:
    """serialize_properties_md renders the four strategy sections."""

    def test_all_sections_rendered(self) -> None:
        props = ResourceProperties(
            存储方式="按资源类型独立文件存储",
            召回策略="按需由 Recaller Agent 主动请求",
            维护策略="每轮更新，覆盖维护",
            版本策略="增量版本控制，每轮产生新 commit",
        )
        text = serialize_properties_md(props)
        for heading in ("存储方式", "召回策略", "维护策略", "版本策略"):
            assert f"## {heading}" in text
        assert "按需由 Recaller Agent 主动请求" in text

    def test_empty_bodies_render_headings_only(self) -> None:
        text = serialize_properties_md(ResourceProperties())
        assert text.count("## ") == 4
        assert text.endswith("\n")

    def test_multiline_body_preserved(self) -> None:
        props = ResourceProperties(存储方式="文件存储\n- 每个资源一个独立目录")
        text = serialize_properties_md(props)
        assert "- 每个资源一个独立目录" in text


# ── tests: manifest write ────────────────────────────────────────────


class TestManifestIO:
    """write_manifest persists the manifest as JSON."""

    def test_write_produces_valid_json(self, tmp_path: Path) -> None:
        original = ResourceManifest(
            type="outline",
            properties_ref="properties.md",
            recent_commit="abc123def456",
            current_branch="main",
        )
        path = tmp_path / "manifest.json"
        write_manifest(path, original)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["type"] == "outline"
        assert data["recent_commit"] == "abc123def456"
        assert data["current_branch"] == "main"

    def test_minimal_manifest_defaults(self, tmp_path: Path) -> None:
        original = ResourceManifest(type="state", properties_ref="properties.md")
        path = tmp_path / "manifest.json"
        write_manifest(path, original)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["type"] == "state"
        assert data["recent_commit"] is None
        assert data["current_branch"] == "main"


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
        with pytest.raises(FrozenInstanceError):
            r.id = "changed"  # type: ignore[misc]
