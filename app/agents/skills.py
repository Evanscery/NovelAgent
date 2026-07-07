"""Skill registry (built-in + from preset extraction); MCP reserved.

Per ``docs/refactor_guide.md:70-71``: skills inherit global (公共 skills), are
mutable, and can be dynamically mounted by the caller. Per ``docs/refactor_guide.md:29``:
allow extracting 文风/jailbreak from a SillyTavern preset to use as agent skills.

The registry is the agent-layer's "global" skills that agents inherit from at
runtime. The agent attribute model (:class:`app.agents.agent.Agent`) carries a
``skills: list[str]`` of skill **names** — the registry resolves names to the
actual :class:`Skill` objects.

Design notes:

* ``DiceRollSkill`` is a pure function (no LLM, no side effects except the
  random source). Deterministic when a ``seed`` is provided; non-deterministic
  otherwise. Ports the dice logic from the legacy ``app/skills.py`` (archived
  at ``archive/legacy/app/skills.py:28-60``) but rewritten for the new
  architecture: it returns a :class:`SkillResult` with a structured ``output``
  dict (``{total, rolls, modifier, notation}``) and uses the new
  :class:`SkillRegistry` API (``get`` raises ``KeyError``, ``list`` not
  ``names``).
* ``extract_skills_from_preset`` is the **basic** extraction + Skill wrapping.
  The full preset-extraction implementation lives in
  ``app/compat/tavern_card/preset_extract.py`` (todo 34) — this function is
  the agent-layer seam that wraps extracted text as :class:`Skill` objects
  with stable, content-hashed names.
* ``register_mcp_skill`` is a **reserved** interface for MCP external skills.
  It raises :class:`NotImplementedError` to surface that the feature is not
  yet wired — callers must not be able to silently register a no-op.

# noqa: SIZE_OK — todo 17 mandates all skill components (Skill protocol,
SkillResult, SkillRegistry, DiceRollSkill, preset extraction, MCP stub,
build_default_registry) live in this single ``app/agents/skills.py`` per the
plan's directory tree. Responsibilities are cohesive (the "skills
abstraction"); the preset-extraction full impl delegates to
compat/tavern_card/preset_extract.py (todo 34).
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from typing import Any, Protocol

# ── Skill protocol & result ────────────────────────────────────────────


class Skill(Protocol):
    """A callable skill — pure function with a name and a schema.

    Per refactor_guide:70-71, skills are dynamically mountable by the caller;
    the registry resolves a skill **name** to the :class:`Skill` instance. The
    protocol is structural (``runtime_checkable`` not required here — the
    registry uses ``.name`` as the key and duck-types ``invoke``).

    ``name`` is declared as a read-only property: concrete skills are frozen
    dataclasses (``DiceRollSkill``, ``PresetStyleSkill``) whose ``name``
    attribute is set-once at construction and immutable thereafter — which is
    exactly the property contract.
    """

    @property
    def name(self) -> str:
        """The unique skill name (set at construction, immutable thereafter)."""
        ...

    def describe(self) -> dict[str, Any]:
        """Return the skill's schema: name, summary, args."""
        ...

    def invoke(self, args: dict[str, Any]) -> SkillResult:
        """Execute the skill with the given args; return a :class:`SkillResult`."""
        ...


