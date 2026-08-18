#!/usr/bin/env bash
# Ensure iOS test DerivedData is anchored at the shared git common directory,
# not duplicated inside every linked worktree.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIXTURE_ROOT="$(mktemp -d -t kg_ios_cache_worktree_XXXXXX)"
WORKTREE="$FIXTURE_ROOT/worktree"
cleanup() {
  git -C "$ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$FIXTURE_ROOT"
}
trap cleanup EXIT

# CI checks out a clean repository and must not depend on a developer's old
# .claude/worktrees directory.  Create a disposable linked worktree through
# Git's own administration so the assertion exercises the real common-dir
# topology without touching any active worktree.
git -C "$ROOT" worktree add --detach "$WORKTREE" HEAD >/dev/null

source "$ROOT/ops/lib/ios_test_cache_root.sh"
main_root="$(kg_ios_test_cache_root "$ROOT")"
worktree_root="$(kg_ios_test_cache_root "$WORKTREE")"
[[ "$main_root" == "$worktree_root" ]] \
  || { echo "FAIL: linked worktrees use different iOS test cache roots" >&2; printf 'main=%s\nworktree=%s\n' "$main_root" "$worktree_root" >&2; exit 1; }

expected_root="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")/.cache/ios-test-derived-data"
[[ "$main_root" == "$expected_root" ]] \
  || { echo "FAIL: cache root is not anchored at git common directory" >&2; printf 'actual=%s\nexpected=%s\n' "$main_root" "$expected_root" >&2; exit 1; }

echo "PASS: iOS test cache root is shared across linked worktrees"
