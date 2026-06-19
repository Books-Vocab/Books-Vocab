#!/bin/bash
# =============================================================================
# devops.sh — BooksAndVocab KG API DevOps 操作腳本
# 供 Claude Code 代理呼叫。不需理解底層 SSH/Docker 細節，直接執行子指令。
#
# Agent 用法：
#   DEVOPS_YES=1 ./devops.sh delete-user <id>   # 跳過互動確認
#   ./devops.sh run "docker ps"                  # 執行任意遠端指令
# =============================================================================

set -euo pipefail

# ── 設定 ──────────────────────────────────────────────────────────────────────
# 正式站 2026-06-15 起 = 家用常駐機 felix（standby），經 Cloudflare Tunnel 對外。
# transport 走 Tailscale + 原生 sshd 公鑰（免密碼，default key，不再用 lightsail .pem）。
# 拓撲正本：~/butler/docs/kg-backend-deployment.md；host/port 正本：docs/reference/host_topology.md。
SERVER="${KG_SERVER:-chenliangyu@100.118.39.104}"
REMOTE_DIR="${KG_REMOTE_DIR:-~/project/kg/backend}"
CONTAINER="knowledge-graph-api"
# standby: 用戶資料在 ~/kg-data（搬出 git worktree），container 內 mount 為 /app/data。
REMOTE_DATA_DIR="${KG_REMOTE_DATA_DIR:-~/kg-data}"
PUBLIC_WEB_BASE_URL="https://wordnexus.lol"
LOCAL_DIR="$(cd "$(dirname "$0")/backend" && pwd)"
BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/backups"

# default key + 已知 host（standby 用內建 ssh config / known_hosts，免帶 -i）
SSH_OPTS=( -T -o StrictHostKeyChecking=accept-new -o BatchMode=yes )
# KG_SSH_CMD is a test seam: point it at a stub (e.g. one that echoes the remote
# command string) to assert transport-layer quoting without a real SSH hop.
if [[ -n "${KG_SSH_CMD:-}" ]]; then
  read -r -a SSH_CMD <<< "$KG_SSH_CMD"
else
  SSH_CMD=( ssh "${SSH_OPTS[@]}" "$SERVER" )
fi
if [[ -n "${KG_SCP_CMD:-}" ]]; then
  read -r -a SCP_CMD <<< "$KG_SCP_CMD"
else
  SCP_CMD=( scp -T -o StrictHostKeyChecking=accept-new -o BatchMode=yes )
fi

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
# info/progress 走 stderr，stdout 只留命令 payload（讓 ops-cli --json 可機讀 parse）。
info()    { echo "▶ $*" >&2; }
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

make_remote_tmp_path() {
  local stem="$1"
  local ext="$2"
  printf '/tmp/%s__%s__%s%s' "$stem" "$(date -u +%Y%m%dT%H%M%SZ)" "$$" "$ext"
}

copy_local_to_container() {
  local src="$1"
  local remote_tmp="$2"
  [[ -f "$src" ]] || err "檔案不存在: $src"
  "${SCP_CMD[@]}" "$src" "$SERVER:$remote_tmp"
  run_remote "docker cp $remote_tmp $CONTAINER:$remote_tmp"
}

cleanup_remote_tmp() {
  local remote_tmp
  for remote_tmp in "$@"; do
    [[ -n "$remote_tmp" ]] || continue
    run_remote "docker exec $CONTAINER rm -f $remote_tmp" >/dev/null 2>&1 || true
    run_remote "rm -f $remote_tmp" >/dev/null 2>&1 || true
  done
}

