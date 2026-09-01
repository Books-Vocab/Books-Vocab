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
export KG_DISK_GUARD_LANE_USAGE_STATE="$TMP/lane-disk-usage.json"
export KG_DISK_GUARD_DERIVED_DATA_GLOBAL="$TMP/derived-data"
export KG_DISK_GUARD_XCTEST_DEVICES_ROOT="$TMP/xctest-devices"
export KG_DISK_GUARD_XCTEST_DEVICES_BUDGET_GIB=16
# Existing fixtures use 30 GiB as a non-pressure value.  Keep that fixture
# contract explicit while production defaults move to the 50/36 GiB floor.
export KG_DISK_GUARD_WARN_FREE_GIB=20
export KG_DISK_GUARD_CRIT_FREE_GIB=10
ok(){ echo "  ✓ $*"; PASS=$((PASS+1)); }
bad(){ echo "  ✗ $*"; FAIL=$((FAIL+1)); }

# Linux runners do not provide macOS's shlock.  Keep production behavior
# fail-closed when it is unavailable, but give lock-acquisition fixtures the
# same deterministic primitive used by the iOS lock contract tests.
FAKE_BIN="$TMP/fake-bin"
mkdir -p "$FAKE_BIN"
cat >"$FAKE_BIN/shlock" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
lock_file=""
owner_pid=""
while (($#)); do
  case "$1" in
    -f) lock_file="$2"; shift 2 ;;
    -p) owner_pid="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$lock_file" && -n "$owner_pid" ]]
