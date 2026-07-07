from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML。请先运行：pip install -e .") from exc

from app.rp_modes import DEFAULT_RP_CONFIG, RpConfig


@dataclass(frozen=True)
class ConfigBundle:
    root: Path
    pipeline: dict[str, Any]
    agents: dict[str, Any]
    models: dict[str, Any]
    paths: dict[str, Any]
    recall: dict[str, Any]
    # per-workspace RP 配置（默认空，由 load_story_config 在 story_root 已知后填入）。
    rp: RpConfig = DEFAULT_RP_CONFIG

    def with_pipeline(self, pipeline: dict[str, Any]) -> "ConfigBundle":
        return ConfigBundle(
            root=self.root,
            pipeline=pipeline,
            agents=self.agents,
            models=self.models,
            paths=self.paths,
            recall=self.recall,
            rp=self.rp,
        )


class ConfigLoader:
    """读取并提供项目配置。"""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def load_yaml(self, path: str) -> dict[str, Any]:
        full_path = self.root / path
        if not full_path.exists():
            raise FileNotFoundError(f"配置文件不存在：{full_path}")
        data = yaml.safe_load(full_path.read_text(encoding="utf-8"))
        return data or {}

    def load(self) -> ConfigBundle:
        return ConfigBundle(
            root=self.root,
            pipeline=self.load_yaml("config/pipeline.yaml"),
            agents=self.load_yaml("config/agents.yaml"),
            models=self.load_yaml("config/models.yaml"),
            paths=self.load_yaml("config/paths.yaml"),
            recall=self.load_yaml("config/recall.yaml"),
        )


def get_agent_config(config: ConfigBundle, agent_name: str) -> dict[str, Any]:
    agents = config.agents.get("agents", {})
    if agent_name not in agents:
        raise KeyError(f"未找到 Agent 配置：{agent_name}")
    return agents[agent_name]