# ── 部署後 smoke verify（從本地打公網，外部視角全鏈路驗證）─────────────────
# 可注入：CURL_BIN（測試用 mock curl）、KG_SKIP_SMOKE=1 完全跳過、
#         SENTRY_VERIFY=1 加做 sentry endpoint 探測、
#         SMOKE_BASE_URL（預設 ${PUBLIC_WEB_BASE_URL}）
verify_post_deploy() {
  local deploy_sha="$1"
  local base_url="${SMOKE_BASE_URL:-${PUBLIC_WEB_BASE_URL:-https://wordnexus.lol}}"
  local curl_bin="${CURL_BIN:-curl}"
  local rc=0

  if [[ "${KG_SKIP_SMOKE:-0}" == "1" ]]; then
    info "KG_SKIP_SMOKE=1，跳過部署後 smoke verify"
    return 0
  fi

  section "部署後 smoke verify"

  # 1) /api/system/info — 公開 endpoint，必須 200，body 含 version 且等於 deploy_sha
  local info_body info_http
  info_body=$("$curl_bin" -sS -o - -w $'\n%{http_code}' --max-time 10 "$base_url/api/system/info" 2>/dev/null || true)
  info_http=$(printf '%s\n' "$info_body" | tail -n1)
  info_body=$(printf '%s\n' "$info_body" | sed '$d')

  if [[ "$info_http" != "200" ]]; then
    echo "✗ /api/system/info HTTP=$info_http (expect 200)"
    rc=1
  else
    local remote_version
    remote_version=$(printf '%s' "$info_body" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
    if [[ -z "$remote_version" ]]; then
      echo "✗ /api/system/info 缺少 version 欄位 (body=$info_body)"
      rc=1
    elif [[ "$remote_version" != "$deploy_sha" ]]; then
      echo "✗ /api/system/info version=$remote_version 不等於 deploy_sha=$deploy_sha"
      rc=1
    else
      ok "/api/system/info 200，version=$remote_version 對齊"
    fi
  fi

  # 2) /api/health — 需要 auth，unauth 預期 401（代表 route 存在 + auth wire 正常）
  #    404/000 視為 endpoint 消失或網路斷，記紅；500 視為 app 起火，記紅
  local health_http
  health_http=$("$curl_bin" -sS -o /dev/null -w '%{http_code}' --max-time 10 "$base_url/api/health" 2>/dev/null || echo "000")
  case "$health_http" in
    401|403)
      ok "/api/health 受 auth 保護 (HTTP ${health_http}), endpoint 正常"
      ;;
    200)
      ok "/api/health HTTP 200 (auth 跳過或測試環境)"
      ;;
    404)
      info "/api/health 不存在 (HTTP 404), 跳過此項 (非失敗)"
      ;;
    000)
      echo "✗ /api/health 無回應 (網路斷或 TLS 失敗)"
      rc=1
      ;;
    *)
      echo "✗ /api/health 異常 HTTP=${health_http}"
      rc=1
      ;;
  esac

  # 3) Sentry verify（opt-in via SENTRY_VERIFY=1）
  if [[ "${SENTRY_VERIFY:-0}" == "1" ]]; then
    local sentry_http
    sentry_http=$("$curl_bin" -sS -o /dev/null -w '%{http_code}' --max-time 10 "$base_url/api/system/sentry-test" 2>/dev/null || echo "000")
    case "$sentry_http" in
      401|403)
        ok "/api/system/sentry-test 存在且 admin 保護 (HTTP ${sentry_http})"
        ;;
      500|502)
        ok "/api/system/sentry-test 觸發例外 (HTTP ${sentry_http}), 請於 Sentry UI 確認事件抵達"
        ;;
      404)
        # endpoint 缺席 → fallback: 透過 system/info 確認 SENTRY_DSN 已被讀取
        info "/api/system/sentry-test 不存在, fallback 檢查 /api/system/info"
        if printf '%s' "$info_body" | grep -q '"sentry"'; then
          ok "/api/system/info 含 sentry 狀態欄位 (DSN 已讀取)"
        else
          info "(/api/system/info 未暴露 sentry 狀態, 僅供參考, 非失敗)"
        fi
        ;;
      000)
        echo "✗ /api/system/sentry-test 無回應"
        rc=1
        ;;
      *)
        info "/api/system/sentry-test HTTP=${sentry_http} (非預期但不視為失敗)"
        ;;
    esac
  fi

  if [[ "$rc" -ne 0 ]]; then
    echo ""
    echo "── 容器最近 30 行 log (smoke 失敗診斷) ──"
    run_remote "cd $REMOTE_DIR && docker compose logs --tail=30" || true
    err "部署後 smoke verify 失敗 (deploy_sha=${deploy_sha}), 詳見上方"
  fi
  ok "部署後 smoke verify 通過"
  return 0
}

