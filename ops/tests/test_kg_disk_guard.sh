#!/usr/bin/env bash
# Contract tests; all cleanup targets are temporary fixtures.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/ops/kg_disk_guard.sh"
TMP="$(mktemp -d -t kg_disk_guard_test_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok(){ echo "  ✓ $*"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $*"; FAIL=$((FAIL+1)); }

[[ -f "$SCRIPT" ]] || { echo "missing $SCRIPT" >&2; exit 1; }

echo "── high free: bounded state, no action ──"
state="$TMP/high/state.json"; mkdir -p "$TMP/high/.cache/ios-build-derived-data"
KG_DISK_GUARD_WORKSPACE="$TMP/high" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"verdict":"ok"' "$state" && ok "high-free verdict ok" || bad "high-free verdict"
grep -q '"action":"none"' "$state" && ok "high-free no action" || bad "high-free action"
bytes1="$(wc -c < "$state")"

echo "── critical: old keyed cache evicted ──"
root="$TMP/low"; cache="$root/.cache/ios-build-derived-data"; state="$TMP/low/state.json"
mkdir -p "$cache/old-a/Build" "$cache/old-b/Build" "$cache/fresh/Build"
printf x > "$cache/old-a/Build/blob"; printf x > "$cache/old-b/Build/blob"; printf x > "$cache/fresh/Build/blob"
touch -m -t 202001010000.00 "$cache/old-a" "$cache/old-b"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 \
  "$SCRIPT" >/dev/null 2>&1
[[ ! -d "$cache/old-a" && ! -d "$cache/old-b" && -d "$cache/fresh" ]] \
  && ok "critical pressure evicts old keyed caches" || bad "old cache eviction"
grep -q '"verdict":"critical"' "$state" && ok "critical verdict recorded" || bad "critical verdict"

echo "── docker build cache: surfaced and logs trimmed ──"
root="$TMP/docker"; state="$TMP/docker/state.json"; log="$TMP/docker/kg_reconcile.err.log"
mkdir -p "$root"; printf '%*s' 4096 '' | tr ' ' x > "$log"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_DOCKER_CACHE_BYTES=$((4*1073741824)) KG_DISK_GUARD_DOCKER_ACTIVE=0 \
  KG_DISK_GUARD_LOG_FILES="$log" KG_DISK_GUARD_LOG_MAX_KB=2 KG_DISK_GUARD_LOG_KEEP_KB=1 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"reason":"docker-build-cache"' "$state" && ok "docker cache reason recorded" || bad "docker cache reason"
[[ "$(wc -c < "$log")" -le 1024 ]] && ok "known log is capped" || bad "known log not capped"

echo "── active build: defer and preserve ──"
root="$TMP/active"; cache="$root/.cache/ios-build-derived-data"; state="$TMP/active/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=1 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "active build protects cache" || bad "active build deletion"
grep -q '"action":"deferred-active-build"' "$state" && ok "active build deferred" || bad "active build action"

echo "── repeated run: state remains bounded ──"
for i in 1 2 3 4 5; do
  KG_DISK_GUARD_WORKSPACE="$TMP/high" KG_DISK_GUARD_STATE="$TMP/high/state.json" \
    KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
    "$SCRIPT" >/dev/null 2>&1 || bad "repeat $i failed"
done
bytes2="$(wc -c < "$TMP/high/state.json")"
state_count="$(find "$TMP/high" -maxdepth 1 -type f -name 'state.json*' | wc -l | tr -d ' ')"
[[ "$bytes2" -lt 900 && "$state_count" -eq 1 ]] && ok "state bounded, one atomic file (${bytes2} bytes)" || bad "state accumulation: bytes=$bytes2 files=$state_count"

echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
