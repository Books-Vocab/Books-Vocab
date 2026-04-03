#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$ROOT_DIR/devops.sh"

[[ -x "$BASE" ]] || { echo "✗ base devops.sh not found or not executable: $BASE" >&2; exit 1; }

safe_usage() {
  cat <<USAGE
kg safe wrapper

usage:
  $0 preflight
  $0 deploy
  $0 restart
  $0 status
  $0 logs [n]
  $0 backup
  $0 env-check
  $0 env-drift
  $0 migrate
  $0 users
  $0 user-info <id>
  $0 run "<remote command>"
  $0 container-run "<cmd>"
  $0 migrate-run "<cmd>"
  $0 ops-cli <subcommand> [args...]
  $0 container-script <script> [args...]

blocked by default:
  setup / push-env / delete-user / ssh / any destructive run command
USAGE
}

preflight() {
  echo "[Preflight]"
  echo "project   : kg"
  echo "root      : $ROOT_DIR"
  echo "base      : $BASE"
  echo "server    : ubuntu@54.95.189.179"
  echo "remote    : ~/knowledge_graph_api"
  echo "domain    : wordnexus.lol"
  echo "container : knowledge-graph-api"
}

is_blocked_run() {
  local cmd="$1"
  [[ "$cmd" =~ (down[[:space:]]+-v|docker[[:space:]]+system[[:space:]]+prune|rm[[:space:]]+-rf[[:space:]]+/|rm[[:space:]]+-rf[[:space:]]+~|delete-user) ]]
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
    logs)
      preflight
      shift
      "$BASE" logs "${1:-80}"
      ;;
    user-info)
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 user-info <id>" >&2; exit 1; }
      "$BASE" user-info "$1"
      ;;
    run)
      preflight
      shift
      local raw="${*:-}"
      [[ -n "$raw" ]] || { echo "✗ usage: $0 run \"<cmd>\"" >&2; exit 1; }
      if is_blocked_run "$raw"; then
        echo "✗ blocked dangerous command" >&2
        exit 1
      fi
      "$BASE" run "$raw"
      ;;
    container-run)
      preflight
      shift
      local raw="${*:-}"
      [[ -n "$raw" ]] || { echo "✗ usage: $0 container-run \"<cmd>\"" >&2; exit 1; }
      if is_blocked_run "$raw"; then
        echo "✗ blocked dangerous command" >&2
        exit 1
      fi
      "$BASE" container-run "$raw"
      ;;
    migrate-run)
      preflight
      shift
      local raw="${*:-}"
      [[ -n "$raw" ]] || { echo "✗ usage: $0 migrate-run \"<cmd>\"" >&2; exit 1; }
      if is_blocked_run "$raw"; then
        echo "✗ blocked dangerous command" >&2
        exit 1
      fi
      "$BASE" migrate-run "$raw"
      ;;
    ops-cli)
      preflight
      shift
      [[ -n "${1:-}" ]] || { echo "✗ usage: $0 ops-cli <subcommand> [args...]" >&2; exit 1; }
      "$BASE" ops-cli "$@"
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
