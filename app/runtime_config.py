from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML。请先运行：pip install -e .") from exc


@dataclass(frozen=True)
class RuntimeConfig:
    api_key: str
    base_url: str
    model_high: str
    model_fast: str


@dataclass(frozen=True)
class RunnerPolicy:
    timeout_seconds: int = 600
    max_retries: int = 3
    backoff_seconds: tuple[int, ...] = (4, 8, 12)


@dataclass(frozen=True)
class RecoveryPolicy:
    allow_guard_degrade: bool = True
    allow_writer_fallback: bool = True
    fallback_tier: str = "standard"


@dataclass(frozen=True)
class ResumePolicy:
    enabled: bool = True
    journal_dir: str = "work/run_journal"
    checkpoint_dir: str = "work/checkpoints"


@dataclass(frozen=True)
class CachePolicy:
    enabled: bool = True
    prompt_cache_dir: str = "data/prompt_cache"


@dataclass(frozen=True)
class ContextPolicy:
    prompt_snapshot_dir: str = "work/prompt_snapshots"
    write_trace: bool = True
    default_max_chars: int = 12000
    agent_max_chars: dict[str, int] = None  # type: ignore[assignment]
    section_strategies: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self):
        object.__setattr__(self, "agent_max_chars", dict(self.agent_max_chars or {}))
        object.__setattr__(self, "section_strategies", {
            "prompt": "keep",
            "module": "keep",
            "artifacts": "keep",
            "context": "truncate",
            "task": "keep",
            **dict(self.section_strategies or {}),
        })


@dataclass(frozen=True)
class RuntimePolicyBundle:
    runner: RunnerPolicy
    recovery: RecoveryPolicy
    resume: ResumePolicy
    cache: CachePolicy
    context: ContextPolicy


DEFAULT_RUNTIME_POLICIES = RuntimePolicyBundle(
    runner=RunnerPolicy(),
    recovery=RecoveryPolicy(),
    resume=ResumePolicy(),
    cache=CachePolicy(),
    context=ContextPolicy(),
)


def load_runtime_config(root: Path | str) -> RuntimeConfig:
    root_path = Path(root).resolve()
    values = dict(os.environ)
    env_example = root_path / ".env.example"
    if env_example.exists():
        values.update(_parse_env_like_file(env_example))

    api_key = values.get("TEST_API_KEY", "").strip()
    base_url = values.get("TEST_BASE_URL", "").strip().rstrip("/")
    model_high = values.get("MODEL_HIGH", "").strip()
    model_fast = values.get("MODEL_FAST", "").strip()

    if not api_key:
        raise ValueError("缺少 TEST_API_KEY，请在环境变量或 .env.example 中提供。")
    if not base_url:
        raise ValueError("缺少 TEST_BASE_URL，请在环境变量或 .env.example 中提供。")
    if not model_high:
        raise ValueError("缺少 MODEL_HIGH，请在环境变量或 .env.example 中提供。")
    if not model_fast:
        raise ValueError("缺少 MODEL_FAST，请在环境变量或 .env.example 中提供。")

    return RuntimeConfig(
        api_key=api_key,
        base_url=base_url,
        model_high=model_high,
        model_fast=model_fast,
    )


def load_runtime_policies(root: Path | str) -> RuntimePolicyBundle:
    root_path = Path(root).resolve()
    config_path = root_path / "config" / "runtime.yaml"
    if not config_path.exists():
        return DEFAULT_RUNTIME_POLICIES
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    runner_raw = raw.get("runner", {})
    recovery_raw = raw.get("recovery", {})
    resume_raw = raw.get("resume", {})
    cache_raw = raw.get("cache", {})
    context_raw = raw.get("context", {})
    return RuntimePolicyBundle(
        runner=RunnerPolicy(
            timeout_seconds=int(runner_raw.get("timeout_seconds", DEFAULT_RUNTIME_POLICIES.runner.timeout_seconds)),
            max_retries=int(runner_raw.get("max_retries", DEFAULT_RUNTIME_POLICIES.runner.max_retries)),
            backoff_seconds=tuple(int(item) for item in runner_raw.get("backoff_seconds", DEFAULT_RUNTIME_POLICIES.runner.backoff_seconds)),
        ),
        recovery=RecoveryPolicy(
            allow_guard_degrade=bool(recovery_raw.get("allow_guard_degrade", DEFAULT_RUNTIME_POLICIES.recovery.allow_guard_degrade)),
            allow_writer_fallback=bool(recovery_raw.get("allow_writer_fallback", DEFAULT_RUNTIME_POLICIES.recovery.allow_writer_fallback)),
            fallback_tier=str(recovery_raw.get("fallback_tier", DEFAULT_RUNTIME_POLICIES.recovery.fallback_tier)),
        ),
        resume=ResumePolicy(
            enabled=bool(resume_raw.get("enabled", DEFAULT_RUNTIME_POLICIES.resume.enabled)),
            journal_dir=str(resume_raw.get("journal_dir", DEFAULT_RUNTIME_POLICIES.resume.journal_dir)),
            checkpoint_dir=str(resume_raw.get("checkpoint_dir", DEFAULT_RUNTIME_POLICIES.resume.checkpoint_dir)),
        ),
        cache=CachePolicy(
            enabled=bool(cache_raw.get("enabled", DEFAULT_RUNTIME_POLICIES.cache.enabled)),
            prompt_cache_dir=str(cache_raw.get("prompt_cache_dir", DEFAULT_RUNTIME_POLICIES.cache.prompt_cache_dir)),
        ),
        context=ContextPolicy(
            prompt_snapshot_dir=str(context_raw.get("prompt_snapshot_dir", DEFAULT_RUNTIME_POLICIES.context.prompt_snapshot_dir)),
            write_trace=bool(context_raw.get("write_trace", DEFAULT_RUNTIME_POLICIES.context.write_trace)),
            default_max_chars=int(context_raw.get("default_max_chars", DEFAULT_RUNTIME_POLICIES.context.default_max_chars)),
            agent_max_chars={str(key): int(value) for key, value in (context_raw.get("agent_max_chars", DEFAULT_RUNTIME_POLICIES.context.agent_max_chars) or {}).items()},
            section_strategies={str(key): str(value) for key, value in (context_raw.get("section_strategies", DEFAULT_RUNTIME_POLICIES.context.section_strategies) or {}).items()},
        ),
    )


def _parse_env_like_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(raw_line)
        if not match:
            continue
        key, value = match.groups()
        result[key] = value.strip().strip('"').strip("'")
    return result


def resolve_model_for_tier(runtime: RuntimeConfig, tier_name: str) -> str:
    lowered = tier_name.lower()
    if lowered in {"premium", "high", "main", "writer", "planner", "quality"}:
        return runtime.model_high
    return runtime.model_fast
