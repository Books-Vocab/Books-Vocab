#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Keep the safe surface and the base entrypoint on one command registry.  The
# registry is source-only; loading it does not contact the remote host.
source "$ROOT_DIR/ops/lib/devops_command_registry.sh"
# One destructive-command predicate for the wrapper AND the base (see the lib header).
source "$ROOT_DIR/ops/lib/devops_run_guard.sh"
devops_command_registry_validate || {
  echo "✗ devops command registry is inconsistent" >&2
  exit 70
}
# KG_DEVOPS_BASE is a test seam (point it at a stub like /usr/bin/true to assert
# the blocklist without invoking the real remote wrapper). Defaults to devops.sh.
BASE="${KG_DEVOPS_BASE:-$ROOT_DIR/devops.sh}"
KG_PUBLIC_DOMAIN="${KG_PUBLIC_DOMAIN:-wordnexus.lol}"

[[ -x "$BASE" ]] || { echo "✗ base devops.sh not found or not executable: $BASE" >&2; exit 1; }

safe_usage() {
  local blocked="" command
  printf 'kg safe wrapper\n\nusage:\n'
  devops_safe_command_help_lines "$0"
  for command in "${DEVOPS_BLOCKED_COMMANDS[@]}"; do
    [[ -n "$blocked" ]] && blocked+=" / "
    blocked+="$command"
  done
  printf '\nblocked by default:\n  %s / any destructive run command / sensitive file reads (users.json, .env, keys)\n' "$blocked"
}

preflight() {
  # 診斷 banner 一律走 stderr — stdout 只留命令 payload，讓 ops-cli --json
  # 可被 `| jq` / json.loads 直接 parse（dogfooding 發現的契約缺陷）。
  {
    echo "[Preflight]"
    echo "project   : kg"
    echo "root      : $ROOT_DIR"
    echo "base      : $BASE"
    echo "server    : ${KG_SERVER:-chenliangyu@100.118.39.104} (standby/felix, via Tailscale)"
    echo "remote    : ${KG_REMOTE_DIR:-~/kg-prod/backend}"
    echo "data      : ${KG_REMOTE_DATA_DIR:-~/kg-data}"
    echo "ingress   : Cloudflare Tunnel (no Caddy on standby)"
    echo "domain    : $KG_PUBLIC_DOMAIN"
    echo "container : knowledge-graph-api"
  } >&2
}

run_fixed_remote() {
  preflight
  "$BASE" run "$1"
}

typed_alias_for_run() {
  case "$1" in
    "sudo systemctl status caddy") echo "caddy-status --json" ;;
    "cat /etc/caddy/Caddyfile") echo "caddyfile" ;;
    "docker ps") echo "docker-ps" ;;
    "df -h") echo "disk-usage" ;;
    "free -m") echo "memory-usage --json" ;;
    "docker stats --no-stream") echo "docker-stats" ;;
    docker\ logs\ knowledge-graph-api\ -n\ *) echo "docker-logs" ;;
    *) return 1 ;;
  esac
}

# Deny-list for reads of secret-bearing files (#2134, option A). It stops
# accidental and naive reads only and is NOT a security boundary: globbing
# (`cat u*`), string assembly (`python3 -c`, base64), variable indirection and
# os.environ inside the container all bypass it. docs/policy/safety.md owns the
# policy; agents read users through the typed `users` command, never via run.
is_sensitive_read() {
  local cmd re
  # Lowercase and drop quotes/backticks/backslashes so "USERS.JSON" and
  # users\.json normalise to the same token. LC_ALL=C: byte-wise, never fails on
  # non-UTF-8 script bytes (a failing tr would silently fail open).
  cmd="$(printf '%s' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]' | LC_ALL=C tr -d '\042\047\140\134')"
  local -a patterns=(
    'users\.json'                                          # _email_index, email, subscription, linked_ids
    '(^|[^a-z0-9_])\.env([^a-z0-9_]|$)'                    # backend secrets (.env, .env.prod; not os.environ)
    '(^|[^a-z0-9_])\.secrets([^a-z0-9_]|$)'                # operator credential dir synced to felix
    '\.(pem|p8|p12)([^a-z0-9_]|$)'                         # TLS / App Store Connect key material
    '(^|[^a-z0-9_])id_(rsa|ecdsa|ed25519)([^a-z0-9_.]|$)'  # ssh private keys (not .pub)
  )
  for re in "${patterns[@]}"; do
    [[ "$cmd" =~ $re ]] && return 0
  done
  return 1
}

