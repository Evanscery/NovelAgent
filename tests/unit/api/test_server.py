"""Tests for app.api.server.create_app wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.agents.agent import get_default_tools, set_default_tools
from app.api.server import create_app


class TestCreateAppDefaultTools:
    """create_app applies config/agents.yaml default_tools — the single
    wiring point for every entry path (CLI serve, direct uvicorn, tests)."""

    @pytest.fixture(autouse=True)
    def _restore_default_tools_cache(self) -> object:
        original = get_default_tools()
        yield
        set_default_tools(original)

    def test_create_app_populates_default_tools(self, tmp_path: Path) -> None:
        (tmp_path / "config").mkdir()
        (tmp_path / "workspaces").mkdir()
        (tmp_path / "config" / "agents.yaml").write_text(
            yaml.safe_dump({"default_tools": ["read", "grep_lines"]}),
            encoding="utf-8",
        )
        set_default_tools([])
        create_app(tmp_path)
        assert get_default_tools() == ["read", "grep_lines"]
