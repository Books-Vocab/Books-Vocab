#!/usr/bin/env bash
# Shared iOS test cache root resolution.
#
# Linked worktrees must share one content-keyed cache. Otherwise every test
# run creates a full DerivedData tree under its own worktree and abandoned
# worktrees retain gigabytes forever.

kg_ios_test_cache_root() {
  local project_root="$1"
  if [[ -n "${KG_IOS_TEST_CACHE_ROOT:-}" ]]; then
    printf '%s\n' "$KG_IOS_TEST_CACHE_ROOT"
    return 0
  fi

  local git_common_dir
  git_common_dir="$(git -C "$project_root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$git_common_dir" && -d "$git_common_dir" ]]; then
    printf '%s/.cache/ios-test-derived-data\n' "$(dirname "$git_common_dir")"
  else
    # Keep standalone/source archives usable when no git metadata is present.
    printf '%s/.cache/ios-test-derived-data\n' "$project_root"
  fi
}
