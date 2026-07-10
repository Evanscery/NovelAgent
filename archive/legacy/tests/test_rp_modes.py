"""RP 模式策略与 per-workspace rp.yaml 的 deterministic 测试。

遵循最小 LLM 原则：全部确定性、零 LLM（gm.runner 默认 mock；llm 路径只断言抛错）。
"""
import shutil
from pathlib import Path

import pytest

from app.config_loader import ConfigLoader
from app.main import load_story_config, run_rp_turn
from app.rp_modes import (
    DEFAULT_RP_CONFIG,
    ImmersiveMode,
    RpContext,
    TrpgMode,
    build_rp_context,
    build_rp_mode_registry,
    load_rp_config,
    resolve_rp_mode,
)
from app.story_config import remap_config_to_story_root


@pytest.fixture()
def project_copy(tmp_path: Path) -> Path:
    source = Path.cwd()
    target = tmp_path / "project"
    target.mkdir()
    for name in ["app", "config", "workspaces", "pyproject.toml"]:
        src = source / name
        dst = target / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _bundle_with_rp(root: Path, story_root: Path, rp):
    """构造带 rp 字段的 ConfigBundle（load_story_config 的等价手写，便于注入自定义 rp）。"""
    config = ConfigLoader(root).load()
    config = remap_config_to_story_root(config, story_root)
    return config.__class__(
        root=config.root,
        pipeline=config.pipeline,
        agents=config.agents,
        models=config.models,
        paths=config.paths,
        recall=config.recall,
        rp=rp,
    )


# ---- rp.yaml 加载 ----

