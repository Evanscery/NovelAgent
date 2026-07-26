"""Agent registry — load built-in agents from yaml, register custom, load workflow.

Per refactor_guide:92-101 the built-in agents are: director (mandatory),
recaller, scout, writer, critic, maintainer. Each is defined by an
**attribute set** (NOT a prompt) stored in ``app/agents/builtin/*.yaml``;
the parser assembles the prompt at runtime.

The registry resolves agent **names** to :class:`~app.agents.agent.Agent`
instances by **id** (the control/storage identifier, per
refactor_guide:63). ``id`` is unique per instance and is the
workflow/tree-facing identifier; ``name`` is a display attribute
(mutable, not guaranteed unique) and is resolved via
:meth:`get_by_name` only on the user-facing surface (the API config
path and the director's ``call_agent``, which the LLM drives by the
human-readable name it sees in the flow sequence).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.agents.agent import Agent

_BUILTIN_DIR = Path(__file__).parent / "builtin"

#: Sentinel for ambiguous name lookups in the name index.
#: When multiple agents share a display name, the name maps to this
#: sentinel so :meth:`AgentRegistry.get_by_name` can raise.
_AMBIGUOUS: object = object()


class AgentRegistry:
    """Registry of :class:`Agent` instances keyed by agent **id**.

    Per refactor_guide:63, ``id`` is the control/storage identifier
    (unique, read-only); ``name`` is a display attribute (mutable, not
    guaranteed unique). The registry keys its primary index by ``id``;
    a secondary name index supports :meth:`get_by_name` for the
    user-facing surfaces (API config, director's ``call_agent``).

    When ``replace=False`` (default), registering a duplicate id
    raises -- this enforces id uniqueness on the load path. When
    ``replace=True``, the agent at that id is overwritten (used for
    per-project overrides).
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._name_index: dict[str, str | object] = {}

    def register(self, agent: Agent, *, replace: bool = False) -> None:
        """Register *agent* under ``agent.id``.

        When *replace* is False (default), a duplicate id raises
        ValueError. When True, the existing agent at that id is
        overwritten (per-project override path).
        """
        if not replace and agent.id in self._agents:
            msg = f"AgentRegistry: duplicate agent id {agent.id!r}"
            raise ValueError(msg)
        self._agents[agent.id] = agent
        self._rebuild_name_index()

    def get(self, agent_id: str) -> Agent:
        """Return the agent registered under *agent_id* (by id).

        Raises:
            KeyError: if no agent is registered under *agent_id*.
        """
        if agent_id not in self._agents:
            msg = f"AgentRegistry: no agent with id {agent_id!r}"
            raise KeyError(msg)
        return self._agents[agent_id]

    def has(self, agent_id: str) -> bool:
        """True if an agent is registered under *agent_id* (by id)."""
        return agent_id in self._agents

    def list_ids(self) -> list[str]:
        """Return the sorted list of registered agent **ids**."""
        return sorted(self._agents.keys())

    def get_by_name(self, name: str) -> Agent:
        """Resolve an agent by its **display name**.

        Used on user-facing surfaces (API config, director's
        ``call_agent``). Raises if no agent has the name, or if the
        name is ambiguous (multiple agents share it).
        """
        if name not in self._name_index:
            msg = f"AgentRegistry: no agent named {name!r}"
            raise KeyError(msg)
        result = self._name_index[name]
        if result is _AMBIGUOUS:
            msg = f"AgentRegistry: ambiguous agent name {name!r} (multiple agents share it)"
            raise KeyError(msg)
        return self._agents[result]  # type: ignore[index]

    def has_by_name(self, name: str) -> bool:
        """True if exactly one agent is registered under *name*."""
        entry = self._name_index.get(name)
        return entry is not None and entry is not _AMBIGUOUS

    def list_names(self) -> list[str]:
        """Return the sorted list of unique (non-ambiguous) agent names."""
        return sorted(
            n for n, v in self._name_index.items() if v is not _AMBIGUOUS
        )

    def _rebuild_name_index(self) -> None:
        """Rebuild the name-to-id index from the id-keyed agent map."""
        self._name_index = {}
        for agent in self._agents.values():
            if agent.name in self._name_index:
                self._name_index[agent.name] = _AMBIGUOUS
            else:
                self._name_index[agent.name] = agent.id

    # ── loaders ────────────────────────────────────────────────────────

    def load_builtin(self, builtin_dir: Path = _BUILTIN_DIR) -> None:
        """Load every ``*.yaml`` agent definition in *builtin_dir*.

        Each yaml file defines one agent's attribute set with an
        explicit ``id`` field. Duplicate ids raise ValueError
        (enforcing uniqueness on the load path).
        """
        for yaml_path in sorted(builtin_dir.glob("*.yaml")):
            agent = _load_agent_yaml(yaml_path)
            self.register(agent)
        # Also pick up .yml just in case.
        for yaml_path in sorted(builtin_dir.glob("*.yml")):
            agent = _load_agent_yaml(yaml_path)
            self.register(agent)


def _load_agent_yaml(path: Path) -> Agent:
    """Parse a single agent yaml file into an :class:`Agent`.

    Delegates to :meth:`Agent.from_dict` (the single load-path
    constructor). An explicit, well-formed ``id`` is required -- there
    is no file-stem fallback, because relying on a file name as
    identity makes shared agents ambiguous (per refactor_guide:63:
    ``id`` is the control/storage identifier).

    Args:
        path: Path to the agent yaml file.

    Returns:
        The parsed :class:`Agent`.

    Raises:
        ValueError: if required fields (including ``id``) are missing
            or a field has the wrong type / an invalid id format.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"Agent yaml {path!s}: expected a mapping at top level, got {type(raw).__name__}"
        raise ValueError(msg)
    return Agent.from_dict(raw, source=f"agent yaml {path!s}")


def build_default_registry() -> AgentRegistry:
    """Build a registry pre-loaded with all built-in agents.

    Returns:
        An :class:`AgentRegistry` with the 6 built-in agents
        (director, recaller, scout, writer, critic, maintainer)
        registered. The director is a system agent; the other five are
        the workflow agents that appear as nodes in the default workflow
        canvas.
    """
    registry = AgentRegistry()
    registry.load_builtin()
    return registry


def build_project_registry(project_path: Path) -> AgentRegistry:
    """Build a registry for *project_path*: builtins + per-project overrides.

    Loads the built-in agents first, then overlays any per-project
    override files in ``<project_path>/agents/*.yaml`` (``replace=True``,
    so an override sharing a builtin's id wins). Override yamls without
    a ``tools:`` field inherit the cached ``config/agents.yaml`` default
    (see :func:`app.agents.agent.get_default_tools`).

    This is the single project-scoped registry constructor: both the API
    config surface and the runtime round-session factory use it, so an
    agent overridden in a project takes effect on the run path too.

    Raises:
        ValueError: If an override file is not a mapping or fails
            :meth:`Agent.from_dict` validation.
    """
    registry = build_default_registry()
    override_dir = project_path / "agents"
    if override_dir.is_dir():
        paths = sorted(override_dir.glob("*.yaml")) + sorted(override_dir.glob("*.yml"))
        for yaml_path in paths:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if raw is None:
                continue
            if not isinstance(raw, dict):
                msg = (
                    f"project agent override {yaml_path!s}: expected a mapping "
                    f"at top level, got {type(raw).__name__}"
                )
                raise ValueError(msg)
            agent = Agent.from_dict(raw, source=f"project agent override {yaml_path!s}")
            registry.register(agent, replace=True)
    return registry


__all__ = [
    "AgentRegistry",
    "build_default_registry",
    "build_project_registry",
]
