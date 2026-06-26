"""HTTP 路由分发：把请求映射到 web/ 下各 API 模块。

设计：单一 ``build_handler(root, server_config)`` 工厂返回 ``BaseHTTPRequestHandler`` 子类。
- 读接口（stories/story/card）复用 main.py 既有聚合函数（延迟导入，避免循环依赖）。
- 写接口走 api_workspace / api_files / api_config / api_run。
- 静态资源走 static.py（有 web/dist 则服务 SPA，否则回退内联页）。
- IP 白名单 / CORS 复用 server_config（白名单为轻量准入，非严格鉴权）。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.web import api_config, api_files, api_novel, api_run, api_workspace, static
from app.web.paths import PathSafetyError


def build_handler(root: Path | str, server_config=None):
    from app.server_config import DEFAULT_SERVER_CONFIG

    root_path = Path(root).resolve()
    cfg = server_config or DEFAULT_SERVER_CONFIG

    class Handler(BaseHTTPRequestHandler):
        # ---- 准入 / CORS ----
        def _client_allowed(self) -> bool:
            client_ip = self.client_address[0] if self.client_address else ""
            if not cfg.is_ip_allowed(client_ip):
                self.send_error(403, "ip not allowed")
                return False
            return True

        def _apply_cors(self):
            origin = self.headers.get("Origin")
            allow = cfg.cors_origin_for(origin)
            if allow:
                self.send_header("Access-Control-Allow-Origin", allow)
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

        def do_OPTIONS(self):
            if not self._client_allowed():
                return
            self.send_response(204)
            self._apply_cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ---- 工具 ----
        def _json(self, payload, status: int = 200):
            data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._apply_cors()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, message: str):
            self._json({"error": message}, status=status)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            # 非 UTF-8 请求体视为非法 JSON，由调用方返回 400（而非 500）。
            text = raw.decode("utf-8")
            return json.loads(text)

        def _query(self, parsed):
            return parse_qs(parsed.query)

        def _send_bytes(self, data: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self._apply_cors()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

        # ---- GET ----
        def do_GET(self):
            if not self._client_allowed():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/"):
                    return self._handle_get_api(path, parsed)
            except PathSafetyError as exc:
                return self._error(400, str(exc))
            except FileNotFoundError:
                return self._error(404, "not found")
            except ValueError as exc:
                return self._error(400, str(exc))
            return self._serve_static(path)

        def _handle_get_api(self, path, parsed):
            from app.main import collect_story_summary, load_card_view_payload, load_story_payload

            query = self._query(parsed)
            if path == "/api/stories":
                return self._json(collect_story_summary(root_path))
            if path == "/api/workspaces":
                return self._json(api_workspace.list_workspaces(root_path))
            if path == "/api/story":
                rel = query.get("path", [""])[0]
                try:
                    return self._json(load_story_payload(root_path, rel))
                except FileNotFoundError:
                    return self._error(404, "story not found")
            if path == "/api/card":
                rel = query.get("path", [""])[0]
                try:
                    return self._json(load_card_view_payload(root_path, rel))
                except FileNotFoundError:
                    return self._error(404, "story not found")
            if path == "/api/files":
                rel = query.get("path", [""])[0]
                return self._json(api_files.list_files(root_path, rel))
            if path == "/api/file":
                ws = query.get("path", [""])[0]
                file_rel = query.get("rel", [""])[0]
                return self._json(api_files.read_file(root_path, ws, file_rel))
            # NOVEL-A2：只读小说阅读通道（章节列表 / 章节正文 / 场景全文本）。
            if path == "/api/novel":
                rel = query.get("path", [""])[0]
                return self._json(api_novel.list_novel(root_path, rel))
            if path == "/api/novel/chapter":
                rel = query.get("path", [""])[0]
                chapter = query.get("chapter", [""])[0]
                return self._json(api_novel.read_chapter(root_path, rel, chapter))
            if path == "/api/novel/scene":
                rel = query.get("path", [""])[0]
                scene_id = query.get("scene_id", [""])[0]
                return self._json(api_novel.read_scene(root_path, rel, scene_id))
            if path == "/api/configs":
                return self._json(api_config.list_configs(root_path))
            if path == "/api/config":
                name = query.get("name", [""])[0]
                return self._json(api_config.read_config(root_path, name))
            if path.startswith("/api/run/"):
                job_id = path[len("/api/run/"):]
                job = api_run.get_job(job_id)
                if job is None:
                    return self._error(404, "job not found")
                return self._json(job)
            return self._error(404, "not found")

        # ---- POST ----
        def do_POST(self):
            if not self._client_allowed():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "invalid json body")
            if not isinstance(body, dict):
                return self._error(400, "body must be a json object")
            try:
                return self._handle_post_api(path, body)
            except PathSafetyError as exc:
                return self._error(400, str(exc))
            except (api_workspace.WorkspaceError, api_run.RunApiError, api_files.FileApiError, api_config.ConfigApiError) as exc:
                return self._error(400, str(exc))

        def _handle_post_api(self, path, body):
            from app.main import load_story_config, run_rp_turn

            if path == "/api/workspace":
                result = api_workspace.create_workspace(root_path, body.get("name", ""), body.get("theme", ""))
                return self._json(result, status=201)
            if path == "/api/run":
                kind = body.get("kind", "")
                params = {k: v for k, v in body.items() if k != "kind"}
                # 默认 synchronous=False；测试可传 sync=true
                result = api_run.start_job(root_path, kind, params, synchronous=bool(body.get("sync")))
                return self._json(result, status=202)
            if path == "/api/rp-turn":
                story_path = body.get("story_path")
                text = body.get("text", "")
                resolve = body.get("resolve")
                if not isinstance(story_path, str) or not story_path.strip():
                    return self._error(400, "story_path required")
                # resolve 模式下 text 可为空（玩家只回传掷骰结果）；否则 text 必填。
                if not isinstance(resolve, dict) and (not isinstance(text, str) or not text.strip()):
                    return self._error(400, "text required")
                _, config, story_root = load_story_config(story_path)
                if story_root is None or not story_root.exists():
                    return self._error(404, "story not found")
                return self._json(run_rp_turn(story_root, config, root_path, text, resolve=resolve))
            return self._error(404, "not found")

        # ---- PUT ----
        def do_PUT(self):
            if not self._client_allowed():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                body = self._read_json_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._error(400, "invalid json body")
            if not isinstance(body, dict):
                return self._error(400, "body must be a json object")
            try:
                if path == "/api/file":
                    result = api_files.write_file(
                        root_path, body.get("path", ""), body.get("rel", ""), body.get("content", "")
                    )
                    return self._json(result)
                if path == "/api/config":
                    result = api_config.write_config(root_path, body.get("name", ""), body.get("content", ""))
                    return self._json(result)
            except PathSafetyError as exc:
                return self._error(400, str(exc))
            except (api_files.FileApiError, api_config.ConfigApiError) as exc:
                return self._error(400, str(exc))
            return self._error(404, "not found")

        # ---- DELETE ----
        def do_DELETE(self):
            if not self._client_allowed():
                return
            parsed = urlparse(self.path)
            path = parsed.path
            query = self._query(parsed)
            try:
                if path == "/api/workspace":
                    rel = query.get("path", [""])[0]
                    return self._json(api_workspace.delete_workspace(root_path, rel))
            except PathSafetyError as exc:
                return self._error(400, str(exc))
            except api_workspace.WorkspaceError as exc:
                return self._error(400, str(exc))
            return self._error(404, "not found")

        # ---- 静态 ----
        def _serve_static(self, path):
            asset = static.resolve_asset(root_path, path, cfg.static_dir)
            if asset is None:
                from app.main import _render_index

                html = _render_index().encode("utf-8")
                return self._send_bytes(html, "text/html; charset=utf-8")
            data, content_type = asset
            return self._send_bytes(data, content_type)

    return Handler
