"""Agent dataclass: id/name/task/input/output/permission/model/skills/tools/head/tail.

Per ``docs/refactor_guide.md:60-73``: each agent is defined by a fixed set
of 11 attributes stored in a data structure (NOT a prompt). The
:func:`app.agents.parser.parse_agent_to_prompt` function assembles these
attributes into a prompt at runtime — "配置是静态的，Prompt 是动态生成的"
(guide:378-384).

The dataclass is **frozen** (immutable): "mutations" to ``name`` / ``task``
/etc. return a new ``Agent`` via :func:`dataclasses.replace`. The ``id`` is
read-only and must never change after creation — it is validated to be
non-empty in ``__post_init__``.

The ``Agent`` structurally satisfies the :class:`RunnerAgent` Protocol
(``id: str``, ``model: str | None``) so it can be passed directly to any
:class:`AgentRunner`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.runtime.permission import Permission

_DEFAULT_TOOLS: list[str] = ["read", "search", "write"]


@dataclass(frozen=True)
class Agent:
    """Agent attribute model — 11 attributes per refactor_guide:62-73.

    Attributes:
        id:         Read-only, created-init, unique. Validated non-empty.
        name:       Agent's display name (e.g. "director", "memory_recaller").
        task:       The agent's task description (core attribute).
        input:      What inputs the agent receives (description).
        output:     Output format description.
        permission: Context isolation scope (hash<string, vector>).
        model:      Which model config to use; None means use runner default.
        skills:     Available skills list. Mutable (dynamically mountable).
        tools:      Available tools list. Default: ["read", "search", "write"].
        head:       Prompt head for special prompt structures; None if unused.
        tail:       Prompt tail for special prompt structures; None if unused.
    """

    id: str
    name: str
    task: str
    input: str
    output: str
    permission: Permission
    model: str | None = None
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=lambda: list(_DEFAULT_TOOLS))
    head: str | None = None
    tail: str | None = None

    def __post_init__(self) -> None:
        """Validate that ``id`` is non-empty (read-only invariant).

        Per refactor_guide:63: "id | 数据结构控制与存储，只读，创建时初始化，唯一".
        The id must never be empty (after whitespace stripping) — this is the
        only runtime validation; uniqueness is enforced by the registry /
        storage layer, not here.
        """
        if not self.id or not self.id.strip():
            msg = "Agent.id must be non-empty (read-only, created-init, unique)"
            raise ValueError(msg)