# ── 安全函式 ──────────────────────────────────────────────────────────────────
# uid 必須是英數字、底線、連字號、點號，1-64 字元；
# shell metachar / path traversal（.. / / / 前導 .）一律拒絕，對齊後端 _safe_user_dir。
validate_uid() {
  local uid="$1"
  if [[ -z "$uid" ]]; then
    err "user_id 不可為空"
  fi
  if [[ -n "${uid//[A-Za-z0-9_.-]/}" ]] ||\
     [[ "$uid" =~ ^\. ]] ||\
     [[ "$uid" =~ \.\. ]] ||\
     [[ "$uid" =~ / ]]; then
    err "非法 user_id：'$uid'（僅允許英數字、底線、連字號、點號，長度 1-64；禁止 '..'、'/'、前導 '.')"
  fi
  if [[ "${#uid}" -gt 64 ]]; then
    err "非法 user_id：'$uid'（長度超過 64）"
  fi
}

# Production 互斥鎖：deploy/restart/migrate 並發保護
# Mac 預設無 flock(1)，改用 mkdir 原子鎖
DEPLOY_LOCK_DIR="/tmp/kg-deploy.lock"
DEPLOY_LOCK_HELD=0
acquire_deploy_lock() {
  # 同 process 內已持有則略過（cmd_deploy → cmd_migrate 遞迴呼叫場景）
  [[ "$DEPLOY_LOCK_HELD" == "1" ]] && return 0
  if ! mkdir "$DEPLOY_LOCK_DIR" 2>/dev/null; then
    err "另一個 deploy/restart/migrate 正在進行中（$DEPLOY_LOCK_DIR 已存在）。若確認無進行中操作，請手動 rmdir $DEPLOY_LOCK_DIR"
  fi
  DEPLOY_LOCK_HELD=1
  trap 'rmdir "$DEPLOY_LOCK_DIR" 2>/dev/null || true' EXIT INT TERM
}

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

  python3 - "$LOCAL_DIR/.env" "$remote_real_dir/.env" "$LOCAL_DIR" "$container_app_root" "$SERVER" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

