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

echo "PASS: ios build cache lifecycle"
