from __future__ import annotations

import asyncio
from typing import Any

from app.archive import ArchiveManager
from app.config_loader import ConfigBundle, get_agent_config
from app.context_builder import ContextBuilder
from app.file_io import ProjectFileIO
from app.prompt_cache import PromptCache
from app.recall import RecallStore
from app.run_journal import RunJournal, StepRecord
from app.runners.base import AgentRunner, Step
from app.runners.direct_runner import DirectRunner
from app.runners.mock_runner import MockRunner
from app.runners.pi_rpc_runner import PiRpcRunner
from app.runtime_config import load_runtime_config, load_runtime_policies
from app.snapshot import SnapshotBuilder
from app.validators import Validator


REVIEW_GUARD_AGENTS = (
    "character_guard",
    "continuity_guard",
    "style_detail_guard",
)

FINAL_REVIEW_OUTPUTS = {
    "character_guard": "final_character",
    "continuity_guard": "final_logic",
    "style_detail_guard": "final_style_detail",
}


class PipelineRunner:
    """执行文件驱动的小说创作流程。"""

    def __init__(self, config: ConfigBundle, runner_override: str | None = None):
        self.config = config
        self.file_io = ProjectFileIO(config.root)
        self.policies = load_runtime_policies(config.root)
        self.context_builder = ContextBuilder(self.file_io, self.policies.context)
        self.validator = Validator(self.file_io)
        self.recall = RecallStore(config.root, config.recall, self.file_io)
        self.archive = ArchiveManager(config.root, config.paths, self.file_io)
        self.snapshot = SnapshotBuilder(config.root, config.paths, self.file_io)
        self.runtime = None
        self.runner_override = runner_override
        self.journal = RunJournal(self.file_io, self._story_relative(self.policies.resume.journal_dir), self._story_relative(self.policies.resume.checkpoint_dir))
        self.prompt_cache = PromptCache(
            self.file_io,
            self._story_relative(self.policies.cache.prompt_cache_dir),
            enabled=self.policies.cache.enabled,
        )
        self.prompt_snapshot_dir = self._story_relative(self.policies.context.prompt_snapshot_dir)

    async def run_scene(self, scene_id: str, resume: bool = True) -> None:
        steps = self.config.pipeline.get("steps", [])
        if not steps:
            raise ValueError("pipeline.yaml 没有 steps")

        self._prepare_work_files()
        completed_steps = self.journal.completed_step_ids(scene_id) if resume and self.policies.resume.enabled else set()
        self.journal.mark_scene_status(scene_id, "running")
        self._write_checkpoint(scene_id, current_step=None)

        for raw_step in steps:
            step = self._build_step(scene_id, raw_step)
            if step.id in completed_steps:
                continue
            self._write_checkpoint(scene_id, current_step=step.id)
            try:
                await self._run_step(step)
                self.journal.record_step(scene_id, StepRecord(step.id, step.agent, "completed", output_path=step.output_path))
            except Exception as exc:
                self.journal.record_step(scene_id, StepRecord(step.id, step.agent, "failed", output_path=step.output_path, error=str(exc)))
                self.journal.mark_scene_status(scene_id, "failed")
                raise
            if step.agent == "prose_reviser":
                await self.rerun_final_review_guards(scene_id)
        self.journal.mark_scene_status(scene_id, "completed")
        self._write_checkpoint(scene_id, current_step=None)

    async def rerun_final_review_guards(self, scene_id: str) -> None:
        for agent_name in REVIEW_GUARD_AGENTS:
            agent_config = get_agent_config(self.config, agent_name)
            inputs = [path.replace("/work/draft.md", "/work/final.md") for path in agent_config.get("inputs", [])]
            step = Step(
                id=f"rerun_{agent_name}",
                agent=agent_name,
                scene_id=scene_id,
                prompt_path=agent_config.get("prompt", ""),
                output_path=self._final_review_output_path(agent_name),
                inputs=inputs,
                runner=self.runner_override or agent_config.get("runner", "mock"),
                raw={"post_check": True, "final_mode": True},
                preset_path=agent_config.get("preset"),
                modules=list(agent_config.get("modules", [])),
                artifacts=list(agent_config.get("artifacts", [])),
                profile=agent_config.get("profile"),
            )
            await self._run_step(step)
            self.journal.record_step(scene_id, StepRecord(step.id, step.agent, "completed", output_path=step.output_path))

    async def _run_step(self, step: Step) -> None:
        if step.runner == "local_snapshot":
            self.snapshot.write_snapshot(step.scene_id, step.inputs, step.output_path)
            self.validator.validate_output(step.agent, step.output_path)
            return

        if step.runner == "local_recall":
            query = self.recall.default_query_from_files(step.inputs)
            self.recall.write_report(query, step.output_path)
            self.validator.validate_output(step.agent, step.output_path)
            return

        if step.runner == "local_archive":
            self.archive.append_memory_summary(step.scene_id)
            self.archive.archive_scene(step.scene_id)
            self.archive.reset_work()
            return

        built = self.context_builder.build(
            agent_name=step.agent,
            prompt_path=step.prompt_path,
            input_paths=step.inputs,
            scene_id=step.scene_id,
            preset_path=step.preset_path,
            module_paths=step.modules,
            artifacts=step.artifacts,
        )
        self._write_prompt_snapshot(step, built)
        cache_key = self.prompt_cache.make_key(step.agent, step.scene_id, built.full_text)
        cached_result = self.prompt_cache.load(cache_key)
        if cached_result is not None:
            self._write_step_output(step, cached_result)
            self.validator.validate_output(step.agent, step.output_path)
            return

        runner = self._runner_for(step.runner)
        result = await runner.run(step, built.full_text)
        self.prompt_cache.store(cache_key, result)
        self._write_step_output(step, result)
        self.validator.validate_output(step.agent, step.output_path)

    def _final_review_output_path(self, agent_name: str) -> str:
        stem = FINAL_REVIEW_OUTPUTS[agent_name]
        return f"{self.config.paths['work']['reports_dir']}/{stem}.md"

    def _write_step_output(self, step: Step, result: str) -> None:
        artifact_sections = self._parse_artifact_sections(result)
        if artifact_sections:
            for path, content in artifact_sections.items():
                self.file_io.write_text(path, content.strip() + "\n")
            return
        if step.agent in {"statekeeper", "state_manifest_keeper", "state_initializer"} and "---PLAYER_VISIBLE_STATE---" in result:
            state_text, player_text = result.split("---PLAYER_VISIBLE_STATE---", 1)
            self.file_io.write_text(self.config.paths["state"]["main"], state_text.strip() + "\n")
            self.file_io.write_text(self.config.paths["state"]["player_visible"], player_text.strip() + "\n")
            return
        self.file_io.write_text(step.output_path, result.strip() + "\n")

    def _parse_artifact_sections(self, result: str) -> dict[str, str]:
        lines = result.splitlines()
        sections: dict[str, list[str]] = {}
        current_path: str | None = None
        for line in lines:
            if line.startswith("---ARTIFACT:") and line.endswith("---"):
                current_path = line[len("---ARTIFACT:") : -3].strip()
                sections[current_path] = []
                continue
            if current_path is not None:
                sections[current_path].append(line)
        return {path: "\n".join(content).strip() for path, content in sections.items() if content}

    def _build_step(self, scene_id: str, raw_step: dict[str, Any]) -> Step:
        agent_name = raw_step["agent"]
        agent_config = get_agent_config(self.config, agent_name)
        runner_name = self.runner_override or agent_config.get("runner", "mock")
        if agent_config.get("runner") in {"local_snapshot", "local_recall", "local_archive"}:
            runner_name = agent_config["runner"]
        return Step(
            id=raw_step["id"],
            agent=agent_name,
            scene_id=scene_id,
            prompt_path=agent_config.get("prompt", ""),
            output_path=agent_config.get("output", ""),
            inputs=list(agent_config.get("inputs", [])),
            runner=runner_name,
            raw=raw_step,
            preset_path=agent_config.get("preset"),
            modules=list(agent_config.get("modules", [])),
            artifacts=list(agent_config.get("artifacts", [])),
            profile=agent_config.get("profile"),
        )

    def _runner_for(self, runner_name: str) -> AgentRunner:
        if runner_name == "mock":
            return MockRunner()
        if runner_name == "pi_rpc":
            return PiRpcRunner()
        if runner_name == "direct":
            runtime = self.runtime or load_runtime_config(self.config.root)
            self.runtime = runtime
            return DirectRunner(runtime, self.config.models, self.policies.runner, self.policies.recovery)
        raise KeyError(f"未知 runner：{runner_name}")

    def _prepare_work_files(self) -> None:
        work = self.config.paths["work"]
        self.file_io.ensure_dir(work["dir"])
        self.file_io.ensure_dir(work["reports_dir"])
        self.file_io.ensure_dir(self.prompt_snapshot_dir)
        player_input = work.get("player_input")
        if player_input and not self.file_io.exists(player_input):
            self.file_io.write_text(player_input, "# Player Input\n\nmode: novel\n\nNo player input this round.\n")

    def _write_prompt_snapshot(self, step: Step, built) -> None:
        if not self.policies.context.write_trace:
            return
        safe_agent = step.agent.replace("/", "_")
        snapshot_base = f"{self.prompt_snapshot_dir}/{step.scene_id}-{step.id}-{safe_agent}"
        self.file_io.write_text(snapshot_base + ".md", built.full_text.rstrip() + "\n")
        import json

        self.file_io.write_text(snapshot_base + ".trace.json", json.dumps(built.trace, ensure_ascii=False, indent=2) + "\n")

    def _story_relative(self, path: str) -> str:
        project_root = self.config.paths.get("project_root")
        if not project_root:
            return path
        normalized_root = project_root.rstrip("/")
        normalized_path = path.lstrip("/")
        if normalized_path.startswith(normalized_root + "/"):
            return normalized_path
        return f"{normalized_root}/{normalized_path}"

    def _write_checkpoint(self, scene_id: str, current_step: str | None) -> None:
        self.journal.write_checkpoint(
            scene_id,
            {
                "current_step": current_step,
                "state_path": self.config.paths["state"]["main"],
                "player_visible_path": self.config.paths["state"]["player_visible"],
                "recall_index_path": self.config.paths["memory"]["index"],
                "work_dir": self.config.paths["work"]["dir"],
            },
        )


def build_runner(config: ConfigBundle, runner_override: str | None = None) -> PipelineRunner:
    return PipelineRunner(config, runner_override=runner_override)


def run_scene_sync(
    config: ConfigBundle,
    scene_id: str,
    runner_override: str | None = None,
    pipeline_path: str | None = None,
    resume: bool = True,
) -> None:
    effective_config = config
    if pipeline_path:
        pipeline = effective_config.root.joinpath(pipeline_path)
        import yaml

        loaded = yaml.safe_load(pipeline.read_text(encoding="utf-8")) or {}
        effective_config = effective_config.with_pipeline(loaded)
    asyncio.run(PipelineRunner(effective_config, runner_override=runner_override).run_scene(scene_id, resume=resume))


def run_post_final_review_sync(
    config: ConfigBundle,
    scene_id: str,
    runner_override: str | None = None,
) -> None:
    asyncio.run(PipelineRunner(config, runner_override=runner_override).rerun_final_review_guards(scene_id))
