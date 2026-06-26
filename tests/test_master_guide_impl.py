import json
import shutil
from pathlib import Path

import pytest

from app.archive import ArchiveManager
from app.card_front import (
    FrontScript,
    apply_front_script,
    build_card_view,
    parse_front_script,
    render_front_widgets,
)
from app.card_migration import infer_card_ir, infer_runtime_plan, materialize_story_from_card
from app.config_loader import ConfigLoader
from app.context_builder import ContextBuilder
from app.event_catalog import resolve_event_catalog_entry
from app.event_runtime import apply_event_to_state, build_runtime_event, build_rp_response
from app.file_io import ProjectFileIO
from app.importers import build_generic_card_ir, detect_source_kind, run_import
from app.main import collect_story_summary, load_card_view_payload, load_story_payload, run_import_card, run_rp_turn
from app.pipeline import run_post_final_review_sync, run_scene_sync
from app.player_input import parse_player_input
from app.recall import RecallStore
from app.server_config import load_server_config, parse_server_config

from app.run_journal import RunJournal, StepRecord
from app.runtime_config import ContextPolicy, load_runtime_policies
from app.state_tools import parse_story_position, set_story_position, validate_story_progression
from app.story_config import remap_config_to_story_root
from app.story_workspace import StoryWorkspaceManager


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


def load_story_bundle(root: Path, story_root: Path):
    config = ConfigLoader(root).load()
    return remap_config_to_story_root(config, story_root)


def test_init_story_uses_clean_memory(project_copy: Path):
    manager = StoryWorkspaceManager(project_copy)
    story_root = manager.init_story("stories/test_story", "测试主题")

    summaries = (story_root / "memory" / "summaries.md").read_text(encoding="utf-8")
    index_text = (story_root / "memory" / "index.md").read_text(encoding="utf-8")
    structured = json.loads((story_root / "memory" / "scenes.json").read_text(encoding="utf-8"))
    fulltext_files = list((story_root / "memory" / "fulltext").glob("*.md"))

    assert "项目刚初始化" in summaries
    assert "Scene C01S00" in index_text
    assert structured["schema_version"] == 1
    assert structured["entries"][0]["scene_id"] == "C01S00"
    assert fulltext_files == []


def test_mock_pipeline_writes_final_review_reports(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)

    run_scene_sync(config, "C04S01", runner_override="mock", pipeline_path="config/pipeline_chapter.yaml")

    archive_dir = story_root / "archive" / "C04S01"
    assert (archive_dir / "reports" / "final_character.md").exists()
    assert (archive_dir / "reports" / "final_logic.md").exists()
    assert (archive_dir / "reports" / "final_style_detail.md").exists()


def test_post_final_review_can_rerun_after_manual_final_update(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)

    work_dir = story_root / "work"
    reports_dir = work_dir / "reports"
    work_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "final.md").write_text("# Final\n\n手动扩写后的正文。\n", encoding="utf-8")
    (work_dir / "outline_final.md").write_text("# Final Outline of This Round\n\n## Required Beats\n1. beat\n", encoding="utf-8")
    (story_root / "lore" / "characters.md").write_text("# Characters\n", encoding="utf-8")
    (story_root / "lore" / "worldbook.md").write_text("# Worldbook\n", encoding="utf-8")
    (story_root / "lore" / "style.md").write_text("# Style\n", encoding="utf-8")
    (work_dir / "run_snapshot.md").write_text("# Frozen Run Input Snapshot\n\n## Scene\n- Scene ID: C99S01\n", encoding="utf-8")
    (story_root / "memory" / "index.md").write_text("# Memory Index\n", encoding="utf-8")

    run_post_final_review_sync(config, "C99S01", runner_override="mock")

    assert (reports_dir / "final_character.md").exists()
    assert (reports_dir / "final_logic.md").exists()
    assert (reports_dir / "final_style_detail.md").exists()


def test_state_tools_validate_progression():
    previous = """# Current State

## Position

- Chapter: 1
- Scene: C01S01
- Time: t1
- Location: L1
- POV: P1

## Current Situation

A
"""
    current = set_story_position(previous, chapter=2, scene_id="C02S01")

    parsed = parse_story_position(current)
    assert parsed.chapter == 2
    assert parsed.scene_id == "C02S01"
    validate_story_progression(previous, current)

    with pytest.raises(ValueError):
        validate_story_progression(current, current)


