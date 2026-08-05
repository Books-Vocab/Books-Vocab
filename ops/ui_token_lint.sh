#!/usr/bin/env bash
# ui_token_lint.sh — gate raw spacing/radius/shadow/color/font magic numbers.
#
# Sibling to ops/i18n_lint.sh and ops/catalyst_lint.sh: every visual constant in
# the iOS app must flow through a design token instead of a literal.
#
#   raw .padding(<number>)                   → AppSpacing.sN
#   raw .shadow(...)                         → .appElevation(.zN)
#   RoundedRectangle(cornerRadius: <number>) → AppRoundedRect(roundness: AppRoundness.*)
#   .cornerRadius(<number>)                  → AppRadius.*
#   raw hex color (Color(hex:/0xRRGGBB/#RGB) → AppColors.*
#   .font(.system(size: <number>))           → AppFonts.*
#
# Modes:
#   --report         (default) Print findings (file:line), exit 0. Local discovery.
#   --baseline       Write the current normalized finding set to ops/ui_token_baseline.txt.
#   --baseline-check Set-difference vs baseline; fail (exit 1) only on NEW findings.
#   --strict         Any finding fails (exit 1). CI gate.
#
# Allowlist: `// token-allow: <reason>` on the same line exempts that line.
#
# Exclusions: AppMetrics.swift (AppElevation/AppShadows impl), AppColors.swift
#   (hex definition source), **/Debug/**, *Preview*.swift, *Tests*.swift.
#
# Baseline is line-drift resistant (set of <relpath>::<pattern>::<snippet>), so
# unrelated edits that only shift line numbers do not regress. See ops/ui_token_lint.py.

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

exec "$UV_BIN" run --python 3.13 python ops/ui_token_lint.py "$@"
