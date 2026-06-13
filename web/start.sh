#!/usr/bin/env bash
# 啟動 KG web app（Vite dev server，預設 :5180）。
#
# monorepo workspace：@kg/types 靠 root `npm install` 建的 symlink 解析，
# web/node_modules 不自帶 vite 等 bin（hoist 到 root）。故缺依賴時在 repo root 安裝。
#
# 用法：
#   ./start.sh            # dev server（HMR）
#   ./start.sh preview    # 先 build 再起 preview（貼近生產產物）
#   PORT=5999 ./start.sh  # 覆寫埠（dev 模式 strictPort，被占用會失敗）
set -euo pipefail

WEB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$WEB_DIR/.." && pwd)"
MODE="${1:-dev}"

# 依賴守門：root node_modules 缺失或 @kg/types symlink 斷掉 → 在 root 安裝。
if [ ! -d "$ROOT_DIR/node_modules" ] || [ ! -e "$ROOT_DIR/node_modules/@kg/types" ]; then
  echo "[start] 安裝 workspace 依賴（root npm install）…"
  (cd "$ROOT_DIR" && npm install)
fi

cd "$WEB_DIR"
case "$MODE" in
  dev)
    echo "[start] Vite dev server → http://localhost:${PORT:-5180}"
    exec npm run dev -- ${PORT:+--port "$PORT"}
    ;;
  preview)
    echo "[start] build + preview…"
    npm run build
    exec npm run preview -- ${PORT:+--port "$PORT"}
    ;;
  *)
    echo "[start] 未知模式：$MODE（用 dev 或 preview）" >&2
    exit 2
    ;;
esac