def test_archive_manager_normalizes_legacy_memory_files(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    file_io = ProjectFileIO(project_copy)
    archive = ArchiveManager(project_copy, config.paths, file_io)

    summaries_path = story_root / "memory" / "summaries.md"
    index_path = story_root / "memory" / "index.md"
    summaries_path.write_text(
        "# Summaries\n\n## C01S00\n\n项目刚初始化。\n\n## C02S01\n\n- Title: Old\n- Length: 10 中文字符\n- Summary: old\n\n# Final 噪声块\n",
        encoding="utf-8",
    )
    index_path.write_text(
        "# Memory Index\n\n## Scene C02S01\n\n- Title: Old\n- Status: archived\n\n## Threads\n\n- noise\n",
        encoding="utf-8",
    )

    result = archive.normalize_memory_files()
    summaries = summaries_path.read_text(encoding="utf-8")
    index_text = index_path.read_text(encoding="utf-8")

    assert result["summaries"] >= 2
    assert result["index"] >= 1
    assert "噪声块" not in summaries
    assert "## Threads" not in index_text
    assert summaries.count("## C02S01") == 1
    assert index_text.count("## Scene C02S01") == 1
    structured = json.loads((story_root / "memory" / "scenes.json").read_text(encoding="utf-8"))
    assert {item["scene_id"] for item in structured["entries"]} >= {"C01S00", "C02S01"}



def test_archive_manager_writes_structured_memory_primary_store(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    file_io = ProjectFileIO(project_copy)
    archive = ArchiveManager(project_copy, config.paths, file_io)

    work_dir = story_root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "final.md").write_text("# 第十章 测试\n\n这是用于结构化记忆主存的测试正文。", encoding="utf-8")

    archive.append_memory_summary("C10S01")

    structured_path = story_root / "memory" / "scenes.json"
    payload = json.loads(structured_path.read_text(encoding="utf-8"))
    entries = {item["scene_id"]: item for item in payload["entries"]}
    assert payload["schema_version"] == 1
    assert entries["C10S01"]["title"] == "第十章 测试"
    assert "结构化记忆主存" in entries["C10S01"]["summary"]
    # Markdown 仍作为投影视图，保持现有前端/召回兼容。
    assert "## C10S01" in (story_root / "memory" / "summaries.md").read_text(encoding="utf-8")
    assert "## Scene C10S01" in (story_root / "memory" / "index.md").read_text(encoding="utf-8")


def test_mock_pipeline_archives_scene(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)

    run_scene_sync(config, "C05S01", runner_override="mock", pipeline_path="config/pipeline_chapter.yaml")
    assert (story_root / "archive" / "C05S01" / "final.md").exists()


def test_recall_indexes_story_memory(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    recall = RecallStore(project_copy, config.recall, ProjectFileIO(project_copy))

    count = recall.index_memory()
    assert count >= 2
    results = recall.search("结城凛")
    assert isinstance(results, list)


def test_runtime_policies_load(project_copy: Path):
    policies = load_runtime_policies(project_copy)
    assert policies.runner.max_retries == 3
    assert policies.recovery.allow_guard_degrade is True
    assert policies.resume.enabled is True
    assert policies.cache.enabled is True
    assert policies.context.prompt_snapshot_dir == "work/prompt_snapshots"
    assert policies.context.write_trace is True
    assert policies.context.default_max_chars == 12000
    assert policies.context.agent_max_chars["prose_writer"] == 9000
    assert policies.context.section_strategies["context"] == "truncate"


def test_run_journal_and_checkpoint(project_copy: Path):
    file_io = ProjectFileIO(project_copy)
    journal = RunJournal(file_io, "workspaces/mygo_harem_comedy/work/run_journal", "workspaces/mygo_harem_comedy/work/checkpoints")
    journal.mark_scene_status("C11S01", "running")
    journal.record_step("C11S01", StepRecord("s1", "scene_planner", "completed", output_path="x.md"))
    checkpoint = journal.write_checkpoint("C11S01", {"current_step": "s2"})

    loaded = journal.load("C11S01")
    cp = journal.load_checkpoint("C11S01")
    assert loaded["status"] == "running"
    assert loaded["steps"][0]["step_id"] == "s1"
    assert checkpoint.exists()
    assert cp["current_step"] == "s2"


def test_context_builder_emits_trace(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    builder = ContextBuilder(ProjectFileIO(project_copy), policy=ContextPolicy())

    built = builder.build(
        agent_name="scene_planner",
        prompt_path=config.agents["agents"]["scene_planner"]["prompt"],
        input_paths=config.agents["agents"]["scene_planner"]["inputs"],
        scene_id="C01S01",
        preset_path=config.agents["agents"]["scene_planner"].get("preset"),
        module_paths=list(config.agents["agents"]["scene_planner"].get("modules", [])),
        artifacts=list(config.agents["agents"]["scene_planner"].get("artifacts", [])),
    )

    assert built.trace["agent"] == "scene_planner"
    assert built.trace["scene_id"] == "C01S01"
    assert built.trace["stages"] == ["collect", "prioritize", "schedule", "render", "trace"]
    assert built.trace["section_count"] >= 4
    assert any(section["kind"] == "module" for section in built.trace["sections"])
    assert built.trace["budget"]["max_chars"] == 12000
    assert any(item["collector"] == "snapshot_collector" for item in built.trace["collectors"])
    assert "# Agent Task Prompt" in built.full_text


def test_pipeline_writes_prompt_snapshot_trace(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)

    run_scene_sync(config, "C07S01", runner_override="mock", pipeline_path="config/pipeline_smoke_generate.yaml")

    snapshot_dir = story_root / "work" / "prompt_snapshots"
    trace_files = list(snapshot_dir.glob("C07S01-*.trace.json"))
    markdown_files = list(snapshot_dir.glob("C07S01-*.md"))
    assert trace_files
    assert markdown_files

    trace = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert trace["scene_id"] == "C07S01"
    assert trace["stages"] == ["collect", "prioritize", "schedule", "render", "trace"]
    assert "budget" in trace
    assert "decisions" in trace["budget"]


def test_context_builder_applies_budget_truncation(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    policy = ContextPolicy(default_max_chars=220, agent_max_chars={"scene_planner": 220})
    builder = ContextBuilder(ProjectFileIO(project_copy), policy=policy)

    built = builder.build(
        agent_name="scene_planner",
        prompt_path=config.agents["agents"]["scene_planner"]["prompt"],
        input_paths=config.agents["agents"]["scene_planner"]["inputs"],
        scene_id="C01S01",
        preset_path=config.agents["agents"]["scene_planner"].get("preset"),
        module_paths=list(config.agents["agents"]["scene_planner"].get("modules", [])),
        artifacts=list(config.agents["agents"]["scene_planner"].get("artifacts", [])),
    )

    decisions = {item["key"]: item for item in built.trace["budget"]["decisions"]}
    assert built.trace["budget"]["max_chars"] == 220
    assert any(item["decision"] in {"truncate", "drop", "compress"} for item in decisions.values())
    assert (
        "[TRUNCATED for context budget]" in built.full_text
        or "[COMPRESSED for context budget]" in built.full_text
        or any(item["decision"] == "drop" for item in decisions.values())
    )


def test_context_builder_exposes_collectors_summary(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    policy = ContextPolicy(default_max_chars=260, agent_max_chars={"scene_planner": 260})
    builder = ContextBuilder(ProjectFileIO(project_copy), policy=policy)

    built = builder.build(
        agent_name="scene_planner",
        prompt_path=config.agents["agents"]["scene_planner"]["prompt"],
        input_paths=config.agents["agents"]["scene_planner"]["inputs"],
        scene_id="C01S01",
        preset_path=config.agents["agents"]["scene_planner"].get("preset"),
        module_paths=list(config.agents["agents"]["scene_planner"].get("modules", [])),
        artifacts=list(config.agents["agents"]["scene_planner"].get("artifacts", [])),
    )

    collectors = {item["collector"]: item for item in built.trace["collectors"]}
    assert "snapshot_collector" in collectors
    assert "recall_collector" in collectors
    assert collectors["snapshot_collector"]["bucket"] == "survival"
    assert any("compress" in item["strategies"] for item in collectors.values())


def test_event_catalog_resolves_intents():
    assert resolve_event_catalog_entry("dialogue").key == "dialogue_turn"
    assert resolve_event_catalog_entry("inspect").key == "inspect_turn"
    assert resolve_event_catalog_entry("move").key == "move_turn"
    assert resolve_event_catalog_entry("act").key == "act_turn"
    # 未知 intent 降级到 fallback
    assert resolve_event_catalog_entry("unknown_intent").key == "fallback_turn"
    # catalog_key 显式优先
    assert resolve_event_catalog_entry("dialogue", "move_turn").key == "move_turn"


def test_player_input_parsing_and_event_runtime():
    parsed = parse_player_input('mode: rp\ntarget: 素世\n\n对素世说：“我们谈谈。”然后向前一步。')
    assert parsed.intent in {"dialogue", "act"}
    event = build_runtime_event(parsed)
    assert event.catalog_key in {"dialogue_turn", "act_turn"}
    state = """# Current State

## Position

- Chapter: 1
- Scene: C01S01
- Time: t1
- Location: L1
- POV: P1

## Current Situation

A

## Open Threads

- T001: old

## Last Scene Result

- old
"""
    visible = """# Player Visible State

## What the Player / POV Character Knows

- old

## Available Leads

- T001

## Hidden Information

none
"""
    result = apply_event_to_state(state, visible, event)
    assert "C01S02" in result.state_text
    assert "我们谈谈" in result.player_visible_text
    assert result.response["character_reactions"]


def test_card_ir_and_runtime_plan():
    payload = {
        "name": "测试角色卡",
        "description": "她有好感系统，也有任务线。",
        "scenario": "如果玩家触发秘密，会进入隐藏剧情。",
        "first_mes": "你好。",
    }
    card_ir = infer_card_ir(payload)
    runtime_plan = infer_runtime_plan(card_ir)
    assert card_ir["card_name"] == "测试角色卡"
    assert runtime_plan["recommended_mode"] == "rp"
    assert runtime_plan["evented_runtime"] is True


def test_card_ir_supports_st_v2_data_envelope():
    payload = {
        "spec": "chara_card_v2",
        "data": {
            "name": "薇拉",
            "description": "她有好感系统。",
            "scenario": "如果触发秘密则进入隐藏线。",
            "first_mes": "嗨。",
            "alternate_greetings": ["早安。", "晚安。"],
            "character_book": {
                "entries": [
                    {"content": "世界规则：魔法需要代价。"},
                    {"content": "禁忌：不可提及旧王。"},
                ]
            },
        },
    }
    card_ir = infer_card_ir(payload)
    runtime_plan = infer_runtime_plan(card_ir)
    assert card_ir["card_name"] == "薇拉"
    assert card_ir["prompt_hints"]["alternate_greetings"] == ["早安。", "晚安。"]
    assert any("魔法需要代价" in rule for rule in card_ir["world_rules"])
    assert runtime_plan["recommended_mode"] == "rp"


def test_resume_skips_completed_steps(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    run_scene_sync(config, "C06S01", runner_override="mock", pipeline_path="config/pipeline_chapter.yaml")

    journal_path = story_root / "work" / "run_journal" / "C06S01.json"
    assert journal_path.exists()
    before = json.loads(journal_path.read_text(encoding="utf-8"))
    run_scene_sync(config, "C06S01", runner_override="mock", pipeline_path="config/pipeline_chapter.yaml", resume=True)
    after = json.loads(journal_path.read_text(encoding="utf-8"))
    assert before["status"] == "completed"
    assert after["status"] == "completed"
    assert len(after["steps"]) >= len(before["steps"])


def test_build_rp_response_layers():
    parsed = parse_player_input('target: 灯\n\n对灯说：“跟我来。”')
    event = build_runtime_event(parsed)
    response = build_rp_response(event, "C01S02")
    assert response["gm_narration"]
    assert len(response["character_reactions"]) >= 2


def test_materialize_story_from_card(tmp_path: Path):
    story_root = tmp_path / "story"
    card_ir = infer_card_ir({"name": "卡", "description": "朋友关系", "scenario": "如果触发秘密", "first_mes": "你好"})
    runtime_plan = infer_runtime_plan(card_ir)
    paths = materialize_story_from_card(story_root, card_ir, runtime_plan)
    assert Path(paths["card_ir"]).exists()
    assert Path(paths["runtime_plan"]).exists()
    assert Path(paths["state"]).exists()
    assert "运行模式" in Path(paths["state"]).read_text(encoding="utf-8")


def test_run_import_card_materializes_workspace(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    card_file = project_copy / "sample_card.json"
    card_file.write_text(json.dumps({"name": "导入卡", "description": "有好感系统", "scenario": "如果触发秘密"}, ensure_ascii=False), encoding="utf-8")
    paths = run_import_card(story_root, card_file)
    assert Path(paths["card_ir"]).exists()
    assert Path(paths["state"]).exists()


def test_run_rp_turn_and_ui_payload(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    payload = run_rp_turn(story_root, config, project_copy, 'target: 爱音\n\n对爱音说：“先听我解释。”')
    assert payload["response"]["gm_narration"]
    story_data = load_story_payload(project_copy, "workspaces/mygo_harem_comedy")
    assert "last_response" in story_data
    stories = collect_story_summary(project_copy)
    assert any(item["name"] == "mygo_harem_comedy" for item in stories)


def test_player_input_normalizes_malformed_target():
    # 模拟 live 验收中的畸形输入：字面 \n 与反引号 n 混入
    parsed = parse_player_input('target: 爱音`n`n对爱音说："先听我解释。"')
    assert parsed.target == "爱音"
    assert parsed.dialogue == "先听我解释。"
    assert len(parsed.target) <= 16


def test_player_input_target_is_clamped():
    parsed = parse_player_input("对一个非常非常非常非常非常非常长的名字说：“喂”")
    assert len(parsed.target) <= 16


def test_card_front_script_substitutes_dollar_groups():
    # 对齐酒馆正则前端：findRegex 抓变量，replaceString 用 $1..$N 替换
    payload = {
        "scriptName": "hp-bar",
        "findRegex": r"\[HP\|(.*?)\|(.*?)\]",
        "replaceString": "<b>$1</b>/<b>$2</b>",
    }
    script = parse_front_script(payload, source_path="hp.json")
    assert isinstance(script, FrontScript)
    rendered, matched = apply_front_script("血量 [HP|30|100] 结束", script)
    assert matched == 1
    assert "<b>30</b>/<b>100</b>" in rendered


def test_card_front_handles_double_digit_groups():
    # $12 不应被 $1 截断
    payload = {
        "scriptName": "many-groups",
        "findRegex": r"\[(.)\|(.)\|(.)\|(.)\|(.)\|(.)\|(.)\|(.)\|(.)\|(.)\|(.)\|(.)\]",
        "replaceString": "g12=$12 g1=$1",
    }
    script = parse_front_script(payload, source_path="m.json")
    rendered, matched = apply_front_script("[a|b|c|d|e|f|g|h|i|j|k|l]", script)
    assert matched == 1
    assert "g12=l" in rendered
    assert "g1=a" in rendered


def test_card_front_renders_st_example_script():
    payload = json.loads(Path("docs/st-char-front.json").read_text(encoding="utf-8-sig"))
    script = parse_front_script(payload, source_path="docs/st-char-front.json")
    assert script is not None
    sample = (
        "<ui-enemy>[名称|蜘蛛女王][等级|Lv.12 精英 (数量: 3)]"
        "[HP|600|800|75][MP|120|200|60][护甲|铁壳]"
        "[属性|力:18, 敏:14, 体:20, 智:9, 感:11, 魅:7]"
        "[特性|剧毒][技能|吐丝][状态|愤怒][背景|盘踞在洞穴深处。]</ui-enemy>"
    )
    rendered, matched = apply_front_script(sample, script)
    assert matched == 1
    assert "蜘蛛女王" in rendered
    assert "<details" in rendered


def test_build_card_view_from_card_ir():
    card_ir = infer_card_ir({
        "name": "薇拉",
        "description": "冷静的剑士。",
        "scenario": "如果触发秘密则进入隐藏线。",
        "first_mes": "你好。",
        "alternate_greetings": ["早安。"],
    })
    view = build_card_view(card_ir)
    assert view["name"] == "薇拉"
    assert "冷静的剑士" in view["persona"]
    assert view["opening"] == "你好。"
    assert view["alternate_greetings"] == ["早安。"]


def test_load_card_view_payload_uses_front_scripts(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    card_file = project_copy / "card.json"
    card_file.write_text(json.dumps({"name": "导入卡", "description": "有好感系统", "scenario": "如果触发秘密"}, ensure_ascii=False), encoding="utf-8")
    run_import_card(story_root, card_file)

    front_dir = story_root / "front"
    front_dir.mkdir(parents=True, exist_ok=True)
    (front_dir / "lead.json").write_text(
        json.dumps({
            "scriptName": "lead-badge",
            "findRegex": r"EVT-(\w+)",
            "replaceString": "<span class='badge'>$1</span>",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = load_card_view_payload(project_copy, "workspaces/mygo_harem_comedy")
    assert payload["card_view"]["name"] == "导入卡"
    assert payload["front_script_count"] == 1
    assert "card-view" in payload["card_html"]
    assert isinstance(payload["widgets"]["scripts"], list)


def test_card_front_escapes_card_ir_fields():
    card_ir = infer_card_ir({"name": "<script>x</script>", "description": "安全测试", "first_mes": "hi"})
    view = build_card_view(card_ir)
    from app.card_front import render_card_view_html

    html_out = render_card_view_html(view)
    assert "<script>x</script>" not in html_out
    assert "&lt;script&gt;" in html_out


def test_server_config_defaults_and_yaml(project_copy: Path):
    # 默认配置（仓库内置 config/server.yaml）
    cfg = load_server_config(project_copy)
    assert cfg.host == "127.0.0.1"
    # 端口由 config/server.yaml 决定（用户当前设定为 8766，与 .env / start 一致）。
    assert cfg.port == 8766
    # 一键启动应自动打开浏览器（known_issue #1）。
    assert cfg.open_browser is True


def test_server_config_parses_whitelist_and_cors():
    cfg = parse_server_config({
        "server": {
            "host": "0.0.0.0",
            "port": 9000,
            "open_browser": True,
            "allow_origins": ["http://localhost:5173"],
            "ip_whitelist": ["127.0.0.1", "10.0.0.5"],
        }
    })
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.open_browser is True
    # CORS
    assert cfg.cors_origin_for("http://localhost:5173") == "http://localhost:5173"
    assert cfg.cors_origin_for("http://evil.example") is None
    # IP 白名单
    assert cfg.is_ip_allowed("127.0.0.1") is True
    assert cfg.is_ip_allowed("8.8.8.8") is False


def test_server_config_empty_whitelist_allows_all():
    cfg = parse_server_config({"server": {"ip_whitelist": []}})
    assert cfg.is_ip_allowed("1.2.3.4") is True
    # 空 allow_origins => 不加 CORS 头
    assert cfg.cors_origin_for("http://anything") is None


def test_server_config_wildcard_cors():
    cfg = parse_server_config({"server": {"allow_origins": ["*"]}})
    assert cfg.cors_origin_for(None) == "*"
    assert cfg.cors_origin_for("http://x") == "*"


def test_dice_roll_skill_is_seed_deterministic():
    from app.skills import build_default_registry

    registry = build_default_registry()
    r1 = registry.invoke("dice_roll", {"notation": "3d6+2", "seed": 42})
    r2 = registry.invoke("dice_roll", {"notation": "3d6+2", "seed": 42})
    assert r1.ok and r2.ok
    assert r1.output == r2.output
    assert r1.output["notation"] == "3d6+2"
    assert len(r1.output["rolls"]) == 3
    assert r1.output["total"] == sum(r1.output["rolls"]) + 2


def test_dice_roll_skill_validates_and_supports_sides():
    from app.skills import build_default_registry

    registry = build_default_registry()
    bad = registry.invoke("dice_roll", {"notation": "garbage"})
    assert bad.ok is False
    by_sides = registry.invoke("dice_roll", {"sides": 100, "seed": 1})
    assert by_sides.ok
    assert 1 <= by_sides.output["total"] <= 100


def test_skill_registry_reports_unknown_skill():
    from app.skills import build_default_registry

    registry = build_default_registry()
    assert "dice_roll" in registry.names()
    result = registry.invoke("nonexistent")
    assert result.ok is False


def test_resolve_agent_skills_reads_config(project_copy: Path):
    from app.skills import resolve_agent_skills

    config = ConfigLoader(project_copy).load()
    gm = config.agents["agents"].get("gm", {})
    assert "dice_roll" in resolve_agent_skills(gm)


def test_apply_gm_skills_detects_dice_in_action():
    from app.skills import apply_gm_skills, build_default_registry

    registry = build_default_registry()
    invocations = apply_gm_skills("我尝试攻击，掷 1d100 判定", registry, ["dice_roll"], seed=7)
    assert len(invocations) == 1
    assert invocations[0]["output"]["notation"] == "1d100"
    # 未授予技能则不触发
    none = apply_gm_skills("掷 1d100", registry, [], seed=7)
    assert none == []


def test_run_rp_turn_invokes_gm_dice_skill(project_copy: Path):
    story_root = project_copy / "workspaces" / "mygo_harem_comedy"
    config = load_story_bundle(project_copy, story_root)
    payload = run_rp_turn(story_root, config, project_copy, "target: 爱音\n\n我掷 1d20 检定能否说服她")
    assert payload["response"]["gm_narration"]
    invocations = payload["response"].get("skill_invocations", [])
    assert any(item["output"]["notation"] == "1d20" for item in invocations)


def test_import_detects_tavern_card(tmp_path: Path):
    card = tmp_path / "card.json"
    card.write_text(json.dumps({"spec": "chara_card_v2", "data": {"name": "薇拉", "first_mes": "嗨", "description": "剑士"}}, ensure_ascii=False), encoding="utf-8")
    payload = json.loads(card.read_text(encoding="utf-8"))
    assert detect_source_kind(card, payload) == "tavern_card"


def test_import_detects_screenplay_and_novel(tmp_path: Path):
    screen = tmp_path / "play.txt"
    screen.write_text("场景一\n爱音：你来了。\n素世：嗯。\n灯：我们走吧。\n", encoding="utf-8")
    assert detect_source_kind(screen) == "screenplay"

    novel = tmp_path / "novel.txt"
    novel.write_text("第一章 开端\n\n" + "她走在长长的走廊上，思绪万千。" * 12 + "\n\n" + "窗外的雨下个不停，仿佛要把整座城市淹没。" * 12, encoding="utf-8")
    assert detect_source_kind(novel) == "novel"


def test_generic_import_builds_card_ir_for_screenplay(tmp_path: Path):
    play = tmp_path / "play.md"
    play.write_text("# 雨夜剧\n\n爱音：先听我解释。\n素世：我不想听。\n\n- 规则：天黑后不能外出\n", encoding="utf-8")
    payload = play.read_text(encoding="utf-8")
    card_ir = build_generic_card_ir(play, payload, "screenplay")
    assert card_ir["card_name"] == "雨夜剧"
    assert "爱音" in card_ir["prompt_hints"]["characters"]
    assert any("天黑后不能外出" in rule for rule in card_ir["world_rules"])


def test_run_import_generic_pipeline_materializes(tmp_path: Path):
    story_root = tmp_path / "story"
    setting = tmp_path / "world.md"
    setting.write_text("# 蒸汽王国\n\n一个由齿轮驱动的国度。\n\n- 规则：禁止使用魔法\n", encoding="utf-8")
    result = run_import(story_root, setting)
    assert result["pipeline"] == "generic"
    assert result["source_kind"] in {"setting", "novel", "screenplay"}
    assert Path(result["paths"]["card_ir"]).exists()
    assert Path(result["paths"]["state"]).exists()


def test_run_import_tavern_pipeline_materializes(tmp_path: Path):
    story_root = tmp_path / "story"
    card = tmp_path / "card.json"
    card.write_text(json.dumps({"name": "导入卡", "description": "有好感系统", "scenario": "如果触发秘密", "first_mes": "你好"}, ensure_ascii=False), encoding="utf-8")
    result = run_import(story_root, card)
    assert result["pipeline"] == "tavern"
    assert result["source_kind"] == "tavern_card"
    assert Path(result["paths"]["card_ir"]).exists()