local_env_path = Path(sys.argv[1])
remote_env_path = sys.argv[2]
local_dir = Path(sys.argv[3]).resolve()
container_root = sys.argv[4].strip()
server = sys.argv[5].strip()

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
        ["ssh", "-T", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes", server, f"cat {path}"],
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
# standby 流程（2026-06-15 起，正本見 ~/butler/docs/kg-backend-deployment.md §4.2）：
#   遠端 git pull → 寫 VERSION → docker compose up -d --build → health → smoke verify。
#   程式碼靠 git 同步（非 rsync push）；data/ 是 ~/kg-data volume mount，build 不碰。
#   migration 由 app 啟動自動跑（migration_version 在 /api/system/info），不再本地 SQL loop。
cmd_deploy() {
  acquire_deploy_lock
  preflight

  # ── 本地 working tree 必須乾淨且已 push（standby 靠 git pull 取碼）──
  local dirty
  dirty=$(cd "$LOCAL_DIR" && git diff --name-only HEAD -- . 2>/dev/null || true)
  if [[ -n "$dirty" ]]; then
    echo "✗ 拒絕在 dirty 工作區部署。以下檔案未 commit：" >&2
    echo "$dirty" | head -20 >&2
    err "請先 commit + push 後再部署（standby 由 git pull 取碼，未 push 的改動不會生效）"
  fi

  local local_sha
  local_sha=$(cd "$LOCAL_DIR" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  info "本地 HEAD = $local_sha（請先確認已 git push，否則 standby pull 不到）"

  local deploy_log="$BACKUP_DIR/deploy.log"

  # ── Step 1: standby git pull + 寫 VERSION ──
  section "standby git pull + 更新 VERSION"
  run_remote "cd $REMOTE_DIR && git pull --ff-only && git rev-parse --short HEAD > VERSION && cat VERSION"

  local deploy_sha
  deploy_sha=$(run_remote "cd $REMOTE_DIR && git rev-parse --short HEAD" 2>/dev/null || echo "unknown")

  # ── Step 2: 重建並啟動容器 ──
  # src/ COPY 進 image（非 volume），改碼必 rebuild 才生效。data/ = ~/kg-data volume，不動。
  section "重新編譯並啟動容器"
  run_remote "cd $REMOTE_DIR && docker compose up -d --build 2>&1 | tail -20"

  # ── Step 3: 健康驗證（直連 standby localhost）──
  section "健康驗證"
  local max_attempts=5
  local delay=3
  local url="http://localhost:8000/api/system/info"
  local http_code=""
  for i in $(seq 1 $max_attempts); do
    http_code=$(run_remote "curl -o /dev/null -s -w '%{http_code}' $url" || echo "000")
    if [[ "$http_code" == "200" ]]; then
      ok "健康檢查通過 (attempt $i)"
      break
    fi
    info "attempt $i: HTTP ${http_code}，等待 ${delay} 秒..."
    sleep $delay
  done
  if [[ "$http_code" != "200" ]]; then
    run_remote "cd $REMOTE_DIR && docker compose logs --tail=30"
    err "部署後健康檢查失敗 (HTTP $http_code)，請確認日誌"
  fi

  # ── Sentry release 對齊驗證 ──
  section "Sentry release 驗證"
  local reported_version
  reported_version=$(run_remote "curl -s $url" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null \
    || echo "unknown")
  if [[ "$reported_version" == "$deploy_sha" ]]; then
    ok "Sentry release = $deploy_sha (api/system/info 對齊)"
  else
    echo "⚠ /api/system/info 回報 version=${reported_version} 但部署 sha=${deploy_sha}" >&2
  fi

  # ── 記錄部署日誌 ──
  mkdir -p "$BACKUP_DIR"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sha=$deploy_sha user=$(whoami)" >> "$deploy_log"
  info "部署記錄已追加至 $deploy_log"

  # ── 部署後 smoke verify（外部視角，確認 CF→tunnel→standby 全鏈路 + 版本對齊）──
  verify_post_deploy "$deploy_sha"

  ok "部署完成 (version: $deploy_sha)。"
}

# ── 指令：migrate ─────────────────────────────────────────────────────────────
# standby 現況：schema migration 由 app 啟動自動跑（migration_version 在
# /api/system/info），deploy 已不再呼叫本指令。此指令保留為手動 idempotent
# fallback（對所有用戶 cards.db 補欄位，在容器內執行），需要時手動觸發。
cmd_migrate() {
  acquire_deploy_lock
  section "DB Migration（手動 fallback；standby 正常情況由 app 啟動自動跑）"
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
  acquire_deploy_lock
  info "重啟容器（不重新 build）"
  run_remote "cd $REMOTE_DIR && docker compose restart"
  sleep 3
  local http_code
  http_code=$(run_remote "curl -o /dev/null -s -w '%{http_code}' http://localhost:8000/api/system/info" || echo "000")
  if [[ "$http_code" == "200" ]]; then
    ok "容器已重啟，API 回應正常"
  else
    err "重啟後健康檢查失敗 (HTTP $http_code)"
  fi
}

# ── 指令：status ──────────────────────────────────────────────────────────────
cmd_status() {
  section "部署版本"
  run_remote "cat $REMOTE_DIR/VERSION 2>/dev/null && echo '' || echo 'unknown (no VERSION file)'"

  section "Docker 容器"
  run_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

  section "對外入口（Cloudflare Tunnel）"
  # standby 無 Caddy（macOS）。對外走 CF Tunnel：cloudflared 由 launchd 常駐。
  run_remote "pgrep -lf 'cloudflared.*tunnel' >/dev/null 2>&1 && echo 'cloudflared tunnel: 運行中（CF Tunnel）' || echo 'cloudflared tunnel: 未偵測到（檢查 launchd com.cloudflare.cloudflared）'"

  section "磁碟使用"
  run_remote "df -h / | awk 'NR==2{print \"根目錄: \" \$3 \" used / \" \$2 \" total (\"\$5\" used)\"}'"
  run_remote "du -sh ~/kg-data 2>/dev/null && echo '(以上為 ~/kg-data 資料目錄，container /app/data volume)' || echo '~/kg-data 不存在'"

  section "用戶數量"
  run_remote "ls ~/kg-data/users/ 2>/dev/null | wc -l | xargs echo '用戶目錄數:'" || echo "(無用戶資料)"

  section "最近部署記錄"
  local deploy_log="$BACKUP_DIR/deploy.log"
  if [[ -f "$deploy_log" ]]; then
    tail -5 "$deploy_log"
  else
    echo "(無部署記錄)"
  fi
}

# ── 指令：logs ────────────────────────────────────────────────────────────────
cmd_logs() {
  local n="${1:-50}"
  local tz="${KG_LOG_TZ:-}"
  info "顯示最新 $n 行日誌"
  if [[ -n "$tz" ]]; then
    # 透過 perl 即時轉換 ISO 8601 timestamp 到指定時區
    run_remote "docker logs knowledge-graph-api -n $n --timestamps 2>&1" \
      | perl -MPOSIX -MTime::Piece -pe '
          if (/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})/) {
            my $utc = $1;
            $ENV{TZ} = "'"$tz"'";
            POSIX::tzset();
            if (my $t = eval { Time::Piece->strptime($utc, "%Y-%m-%dT%H:%M:%S") }) {
              my $local = localtime($t->epoch);
              my $s = $local->strftime("%Y-%m-%d %H:%M:%S %Z");
              s/\Q$utc\E/$s/;
            }
          }
        '
  else
    run_remote "docker logs knowledge-graph-api -n $n --timestamps 2>&1"
  fi
}

