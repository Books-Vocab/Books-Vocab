#!/usr/bin/env bash
# Contract tests for the bounded iOS development disk budget.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$ROOT/ops/lib/ios_disk_budget.sh"
TMP="$(mktemp -d -t kg_ios_disk_budget_test_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

PASS=0
FAIL=0
ok() { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad() { echo "  ✗ $*"; FAIL=$((FAIL + 1)); }

[[ -f "$LIB" ]] || { echo "missing $LIB" >&2; exit 1; }

cache_root="$TMP/cache"
mkdir -p "$cache_root/ios-build-derived-data" "$cache_root/ios-test-derived-data"
mkdir -p "$cache_root/ios/build"

echo "── under budget and free-space floor ──"
if KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_CACHE_BUDGET_GIB=1 KG_IOS_DISK_CACHE_HEADROOM_GIB=0 \
  KG_IOS_DISK_MIN_FREE_GIB=20 KG_IOS_DISK_FREE_BYTES=$((40 * 1073741824)) \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" \
  >/dev/null 2>&1; then
  ok "under-budget preflight passes"
else
  bad "under-budget preflight unexpectedly failed"
fi

echo "── over budget blocks before a writer starts ──"
dd if=/dev/zero of="$cache_root/ios-build-derived-data/payload" bs=1m count=2 >/dev/null 2>&1
over_output=""
over_rc=0
over_output="$(KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_CACHE_BUDGET_GIB=0 KG_IOS_DISK_CACHE_HEADROOM_GIB=0 \
  KG_IOS_DISK_MIN_FREE_GIB=20 KG_IOS_DISK_FREE_BYTES=$((40 * 1073741824)) \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" 2>&1)" || over_rc=$?
[[ "$over_rc" -eq 75 ]] && ok "over-budget exits 75" || bad "over-budget exit=$over_rc"
grep -q 'reason=cache-budget-exceeded' <<<"$over_output" \
  && ok "over-budget reason is structured" \
  || bad "over-budget reason missing: $over_output"

echo "── low free space blocks even with a small cache ──"
low_rc=0
KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_CACHE_BUDGET_GIB=1 KG_IOS_DISK_CACHE_HEADROOM_GIB=0 \
  KG_IOS_DISK_MIN_FREE_GIB=20 KG_IOS_DISK_FREE_BYTES=$((19 * 1073741824)) \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" \
  >/dev/null 2>&1 || low_rc=$?
[[ "$low_rc" -eq 75 ]] && ok "low free space exits 75" || bad "low free-space exit=$low_rc"

echo "── unknown free-space observation fails closed ──"
unknown_rc=0
KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_CACHE_BUDGET_GIB=1 KG_IOS_DISK_CACHE_HEADROOM_GIB=0 \
  KG_IOS_DISK_MIN_FREE_GIB=20 KG_IOS_DISK_FREE_BYTES=unknown \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" \
  >/dev/null 2>&1 || unknown_rc=$?
[[ "$unknown_rc" -eq 75 ]] && ok "unknown free-space exits 75" || bad "unknown free-space exit=$unknown_rc"

echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
