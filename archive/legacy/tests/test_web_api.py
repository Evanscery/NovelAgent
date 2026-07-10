"""app/web 写 API 的 deterministic 测试。

遵循最小 LLM 调用原则：run 测试只用 rp-turn / import（确定性、不调 LLM），
不触发 run-scene 真实写作。文件/工作区/配置 API 取显式 root，无需 chdir。
"""
import shutil
from pathlib import Path

import pytest

from app.web import api_config, api_files, api_novel, api_run, api_workspace
from app.web.paths import PathSafetyError, resolve_workspace, safe_resolve


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


# ---- paths 守卫 ----

def test_safe_resolve_blocks_traversal(project_copy: Path):
    base = project_copy / "workspaces"
    with pytest.raises(PathSafetyError):
        safe_resolve(base, "../config/server.yaml")
    with pytest.raises(PathSafetyError):
        safe_resolve(base, "/etc/passwd")
    # 合法相对路径放行
    ok = safe_resolve(base, "mygo_harem_comedy")
    assert ok.name == "mygo_harem_comedy"


def test_resolve_workspace_rejects_non_workspace(project_copy: Path):
    with pytest.raises(PathSafetyError):
        resolve_workspace(project_copy, "config")


# ---- 工作区 ----

def test_create_and_list_and_delete_workspace(project_copy: Path):
    result = api_workspace.create_workspace(project_copy, "unit_test_story", "测试主题")
    assert result["name"] == "unit_test_story"
    assert (project_copy / "workspaces" / "unit_test_story" / "PROJECT.md").exists()

    names = [item["name"] for item in api_workspace.list_workspaces(project_copy)]
    assert "unit_test_story" in names

    deleted = api_workspace.delete_workspace(project_copy, result["path"])
    assert deleted["deleted"] is True
    assert not (project_copy / "workspaces" / "unit_test_story").exists()


def test_create_workspace_rejects_bad_name_and_duplicate(project_copy: Path):
    with pytest.raises(api_workspace.WorkspaceError):
        api_workspace.create_workspace(project_copy, "../escape", "x")
    with pytest.raises(api_workspace.WorkspaceError):
        api_workspace.create_workspace(project_copy, "", "x")
    with pytest.raises(api_workspace.WorkspaceError):
        api_workspace.create_workspace(project_copy, "mygo_harem_comedy", "dup")


# ---- 文件 CRUD ----

def test_list_read_write_file_roundtrip(project_copy: Path):
    ws = "workspaces/mygo_harem_comedy"
    listing = api_files.list_files(project_copy, ws)
    rels = [f["rel"] for f in listing["files"]]
    assert any(rel.startswith("prompts/") for rel in rels)

    target_rel = "prompts/scene_planner.md"
    read = api_files.read_file(project_copy, ws, target_rel)
    assert read["content"]

    new_content = read["content"] + "\n\n## UNIT TEST APPEND\n"
    saved = api_files.write_file(project_copy, ws, target_rel, new_content)
    assert saved["saved"] is True
    again = api_files.read_file(project_copy, ws, target_rel)
    assert "UNIT TEST APPEND" in again["content"]


def test_write_file_blocks_traversal_and_bad_dir(project_copy: Path):
    ws = "workspaces/mygo_harem_comedy"
    with pytest.raises(PathSafetyError):
        api_files.write_file(project_copy, ws, "../../config/server.yaml", "hacked")
    with pytest.raises(api_files.FileApiError):
        api_files.write_file(project_copy, ws, "work/secret.md", "nope")  # work 非可编辑目录
    with pytest.raises(api_files.FileApiError):
        api_files.write_file(project_copy, ws, "prompts/x.exe", "nope")  # 非文本类型


# ---- 小说阅读（只读，NOVEL-A2）----

def test_novel_list_and_read_chapter(project_copy: Path):
    ws = "workspaces/mygo_harem_comedy"
    idx = api_novel.list_novel(project_copy, ws)
    assert idx["has_novel"] is True
    assert len(idx["chapters"]) >= 1
    first = idx["chapters"][0]
    assert first["number"] == 1
    assert first["title"]
    assert first["char_count"] > 0
    # 场景全本也应存在
    assert any(s["scene_id"].startswith("C01") for s in idx["scenes"])

    chapter = api_novel.read_chapter(project_copy, ws, "1")
    assert chapter["chapter"] == 1
    assert chapter["title"]
    assert chapter["body"]
    assert chapter["char_count"] > 0


def test_novel_read_scene(project_copy: Path):
    ws = "workspaces/mygo_harem_comedy"
    scene = api_novel.read_scene(project_copy, ws, "C01S01")
    assert scene["scene_id"] == "C01S01"
    assert scene["chapter"] == 1
    assert scene["body"]


