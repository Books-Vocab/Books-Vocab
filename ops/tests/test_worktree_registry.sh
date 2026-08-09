#!/usr/bin/env bash
# Regression for IMP-20260809-e00c9f: hand-back without selectors must use cwd.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGISTRY="$ROOT/ops/worktree_registry.py"
TMP="$(mktemp -d -t kg_worktree_registry_XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

REPO="$TMP/current"
OTHER="$TMP/other"
STATE="$TMP/registry.json"
mkdir -p "$REPO" "$OTHER"
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email test@example.invalid
git -C "$REPO" config user.name test
printf 'base\n' > "$REPO/file"
git -C "$REPO" add file
git -C "$REPO" commit -qm base
mkdir "$REPO/nested"

"$REGISTRY" register --state "$STATE" --at 2999-01-01T00:00:00Z \
  --path "$REPO" --branch main --intent current --base main >/dev/null
"$REGISTRY" register --state "$STATE" --at 2999-01-01T00:00:00Z \
  --path "$OTHER" --branch other --intent another --base main >/dev/null

HELP="$($REGISTRY hand-back --help)"
grep -Fq -- '--branch' <<<"$HELP"

set +e
OUT="$(cd "$REPO/nested" && "$REGISTRY" hand-back \
  --state "$STATE" --at 2999-01-01T00:00:00Z --json 2>&1)"
RC=$?
set -e
if [[ "$RC" -ne 0 ]]; then
  echo "FAIL: hand-back default returned rc=$RC"
  printf '%s\n' "$OUT"
  exit 1
fi
grep -Fq '"action": "hand-back"' <<<"$OUT"
grep -Fq '"branch": "main"' <<<"$OUT"
grep -Fq '"handed_back_sha":' <<<"$OUT"

echo "PASS: hand-back default selects the current worktree"
