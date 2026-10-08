#!/usr/bin/env bash
# tap_a11y_lint.sh — gate `.onTapGesture` views that carry no accessibility semantics.
#
# Sibling to ops/plain_deadzone_lint.sh / ops/ui_token_lint.sh / ops/i18n_lint.sh.
# `.onTapGesture` gives VoiceOver no button trait and no selected state, and no
# 44pt hit target by itself (issue #2053). Use `Button`, or declare
# `.accessibilityAddTraits(.isButton)` / `.accessibilityAction` /
# `.accessibilityHidden(true)` after the gesture.
#
# Modes:
#   --report         (default) Print findings (file:line), exit 0. Local discovery.
#   --baseline       Write the normalized finding set to ops/tap_a11y_baseline.txt.
#   --baseline-check Set-difference vs baseline; fail (exit 1) only on NEW findings.
#   --strict         Any finding fails (exit 1).
#
# Allowlist: `// a11y-allow: <reason>` on the tap line, the comment line above it,
# or inside the call's extent.
# Exclusions: **/Debug/**, *Preview*.swift, *Tests*.swift.
# Baseline is line-drift resistant. See ops/tap_a11y_lint.py.

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

exec "$UV_BIN" run --python 3.13 python ops/tap_a11y_lint.py "$@"
