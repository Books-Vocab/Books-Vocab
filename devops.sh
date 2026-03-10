#!/bin/bash
# =============================================================================
# devops.sh — BooksBrowser KG API DevOps 操作腳本
# 供 Claude Code 代理呼叫。不需理解底層 SSH/Docker 細節，直接執行子指令。
#
# Agent 用法：
#   DEVOPS_YES=1 ./devops.sh delete-user <id>   # 跳過互動確認
#   ./devops.sh run "docker ps"                  # 執行任意遠端指令
# =============================================================================

set -euo pipefail

# ── 設定 ──────────────────────────────────────────────────────────────────────
SSH_KEY="$HOME/.ssh/lightsail_default.pem"
SERVER="ubuntu@54.95.189.179"
REMOTE_DIR="~/knowledge_graph_api"
LOCAL_DIR="$(cd "$(dirname "$0")/backend" && pwd)"
BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/backups"

SSH_OPTS=( -T -i "$SSH_KEY" -o StrictHostKeyChecking=no -o BatchMode=yes )
SSH_CMD=( ssh "${SSH_OPTS[@]}" "$SERVER" )
SCP_CMD=( scp -T -i "$SSH_KEY" -o StrictHostKeyChecking=no -o BatchMode=yes )

# 必要環境變數清單（deploy 前自動檢查）
REQUIRED_ENV_KEYS=(
  "JWT_SECRET"
  "GEMINI_API_KEY"
  "GOOGLE_CLIENT_ID"
  "APPLE_BUNDLE_ID"
  "ADMIN_TOKEN"
  "APP_STORE_ROOT_CA_PATH"
  "APP_STORE_CONNECT_ISSUER_ID"
  "APP_STORE_CONNECT_KEY_ID"
  "APP_STORE_CONNECT_PRIVATE_KEY_PATH"
)

# 允許本地/遠端路徑不同，但要求指向同名檔案並符合各自主機上的預期目錄
HOST_SPECIFIC_ENV_KEYS=(
  "APP_STORE_ROOT_CA_PATH"
  "APP_STORE_CONNECT_PRIVATE_KEY_PATH"
)

# ── 工具函式 ──────────────────────────────────────────────────────────────────
info()    { echo "▶ $*"; }
ok()      { echo "✓ $*"; }
err()     { echo "✗ $*" >&2; exit 1; }
section() { echo ""; echo "── $* ──"; }

require_local_files() {
  [[ -f "$LOCAL_DIR/Dockerfile" ]]         || err "Dockerfile not found in $LOCAL_DIR"
  [[ -f "$LOCAL_DIR/docker-compose.yml" ]] || err "docker-compose.yml not found in $LOCAL_DIR"
}

# 確認函式：DEVOPS_YES=1 時自動跳過（agent 模式）
preflight() {
  require_local_files
}

confirm() {
  if [[ "${DEVOPS_YES:-0}" == "1" ]]; then
    echo "⚠️  $1 [已透過 DEVOPS_YES=1 自動確認]"
    return 0
  fi
  echo ""
  echo "⚠️  $1"
  read -r -p "   輸入 yes 確認: " ans
  [[ "$ans" == "yes" ]] || { echo "已取消。"; exit 0; }
}

run_remote() { "${SSH_CMD[@]}" "$@"; }  # 在遠端執行指令（非互動式）

