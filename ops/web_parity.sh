#!/usr/bin/env bash
#
# web_parity.sh — web app ⟷ iOS visual-parity tooling.
#
# Captures every web parity case in headless Chromium (Playwright) at
# 1179×2556 (iPhone @3x — same dims as Catalog snapshot PNGs), then composites
# each web shot beside the iOS Catalog surface it should mirror into ONE
# contact sheet. With --audit, also emits per-case diff, zoomed crop strips,
# palette summaries, and numeric metrics via the shared parity engine
# (design-system/parity/parity-core.mjs — same engine as ops/chrome_parity.sh).
#
# iOS references come from the Catalog snapshot system (source-SoT, regenerable
# via `./ops/ios_ops.sh catalog snapshots`), addressed by {surface, scenario,
# appearance} in web/tools/parity-manifest.mjs.
#
# Output:
#   web/tools/shots/*.png        per-case web renders
#   web/tools/compare/*.png      per-case web|iOS pairs
#   web/tools/compare/contact.png    the single review sheet
#   web/tools/audit/<case>/*     --audit drill-down artifacts
#   (all git-ignored — regenerable)
#
# Usage:  ops/web_parity.sh [--audit] [--only <case-substring>] [--no-build]
# Env:    KG_CATALOG_ROOT  catalog snapshot root override (worktrees have an
#         empty build/, so point this at the main repo's snapshot root)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'USAGE'
Usage: ops/web_parity.sh [--audit] [--only <case-substring>] [--no-build]
  --audit      also run the per-case drill-down audit (diff/zoom/palette/metrics)
  --only SUB   restrict the audit to cases whose name contains SUB
  --no-build   skip the vite build (use when web/dist is fresh)
Env: KG_CATALOG_ROOT  catalog snapshot root override (worktrees have an empty build/)
USAGE
}

AUDIT=0
ONLY=""
NO_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --audit) AUDIT=1 ;;
    --only) ONLY="${2:?--only needs a case substring}"; shift ;;
    --no-build) NO_BUILD=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

shot_args=()
[[ "$NO_BUILD" == 1 ]] && shot_args+=(--no-build)
node web/tools/shots.mjs "${shot_args[@]+"${shot_args[@]}"}"

node web/tools/compare.mjs

if [[ "$AUDIT" == 1 ]]; then
  audit_args=()
  [[ -n "$ONLY" ]] && audit_args+=(--only "$ONLY")
  node web/tools/parity-audit.mjs "${audit_args[@]+"${audit_args[@]}"}"
fi
