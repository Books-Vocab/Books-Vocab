#!/usr/bin/env bash
# Contract tests for the bounded iOS development disk budget.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$ROOT/ops/lib/ios_disk_budget.sh"
TMP="$(mktemp -d -t kg_ios_disk_budget_test_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
export KG_IOS_DISK_GUARD_STATE="$TMP/guard-state.json"

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

echo "── disk guard shared XCTestDevices block stops a new writer ──"
guard_state="$TMP/guard-xctest-block.json"
cat > "$guard_state" <<'EOF'
{"schema":"kg.disk.guard.v1","verdict":"block","xctest_devices_verdict":"block","xctest_devices_reclaim_status":"not-requested","xctest_devices_manual_review":1,"at":"2099-01-01T00:00:00Z"}
EOF
guard_output=""
guard_rc=0
guard_output="$(KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_GUARD_STATE="$guard_state" KG_IOS_DISK_GUARD_ENFORCE_XCTEST=1 \
  KG_IOS_DISK_CACHE_BUDGET_GIB=1 KG_IOS_DISK_CACHE_HEADROOM_GIB=0 \
  KG_IOS_DISK_MIN_FREE_GIB=20 KG_IOS_DISK_FREE_BYTES=$((40 * 1073741824)) \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" 2>&1)" || guard_rc=$?
[[ "$guard_rc" -eq 77 ]] && ok "XCTestDevices manual-review block exits 77 (not retryable)" || bad "shared XCTestDevices block exit=$guard_rc"
grep -q 'reason=xctest-devices-manual-review-required' <<<"$guard_output" \
  && ok "shared XCTestDevices blocker is structured" \
  || bad "shared XCTestDevices blocker missing: $guard_output"

echo "── stale disk guard state fails closed when enforcement is enabled ──"
stale_state="$TMP/guard-stale.json"
cat > "$stale_state" <<'EOF'
{"schema":"kg.disk.guard.v1","verdict":"ok","xctest_devices_verdict":"pass","at":"2000-01-01T00:00:00Z"}
EOF
stale_rc=0
stale_output="$(KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_GUARD_STATE="$stale_state" KG_IOS_DISK_GUARD_ENFORCE_XCTEST=1 \
  KG_IOS_DISK_GUARD_MAX_AGE_SECONDS=900 KG_IOS_DISK_CACHE_BUDGET_GIB=1 \
  KG_IOS_DISK_CACHE_HEADROOM_GIB=0 KG_IOS_DISK_MIN_FREE_GIB=20 \
  KG_IOS_DISK_FREE_BYTES=$((40 * 1073741824)) \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" 2>&1)" || stale_rc=$?
[[ "$stale_rc" -eq 75 ]] && ok "stale disk guard state exits 75" || bad "stale disk guard state exit=$stale_rc"
grep -q 'reason=disk-guard-state-stale' <<<"$stale_output" \
  && ok "stale disk guard reason is structured" \
  || bad "stale disk guard reason missing: $stale_output"

echo "── fresh healthy disk guard state permits a writer ──"
fresh_state="$TMP/guard-fresh.json"
cat > "$fresh_state" <<EOF
{"schema":"kg.disk.guard.v1","verdict":"ok","xctest_devices_verdict":"pass","at":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')"}
EOF
fresh_rc=0
fresh_output="$(KG_IOS_DISK_CACHE_ROOTS="$cache_root/ios-build-derived-data:$cache_root/ios-test-derived-data:$cache_root/ios/build" \
  KG_IOS_DISK_GUARD_STATE="$fresh_state" KG_IOS_DISK_GUARD_ENFORCE_XCTEST=1 \
  KG_IOS_DISK_GUARD_MAX_AGE_SECONDS=900 KG_IOS_DISK_CACHE_BUDGET_GIB=1 \
  KG_IOS_DISK_CACHE_HEADROOM_GIB=0 KG_IOS_DISK_MIN_FREE_GIB=20 \
  KG_IOS_DISK_FREE_BYTES=$((40 * 1073741824)) \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_preflight '$cache_root' build" 2>&1)" || fresh_rc=$?
[[ "$fresh_rc" -eq 0 ]] && ok "fresh disk guard state permits writer" || bad "fresh disk guard state exit=$fresh_rc"
grep -q 'verdict=pass' <<<"$fresh_output" \
  && ok "fresh disk guard state is accepted" \
  || bad "fresh disk guard state rejected: $fresh_output"

