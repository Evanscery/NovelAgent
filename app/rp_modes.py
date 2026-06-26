"""RP 反馈模型：可插拔的 ``RpMode`` 策略 + per-workspace ``rp.yaml`` 配置。

设计目标（见 docs/known_issue.md §A）：
- GM「反馈」改为按模式分派到策略函数，而不是固定模板复读。
- 内置两种模式：``immersive``（叙述推进，保留原模板作 mock）/ ``trpg``（判定→掷骰→产出 GM 指令）。
- 模式、骰子规则、GM 人格、可见性都按项目隔离，存放在 ``workspaces/<story>/rp.yaml``。
- rp-turn 默认确定性、零 LLM；真实 GM 仅显式 ``gm.runner: llm`` 时触发（当前 NotImplementedError 占位）。

状态推进（``reduce_state_advance_scene``）与叙述解耦：mode 只负责 narrate，不改 scene 推进逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML。请先运行：pip install -e .") from exc

from app.event_types import RuntimeEvent
from app.skills import SkillRegistry, build_default_registry, resolve_agent_skills


# ---- per-workspace RP 配置 ----


@dataclass(frozen=True)
class RpConfig:
    """``workspaces/<story>/rp.yaml`` 的解析结果。全字段可选，缺省即当前默认行为。"""

    mode: str = "immersive"               # immersive | trpg
    dice_source: str = "gm"               # gm | player
    dice_prompt_on: tuple[str, ...] = ()  # 触发判定的 intent 列表（attack/act/...）
    dice_notation: str = "1d20"
    dice_seed: int | None = None
    gm_persona: str = ""                  # 折进 gm_narration 前缀
    gm_runner: str = "mock"               # mock | llm（llm 当前 NotImplementedError）
    debug_default: bool = False


DEFAULT_RP_CONFIG = RpConfig()


def load_rp_config(story_root: Path) -> RpConfig:
    """读取工作区级 ``rp.yaml``；缺失或非法字段一律降级到默认（绝不因配置错误中断回合）。"""
    rp_path = Path(story_root) / "rp.yaml"
    if not rp_path.exists():
        return DEFAULT_RP_CONFIG
    raw = yaml.safe_load(rp_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return DEFAULT_RP_CONFIG

    mode = str(raw.get("mode", "immersive")).strip().lower()
    if mode not in ("immersive", "trpg"):
        mode = "immersive"

    dice_raw = raw.get("dice", {}) or {}
    if not isinstance(dice_raw, dict):
        dice_raw = {}
    source = str(dice_raw.get("source", "gm")).strip().lower()
    if source not in ("gm", "player"):
        source = "gm"
    prompt_on_raw = dice_raw.get("prompt_on", []) or []
    prompt_on = tuple(str(item).strip().lower() for item in prompt_on_raw if str(item).strip()) if isinstance(prompt_on_raw, list) else ()
    notation = str(dice_raw.get("notation", "1d20")).strip() or "1d20"
    seed = dice_raw.get("seed", None)
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = None

    gm_raw = raw.get("gm", {}) or {}
    if not isinstance(gm_raw, dict):
        gm_raw = {}
    persona = str(gm_raw.get("persona", "")).strip()
    runner = str(gm_raw.get("runner", "mock")).strip().lower()
    if runner not in ("mock", "llm"):
        runner = "mock"

    vis_raw = raw.get("visibility", {}) or {}
    if not isinstance(vis_raw, dict):
        vis_raw = {}
    debug_default = bool(vis_raw.get("debug_default", False))

    return RpConfig(
        mode=mode,
        dice_source=source,
        dice_prompt_on=prompt_on,
        dice_notation=notation,
        dice_seed=seed,
        gm_persona=persona,
        gm_runner=runner,
        debug_default=debug_default,
    )


# ---- 策略接口 ----


@dataclass(frozen=True)
class RpContext:
    """每回合构造、传给 mode.narrate 的上下文。全部来自文件，无会话存储。"""

    story_root: Path
    rp_config: RpConfig
    dice_registry: SkillRegistry
    allowed_skills: list[str]
    debug: bool


@dataclass(frozen=True)
class RpResponse:
    """mode.narrate 的返回。``response`` 保持原 layered_turn_response 形状以兼容测试契约。"""

    response: dict[str, Any]
    skill_invocations: list[dict] = field(default_factory=list)
    pending: dict | None = None


class RpMode(Protocol):
    name: str

    def narrate(
        self,
        event: RuntimeEvent,
        state_text: str,
        player_visible_text: str,
        ctx: RpContext,
        next_scene_id: str,
    ) -> RpResponse: ...


# ---- GM runner 钩子（mock 默认；llm 占位，绝不静默联网） ----
#
# 当前 immersive 模式直接用 _base_narration 产出确定性叙述（零 LLM）。
# 此钩子为 RP-A6 预留：未来 gm.runner=llm 时把叙述生成换成真实模型，mode 逻辑不动。


def resolve_gm_runner(rp_config: RpConfig) -> Callable[..., str]:
    if rp_config.gm_runner == "llm":
        raise NotImplementedError("gm.runner=llm 尚未实现（RP-A6）。请设 gm.runner=mock 或省略。")
    # mock：无独立 runner 函数，mode 自行用 _base_narration；返回 no-op 以保留接口形状。
    return lambda *args, **kwargs: ""


# ---- 共享的叙述/反应工具（来自原 event_response_builders） ----


def _base_narration(event: RuntimeEvent, next_scene_id: str) -> str:
    narration = f"场景推进到 {next_scene_id}。{event.actor} 针对 {event.target} 采取了行动：{event.action or event.intent}。"
    if event.intent == "dialogue" and event.dialogue:
        narration += f" 对话内容是：{event.dialogue}。"
    return narration


def _character_reply(event: RuntimeEvent) -> str:
    if event.intent == "dialogue" and event.dialogue:
        return f"{event.target} 听完后给出回应，并把话题推回当前冲突。"
    if event.intent == "inspect":
        return f"{event.target} 注意到你的观察，并露出一丝新的反应。"
    if event.intent == "move":
        return f"{event.target} 随着你的移动而调整站位。"
    return f"{event.target} 对这一行动做出即时反馈。"


def _build_reactions(event: RuntimeEvent, narration: str) -> list[dict]:
    return [
        {"speaker": "GM", "role": "narrator", "text": narration},
        {"speaker": event.target or "环境", "role": "character", "text": _character_reply(event)},
    ]


def _invoke_action_text_dice(event: RuntimeEvent, ctx: RpContext) -> list[dict]:
    """保留原 GM 技能挂载点：玩家行动文本里含骰子表达式时被动掷骰（兼容旧行为）。"""
    from app.skills import apply_gm_skills

    if "dice_roll" not in ctx.allowed_skills or not ctx.dice_registry.has("dice_roll"):
        return []
    action_text = " ".join(part for part in [event.action, event.summary] if part)
    return apply_gm_skills(action_text, ctx.dice_registry, ctx.allowed_skills, seed=ctx.rp_config.dice_seed)


# ---- ImmersiveMode：叙述推进（= 原 mock，零行为变化） ----


class ImmersiveMode:
    name = "immersive"

    def narrate(self, event, state_text, player_visible_text, ctx, next_scene_id):
        narration = _base_narration(event, next_scene_id)
        if ctx.rp_config.gm_persona:
            narration = f"【{ctx.rp_config.gm_persona}】{narration}"
        reactions = _build_reactions(event, narration)
        response: dict[str, Any] = {
            "scene_id": next_scene_id,
            "gm_narration": narration,
            "character_reactions": reactions,
        }
        invocations = _invoke_action_text_dice(event, ctx)
        if invocations:
            response["skill_invocations"] = invocations
        return RpResponse(response=response, skill_invocations=invocations, pending=None)


# ---- TrpgMode：判定→掷骰→GM 指令（RP-A3 最小实现；player 侧 pending 占位） ----


class TrpgMode:
    name = "trpg"

    def narrate(self, event, state_text, player_visible_text, ctx, next_scene_id):
        base = _base_narration(event, next_scene_id)

        should_adjudicate = event.intent in ctx.rp_config.dice_prompt_on
        skill_invocations: list[dict] = []
        pending: dict | None = None
        gm_line = ""

        if should_adjudicate:
            notation = ctx.rp_config.dice_notation
            if ctx.rp_config.dice_source == "gm":
                # GM 侧行动：同回合内掷骰并把结果折进叙述（命中/未命中，阈值 >=10）。
                roll = ctx.dice_registry.invoke("dice_roll", {"notation": notation, "seed": ctx.rp_config.dice_seed})
                if roll.ok:
                    skill_invocations.append(roll.to_dict())
                    total = roll.output.get("total") if isinstance(roll.output, dict) else None
                    outcome = "命中" if isinstance(total, int) and total >= 10 else "未命中"
                    gm_line = f"你过个 {notation} 看是否命中。（GM 掷 {notation} => {total}：{outcome}）"
                else:
                    gm_line = f"你过个 {notation} 看是否命中。"
            else:  # source == player -> RP-A7：不掷，只要求玩家掷，pending 占位（无状态机）
                gm_line = f"请玩家掷 {notation} 并告知结果。"
                pending = {
                    "kind": "player_dice",
                    "notation": notation,
                    "intent": event.intent,
                    "scene_id": next_scene_id,
                    "status": "awaiting_roll",
                }

        narration = base + (f"\n{gm_line}" if gm_line else "")
        if ctx.rp_config.gm_persona:
            narration = f"【{ctx.rp_config.gm_persona}】{narration}"
        reactions = _build_reactions(event, narration)
        response: dict[str, Any] = {
            "scene_id": next_scene_id,
            "gm_narration": narration,
            "character_reactions": reactions,
        }
        if skill_invocations:
            response["skill_invocations"] = skill_invocations
        if pending is not None:
            response["pending"] = pending
        return RpResponse(response=response, skill_invocations=skill_invocations, pending=pending)


def resolve_player_roll(ctx: RpContext, resolve: dict) -> RpResponse:
    """RP-A7：玩家掷骰后把结果回传，GM 据此产出判定叙述。

    不再推进场景、不再要求掷骰：直接用玩家回传的 ``total`` 判定命中/未命中（阈值 >=10），
    产出一句 GM 判定叙述。确定性、零 LLM。``resolve`` 形如
    ``{"scene_id","notation","total"}``。
    """
    notation = str(resolve.get("notation") or ctx.rp_config.dice_notation or "1d20")
    total = resolve.get("total")
    try:
        total_int = int(total)
    except (TypeError, ValueError):
        total_int = None
    scene_id = str(resolve.get("scene_id") or "C00S00")

    if total_int is not None:
        outcome = "命中" if total_int >= 10 else "未命中"
        narration = f"玩家掷 {notation} => {total_int}：{outcome}。"
    else:
        narration = f"玩家掷 {notation} 的结果无法识别，请重掷。"

    if ctx.rp_config.gm_persona:
        narration = f"【{ctx.rp_config.gm_persona}】{narration}"
    response = {
        "scene_id": scene_id,
        "gm_narration": narration,
        "character_reactions": [
            {"speaker": "GM", "role": "narrator", "text": narration},
        ],
        "resolved": True,
    }
    return RpResponse(response=response, skill_invocations=[], pending=None)


def build_rp_mode_registry() -> dict[str, RpMode]:
    """静态策略表。新增模式 = 在此注册，不做自动发现（确定性运行时）。"""
    return {"immersive": ImmersiveMode(), "trpg": TrpgMode()}


def resolve_rp_mode(name: str | None, registry: dict[str, RpMode]) -> RpMode:
    key = (name or "immersive").strip().lower()
    return registry.get(key) or registry["immersive"]


def build_rp_context(story_root: Path, rp_config: RpConfig, config) -> RpContext:
    """构造每回合 ctx：dice registry + 允许技能（来自全局 agents.yaml gm.skills）+ debug。"""
    agents = config.agents.get("agents", {}) if hasattr(config, "agents") else {}
    gm_config = agents.get("gm") or agents.get("game_master") or {}
    allowed = resolve_agent_skills(gm_config)
    registry = build_default_registry()
    return RpContext(
        story_root=Path(story_root),
        rp_config=rp_config,
        dice_registry=registry,
        allowed_skills=allowed,
        debug=rp_config.debug_default,
    )
