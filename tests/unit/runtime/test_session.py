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


class TestDirectorToolWiring:
    @pytest.mark.asyncio
    async def test_director_read_tool_call_is_dispatched_not_rejected(
        self, tmp_path: Path
    ) -> None:
        """create_round_session wires the director's ToolDispatcher
        (director permission + project store), so a director ``read``
        tool call is dispatched instead of rejected with
        ``no_tools_surface`` (which used to happen because
        director_tools was never passed)."""
        from app.data.store import ResourceStore
        from app.runtime.prompt_builder import RequestSpec
        from app.runtime.runners.base import (
            AgentResponse,
            AgentRunner,
            RunnerAgent,
            TokenUsage,
            ToolCall,
        )
        from app.runtime.session import run_session

        store = ResourceStore(tmp_path)
        resource = store.create_resource("state", "state-001")
        store.write(resource, "current.md", "主角位于破庙。")

        class _DirectorReadRunner(AgentRunner):
            def __init__(self) -> None:
                self.director_turns = 0

            async def run(self, agent: RunnerAgent, request: RequestSpec) -> AgentResponse:
                if agent.id == "director":
                    self.director_turns += 1
                    if self.director_turns == 1:
                        return AgentResponse(
                            text="读取状态",
                            tool_calls=[
                                ToolCall(
                                    name="read",
                                    args={"resource_type": "state"},
                                    id="call_read",
                                )
                            ],
                            usage=TokenUsage(10, 5),
                        )
                    return AgentResponse(
                        text="完成",
                        tool_calls=[ToolCall(name="finalize", args={})],
                        usage=TokenUsage(10, 5),
                    )
                return AgentResponse(text="sub", usage=TokenUsage(5, 5))

        runner = _DirectorReadRunner()
        tree = _make_tree({})
        session = create_round_session(
            project_path=tmp_path,
            project_id="proj-1",
            context="ctx",
            tree=tree,
            max_iterations=10,
            maximal_recursive_calling_depth=None,
            runner_factory=lambda: runner,
        )
        result = await run_session(session)

        assert result.finalize_reason == "explicit_finalize"
        assert not any(
            "no_tools_surface" in record.reason for record in result.rejected_calls
        ), f"director read was rejected: {result.rejected_calls}"
        # The read actually went through the scoped store (no tool_error).
        assert not any(
            "tool_error" in record.reason for record in result.rejected_calls
        ), f"director read errored: {result.rejected_calls}"


class TestRuntimeConfigWiring:
    def test_runtime_config_supplies_budget_and_depth(self, tmp_path: Path) -> None:
        """create_round_session maps config/runtime.yaml values instead of
        hard-coding policy: budget tokens/tool-calls, iteration multiplier
        and recursion depth all come from the RuntimeConfig."""
        from app.config_loader import RuntimeConfig

        cfg = RuntimeConfig(
            runner={"timeout_seconds": 30, "max_retries": 2, "max_concurrent": 4},
            workflow={
                "maximal_recursive_calling_depth": 3,
                "max_calls_multiplier": 5,
                "max_tokens": 1234,
                "max_tool_calls": 7,
            },
        )
        tree = _make_tree({})
        session = create_round_session(
            project_path=tmp_path,
            project_id="proj-1",
            context="ctx",
            tree=tree,
            max_iterations=None,
            maximal_recursive_calling_depth=None,
            runtime_config=cfg,
        )
        snap = session.budget.snapshot()
        assert snap.max_iterations == 5 * tree.node_count()
        assert snap.max_tokens == 1234
        assert snap.max_tool_calls == 7
        assert session.maximal_recursive_calling_depth == 3

    def test_none_config_keeps_defaults(self, tmp_path: Path) -> None:
        tree = _make_tree({})
        session = create_round_session(
            project_path=tmp_path,
            project_id="proj-1",
            context="ctx",
            tree=tree,
            max_iterations=None,
            maximal_recursive_calling_depth=None,
        )
        snap = session.budget.snapshot()
        assert snap.max_iterations == 2 * tree.node_count()
        assert snap.max_tokens == 100_000
        assert snap.max_tool_calls == 50
        assert session.maximal_recursive_calling_depth == 1


