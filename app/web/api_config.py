"""配置 API：读写 ``config/*.yaml``。

仅允许白名单内的配置文件，写入前做 YAML 解析校验，避免写坏配置导致服务无法启动。
"""
from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML。请先运行：pip install -e .") from exc

# 允许通过 API 读写的配置文件名（不含目录、不含扩展名以外的路径）。
ALLOWED_CONFIGS = (
    "agents",
    "models",
    "paths",
    "pipeline",
    "pipeline_chapter",
    "pipeline_evaluate",
    "pipeline_story_init",
    "pipeline_smoke_critic",
    "pipeline_smoke_generate",
    "recall",
    "runtime",
    "server",
)


class ConfigApiError(ValueError):
    """配置操作失败（非白名单 / YAML 非法）。"""


def _config_path(root: Path, name: str) -> Path:
    if name not in ALLOWED_CONFIGS:
        raise ConfigApiError(f"不允许的配置文件：{name}")
    return root / "config" / f"{name}.yaml"


def list_configs(root: Path | str) -> dict[str, object]:
    root_path = Path(root).resolve()
    items = []
    for name in ALLOWED_CONFIGS:
        path = root_path / "config" / f"{name}.yaml"
        items.append({"name": name, "exists": path.exists()})
    return {"configs": items}


def read_config(root: Path | str, name: str) -> dict[str, object]:
    root_path = Path(root).resolve()
    path = _config_path(root_path, name)
    if not path.exists():
        raise ConfigApiError(f"配置文件不存在：{name}")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


def write_config(root: Path | str, name: str, content: str) -> dict[str, object]:
    if not isinstance(content, str):
        raise ConfigApiError("content must be a string")
    root_path = Path(root).resolve()
    path = _config_path(root_path, name)
    # 写前校验 YAML，拒绝语法错误的内容。
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigApiError(f"YAML 语法错误：{exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n")
    path.write_text(normalized, encoding="utf-8", newline="\n")
    return {"name": name, "bytes": len(normalized.encode("utf-8")), "saved": True}
