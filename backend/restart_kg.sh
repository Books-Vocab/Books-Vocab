#!/bin/bash
# restart_kg.sh — 一鍵重啟 KG 後端

KG_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$KG_DIR/.venv/bin/uvicorn"
ENV_FILE="$KG_DIR/.env"

echo "🔄 停止舊的 KG server..."
lsof -ti:8000 | xargs kill 2>/dev/null
sleep 1

echo "🚀 啟動 KG server..."
PYTHONPATH="$KG_DIR/src" "$VENV" kg.api:app \
    --reload \
    --host 0.0.0.0 \
    --port 8000 \
    --env-file "$ENV_FILE"
