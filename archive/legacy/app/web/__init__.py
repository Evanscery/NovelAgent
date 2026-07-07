"""NovelAgent web 服务包：HTTP 路由 + 工作区/文件/配置/运行 写 API + 静态托管。

入口为 ``app.web.routes.build_handler(root, server_config)``。
"""
from app.web.routes import build_handler

__all__ = ["build_handler"]
