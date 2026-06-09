#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# KG_DEVOPS_BASE is a test seam (point it at a stub like /usr/bin/true to assert
# the blocklist without invoking the real remote wrapper). Defaults to devops.sh.
BASE="${KG_DEVOPS_BASE:-$ROOT_DIR/devops.sh}"
KG_PUBLIC_DOMAIN="${KG_PUBLIC_DOMAIN:-wordnexus.lol}"

[[ -x "$BASE" ]] || { echo "✗ base devops.sh not found or not executable: $BASE" >&2; exit 1; }

safe_usage() {
  cat <<USAGE
kg safe wrapper

usage:
  $0 preflight
  $0 deploy
  $0 restart
  $0 status
  $0 health [--json]
  $0 logs [n]
  $0 caddy-status
  $0 caddyfile
  $0 docker-ps
  $0 docker-logs [n]
  $0 disk-usage
  $0 memory-usage
  $0 docker-stats
  $0 backup
  $0 backup-s3-test
  $0 env-check
  $0 env-drift
  $0 migrate
  $0 users
  $0 user-info <id>
  $0 run "<remote command>"
  $0 container-run "<cmd>"
  $0 migrate-run "<cmd>"
  $0 ops-cli <subcommand> [args...]
  $0 ops-edit <subcommand> [args...]
  $0 ops-edit-batch <plan.json> [runner args...]
  $0 container-script <script> [args...]

blocked by default:
  setup / push-env / delete-user / ssh / any destructive run command
USAGE
}

preflight() {
  # 診斷 banner 一律走 stderr — stdout 只留命令 payload，讓 ops-cli --json
  # 可被 `| jq` / json.loads 直接 parse（dogfooding 發現的契約缺陷）。
  {
    echo "[Preflight]"
    echo "project   : kg"
    echo "root      : $ROOT_DIR"
    echo "base      : $BASE"
    echo "server    : ubuntu@13.193.212.134"
    echo "remote    : ~/knowledge_graph_api"
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
    "sudo systemctl status caddy") echo "caddy-status" ;;
    "cat /etc/caddy/Caddyfile") echo "caddyfile" ;;
    "docker ps") echo "docker-ps" ;;
    "df -h") echo "disk-usage" ;;
    "free -m") echo "memory-usage" ;;
    "docker stats --no-stream") echo "docker-stats" ;;
    docker\ logs\ knowledge-graph-api\ -n\ *) echo "docker-logs" ;;
    *) return 1 ;;
  esac
}