echo "── lane-attribution block names the worktrees and reasons ──"
lane_state="$TMP/lane-block-usage.json"
cat > "$lane_state" <<'EOF'
{
  "policy": {
    "blocking_reasons": [
      "unregistered-physical-worktree"
    ],
    "blocking_dirty_physical_worktrees": [],
    "unknown_physical_worktrees": [],
    "unregistered_physical_worktrees": [
      "/x/orphan-one",
      "/x/orphan-two"
    ]
  }
}
EOF
lane_block_state="$TMP/lane-block-guard.json"
cat > "$lane_block_state" <<EOF
{"schema":"kg.disk.guard.v1","verdict":"block","reason":"lane-usage-report-blocked","action":"manual-review-lane-attribution","lane_usage_verdict":"block","xctest_devices_verdict":"pass","at":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')"}
EOF
lane_rc=0
lane_output="$(KG_IOS_DISK_GUARD_STATE="$lane_block_state" KG_IOS_DISK_LANE_USAGE_STATE="$lane_state" \
  KG_IOS_DISK_GUARD_AUTO_REFRESH=0 \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_guard_state test" 2>&1)" || lane_rc=$?
[[ "$lane_rc" -eq 77 ]] && ok "lane block exits 77 (structural)" || bad "lane block exit=$lane_rc"
grep -q 'blockingReasons=unregistered-physical-worktree' <<<"$lane_output" \
  && ok "diagnostic names blocking reason" || bad "diagnostic reason missing: $lane_output"
grep -q 'unregisteredWorktrees=/x/orphan-one;/x/orphan-two' <<<"$lane_output" \
  && ok "diagnostic names unregistered worktree paths" || bad "diagnostic paths missing: $lane_output"
grep -q 'guardReason=lane-usage-report-blocked' <<<"$lane_output" \
  && ok "diagnostic names guard reason" || bad "diagnostic guardReason missing: $lane_output"
grep -q 'guard --refresh' <<<"$lane_output" \
  && ok "diagnostic points at the refresh command" || bad "diagnostic refresh hint missing: $lane_output"

echo "── inline refresh clears a stale lane block ──"
fake_tick="$TMP/fake_tick.sh"
cat > "$fake_tick" <<'EOF'
#!/usr/bin/env bash
printf '{"schema":"kg.disk.guard.v1","verdict":"ok","xctest_devices_verdict":"pass","at":"%s"}\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$KG_DISK_GUARD_STATE"
echo "$KG_DISK_GUARD_BUILD_LOCK_HELD" > "$KG_DISK_GUARD_STATE.lockheld"
EOF
chmod +x "$fake_tick"
cp "$lane_block_state" "$TMP/lane-refresh-guard.json"
refresh_rc=0
refresh_output="$(KG_IOS_DISK_GUARD_STATE="$TMP/lane-refresh-guard.json" KG_IOS_DISK_GUARD_TICK="$fake_tick" \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_guard_state test" 2>&1)" || refresh_rc=$?
[[ "$refresh_rc" -eq 0 ]] && ok "stale lane block is cleared by inline refresh" || bad "inline refresh exit=$refresh_rc: $refresh_output"
[[ "$(cat "$TMP/lane-refresh-guard.json.lockheld" 2>/dev/null)" == "1" ]] \
  && ok "inline refresh tells the tick the build lock is held" || bad "inline refresh lock flag wrong"

echo "── refresh that still blocks keeps exit 77 with diagnostics ──"
cat > "$fake_tick" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cp "$lane_block_state" "$TMP/lane-still-guard.json"
still_rc=0
still_output="$(KG_IOS_DISK_GUARD_STATE="$TMP/lane-still-guard.json" KG_IOS_DISK_GUARD_TICK="$fake_tick" \
  KG_IOS_DISK_LANE_USAGE_STATE="$lane_state" \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_guard_state test" 2>&1)" || still_rc=$?
[[ "$still_rc" -eq 77 ]] && ok "unresolved block still exits 77 after one refresh" || bad "still-block exit=$still_rc"
grep -q 'unregisteredWorktrees=/x/orphan-one' <<<"$still_output" \
  && ok "unresolved block still names worktrees" || bad "still-block diagnostics missing: $still_output"

