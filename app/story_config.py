from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config_loader import ConfigBundle
from app.project_paths import infer_project_prefix, normalize_project_path


def remap_config_to_story_root(config: ConfigBundle, story_root: Path) -> ConfigBundle:
    source_project_root = infer_project_prefix(config.paths.get("project_root", "novel_project")) or "novel_project"
    story_root = story_root.resolve()
    config_root = config.root.resolve()
    target_project_root = story_root.relative_to(config_root).as_posix()

    def rewrite(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {key: rewrite(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [rewrite(item) for item in obj]
        if isinstance(obj, str):
            rewritten = normalize_project_path(obj, source_project_root)
            if rewritten == source_project_root:
                return target_project_root
            return rewritten.replace(source_project_root + "/", target_project_root + "/", 1)
        return obj

    return ConfigBundle(
        root=config.root,
        pipeline=rewrite(config.pipeline),
        agents=rewrite(config.agents),
        models=rewrite(config.models),
        paths=rewrite(config.paths),
        recall=rewrite(config.recall),
        rp=config.rp,
    )
