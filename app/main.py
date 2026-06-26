from __future__ import annotations

import argparse
import json
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.archive import ArchiveManager
from app.card_front import build_card_view, load_front_scripts, render_card_view_html, render_front_widgets
from app.card_migration import infer_card_ir, infer_runtime_plan, load_card_payload, materialize_story_from_card, write_json
from app.chapter_expander import iterative_expand_chapter_sync
from app.chapter_tools import chapter_body_from_final_text, chapter_title_from_final_text, count_chinese_chars
from app.config_loader import ConfigLoader
from app.event_runtime import apply_event_to_state, build_runtime_event, dump_event, dump_response
from app.file_io import ProjectFileIO
from app.pipeline import run_post_final_review_sync, run_scene_sync
from app.player_input import dump_player_input, parse_player_input
from app.recall import RecallStore
from app.state_tools import set_story_position, validate_story_progression
from app.story_config import remap_config_to_story_root
from app.story_workspace import StoryWorkspaceManager


def load_config() -> tuple[Path, object]:
    root = Path.cwd().resolve()
    config = ConfigLoader(root).load()
    return root, config


def load_story_config(story_root: str | None) -> tuple[Path, object, Path | None]:
    root, config = load_config()
    if not story_root:
        return root, config, None
    story_path = Path(story_root)
    if not story_path.is_absolute():
        story_path = (root / story_path).resolve()
    config = remap_config_to_story_root(config, story_path)
    if story_path.exists():
        from app.rp_modes import load_rp_config

        config = config.__class__(
            root=config.root,
            pipeline=config.pipeline,
            agents=config.agents,
            models=config.models,
            paths=config.paths,
            recall=config.recall,
            rp=load_rp_config(story_path),
        )
    return root, config, story_path


def cmd_init_db(args: argparse.Namespace) -> None:
    root, config = load_config()
    recall = RecallStore(root, config.recall, ProjectFileIO(root))
    recall.init_db()
    print(f"已初始化 Recall 数据库：{recall.db_path}")


def cmd_index_memory(args: argparse.Namespace) -> None:
    root, config, _ = load_story_config(args.story_root)
    recall = RecallStore(root, config.recall, ProjectFileIO(root))
    count = recall.index_memory()
    print(f"已索引记忆文件：{count} 个")


def cmd_recall(args: argparse.Namespace) -> None:
    root, config, _ = load_story_config(args.story_root)
    file_io = ProjectFileIO(root)
    recall = RecallStore(root, config.recall, file_io)
    output = config.paths["work"]["recall_report"]
    recall.write_report(args.query, output)
    print(f"已写入召回报告：{output}")


def cmd_run_scene(args: argparse.Namespace) -> None:
    _, config, _ = load_story_config(args.story_root)
    run_scene_sync(config, args.scene_id, runner_override=args.runner, pipeline_path=args.pipeline, resume=not args.no_resume)
    print(f"已完成场景流程：{args.scene_id}")


def cmd_archive(args: argparse.Namespace) -> None:
    root, config, _ = load_story_config(args.story_root)
    archive = ArchiveManager(root, config.paths, ProjectFileIO(root))
    archive.append_memory_summary(args.scene_id)
    path = archive.archive_scene(args.scene_id, overwrite=args.overwrite)
    if args.reset_work:
        archive.reset_work()
    print(f"已归档：{path}")


def cmd_reset_work(args: argparse.Namespace) -> None:
    root, config, _ = load_story_config(args.story_root)
    archive = ArchiveManager(root, config.paths, ProjectFileIO(root))
    archive.reset_work()
    print("已清空 work 目录")


def cmd_normalize_memory(args: argparse.Namespace) -> None:
    root, config, _ = load_story_config(args.story_root)
    archive = ArchiveManager(root, config.paths, ProjectFileIO(root))
    result = archive.normalize_memory_files()
    print(json.dumps({"normalized": result}, ensure_ascii=False, indent=2))


def cmd_init_story(args: argparse.Namespace) -> None:
    root, config = load_config()
    manager = StoryWorkspaceManager(root)
    story_root = manager.init_story(args.story_root, args.theme)
    story_config = remap_config_to_story_root(config, story_root)
    run_scene_sync(story_config, "BOOTSTRAP", runner_override=args.runner, pipeline_path="config/pipeline_story_init.yaml")
    print(f"已初始化故事工作区：{story_root}")


