"""Unit tests for the runtime tool catalog (:mod:`app.runtime.tool_catalog`)."""

from __future__ import annotations

import logging

import pytest

from app.agents.tools import BUILTIN_TOOL_SCHEMAS, ToolSchema
from app.runtime.tool_catalog import build_default_catalog


def _custom_schema(name: str = "custom_tool") -> ToolSchema:
    return ToolSchema(
        name=name,
        description="custom",
        parameters={"type": "object", "properties": {}, "required": []},
        source="mcp",
    )


class TestSchemasFor:
    def test_resolves_known_names_in_order(self) -> None:
        catalog = build_default_catalog()
        schemas = catalog.schemas_for(["write", "read"])
        assert [s.name for s in schemas] == ["write", "read"]

    def test_unknown_names_skipped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        catalog = build_default_catalog()
        with caplog.at_level(logging.WARNING, logger="app.runtime.tool_catalog"):
            schemas = catalog.schemas_for(["read", "no_such_tool"])
        assert [s.name for s in schemas] == ["read"]
        assert any("no_such_tool" in m for m in caplog.messages)


class TestInvoke:
    def test_invoke_dice_roll(self) -> None:
        catalog = build_default_catalog()
        result = catalog.invoke("dice_roll", notation="1d6", seed=1)
        assert isinstance(result, dict)
        assert "total" in result

    def test_invoke_schema_only_tool_raises_keyerror(self) -> None:
        catalog = build_default_catalog()
        with pytest.raises(KeyError, match="read"):
            catalog.invoke("read", resource_type="state")

    def test_invoke_unknown_tool_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            build_default_catalog().invoke("nope")


class TestRegister:
    def test_register_schema_and_impl(self) -> None:
        catalog = build_default_catalog()
        catalog.register(_custom_schema(), impl=lambda **kwargs: "custom result")
        assert catalog.has("custom_tool")
        assert catalog.has_impl("custom_tool")
        assert [s.name for s in catalog.schemas_for(["custom_tool"])] == ["custom_tool"]
        assert catalog.invoke("custom_tool") == "custom result"

    def test_register_schema_only(self) -> None:
        catalog = build_default_catalog()
        catalog.register(_custom_schema("schema_only"))
        assert catalog.has("schema_only")
        assert not catalog.has_impl("schema_only")


class TestBuildDefaultCatalog:
    def test_carries_every_builtin_schema(self) -> None:
        catalog = build_default_catalog()
        for name in BUILTIN_TOOL_SCHEMAS:
            assert catalog.has(name)

    def test_only_dice_roll_has_impl(self) -> None:
        assert build_default_catalog().impl_names() == ["dice_roll"]
