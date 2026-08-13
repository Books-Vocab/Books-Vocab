#!/usr/bin/env bash
set -euo pipefail

WORKTREE="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$WORKTREE/ios_build.sh"

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

echo "PASS: ios build cache lifecycle"
