#!/usr/bin/env bash
# ios_install.sh — provenance-gated iOS app installation.
#
# Usage:
#   ./ops/ios_install.sh --simulator <udid> [--app <path>] [--configuration Debug]
#   ./ops/ios_install.sh --device <udid> [--app <path>] [--configuration Debug]
#
# The app must have been produced by ios_build.sh from this worktree at its
# current HEAD.  --dry-run validates provenance but does not call xcrun.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/ios_install_provenance.sh
source "$SCRIPT_DIR/lib/ios_install_provenance.sh"

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"; }

MODE=""
TARGET=""
APP=""
CONFIGURATION="Debug"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --simulator|--device)
      [[ -z "$MODE" ]] || { echo "error: --simulator and --device are mutually exclusive" >&2; exit 64; }
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "error: $1 requires a device identifier" >&2; exit 64; }
      MODE="${1#--}"
      TARGET="$2"
      shift 2
      ;;
    --app)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "error: --app requires a path" >&2; exit 64; }
      APP="$2"
      shift 2
      ;;
    --configuration)
      [[ $# -ge 2 ]] || { echo "error: --configuration requires Debug or Release" >&2; exit 64; }
      CONFIGURATION="$2"
      shift 2
      ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 64 ;;
  esac
done

[[ -n "$MODE" ]] || { echo "error: choose --simulator <udid> or --device <udid>" >&2; exit 64; }
[[ "$CONFIGURATION" == Debug || "$CONFIGURATION" == Release ]] || {
  echo "error: --configuration must be Debug or Release" >&2
  exit 64
}

if [[ -z "$APP" ]]; then
  DERIVED_DATA_ROOT="$(kg_ios_shared_derived_data_root "$PROJECT_ROOT")"
  APP="$(kg_ios_install_app_path "$DERIVED_DATA_ROOT" "$CONFIGURATION" "$MODE")"
fi
SIDECAR="$(kg_ios_install_provenance_path "$APP")"

kg_ios_validate_install_provenance "$PROJECT_ROOT" "$APP" "$SIDECAR"

if [[ "$MODE" == simulator ]]; then
  INSTALL_COMMAND=(xcrun simctl install "$TARGET" "$APP")
else
  INSTALL_COMMAND=(xcrun devicectl device install app --device "$TARGET" "$APP")
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  printf 'argv='
  printf '%q ' "${INSTALL_COMMAND[@]}"
  printf '\n'
  exit 0
fi

echo "[ios_install] installing app=$APP target=$TARGET mode=$MODE"
"${INSTALL_COMMAND[@]}"
echo "[ios_install] install succeeded target=$TARGET"