def cmd_write_book(args: argparse.Namespace) -> None:
    root, config, story_root = load_story_config(args.story_root)
    if story_root is None:
        raise ValueError("write-book 必须提供 --story-root")
    manager = StoryWorkspaceManager(root)
    file_io = ProjectFileIO(root)
    existing_chapters = sorted((story_root / "novels").glob("chapter_*.txt"))
    start_chapter = len(existing_chapters) + 1

    for chapter in range(start_chapter, args.chapters + 1):
        state_path = file_io.resolve(config.paths["state"]["main"])
        previous_state = state_path.read_text(encoding="utf-8")
        scene_id = f"C{chapter:02d}S01"
        chapter_state = set_story_position(previous_state, chapter=chapter, scene_id=scene_id)
        state_path.write_text(chapter_state, encoding="utf-8", newline="\n")

        archive_dir = story_root / "archive" / scene_id
        if archive_dir.exists():
            raise FileExistsError(f"目标章节归档已存在，请先确认后再继续：{archive_dir}")

        try:
            run_scene_sync(config, scene_id, runner_override=args.runner, pipeline_path="config/pipeline_chapter.yaml")
        except Exception as exc:
            raise RuntimeError(f"第 {chapter} 章主流程失败：{exc}") from exc

        current_state = state_path.read_text(encoding="utf-8")
        validate_story_progression(previous_state, current_state)

        archived_scene_dir = story_root / "archive" / scene_id
        archived_final = archived_scene_dir / "final.md"
        if not archived_final.exists():
            raise FileNotFoundError(f"未找到归档后的最终正文：{archived_final}")

        final_text = archived_final.read_text(encoding="utf-8")
        title = chapter_title_from_final_text(final_text, chapter)
        body = chapter_body_from_final_text(final_text)
        body_chars = count_chinese_chars(body)

        if body_chars < 1800:
            outline_text = (archived_scene_dir / "outline_final.md").read_text(encoding="utf-8")
            snapshot_text = (archived_scene_dir / "run_snapshot.md").read_text(encoding="utf-8")
            characters_text = file_io.read_text(str(story_root / "lore" / "characters.md"))
            style_text = file_io.read_text(str(story_root / "modules" / "style" / "default.md"))

            try:
                final_text = iterative_expand_chapter_sync(
                    config=config,
                    scene_id=scene_id,
                    chapter_markdown=final_text,
                    outline_text=outline_text,
                    snapshot_text=snapshot_text,
                    characters_text=characters_text,
                    style_text=style_text,
                    min_chars=args.min_words,
                    counter=count_chinese_chars,
                    max_passes=2,
                )
            except Exception as exc:
                raise RuntimeError(f"第 {chapter} 章扩写失败：{exc}") from exc

            title = chapter_title_from_final_text(final_text, chapter)
            body = chapter_body_from_final_text(final_text)
            archived_final.write_text(final_text, encoding="utf-8", newline="\n")
            file_io.write_text(config.paths["work"]["final"], final_text.strip() + "\n")
            run_post_final_review_sync(config, scene_id, runner_override=args.runner)

        exported = manager.export_chapter_txt(story_root, chapter, title, body)
        print(f"已导出章节：{exported}")

        recall = RecallStore(root, config.recall, file_io)
        recall.index_memory()

    print(f"已完成全书写作：{story_root}")


def cmd_evaluate_book(args: argparse.Namespace) -> None:
    _, config, story_root = load_story_config(args.story_root)
    if story_root is None:
        raise ValueError("evaluate-book 必须提供 --story-root")
    run_scene_sync(config, "EVALUATE", runner_override=args.runner, pipeline_path="config/pipeline_evaluate.yaml")
    print(f"已完成写作评估：{story_root}")


