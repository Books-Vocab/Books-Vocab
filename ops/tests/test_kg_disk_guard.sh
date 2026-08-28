#!/usr/bin/env bash
# Contract tests; all cleanup targets are temporary fixtures.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/ops/kg_disk_guard.sh"
TMP="$(mktemp -d -t kg_disk_guard_test_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
# Each fixture is a serial one-shot; bypass the host-level singleton lock so
# the test suite does not depend on launchd/shlock state from another run.
export KG_DISK_GUARD_GUARD_LOCK_HELD=1
export KG_DISK_GUARD_BUILD_LOCK_HELD=1
ok(){ echo "  ✓ $*"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $*"; FAIL=$((FAIL+1)); }

timestamp_minutes_ago() {
  local minutes="$1"
  if date -v-"${minutes}"M '+%Y%m%d%H%M.%S' 2>/dev/null; then
    return 0
  fi
  date -d "${minutes} minutes ago" '+%Y%m%d%H%M.%S'
}

[[ -f "$SCRIPT" ]] || { echo "missing $SCRIPT" >&2; exit 1; }

echo "── high free: bounded state, no action ──"
state="$TMP/high/state.json"; mkdir -p "$TMP/high/.cache/ios-build-derived-data"
KG_DISK_GUARD_WORKSPACE="$TMP/high" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"verdict":"ok"' "$state" && ok "high-free verdict ok" || bad "high-free verdict"
grep -q '"action":"none"' "$state" && ok "high-free no action" || bad "high-free action"
bytes1="$(wc -c < "$state")"

echo "── healthy: reader window protects warm shared cache keys ──"
root="$TMP/shared-reader-window"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache"
for key in a b c d; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
mkdir -p "$cache/warm/Build"; printf x > "$cache/warm/Build/blob"
touch -m -t "$(timestamp_minutes_ago 30)" "$cache"/a "$cache"/b "$cache"/c "$cache"/d
touch -m -t "$(timestamp_minutes_ago 45)" "$cache/warm"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=1 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 5 ]] && ok "warm reader window preserves shared keys" || bad "warm reader window changed keys: $key_count"

echo "── healthy: shared keyed cache cap is enforced ──"
root="$TMP/shared-overflow"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache"
for key in a b c d e; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 3 ]] && ok "healthy guard caps shared cache keys" || bad "shared cache key cap: $key_count"
grep -q '"reason":"ios-cache-overflow"' "$state" && ok "shared cache overflow recorded" || bad "shared cache overflow missing"
grep -q '"cache_overflow_keys":2' "$state" && ok "shared cache overflow count recorded" || bad "shared cache overflow count missing"

echo "── healthy: guard releases its build lock ──"
root="$TMP/lock-release"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"; build_lock="$root/build.lock"
mkdir -p "$cache"
for key in a b c d; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 KG_DISK_GUARD_BUILD_LOCK_FILE="$build_lock" \
  env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
[[ ! -e "$build_lock" ]] && ok "guard releases owned build lock" || bad "guard left build lock"

echo "── queued build: guard defers without bypassing FIFO ──"
root="$TMP/queue-defer"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"; build_lock="$root/build.lock"
mkdir -p "$cache" "${build_lock}.queue"
for key in a b c d; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
printf 123 > "${build_lock}.queue/ticket-123"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 KG_DISK_GUARD_BUILD_LOCK_FILE="$build_lock" \
  env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 4 ]] && ok "queued build cache preserved" || bad "queued build cache changed: $key_count"
grep -q '"action":"deferred-build-lock"' "$state" && ok "queued build deferral recorded" || bad "queued build deferral missing"

echo "── persistent queue metadata: guard may clean ──"
root="$TMP/queue-metadata"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"; build_lock="$root/build.lock"
mkdir -p "$cache" "${build_lock}.queue"
for key in a b c d; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
printf 1 > "${build_lock}.queue/.next"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 KG_DISK_GUARD_BUILD_LOCK_FILE="$build_lock" \
  env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 3 ]] && ok "persistent queue metadata does not block cleanup" || bad "persistent queue metadata blocked cleanup: $key_count"
grep -q '"action":"evict-old-ios-cache"' "$state" && ok "persistent queue metadata allows cleanup" || bad "persistent queue metadata action"