echo "── refresh from a linked worktree runs the canonical checkout's tick ──"
# The host-global guard state has one writer identity (the canonical tick, as
# the launchd job runs it).  A lane's own copy must never publish into it.
canon="$TMP/refresh-canonical"; refresh_lane="$TMP/refresh-canonical-lane"; refresh_record="$TMP/refresh-record"
mkdir -p "$canon/ops/lib"
cp "$LIB" "$canon/ops/lib/ios_disk_budget.sh"
cat > "$canon/ops/kg_disk_guard.sh" <<'EOF'
#!/usr/bin/env bash
printf 'tick=canonical workspace=%s\n' "${KG_DISK_GUARD_WORKSPACE:-}" > "$KG_TEST_REFRESH_RECORD"
EOF
chmod +x "$canon/ops/kg_disk_guard.sh"
git -C "$canon" init -b main >/dev/null 2>&1
git -C "$canon" config user.email disk-test@example.com
git -C "$canon" config user.name "Disk Test"
git -C "$canon" add ops >/dev/null 2>&1
git -C "$canon" commit -m initial >/dev/null 2>&1
git -C "$canon" worktree add -b refresh-lane "$refresh_lane" HEAD >/dev/null 2>&1
cat > "$refresh_lane/ops/kg_disk_guard.sh" <<'EOF'
#!/usr/bin/env bash
printf 'tick=lane workspace=%s\n' "${KG_DISK_GUARD_WORKSPACE:-}" > "$KG_TEST_REFRESH_RECORD"
EOF
canon_real="$(cd "$canon" && pwd -P)"
refresh_rc=0
(
  unset KG_DISK_GUARD_WORKSPACE KG_IOS_DISK_GUARD_TICK
  KG_TEST_REFRESH_RECORD="$refresh_record" \
    /bin/bash -c "source '$refresh_lane/ops/lib/ios_disk_budget.sh'; kg_ios_disk_guard_refresh '$TMP/refresh-canonical-state.json' 0"
) || refresh_rc=$?
recorded="$(cat "$refresh_record" 2>/dev/null || true)"
[[ "$refresh_rc" -eq 0 ]] && ok "lane refresh succeeds" || bad "lane refresh exit=$refresh_rc"
[[ "$recorded" == tick=canonical* ]] \
  && ok "lane refresh runs the canonical tick, not the lane copy" || bad "lane refresh ran: ${recorded:-nothing}"