def run_rp_turn(story_root: Path, config, root: Path, raw_text: str, resolve: dict | None = None) -> dict[str, object]:
    file_io = ProjectFileIO(root)
    parsed = parse_player_input(raw_text)
    dump_player_input(parsed, story_root / "work" / "player_input.json")

    state_path = file_io.resolve(config.paths["state"]["main"])
    visible_path = file_io.resolve(config.paths["state"]["player_visible"])
    state_text = state_path.read_text(encoding="utf-8")
    visible_text = visible_path.read_text(encoding="utf-8")

    # RP 模式分派（RP-A1/A2）：默认 immersive = 原 layered_turn_response 行为。
    from app.rp_modes import (
        DEFAULT_RP_CONFIG,
        build_rp_context,
        build_rp_mode_registry,
        resolve_gm_runner,
        resolve_player_roll,
        resolve_rp_mode,
    )

    rp_config = getattr(config, "rp", None)
    if rp_config is None:
        rp_config = DEFAULT_RP_CONFIG
    # 先解析 GM runner：gm.runner=llm 显式拒绝（绝不静默联网），其余沿用 mock。
    resolve_gm_runner(rp_config)
    ctx = build_rp_context(story_root, rp_config, config)

    # RP-A7：玩家掷骰 resolve 路径——不推进场景，不要求重掷，直接判定。
    if isinstance(resolve, dict) and resolve.get("total") is not None:
        rp_response = resolve_player_roll(ctx, resolve)
        dump_response(rp_response.response, story_root / "work" / "last_response.json")
        return {
            "parsed_input": parsed.to_dict() if raw_text.strip() else {},
            "event": {},
            "response": rp_response.response,
            "state": state_text,
            "player_visible": visible_text,
        }

    event = build_runtime_event(parsed)

    # 状态推进与叙述解耦：先跑 state reducer 得到 next_scene_id，再交给 RP 模式 narrate。
    from app.event_catalog import resolve_event_catalog_entry
    from app.event_reducers import build_reducer_registry

    state_reducers, visible_reducers = build_reducer_registry()
    entry = resolve_event_catalog_entry(event.intent, event.catalog_key)
    state_text, next_scene = state_reducers[entry.state_reducer](state_text, event)

    registry = build_rp_mode_registry()
    mode = resolve_rp_mode(rp_config.mode, registry)
    rp_response = mode.narrate(event, state_text, visible_text, ctx, next_scene)

    # 可见投影仍按原 visible reducer 投影到 player_visible（保持响应形状兼容）。
    visible_text = visible_reducers[entry.visible_reducer](visible_text, event, rp_response.response)

    state_path.write_text(state_text, encoding="utf-8", newline="\n")
    visible_path.write_text(visible_text, encoding="utf-8", newline="\n")
    dump_event(event, story_root / "work" / "last_event.json")
    dump_response(rp_response.response, story_root / "work" / "last_response.json")
    return {
        "parsed_input": parsed.to_dict(),
        "event": event.to_dict(),
        "response": rp_response.response,
        "state": state_text,
        "player_visible": visible_text,
    }


def _apply_gm_skills_for_turn(config, parsed) -> list[dict[str, object]]:
    """已迁移到 ImmersiveMode._invoke_action_text_dice；保留薄壳兼容旧测试导入。"""
    from app.skills import apply_gm_skills, build_default_registry, resolve_agent_skills

    agents = config.agents.get("agents", {}) if hasattr(config, "agents") else {}
    gm_config = agents.get("gm") or agents.get("game_master") or {}
    allowed = resolve_agent_skills(gm_config)
    if not allowed:
        return []
    registry = build_default_registry()
    action_text = " ".join(part for part in [parsed.action, parsed.raw_text] if part)
    return apply_gm_skills(action_text, registry, allowed)


def cmd_rp_turn(args: argparse.Namespace) -> None:
    root, config, story_root = load_story_config(args.story_root)
    if story_root is None:
        raise ValueError("rp-turn 必须提供 --story-root")
    player_input_path = story_root / "work" / "player_input.md"
    raw_text = args.text if args.text is not None else player_input_path.read_text(encoding="utf-8")
    payload = run_rp_turn(story_root, config, root, raw_text)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run_import_card(story_root: Path, input_path: str | Path) -> dict[str, str]:
    payload = load_card_payload(input_path)
    card_ir = infer_card_ir(payload)
    runtime_plan = infer_runtime_plan(card_ir)
    return materialize_story_from_card(story_root, card_ir, runtime_plan)


