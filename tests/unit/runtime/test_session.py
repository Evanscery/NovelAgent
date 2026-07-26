"""Unit tests for the runtime session factory (:mod:`app.runtime.session`).

Covers registration of embedded definitions from an imported
:class:`WorkflowTree`: valid agent definitions are registered into the
round's registry; malformed definitions are skipped with a warning
(never silently swallowed, never fatal to session construction).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from app.agents.tree_model import AGENT_KIND, NodeDefinition, TreeNode, WorkflowTree
from app.runtime.session import create_round_session


def _make_tree(definitions: dict[str, NodeDefinition]) -> WorkflowTree:
    root = TreeNode(
        id="node-1",
        agent_name="writer",
        description="root node",
        params={},
        depth=0,
        parent_id=None,
    )
    return WorkflowTree(root=root, definitions=definitions)


def _agent_payload(agent_id: str, name: str) -> dict[str, object]:
    return {
        "id": agent_id,
        "name": name,
        "task": "imported task",
        "input": "imported input",
        "output": "imported output",
        "permission": {"read": ["state"], "write": []},
    }


class TestImportedDefinitionRegistration:
    def test_valid_definition_registered_malformed_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        valid = NodeDefinition(
            kind=AGENT_KIND,
            id="imported-writer",
            payload=_agent_payload("imported-writer", "writer"),
        )
        # Malformed: payload is missing the required 'id' field.
        malformed = NodeDefinition(
            kind=AGENT_KIND,
            id="broken-agent",
            payload={"name": "broken"},
        )
        tree = _make_tree({valid.key: valid, malformed.key: malformed})

        with caplog.at_level(logging.WARNING, logger="app.runtime.session"):
            session = create_round_session(
                project_path=tmp_path,
                project_id="proj-1",
                context="ctx",
                tree=tree,
                max_iterations=None,
                maximal_recursive_calling_depth=None,
            )

        # Session construction survived the malformed definition.
        assert session.state == "pending"
        # The valid definition is registered under its id.
        agent = session.registry.get("imported-writer")
        assert agent.name == "writer"
        # The malformed definition produced a warning, not silence.
        assert any("agent:broken-agent" in message for message in caplog.messages)

    def test_non_agent_kind_definitions_are_ignored(self, tmp_path: Path) -> None:
        tool_def = NodeDefinition(kind="tool", id="some-tool", payload={"whatever": 1})
        tree = _make_tree({tool_def.key: tool_def})
        session = create_round_session(
            project_path=tmp_path,
            project_id="proj-1",
            context="ctx",
            tree=tree,
            max_iterations=None,
            maximal_recursive_calling_depth=None,
        )
        with pytest.raises(KeyError):
            session.registry.get("some-tool")


class TestProjectAgentOverrides:
    def test_project_override_reaches_round_registry(self, tmp_path: Path) -> None:
        """An agent overridden in <project>/agents/*.yaml is the one the
        round session's registry resolves (run path honors overrides)."""
        project = tmp_path
        agents_dir = project / "agents"
        agents_dir.mkdir()
        (agents_dir / "writer.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "writer",
                    "name": "writer",
                    "task": "OVERRIDDEN TASK",
                    "input": "i",
                    "output": "o",
                    "permission": {"read": ["state"], "write": []},
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        session = create_round_session(
            project_path=project,
            project_id="proj-1",
            context="ctx",
            tree=None,
            max_iterations=None,
            maximal_recursive_calling_depth=None,
        )
        assert session.registry.get("writer").task == "OVERRIDDEN TASK"

    def test_imported_tree_definition_wins_over_project_override(
        self, tmp_path: Path
    ) -> None:
        """A portable workflow's embedded definition registers after the
        project override, so the imported tree's own node definitions win."""
        project = tmp_path
        agents_dir = project / "agents"
        agents_dir.mkdir()
        (agents_dir / "writer.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": "imported-writer",
                    "name": "writer",
                    "task": "PROJECT OVERRIDE",
                    "input": "i",
                    "output": "o",
                    "permission": {"read": ["state"], "write": []},
                }
            ),
            encoding="utf-8",
        )
        definition = NodeDefinition(
            kind=AGENT_KIND,
            id="imported-writer",
            payload=_agent_payload("imported-writer", "writer"),
        )
        tree = _make_tree({definition.key: definition})

        session = create_round_session(
            project_path=project,
            project_id="proj-1",
            context="ctx",
            tree=tree,
            max_iterations=None,
            maximal_recursive_calling_depth=None,
        )
        assert session.registry.get("imported-writer").task == "imported task"
