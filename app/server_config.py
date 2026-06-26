from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 PyYAML。请先运行：pip install -e .") from exc


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8766
    open_browser: bool = False
    allow_origins: list[str] = field(default_factory=list)
    ip_whitelist: list[str] = field(default_factory=list)
    static_dir: str | None = None

    def is_ip_allowed(self, client_ip: str) -> bool:
        """空白名单 = 不额外限制（仍受 host 绑定约束）；非空则必须命中。"""
        if not self.ip_whitelist:
            return True
        return client_ip in self.ip_whitelist

    def cors_origin_for(self, origin: str | None) -> str | None:
        """返回应回写的 Access-Control-Allow-Origin；None 表示不加该头。"""
        if not self.allow_origins:
            return None
        if "*" in self.allow_origins:
            return "*"
        if origin and origin in self.allow_origins:
            return origin
        return None


DEFAULT_SERVER_CONFIG = ServerConfig()


def load_server_config(root: Path | str, config_path: str | Path | None = None) -> ServerConfig:
    root_path = Path(root).resolve()
    path = Path(config_path) if config_path else (root_path / "config" / "server.yaml")
    if not path.is_absolute():
        path = root_path / path
    if not path.exists():
        return DEFAULT_SERVER_CONFIG
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_server_config(raw)


def parse_server_config(raw: dict[str, Any]) -> ServerConfig:
    if not isinstance(raw, dict):
        return DEFAULT_SERVER_CONFIG
    server = raw.get("server", raw)
    if not isinstance(server, dict):
        server = {}
    return ServerConfig(
        host=str(server.get("host", DEFAULT_SERVER_CONFIG.host)),
        port=int(server.get("port", DEFAULT_SERVER_CONFIG.port)),
        open_browser=bool(server.get("open_browser", DEFAULT_SERVER_CONFIG.open_browser)),
        allow_origins=[str(item) for item in (server.get("allow_origins") or [])],
        ip_whitelist=[str(item) for item in (server.get("ip_whitelist") or server.get("whitelist") or [])],
        static_dir=(str(server["static_dir"]) if server.get("static_dir") else None),
    )
