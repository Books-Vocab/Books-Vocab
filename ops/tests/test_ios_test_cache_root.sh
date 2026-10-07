#!/usr/bin/env bash
# Ensure iOS test DerivedData is anchored at the shared git common directory,
# not duplicated inside every linked worktree.
#
# The main-plus-linked-worktree topology lives in a disposable `git init`
# repository under this test's temp dir; the real checkout is only read.  A
# linked worktree registered in the real repository is visible to every live
# delivery/audit tool while the test runs, and a killed run (timeout, SIGKILL)
# skips the EXIT trap and leaves a stale .git/worktrees entry behind (#2119).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# A caller's GIT_DIR / GIT_INDEX_FILE / ... (git hooks, `rebase --exec`) would
# point fixture commands at the real repository; KG_IOS_TEST_CACHE_ROOT would
# short-circuit the resolver under test.
for var in $(git rev-parse --local-env-vars); do unset "$var"; done
unset KG_IOS_TEST_CACHE_ROOT
# Not in --local-env-vars but still shape a fixture: GIT_TEMPLATE_DIR outranks
# init.templateDir and copies the caller's hooks into the new repository;
# GIT_AUTHOR_* / GIT_COMMITTER_* outrank the -c identity; GIT_DEFAULT_* change
# the new repository's hash / ref format.
unset GIT_TEMPLATE_DIR \
  GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_AUTHOR_DATE \
  GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_COMMITTER_DATE \
  GIT_DEFAULT_HASH GIT_DEFAULT_REF_FORMAT

FIXTURE_ROOT="$(mktemp -d -t kg_ios_cache_worktree_XXXXXX)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT
# git reports physical paths; macOS TMPDIR sits behind /var -> /private/var.
FIXTURE_ROOT="$(cd "$FIXTURE_ROOT" && pwd -P)"

# A known-empty template: even with the env unset, an `init.templateDir` that
# somehow survives must not copy hooks into the fixture.
EMPTY_TEMPLATE="$FIXTURE_ROOT/empty-template"
mkdir "$EMPTY_TEMPLATE"

# The developer's global/system config (hooksPath, gpgsign, templateDir) must
# not shape the fixture.
fixture_git() {
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    git -c user.name='kg ios cache test' -c user.email=ios-cache-test@example.invalid "$@"
}

# Worktree paths only: HEAD/branch/lock columns churn with every concurrent
# commit and are not this test's footprint.
real_worktree_paths() {
  git -C "$ROOT" worktree list --porcelain | sed -n 's/^worktree //p' | LC_ALL=C sort
}

source "$ROOT/ops/lib/ios_test_cache_root.sh"

# Build main + linked worktree, resolve both cache roots, and record how the
# real repository's worktree paths moved in the meantime.
run_fixture() {
  local before after
  before="$(real_worktree_paths)"
  fixture_git init -q --template="$EMPTY_TEMPLATE" -b main "$MAIN"
  fixture_git -C "$MAIN" commit -q --allow-empty -m fixture
  fixture_git -C "$MAIN" worktree add -q --detach "$WORKTREE" HEAD
  main_root="$(kg_ios_test_cache_root "$MAIN")"
  worktree_root="$(kg_ios_test_cache_root "$WORKTREE")"
  after="$(real_worktree_paths)"
  changes="$(
    LC_ALL=C comm -13 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | sed 's/^/added:   /'
    LC_ALL=C comm -23 <(printf '%s\n' "$before") <(printf '%s\n' "$after") | sed 's/^/removed: /'
  )"
}

fail_real_repo_changed() {
  echo "FAIL: $1 ($ROOT)" >&2
  printf '%s\n' "$changes" | sed 's/^/  /' >&2
  exit 1
}

# The real worktree list must be identical before and after the fixture.  Other
# agents add/remove worktrees concurrently (a fan-out creates one every few
# seconds), so a change outside the fixture root earns a fresh attempt; a change
# under the fixture root is this test's own and fails at once.  An addition the
# test makes elsewhere recurs on every attempt and still fails.  Blind spot: a
# one-shot or idempotent change to the real repository (`worktree remove`,
# `worktree prune`, a removal of any kind) is indistinguishable from concurrent
# churn, is retried, and passes once later attempts see no further change.
# Only strict equality without retries would catch it, and that is flaky while
# other agents share the repository.
for attempt in 1 2 3; do
  MAIN="$FIXTURE_ROOT/attempt-$attempt/main"
  WORKTREE="$FIXTURE_ROOT/attempt-$attempt/linked"
  run_fixture
  [[ -n "$changes" ]] || break
  grep -qF -- "$FIXTURE_ROOT/" <<<"$changes" \
    && fail_real_repo_changed "test registered its fixture in the real repository's worktree list"
  [[ "$attempt" -lt 3 ]] \
    || fail_real_repo_changed "real repository's worktree list changed during each of 3 attempts"
  echo "NOTE: real worktree list changed outside the fixture during attempt $attempt; retrying" >&2
  printf '%s\n' "$changes" | sed 's/^/  /' >&2
done

[[ -f "$WORKTREE/.git" ]] \
  || { echo "FAIL: fixture did not create a linked worktree at $WORKTREE" >&2; exit 1; }

[[ "$main_root" == "$worktree_root" ]] \
  || { echo "FAIL: linked worktrees use different iOS test cache roots" >&2; printf 'main=%s\nworktree=%s\n' "$main_root" "$worktree_root" >&2; exit 1; }

expected_root="$MAIN/.cache/ios-test-derived-data"
[[ "$main_root" == "$expected_root" ]] \
  || { echo "FAIL: cache root is not anchored at git common directory" >&2; printf 'actual=%s\nexpected=%s\n' "$main_root" "$expected_root" >&2; exit 1; }

echo "PASS: iOS test cache root is shared across linked worktrees"