class TestSubAgentToolSurface:
    """Sub-agents get their own permission-scoped tool surface."""

    @staticmethod
    def _call_agent_runner(sub_tool_call: object) -> object:
        from app.runtime.prompt_builder import RequestSpec
        from app.runtime.runners.base import (
            AgentResponse,
            AgentRunner,
            RunnerAgent,
            TokenUsage,
            ToolCall,
        )

        class _Runner(AgentRunner):
            def __init__(self) -> None:
                self.director_turns = 0

            async def run(self, agent: RunnerAgent, request: RequestSpec) -> AgentResponse:
                if agent.id == "director":
                    self.director_turns += 1
                    if self.director_turns == 1:
                        return AgentResponse(
                            text="调度 writer",
                            tool_calls=[
                                ToolCall(
                                    name="call_agent",
                                    args={"agent_name": "writer", "prompt": "写一段"},
                                    id="call_writer",
                                )
                            ],
                            usage=TokenUsage(10, 5),
                        )
                    return AgentResponse(
                        text="完成",
                        tool_calls=[ToolCall(name="finalize", args={})],
                        usage=TokenUsage(10, 5),
                    )
                # The writer emits one tool call of the test's choosing.
                assert isinstance(sub_tool_call, ToolCall)
                return AgentResponse(
                    text="正文",
                    tool_calls=[sub_tool_call],
                    usage=TokenUsage(5, 5),
                )

        return _Runner()

    @pytest.mark.asyncio
    async def test_sub_agent_write_lands_on_disk(self, tmp_path: Path) -> None:
        """A writer's ``write`` tool call is dispatched through its own
        permission scope and the file actually lands in the project."""
        from app.data.store import ResourceStore
        from app.runtime.runners.base import AgentRunner, ToolCall
        from app.runtime.session import run_session

        runner = self._call_agent_runner(
            ToolCall(
                name="write",
                args={
                    "resource_type": "notes",
                    "filename": "draft.md",
                    "content": "写下的正文",
                },
                id="w1",
            )
        )
        assert isinstance(runner, AgentRunner)
        session = create_round_session(
            project_path=tmp_path,
            project_id="proj-1",
            context="ctx",
            tree=_make_tree({}),
            max_iterations=10,
            maximal_recursive_calling_depth=None,
            runner_factory=lambda: runner,
        )
        result = await run_session(session)

        assert result.finalize_reason == "explicit_finalize"
        # completed_agents lists the director exactly once (regression:
        # it used to be appended every loop iteration).
        assert result.completed_agents.count("director") == 1
        assert "writer" in result.completed_agents
        # The write is on disk under the project's notes resource.
        store = ResourceStore(tmp_path)
        notes = store.create_resource("notes", "notes")
        assert "写下的正文" in store.read(notes, "draft.md")

    @pytest.mark.asyncio
    async def test_sub_agent_overreach_write_is_rejected(self, tmp_path: Path) -> None:
        """A writer writing a resource outside its permission is rejected
        with ``tool_error: PermissionDenied`` and nothing lands on disk."""
        from app.runtime.runners.base import AgentRunner, ToolCall
        from app.runtime.session import run_session

        runner = self._call_agent_runner(
            ToolCall(
                name="write",
                args={
                    "resource_type": "worldbook",
                    "filename": "lore.md",
                    "content": "越权写入",
                },
                id="w2",
            )
        )
        assert isinstance(runner, AgentRunner)
        session = create_round_session(
            project_path=tmp_path,
            project_id="proj-1",
            context="ctx",
            tree=_make_tree({}),
            max_iterations=10,
            maximal_recursive_calling_depth=None,
            runner_factory=lambda: runner,
        )
        result = await run_session(session)

        assert any(
            record.agent == "writer" and "tool_error: PermissionDenied" in record.reason
            for record in result.rejected_calls
        ), f"expected a PermissionDenied rejection: {result.rejected_calls}"
        assert not (tmp_path / "resources" / "worldbook" / "lore.md").exists()