def test_novel_blocks_traversal(project_copy: Path):
    ws = "workspaces/mygo_harem_comedy"
    # 章节标识拒绝含路径分隔符 / 盘符
    with pytest.raises(api_novel.NovelApiError):
        api_novel.read_chapter(project_copy, ws, "../../config/server.yaml")
    with pytest.raises(api_novel.NovelApiError):
        api_novel.read_scene(project_copy, ws, "C01S01/../../secret")
    # 非法场景 ID
    with pytest.raises(api_novel.NovelApiError):
        api_novel.read_scene(project_copy, ws, "not-a-scene")
    # 不存在的章节返回 400（越界/不存在）
    with pytest.raises(PathSafetyError):
        api_novel.read_chapter(project_copy, ws, "999")


# ---- 配置 ----

def test_config_read_write_whitelist(project_copy: Path):
    read = api_config.read_config(project_copy, "server")
    assert "host" in read["content"]

    saved = api_config.write_config(project_copy, "server", read["content"])
    assert saved["saved"] is True

    with pytest.raises(api_config.ConfigApiError):
        api_config.read_config(project_copy, "secrets")  # 非白名单
    with pytest.raises(api_config.ConfigApiError):
        api_config.write_config(project_copy, "server", "host: [unclosed")  # YAML 非法


# ---- 运行 job 生命周期（仅确定性 rp-turn / import，不调 LLM）----

def test_run_job_rp_turn_lifecycle(project_copy: Path, monkeypatch):
    monkeypatch.chdir(project_copy)
    api_run.clear_jobs()
    job = api_run.start_job(
        project_copy,
        "rp-turn",
        {"story_path": "workspaces/mygo_harem_comedy", "text": "target: 爱音\n\n对爱音说：“在吗”"},
        synchronous=True,
    )
    assert job["status"] == "done"
    fetched = api_run.get_job(job["job_id"])
    assert fetched["status"] == "done"
    assert fetched["result"]["response"]["gm_narration"]


def test_run_job_unknown_kind_rejected(project_copy: Path):
    with pytest.raises(api_run.RunApiError):
        api_run.start_job(project_copy, "nonsense", {}, synchronous=True)


def test_run_job_reports_error_status(project_copy: Path, monkeypatch):
    monkeypatch.chdir(project_copy)
    api_run.clear_jobs()
    job = api_run.start_job(project_copy, "rp-turn", {"story_path": "workspaces/mygo_harem_comedy", "text": ""}, synchronous=True)
    assert job["status"] == "error"
    assert job["error"]


# ---- Wave 1 workbench-novel-flow: 扩写门控哨兵 ----

def test_mock_write_book_no_direct_runner(project_copy: Path, monkeypatch):
    """mock 写作必须 NOT 触发 DirectRunner（chapter_expander 硬编码 DirectRunner，无 runner 透传）。

    做法：monkeypatch ``DirectRunner.__init__`` 让其实例化即抛错。若 mock 路径意外走进
    扩写分支（``run_write_book_sync`` 的 ``if body_chars < 1800`` 块），该测试会立刻失败。
    扩写门控保证 mock 跳过扩写，导出原本（mock 章节刻意短），哨兵保持绿。

    测试准备：scaffold 复制 ``workspaces/`` 字典序首目录作为模板——该目录是已推进到 Chapter 2 的
    ``jin_dynasty_harem``。``cmd_write_book`` 从该状态写 chapter 1 会触发「章节倒退」校验失败
    （这是 scaffold 模板选取的既有行为，不在本 wave 修复范围）。这里把脚手架后的
    ``state.md`` 的 Position 块显式重置为 Chapter 0 / Scene C00S00，使 mock 写作可推进
    Chapter 1；这并不削弱哨兵目的——哨兵检查的是「mock 不实例化 DirectRunner」。
    """
    from app.runners.direct_runner import DirectRunner
    from app.state_tools import set_story_position

    # 创建一个全新的、临时的、未用作 scaffold 模板的工作区。
    ws_name = "zz_sentinel_write_book"
    ws_rel = f"workspaces/{ws_name}"
    try:
        scaffold = api_workspace.create_workspace(project_copy, ws_name, "哨兵主题")
        assert scaffold["name"] == ws_name
        ws_path = project_copy / ws_rel
        assert (ws_path / "PROJECT.md").exists()

        # 把 scaffold 继承的 jin_dynasty_harem 高阶状态重置为可写 chapter 1 的起点。
        state_path = ws_path / "state" / "state.md"
        reset_state = set_story_position(
            state_path.read_text(encoding="utf-8"), chapter=0, scene_id="C00S00"
        )
        state_path.write_text(reset_state, encoding="utf-8", newline="\n")

        # 把 DirectRunner 实例化变成 fail-loud：任何对真实 LLM runner 的调用都会立刻爆。
        original_init = DirectRunner.__init__

        def boom(self, *args, **kwargs):
            raise AssertionError("DirectRunner 不应在 mock 写作路径中被实例化")

        monkeypatch.setattr(DirectRunner, "__init__", boom)

        monkeypatch.chdir(project_copy)
        api_run.clear_jobs()
        job = api_run.start_job(
            project_copy,
            "write-book",
            {"story_path": ws_rel, "chapters": 1, "runner": "mock", "sync": True},
            synchronous=True,
        )
        assert job["status"] == "done", f"job failed: {job.get('error')}\n{job.get('logs')}"

        # 章节文件已导出。
        chapter_path = ws_path / "novels" / "chapter_01.txt"
        assert chapter_path.exists(), f"chapter_01.txt 未生成；logs={job.get('logs')}"
        body = chapter_path.read_text(encoding="utf-8")
        assert body.strip(), "导出的章节正文不应为空"

        # 扩写门控生效：mock 不会进入扩写分支，DirectRunner.__init__ boom 从未被调用。
        # 还原 init 以防后续测试误用。
        monkeypatch.setattr(DirectRunner, "__init__", original_init)
    finally:
        # 清理临工作区，避免 residue。
        target = project_copy / ws_rel
        if target.exists():
            shutil.rmtree(target)