def run_import_any(story_root: Path, input_path: str | Path) -> dict[str, object]:
    """G3：通用导入分发——酒馆卡走专用管线，其它来源走通用管线（可降级）。"""
    from app.importers import run_import

    return run_import(story_root, input_path)


def cmd_import(args: argparse.Namespace) -> None:
    _, _, story_root = load_story_config(args.story_root)
    if story_root is None:
        raise ValueError("import 必须提供 --story-root")
    result = run_import_any(story_root, args.input)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_import_card(args: argparse.Namespace) -> None:
    _, _, story_root = load_story_config(args.story_root)
    if story_root is None:
        raise ValueError("import-card 必须提供 --story-root")
    paths = run_import_card(story_root, args.input)
    print(json.dumps(paths, ensure_ascii=False, indent=2))


def collect_story_summary(root: Path) -> list[dict[str, str]]:
    stories = []
    base = root / "workspaces"
    if base.exists():
        for story in sorted(path for path in base.iterdir() if path.is_dir()):
            stories.append({"name": story.name, "path": str(story.relative_to(root)).replace("\\", "/")})
    return stories


def load_story_payload(root: Path, rel_path: str) -> dict[str, object]:
    target = (root / rel_path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"story not found: {rel_path}")
    return {
        "project": _safe_read(target / "PROJECT.md"),
        "state": _safe_read(target / "state" / "state.md"),
        "player_visible": _safe_read(target / "state" / "player_visible.md"),
        "summaries": _safe_read(target / "memory" / "summaries.md"),
        "index": _safe_read(target / "memory" / "index.md"),
        "chapters": sorted(path.name for path in (target / "novels").glob("chapter_*.txt")),
        "archives": sorted(path.name for path in (target / "archive").glob("C*")),
        "evaluation": _safe_read(target / "evaluation" / "final_report.md"),
        "journal": _safe_read(target / "work" / "run_journal" / "latest.json"),
        "last_response": _safe_read(target / "work" / "last_response.json"),
        "card_ir": _safe_read(target / "data" / "card_ir.json"),
        "runtime_plan": _safe_read(target / "data" / "runtime_plan.json"),
    }


def load_card_view_payload(root: Path, rel_path: str) -> dict[str, object]:
    """G1：返回前端「角色卡」聚合视图。

    - card_view：从 card_ir 提炼的基础卡片字段（安全转义后可直接渲染）。
    - card_html：基础卡片 HTML。
    - widgets：对 state/player_visible/last_response 应用 ST 风格正则前端脚本后的渲染结果。
    前端逻辑对齐酒馆：findRegex 抓变量，replaceString(HTML+JS) 显示。
    """
    target = (root / rel_path).resolve()
    if not target.exists():
        raise FileNotFoundError(f"story not found: {rel_path}")

    card_ir_raw = _safe_read(target / "data" / "card_ir.json")
    card_ir: dict[str, object] = {}
    if card_ir_raw.strip():
        try:
            card_ir = json.loads(card_ir_raw)
        except json.JSONDecodeError:
            card_ir = {}
    card_view = build_card_view(card_ir)

    scripts = load_front_scripts(target / "front")
    state_text = _safe_read(target / "state" / "player_visible.md")
    last_response = _safe_read(target / "work" / "last_response.json")
    widget_source = "\n\n".join(part for part in [state_text, last_response] if part.strip())
    widgets = render_front_widgets(widget_source, scripts) if scripts else {
        "html": "",
        "scripts": [],
        "total_matches": 0,
        "source_chars": len(widget_source),
    }

    return {
        "card_view": card_view,
        "card_html": render_card_view_html(card_view),
        "widgets": widgets,
        "front_script_count": len(scripts),
    }


def cmd_serve_ui(args: argparse.Namespace) -> None:
    from app.web import build_handler

    root = Path.cwd().resolve()
    handler = build_handler(root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"UI 已启动：http://{args.host}:{args.port}")
    server.serve_forever()