# ── 指令：backup ──────────────────────────────────────────────────────────────
cleanup_old_backups() {
  local backup_dir="$BACKUP_DIR"
  local keep=10
  local count
  count=$(ls -1d "$backup_dir"/data_* 2>/dev/null | wc -l)
  if [ "$count" -gt "$keep" ]; then
    local to_delete=$(( count - keep ))
    echo "清理舊備份：刪除最舊的 $to_delete 份..."
    ls -1d "$backup_dir"/data_* | head -n "$to_delete" | while read -r dir; do
      echo "  刪除: $(basename "$dir")"
      rm -rf "$dir"
    done
  fi
}

cmd_backup() {
  # 注意：standby 的**權威排程/異地**備份 = standby launchd `com.kg.backup` → S3
  #（見 ~/butler/docs/kg-backend-deployment.md §4.5 / §7 G5）。本指令是 oscar 端
  # 的「臨時冷快照」：把 standby ~/kg-data **拉**回本地 backups/ 並做完整性驗證，
  # 不對 prod 寫入、不取代排程備份。
  local date_str; date_str=$(date +%Y%m%d_%H%M)
  local dest="$BACKUP_DIR/data_$date_str"
  mkdir -p "$BACKUP_DIR"

  info "本地冷快照（pull from standby）：$SERVER:$REMOTE_DATA_DIR → ${dest}（排除 _ops_backups / _ops_world_backups）"

  # 找最近一份備份目錄當增量基準（未變的 db 走硬連結，只傳當日有寫入的）
  local prev
  prev=$(ls -1dt "$BACKUP_DIR"/data_*/ 2>/dev/null | grep -vF "/data_${date_str}/" | head -1) || true  # grep 無匹配 exit 1，避免 set -e 在首次（無既有備份）誤殺
  mkdir -p "$dest"
  info "rsync progress enabled: --info=progress2 --human-readable"
  rsync -az --delete --info=progress2 --human-readable \
    --exclude='_ops_backups/' \
    --exclude='_ops_world_backups/' \
    ${prev:+--link-dest="$prev"} \
    -e "ssh -T -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
    "$SERVER:$REMOTE_DATA_DIR/" "$dest/"
  [[ -n "$prev" ]] && info "增量基準: $(basename "$prev")（未變檔走硬連結）" \
                   || info "首次全量備份（無基準）"

  # ── 完整性驗證：SQLite integrity_check ──────────────────────────────────
  section "驗證備份完整性"
  local integrity_ok=1
  while IFS= read -r -d '' db; do
    local result
    result=$(sqlite3 "$db" "PRAGMA integrity_check;" 2>&1)
    if [[ "$result" == "ok" ]]; then
      ok "integrity_check: $(basename "$(dirname "$db")")/$(basename "$db")"
    else
      echo "✗ 損毀: $db" >&2
      echo "  $result" >&2
      integrity_ok=0
    fi
  done < <(find "$dest" -name "*.db" -print0)

  # ── 完整性驗證：sha256 checksum ─────────────────────────────────────────
  local tar_file="$BACKUP_DIR/data_${date_str}.tar.gz"
  info "計算備份 checksum → ${tar_file}.sha256"
  tar -czf "$tar_file" -C "$BACKUP_DIR" "data_$date_str"
  sha256sum "$tar_file" > "${tar_file}.sha256"
  ok "checksum: $(cat "${tar_file}.sha256")"

  if [[ "$integrity_ok" -eq 0 ]]; then
    err "備份完整性驗證失敗，請檢查上方錯誤訊息"
  fi

  ok "備份完成且驗證通過: $dest"
  ls -lh "$BACKUP_DIR" | tail -5
  cleanup_old_backups
}

