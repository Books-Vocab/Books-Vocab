#!/usr/bin/env bash
set -euo pipefail

WORKTREE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$WORKTREE/.." && pwd)"
BUILD="$WORKTREE/ios_build.sh"
TEST="$WORKTREE/ios_test.sh"
SWIFTPM_LIB="$WORKTREE/lib/ios_swiftpm_cache.sh"
LOCKFILE="$ROOT/ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
SWIFTPM_LIB_REL="ops/lib/ios_swiftpm_cache.sh"
LOCKFILE_REL="ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"

fail() { echo "FAIL: $*" >&2; exit 1; }

bash -n "$BUILD" || fail "ios_build.sh syntax"
plan="$(KG_IOS_BUILD_DERIVED_DATA_ROOT="$WORKTREE/.cache/test-ios-build-root" \
  "$BUILD" --catalyst --dry-run 2>&1)" || fail "catalyst dry-run"
grep -F '/.cache/test-ios-build-root/catalyst' <<<"$plan" \
  || fail "catalyst uses a dedicated derived-data root"
grep -F -- '-derivedDataPath' <<<"$plan" \
  || fail "dry-run exposes derived-data path"
grep -F 'IOS_DERIVED_DATA_ROOT=' "$BUILD" \
  || fail "catalyst cleans the sibling iOS cache under the build lock"
grep -F 'KG_IOS_CATALYST_KEEP_DERIVED_DATA' "$BUILD" \
  || fail "catalyst cleanup has an explicit diagnostic retention escape hatch"

[[ -f "$SWIFTPM_LIB" ]] || fail "SwiftPM cache helper is missing"
[[ -f "$LOCKFILE" ]] || fail "SwiftPM dependency lockfile is missing"
git -C "$ROOT" ls-files --error-unmatch -- "$SWIFTPM_LIB_REL" >/dev/null 2>&1 \
  || fail "SwiftPM cache helper is not tracked by Git"
git -C "$ROOT" ls-files --error-unmatch -- "$LOCKFILE_REL" >/dev/null 2>&1 \
  || fail "SwiftPM dependency lockfile is not tracked by Git"
if git -C "$ROOT" check-ignore -q -- "$LOCKFILE"; then
  fail "SwiftPM dependency lockfile is ignored instead of versioned"
fi

bash -n "$SWIFTPM_LIB" "$BUILD" "$TEST" || fail "SwiftPM cache scripts have invalid shell syntax"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/kg-ios-swiftpm-cache.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
fixture_root="$tmp/project"
fixture_lock="$fixture_root/ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
mkdir -p "$(dirname "$fixture_lock")"
printf '{"version": 3, "pins": []}\n' > "$fixture_lock"

# shellcheck source=../lib/ios_swiftpm_cache.sh
source "$SWIFTPM_LIB"

unset KG_IOS_SWIFTPM_CACHE_DIR
kg_ios_swiftpm_configure "$fixture_root"
[[ "${#KG_IOS_SWIFTPM_XCODEBUILD_ARGS[@]}" -eq 0 ]] \
  || fail "local runs unexpectedly receive a hosted SwiftPM cache"

if KG_IOS_SWIFTPM_CACHE_DIR='relative-cache' kg_ios_swiftpm_configure "$fixture_root" >"$tmp/relative.out" 2>"$tmp/relative.err"; then
  fail "relative SwiftPM cache root was accepted"
fi
grep -F 'absolute path' "$tmp/relative.err" >/dev/null \
  || fail "relative cache rejection is not actionable"

if KG_IOS_SWIFTPM_CACHE_DIR="$fixture_root/cache" kg_ios_swiftpm_configure "$fixture_root" >"$tmp/project.out" 2>"$tmp/project.err"; then
  fail "project-local SwiftPM cache root was accepted"
fi
grep -F 'outside the project root' "$tmp/project.err" >/dev/null \
  || fail "project-local cache rejection is not actionable"

missing_root="$tmp/missing-project"
mkdir -p "$missing_root"
if KG_IOS_SWIFTPM_CACHE_DIR="$tmp/hosted-cache" kg_ios_swiftpm_configure "$missing_root" >"$tmp/missing.out" 2>"$tmp/missing.err"; then
  fail "cache setup accepted a project without Package.resolved"
fi
grep -F 'Package.resolved' "$tmp/missing.err" >/dev/null \
  || fail "missing-lock rejection is not actionable"