def test_mock_init_story_completes(project_copy: Path, monkeypatch):
    """mock init-story 必须完整完成 bootstrap，5 个关键文件非空且通过 validators。

    哨兵覆盖 Wave 1 todo 1 的 MOCK BOOTSTRAP COMPLETION FIX：arc_planner 的 mock 输出
    必须含 ``Required Events``（写入 current_arc.md），master_outline.md 必须含
    ``Required Beats``，state_initializer 的 mock 输出必须含 state 三件套标题。
    """
    from app.config_loader import ConfigLoader
    from app.file_io import ProjectFileIO
    from app.story_config import remap_config_to_story_root
    from app.validators import Validator

    ws_name = "zz_sentinel_init_story"
    ws_rel = f"workspaces/{ws_name}"
    try:
        monkeypatch.chdir(project_copy)
        api_run.clear_jobs()
        job = api_run.start_job(
            project_copy,
            "init-story",
            {"story_path": ws_rel, "theme": "哨兵题材", "runner": "mock", "sync": True},
            synchronous=True,
        )
        assert job["status"] == "done", f"job failed: {job.get('error')}\n{job.get('logs')}"

        ws_path = project_copy / ws_rel
        # 5 个关键文件全部非空。
        expected_files = [
            "lore/premise.md",
            "lore/characters.md",
            "outline/master_outline.md",
            "outline/current_arc.md",
            "state/state.md",
        ]
        for rel in expected_files:
            p = ws_path / rel
            assert p.exists(), f"{rel} 不存在；logs={job.get('logs')}"
            content = p.read_text(encoding="utf-8").strip()
            assert content, f"{rel} 内容为空"

        # outline 文件含 validator 要求的标题。
        master = (ws_path / "outline" / "master_outline.md").read_text(encoding="utf-8")
        assert "Required Beats" in master, "master_outline.md 缺少 Required Beats"
        arc = (ws_path / "outline" / "current_arc.md").read_text(encoding="utf-8")
        assert "Required Events" in arc, "current_arc.md 缺少 Required Events"

        # state 文件含三件套标题。
        state = (ws_path / "state" / "state.md").read_text(encoding="utf-8")
        for heading in ["# Current State", "## Position", "## Current Situation"]:
            assert heading in state, f"state.md 缺少标题：{heading}"

        # 调用 Validator 逐一校验（与 pipeline 内部一致）。
        config = ConfigLoader(project_copy).load()
        story_root = ws_path.resolve()
        remapped = remap_config_to_story_root(config, story_root)
        file_io = ProjectFileIO(project_copy)
        validator = Validator(file_io)
        agents = remapped.agents["agents"]
        for agent_name in [
            "theme_bootstrapper",
            "cast_designer",
            "worldbook_builder",
            "arc_planner",
            "state_initializer",
        ]:
            output_path = agents[agent_name]["output"]
            validator.validate_output(agent_name, output_path)
    finally:
        target = project_copy / ws_rel
        if target.exists():
            shutil.rmtree(target)