[[ "$(cd "${recorded##*workspace=}" 2>/dev/null && pwd -P)" == "$canon_real" ]] \
  && ok "lane refresh roots the tick at the canonical checkout" || bad "lane refresh workspace: ${recorded:-nothing}"

echo "── refresh without a resolvable canonical checkout fails closed ──"
loose="$TMP/refresh-no-git"; loose_record="$TMP/refresh-no-git-record"
mkdir -p "$loose/ops/lib"
cp "$LIB" "$loose/ops/lib/ios_disk_budget.sh"
cat > "$loose/ops/kg_disk_guard.sh" <<'EOF'
#!/usr/bin/env bash
printf 'ran\n' > "$KG_TEST_REFRESH_RECORD"
EOF
chmod +x "$loose/ops/kg_disk_guard.sh"
loose_rc=0
(
  unset KG_DISK_GUARD_WORKSPACE KG_IOS_DISK_GUARD_TICK
  GIT_CEILING_DIRECTORIES="$TMP" KG_TEST_REFRESH_RECORD="$loose_record" \
    /bin/bash -c "source '$loose/ops/lib/ios_disk_budget.sh'; kg_ios_disk_guard_refresh '$TMP/refresh-no-git-state.json' 0"
) || loose_rc=$?
[[ "$loose_rc" -ne 0 ]] && ok "unresolvable canonical refresh fails" || bad "unresolvable canonical refresh exited 0"
[[ ! -e "$loose_record" ]] \
  && ok "no tick publishes from a script-relative fallback root" || bad "a tick ran without a canonical root"

echo "── structural guard block is a distinct non-retryable exit 77 ──"
struct_rc=0
struct_output="$(KG_IOS_DISK_GUARD_STATE="$lane_block_state" KG_IOS_DISK_LANE_USAGE_STATE="$lane_state" \
  KG_IOS_DISK_GUARD_AUTO_REFRESH=0 \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_guard_state test" 2>&1)" || struct_rc=$?
[[ "$struct_rc" -eq 77 ]] && ok "unregistered-worktree block exits 77" || bad "structural block exit=$struct_rc"
grep -q 'retryable=no' <<<"$struct_output" \
  && ok "structural block says retryable=no" || bad "retryable=no missing: $struct_output"
grep -q 'guardAction=manual-review-lane-attribution' <<<"$struct_output" \
  && ok "structural block prints the guard's own action" || bad "guard action missing: $struct_output"

xctest_budget_state="$TMP/guard-xctest-budget.json"
cat > "$xctest_budget_state" <<'EOF2'
{"schema":"kg.disk.guard.v1","verdict":"block","xctest_devices_verdict":"block","xctest_devices_manual_review":0,"at":"2099-01-01T00:00:00Z"}
EOF2
xctest_rc=0
KG_IOS_DISK_GUARD_STATE="$xctest_budget_state" KG_IOS_DISK_GUARD_ENFORCE_XCTEST=1 \
  /bin/bash -c "source '$LIB'; kg_ios_disk_budget_guard_state test" >/dev/null 2>&1 || xctest_rc=$?
[[ "$xctest_rc" -eq 75 ]] && ok "XCTestDevices budget block keeps 75" || bad "xctest block exit=$xctest_rc"

echo "── ios_ops.sh test reads the guard before the lease and the build lock ──"
early_lock="$TMP/early-build.lock"
early_leases="$TMP/early-leases"
early_verdict="$TMP/early-verdict"
early_start=$SECONDS
early_rc=0
early_output="$(KG_IOS_DISK_GUARD_STATE="$lane_block_state" KG_IOS_DISK_LANE_USAGE_STATE="$lane_state" \
  KG_IOS_DISK_GUARD_AUTO_REFRESH=0 KG_IOS_BUILD_LOCK_FILE="$early_lock" \
  KG_IOS_SIM_LEASE_ROOT="$early_leases" KG_IOS_VERDICT_FILE="$early_verdict" \
  "$ROOT/ops/ios_ops.sh" test --lease 2>&1)" || early_rc=$?
early_elapsed=$((SECONDS - early_start))
[[ "$early_rc" -eq 77 ]] && ok "ios_ops.sh test exits 77 on a structural block" || bad "ios_ops.sh test exit=$early_rc: $early_output"
(( early_elapsed <= 10 )) && ok "verdict arrives within 10s (${early_elapsed}s)" || bad "verdict took ${early_elapsed}s"
[[ ! -e "$early_leases" ]] && ok "no simulator lease was touched" || bad "lease root was created"
[[ -z "$(ls "$TMP" | grep '^early-build.lock')" ]] && ok "build lock was never taken" || bad "build lock artifacts exist"
grep -q 'unregisteredWorktrees=/x/orphan-one;/x/orphan-two' <<<"$early_output" \
  && ok "early verdict names the blocking worktrees" || bad "early verdict lacks worktrees: $early_output"
grep -q 'clean rebuildable cache' <<<"$early_output" \
  && bad "structural block still tells the agent to clean cache" || ok "no misleading clean-cache advice"

echo "── ios_ops.sh build reads the guard before queueing for the build lock ──"
build_rc=0
build_start=$SECONDS
build_output="$(KG_IOS_DISK_GUARD_STATE="$lane_block_state" KG_IOS_DISK_LANE_USAGE_STATE="$lane_state" \
  KG_IOS_DISK_GUARD_AUTO_REFRESH=0 KG_IOS_BUILD_LOCK_FILE="$early_lock" \
  "$ROOT/ops/ios_ops.sh" build 2>&1)" || build_rc=$?
[[ "$build_rc" -eq 77 ]] && ok "ios_ops.sh build exits 77 on a structural block" || bad "build exit=$build_rc: $build_output"
(( SECONDS - build_start <= 10 )) && ok "build verdict arrives within 10s" || bad "build verdict was slow"
[[ -z "$(ls "$TMP" | grep '^early-build.lock')" ]] && ok "build never took the lock" || bad "build lock artifacts exist"

echo "── disk-space style guard block keeps 75, also before lease and lock ──"
space_state="$TMP/guard-space-block.json"
cat > "$space_state" <<EOF
{"schema":"kg.disk.guard.v1","verdict":"critical","reason":"free-below-critical","action":"evict-old-ios-cache","lane_usage_verdict":"pass","xctest_devices_verdict":"pass","at":"$(date -u '+%Y-%m-%dT%H:%M:%SZ')"}
EOF
space_rc=0
space_output="$(KG_IOS_DISK_GUARD_STATE="$space_state" KG_IOS_DISK_GUARD_AUTO_REFRESH=0 \
  KG_IOS_BUILD_LOCK_FILE="$early_lock" KG_IOS_SIM_LEASE_ROOT="$early_leases" \
  KG_IOS_VERDICT_FILE="$early_verdict" "$ROOT/ops/ios_ops.sh" test --lease 2>&1)" || space_rc=$?
[[ "$space_rc" -eq 75 ]] && ok "disk-space guard block exits 75" || bad "space block exit=$space_rc: $space_output"
[[ ! -e "$early_leases" ]] && ok "space block also stops before the lease" || bad "lease root created on space block"

echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