hosted_cache_root="$(cd "$tmp" && pwd -P)/hosted-cache"
KG_IOS_SWIFTPM_CACHE_DIR="$hosted_cache_root" kg_ios_swiftpm_configure "$fixture_root"
expected_args=(
  -clonedSourcePackagesDirPath "$hosted_cache_root"
  -packageCachePath "$hosted_cache_root/package-cache"
  -onlyUsePackageVersionsFromResolvedFile
)
[[ "${KG_IOS_SWIFTPM_XCODEBUILD_ARGS[*]}" == "${expected_args[*]}" ]] \
  || fail "SwiftPM xcodebuild arguments differ from the safe cache contract"

plan="$(KG_IOS_BUILD_DERIVED_DATA_ROOT="$tmp/derived-data" \
  KG_IOS_SWIFTPM_CACHE_DIR="$hosted_cache_root" \
  "$BUILD" --dry-run 2>&1)" || fail "ios_build SwiftPM cache dry-run"
grep -F "argv=-clonedSourcePackagesDirPath" <<<"$plan" >/dev/null \
  || fail "ios_build does not pass the shared SwiftPM checkout root"
grep -F "argv=$hosted_cache_root" <<<"$plan" >/dev/null \
  || fail "ios_build does not use the requested SwiftPM cache root"
grep -F 'argv=-onlyUsePackageVersionsFromResolvedFile' <<<"$plan" >/dev/null \
  || fail "ios_build does not lock dependency resolution"

grep -F 'source "$SCRIPT_DIR/lib/ios_swiftpm_cache.sh"' "$TEST" >/dev/null \
  || fail "ios_test does not load the SwiftPM cache contract"
grep -F 'kg_ios_swiftpm_configure "$PROJECT_ROOT"' "$TEST" >/dev/null \
  || fail "ios_test does not configure the SwiftPM cache contract"
grep -F '"${KG_IOS_SWIFTPM_XCODEBUILD_ARGS[@]}"' "$TEST" >/dev/null \
  || fail "ios_test build-for-testing does not pass SwiftPM cache arguments"

echo "── ios_test writer disk-budget gate ──"
rebuild_start="$(awk '/^rebuild_test_cache\(\) \{/ { print NR; exit }' "$TEST")"
rebuild_end="$(awk 'NR > start && /^ensure_xctestrun_ready_or_fail\(\) \{/ { print NR; exit }' start="$rebuild_start" "$TEST")"
[[ -n "$rebuild_start" && -n "$rebuild_end" ]] \
  || fail "ios_test rebuild_test_cache function boundaries are not discoverable"
rebuild_body="$(sed -n "${rebuild_start},$((rebuild_end - 1))p" "$TEST")"
lock_line="$(awk '/^[[:space:]]*acquire_build_lock$/ { print NR; exit }' <<<"$rebuild_body")"
eviction_line="$(awk '/^[[:space:]]*kg_ios_cache_evict / { print NR; exit }' <<<"$rebuild_body")"
preflight_line="$(awk '/^[[:space:]]*if ! kg_ios_disk_budget_preflight / { print NR; exit }' <<<"$rebuild_body")"
xcodebuild_line="$(awk '/^[[:space:]]*xcodebuild build-for-testing/ { print NR; exit }' <<<"$rebuild_body")"
[[ -n "$lock_line" && -n "$eviction_line" && -n "$preflight_line" && -n "$xcodebuild_line" ]] \
  || fail "ios_test build writer is missing lock, eviction, disk preflight, or xcodebuild"
(( lock_line < eviction_line && eviction_line < preflight_line && preflight_line < xcodebuild_line )) \
  || fail "ios_test disk preflight is not after eviction and before xcodebuild"
grep -F 'disk_budget_project_root="$(dirname "$(dirname "$TEST_CACHE_ROOT")")"' <<<"$rebuild_body" >/dev/null \
  || fail "ios_test disk preflight does not resolve the shared cache project root"
grep -F 'kg_ios_disk_budget_preflight "$disk_budget_project_root" "test"' <<<"$rebuild_body" >/dev/null \
  || fail "ios_test disk preflight does not identify the test writer"
grep -F 'release_build_lock' <<<"$rebuild_body" >/dev/null \
  || fail "ios_test disk-budget block does not release the shared build lock"
grep -F 'return "$KG_IOS_DISK_BUDGET_EXIT"' <<<"$rebuild_body" >/dev/null \
  || fail "ios_test disk-budget block does not preserve exit=75"

echo "PASS: ios build cache lifecycle"
