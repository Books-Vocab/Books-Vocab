#!/usr/bin/env bash
# ios_ops.sh — unified iOS ops entrypoint for agents and humans.
#
# Usage:
#   ./ops/ios_ops.sh status
#   ./ops/ios_ops.sh build [ios_build.sh args...]
#   ./ops/ios_ops.sh test [ios_test.sh args...]
#   ./ops/ios_ops.sh test --cache-status [--unit|--ui|--all-targets] [--json]
#   ./ops/ios_ops.sh test --prepare-cache [--unit|--ui|--all-targets] [--json]
#   ./ops/ios_ops.sh test --clean-cache [--unit|--ui|--all-targets] [--json]
#   ./ops/ios_ops.sh archive [--upload] [ios_release.sh args...]
#   ./ops/ios_ops.sh archives [list|latest|inspect ...]
#   ./ops/ios_ops.sh issues --log <xcodebuild.log> [--json]
#   ./ops/ios_ops.sh logs [--since 5m] [--predicate <predicate>] [--limit 200] [--json]
#   ./ops/ios_ops.sh sentry
#   ./ops/ios_ops.sh doctor [--json]
#   ./ops/ios_ops.sh workflow release [--json]
#   ./ops/ios_ops.sh gate release [--json]
#   ./ops/ios_ops.sh xcode [--json]
#   ./ops/ios_ops.sh simulator status [--json]
#   ./ops/ios_ops.sh simulator ensure-booted [--device <udid|name>] [--json]
#   ./ops/ios_ops.sh simulator launch [--json] [-- app args...]
#   ./ops/ios_ops.sh simulator terminate [--json]
#   ./ops/ios_ops.sh simulator screenshot [--out <png>] [--device booted] [--json]
#   ./ops/ios_ops.sh runs [--json]
#   ./ops/ios_ops.sh snapshot [--json] [--skip-xcode] [--skip-simulator] [--include-logs] [--log-since 5m] [--log-limit 200]
#   ./ops/ios_ops.sh catalog prepare [--destination <xcodebuild-destination>] [--json]
#   ./ops/ios_ops.sh catalog snapshots [--out-root <dir>] [--destination <xcodebuild-destination>] [--group <category>]... [--scenario <category/title>]... [--dataset <name> | --dataset-file <path>] [--reuse-build] [--json]
#   ./ops/ios_ops.sh catalog clean [--json]
#   ./ops/ios_ops.sh commands [--json]
#
# Side-effect model:
# - status/archives/issues/logs/sentry/doctor/workflow/gate/xcode/simulator status/runs/snapshot/dashboard/commands are read-only.
# - build/test/archive/simulator screenshot/catalog snapshots are local machine side effects.
# - archive only uploads when --upload is passed through explicitly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }

# shellcheck source=lib/ios_ops_core.sh
source "$SCRIPT_DIR/lib/ios_ops_core.sh"

# shellcheck source=lib/ios_ops_commands.sh
source "$SCRIPT_DIR/lib/ios_ops_commands.sh"

cmd_status() {
  local version build
  read_project_settings version build
  echo "[ios][status] project_version=${version:-unknown} project_build=${build:-unknown}"
  "$SCRIPT_DIR/ios_archive.sh" latest 2>/dev/null | tail -1 | awk -F'\t' 'NF>=6 {printf "[ios][status] organizer_latest=%s(%s) archive=%s\n", $4, $5, $6}'
  "$SCRIPT_DIR/asc.sh" builds 2>/dev/null | sed 's/^/[ios][status] /' || true
}

# shellcheck source=lib/ios_ops_logs.sh
source "$SCRIPT_DIR/lib/ios_ops_logs.sh"

# shellcheck source=lib/ios_ops_release.sh
source "$SCRIPT_DIR/lib/ios_ops_release.sh"

# shellcheck source=lib/ios_ops_xcode.sh
source "$SCRIPT_DIR/lib/ios_ops_xcode.sh"

# shellcheck source=lib/ios_ops_simulator.sh
source "$SCRIPT_DIR/lib/ios_ops_simulator.sh"

# shellcheck source=lib/ios_ops_runs.sh
source "$SCRIPT_DIR/lib/ios_ops_runs.sh"

# shellcheck source=lib/ios_ops_snapshot.sh
source "$SCRIPT_DIR/lib/ios_ops_snapshot.sh"

# shellcheck source=lib/ios_ops_catalog.sh
source "$SCRIPT_DIR/lib/ios_ops_catalog.sh"

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
  workflow|flow) cmd_workflow "$@" ;;
  gate|verdict) cmd_gate "$@" ;;
  xcode|environment) cmd_xcode "$@" ;;
  simulator|sim) cmd_simulator "$@" ;;
  runs|reports) cmd_runs "$@" ;;
  snapshot|dashboard) cmd_snapshot "$@" ;;
  catalog) cmd_catalog "$@" ;;
  commands|capabilities) cmd_commands "$@" ;;
  -h|--help|help) usage ;;
  *)
    echo "✗ unknown subcommand: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
