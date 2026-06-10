#!/usr/bin/env bash
# test_chrome_parity_refs.sh — chrome parity catalog-ref plumbing regression.
#
# Covers: ios-ref.mjs resolver behavior (node:test fixtures), PARITY manifest
# shape, and syntax of the consumer scripts (compare / parity-audit / shots).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

pass=0
fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

section "Resolver + manifest node tests"
if node --test chrome-extension/tools/ios-ref.test.mjs >/dev/null 2>&1; then
  ok "node --test ios-ref.test.mjs"
else
  fail_t "node --test ios-ref.test.mjs failed"
  node --test chrome-extension/tools/ios-ref.test.mjs 2>&1 | tail -20 >&2
fi

section "Consumer script syntax"
for f in chrome-extension/tools/compare.mjs chrome-extension/tools/parity-audit.mjs chrome-extension/tools/shots.mjs chrome-extension/tools/parity-manifest.mjs chrome-extension/tools/ios-ref.mjs; do
  if node --check "$f" >/dev/null 2>&1; then
    ok "$(basename "$f") parses"
  else
    fail_t "$(basename "$f") syntax error"
  fi
done

section "No stale Desktop-ref plumbing"
grep -rn "IOS_REF_DIR\|IOS截圖參考\|IMG_89" chrome-extension/tools/*.mjs ops/chrome_parity.sh >/dev/null 2>&1
case $? in
  1) ok "Desktop reference folder fully retired" ;;
  0) fail_t "IOS_REF_DIR / Desktop reference folder still referenced" ;;
  *) fail_t "grep guard errored (paths moved?)" ;;
esac

echo ""
echo "chrome-parity-refs: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
