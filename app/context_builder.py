from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from app.file_io import ProjectFileIO
from app.prompt_modules import PromptModule, PromptModuleLoader
from app.project_paths import rewrite_legacy_project_paths
from app.runtime_config import ContextPolicy


@dataclass(frozen=True)
class CollectorRule:
    name: str
    bucket: str
    priority: int
    strategy: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class ContextSection:
    key: str
    kind: str
    content: str
    priority: int
    strategy: str = "keep"
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BuiltContext:
    prompt: str
    modules: str
    context: str
    full_text: str
    trace: dict[str, Any]


class ContextBuilder:
    """按 Collect → Prioritize → Schedule → Render → Trace 组装 Agent 上下文。"""

    def __init__(self, file_io: ProjectFileIO, policy: ContextPolicy | None = None):
        self.file_io = file_io
        self.module_loader = PromptModuleLoader(file_io)
        self.policy = policy or ContextPolicy()

    def build(
        self,
        agent_name: str,
        prompt_path: str,
        input_paths: Iterable[str],
        scene_id: str,
        preset_path: str | None = None,
        module_paths: list[str] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> BuiltContext:
        prompt = rewrite_legacy_project_paths(self.file_io.read_text(prompt_path), prompt_path)
        collected = self._collect_sections(
            agent_name=agent_name,
            prompt=prompt,
            prompt_path=prompt_path,
            input_paths=list(input_paths),
            scene_id=scene_id,
            preset_path=preset_path,
            module_paths=module_paths or [],
            artifacts=artifacts or [],
        )
        prioritized = self._prioritize_sections(collected)
        scheduled, budget_trace = self._schedule_sections(agent_name, prioritized)
        full_text = self._render_sections(scheduled)
        modules = self._render_modules(scheduled)
        context = self._render_context(scheduled)
        trace = self._build_trace(agent_name, scene_id, scheduled, budget_trace, full_text)
        return BuiltContext(prompt=prompt, modules=modules, context=context, full_text=full_text, trace=trace)

    def _collect_sections(
        self,
        agent_name: str,
        prompt: str,
        prompt_path: str,
        input_paths: list[str],
        scene_id: str,
        preset_path: str | None,
        module_paths: list[str],
        artifacts: list[dict[str, Any]],
    ) -> list[ContextSection]:
        sections: list[ContextSection] = []
        sections.append(
            ContextSection(
                key="task_prompt",
                kind="prompt",
                content="# Agent Task Prompt\n\n" + prompt.strip(),
                priority=10,
                strategy=self._strategy_for_kind("prompt"),
                source_path=prompt_path,
                metadata={"collector": "task_prompt"},
            )
        )

        for index, module in enumerate(self._load_modules(agent_name, preset_path, module_paths), start=1):
            sections.append(
                ContextSection(
                    key=f"module_{index}",
                    kind="module",
                    content=f"# Prompt Module: {module.title}\n\n来源：`{module.path}`\n\n{module.content}",
                    priority=20,
                    strategy=self._strategy_for_kind("module"),
                    source_path=module.path,
                    metadata={"title": module.title, "collector": "prompt_module_loader"},
                )
            )

        artifact_contract = self._build_artifacts(artifacts)
        if artifact_contract.strip():
            sections.append(
                ContextSection(
                    key="artifacts",
                    kind="artifacts",
                    content=artifact_contract,
                    priority=30,
                    strategy=self._strategy_for_kind("artifacts"),
                    metadata={"count": len(artifacts), "collector": "artifact_contract_builder"},
                )
            )

        sections.extend(self._collect_context_sections(input_paths))
        sections.append(
            ContextSection(
                key="task_metadata",
                kind="task",
                content=f"## 本轮任务\n\n- Agent: {agent_name}\n- Scene ID: {scene_id}\n",
                priority=50,
                strategy=self._strategy_for_kind("task"),
                metadata={"agent": agent_name, "scene_id": scene_id, "collector": "task_metadata"},
            )
        )
        return sections

    def _collect_context_sections(self, input_paths: list[str]) -> list[ContextSection]:
        sections: list[ContextSection] = []
        for index, path in enumerate(input_paths, start=1):
            content = rewrite_legacy_project_paths(self.file_io.read_text(path), path).strip()
            rule = self._match_collector(path)
            sections.append(
                ContextSection(
                    key=f"context_{index}",
                    kind="context",
                    content=f"## 文件：{path}\n\n{content}\n",
                    priority=rule.priority,
                    strategy=rule.strategy,
                    source_path=path,
                    metadata={"bucket": rule.bucket, "collector": rule.name},
                )
            )
        return sections

    def _load_modules(self, agent_name: str, preset_path: str | None, module_paths: list[str]) -> list[PromptModule]:
        return self.module_loader.load_for_agent(agent_name, preset_path, module_paths)

    def _prioritize_sections(self, sections: list[ContextSection]) -> list[ContextSection]:
        prioritized = sorted(enumerate(sections), key=lambda item: (item[1].priority, item[0]))
        return [section for _, section in prioritized]

    def _schedule_sections(self, agent_name: str, sections: list[ContextSection]) -> tuple[list[ContextSection], dict[str, Any]]:
        max_chars = self._max_chars_for_agent(agent_name)
        before_chars = sum(len(section.content) for section in sections if section.content.strip())
        if max_chars <= 0:
            return sections, {
                "max_chars": max_chars,
                "before_chars": before_chars,
                "after_chars": before_chars,
                "remaining_chars": 0,
                "decisions": [],
            }

        scheduled: list[ContextSection] = []
        decisions: list[dict[str, Any]] = []
        used_chars = 0

        for section in sections:
            original_len = len(section.content)
            content = section.content
            decision = "keep"
            reason = "within budget"

            if not content.strip():
                scheduled.append(section)
                decisions.append(self._decision(section, decision, reason, original_len, len(content), used_chars, max_chars))
                continue

            remaining = max_chars - used_chars
            if remaining >= original_len:
                used_chars += original_len
            elif section.strategy == "keep":
                decision = "keep_over_budget"
                reason = "required section kept despite budget"
                used_chars += original_len
            elif section.strategy == "drop":
                content = ""
                decision = "drop"
                reason = "dropped to respect budget"
            elif section.strategy == "truncate":
                if remaining <= 0:
                    content = ""
                    decision = "drop"
                    reason = "no budget remained"
                else:
                    content = self._truncate_content(content, remaining)
                    if content:
                        decision = "truncate"
                        reason = f"truncated to {len(content)} chars"
                        used_chars += len(content)
                    else:
                        decision = "drop"
                        reason = "remaining budget too small"
            elif section.strategy == "compress":
                if remaining <= 0:
                    content = ""
                    decision = "drop"
                    reason = "no budget remained"
                else:
                    content = self._compress_content(content, remaining)
                    if content:
                        decision = "compress"
                        reason = f"compressed to {len(content)} chars"
                        used_chars += len(content)
                    else:
                        decision = "drop"
                        reason = "remaining budget too small"
            else:
                decision = "keep_over_budget"
                reason = f"unknown strategy {section.strategy}; kept"
                used_chars += original_len

            scheduled_section = replace(section, content=content)
            scheduled.append(scheduled_section)
            decisions.append(self._decision(section, decision, reason, original_len, len(content), used_chars, max_chars))

        after_chars = sum(len(section.content) for section in scheduled if section.content.strip())
        return scheduled, {
            "max_chars": max_chars,
            "before_chars": before_chars,
            "after_chars": after_chars,
            "remaining_chars": max_chars - after_chars,
            "decisions": decisions,
        }

    def _decision(
        self,
        section: ContextSection,
        decision: str,
        reason: str,
        before_chars: int,
        after_chars: int,
        used_chars: int,
        max_chars: int,
    ) -> dict[str, Any]:
        return {
            "key": section.key,
            "kind": section.kind,
            "source_path": section.source_path,
            "priority": section.priority,
            "strategy": section.strategy,
            "decision": decision,
            "reason": reason,
            "before_chars": before_chars,
            "after_chars": after_chars,
            "used_chars": used_chars,
            "budget_remaining": max_chars - used_chars,
        }

    def _render_sections(self, sections: list[ContextSection]) -> str:
        blocks: list[str] = []
        context_blocks: list[str] = []
        for section in sections:
            if not section.content.strip():
                continue
            if section.kind == "context":
                context_blocks.append(section.content.rstrip())
                continue
            if context_blocks:
                blocks.append("# 上下文\n\n" + "\n---\n\n".join(context_blocks))
                context_blocks = []
            blocks.append(section.content.rstrip())
        if context_blocks:
            blocks.append("# 上下文\n\n" + "\n---\n\n".join(context_blocks))
        return "\n\n---\n\n".join(block for block in blocks if block.strip())

    def _render_modules(self, sections: list[ContextSection]) -> str:
        return "\n\n---\n\n".join(section.content.rstrip() for section in sections if section.kind == "module" and section.content.strip())

    def _render_context(self, sections: list[ContextSection]) -> str:
        return "\n---\n\n".join(section.content.rstrip() for section in sections if section.kind == "context" and section.content.strip())

    def _build_trace(
        self,
        agent_name: str,
        scene_id: str,
        sections: list[ContextSection],
        budget_trace: dict[str, Any],
        full_text: str,
    ) -> dict[str, Any]:
        decisions = {item["key"]: item for item in budget_trace.get("decisions", [])}
        return {
            "agent": agent_name,
            "scene_id": scene_id,
            "stages": ["collect", "prioritize", "schedule", "render", "trace"],
            "section_count": len(sections),
            "char_count": len(full_text),
            "budget": budget_trace,
            "collectors": self._build_collectors_summary(sections),
            "sections": [
                {
                    "key": section.key,
                    "kind": section.kind,
                    "priority": section.priority,
                    "strategy": section.strategy,
                    "source_path": section.source_path,
                    "char_count": len(section.content),
                    "metadata": section.metadata,
                    "schedule": decisions.get(section.key, {}),
                }
                for section in sections
            ],
        }

    def _build_collectors_summary(self, sections: list[ContextSection]) -> list[dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        for section in sections:
            collector = str(section.metadata.get("collector", "unknown"))
            bucket = str(section.metadata.get("bucket", section.kind))
            entry = summary.setdefault(
                collector,
                {
                    "collector": collector,
                    "bucket": bucket,
                    "section_count": 0,
                    "char_count": 0,
                    "strategies": set(),
                },
            )
            entry["section_count"] += 1
            entry["char_count"] += len(section.content)
            entry["strategies"].add(section.strategy)
        return [
            {
                "collector": value["collector"],
                "bucket": value["bucket"],
                "section_count": value["section_count"],
                "char_count": value["char_count"],
                "strategies": sorted(value["strategies"]),
            }
            for _, value in sorted(summary.items())
        ]

    def _strategy_for_kind(self, kind: str) -> str:
        return self.policy.section_strategies.get(kind, "keep")

    def _max_chars_for_agent(self, agent_name: str) -> int:
        return int(self.policy.agent_max_chars.get(agent_name, self.policy.default_max_chars))

    def _match_collector(self, path: str) -> CollectorRule:
        normalized = path.replace("\\", "/").lower()
        for rule in self._collector_rules():
            if any(pattern in normalized for pattern in rule.patterns):
                return rule
        return CollectorRule("general_context", "general", 44, "truncate", tuple())

    def _collector_rules(self) -> tuple[CollectorRule, ...]:
        return (
            CollectorRule("snapshot_collector", "survival", 34, "keep", ("/work/run_snapshot.md",)),
            CollectorRule("recall_collector", "retrieved", 35, "compress", ("/work/recall_report.md",)),
            CollectorRule("outline_collector", "working", 36, "keep", ("/work/outline_final.md",)),
            CollectorRule("draft_collector", "working", 37, "truncate", ("/work/draft.md", "/work/final.md")),
            CollectorRule("state_collector", "state", 38, "keep", ("/state/",)),
            CollectorRule("world_collector", "stable", 39, "compress", ("/lore/characters.md", "/lore/worldbook.md")),
            CollectorRule("style_arc_collector", "stable", 40, "compress", ("/lore/style.md", "/outline/current_arc.md")),
            CollectorRule("memory_index_collector", "memory", 41, "compress", ("/memory/index.md",)),
            CollectorRule("memory_summary_collector", "memory", 42, "drop", ("/memory/summaries.md",)),
            CollectorRule("extended_lore_collector", "enhanced", 43, "drop", ("/outline/master_outline.md", "/lore/locations.md")),
        )

    def _truncate_content(self, content: str, limit: int) -> str:
        suffix = "\n\n[TRUNCATED for context budget]\n"
        if limit <= len(suffix):
            return ""
        if len(content) <= limit:
            return content
        allowed = limit - len(suffix)
        truncated = content[:allowed].rstrip()
        if not truncated:
            return ""
        return truncated + suffix

    def _compress_content(self, content: str, limit: int) -> str:
        suffix = "\n\n[COMPRESSED for context budget]\n"
        if len(content) <= limit:
            return content
        if limit <= len(suffix) + 24:
            return ""

        lines = [line.rstrip() for line in content.splitlines()]
        selected: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("##") or stripped.startswith("###"):
                selected.append(line)
                continue
            if stripped.startswith("-") or stripped[:2].isdigit():
                selected.append(line)
                continue
            if len(selected) < 4:
                selected.append(line)
        if not selected:
            selected = [line for line in lines if line.strip()][:4]

        compressed = "\n".join(selected).strip()
        if not compressed:
            return ""
        candidate = compressed + suffix
        if len(candidate) <= limit:
            return candidate
        return self._truncate_content(candidate, limit)

    def _build_artifacts(self, artifacts: list[dict[str, Any]]) -> str:
        if not artifacts:
            return ""
        lines = ["# Output Artifacts", ""]
        for artifact in artifacts:
            lines.extend(
                [
                    f"## {artifact.get('id', 'artifact')}",
                    f"- path: {artifact.get('path', '')}",
                    f"- kind: {artifact.get('kind', 'markdown')}",
                    f"- required: {artifact.get('required', True)}",
                    "",
                ]
            )
        return "\n".join(lines)
