from __future__ import annotations

from dataclasses import dataclass, field
import random
import re
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class SkillResult:
    skill: str
    ok: bool
    output: Any
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"skill": self.skill, "ok": self.ok, "output": self.output, "detail": self.detail}


class Skill(Protocol):
    name: str

    def describe(self) -> dict[str, Any]: ...

    def invoke(self, args: dict[str, Any]) -> SkillResult: ...


_DICE_RE = re.compile(r"^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class DiceRollSkill:
    """掷骰技能（DnD 风格）：1d10 / 1d100 / 3d6+2 等。

    确定性原则：默认使用调用方传入的 seed 才可复现；不传 seed 则非确定（仅用于真实运行）。
    本技能是纯函数式（除随机源外无副作用），不调用 LLM。
    """

    name: str = "dice_roll"

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": "掷骰：支持 NdM(+/-K)，如 1d10、1d100、3d6+2。",
            "args": {
                "notation": "字符串，如 '1d100'（必填或用 sides/count）",
                "sides": "整数骰面数（可替代 notation）",
                "count": "整数骰子数量，默认 1",
                "modifier": "整数加值，默认 0",
                "seed": "整数随机种子（提供则结果可复现）",
            },
        }

    def invoke(self, args: dict[str, Any]) -> SkillResult:
        try:
            count, sides, modifier = self._parse_args(args)
        except ValueError as exc:
            return SkillResult(self.name, False, None, str(exc))
        if sides < 1 or count < 1 or count > 1000:
            return SkillResult(self.name, False, None, "非法掷骰参数（sides>=1, 1<=count<=1000）")

        rng = random.Random(args["seed"]) if args.get("seed") is not None else random.Random()
        rolls = [rng.randint(1, sides) for _ in range(count)]
        total = sum(rolls) + modifier
        notation = f"{count}d{sides}" + (f"{modifier:+d}" if modifier else "")
        return SkillResult(
            self.name,
            True,
            {"notation": notation, "rolls": rolls, "modifier": modifier, "total": total},
            f"{notation} => {rolls} {('+ ' + str(modifier)) if modifier else ''}= {total}".strip(),
        )

    def _parse_args(self, args: dict[str, Any]) -> tuple[int, int, int]:
        notation = args.get("notation")
        if isinstance(notation, str) and notation.strip():
            match = _DICE_RE.match(notation)
            if not match:
                raise ValueError(f"无法解析骰子表达式：{notation}")
            count = int(match.group(1)) if match.group(1) else 1
            sides = int(match.group(2))
            modifier = int(match.group(3).replace(" ", "")) if match.group(3) else 0
            return count, sides, modifier
        if args.get("sides") is None:
            raise ValueError("缺少 notation 或 sides")
        count = int(args.get("count", 1))
        sides = int(args["sides"])
        modifier = int(args.get("modifier", 0))
        return count, sides, modifier


class SkillRegistry:
    """内置 Python 技能 registry。MCP 作为未来外部通道，统一在同一抽象下挂载（见 IP-005）。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def has(self, name: str) -> bool:
        return name in self._skills

    def names(self) -> list[str]:
        return sorted(self._skills.keys())

    def invoke(self, name: str, args: dict[str, Any] | None = None) -> SkillResult:
        skill = self._skills.get(name)
        if skill is None:
            return SkillResult(name, False, None, f"未注册技能：{name}")
        return skill.invoke(args or {})

    def describe_all(self) -> list[dict[str, Any]]:
        return [self._skills[name].describe() for name in self.names()]


def build_default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(DiceRollSkill())
    return registry


def resolve_agent_skills(agent_config: dict[str, Any]) -> list[str]:
    """从 agent 配置读取声明的技能名列表（`skills:`）。"""
    skills = agent_config.get("skills") if isinstance(agent_config, dict) else None
    if not isinstance(skills, list):
        return []
    return [str(item) for item in skills if str(item).strip()]


_DICE_REQUEST_RE = re.compile(r"(\d*d\d+(?:\s*[+-]\s*\d+)?)", re.IGNORECASE)


def apply_gm_skills(
    action_text: str,
    registry: SkillRegistry,
    allowed_skills: list[str],
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """GM 技能挂载点：在玩家行动文本里检测可执行技能并调用（确定性可 seed）。

    当前只实现 dice_roll：若 GM 被授予 dice_roll 且行动文本含骰子表达式（如 1d100），
    则执行掷骰并返回结果。其他技能后续可在此扩展或经 MCP 外部通道接入。
    """
    invocations: list[dict[str, Any]] = []
    if not action_text:
        return invocations
    if "dice_roll" in allowed_skills and registry.has("dice_roll"):
        for match in _DICE_REQUEST_RE.finditer(action_text):
            notation = match.group(1)
            result = registry.invoke("dice_roll", {"notation": notation, "seed": seed})
            if result.ok:
                invocations.append(result.to_dict())
    return invocations
