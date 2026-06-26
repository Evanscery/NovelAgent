#!/usr/bin/env bash
# NovelAgent 一键启动（macOS / Linux）。同时启动后端 API + 前端 Web。
# 行为由 config/server.yaml 驱动（host / port / CORS / IP 白名单 / 自动开浏览器）。
# 可追加参数覆盖，例如：./start.sh --port 9000 --host 0.0.0.0
set -euo pipefail
cd "$(dirname "$0")"

# 首次运行：若 web/dist 缺失则构建前端（需 Node.js + npm）。
if [ ! -f "web/dist/index.html" ] && [ -f "web/package.json" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "[NovelAgent] Building web UI (first run)..."
    (cd web && npm install && npm run build)
  else
    echo "[NovelAgent] 未找到 Node.js/npm，将使用回退页。"
    echo "[NovelAgent] 安装 Node.js 后运行：cd web && npm install && npm run build"
  fi
fi

if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

exec "$PY" -m app.main serve "$@"