def test_load_rp_config_defaults_when_absent(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    cfg = load_rp_config(story_root)
    assert cfg == DEFAULT_RP_CONFIG
    assert cfg.mode == "immersive"
    assert cfg.dice_source == "gm"
    assert cfg.dice_prompt_on == ()
    assert cfg.gm_runner == "mock"


def test_load_rp_config_parses_trpg_yaml(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    (story_root / "rp.yaml").write_text(
        "mode: trpg\ndice:\n  source: gm\n  prompt_on: [attack, act]\n  notation: 1d20\n  seed: 42\n"
        "gm:\n  persona: 地下城主\n  runner: mock\nvisibility:\n  debug_default: false\n",
        encoding="utf-8",
    )
    cfg = load_rp_config(story_root)
    assert cfg.mode == "trpg"
    assert cfg.dice_source == "gm"
    assert cfg.dice_prompt_on == ("attack", "act")
    assert cfg.dice_notation == "1d20"
    assert cfg.dice_seed == 42
    assert cfg.gm_persona == "地下城主"
    assert cfg.gm_runner == "mock"


def test_load_rp_config_degrades_on_bad_values(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    (story_root / "rp.yaml").write_text(
        "mode: wat\ndice:\n  source: dice\n  prompt_on: notalist\n  seed: abc\n", encoding="utf-8"
    )
    cfg = load_rp_config(story_root)
    # 非法值一律降级到默认，绝不中断回合。
    assert cfg.mode == "immersive"
    assert cfg.dice_source == "gm"
    assert cfg.dice_prompt_on == ()
    assert cfg.dice_seed is None


# ---- immersive：默认路径保持原响应形状（向后兼容） ----

def test_immersive_mode_preserves_response_shape(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = _bundle_with_rp(project_copy, story_root, DEFAULT_RP_CONFIG)
    payload = run_rp_turn(story_root, config, project_copy, "target: 爱音\n\n对爱音说：“在吗”")
    resp = payload["response"]
    assert resp["gm_narration"]
    assert len(resp["character_reactions"]) >= 2
    assert resp["character_reactions"][0]["role"] == "narrator"


def test_immersive_mode_invokes_action_text_dice(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = _bundle_with_rp(project_copy, story_root, DEFAULT_RP_CONFIG)
    payload = run_rp_turn(story_root, config, project_copy, "我掷 1d20 检定能否说服她")
    invocations = payload["response"].get("skill_invocations", [])
    assert any(item["output"]["notation"] == "1d20" for item in invocations)


# ---- trpg：判定 → GM 侧掷骰 → 折进叙述 ----

def test_trpg_mode_emits_roll_instruction_and_deterministic_result(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    rp = load_rp_config(story_root).__class__(
        mode="trpg",
        dice_source="gm",
        dice_prompt_on=("attack", "act"),
        dice_notation="1d20",
        dice_seed=42,
    )
    config = _bundle_with_rp(project_copy, story_root, rp)
    p1 = run_rp_turn(story_root, config, project_copy, "我一剑刺向王弘")
    narration = p1["response"]["gm_narration"]
    assert "1d20" in narration
    assert ("命中" in narration) or ("未命中" in narration)
    invocations = p1["response"].get("skill_invocations", [])
    assert invocations and invocations[0]["output"]["notation"] == "1d20"
    # 同 seed 两次结果完全一致（确定性）。
    p2 = run_rp_turn(story_root, config, project_copy, "我一剑刺向王弘")
    assert invocations[0]["output"]["total"] == p2["response"]["skill_invocations"][0]["output"]["total"]


def test_trpg_mode_player_source_sets_pending(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    rp = load_rp_config(story_root).__class__(
        mode="trpg",
        dice_source="player",
        dice_prompt_on=("attack",),
        dice_notation="1d20",
    )
    config = _bundle_with_rp(project_copy, story_root, rp)
    payload = run_rp_turn(story_root, config, project_copy, "我一剑刺向王弘")
    resp = payload["response"]
    # player 侧不掷骰，只要求玩家掷。
    assert resp.get("skill_invocations") is None or resp.get("skill_invocations") == []
    pending = resp.get("pending")
    assert pending is not None
    assert pending["kind"] == "player_dice"
    assert pending["notation"] == "1d20"
    assert pending["status"] == "awaiting_roll"


def test_trpg_mode_skips_adjudication_when_intent_not_listed(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    rp = load_rp_config(story_root).__class__(
        mode="trpg",
        dice_source="gm",
        dice_prompt_on=("attack",),
        dice_notation="1d20",
    )
    config = _bundle_with_rp(project_copy, story_root, rp)
    # 对话不在 prompt_on 内 → 不判定，行为同 immersive。
    payload = run_rp_turn(story_root, config, project_copy, "对爱音说：“在吗”")
    resp = payload["response"]
    assert resp.get("pending") is None
    assert resp.get("skill_invocations") is None or resp.get("skill_invocations") == []
    assert "1d20" not in resp["gm_narration"]


# ---- per-workspace 隔离 ----

def test_per_workspace_isolation_two_modes(project_copy: Path):
    ws_imm = project_copy / "workspaces" / "mygo_harem_comedy"
    ws_trpg = project_copy / "workspaces" / "jin_dynasty_harem"
    (ws_trpg / "rp.yaml").write_text(
        "mode: trpg\ndice:\n  source: gm\n  prompt_on: [attack]\n  notation: 1d20\n  seed: 7\n",
        encoding="utf-8",
    )
    # 沉浸项目：叙述无掷骰指令。
    imm_payload = run_rp_turn(
        ws_imm,
        _bundle_with_rp(project_copy, ws_imm, DEFAULT_RP_CONFIG),
        project_copy,
        "我一剑刺向王弘",
    )
    assert "1d20" not in imm_payload["response"]["gm_narration"]
    # 跑团项目：叙述含掷骰指令。
    import os

    old = os.getcwd()
    os.chdir(project_copy)
    try:
        _, trpg_config, _ = load_story_config(str(ws_trpg.relative_to(project_copy)))
        assert trpg_config.rp.mode == "trpg"
        trpg_payload = run_rp_turn(ws_trpg, trpg_config, project_copy, "我一剑刺向王弘")
    finally:
        os.chdir(old)
    assert "1d20" in trpg_payload["response"]["gm_narration"]


# ---- gm.runner=llm 显式拒绝（绝不静默联网） ----

def test_gm_runner_llm_raises_not_implemented(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    rp = load_rp_config(story_root).__class__(mode="immersive", gm_runner="llm")
    config = _bundle_with_rp(project_copy, story_root, rp)
    with pytest.raises(NotImplementedError):
        run_rp_turn(story_root, config, project_copy, "对爱音说：“在吗”")


# ---- RP-A7：玩家掷骰 resolve 路径 ----

def test_rp_turn_resolve_player_roll_adjudicates(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    rp = load_rp_config(story_root).__class__(
        mode="trpg",
        dice_source="player",
        dice_prompt_on=("attack",),
        dice_notation="1d20",
    )
    config = _bundle_with_rp(project_copy, story_root, rp)
    # 玩家回传掷骰结果：total=15 → 命中。
    payload = run_rp_turn(
        story_root,
        config,
        project_copy,
        "",
        resolve={"scene_id": "C03S02", "notation": "1d20", "total": 15},
    )
    resp = payload["response"]
    assert resp.get("resolved") is True
    assert "命中" in resp["gm_narration"]
    assert "15" in resp["gm_narration"]
    assert resp.get("pending") is None
    # total=3 → 未命中。
    payload2 = run_rp_turn(
        story_root,
        config,
        project_copy,
        "",
        resolve={"scene_id": "C03S02", "notation": "1d20", "total": 3},
    )
    assert "未命中" in payload2["response"]["gm_narration"]


def test_rp_turn_resolve_does_not_advance_scene(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    rp = load_rp_config(story_root).__class__(mode="trpg", dice_source="player", dice_prompt_on=("attack",))
    config = _bundle_with_rp(project_copy, story_root, rp)
    before = (story_root / "state" / "state.md").read_text(encoding="utf-8")
    run_rp_turn(story_root, config, project_copy, "", resolve={"scene_id": "C99S99", "notation": "1d20", "total": 12})
    after = (story_root / "state" / "state.md").read_text(encoding="utf-8")
    # resolve 路径不推进场景、不写 state。
    assert before == after


# ---- 策略注册表 ----

def test_rp_mode_registry_resolves_known_and_unknown():
    registry = build_rp_mode_registry()
    assert isinstance(registry["immersive"], ImmersiveMode)
    assert isinstance(registry["trpg"], TrpgMode)
    assert resolve_rp_mode("trpg", registry) is registry["trpg"]
    # 未知 mode → fallback immersive，不抛错。
    assert resolve_rp_mode("nonexistent", registry) is registry["immersive"]
    assert resolve_rp_mode(None, registry) is registry["immersive"]