def cmd_serve(args: argparse.Namespace) -> None:
    """G4：一键启动，读取 config/server.yaml，按配置拉起后端 API + 前端 Web。"""
    from app.server_config import load_server_config
    from app.web import build_handler
    from app.web.static import has_spa

    root = Path.cwd().resolve()
    cfg = load_server_config(root, args.config)
    if args.host is not None:
        cfg = replace_server_host(cfg, args.host)
    if args.port is not None:
        cfg = replace_server_port(cfg, args.port)

    handler = build_handler(root, cfg)
    server = ThreadingHTTPServer((cfg.host, cfg.port), handler)
    url = f"http://{cfg.host}:{cfg.port}"
    # 浏览器无法访问 0.0.0.0 / :: 通配地址，自动打开时回退到本地回环。
    browse_host = "127.0.0.1" if cfg.host in ("0.0.0.0", "::", "") else cfg.host
    browse_url = f"http://{browse_host}:{cfg.port}"
    print(f"NovelAgent 服务已启动：{url}")
    print(f"  监听: {cfg.host}:{cfg.port} | CORS: {cfg.allow_origins or '关闭'} | IP 白名单: {cfg.ip_whitelist or '不限制'}")
    if has_spa(root, cfg.static_dir):
        print("  前端: web/dist (已构建的 SPA)")
    else:
        print("  前端: 内联回退页（运行 `cd web && npm install && npm run build` 启用完整前端）")
    if cfg.open_browser:
        print(f"  正在打开浏览器：{browse_url}")
        import threading
        import webbrowser

        # 延迟到服务开始监听后再打开，避免浏览器先于 serve_forever 抢访问。
        threading.Timer(0.6, lambda: _safe_open_browser(webbrowser, browse_url)).start()
    server.serve_forever()


def _safe_open_browser(webbrowser_mod, url: str) -> None:
    try:
        webbrowser_mod.open(url)
    except Exception:
        pass


def replace_server_host(cfg, host: str):
    from dataclasses import replace

    return replace(cfg, host=host)


def replace_server_port(cfg, port: int):
    from dataclasses import replace

    return replace(cfg, port=port)