refuse_sensitive_read() {
  echo "✗ blocked sensitive file read (users.json / .env / ~/.secrets / private keys)" >&2
  echo "  use the typed \`users\` command; policy and its limits: docs/policy/safety.md" >&2
  exit 1
}

# logs / docker-logs splice the line count into a remote shell string, so a
# value like `1; cat users.json` would bypass both guards above: digits only.
require_line_count() {  # <sub> <n>
  [[ "$2" =~ ^[0-9]+$ ]] || { echo "✗ usage: $0 $1 [n]  (n: line count, digits only)" >&2; exit 64; }
}

main() {
  local sub="${1:-}"

  if ! devops_safe_command_registered "$sub" && ! devops_command_blocked "$sub"; then
    safe_usage
    exit 1
  fi

  # ── transport retarget（2026-06-19）────────────────────────────────────────
  # devops.sh transport 已從停用的 Lightsail retarget 到家用 standby（felix，
  # 經 Cloudflare Tunnel）。deploy/restart/migrate 現對 standby 生效 = 正式站。
  # 破壞性 run 命令仍由 devops_run_guard_enforce 守護；deploy 仍要求本地 working tree 乾淨
  # 且已 git push（standby 靠 git pull 取碼）。
  # backup-s3-test 的舊 Lightsail cron（/usr/local/bin/kg_backup.sh）在 standby
  # 不適用 → 改成指向 standby launchd com.kg.backup（見下方 handler）。

  # Registry owns membership/help/blocked policy.  The explicit arms below are
  # intentionally kept as the safety boundary: each arm validates its own
  # argument shape before delegating to the base entrypoint or a fixed probe.
  # This is execution policy, not a second command inventory.
  case "$sub" in
    preflight)
      preflight
      ;;
    deploy|restart|status|backup|env-check|env-drift|migrate)
      preflight
      "$BASE" "$sub"
      ;;
    users)
      # #2098：只有固定的 count + uid 摘要。多餘參數（例如未來的 --raw）一律拒絕，
      # safe surface 上不存在整檔 dump 路徑。
      [[ $# -eq 1 ]] || { echo "✗ usage: $0 users" >&2; exit 64; }
      preflight
      "$BASE" users
      ;;
    backup-s3-test)
      # standby：排程備份由 launchd `com.kg.backup` → S3 跑（非 Lightsail cron）。
      # 此命令做唯讀驗證：backup_status.sh fail-closed 檢查 job、穩定 log 格式與 36h freshness。
      # helper 與生產 checkout 同步，故從 backend 目錄以 ../ops 路徑呼叫。
      # 手動觸發/排程細節見 ~/butler/docs/kg-backend-deployment.md §4.5 / §7 G5。
      run_fixed_remote "cd ${KG_REMOTE_DIR:-~/kg-prod/backend} && ../ops/backup_status.sh"
      ;;
    logs)
      shift
      local n="${1:-80}"
      require_line_count logs "$n"
      preflight
      "$BASE" logs "$n"
      ;;
    caddy-status)
      # 相容保留 caddy-status 名稱，但 payload 是固定 Cloudflare Tunnel schema。
      # 不走 preflight：成功時 stderr 必須為空，避免 JSON consumer 被診斷污染。
      shift
      [[ "${1:-}" == "--json" && -z "${2:-}" ]] || {
        echo "✗ usage: $0 caddy-status --json" >&2
        exit 64
      }
      KG_BASE="$BASE" "$ROOT_DIR/ops/infra_health.sh" --caddy-status --json
      ;;
    caddyfile)
      # 無本地 Caddyfile；CF Tunnel ingress 是 remotely-managed（存 CF 端）。
      echo "ℹ caddyfile 不適用（standby 走 CF Tunnel，ingress 為 CF remotely-managed config）" >&2
      echo "  ingress 正本見 ~/butler/docs/kg-backend-deployment.md §3.1" >&2
      ;;
    docker-ps)
      run_fixed_remote "docker ps"
      ;;
    docker-logs)
      shift
      local n="${1:-100}"
      require_line_count docker-logs "$n"
      run_fixed_remote "docker logs knowledge-graph-api -n $n"
      ;;
    disk-usage)
      run_fixed_remote "df -h"
      ;;
    memory-usage)
      # Felix 是 macOS；Linux free -m 在 standby 上不存在。沿用 infra_health
      # 的 vm_stat/sysctl 單一解析來源，輸出固定四欄 JSON。
      shift
      [[ "${1:-}" == "--json" && -z "${2:-}" ]] || {
        echo "✗ usage: $0 memory-usage --json" >&2
        exit 64
      }
      KG_BASE="$BASE" "$ROOT_DIR/ops/infra_health.sh" --memory-usage --json
      ;;
    docker-stats)
      run_fixed_remote "docker stats --no-stream"
      ;;
    health)
      # host 層唯讀健康聚合（系統資源 + 容器 + Cloudflare Tunnel + TLS 憑證 + 近期錯誤）。
      # 全唯讀，補 ops-cli（讀業務 DB）看不到的機器層盲區。--json 走 stdout。
      # data dir 單一真相：由本 wrapper 已知的 standby 路徑注入 infra_health（兩處不各寫死）。
      preflight
      shift
      KG_DATA_DIR="${KG_REMOTE_DATA_DIR:-/Users/chenliangyu/kg-data}" \
      KG_PROD_REPO="${KG_REMOTE_PROD_REPO:-/Users/chenliangyu/kg-prod}" \
        "$ROOT_DIR/ops/infra_health.sh" "$@"
      ;;
    user-info)
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 user-info <id>" >&2; exit 1; }
      "$BASE" user-info "$1"
      ;;
    run|container-run|migrate-run)
      # All three forward an arbitrary command string to $BASE through the same
      # dangerous-command gate; $sub holds the matched subcommand verbatim.
      preflight
      shift
      local raw="${*:-}"
      [[ -n "$raw" ]] || { echo "✗ usage: $0 $sub \"<cmd>\"" >&2; exit 1; }
      if [[ "$sub" == "run" ]]; then
        local typed_alias
        if typed_alias="$(typed_alias_for_run "$raw")"; then
          echo "✗ use typed command: $typed_alias" >&2
          exit 1
        fi
      fi
      # Same predicate the base devops.sh enforces (ops/lib/devops_run_guard.sh):
      # the wrapper is no longer the only line of defense.
      devops_run_guard_enforce "$sub" "$raw"
      if is_sensitive_read "$raw"; then
        refuse_sensitive_read
      fi
      "$BASE" "$sub" "$raw"
      ;;
    ops-cli)
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 ops-cli <subcommand> [args...]" >&2; exit 1; }
      "$BASE" ops-cli "$@"
      ;;
    ops-edit)
      # 寫入工具(ops_cli 的可寫對應面)。安全模型在工具內:dry-run 預設、寫前自動
      # 備份、寫後 verify、audit、restore 可回退。argv pass-through(不走 shell,
      # devops_run_guard_enforce 不適用);破壞性由 --commit gate 守護。
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 ops-edit <subcommand> [args...]" >&2; exit 1; }
      "$BASE" ops-edit "$@"
      ;;
    ops-edit-batch)
      # 高頻 shaping / demo materialize 用的 batch surface：本地 plan 上傳到 container，
      # 由 runner 一次執行多個 ops_edit 子命令，避免單筆 round-trip 過慢。
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 ops-edit-batch <plan.json> [runner args...]" >&2; exit 1; }
      "$BASE" ops-edit-batch "$@"
      ;;
    container-script)
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 container-script <script> [args...]" >&2; exit 1; }
      # #2134：腳本內容與參數套用同一份敏感檔 deny-list。argv 不經 remote shell 解析，
      # 所以 devops_run_is_blocked 的毀滅字串 guard 不適用，但「讀了什麼」是同一個問題。
      local script_body=""
      [[ -f "$1" ]] && script_body="$(<"$1")"
      if is_sensitive_read "$* $script_body"; then
        refuse_sensitive_read
      fi
      "$BASE" container-script "$@"
      ;;
    *)
      if devops_command_blocked "$sub"; then
        echo "✗ blocked in safe wrapper: $sub" >&2
        echo "  if you really need it, run base devops.sh manually with explicit review" >&2
        exit 1
      fi
      safe_usage
      exit 1
      ;;
  esac
}

main "$@"
