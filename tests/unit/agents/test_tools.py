"""Unit tests for the agent-layer tool schemas (:mod:`app.agents.tools`).

The module is pure schema metadata: a frozen :class:`ToolSchema`
dataclass and the :data:`BUILTIN_TOOL_SCHEMAS` mapping covering the six
storage tools, the three director tools, and ``dice_roll``.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.agents.tools import BUILTIN_TOOL_SCHEMAS, ToolSchema

STORAGE_TOOLS = {"read", "write", "list_files", "glob_files", "grep_lines", "read_lines"}
DIRECTOR_TOOLS = {"call_agent", "await", "finalize"}
RUNTIME_TOOLS = {"dice_roll"}


class TestToolSchema:
    def test_frozen(self) -> None:
        schema = BUILTIN_TOOL_SCHEMAS["read"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            schema.name = "other"  # type: ignore[misc]

    def test_default_source_is_builtin(self) -> None:
        for schema in BUILTIN_TOOL_SCHEMAS.values():
            assert schema.source == "builtin"

    def test_to_openai_shape(self) -> None:
        schema = BUILTIN_TOOL_SCHEMAS["write"]
        rendered = schema.to_openai()
        assert rendered["type"] == "function"
        fn = rendered["function"]
        assert fn["name"] == "write"
        assert fn["description"] == schema.description
        assert fn["parameters"] is schema.parameters

    def test_custom_source_round_trips(self) -> None:
        schema = ToolSchema(
            name="external_tool",
            description="d",
            parameters={"type": "object", "properties": {}, "required": []},
            source="mcp",
        )
        assert schema.source == "mcp"


class TestBuiltinToolSchemas:
    def test_contains_exactly_the_builtin_surface(self) -> None:
        assert set(BUILTIN_TOOL_SCHEMAS) == STORAGE_TOOLS | DIRECTOR_TOOLS | RUNTIME_TOOLS

    def test_keys_match_schema_names(self) -> None:
        for name, schema in BUILTIN_TOOL_SCHEMAS.items():
            assert schema.name == name

    def test_parameters_are_json_schema_objects(self) -> None:
        for schema in BUILTIN_TOOL_SCHEMAS.values():
            params = schema.parameters
            assert params["type"] == "object"
            assert isinstance(params["properties"], dict)
            assert isinstance(params["required"], list)
            # required must be a subset of declared properties
            assert set(params["required"]) <= set(params["properties"])

    def test_descriptions_non_empty(self) -> None:
        for schema in BUILTIN_TOOL_SCHEMAS.values():
            assert schema.description.strip()

    def test_call_agent_requires_name_and_prompt(self) -> None:
        params = BUILTIN_TOOL_SCHEMAS["call_agent"].parameters
        assert set(params["required"]) == {"agent_name", "prompt"}

    def test_finalize_and_dice_roll_have_no_required_args(self) -> None:
        assert BUILTIN_TOOL_SCHEMAS["finalize"].parameters["required"] == []
        assert BUILTIN_TOOL_SCHEMAS["dice_roll"].parameters["required"] == []

    def test_read_lines_requires_full_range(self) -> None:
        params = BUILTIN_TOOL_SCHEMAS["read_lines"].parameters
        assert set(params["required"]) == {"resource_type", "filename", "start", "end"}