def _safe_read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _render_index() -> str:
    return """<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <title>NovelAgent Minimal UI</title>
  <style>
    body { font-family: sans-serif; margin: 0; display: grid; grid-template-columns: 280px 1fr; height: 100vh; }
    aside { border-right: 1px solid #ddd; padding: 12px; overflow: auto; }
    main { padding: 12px; overflow: auto; }
    button { margin: 4px 0; width: 100%; }
    textarea { width: 100%; min-height: 120px; }
    pre { white-space: pre-wrap; background: #f6f6f6; padding: 8px; }
    .section { margin-bottom: 16px; }
  </style>
</head>
<body>
  <aside>
    <h3>Stories</h3>
    <div id=\"stories\"></div>
  </aside>
  <main>
    <h2 id=\"story-title\">选择一个 story</h2>
    <div class=\"section\">
      <h3>RP 输入</h3>
      <textarea id=\"rp-input\" placeholder=\"输入玩家行动...\"></textarea>
      <button onclick=\"sendTurn()\">提交 RP Turn</button>
    </div>
    <div class=\"section\"><h3>角色卡</h3><div id=\"card-view\"></div></div>
    <div class=\"section\"><h3>前端组件（正则渲染）</h3><div id=\"card-widgets\"></div><pre id=\"card-widgets-info\"></pre></div>
    <div class=\"section\"><h3>PROJECT</h3><pre id=\"project\"></pre></div>
    <div class=\"section\"><h3>State</h3><pre id=\"state\"></pre></div>
    <div class=\"section\"><h3>Player Visible</h3><pre id=\"visible\"></pre></div>
    <div class=\"section\"><h3>Last Response</h3><pre id=\"last_response\"></pre></div>
    <div class=\"section\"><h3>Summaries</h3><pre id=\"summaries\"></pre></div>
    <div class=\"section\"><h3>Index</h3><pre id=\"index\"></pre></div>
    <div class=\"section\"><h3>Evaluation</h3><pre id=\"evaluation\"></pre></div>
    <div class=\"section\"><h3>Latest Journal</h3><pre id=\"journal\"></pre></div>
    <div class=\"section\"><h3>Card IR</h3><pre id=\"card_ir\"></pre></div>
    <div class=\"section\"><h3>Runtime Plan</h3><pre id=\"runtime_plan\"></pre></div>
    <div class=\"section\"><h3>Chapters</h3><pre id=\"chapters\"></pre></div>
    <div class=\"section\"><h3>Archives</h3><pre id=\"archives\"></pre></div>
  </main>
<script>
let currentStory = null;
async function loadStories() {
  const stories = await fetch('/api/stories').then(r => r.json());
  const root = document.getElementById('stories');
  root.innerHTML = '';
  stories.forEach(story => {
    const btn = document.createElement('button');
    btn.textContent = story.name;
    btn.onclick = () => loadStory(story.path, story.name);
    root.appendChild(btn);
  });
}
async function loadStory(path, name) {
  currentStory = path;
  document.getElementById('story-title').textContent = name;
  const data = await fetch('/api/story?path=' + encodeURIComponent(path)).then(r => r.json());
  document.getElementById('project').textContent = data.project || '';
  document.getElementById('state').textContent = data.state || '';
  document.getElementById('visible').textContent = data.player_visible || '';
  document.getElementById('last_response').textContent = data.last_response || '';
  document.getElementById('summaries').textContent = data.summaries || '';
  document.getElementById('index').textContent = data.index || '';
  document.getElementById('evaluation').textContent = data.evaluation || '';
  document.getElementById('journal').textContent = data.journal || '';
  document.getElementById('card_ir').textContent = data.card_ir || '';
  document.getElementById('runtime_plan').textContent = data.runtime_plan || '';
  document.getElementById('chapters').textContent = (data.chapters || []).join('\n');
  document.getElementById('archives').textContent = (data.archives || []).join('\n');
  await loadCard(path);
}
async function loadCard(path) {
  try {
    const card = await fetch('/api/card?path=' + encodeURIComponent(path)).then(r => r.json());
    document.getElementById('card-view').innerHTML = card.card_html || '';
    const widgets = card.widgets || {};
    document.getElementById('card-widgets').innerHTML = widgets.html || '';
    const info = '前端脚本数: ' + (card.front_script_count || 0) + '，命中: ' + (widgets.total_matches || 0);
    document.getElementById('card-widgets-info').textContent = info;
  } catch (e) {
    document.getElementById('card-view').textContent = '';
    document.getElementById('card-widgets').innerHTML = '';
    document.getElementById('card-widgets-info').textContent = '';
  }
}
async function sendTurn() {
  if (!currentStory) return alert('请先选择 story');
  const text = document.getElementById('rp-input').value;
  await fetch('/api/rp-turn', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({story_path: currentStory, text})});
  await loadStory(currentStory, document.getElementById('story-title').textContent);
}
loadStories();
</script>
</body>
</html>"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说多 Agent MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="初始化 Recall 数据库")
    init_db.set_defaults(func=cmd_init_db)

    index_memory = subparsers.add_parser("index-memory", help="索引 memory 目录")
    index_memory.add_argument("--story-root", default=None, help="故事工作区根目录")
    index_memory.set_defaults(func=cmd_index_memory)

    recall = subparsers.add_parser("recall", help="检索历史记忆并写入 recall_report")
    recall.add_argument("query", help="检索关键词")
    recall.add_argument("--story-root", default=None, help="故事工作区根目录")
    recall.set_defaults(func=cmd_recall)

    run_scene = subparsers.add_parser("run-scene", help="运行完整场景流程")
    run_scene.add_argument("scene_id", help="场景 ID，例如 C01S01")
    run_scene.add_argument("--runner", choices=["mock", "pi_rpc", "direct"], default=None, help="覆盖配置中的运行器")
    run_scene.add_argument("--story-root", default=None, help="故事工作区根目录")
    run_scene.add_argument("--pipeline", default=None, help="覆盖默认 pipeline 文件")
    run_scene.add_argument("--no-resume", action="store_true", help="禁用 resume，强制完整重跑")
    run_scene.set_defaults(func=cmd_run_scene)

    archive = subparsers.add_parser("archive", help="归档当前 work 目录")
    archive.add_argument("scene_id", help="场景 ID，例如 C01S01")
    archive.add_argument("--overwrite", action="store_true", help="允许覆盖已有归档")
    archive.add_argument("--reset-work", action="store_true", help="归档后清空 work")
    archive.add_argument("--story-root", default=None, help="故事工作区根目录")
    archive.set_defaults(func=cmd_archive)

    reset_work = subparsers.add_parser("reset-work", help="清空 work 目录")
    reset_work.add_argument("--story-root", default=None, help="故事工作区根目录")
    reset_work.set_defaults(func=cmd_reset_work)

    normalize_memory = subparsers.add_parser("normalize-memory", help="清理并归一化历史 summaries/index 格式")
    normalize_memory.add_argument("--story-root", required=True, help="故事工作区根目录")
    normalize_memory.set_defaults(func=cmd_normalize_memory)

    init_story = subparsers.add_parser("init-story", help="初始化独立故事工作区并生成基础设定")
    init_story.add_argument("--story-root", required=True, help="故事工作区根目录")
    init_story.add_argument("--theme", required=True, help="故事主题")
    init_story.add_argument("--runner", choices=["mock", "pi_rpc", "direct"], default="direct", help="初始化时使用的运行器")
    init_story.set_defaults(func=cmd_init_story)

    write_book = subparsers.add_parser("write-book", help="为指定故事写出多章正文并导出 txt")
    write_book.add_argument("--story-root", required=True, help="故事工作区根目录")
    write_book.add_argument("--chapters", type=int, default=3, help="章节数量")
    write_book.add_argument("--min-words", type=int, default=3000, help="每章最少中文字符数")
    write_book.add_argument("--runner", choices=["mock", "pi_rpc", "direct"], default="direct", help="写作时使用的运行器")
    write_book.set_defaults(func=cmd_write_book)

    evaluate_book = subparsers.add_parser("evaluate-book", help="评估一本书的写作效果")
    evaluate_book.add_argument("--story-root", required=True, help="故事工作区根目录")
    evaluate_book.add_argument("--runner", choices=["mock", "pi_rpc", "direct"], default="direct", help="评估时使用的运行器")
    evaluate_book.set_defaults(func=cmd_evaluate_book)

    rp_turn = subparsers.add_parser("rp-turn", help="解析玩家输入并执行一次事件驱动的 RP turn")
    rp_turn.add_argument("--story-root", required=True, help="故事工作区根目录")
    rp_turn.add_argument("--text", default=None, help="直接提供玩家输入；不提供则读取 work/player_input.md")
    rp_turn.set_defaults(func=cmd_rp_turn)

    import_card = subparsers.add_parser("import-card", help="导入角色卡并生成 card_ir/runtime_plan 以及基础 story 文件")
    import_card.add_argument("--input", required=True, help="角色卡输入文件（json/txt 等）")
    import_card.add_argument("--story-root", required=True, help="故事工作区根目录")
    import_card.set_defaults(func=cmd_import_card)

    import_any = subparsers.add_parser("import", help="通用导入：酒馆卡走专用管线，剧本/设定/小说走通用管线（可降级）")
    import_any.add_argument("--input", required=True, help="输入文件（json/txt/md 等）")
    import_any.add_argument("--story-root", required=True, help="故事工作区根目录")
    import_any.set_defaults(func=cmd_import)

    serve_ui = subparsers.add_parser("serve-ui", help="启动最小操作前端")
    serve_ui.add_argument("--host", default="127.0.0.1", help="监听地址")
    serve_ui.add_argument("--port", type=int, default=8766, help="监听端口")
    serve_ui.set_defaults(func=cmd_serve_ui)

    serve = subparsers.add_parser("serve", help="一键启动后端 API + 前端 Web（读取 config/server.yaml）")
    serve.add_argument("--config", default=None, help="server 配置文件，默认 config/server.yaml")
    serve.add_argument("--host", default=None, help="覆盖配置中的监听地址")
    serve.add_argument("--port", type=int, default=None, help="覆盖配置中的监听端口")
    serve.set_defaults(func=cmd_serve)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
