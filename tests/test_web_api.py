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
