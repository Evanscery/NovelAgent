"""Agent registry — load built-in agents from yaml, register custom, load workflow.

Per refactor_guide:92-101 the built-in agents are: director (mandatory),
recaller, scout, writer, critic, maintainer. Each is defined by an
**attribute set** (NOT a prompt) stored in ``app/agents/builtin/*.yaml``;
the parser assembles the prompt at runtime.

The registry resolves agent **names** to :class:`~app.agents.agent.Agent`
instances. Workflow nodes carry an ``agent_name``; the registry turns
that into the concrete agent for the runtime.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.agents.agent import Agent
from app.agents.workflow import WorkflowTree
from app.runtime.permission import parse_permission

_BUILTIN_DIR = Path(__file__).parent / "builtin"
_DEFAULT_WORKFLOW = Path(__file__).parent / "default_workflow.yaml"


class AgentRegistry:
    """Registry of :class:`Agent` instances keyed by agent name.

    Agents are registered under their ``name`` attribute (NOT ``id`` —
    ``id`` is unique per instance, ``name`` is the workflow-facing
    identifier). Re-registering a name overwrites the previous agent.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register *agent* under ``agent.name`` (overwrites prior)."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        """Return the agent registered under *name*.

        Raises:
            KeyError: if no agent is registered under *name*.
        """
        if name not in self._agents:
            msg = f"AgentRegistry: no agent named {name!r}"
            raise KeyError(msg)
        return self._agents[name]

    def has(self, name: str) -> bool:
        """True if an agent is registered under *name*."""
        return name in self._agents

    def list(self) -> list[str]:
        """Return the sorted list of registered agent names."""
        return sorted(self._agents.keys())

    # ── loaders ────────────────────────────────────────────────────────

    def load_builtin(self, builtin_dir: Path = _BUILTIN_DIR) -> None:
        """Load every ``*.yaml`` agent definition in *builtin_dir*.

        Each yaml file defines one agent's attribute set. The file name
        (sans ``.yaml``) is used as the agent's ``id`` if the yaml does
        not specify one; ``name`` defaults to the id.
        """
        for yaml_path in sorted(builtin_dir.glob("*.yaml")):
            agent = _load_agent_yaml(yaml_path)
            self.register(agent)
        # Also pick up .yml just in case.
        for yaml_path in sorted(builtin_dir.glob("*.yml")):
            agent = _load_agent_yaml(yaml_path)
            self.register(agent)

    def load_workflow(self, path: str | Path = _DEFAULT_WORKFLOW) -> WorkflowTree:
        """Load a workflow canvas/tree from *path* and return a :class:`WorkflowTree`.

        Delegates to :func:`app.agents.workflow.load_workflow` (supports
        both canvas-format and tree-format files).
        """
        from app.agents.workflow import load_workflow as _load

        return _load(path)


def _load_agent_yaml(path: Path) -> Agent:
    """Parse a single agent yaml file into an :class:`Agent`.

    The yaml schema (attribute set, NOT a prompt)::

        name: recaller
        task: 召回数据...
        input: 当前状态、世界书...
        output: 召回结果文本
        permission:
          read: [state, character_memory, worldbook, facts, notes]
          write: []
        model: standard        # optional
        skills: [recall]       # optional
        tools: [read, search]  # optional, defaults to read/search/write
        head: |                # optional
          ...
        tail: |                # optional
          ...
        allow_recursive: true  # optional, defaults to true

    Args:
        path: Path to the agent yaml file.

    Returns:
        The parsed :class:`Agent`.

    Raises:
        ValueError: if required fields (name, task, input, output,
            permission) are missing or permission is malformed.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Agent yaml {path!s}: expected a mapping at top level, got {type(raw).__name__}"
        raise ValueError(msg)

    # Required fields.
    for required in ("name", "task", "input", "output", "permission"):
        if required not in raw:
            msg = f"Agent yaml {path!s}: missing required field {required!r}"
            raise ValueError(msg)

    name = raw["name"]
    if not isinstance(name, str) or not name.strip():
        msg = f"Agent yaml {path!s}: 'name' must be a non-empty str"
        raise ValueError(msg)

    # id defaults to the file stem.
    agent_id = raw.get("id", path.stem)
    if not isinstance(agent_id, str) or not agent_id.strip():
        msg = f"Agent yaml {path!s}: 'id' must be a non-empty str"
        raise ValueError(msg)

    # Permission.
    perm_raw = raw["permission"]
    if not isinstance(perm_raw, dict):
        msg = f"Agent yaml {path!s}: 'permission' must be a mapping"
        raise ValueError(msg)
    permission = parse_permission(perm_raw)

    # Optional fields.
    model = raw.get("model")
    if model is not None and not isinstance(model, str):
        msg = f"Agent yaml {path!s}: 'model' must be a str or null"
        raise ValueError(msg)

    skills = raw.get("skills", [])
    if not isinstance(skills, list):
        msg = f"Agent yaml {path!s}: 'skills' must be a list"
        raise ValueError(msg)

    tools = raw.get("tools", ["read", "search", "write"])
    if not isinstance(tools, list):
        msg = f"Agent yaml {path!s}: 'tools' must be a list"
        raise ValueError(msg)

    head = raw.get("head")
    if head is not None and not isinstance(head, str):
        msg = f"Agent yaml {path!s}: 'head' must be a str or null"
        raise ValueError(msg)

    tail = raw.get("tail")
    if tail is not None and not isinstance(tail, str):
        msg = f"Agent yaml {path!s}: 'tail' must be a str or null"
        raise ValueError(msg)

    allow_recursive = raw.get("allow_recursive", True)
    if not isinstance(allow_recursive, bool):
        msg = f"Agent yaml {path!s}: 'allow_recursive' must be a bool"
        raise ValueError(msg)

    return Agent(
        id=agent_id,
        name=name,
        task=raw["task"],
        input=raw["input"],
        output=raw["output"],
        permission=permission,
        model=model,
        skills=list(skills),
        tools=list(tools),
        head=head,
        tail=tail,
        allow_recursive=allow_recursive,
    )


def load_workflow(path: Path = _DEFAULT_WORKFLOW) -> WorkflowTree:
    """Load the default canvas workflow from *path* and parse it to a tree.

    Thin wrapper around :func:`app.agents.workflow.load_workflow` for
    backwards compatibility.
    """
    from app.agents.workflow import load_workflow as _load

    return _load(path)


def build_default_registry() -> AgentRegistry:
    """Build a registry pre-loaded with all built-in agents.

    Returns:
        An :class:`AgentRegistry` with the 5 built-in workflow agents
        (recaller, scout, writer, critic, maintainer) registered.
    """
    registry = AgentRegistry()
    registry.load_builtin()
    return registry


__all__ = [
    "AgentRegistry",
    "build_default_registry",
    "load_workflow",
]
