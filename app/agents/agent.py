"""
Agent dataclass: id/name/task/input/output/permission/model/tools/head/tail/allow_recursive.

Design Philosophy:
- Configurations are static; prompts are generated dynamically at runtime
  via `render_agent_system_prompt`. Do not hardcode prompts here.

Attributes:
-The first 10 attributes (id … tail) form the core agent attribute set.
The 11th, ``allow_recursive``, is a **runtime-only** flag
introduced by the AST-like workflow design: it is
NOT injected into the agent's prompt (the parser must never emit it), but
it IS serializable to yaml so the front-end config page can expose it as a
per-agent toggle. Runtime uses it as the third recursion-control gate:
when ``allow_recursive is False`` and the director attempts a *recursive*
call (``call_count > 1``), the runtime rejects the call.

Constraints:
-The dataclass is **frozen** (immutable): "mutations" to ``name`` / ``task``
/etc. return a new ``Agent`` via :func:`dataclasses.replace`. The ``id`` is
read-only and must never change after creation — it is validated to be
non-empty in ``__post_init__``.

-The ``Agent`` exposes the minimal attribute surface a runner needs
(``id: str``, ``model: str | None``), so it can be passed directly to
any runner.

The default tools are NOT hardcoded here. ``tools`` falls back to the
module-level cache :data:`_default_tools_cache`, which is populated once
at app startup from ``config/agents.yaml`` (via
:class:`app.config_loader.AgentsConfig`) by :func:`set_default_tools`.
Editing ``config/agents.yaml`` and restarting the server (or the
uvicorn ``--reload`` flag) picks up the new default — there is no in-process
provider callback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.permission import Permission, parse_permission

#: Rigorous agent-id format. ``id`` is the control / storage identifier
#: and ``name`` is the display attribute. A shareable
#: id must be a safe identifier (lowercase alnum + ``-`` / ``_``). Enforced
#: on the load path only, NOT in __post_init__.
_AGENT_ID_RE: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def validate_agent_id(agent_id: object, *, source: str = "agent") -> str:
    """Validate that *agent_id* is a rigorous, shareable agent identifier."""
    if not isinstance(agent_id, str) or not agent_id.strip():
        msg = f"{source}: 'id' is required (non-empty str) — id is the agent's identity, not a display label"
        raise ValueError(msg)
    if not _AGENT_ID_RE.match(agent_id):
        msg = (
            f"{source}: invalid agent id {agent_id!r} — must match {_AGENT_ID_RE.pattern} "
            "(lowercase alnum + '-' / '_', starting with an alnum)"
        )
        raise ValueError(msg)
    return agent_id

#: Default tools cache — populated once from ``config/agents.yaml`` at app
#: startup via :func:`set_default_tools`. Empty until then (ad-hoc
#: construction in unit tests that don't wire the setter just gets ``[]``).
_default_tools_cache: list[str] = []


def set_default_tools(tools: list[str]) -> None:
    """Populate the module-level default-tools cache from the loaded config.

    Called once at app startup (``app.main._serve``) with the
    ``agents.default_tools`` list read by
    :class:`~app.config_loader.ConfigLoader`. Editing ``config/agents.yaml``
    and restarting the process (or uvicorn ``--reload``) picks up the new
    default — there is no in-process reload mechanism here by design.
    """
    global _default_tools_cache
    _default_tools_cache = list(tools)


def get_default_tools() -> list[str]:
    """Return a fresh copy of the cached default tools list.

    Public accessor so callers (e.g. :mod:`app.agents.registry`) consult
    the same fallback the Agent constructor uses without naming the
    private :data:`_default_tools_cache`.
    """
    return list(_default_tools_cache)


@dataclass(frozen=True)
class Agent:
    """Agent attribute model — the 11-attribute agent set.

    Attributes:
        id:              Read-only, created-init, unique. Validated non-empty.
        name:            Agent's display name (e.g. "director", "memory_recaller").
        task:            The agent's task description (core attribute).
        input:           What inputs the agent receives (description).
        output:          Output format description.
        permission:      Context isolation scope (hash<string, vector>).
        model:           Which model config to use; None means use runner default.
        tools:           Available tools list. Default: the cached value from
            ``config/agents.yaml`` (see :func:`set_default_tools`). Empty list
            when the cache has not been populated (e.g. unit tests that don't
            call :func:`set_default_tools`).
        head:            Prompt head for special prompt structures; None if unused.
        tail:            Prompt tail for special prompt structures; None if unused.
        allow_recursive: Runtime-only flag (NOT injected to prompt). When False
            and the director attempts a recursive call (call_count > 1), the
            runtime rejects the call with ``ValueError``. Defaults to True.
            Serializable to yaml so the front-end config page can toggle it.
    """

    id: str
    name: str
    task: str
    input: str
    output: str
    permission: Permission
    model: str | None = None
    tools: list[str] = field(default_factory=lambda: list(_default_tools_cache))
    head: str | None = None
    tail: str | None = None
    allow_recursive: bool = True

    def __post_init__(self) -> None:
        """Validate that ``id`` is non-empty (read-only invariant).

        ``id`` 由数据结构控制与存储：只读，创建时初始化，唯一。
        The id must never be empty (after whitespace stripping) — this is the
        only runtime validation; uniqueness is enforced by the registry /
        storage layer, not here.
        """
        if not self.id or not self.id.strip():
            msg = "Agent.id must be non-empty (read-only, created-init, unique)"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Serialise this agent's full attribute set to a plain dict.

        The inverse of :meth:`from_dict`. Includes ``id`` (the identity)
        so a serialised agent is self-contained and
        shareable: a recipient can reconstruct the exact agent from the dict
        alone (no ``agent_name`` mapping needed).
        """
        return {
            "id": self.id,
            "name": self.name,
            "task": self.task,
            "input": self.input,
            "output": self.output,
            "permission": {
                action: list(vector) for action, vector in self.permission.rules.items()
            },
            "model": self.model,
            "tools": list(self.tools),
            "head": self.head,
            "tail": self.tail,
            "allow_recursive": self.allow_recursive,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, source: str = "agent") -> Agent:
        """Construct an :class:`Agent` from a yaml-style attribute dict.

        This is the single load-path constructor used by the registry
        (``_load_agent_yaml``), the project override loader
        (``build_project_registry``),
        and workflow-tree import (embedded agent definitions). It enforces
        the rigorous id invariant (``id`` is the control identifier, not
        a display label): an explicit, well-formed
        ``id`` is required — there is no file-stem fallback, because
        relying on a file name as identity makes shared agents ambiguous.

        When *raw* omits ``tools``, the agent inherits the cached
        ``config/agents.yaml`` default (see :func:`get_default_tools`).

        Raises:
            ValueError: If a required field is missing or a field has the
                wrong type / an invalid id format.
        """
        if not isinstance(raw, dict):
            msg = f"{source}: expected a mapping, got {type(raw).__name__}"
            raise ValueError(msg)

        for required in ("name", "task", "input", "output", "permission", "id"):
            if required not in raw:
                msg = f"{source}: missing required field {required!r}"
                raise ValueError(msg)

        agent_id = validate_agent_id(raw["id"], source=source)

        name = raw["name"]
        if not isinstance(name, str) or not name.strip():
            msg = f"{source}: 'name' must be a non-empty str"
            raise ValueError(msg)

        perm_raw = raw["permission"]
        if not isinstance(perm_raw, dict):
            msg = f"{source}: 'permission' must be a mapping"
            raise ValueError(msg)
        permission = parse_permission(dict[str, object](perm_raw))

        model = raw.get("model")
        if model is not None and not isinstance(model, str):
            msg = f"{source}: 'model' must be a str or null"
            raise ValueError(msg)

        # NOTE: a leftover 'skills' key from pre-refactor yaml files is
        # deliberately ignored — the skill abstraction was removed (a
        # skill IS an agent), and old files must keep loading.

        tools = list(raw["tools"]) if "tools" in raw else get_default_tools()
        if not isinstance(tools, list):
            msg = f"{source}: 'tools' must be a list"
            raise ValueError(msg)

        head = raw.get("head")
        if head is not None and not isinstance(head, str):
            msg = f"{source}: 'head' must be a str or null"
            raise ValueError(msg)

        tail = raw.get("tail")
        if tail is not None and not isinstance(tail, str):
            msg = f"{source}: 'tail' must be a str or null"
            raise ValueError(msg)

        allow_recursive = raw.get("allow_recursive", True)
        if not isinstance(allow_recursive, bool):
            msg = f"{source}: 'allow_recursive' must be a bool"
            raise ValueError(msg)

        return cls(
            id=agent_id,
            name=name,
            task=raw["task"],
            input=raw["input"],
            output=raw["output"],
            permission=permission,
            model=model,
            tools=tools,
            head=head,
            tail=tail,
            allow_recursive=allow_recursive,
        )