if [[ -f "$lock_file" ]]; then
  held_pid="$(cat "$lock_file" 2>/dev/null || true)"
  if [[ "$held_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$held_pid" 2>/dev/null; then
    rm -f "$lock_file"
  else
    exit 1
  fi
fi
if mkdir "${lock_file}.claim" 2>/dev/null; then
  printf '%s\n' "$owner_pid" >"$lock_file"
  rmdir "${lock_file}.claim"
  exit 0
fi
exit 1
EOF
chmod +x "$FAKE_BIN/shlock"

timestamp_minutes_ago() {
  local minutes="$1"
  if date -v-"${minutes}"M '+%Y%m%d%H%M.%S' 2>/dev/null; then
    return 0
  fi
  date -d "${minutes} minutes ago" '+%Y%m%d%H%M.%S'
}

[[ -f "$SCRIPT" ]] || { echo "missing $SCRIPT" >&2; exit 1; }

echo "── fixed attribution timebox contract ──"
grep -q 'KG_DISK_GUARD_LANE_USAGE_BUDGET_SECONDS:-240' "$SCRIPT" \
  && ok "guard default attribution budget is 240 seconds" \
  || bad "guard attribution budget default drifted"
grep -q 'attribution scan budget (default: 240)' "$SCRIPT" \
  && ok "guard help documents 240-second budget" \
  || bad "guard help budget is stale"
grep -q 'WARN_FREE_GIB="\${KG_DISK_GUARD_WARN_FREE_GIB:-50}"' "$SCRIPT" \
  && ok "guard default warning floor is 50 GiB" || bad "guard warning floor drifted"
grep -q 'CRIT_FREE_GIB="\${KG_DISK_GUARD_CRIT_FREE_GIB:-36}"' "$SCRIPT" \
  && ok "guard default critical floor is 36 GiB" || bad "guard critical floor drifted"
grep -q 'SIMULATOR_RUNTIME_BUDGET_GIB.*:-56' "$SCRIPT" \
  && ok "guard shared runtime budget is explicit" || bad "guard shared runtime budget missing"

echo "── help is read-only ──"
root="$TMP/help"; state="$root/state.json"; cache="$root/.cache/ios-test-derived-data"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"
if KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  "$SCRIPT" --help >/dev/null 2>&1; then
  [[ ! -e "$state" && -d "$cache/old" ]] \
    && ok "help does not run a guard tick" || bad "help changed guard state"
else
  bad "help exited non-zero"
fi

echo "── high free: bounded state, no action ──"
state="$TMP/high/state.json"; mkdir -p "$TMP/high/.cache/ios-build-derived-data"
KG_DISK_GUARD_WORKSPACE="$TMP/high" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"verdict":"ok"' "$state" && ok "high-free verdict ok" || bad "high-free verdict"
grep -q '"action":"none"' "$state" && ok "high-free no action" || bad "high-free action"
bytes1="$(wc -c < "$state")"

echo "── healthy: global BooksAndVocab DerivedData has an independent byte bound ──"
root="$TMP/global-dd-budget"; global_derived="$root/global-derived-data"; state="$root/state.json"
mkdir -p "$global_derived/BooksAndVocab-old/Build" "$global_derived/BooksAndVocab-middle/Build" \
  "$global_derived/BooksAndVocab-new/Build" "$global_derived/OtherProject-unmanaged/Build"
dd if=/dev/zero of="$global_derived/BooksAndVocab-old/Build/blob" bs=1024 count=700 >/dev/null 2>&1
dd if=/dev/zero of="$global_derived/BooksAndVocab-middle/Build/blob" bs=1024 count=700 >/dev/null 2>&1
dd if=/dev/zero of="$global_derived/BooksAndVocab-new/Build/blob" bs=1024 count=700 >/dev/null 2>&1
dd if=/dev/zero of="$global_derived/OtherProject-unmanaged/Build/blob" bs=1024 count=700 >/dev/null 2>&1
touch -m -t 202001010000.00 "$global_derived/BooksAndVocab-old"
touch -m -t 202001020000.00 "$global_derived/BooksAndVocab-middle"
touch -m -t 202001030000.00 "$global_derived/BooksAndVocab-new"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_DERIVED_DATA_GLOBAL="$global_derived" \
  KG_DISK_GUARD_DERIVED_DATA_BUDGET_GIB=0 KG_DISK_GUARD_DERIVED_DATA_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_BUILD_LOCK_FILE="$root/build.lock" "$SCRIPT" >/dev/null 2>&1
dd_count="$(find "$global_derived" -mindepth 1 -maxdepth 1 -type d -name 'BooksAndVocab-*' | wc -l | tr -d ' ')"
[[ "$dd_count" -eq 0 ]] && ok "healthy guard bounds global DerivedData" || bad "global DerivedData remains unbounded: $dd_count directories"
grep -q '"reason":"derived-data-budget-exceeded"' "$state" \
  && ok "global DerivedData budget breach recorded" || bad "global DerivedData budget reason missing"
grep -q '"action":"enforce-derived-data-budget"' "$state" \
  && ok "global DerivedData repair action recorded" || bad "global DerivedData repair action missing"
grep -q '"derived_data_budget_kb":0' "$state" \
  && ok "global DerivedData budget recorded" || bad "global DerivedData budget missing"
[[ -d "$global_derived/OtherProject-unmanaged" ]] \
  && ok "unmanaged global DerivedData is preserved" || bad "unmanaged global DerivedData was removed"

echo "── global DerivedData: active consumer defers repair ──"
root="$TMP/global-dd-active"; global_derived="$root/global-derived-data"; state="$root/state.json"
mkdir -p "$global_derived/BooksAndVocab-active-a/Build" "$global_derived/BooksAndVocab-active-b/Build"
printf x > "$global_derived/BooksAndVocab-active-a/Build/blob"
printf x > "$global_derived/BooksAndVocab-active-b/Build/blob"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_DERIVED_DATA_GLOBAL="$global_derived" KG_DISK_GUARD_DERIVED_DATA_BUDGET_GIB=0 \
  KG_DISK_GUARD_DERIVED_DATA_MIN_AGE_HOURS=0 KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=1 "$SCRIPT" >/dev/null 2>&1
dd_count="$(find "$global_derived" -mindepth 1 -maxdepth 1 -type d -name 'BooksAndVocab-*' | wc -l | tr -d ' ')"
[[ "$dd_count" -eq 2 ]] && ok "active consumer preserves global DerivedData" || bad "active consumer cleanup changed global DerivedData"
grep -q '"action":"deferred-active-build"' "$state" \
  && ok "active consumer deferral is recorded" || bad "active consumer deferral missing"

echo "── global DerivedData: held build lock defers repair ──"
root="$TMP/global-dd-lock"; global_derived="$root/global-derived-data"; state="$root/state.json"; build_lock="$root/build.lock"
mkdir -p "$global_derived/BooksAndVocab-held/Build"
printf x > "$global_derived/BooksAndVocab-held/Build/blob"
printf '%s\n' "$$" > "$build_lock"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_DERIVED_DATA_GLOBAL="$global_derived" KG_DISK_GUARD_DERIVED_DATA_BUDGET_GIB=0 \
  KG_DISK_GUARD_DERIVED_DATA_MIN_AGE_HOURS=0 KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 KG_DISK_GUARD_BUILD_LOCK_FILE="$build_lock" \
  PATH="$FAKE_BIN:$PATH" env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
[[ -d "$global_derived/BooksAndVocab-held" ]] \
  && ok "held build lock preserves global DerivedData" || bad "held build lock deleted global DerivedData"
grep -q '"action":"deferred-build-lock"' "$state" \
  && ok "held build lock deferral is recorded" || bad "held build lock deferral missing"

echo "── global DerivedData: dry-run preserves repair targets and exit semantics ──"
root="$TMP/global-dd-dry-run"; global_derived="$root/global-derived-data"; state="$root/state.json"
mkdir -p "$global_derived/BooksAndVocab-dry-a/Build" "$global_derived/BooksAndVocab-dry-b/Build"
printf x > "$global_derived/BooksAndVocab-dry-a/Build/blob"
printf x > "$global_derived/BooksAndVocab-dry-b/Build/blob"
if KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_DERIVED_DATA_GLOBAL="$global_derived" KG_DISK_GUARD_DERIVED_DATA_BUDGET_GIB=0 \
  KG_DISK_GUARD_DERIVED_DATA_MIN_AGE_HOURS=0 KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 KG_DISK_GUARD_DRY_RUN=1 "$SCRIPT" >/dev/null 2>&1; then
  ok "dry-run keeps guard exit compatible"
else
  bad "dry-run changed guard exit semantics"
fi
dd_count="$(find "$global_derived" -mindepth 1 -maxdepth 1 -type d -name 'BooksAndVocab-*' | wc -l | tr -d ' ')"
[[ "$dd_count" -eq 2 ]] && ok "dry-run preserves global DerivedData" || bad "dry-run deleted global DerivedData"
grep -q '"action":"enforce-derived-data-budget"' "$state" \
  && ok "dry-run repair action is recorded" || bad "dry-run repair action missing"
grep -q '"cache_eviction_evicted":0' "$state" \
  && ok "dry-run records no eviction" || bad "dry-run reports eviction"

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
  PATH="$FAKE_BIN:$PATH" env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
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
  PATH="$FAKE_BIN:$PATH" env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
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
  PATH="$FAKE_BIN:$PATH" env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
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

echo "── conservative free-space floor: exactly 36 GiB is critical ──"
root="$TMP/free-floor"; state="$root/state.json"
mkdir -p "$root"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((36*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_WARN_FREE_GIB=50 KG_DISK_GUARD_CRIT_FREE_GIB=36 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"verdict":"critical"' "$state" && ok "36 GiB floor is critical" || bad "36 GiB floor was not critical"
grep -q '"reason":"free-below-critical"' "$state" && ok "critical floor reason is explicit" || bad "critical floor reason missing"

echo "── active build: defer and preserve ──"
root="$TMP/active"; cache="$root/.cache/ios-test-derived-data"; state="$TMP/active/state.json"
build_cache="$root/.cache/ios-build-derived-data"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
mkdir -p "$build_cache/Build"; printf x > "$build_cache/Build/blob"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((8*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=1 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "active build protects cache" || bad "active build deletion"
[[ -d "$build_cache" ]] && ok "active build protects shared build cache" || bad "active build deleted shared build cache"
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

echo "── headroom exhausted: reader window yields to writer budget ──"
root="$TMP/headroom-repair"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache/old/Build" "$cache/warm/Build"
printf x > "$cache/old/Build/blob"; printf x > "$cache/warm/Build/blob"
touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_CACHE_READER_WINDOW_HOURS=1 "$SCRIPT" >/dev/null 2>&1
[[ ! -d "$cache/old" && ! -d "$cache/warm" ]] \
  && ok "headroom repair releases reader-window cache" || bad "headroom repair left writer headroom short"
grep -q '"cache_repair_status":"repaired"' "$state" \
  && ok "headroom repair converges to writer budget" || bad "headroom repair did not converge"
grep -q '"action":"enforce-cache-headroom"' "$state" \
  && ok "headroom repair action recorded" || bad "headroom repair action missing"
grep -q '"cache_budget_overflow_kb":0' "$state" \
  && ok "headroom case is below hard budget" || bad "headroom case misclassified as hard overflow"
grep -q '"cache_headroom_overflow_kb":[1-9]' "$state" \
  && ok "headroom overflow evidence recorded" || bad "headroom overflow evidence missing"
grep -q '"cache_repair_remaining_kb":0' "$state" \
  && ok "headroom repair has no remaining shortfall" || bad "headroom shortfall remains"

echo "── headroom exhausted: recent reader-window keys yield to writer budget ──"
root="$TMP/headroom-recent-repair"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache"
for key in oldest middle newest; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t "$(timestamp_minutes_ago 50)" "$cache/oldest"
touch -m -t "$(timestamp_minutes_ago 40)" "$cache/middle"
touch -m -t "$(timestamp_minutes_ago 30)" "$cache/newest"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_CACHE_READER_WINDOW_HOURS=1 "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 0 ]] \
  && ok "recent reader-window keys yield to writer headroom repair" \
  || bad "recent reader-window keys still block repair: $key_count"
grep -q '"cache_repair_status":"repaired"' "$state" \
  && ok "recent-key headroom repair is recorded" || bad "recent-key repair status missing"
grep -q '"cache_repair_remaining_kb":0' "$state" \
  && ok "recent-key headroom repair has no shortfall" || bad "recent-key repair shortfall"

echo "── headroom exhausted: stale cache repair completes ──"
root="$TMP/headroom-repaired"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ ! -d "$cache/old" ]] && ok "headroom repair reaches writer limit" || bad "headroom repair left stale cache"
grep -q '"cache_repair_status":"repaired"' "$state" \
  && ok "completed headroom repair is recorded" || bad "completed headroom repair missing"
grep -q '"cache_repair_remaining_kb":0' "$state" \
  && ok "completed headroom repair has no shortfall" || bad "completed headroom repair shortfall"

echo "── aggregate headroom: inactive shared build cache is rebuildable ──"
root="$TMP/build-cache-repair"; cache="$root/.cache/ios-build-derived-data"; state="$root/state.json"
mkdir -p "$cache/Build/Products"
printf x > "$cache/Build/Products/blob"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_CACHE_READER_WINDOW_HOURS=0 \
  KG_DISK_GUARD_BUILD_LOCK_FILE="$TMP/build-cache-repair.lock" \
  "$SCRIPT" >/dev/null 2>&1
[[ ! -d "$cache" ]] \
  && ok "inactive shared build cache reclaimed" || bad "inactive shared build cache remains"
grep -q '"cache_repair_status":"repaired"' "$state" \
  && ok "build cache repair is recorded" || bad "build cache repair missing"
grep -q '"cache_repair_remaining_kb":0' "$state" \
  && ok "build cache repair has no shortfall" || bad "build cache repair shortfall"

echo "── aggregate budget: oldest-first eviction stops at target ──"
root="$TMP/evict-order"; cache="$root/.cache/ios-test-derived-data"
mkdir -p "$cache/old/Build" "$cache/new/Build"
touch -m -t 202001010000.00 "$cache/old"
touch -m -t 202001020000.00 "$cache/new"
source "$ROOT/ops/lib/ios_cache_evict.sh"
kg_ios_disk_budget_cache_kb() { printf '5'; }
du() { printf '2\t%s\n' "${!#}"; }
KG_IOS_CACHE_KEEP=0 KG_IOS_CACHE_EVICT_MIN_AGE_HOURS=0 KG_IOS_DISK_CACHE_BUDGET_KB=3 \
  kg_ios_cache_evict "$cache" "" >/dev/null 2>&1
unset -f du kg_ios_disk_budget_cache_kb
[[ ! -d "$cache/old" && -d "$cache/new" ]] \
  && ok "budget repair evicts the oldest key first" || bad "budget repair did not preserve newest key"

echo "── headroom healthy: no-overflow is a no-op ──"
root="$TMP/headroom-noop"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache/kept/Build"; printf x > "$cache/kept/Build/blob"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=2 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/kept" ]] && ok "healthy headroom preserves cache" || bad "healthy headroom removed cache"
grep -q '"verdict":"ok"' "$state" && ok "healthy headroom verdict ok" || bad "healthy headroom verdict"
grep -q '"action":"none"' "$state" && ok "healthy headroom action none" || bad "healthy headroom action"

echo "── headroom exhausted: active build defers ──"
root="$TMP/headroom-active"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=1 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "active writer preserves headroom cache" || bad "active writer deleted headroom cache"
grep -q '"reason":"cache-budget-headroom-exhausted"' "$state" \
  && ok "active writer retains headroom evidence" || bad "active writer headroom reason missing"
grep -q '"action":"deferred-active-build"' "$state" \
  && ok "active writer deferral recorded" || bad "active writer deferral missing"

echo "── headroom exhausted: held build lock defers ──"
root="$TMP/headroom-lock"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"; build_lock="$root/build.lock"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
printf '%s\n' "$$" > "$build_lock"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_BUILD_LOCK_FILE="$build_lock" PATH="$FAKE_BIN:$PATH" \
  env -u KG_DISK_GUARD_BUILD_LOCK_HELD "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "held build lock preserves headroom cache" || bad "held build lock deleted headroom cache"
grep -q '"action":"deferred-build-lock"' "$state" \
  && ok "held build lock deferral recorded" || bad "held build lock deferral missing"
rm -f "$build_lock"

echo "── headroom exhausted: unknown process state fails closed ──"
root="$TMP/headroom-probe"; cache="$root/.cache/ios-test-derived-data"; state="$root/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_PROCESS_PROBE_FAIL=1 \
  KG_DISK_GUARD_CACHE_BUDGET_GIB=1 KG_DISK_GUARD_CACHE_HEADROOM_GIB=1 \
  KG_DISK_GUARD_CACHE_KEEP=3 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "unknown process state preserves headroom cache" || bad "unknown process state deleted headroom cache"
grep -q '"action":"deferred-process-observation"' "$state" \
  && ok "unknown process deferral recorded" || bad "unknown process deferral missing"

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

echo "── pressure-only: unknown worktree cache is preserved ──"
root="$TMP/worktree"; cache="$root/.claude/worktrees/w1/.cache/ios-test-derived-data"; state="$TMP/worktree/state.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((15*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 KG_DISK_GUARD_WORKTREE_CACHE_KEEP=0 \
  "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "pressure preserves unknown worktree cache" || bad "unknown worktree cache deleted"
grep -q '"action":"deferred-worktree-ownership"' "$state" \
  && ok "unknown worktree cleanup is deferred" || bad "unknown worktree cleanup was not deferred"

echo "── pressure-only: active registered worktree cache is preserved ──"
root="$TMP/worktree-active-registered"; cache="$root/.claude/worktrees/w1/.cache/ios-test-derived-data"; state="$root/state.json"; registry="$root/registry.json"
mkdir -p "$cache/old/Build"; printf x > "$cache/old/Build/blob"; touch -m -t 202001010000.00 "$cache/old"
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[{"branch":"debug/test-w1","path":"'$root'/.claude/worktrees/w1","status":"active","claim_generation":0,"external_ids":["TEST-W1"]}]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((15*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_CACHE_KEEP=0 KG_DISK_GUARD_CACHE_MIN_AGE_HOURS=1 KG_DISK_GUARD_WORKTREE_CACHE_KEEP=0 \
  KG_DISK_GUARD_REGISTRY_STATE="$registry" "$SCRIPT" >/dev/null 2>&1
[[ -d "$cache/old" ]] && ok "active registered worktree cache preserved" || bad "active worktree cache deleted"
grep -q '"action":"deferred-worktree-ownership"' "$state" \
  && ok "active registered worktree cleanup is deferred" || bad "active worktree cleanup was not deferred"

echo "── healthy: worktree cache key cap ──"
root="$TMP/worktree-overflow"; cache="$root/.claude/worktrees/w1/.cache/ios-test-derived-data"; state="$TMP/worktree-overflow/state.json"; registry="$root/registry.json"
build_cache="$root/.claude/worktrees/w1/.cache/ios-build-derived-data"
mkdir -p "$cache"
for key in a b c d e; do mkdir -p "$cache/$key/Build"; printf x > "$cache/$key/Build/blob"; done
touch -m -t 202001010000.00 "$cache"/*
mkdir -p "$build_cache/Build" "$build_cache/Index.noindex" "$build_cache/ModuleCache.noindex" "$build_cache/Logs"
touch -m -t 202001010000.00 "$build_cache"/*
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[{"branch":"debug/test-w1","path":"'$root'/.claude/worktrees/w1","status":"merged","claim_generation":0,"external_ids":["TEST-W1"]}]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_WORKTREE_CACHE_KEEP=3 KG_DISK_GUARD_WORKTREE_CACHE_MIN_AGE_HOURS=0 \
  KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  "$SCRIPT" >/dev/null 2>&1
key_count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[[ "$key_count" -eq 5 ]] && ok "guard preserves terminal worktree cache keys" || bad "terminal worktree cache key count: $key_count"
grep -q '"reason":"worktree-cache-overflow"' "$state" && ok "worktree overflow recorded" || bad "worktree overflow missing"
grep -q '"worktree_cache_keys":5' "$state" && ok "worktree key count recorded" || bad "worktree key count missing"
grep -q '"action":"deferred-worktree-ownership"' "$state" && ok "terminal worktree cleanup deferred" || bad "terminal worktree cleanup was attempted"
[[ -d "$build_cache/Build" && -d "$build_cache/Index.noindex" && -d "$build_cache/ModuleCache.noindex" && -d "$build_cache/Logs" ]] \
  && ok "worktree build DerivedData internals preserved" || bad "worktree build DerivedData internals removed"

echo "── .codex topology: active, terminal, and unknown worktrees are never evicted ──"
root="$TMP/codex-topology"; state="$root/state.json"; registry="$root/registry.json"
codex_root="$root/.codex/worktrees"
for lane in active terminal unknown; do
  cache="$codex_root/$lane/.cache/ios-test-derived-data"
  for key in a b c d; do
    mkdir -p "$cache/$key/Build"
    printf x > "$cache/$key/Build/blob"
  done
done
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[{"branch":"active","path":"'$codex_root'/active","status":"active"},{"branch":"terminal","path":"'$codex_root'/terminal","status":"merged"},{"branch":"unknown","path":"'$codex_root'/unknown","status":"paused"}]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_REGISTRY_STATE="$registry" KG_DISK_GUARD_CODEX_WORKTREE_ROOT="$codex_root" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  KG_DISK_GUARD_WORKTREE_CACHE_KEEP=0 "$SCRIPT" >/dev/null 2>&1
key_count=0
for cache in "$codex_root"/*/.cache/ios-test-derived-data; do
  [[ -d "$cache" ]] || continue
  count="$(find "$cache" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
  key_count=$((key_count + count))
done
[[ "$key_count" -eq 12 ]] && ok ".codex topology keys remain observable" || bad ".codex topology keys changed: $key_count"
grep -q '"worktree_cache_keys":12' "$state" && ok ".codex topology count recorded" || bad ".codex topology count missing"
grep -q '"action":"deferred-worktree-ownership"' "$state" && ok "active/terminal/unknown cleanup deferred" || bad "worktree cleanup action was not deferred"

echo "── eviction failure: guard never reports budget repair success ──"
root="$TMP/eviction-failure"; state="$root/state.json"; cache="$root/.cache/ios-test-derived-data"; failing_lib="$root/failing-cache-lib.sh"
mkdir -p "$cache/old/Build"
printf x > "$cache/old/Build/blob"
cat > "$failing_lib" <<'EOF'
kg_ios_cache_evict() {
  KG_IOS_CACHE_EVICT_ATTEMPTED=1
  KG_IOS_CACHE_EVICTED=0
  KG_IOS_CACHE_EVICT_FAILED=1
  return 0
}
EOF
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_CACHE_LIB="$failing_lib" KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 KG_DISK_GUARD_CACHE_BUDGET_GIB=0 KG_DISK_GUARD_CACHE_HEADROOM_GIB=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"cache_eviction_attempted":1' "$state" && ok "failed eviction attempted recorded" || bad "failed eviction attempt missing"
grep -q '"cache_eviction_failed":1' "$state" && ok "failed eviction recorded" || bad "failed eviction missing"
grep -q '"cache_repair_status":"failed"' "$state" && ok "failed budget repair is explicit" || bad "failed budget repair status missing"
grep -q '"budget_repaired":0' "$state" && ok "failed repair is not reported repaired" || bad "failed repair falsely reported repaired"
[[ -d "$cache/old" ]] && ok "failed eviction preserves cache" || bad "failed eviction removed cache"

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
[[ "$bytes2" -lt 1400 && "$state_count" -eq 1 ]] && ok "state bounded, one atomic file (${bytes2} bytes)" || bad "state accumulation: bytes=$bytes2 files=$state_count"

echo "── lane usage: missing active lanes warn without blocking disk attribution ──"
root="$TMP/lane-usage"; state="$root/guard.json"; registry="$root/registry.json"; lane_state="$root/lane-disk-usage.json"
mkdir -p "$root"
git -C "$root" init -b main >/dev/null 2>&1
git -C "$root" config user.email disk-test@example.com
git -C "$root" config user.name "Disk Test"
printf 'main\n' > "$root/tracked.txt"
git -C "$root" add tracked.txt >/dev/null 2>&1
git -C "$root" commit -m initial >/dev/null 2>&1
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[{"branch":"feat/missing-lane","path":"'$root'/missing-lane","status":"active","claim_generation":0,"external_ids":["DIRECT-DELIVERY-MISSING"]}]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 "$SCRIPT" >/dev/null 2>&1
grep -q 'kg.disk.lane-usage.v1' "$lane_state" && ok "lane usage report is written" || bad "lane usage report missing"
grep -q 'missing-registered-lane' "$lane_state" && ok "missing active lane is visible" || bad "missing active lane not visible"
grep -q '"exists": false' "$lane_state" && ok "missing active lane has explicit accounting row" || bad "missing active lane accounting row missing"
grep -q '"measurement_error": "path-missing"' "$lane_state" && ok "missing active lane error is explicit" || bad "missing active lane error missing"
grep -q '"verdict": "warning"' "$lane_state" && ok "missing lane is warning-only" || bad "missing lane still blocks"
grep -q '"lane_usage_verdict":"warning"' "$root/guard.json" && ok "guard state carries attribution warning" || bad "guard state missed attribution warning"
grep -q '"lane_usage_rc":0' "$root/guard.json" && ok "warning keeps guard exit compatible" || bad "warning changed guard exit"

echo "── lane usage: active registered dirty implementation lane is attributable ──"
root="$TMP/active-dirty"; state="$root/guard.json"; registry="$root/registry.json"; lane_state="$root/lane-disk-usage.json"; active_dirty="$TMP/active-dirty-worktree"
mkdir -p "$root"
git -C "$root" init -b main >/dev/null 2>&1
git -C "$root" config user.email disk-test@example.com
git -C "$root" config user.name "Disk Test"
printf 'main\n' > "$root/tracked.txt"
git -C "$root" add tracked.txt >/dev/null 2>&1
git -C "$root" commit -m initial >/dev/null 2>&1
git -C "$root" worktree add -b active-dirty "$active_dirty" HEAD >/dev/null 2>&1
printf 'dirty\n' > "$active_dirty/dirty.txt"
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[{"branch":"active-dirty","path":"'$active_dirty'","status":"active","claim_generation":0,"external_ids":["DIRECT-DELIVERY-ACTIVE-DIRTY"]}]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 "$SCRIPT" >/dev/null 2>&1
grep -q '"physical_state": "dirty"' "$lane_state" && ok "active dirty state is observable" || bad "active dirty state missing"
grep -q 'active-dirty-worktree' "$lane_state" && ok "active dirty lane is named" || bad "active dirty lane missing"
grep -q '"active_dirty_implementation_worktrees": \[' "$lane_state" && ok "active dirty classification is explicit" || bad "active dirty classification missing"
grep -q '"blocking_dirty_physical_worktrees": \[\]' "$lane_state" && ok "active dirty lane is not a blocker" || bad "active dirty lane blocked"
grep -Eq '"physical_lane_allocated_bytes": [1-9][0-9]*' "$lane_state" && ok "active dirty lane bytes are aggregated" || bad "active dirty aggregate bytes missing"
grep -Eq '"allocated_bytes": [1-9][0-9]*' "$lane_state" && ok "active dirty lane bytes are attributed" || bad "active dirty lane bytes missing"
grep -Eq '"lane_usage_verdict":"(pass|warning)"' "$state" && ok "guard accepts active dirty lane" || bad "guard rejects active dirty lane"
grep -q '"lane_usage_rc":0' "$state" && ok "active dirty lane keeps guard exit compatible" || bad "active dirty lane changed guard exit"

echo "── lane usage: exact supervision checkout is excluded with state evidence ──"
root="$TMP/supervision"; state="$root/guard.json"; registry="$root/registry.json"; lane_state="$root/lane-disk-usage.json"; supervision="$TMP/supervision-checkout"
mkdir -p "$root"
git -C "$root" init -b main >/dev/null 2>&1
git -C "$root" config user.email disk-test@example.com
git -C "$root" config user.name "Disk Test"
printf 'main\n' > "$root/tracked.txt"
git -C "$root" add tracked.txt >/dev/null 2>&1
git -C "$root" commit -m initial >/dev/null 2>&1
git -C "$root" worktree add -b supervision "$supervision" HEAD >/dev/null 2>&1
printf 'supervision\n' > "$supervision/supervision.txt"
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 "$SCRIPT" --supervision-worktree "$supervision" >/dev/null 2>&1
grep -q 'supervision-checkout' "$lane_state" && ok "supervision path remains observable" || bad "supervision path missing from report"
grep -q '"ownership": "excluded"' "$lane_state" && ok "supervision path is explicitly excluded" || bad "supervision path not excluded"
grep -q '"supervision_worktree_paths": \[' "$lane_state" && ok "report records exclusion list" || bad "report exclusion list missing"
grep -q '"lane_usage_exclusions":\[' "$state" && ok "guard state records exclusion list" || bad "guard state exclusion list missing"
grep -q 'supervision-checkout' "$state" && ok "guard state records exact exclusion" || bad "guard state exact exclusion missing"
grep -q '"lane_usage_verdict":"pass"' "$state" && ok "guard accepts exact supervision exclusion" || bad "guard blocks exact supervision exclusion"
grep -q '"lane_usage_rc":0' "$state" && ok "supervision exclusion keeps guard exit compatible" || bad "supervision exclusion changed guard exit"

echo "── lane usage: unregistered physical checkout is a hard block ──"
root="$TMP/unregistered-physical"; state="$root/guard.json"; registry="$root/registry.json"; lane_state="$root/lane-disk-usage.json"; unregistered="$TMP/unregistered-checkout"
mkdir -p "$root"
git -C "$root" init -b main >/dev/null 2>&1
git -C "$root" config user.email disk-test@example.com
git -C "$root" config user.name "Disk Test"
printf 'main\n' > "$root/tracked.txt"
git -C "$root" add tracked.txt >/dev/null 2>&1
git -C "$root" commit -m initial >/dev/null 2>&1
git -C "$root" worktree add -b unregistered "$unregistered" HEAD >/dev/null 2>&1
printf 'unregistered\n' > "$unregistered/unregistered.txt"
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 "$SCRIPT" >/dev/null 2>&1
grep -q '"unregistered-physical-worktree"' "$lane_state" && ok "unregistered checkout is visible" || bad "unregistered checkout missing"
grep -q '"verdict": "block"' "$lane_state" && ok "unregistered checkout blocks" || bad "unregistered checkout did not block"
grep -q '"lane_usage_verdict":"block"' "$state" && ok "guard state carries unregistered block" || bad "guard state missed unregistered block"
grep -q '"lane_usage_rc":75' "$state" && ok "guard state carries hard-block exit" || bad "guard state missed hard-block exit"

echo "── lane report budget: slow attribution fails closed without hanging ──"
root="$TMP/time-budget"; state="$root/guard.json"; lane_state="$root/lane-disk-usage.json"
mkdir -p "$root"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_REGISTRY_STATE="$root/missing-registry.json" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" \
  KG_DISK_GUARD_LANE_USAGE_BUDGET_SECONDS=0 \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"budget_seconds": 0.0' "$lane_state" \
  && ok "lane report records its time budget" || bad "lane report budget missing"
grep -q 'measurement-time-budget-exceeded' "$lane_state" \
  && ok "time budget produces explicit measurement blocker" || bad "time budget blocker missing"
grep -q '"lane_usage_rc":75' "$state" \
  && ok "time budget reaches guard state" || bad "time budget guard state missing"
grep -q '"lane_usage_budget_seconds":0' "$state" \
  && ok "time budget is recorded in guard state" || bad "time budget state missing"

echo "── lane report budget: external attribution process is hard-stopped ──"
root="$TMP/external-timeout"; state="$root/guard.json"; lane_state="$root/lane-disk-usage.json"; fake_uv="$root/fake-uv"; child_pid_file="$root/child.pid"
mkdir -p "$root"
cat >"$fake_uv" <<'EOF'
#!/usr/bin/env bash
set -u
printf '%s\n' "$$" > "${FAKE_PID_FILE:?}"
sleep 5 &
wait
EOF
chmod +x "$fake_uv"
started=$SECONDS
if KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" \
  KG_DISK_GUARD_REGISTRY_STATE="$root/missing-registry.json" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" \
  KG_DISK_GUARD_LANE_USAGE_BUDGET_SECONDS=1 \
  KG_DISK_GUARD_UV_BIN="$fake_uv" FAKE_PID_FILE="$child_pid_file" \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  "$SCRIPT" >/dev/null 2>&1; then
  external_rc=0
else
  external_rc=$?
fi
elapsed=$((SECONDS - started))
(( external_rc == 0 )) && ok "guard preserves command exit compatibility" || bad "guard command exit changed after external timeout"
(( elapsed <= 3 )) && ok "external attribution is stopped within the hard budget" || bad "external attribution exceeded hard budget (${elapsed}s)"
grep -q '"lane_usage_rc":75' "$state" \
  && ok "external timeout reaches guard state as a hard block" || bad "external timeout did not reach guard state"
grep -q '"lane_usage_budget_seconds":1' "$state" \
  && ok "external timeout records its configured budget" || bad "external timeout budget missing"
if [[ -s "$child_pid_file" ]]; then
  child_pid="$(cat "$child_pid_file")"
  if ! kill -0 "$child_pid" 2>/dev/null; then
    ok "external timeout does not leave a child process"
  else
    bad "external timeout left a child process"
  fi
else
  bad "external timeout fixture did not record its child"
fi

echo "── shared XCTestDevices: over-budget platform storage is visible and untouched ──"
root="$TMP/xctest-budget"; xctest="$root/XCTestDevices"; state="$root/guard.json"; registry="$root/registry.json"; lane_state="$root/lane-disk-usage.json"
udid="55555555-5555-4555-8555-555555555555"; device="$xctest/$udid"
mkdir -p "$device/data"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>UDID</key><string>'"$udid"'</string><key>isEphemeral</key><false/><key>isDeleted</key><false/><key>state</key><string>Shutdown</string></dict></plist>' > "$device/device.plist"
dd if=/dev/zero of="$device/data/payload" bs=1024 count=4 >/dev/null 2>&1
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" KG_DISK_GUARD_XCTEST_DEVICES_ROOT="$xctest" \
  KG_DISK_GUARD_XCTEST_DEVICES_BUDGET_GIB=0 KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) \
  KG_DISK_GUARD_ACTIVE_BUILD=0 "$SCRIPT" >/dev/null 2>&1
grep -q 'xctest-devices-budget-exceeded' "$lane_state" && ok "shared XCTestDevices budget block is recorded" || bad "shared XCTestDevices budget block missing"
grep -q '"attribution": "shared-host-platform"' "$lane_state" && ok "shared XCTestDevices attribution is platform-scoped" || bad "shared XCTestDevices attribution missing"
grep -q '"xctest_devices_verdict":"block"' "$state" && ok "guard cannot claim within-bounds over shared budget" || bad "guard claimed within-bounds over shared budget"
grep -q '"xctest_devices_manual_review":1' "$state" && ok "unsafe shared device is manual review" || bad "shared device manual review missing"
[[ -d "$device" ]] && ok "non-ephemeral shared device is untouched" || bad "non-ephemeral shared device was deleted"

echo "── shared Simulator runtimes: visible, budgeted, and never auto-reclaimed ──"
root="$TMP/simulator-runtime"; state="$root/guard.json"; registry="$root/registry.json"; lane_state="$root/lane-disk-usage.json"
mkdir -p "$root"
printf '%s\n' '{"schema":"kg.worktree.registry.v2","records":[]}' > "$registry"
KG_DISK_GUARD_WORKSPACE="$root" KG_DISK_GUARD_STATE="$state" KG_DISK_GUARD_REGISTRY_STATE="$registry" \
  KG_DISK_GUARD_LANE_USAGE_STATE="$lane_state" KG_DISK_GUARD_SIMULATOR_RUNTIME_BUDGET_GIB=56 \
  KG_DISK_GUARD_FREE_BYTES=$((30*1073741824)) KG_DISK_GUARD_ACTIVE_BUILD=0 \
  "$SCRIPT" >/dev/null 2>&1
grep -q '"simulator_runtime_kb":' "$state" && ok "shared runtime bytes are in guard state" || bad "shared runtime bytes missing"
grep -q '"simulator_runtime_budget_kb":58720256' "$state" && ok "shared runtime budget is recorded" || bad "shared runtime budget missing"
grep -q '"simulator_runtime_count":' "$state" && ok "shared runtime count is recorded" || bad "shared runtime count missing"
grep -q '"simulator_runtime_reclaim_status":"not-supported"' "$state" \
  && ok "shared runtime reclaim is disabled" || bad "shared runtime reclaim contract drifted"
grep -q '"simulator_runtimes"' "$lane_state" && ok "lane report has shared runtime bucket" || bad "lane report shared runtime bucket missing"

echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
