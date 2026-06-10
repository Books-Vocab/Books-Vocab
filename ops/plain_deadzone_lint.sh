#!/usr/bin/env bash
# plain_deadzone_lint.sh — gate `.plain` Button labels with transparent dead zones.
#
# Sibling to ops/ui_token_lint.sh / ops/i18n_lint.sh. `buttonStyle(.plain)`
# hit-testing falls through transparent pixels: a label with a Spacer gap or a
# maxWidth-infinity frame and no `.contentShape` leaves the middle of the row
# dead (production bug caught by the Settings UI flow, fixed in PR #904).
#
# Modes:
#   --report         (default) Print findings (file:line), exit 0. Local discovery.
#   --baseline       Write the normalized finding set to ops/plain_deadzone_baseline.txt.
#   --baseline-check Set-difference vs baseline; fail (exit 1) only on NEW findings.
#   --strict         Any finding fails (exit 1). CI gate.
#
# Allowlist: `// deadzone-allow: <reason>` on the Button line or inside its extent.
# Exclusions: **/Debug/**, *Preview*.swift, *Tests*.swift.
# Baseline is line-drift resistant. See ops/plain_deadzone_lint.py.

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    UV_BIN="uv"
  fi
fi

exec "$UV_BIN" run --python 3.13 python ops/plain_deadzone_lint.py "$@"