echo "── critical: old keyed cache evicted ──"
root="$TMP/low"; cache="$root/.cache/ios-test-derived-data"; state="$TMP/low/state.json"
global_derived="$root/global-derived-data"
mkdir -p "$cache/old-a/Build" "$cache/old-b/Build" "$cache/fresh/Build"
mkdir -p "$global_derived/BooksAndVocab-old" "$global_derived/BooksAndVocab-recent" "$global_derived/BooksAndVocab-fresh"
printf x > "$cache/old-a/Build/blob"; printf x > "$cache/old-b/Build/blob"; printf x > "$cache/fresh/Build/blob"
touch -m -t 202001010000.00 "$cache/old-a" "$cache/old-b"
touch -m -t 202001010000.00 "$global_derived/BooksAndVocab-old"
touch -m -t 202001010000.00 "$global_derived/BooksAndVocab-recent"
touch -m "$global_derived/BooksAndVocab-recent"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 \
  KG_DISK_GUARD_DERIVED_DATA_GLOBAL="$global_derived" \
  "$SCRIPT" >/dev/null 2>&1
[[ ! -d "$cache/old-a" && ! -d "$cache/old-b" && -d "$cache/fresh" ]] \
  && ok "critical pressure evicts old keyed caches" || bad "old cache eviction"
[[ ! -d "$global_derived/BooksAndVocab-old" && -d "$global_derived/BooksAndVocab-recent" && -d "$global_derived/BooksAndVocab-fresh" ]] \
  && ok "global DerivedData fixture is isolated" || bad "global DerivedData fixture isolation"
grep -q '"verdict":"critical"' "$state" && ok "critical verdict recorded" || bad "critical verdict"

echo "── pressure: build DerivedData layout is never treated as keyed ──"
root="$TMP/build-layout"; build_cache="$root/.cache/ios-build-derived-data"; state="$root/state.json"
worktree_build_cache="$root/.claude/worktrees/w1/.cache/ios-build-derived-data"
mkdir -p "$build_cache/Build" "$build_cache/Index.noindex" "$build_cache/ModuleCache.noindex"
printf x > "$build_cache/Build/blob"; printf x > "$build_cache/Index.noindex/blob"; printf x > "$build_cache/ModuleCache.noindex/blob"
touch -m -t 202001010000.00 "$build_cache/Build" "$build_cache/Index.noindex" "$build_cache/ModuleCache.noindex"
mkdir -p "$worktree_build_cache/Build" "$worktree_build_cache/Index.noindex" "$worktree_build_cache/ModuleCache.noindex"
printf x > "$worktree_build_cache/Build/blob"; printf x > "$worktree_build_cache/Index.noindex/blob"; printf x > "$worktree_build_cache/ModuleCache.noindex/blob"
touch -m -t 202001010000.00 "$worktree_build_cache/Build" "$worktree_build_cache/Index.noindex" "$worktree_build_cache/ModuleCache.noindex"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$build_cache/Build" && -d "$build_cache/Index.noindex" && -d "$build_cache/ModuleCache.noindex" ]] \
  && ok "build DerivedData internals preserved" || bad "build DerivedData internals removed"
[[ -d "$worktree_build_cache/Build" && -d "$worktree_build_cache/Index.noindex" && -d "$worktree_build_cache/ModuleCache.noindex" ]] \
  && ok "worktree build DerivedData internals preserved" || bad "worktree build DerivedData internals removed"

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

echo "── exact threshold and healthy-disk log cap ──"
root="$TMP/exact"; state="$TMP/exact/state.json"; log="$TMP/exact/reconcile.log"
mkdir -p "$root"; printf '%*s' 4096 '' | tr ' ' x > "$log"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_DOCKER_CACHE_BYTES=$((2*1073741824+1)) KG_DISK_GUARD_DOCKER_ACTIVE=0 \
  KG_DISK_GUARD_LOG_FILES="$log" KG_DISK_GUARD_LOG_MAX_KB=2 KG_DISK_GUARD_LOG_KEEP_KB=1 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"reason":"docker-build-cache"' "$state" && ok "2GiB+1 exact threshold warns" || bad "exact docker threshold"
[[ "$(wc -c < "$log")" -le 1024 ]] && ok "healthy disk still caps known log" || bad "healthy disk log cap"

echo "── active build: defer and preserve ──"
root="$TMP/active"; cache="$root/.cache/ios-test-derived-data"; state="$TMP/active/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=1 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "active build protects cache" || bad "active build deletion"
grep -q '"action":"deferred-active-build"' "$state" && ok "active build deferred" || bad "active build action"

echo "── aggregate cache budget: stale keyed cache is reclaimed ──"
root="$TMP/budget"; cache="$root/.cache/ios-test-derived-data"; state="$TMP/budget/state.json"
mkdir -p "$cache/old-a/Build" "$cache/old-b/Build" "$root/.cache/ios-release-derived-data/Build" \
  "$root/ios/build/BooksAndVocab.xcarchive" "$root/ios/build/export"