@dataclass(frozen=True)
class SkillResult:
    """The outcome of a single skill invocation.

    Attributes:
        skill:  The name of the skill that produced this result.
        ok:     ``True`` if the invocation succeeded; ``False`` if validation
                or execution failed (check ``detail`` for the reason).
        output: The structured result on success. Polymorphic — each skill
                defines its own output shape (e.g. ``DiceRollSkill`` returns
                ``{"total": int, "rolls": list[int], "modifier": int,
                "notation": str}``). ``None`` on failure.
        detail: Human-readable detail — a failure reason on ``ok=False``, or
                a short summary on success. Defaults to ``""``.
    """

    skill: str
    ok: bool
    output: Any
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (for logging / API response / JSON)."""
        return {
            "skill": self.skill,
            "ok": self.ok,
            "output": self.output,
            "detail": self.detail,
        }


# ── DiceRollSkill ──────────────────────────────────────────────────────

# Matches NdM(+/-K) notation: 1d10, 1d100, 3d6+2, d20, 2d8-1.
# Group 1 = count (optional, defaults to 1), group 2 = sides, group 3 = modifier.
_DICE_RE: re.Pattern[str] = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class DiceRollSkill:
    """DnD-style dice roll skill — pure function (no LLM, no side effects except RNG).

    Supports ``NdM(+/-K)`` notation: ``1d10``, ``1d100``, ``3d6+2``, ``d20``,
    ``2d8-1``. Deterministic when ``args["seed"]`` is provided;
    non-deterministic otherwise.

    Args for :meth:`invoke`:
        notation: Dice expression string (e.g. ``"1d100"``). Required unless
            ``sides`` is provided.
        sides:    Integer number of faces. Alternative to ``notation``.
        count:    Integer number of dice. Defaults to ``1``.
        modifier: Integer add/subtract to the total. Defaults to ``0``.
        seed:     Integer RNG seed. If provided, the result is reproducible.

    Returns a :class:`SkillResult` whose ``output`` is::

        {"total": int, "rolls": list[int], "modifier": int, "notation": str}
    """

    name: str = "dice_roll"

    def describe(self) -> dict[str, Any]:
        """Return the skill schema: name, summary, args."""
        return {
            "name": self.name,
            "summary": "掷骰：支持 NdM(+/-K)，如 1d10、1d100、3d6+2。确定性：提供 seed 可复现。",
            "args": {
                "notation": "字符串，如 '1d100'（必填或用 sides/count/modifier）",
                "sides": "整数骰面数（可替代 notation）",
                "count": "整数骰子数量，默认 1",
                "modifier": "整数加值，默认 0",
                "seed": "整数随机种子（提供则结果可复现）",
            },
        }

    def invoke(self, args: dict[str, Any]) -> SkillResult:
        """Execute the dice roll; return a :class:`SkillResult`.

        Validation errors (unparseable notation, ``sides<1``, ``count<1``,
        ``count>1000``) return ``SkillResult(ok=False, output=None, detail=...)``
        — they never raise, so callers can branch on ``ok`` without a try/except.
        """
        try:
            count, sides, modifier = self._parse_args(args)
        except ValueError as exc:
            return SkillResult(self.name, False, None, str(exc))
        if sides < 1 or count < 1 or count > 1000:
            return SkillResult(self.name, False, None, "非法掷骰参数（要求 sides>=1, 1<=count<=1000）")

        seed = args.get("seed")
        rng = random.Random(seed) if seed is not None else random.Random()
        rolls = [rng.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + modifier
        notation = f"{count}d{sides}" + (f"{modifier:+d}" if modifier else "")
        return SkillResult(
            skill=self.name,
            ok=True,
            output={"total": total, "rolls": rolls, "modifier": modifier, "notation": notation},
            detail=f"{notation} => {rolls}{' ' + (f'{modifier:+d}' if modifier else '')} = {total}".strip(),
        )

    def _parse_args(self, args: dict[str, Any]) -> tuple[int, int, int]:
        """Parse notation or sides/count/modifier into (count, sides, modifier).

        Raises:
            ValueError: If notation is unparseable or both notation and sides
                are missing.
        """
        notation = args.get("notation")
        if isinstance(notation, str) and notation.strip():
            match = _DICE_RE.match(notation)
            if not match:
                msg = f"无法解析骰子表达式：{notation!r}"
                raise ValueError(msg)
            count = int(match.group(1)) if match.group(1) else 1
            sides = int(match.group(2))
            modifier = int(match.group(3).replace(" ", "")) if match.group(3) else 0
            return count, sides, modifier
        if args.get("sides") is None:
            msg = "缺少 notation 或 sides 参数"
            raise ValueError(msg)
        count = int(args.get("count", 1))
        sides = int(args["sides"])
        modifier = int(args.get("modifier", 0))
        return count, sides, modifier


# ── SkillRegistry ──────────────────────────────────────────────────────


class SkillRegistry:
    """Registry of available skills — the agent layer's "global" skill set.

    Per refactor_guide:70-71, agents inherit global (公共) skills; this
    registry IS that global set. Callers (runtime / director / system agents)
    dynamically mount additional skills via :meth:`register`.

    The registry is mutable by design: skill mounting is a runtime operation
    (per guide:70 "可由调用者动态挂载"). The registry object itself is the
    single mutability point — individual :class:`Skill` instances remain
    immutable.
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register a skill under ``skill.name``.

        Re-registering the same name overwrites the previous skill (dynamic
        mounting implies replacement is allowed).
        """
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        """Return the skill registered under *name*.

        Raises:
            KeyError: If no skill is registered under *name*. (Hard error —
                callers should resolve agent.skill names before invocation;
                a silent ``None`` return would propagate the missing-skill
                bug to runtime.)
        """
        return self._skills[name]

    def has(self, name: str) -> bool:
        """Return ``True`` if a skill is registered under *name*."""
        return name in self._skills

    def list(self) -> list[str]:
        """Return the sorted list of registered skill names."""
        return sorted(self._skills.keys())

    def invoke(self, name: str, args: dict[str, Any]) -> SkillResult:
        """Convenience: get the skill by name and invoke it with *args*.

        Raises:
            KeyError: If *name* is not registered (delegates to :meth:`get`).
        """
        return self.get(name).invoke(args)

    def register_mcp_skill(self, name: str, config: dict[str, Any]) -> None:
        """Register an MCP external skill — RESERVED for future implementation.

        MCP (Model Context Protocol) external skills are a planned extension
        point. The interface is reserved here so callers can be written
        against it, but the implementation is not yet wired. Any call raises
        :class:`NotImplementedError` to surface that the feature is not
        available — callers must not be able to silently register a no-op.

        Args:
            name:   The skill name to register under.
            config: MCP server config (url, transport, tool schema, etc.).

        Raises:
            NotImplementedError: Always — MCP skills not yet implemented.
        """
        msg = "MCP skills not yet implemented — reserved for future"
        raise NotImplementedError(msg)


# ── Preset skill extraction ────────────────────────────────────────────

# Markdown section headers we recognise as skill-extractable. The header text
# is matched case-insensitively after stripping whitespace; both Chinese (文风)
# and English (jailbreak / Jailbreak) forms are accepted.
_PRESET_SECTION_RE: re.Pattern[str] = re.compile(
    r"^##\s+(.+?)\s*$",
    re.MULTILINE,
)
_STYLE_HEADERS: frozenset[str] = frozenset({"文风", "style", "写作风格"})
_JAILBREAK_HEADERS: frozenset[str] = frozenset({"jailbreak", "越狱"})


def _hash_name(prefix: str, content: str) -> str:
    """Build a stable skill name: ``<prefix>_<8-hex-chars>`` from *content*.

    The hash is content-addressed so the same preset text always yields the
    same skill name — callers can reference a preset-extracted skill by a
    stable identifier across runs.
    """
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{digest}"


def _split_sections(preset_text: str) -> list[tuple[str, str]]:
    """Split *preset_text* into ``[(header, body), ...]`` for ``##``-level sections.

    The body of each section runs from the line after the header to the line
    before the next ``##`` header (or end of text). ``#``-level (top-level)
    and ``###``+ (deeper) headers are NOT section boundaries here — only
    ``##`` sections are extractable skill sources.
    """
    sections: list[tuple[str, str]] = []
    matches = list(_PRESET_SECTION_RE.finditer(preset_text))
    for i, match in enumerate(matches):
        header = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(preset_text)
        body = preset_text[body_start:body_end].strip()
        sections.append((header, body))
    return sections


@dataclass(frozen=True)
class PresetStyleSkill:
    """A skill wrapping an extracted 文风 / jailbreak section from a preset.

    The extracted text becomes the skill's "payload" — when invoked, it
    returns the text as its output (the agent prompt parser will inject it
    into the agent's prompt as a style/jailbreak directive). The name is
    content-hashed so the same preset section yields a stable identifier.

    Attributes:
        name:    ``style_<hash8>`` or ``jailbreak_<hash8>``.
        kind:    ``"style"`` or ``"jailbreak"``.
        text:    The extracted section body (the style/jailbreak directive).
    """

    name: str
    kind: str
    text: str

    def describe(self) -> dict[str, Any]:
        """Return the skill schema: name, summary, args."""
        return {
            "name": self.name,
            "summary": f"从预设提取的 {self.kind} 片段（注入到 agent prompt）。",
            "args": {},
        }

    def invoke(self, args: dict[str, Any]) -> SkillResult:
        """Return the extracted text as the skill output.

        The args are ignored for now — the skill is a static text carrier.
        Future preset-extraction improvements (todo 34) may parameterize this.
        """
        return SkillResult(skill=self.name, ok=True, output={"text": self.text, "kind": self.kind})


def extract_skills_from_preset(preset_text: str) -> list[Skill]:
    """Extract 文风 / jailbreak sections from a preset text as :class:`Skill` objects.

    This is the **basic** extraction + Skill wrapping. The full preset
    extraction (parsing ST preset format, normalizing, etc.) lives in
    ``app/compat/tavern_card/preset_extract.py`` (todo 34); this function is
    the agent-layer seam that wraps the extracted text as skills with stable,
    content-hashed names.

    Scans for markdown ``##``-level sections whose header matches a known
    style/jailbreak label (case-insensitive for English headers):

    * 文风 / style / 写作风格 → ``style_<hash8>``
    * jailbreak / 越狱       → ``jailbreak_<hash8>``

    Args:
        preset_text: The raw preset text (markdown).

    Returns:
        A list of :class:`PresetStyleSkill` (typed as :class:`Skill`) — one
        per matching section. Empty list if no matching sections are found.
        Names are unique by content hash.
    """
    skills: list[Skill] = []
    for header, body in _split_sections(preset_text):
        header_lower = header.lower()
        if header_lower in _STYLE_HEADERS or header in _STYLE_HEADERS:
            skills.append(PresetStyleSkill(name=_hash_name("style", body), kind="style", text=body))
        elif header_lower in _JAILBREAK_HEADERS or header in _JAILBREAK_HEADERS:
            skills.append(
                PresetStyleSkill(name=_hash_name("jailbreak", body), kind="jailbreak", text=body)
            )
    return skills


# ── Default registry factory ───────────────────────────────────────────


def build_default_registry() -> SkillRegistry:
    """Build the default :class:`SkillRegistry` with built-in skills pre-registered.

    This is the "global" skill set that agents inherit from (per
    refactor_guide:70-71 "继承全局公共 skills"). Currently the only built-in
    is :class:`DiceRollSkill`; MCP external skills will be added via
    :meth:`SkillRegistry.register_mcp_skill` once implemented.
    """
    registry = SkillRegistry()
    registry.register(DiceRollSkill())
    return registry
