#!/usr/bin/env bash
# ios_ops.sh — unified iOS ops entrypoint for agents and humans.
#
# Usage:
#   ./ops/ios_ops.sh status
#   ./ops/ios_ops.sh build [ios_build.sh args...]
#   ./ops/ios_ops.sh test [ios_test.sh args...]
#   ./ops/ios_ops.sh archive [--upload] [ios_release.sh args...]
#   ./ops/ios_ops.sh archives [list|latest|inspect ...]
#   ./ops/ios_ops.sh issues --log <xcodebuild.log> [--json]
#   ./ops/ios_ops.sh logs [--since 5m] [--predicate <predicate>]
#   ./ops/ios_ops.sh sentry
#   ./ops/ios_ops.sh doctor
#
# Side-effect model:
# - status/archives/issues/logs/sentry/doctor are read-only.
# - build/test/archive are local machine side effects.
# - archive only uploads when --upload is passed through explicitly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$ROOT/ios/BooksBrowser.xcodeproj"
SCHEME="BooksBrowser"

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }

cmd_status() {
  local version build
  version="$(xcodebuild -project "$XCODEPROJ" -target "$SCHEME" -configuration Release -showBuildSettings 2>/dev/null | awk -F' = ' '/ MARKETING_VERSION /{print $2; exit}' | tr -d '[:space:]')"
  build="$(xcodebuild -project "$XCODEPROJ" -target "$SCHEME" -configuration Release -showBuildSettings 2>/dev/null | awk -F' = ' '/ CURRENT_PROJECT_VERSION /{print $2; exit}' | tr -d '[:space:]')"
  echo "[ios][status] project_version=${version:-unknown} project_build=${build:-unknown}"
  "$SCRIPT_DIR/ios_archive.sh" latest 2>/dev/null | tail -1 | awk -F'\t' 'NF>=6 {printf "[ios][status] organizer_latest=%s(%s) archive=%s\n", $4, $5, $6}'
  "$SCRIPT_DIR/asc.sh" builds 2>/dev/null | sed 's/^/[ios][status] /' || true
}

cmd_logs() {
  local since="5m" predicate='process == "BooksBrowser" OR subsystem BEGINSWITH "com.Max0228.BooksBrowser" OR subsystem BEGINSWITH "com.wordnexus"'
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --since) since="${2:?--since needs value}"; shift 2 ;;
      --predicate) predicate="${2:?--predicate needs value}"; shift 2 ;;
      -h|--help) echo "Usage: ./ops/ios_ops.sh logs [--since 5m] [--predicate <predicate>]"; return 0 ;;
      *) echo "✗ unknown logs option: $1" >&2; return 1 ;;
    esac
  done
  echo "[ios][logs] since=$since predicate=$predicate" >&2
  log show --style compact --last "$since" --predicate "$predicate" 2>/dev/null \
    | grep -vE 'runningboard\.assertions\.webkit|RBSServiceErrorDomain|ProcessAssertion' \
    || true
}

cmd_sentry() {
  local source="$ROOT/ios/BooksBrowser/Services/AppCrashReporting.swift"
  local has_sdk has_dsn_key
  grep -q 'canImport(Sentry)' "$source" && has_sdk=1 || has_sdk=0
  rg -q 'SentryDSN|SENTRY_ENABLED_IN_DEBUG|-sentryTest' "$ROOT/ios" && has_dsn_key=1 || has_dsn_key=0
  echo "[ios][sentry] source=$source"
  echo "[ios][sentry] can_import_guard=$has_sdk dsn_key_reference=$has_dsn_key"
  echo "[ios][sentry] debug_requires_env=SENTRY_ENABLED_IN_DEBUG=1 test_arg=-sentryTest"
  echo "[ios][sentry] release_name=bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION dist=CURRENT_PROJECT_VERSION"
}

cmd_doctor() {
  echo "[ios][doctor] phase=status"
  cmd_status
  echo "[ios][doctor] phase=sentry"
  cmd_sentry
  echo "[ios][doctor] phase=storekit"
  if rg -q 'StoreKit Configuration' "$ROOT/ios" "$XCODEPROJ" 2>/dev/null; then
    echo "[ios][doctor] storekit_config_reference=present"
  else
    echo "[ios][doctor] storekit_config_reference=unknown"
  fi
}

cmd="${1:-}"
[[ -n "$cmd" ]] || { usage; exit 0; }
shift || true

case "$cmd" in
  status) cmd_status "$@" ;;
  build) "$SCRIPT_DIR/ios_build.sh" "$@" ;;
  test) "$SCRIPT_DIR/ios_test.sh" "$@" ;;
  archive) "$SCRIPT_DIR/ios_release.sh" "$@" ;;
  release) "$SCRIPT_DIR/ios_release.sh" "$@" ;;
  archives) "$SCRIPT_DIR/ios_archive.sh" "${@:-list}" ;;
  issues) "$SCRIPT_DIR/ios_diagnostics.py" "$@" ;;
  logs) cmd_logs "$@" ;;
  sentry) cmd_sentry "$@" ;;
  doctor) cmd_doctor "$@" ;;
  -h|--help|help) usage ;;
  *)
    echo "✗ unknown subcommand: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
