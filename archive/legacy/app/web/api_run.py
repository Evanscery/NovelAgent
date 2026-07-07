"""运行 API：后台执行 run-scene / rp-turn / import / write-book，并轮询 job 状态。

测试与默认行为遵循「最小 LLM 调用」原则：``run-scene`` / ``write-book`` 默认 runner=mock，
真实 runner 必须由调用方显式指定。rp-turn / import 本身是确定性、不调 LLM。
"""
from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_JOBS: dict[str, "RunJob"] = {}
_LOCK = threading.Lock()

VALID_KINDS = ("run-scene", "rp-turn", "import", "write-book", "init-story", "evaluate-book")


@dataclass
class RunJob:
    job_id: str
    kind: str
    status: str = "pending"  # pending | running | done | error
    result: Any = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "logs": self.logs,
        }


class RunApiError(ValueError):
    """运行参数非法。"""


def _build_worker(root: Path, kind: str, params: dict[str, Any]) -> Callable[[RunJob], Any]:
    """根据 kind 返回一个无参 worker（闭包捕获参数）。延迟导入避免循环依赖。"""

    def worker(job: RunJob) -> Any:
        from app.main import (
            load_story_config,
            run_evaluate_book_sync,
            run_import_any,
            run_init_story_sync,
            run_rp_turn,
            run_write_book_sync,
        )
        from app.pipeline import run_scene_sync

        story_path = params.get("story_path") or params.get("story_root")
        if kind == "run-scene":
            scene_id = params.get("scene_id")
            if not scene_id:
                raise RunApiError("scene_id required")
            runner = params.get("runner", "mock")  # 默认 mock，不接真实 LLM
            _, config, story_root = load_story_config(story_path)
            if story_root is None or not story_root.exists():
                raise RunApiError("story not found")
            job.logs.append(f"run-scene {scene_id} runner={runner}")
            run_scene_sync(config, scene_id, runner_override=runner)
            return {"scene_id": scene_id, "runner": runner}
        if kind == "rp-turn":
            text = params.get("text", "")
            if not isinstance(text, str) or not text.strip():
                raise RunApiError("text required")
            root_cfg, config, story_root = load_story_config(story_path)
            if story_root is None or not story_root.exists():
                raise RunApiError("story not found")
            return run_rp_turn(story_root, config, root_cfg, text)
        if kind == "import":
            input_path = params.get("input")
            if not input_path:
                raise RunApiError("input required")
            _, _, story_root = load_story_config(story_path)
            if story_root is None:
                raise RunApiError("story_root required")
            return run_import_any(story_root, input_path)
        if kind == "init-story":
            # init-story 的 story_path 是「待创建的工作区路径」，不是已存在的故事目录。
            if not story_path:
                raise RunApiError("story_path required")
            theme = params.get("theme", "")
            runner = params.get("runner", "mock")
            story_root_path = run_init_story_sync(
                root, story_path, theme, runner, log=job.logs.append
            )
            return {"story_root": str(story_root_path), "runner": runner}
        if kind == "write-book":
            _, config, story_root = load_story_config(story_path)
            if story_root is None or not story_root.exists():
                raise RunApiError("story not found")
            chapters = int(params.get("chapters", 3))
            min_words = int(params.get("min_words", 3000))
            runner = params.get("runner", "mock")
            return run_write_book_sync(
                root,
                config,
                story_root,
                chapters,
                min_words,
                runner,
                log=job.logs.append,
            )
        if kind == "evaluate-book":
            _, config, story_root = load_story_config(story_path)
            if story_root is None or not story_root.exists():
                raise RunApiError("story not found")
            runner = params.get("runner", "mock")
            return run_evaluate_book_sync(
                config, story_root, runner, log=job.logs.append
            )
        raise RunApiError(f"unknown kind: {kind}")

    return worker


def start_job(root: Path | str, kind: str, params: dict[str, Any], *, synchronous: bool = False) -> dict[str, Any]:
    """创建并启动一个后台 job，返回 job 概要（含 job_id）。

    ``synchronous=True``（测试用）会在当前线程内跑完，便于 deterministic 断言。
    """
    if kind not in VALID_KINDS:
        raise RunApiError(f"unknown kind: {kind}")
    root_path = Path(root).resolve()
    job_id = uuid.uuid4().hex[:12]
    job = RunJob(job_id=job_id, kind=kind)
    with _LOCK:
        _JOBS[job_id] = job
    worker = _build_worker(root_path, kind, params or {})

    def run() -> None:
        job.status = "running"
        try:
            job.result = worker(job)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - 需把任意失败回报给前端
            job.status = "error"
            job.error = str(exc)
            job.logs.append(traceback.format_exc().splitlines()[-1])

    if synchronous:
        run()
    else:
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
    return job.to_dict()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
    return job.to_dict() if job else None


def clear_jobs() -> None:
    """测试辅助：清空 job 表。"""
    with _LOCK:
        _JOBS.clear()