# ── 指令：env-check ───────────────────────────────────────────────────────────
cmd_env_check() {
  section "檢查遠端 .env 環境變數"
  local missing=()
  local unsafe=()
  for key in "${REQUIRED_ENV_KEYS[@]}"; do
    if run_remote "grep -q '^${key}=' $REMOTE_DIR/.env" 2>/dev/null; then
      ok "$key"
    else
      echo "✗ ${key} (缺少)"
      missing+=("$key")
    fi
  done

  for key in APP_STORE_ALLOW_UNSIGNED_SYNC APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS; do
    if run_remote "grep -Eq '^${key}=(1|true|TRUE|yes|YES)$' $REMOTE_DIR/.env" 2>/dev/null; then
      echo "✗ ${key} (production 不可啟用)"
      unsafe+=("$key")
    else
      ok "${key:-unset}"
    fi
  done

  if [ ${#missing[@]} -gt 0 ]; then
    err "缺少必要環境變數：${missing[*]}，請手動 SSH 更新 .env 後重試"
  fi
  if [ ${#unsafe[@]} -gt 0 ]; then
    err "偵測到不安全的 App Store fallback 開關：${unsafe[*]}，production 請移除或設為 false"
  fi
}

cmd_env_drift() {
  section "檢查本地/遠端 .env 一致性"

  local remote_real_dir
  remote_real_dir=$(run_remote "cd $REMOTE_DIR >/dev/null 2>&1 && pwd")

  local container_app_root="/app"

  python3 - "$LOCAL_DIR/.env" "$remote_real_dir/.env" "$LOCAL_DIR" "$container_app_root" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

local_env_path = Path(sys.argv[1])
remote_env_path = sys.argv[2]
local_dir = Path(sys.argv[3]).resolve()
container_root = sys.argv[4].strip()

host_specific = {
    "APP_STORE_ROOT_CA_PATH": (local_dir / "certs", f"{container_root}/certs"),
    "APP_STORE_CONNECT_PRIVATE_KEY_PATH": (local_dir / "certs", f"{container_root}/certs"),
}

def parse_env_text(text: str):
    result = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result

def parse_local_env(path: Path):
    if not path.exists():
        raise SystemExit(f"✗ 本地 .env 不存在：{path}")
    return parse_env_text(path.read_text())

def parse_remote_env(path: str):
    proc = subprocess.run(
        ["ssh", "-T", "-i", os.path.expanduser("~/.ssh/lightsail_default.pem"), "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", "ubuntu@54.95.189.179", f"cat {path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"✗ 無法讀取遠端 .env：{proc.stderr.strip()}")
    return parse_env_text(proc.stdout)

local_env = parse_local_env(local_env_path)
remote_env = parse_remote_env(remote_env_path)

missing_remote = sorted(set(local_env) - set(remote_env))
missing_local = sorted(set(remote_env) - set(local_env))
value_mismatches = []

for key in sorted(set(local_env) & set(remote_env)):
    lv = local_env[key]
    rv = remote_env[key]
    if key in host_specific:
        local_base_dir, remote_base_dir = host_specific[key]
        local_name = Path(lv).name
        remote_name = Path(rv).name
        expected_local_prefix = str(local_base_dir)
        expected_remote_prefix = remote_base_dir
        if not lv.startswith(expected_local_prefix + "/"):
            value_mismatches.append((key, lv, rv, f"本地值應位於 {expected_local_prefix}/ 下"))
            continue
        if not rv.startswith(expected_remote_prefix + "/"):
            value_mismatches.append((key, lv, rv, f"遠端值應位於 {expected_remote_prefix}/ 下"))
            continue
        if local_name != remote_name:
            value_mismatches.append((key, lv, rv, "本地與遠端指向的檔名不同"))
        continue
    if lv != rv:
        value_mismatches.append((key, lv, rv, "值不同"))

if missing_remote or missing_local or value_mismatches:
    if missing_remote:
        print("✗ 遠端缺少以下 key:")
        for key in missing_remote:
            print(f"  - {key}")
    if missing_local:
        print("✗ 本地缺少以下 key:")
        for key in missing_local:
            print(f"  - {key}")
    if value_mismatches:
        print("✗ 本地/遠端 .env 存在不一致:")
        for key, lv, rv, reason in value_mismatches:
            print(f"  - {key}: {reason}")
            print(f"      local : {lv}")
            print(f"      remote: {rv}")
    raise SystemExit(1)

print("✓ 本地/遠端 .env 已一致（host-specific path key 已正規化檢查）")
PY
}

# ── 指令：deploy ──────────────────────────────────────────────────────────────
cmd_deploy() {
  preflight
  cmd_backup
  cmd_env_check

  # 檢查 working tree 是否與 HEAD 一致（防止 rsync 推送未 commit 的差異）
  local dirty
  dirty=$(cd "$LOCAL_DIR" && git diff --name-only HEAD -- . 2>/dev/null || true)
  if [[ -n "$dirty" ]]; then
    echo "⚠️  Working tree 有未 commit 的變更，rsync 會把它們推上去："
    echo "$dirty" | head -10
    confirm "繼續部署？"
  fi

  section "Step 1/3: 同步代碼"
  rsync -az --stats \
    -e "ssh -T -i $SSH_KEY -o StrictHostKeyChecking=no -o BatchMode=yes" \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.git' \
    --exclude '.env' \
    --exclude 'certs' \
    --exclude 'data' \
    --exclude '.pytest_cache' \
    --exclude '*.pyc' \
    "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

  section "Step 2/3: 重新編譯並啟動容器"
  run_remote "cd $REMOTE_DIR && docker compose up -d --build 2>&1 | tail -20"

  section "Step 3/3: DB Migration"
  cmd_migrate

  section "Step 4/4: 健康驗證"
  local http_code=""
  for i in 1 2 3 4 5; do
    http_code=$(run_remote "curl -o /dev/null -s -w '%{http_code}' http://localhost:8000/docs" || echo "000")
    [[ "$http_code" == "200" ]] && break
    info "attempt $i: HTTP ${http_code}，等待 3 秒..."
    sleep 3
  done
  if [[ "$http_code" == "200" ]]; then
    ok "API 回應正常 (HTTP 200)"
  else
    run_remote "docker logs knowledge-graph-api -n 30"
    err "部署後健康檢查失敗 (HTTP $http_code)，請確認日誌"
  fi

  section "Step 5/5: .env 一致性驗證"
  cmd_env_drift

  ok "部署完成。"
}

# ── 指令：migrate ─────────────────────────────────────────────────────────────
# 對所有用戶的 cards.db 執行 idempotent schema migration（在容器內執行）
cmd_migrate() {
  section "DB Migration"
  run_remote "docker exec knowledge-graph-api python3 -c \"
import sqlite3, glob, os

MIGRATIONS = [
    ('root_form',   'ALTER TABLE card ADD COLUMN root_form TEXT'),
    ('inflections', \\\"ALTER TABLE card ADD COLUMN inflections TEXT DEFAULT '[]'\\\"),
]

dbs = sorted(glob.glob('/app/data/users/*/cards.db'))
if not dbs:
    print('(no databases found)')
for db in dbs:
    uid = db.split('/')[-2]
    conn = sqlite3.connect(db)
    existing = {r[1] for r in conn.execute('PRAGMA table_info(card)').fetchall()}
    changed = []
    for col, sql in MIGRATIONS:
        if col not in existing:
            conn.execute(sql)
            changed.append(col)
    conn.commit()
    conn.close()
    if changed:
        print(f'✓ {uid}: added {changed}')
    else:
        print(f'- {uid}: up to date')
\""
}

# ── 指令：restart ─────────────────────────────────────────────────────────────
cmd_restart() {
  info "重啟容器（不重新 build）"
  run_remote "docker compose -f $REMOTE_DIR/docker-compose.yml restart"
  sleep 3
  local http_code
  http_code=$(run_remote "curl -o /dev/null -s -w '%{http_code}' http://localhost:8000/docs" || echo "000")
  if [[ "$http_code" == "200" ]]; then
    ok "容器已重啟，API 回應正常"
  else
    err "重啟後健康檢查失敗 (HTTP $http_code)"
  fi
}

# ── 指令：status ──────────────────────────────────────────────────────────────
cmd_status() {
  section "Docker 容器"
  run_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

  section "Caddy 狀態"
  run_remote "sudo systemctl is-active caddy && echo 'Caddy: 運行中' || echo 'Caddy: 已停止'"

  section "磁碟使用"
  run_remote "df -h / | awk 'NR==2{print \"根目錄: \" \$3 \" used / \" \$2 \" total (\"\$5\" used)\"}'"
  run_remote "du -sh $REMOTE_DIR/data 2>/dev/null && echo '(以上為 data/ 目錄)' || echo 'data/ 目錄不存在'"

  section "用戶數量"
  run_remote "ls $REMOTE_DIR/data/users/ 2>/dev/null | wc -l | xargs echo '用戶目錄數:'" || echo "(無用戶資料)"
}

# ── 指令：logs ────────────────────────────────────────────────────────────────
cmd_logs() {
  local n="${1:-50}"
  info "顯示最新 $n 行日誌"
  run_remote "docker logs knowledge-graph-api -n $n --timestamps 2>&1"
}

# ── 指令：backup ──────────────────────────────────────────────────────────────
cmd_backup() {
  local date_str; date_str=$(date +%Y%m%d_%H%M)
  local dest="$BACKUP_DIR/data_$date_str"
  mkdir -p "$BACKUP_DIR"

  info "備份 $REMOTE_DIR/data → $dest"
  "${SCP_CMD[@]}" -r "$SERVER:$REMOTE_DIR/data" "$dest"

  ok "備份完成: $dest"
  ls -lh "$BACKUP_DIR" | tail -5
}

# ── 指令：users ───────────────────────────────────────────────────────────────
cmd_users() {
  section "遠端用戶目錄"
  run_remote "ls -la $REMOTE_DIR/data/users/ 2>/dev/null || echo '(無用戶資料)'"

  section "users.json（可選第三方整合設定）"
  run_remote "cat $REMOTE_DIR/data/users.json 2>/dev/null || echo '(不存在)'"
}

# ── 指令：user-info <user_id> ─────────────────────────────────────────────────
cmd_user_info() {
  local uid="${1:-}"
  [[ -z "$uid" ]] && err "用法: $0 user-info <user_id>"

  section "用戶: $uid"
  run_remote "ls -lah $REMOTE_DIR/data/users/$uid/ 2>/dev/null || (echo '用戶不存在'; exit 1)"

  section "單字庫統計"
  run_remote "python3 -c \"
import sqlite3, sys
try:
    conn = sqlite3.connect('$REMOTE_DIR/data/users/$uid/cards.db')
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*), SUM(CASE WHEN is_deleted=0 THEN 1 ELSE 0 END), SUM(CASE WHEN is_deleted=1 THEN 1 ELSE 0 END) FROM card')
    total, active, deleted = cur.fetchone()
    print(f'總卡片: {total}  有效: {active}  已刪除: {deleted}')
except Exception as e:
    print(f'(無法讀取 SQLite: {e})')
\""
}

# ── 指令：delete-user <user_id> [--yes] ───────────────────────────────────────
cmd_delete_user() {
  local uid="${1:-}"
  local yes_flag="${2:-}"
  [[ -z "$uid" ]] && err "用法: $0 delete-user <user_id> [--yes]"

  info "即將刪除的資料:"
  run_remote "ls -lah $REMOTE_DIR/data/users/$uid/ 2>/dev/null || (echo '用戶不存在'; exit 1)"

  [[ "$yes_flag" == "--yes" ]] && DEVOPS_YES=1
  confirm "永久刪除用戶 '$uid' 的所有資料（SQLite、向量、圖譜、第三方整合映射）。此操作不可逆。"
  run_remote "rm -rf $REMOTE_DIR/data/users/$uid"
  ok "用戶 $uid 的資料已刪除。"
}

# ── 指令：push-env [file] ─────────────────────────────────────────────────────
cmd_push_env() {
  local src="${1:-$LOCAL_DIR/.env}"
  [[ ! -f "$src" ]] && err "本地 .env 不存在：$src"
  info "推送 $src → 遠端 $REMOTE_DIR/.env"
  "${SCP_CMD[@]}" "$src" "$SERVER:$REMOTE_DIR/.env"
  ok "已推送 .env"
}

# ── 指令：setup ───────────────────────────────────────────────────────────────
# 初始化或 secret 變動時用：push-env + deploy 一條龍
cmd_setup() {
  cmd_push_env "${1:-}"
  cmd_deploy
}

# ── 指令：run <cmd...> ────────────────────────────────────────────────────────
cmd_run() {
  [[ -z "${1:-}" ]] && err "用法: $0 run \"<remote command>\""
  run_remote "$*"
}

# ── 指令：ssh ─────────────────────────────────────────────────────────────────
# 注意：此指令為互動式，agent 應使用 ./devops.sh run "<cmd>" 代替
cmd_ssh() {
  info "開啟互動式 SSH 連線（agent 請改用 'run' 指令）"
  ssh "${SSH_OPTS[@]}" "$SERVER"
}

# ── 主程式 ────────────────────────────────────────────────────────────────────
case "${1:-help}" in
  deploy)       cmd_deploy ;;
  setup)        cmd_setup "${2:-}" ;;
  push-env)     cmd_push_env "${2:-}" ;;
  env-check)    cmd_env_check ;;
  env-drift)    cmd_env_drift ;;
  migrate)      cmd_migrate ;;
  restart)      cmd_restart ;;
  status)       cmd_status ;;
  logs)         cmd_logs "${2:-50}" ;;
  backup)       cmd_backup ;;
  users)        cmd_users ;;
  user-info)    cmd_user_info "${2:-}" ;;
  delete-user)  cmd_delete_user "${2:-}" "${3:-}" ;;
  run)          cmd_run "${@:2}" ;;
  ssh)          cmd_ssh ;;
  help|--help|-h|*)
    echo ""
    echo "devops.sh — BooksBrowser KG API DevOps"
    echo ""
    echo "用法: ./devops.sh <command> [args]"
    echo ""
    echo "指令:"
    echo "  setup [env_file]        push-env + deploy 一條龍（初始化或 secret 變動時）
  push-env [file]         推送本地 .env 到遠端（預設: backend/.env）
  deploy                  env-check + rsync + build + migrate + health-check
  restart                 重啟容器（不重新 build）
  migrate                 對所有用戶 DB 執行 idempotent schema migration"
    echo "  env-check               檢查遠端 .env 是否包含所有必要環境變數"
    echo "  env-drift               檢查本地/遠端 .env 是否一致（path key 正規化）"
    echo "  status                  Docker / Caddy / 磁碟 / 用戶數概覽"
    echo "  logs [n]                最新 n 行日誌（預設 50）"
    echo "  backup                  備份 data/ 到本地 backups/"
    echo "  users                   列出所有遠端用戶 + users.json"
    echo "  user-info <id>          查看特定用戶單字統計"
    echo "  delete-user <id> [--yes]  刪除用戶資料（--yes 跳過確認，或設 DEVOPS_YES=1）"
    echo "  run \"<cmd>\"             在遠端執行任意指令（agent 用）"
    echo "  ssh                     開啟互動式 SSH（人工用，agent 改用 run）"
    echo ""
    echo "Agent 環境變數:"
    echo "  DEVOPS_YES=1            自動確認所有危險操作"
    echo ""
    ;;
esac
