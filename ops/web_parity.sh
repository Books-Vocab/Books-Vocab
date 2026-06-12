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
# With --check, after the audit it runs the verdict gate
# (design-system/parity/parity-verdict.mjs) against the committed baseline and
# exits non-zero on any regression / over-ceiling new case / missing case —
# turning the measured numbers into an actual pass/fail. --bless rewrites the
# baseline from the current run (the explicit "accept current state" action).
#
# Usage:  ops/web_parity.sh [--audit] [--check] [--bless] [--only <sub>] [--no-build]
# Env:    KG_CATALOG_ROOT  catalog snapshot root override (worktrees have an
#         empty build/, so point this at the main repo's snapshot root)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'USAGE'
Usage: ops/web_parity.sh [--audit] [--check] [--bless] [--fast] [--only <case-substring>] [--no-build]
  --audit      also run the per-case drill-down audit (diff/zoom/palette/metrics)
  --check      after the audit, run the verdict gate vs the committed baseline
               (exit non-zero on regression / over-ceiling new case / missing); implies --audit
  --bless      rewrite the baseline from the current audit run; implies --audit
  --fast       metrics-only: skip the contact sheet + per-case diff/zoom/palette/phash.
               ~4× faster; the gated numbers (rmse/mae/ssim) are identical. Use for
               bless/check loops; drop --fast (full audit) when you need to eyeball a case.
  --only SUB   restrict the audit to cases whose name contains SUB
  --no-build   skip the vite build (use when web/dist is fresh)
Env: KG_CATALOG_ROOT  catalog snapshot root override (worktrees have an empty build/)
USAGE
}

AUDIT=0
CHECK=0
BLESS=0
FAST=0
ONLY=""
NO_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --audit) AUDIT=1 ;;
    --check) CHECK=1; AUDIT=1 ;;
    --bless) BLESS=1; AUDIT=1 ;;
    --fast) FAST=1 ;;
    --only) ONLY="${2:?--only needs a case substring}"; shift ;;
    --no-build) NO_BUILD=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$BLESS" == 1 && "$CHECK" == 1 ]]; then
  echo "--bless and --check are mutually exclusive (bless rewrites the very baseline check verifies)" >&2
  exit 2
fi

shot_args=()
[[ "$NO_BUILD" == 1 ]] && shot_args+=(--no-build)
# --only scopes BOTH capture and audit to matching cases (shots.mjs supports it):
# without forwarding here, --only re-shot all 67 cases just to audit a few.
[[ -n "$ONLY" ]] && shot_args+=(--only "$ONLY")
# Phase banners + heartbeat so the run is NEVER silent. The node tools print
# live per-item progress, but a phase can still have an internal quiet stretch
# (vite bundling, chromium launch before the first shot). run_phase runs the
# command in the background and emits a heartbeat every HEARTBEAT_SECS until it
# exits, guaranteeing output at least that often regardless of what's inside.
banner() { printf '\n══ %s ══\n' "$1" >&2; }
HEARTBEAT_SECS="${PARITY_HEARTBEAT_SECS:-15}"

run_phase() {
  local label="$1"; shift
  banner "$label"
  "$@" &
  local pid=$! secs=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep "$HEARTBEAT_SECS"
    kill -0 "$pid" 2>/dev/null || break
    secs=$((secs + HEARTBEAT_SECS))
    printf '  ⏳ %s … still running (%ds)\n' "$label" "$secs" >&2
  done
  wait "$pid"  # propagate the phase's exit code (set -e aborts the run on failure)
}

run_phase "build + capture" node web/tools/shots.mjs "${shot_args[@]+"${shot_args[@]}"}"

# The contact sheet (compare.mjs) is a human review artifact and itself a heavy
# all-pairs montage; --fast skips it (bless/check read metrics, not the sheet).
if [[ "$FAST" != 1 ]]; then
  run_phase "contact sheet" node web/tools/compare.mjs
fi

if [[ "$AUDIT" == 1 ]]; then
  [[ "$FAST" == 1 ]] && audit_label="audit (per-case metrics, fast/metrics-only)" || audit_label="audit (per-case metrics)"
  audit_args=()
  [[ -n "$ONLY" ]] && audit_args+=(--only "$ONLY")
  [[ "$FAST" == 1 ]] && audit_args+=(--metrics-only)
  run_phase "$audit_label" node web/tools/parity-audit.mjs "${audit_args[@]+"${audit_args[@]}"}"
fi

if [[ "$BLESS" == 1 ]]; then
  run_phase "bless (rewrite baseline)" node design-system/parity/parity-verdict.mjs --update
fi

if [[ "$CHECK" == 1 ]]; then
  run_phase "verdict gate (--check)" node design-system/parity/parity-verdict.mjs --check
fi
