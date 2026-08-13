#!/usr/bin/env bash
# Ensure iOS test DerivedData is anchored at the shared git common directory,
# not duplicated inside every linked worktree.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKTREE="$(find "$ROOT/.claude/worktrees" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -n "$WORKTREE" ]] || { echo "FAIL: no linked worktree fixture available" >&2; exit 1; }

source "$ROOT/ops/lib/ios_test_cache_root.sh"
main_root="$(kg_ios_test_cache_root "$ROOT")"
worktree_root="$(kg_ios_test_cache_root "$WORKTREE")"
[[ "$main_root" == "$worktree_root" ]] \
  || { echo "FAIL: linked worktrees use different iOS test cache roots" >&2; printf 'main=%s\nworktree=%s\n' "$main_root" "$worktree_root" >&2; exit 1; }

expected_root="$(dirname "$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)")/.cache/ios-test-derived-data"
[[ "$main_root" == "$expected_root" ]] \
  || { echo "FAIL: cache root is not anchored at git common directory" >&2; printf 'actual=%s\nexpected=%s\n' "$main_root" "$expected_root" >&2; exit 1; }

echo "PASS: iOS test cache root is shared across linked worktrees"