# ── 指令：users ───────────────────────────────────────────────────────────────
cmd_users() {
  section "遠端用戶目錄"
  run_remote "ls -la $REMOTE_DATA_DIR/users/ 2>/dev/null || echo '(無用戶資料)'"

  section "users.json（可選第三方整合設定）"
  run_remote "cat $REMOTE_DATA_DIR/users.json 2>/dev/null || echo '(不存在)'"
}

# ── 指令：user-info <user_id> ─────────────────────────────────────────────────
cmd_user_info() {
  local uid="${1:-}"
  [[ -z "$uid" ]] && err "用法: $0 user-info <user_id>"
  validate_uid "$uid"

  section "用戶: $uid"
  run_remote "ls -lah $REMOTE_DATA_DIR/users/$uid/ 2>/dev/null || (echo '用戶不存在'; exit 1)"

  section "單字庫統計"
  run_remote "python3 -c \"
import sqlite3, sys
try:
    conn = sqlite3.connect('$REMOTE_DATA_DIR/users/$uid/cards.db')
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
  validate_uid "$uid"

  info "即將刪除的資料:"
  run_remote "ls -lah $REMOTE_DATA_DIR/users/$uid/ 2>/dev/null || (echo '用戶不存在'; exit 1)"

  [[ "$yes_flag" == "--yes" ]] && DEVOPS_YES=1
  confirm "永久刪除用戶 '$uid' 的所有資料（SQLite、向量、圖譜、第三方整合映射）。此操作不可逆。"
  run_remote "rm -rf $REMOTE_DATA_DIR/users/$uid"
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

# ── 指令：container-run <cmd...> ─────────────────────────────────────────────
# 在 Docker container 內執行指令（自動包 docker exec）
cmd_container_run() {
  [[ -z "${1:-}" ]] && err "用法: $0 container-run \"<cmd>\""
  run_remote "docker inspect -f '{{.State.Running}}' $CONTAINER 2>/dev/null" \
    | grep -q true || err "容器 $CONTAINER 未在運行"
  info "在容器 $CONTAINER 內執行指令"
  run_remote "docker exec $CONTAINER $*"
}

# ── 指令：migrate-run <cmd...> ───────────────────────────────────────────────
# backup + 在 container 內執行遷移指令 + 自動重啟（清 in-memory cache）
cmd_migrate_run() {
  [[ -z "${1:-}" ]] && err "用法: $0 migrate-run \"<cmd>\""
  cmd_backup
  cmd_container_run "$@"
  info "遷移完成，重啟容器以清除 in-memory cache"
  cmd_restart
}

# ── 在容器內執行 argv（非 shell 字串）──────────────────────────────────────
# 與 cmd_container_run 的差別:後者契約是「遠端 shell 指令字串」(pipe/redirect 生效);
# 本函式契約是「一組 argv」——每個 arg 用 printf %q 轉義,讓遠端 bash 重新解析後
# 還原出完全相同的 argv。SQL 中的引號 / 括號 / % 因此原封不動抵達 ops_cli.py,
# 不再被 shell 二次解析破壞（這正是 container-script 早已採用的安全序列化手法）。
container_exec_argv() {
  run_remote "docker inspect -f '{{.State.Running}}' $CONTAINER 2>/dev/null" \
    | grep -q true || err "容器 $CONTAINER 未在運行"
  info "在容器 $CONTAINER 內執行 argv"
  local quoted; quoted=$(printf ' %q' "$@")
  run_remote "docker exec $CONTAINER$quoted"
}

# ── 指令：ops-cli <subcommand> [args] ───────────────────────────────────
cmd_ops_cli() {
  [[ -z "${1:-}" ]] && err "用法: $0 ops-cli <subcommand> [args...]"
  container_exec_argv python3 /app/ops_cli.py "$@"
}

# ── 指令：ops-edit <subcommand> [args] ──────────────────────────────────
# ops_cli.py 的**寫入**對應面。dry-run 預設(不傳 --commit 只印 plan)、寫前自動
# 備份 user_dir、寫後讀回 verify、audit。安全模型在工具內(EditContext),故與
# ops-cli 同級 argv pass-through —— is_blocked_run 的 shell-string 過濾不適用
# (argv 不走 remote shell 解析,破壞性已由 --commit gate + 自動備份守護)。
cmd_ops_edit() {
  [[ -z "${1:-}" ]] && err "用法: $0 ops-edit <subcommand> [args...]"
  container_exec_argv python3 /app/ops_edit.py "$@"
}

# ── 指令：ops-edit-batch <local-plan.json> [runner args] ───────────────────
cmd_ops_edit_batch() {
  local plan="${1:-}"
  [[ -z "$plan" ]] && err "用法: $0 ops-edit-batch <local-plan.json> [runner args...]"
  [[ ! -f "$plan" ]] && err "檔案不存在: $plan"
  local runner; runner="$(cd "$(dirname "$0")" && pwd)/ops/ops_edit_batch.py"
  [[ -f "$runner" ]] || err "batch runner 不存在: $runner"

  local remote_runner remote_plan
  remote_runner="$(make_remote_tmp_path "ops_edit_batch" ".py")"
  remote_plan="$(make_remote_tmp_path "ops_edit_batch_plan" ".json")"

  info "上傳 batch runner + plan → container"
  copy_local_to_container "$runner" "$remote_runner"
  copy_local_to_container "$plan" "$remote_plan"

  shift
  local quoted_args=""
  if [[ $# -gt 0 ]]; then
    quoted_args=$(printf ' %q' "$@")
  fi

  local rc=0
  set +e
  run_remote "docker exec $CONTAINER python3 $remote_runner $remote_plan$quoted_args"
  rc=$?
  set -e
  cleanup_remote_tmp "$remote_runner" "$remote_plan"
  return "$rc"
}

# ── 指令：container-script <local-script> [args] ────────────────────────
cmd_container_script() {
  local script="${1:-}"
  [[ -z "$script" ]] && err "用法: $0 container-script <local-script.py> [args...]"
  [[ ! -f "$script" ]] && err "檔案不存在: $script"
  local ext="${script##*.}"
  [[ "$ext" == "py" || "$ext" == "sh" ]] || err "只允許 .py 和 .sh: $script"
  local base; base=$(basename "$script")
  local remote_tmp="/tmp/$base"
  info "上傳 $script → container"
  copy_local_to_container "$script" "$remote_tmp"
  shift
  local interp
  [[ "$ext" == "py" ]] && interp="python3" || interp="bash"
  # $@ 透過 SSH 會被 remote shell 重新解析，必須用 printf %q 安全序列化
  local quoted_args=""
  if [[ $# -gt 0 ]]; then
    quoted_args=$(printf ' %q' "$@")
  fi
  run_remote "docker exec $CONTAINER $interp $remote_tmp$quoted_args"
  cleanup_remote_tmp "$remote_tmp"
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
  container-run) cmd_container_run "${@:2}" ;;
  migrate-run)  cmd_migrate_run "${@:2}" ;;
  ops-cli)          cmd_ops_cli "${@:2}" ;;
  ops-edit)         cmd_ops_edit "${@:2}" ;;
  ops-edit-batch)   cmd_ops_edit_batch "${@:2}" ;;
  container-script) cmd_container_script "${@:2}" ;;
  ssh)          cmd_ssh ;;
  help|--help|-h|*)
    echo ""
    echo "devops.sh — BooksAndVocab KG API DevOps"
    echo ""
    echo "用法: ./devops.sh <command> [args]"
    echo ""
    echo "指令:"
    echo "  setup [env_file]        push-env + deploy 一條龍（初始化或 secret 變動時）
  push-env [file]         推送本地 .env 到遠端（預設: backend/.env）
  deploy                  standby git pull + build + health + smoke（需先 git push）
  restart                 重啟容器（不重新 build）
  migrate                 手動 fallback：對用戶 DB 補欄位（standby 正常由 app 啟動自動跑）"
    echo "  env-check               檢查遠端 .env 是否包含所有必要環境變數"
    echo "  env-drift               檢查本地/遠端 .env 是否一致（path key 正規化）"
    echo "  status                  Docker / CF Tunnel / 磁碟 / 用戶數概覽"
    echo "  logs [n]                最新 n 行日誌（預設 50）"
    echo "  backup                  備份 data/ 到本地 backups/"
    echo "  users                   列出所有遠端用戶 + users.json"
    echo "  user-info <id>          查看特定用戶單字統計"
    echo "  delete-user <id> [--yes]  刪除用戶資料（--yes 跳過確認，或設 DEVOPS_YES=1）"
    echo "  run \"<cmd>\"             在遠端 host 執行任意指令"
    echo "  container-run \"<cmd>\"   在 Docker 容器內執行指令"
    echo "  migrate-run \"<cmd>\"     container-run + 自動重啟（清 cache）"
    echo "  ops-cli <sub> [args]    在容器內執行 ops_cli.py <sub> [args]（唯讀查詢）"
    echo "  ops-edit <sub> [args]   在容器內執行 ops_edit.py <sub> [args]（寫入,dry-run 預設）"
    echo "  ops-edit-batch <plan>   上傳本地 batch plan 到容器並一次執行（高頻 shaping 用）"
    echo "  container-script <file> [args]  上傳本地腳本到容器內執行（.py/.sh）"
    echo "  ssh                     開啟互動式 SSH（人工用，agent 改用 run）"
    echo ""
    echo "Agent 環境變數:"
    echo "  DEVOPS_YES=1            自動確認所有危險操作"
    echo ""
    ;;
esac