printf x > "$cache/old-a/Build/blob"; printf x > "$cache/old-b/Build/blob"
printf x > "$root/ios/build/BooksAndVocab.xcarchive/blob"; printf x > "$root/ios/build/export/BooksAndVocab.ipa"
touch -m -t 202001010000.00 "$cache/old-a" "$cache/old-b"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=0 KG_DISK_GUARD_CACHE_HEADROOM_GIB=0 \
  KG_DISK_GUARD_CACHE_KEEP=1 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_CACHE_READER_WINDOW_HOURS=0 KG_DISK_GUARD_BUILD_LOCK_FILE="$TMP/budget.lock" \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"reason":"cache-budget-exceeded"' "$state" && ok "cache budget breach recorded" || bad "cache budget reason missing"
grep -q '"cache_budget_overflow_kb":[1-9]' "$state" && ok "cache budget overflow recorded" || bad "cache budget overflow missing"
grep -q '"action":"enforce-cache-budget"' "$state" && ok "cache budget enforcement recorded" || bad "cache budget action missing"
[[ ! -d "$cache/old-a" && ! -d "$cache/old-b" && ! -d "$root/.cache/ios-release-derived-data" \
  && ! -d "$root/ios/build/BooksAndVocab.xcarchive" && ! -d "$root/ios/build/export" ]] \
  && ok "stale rebuildable caches reclaimed" || bad "stale rebuildable caches remain"

echo "── process probe failure: fail closed ──"
root="$TMP/probe-fail"; cache="$root/.cache/ios-test-derived-data"; state="$TMP/probe-fail/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_PROCESS_PROBE_FAIL=1 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "unknown process state preserves cache" || bad "probe failure deleted cache"
grep -q '"active_build":2' "$state" && ok "unknown process state recorded" || bad "unknown process state missing"
grep -q '"action":"deferred-process-observation"' "$state" && ok "probe failure deferred" || bad "probe failure action"

echo "── pressure-only: worktree cache sweep ──"
root="$TMP/worktree"; cache="$root/.claude/worktrees/w1/.cache/ios-test-derived-data"; state="$TMP/worktree/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 KG_DISK_GUARD_WORKTREE_CACHE_KEEP=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ ! -d "$cache/old" ]] && ok "pressure sweeps old worktree cache" || bad "worktree cache not swept"

echo "── healthy: worktree cache key cap ──"
root="$TMP/worktree-overflow"; cache="$root/.claude/worktrees/w1/.cache/ios-test-derived-data"; state="$TMP/worktree-overflow/state.json"
build_cache="$root/.claude/worktrees/w1/.cache/ios-build-derived-data"
mkdir -p "$cache"
for key in a b c d e; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
mkdir -p "$build_cache/Build" "$build_cache/Index.noindex" "$build_cache/ModuleCache.noindex" "$build_cache/Logs"
touch -m -t 202001010000.00 "$build_cache"/*
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_WORKTREE_CACHE_KEEP=3 KG_DISK_GUARD_WORKTREE_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 3 ]] && ok "healthy guard caps worktree cache keys" || bad "worktree cache key cap: $key_count"
grep -q '"reason":"worktree-cache-overflow"' "$state" && ok "worktree overflow recorded" || bad "worktree overflow missing"
grep -q '"worktree_cache_keys":5' "$state" && ok "worktree key count recorded" || bad "worktree key count missing"
[[ -d "$build_cache/Build" && -d "$build_cache/Index.noindex" && -d "$build_cache/ModuleCache.noindex" && -d "$build_cache/Logs" ]] \
  && ok "worktree build DerivedData internals preserved" || bad "worktree build DerivedData internals removed"

echo "── healthy: per-root cap does not sum roots ──"
root="$TMP/worktree-multi"; state="$TMP/worktree-multi/state.json"
for worktree in w1 w2; do
  for key in a b c; do mkdir -p "$root/.claude/worktrees/$worktree/.cache/ios-test-derived-data/$key/Build"; done
done
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_WORKTREE_CACHE_KEEP=3 KG_DISK_GUARD_WORKTREE_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"verdict":"ok"' "$state" && ok "per-root cap avoids aggregate false warning" || bad "aggregate worktree false warning"
grep -q '"worktree_cache_overflow_keys":0' "$state" && ok "per-root overflow is zero" || bad "per-root overflow nonzero"

echo "── active: worktree overflow defers ──"
root="$TMP/worktree-active"; cache="$root/.claude/worktrees/w1/.cache/ios-test-derived-data"; state="$TMP/worktree-active/state.json"
mkdir -p "$cache"
for key in a b c d e; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=1 \
  KG_DISK_GUARD_WORKTREE_CACHE_KEEP=3 KG_DISK_GUARD_WORKTREE_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 5 ]] && ok "active build preserves worktree cache" || bad "active worktree cache changed: $key_count"
grep -q '"action":"deferred-active-build"' "$state" && ok "active worktree cleanup deferred" || bad "active worktree defer missing"

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