is_blocked_run() {
  # Normalise so equivalent-but-differently-typed destructive commands can't
  # slip past a literal match:
  #   - lowercase (RM -RF)
  #   - drop quotes/backticks ("/home/ubuntu", '/')
  #   - ${HOME} brace form -> $home
  #   - collapse repeated slashes (/home//ubuntu)
  #   - turn shell separators ; | & ( ) into spaces so a protected path is
  #     always whitespace/EOL/'>'-bounded (rm -rf /home/ubuntu;)
  local cmd
  cmd="$(printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -d '\042\047\140' \
    | sed -E 's#\$\{home\}#$home#g; s#/+#/#g; s/[;|&()]/ /g')"

  # delete-user CLI
  [[ "$cmd" =~ delete-user ]] && return 0

  # Docker destructive cleanup: prune (system/volume/image/builder), volume rm,
  # and `compose down` with volume removal — all cause prod data loss.
  [[ "$cmd" =~ docker[[:space:]]+(system|volume|image|builder)[[:space:]]+prune ]] && return 0
  [[ "$cmd" =~ docker[[:space:]]+volume[[:space:]]+rm[[:space:]] ]] && return 0
  if [[ "$cmd" =~ (^|[[:space:]])down([[:space:]]|$) ]] \
     && [[ "$cmd" =~ (^|[[:space:]])(-v|--volume|--volumes)([[:space:]]|=|$) ]]; then
    return 0
  fi

  # Reference to a protected production path. Bare `/`, `~`, `$HOME` need a
  # trailing boundary so ordinary paths (/tmp/foo) don't match; named dirs
  # match themselves or any sub-path.
  # Bare `/` includes `*` and `.` in its trailing boundary so `rm -rf /*` and
  # `/.` (machine-wipe equivalents) are caught, not just a lone `rm -rf /`.
  local prot='(/([[:space:]>*.]|$)|~([[:space:]/>]|$)|\$home([[:space:]/>]|$)|/home/ubuntu([[:space:]/>]|$)|/root([[:space:]/>]|$)|/app/data([[:space:]/>]|$)|knowledge_graph_api|knowledge-graph-api_data)'

  # Recursive `rm` (any flag order/long form; also /bin/rm) at a protected path.
  if [[ "$cmd" =~ (^|[[:space:]]|/)rm[[:space:]] ]] \
     && [[ "$cmd" =~ ((^|[[:space:]])-[a-z]*r[a-z]*([[:space:]]|$)|--recursive|--no-preserve-root) ]] \
     && [[ "$cmd" =~ [[:space:]]$prot ]]; then
    return 0
  fi

  # find-based recursive deletion at a protected path.
  if [[ "$cmd" =~ (^|[[:space:]]|/)find[[:space:]] ]] \
     && [[ "$cmd" =~ (-delete|-exec[[:space:]]+rm) ]] \
     && [[ "$cmd" =~ [[:space:]]$prot ]]; then
    return 0
  fi

  # Clobbering a protected file: redirect, tee, truncate, or dd of=.
  [[ "$cmd" =~ \>[[:space:]]*$prot ]] && return 0
  if [[ "$cmd" =~ (^|[[:space:]]|/)(truncate|dd|tee)[[:space:]] ]] && [[ "$cmd" =~ $prot ]]; then
    return 0
  fi

  return 1
}

main() {
  local sub="${1:-}"
  case "$sub" in
    preflight)
      preflight
      ;;
    deploy|restart|status|backup|env-check|env-drift|migrate|users)
      preflight
      "$BASE" "$sub"
      ;;
    backup-s3-test)
      # Manually trigger /usr/local/bin/kg_backup.sh on prod and tail the log.
      # Cron does the same daily at UTC 03:00 — use this for ad-hoc verification
      # (e.g. after editing kg_backup.sh, before relying on it for a release).
      preflight
      "$BASE" run "sudo /usr/local/bin/kg_backup.sh && sudo tail -1 /var/log/kg_backup.log"
      ;;
    logs)
      preflight
      shift
      "$BASE" logs "${1:-80}"
      ;;
    caddy-status)
      run_fixed_remote "sudo systemctl status caddy"
      ;;
    caddyfile)
      run_fixed_remote "cat /etc/caddy/Caddyfile"
      ;;
    docker-ps)
      run_fixed_remote "docker ps"
      ;;
    docker-logs)
      shift
      run_fixed_remote "docker logs knowledge-graph-api -n ${1:-100}"
      ;;
    disk-usage)
      run_fixed_remote "df -h"
      ;;
    memory-usage)
      run_fixed_remote "free -m"
      ;;
    docker-stats)
      run_fixed_remote "docker stats --no-stream"
      ;;
    health)
      # host 層唯讀健康聚合（系統資源 + 容器 + Caddy + TLS 憑證 + 近期錯誤）。
      # 全唯讀，補 ops-cli（讀業務 DB）看不到的機器層盲區。--json 走 stdout。
      preflight
      shift
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
      if is_blocked_run "$raw"; then
        echo "✗ blocked dangerous command" >&2
        exit 1
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
      # is_blocked_run 不適用);破壞性由 --commit gate 守護。
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
      "$BASE" container-script "$@"
      ;;
    setup|push-env|delete-user|ssh)
      echo "✗ blocked in safe wrapper: $sub" >&2
      echo "  if you really need it, run base devops.sh manually with explicit review" >&2
      exit 1
      ;;
    *)
      safe_usage
      exit 1
      ;;
  esac
}

main "$@"
