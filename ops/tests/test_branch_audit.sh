#!/usr/bin/env bash
# Offline regression tests for ops/branch_audit.sh.

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
AUDIT="$WORKSPACE/ops/branch_audit.sh"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

setup_repo() {
  TMP="$(mktemp -d)"
  export TMP
  trap 'rm -rf "$TMP"' EXIT
  mkdir -p "$TMP/origin.git" "$TMP/bin"
  git init --bare "$TMP/origin.git" >/dev/null
  git init "$TMP/work" >/dev/null
  git -C "$TMP/work" config user.name "Branch Audit Test"
  git -C "$TMP/work" config user.email "branch-audit@example.test"
  printf 'root\n' >"$TMP/work/root.txt"
  git -C "$TMP/work" add root.txt
  git -C "$TMP/work" commit -m "root" >/dev/null
  git -C "$TMP/work" branch -M main
  git -C "$TMP/work" remote add origin "$TMP/origin.git"
  git -C "$TMP/work" push -u origin main >/dev/null

  cat >"$TMP/bin/gh" <<'GH'
#!/usr/bin/env bash
head=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --head) head="$2"; shift 2 ;;
    *) shift ;;
  esac
done
case "$head" in
  open-pr)
    printf '[{"number":12,"state":"OPEN","mergedAt":null,"title":"open work","url":"https://example.test/pull/12","headRefName":"open-pr","updatedAt":"2026-06-01T00:00:00Z"}]\n'
    ;;
  merged-ahead)
    printf '[{"number":34,"state":"MERGED","mergedAt":"2026-06-01T00:00:00Z","title":"merged but ahead","url":"https://example.test/pull/34","headRefName":"merged-ahead","updatedAt":"2026-06-01T00:00:00Z"}]\n'
    ;;
  *)
    printf '[]\n'
    ;;
esac
GH
  chmod +x "$TMP/bin/gh"
}

make_branch() {
  name="$1"
  date="${2:-2026-06-01T00:00:00Z}"
  git -C "$TMP/work" checkout -B "$name" main >/dev/null
  printf '%s\n' "$name" >"$TMP/work/$name.txt"
  git -C "$TMP/work" add "$name.txt"
  GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" git -C "$TMP/work" commit -m "$name" >/dev/null
  git -C "$TMP/work" push -u origin "$name" >/dev/null
  git -C "$TMP/work" checkout main >/dev/null
}

section "Syntax"
bash -n "$AUDIT" && ok "branch_audit syntax" || fail_t "branch_audit syntax"
[[ -x "$AUDIT" ]] && ok "branch_audit executable" || fail_t "branch_audit not executable"

setup_repo

make_branch safe-delete
git -C "$TMP/work" checkout main >/dev/null
git -C "$TMP/work" merge --no-ff safe-delete -m "merge safe-delete" >/dev/null
git -C "$TMP/work" push origin main >/dev/null
make_branch open-pr
make_branch merged-ahead
make_branch orphan-ahead
make_branch stale-ahead "2020-01-01T00:00:00Z"
git -C "$TMP/work" fetch origin >/dev/null

section "Classification"
set +e
PATH="$TMP/bin:$PATH" KG_BRANCH_AUDIT_ROOT="$TMP/work" "$AUDIT" --no-fetch --base origin/main --stale-days 1000 >"$TMP/audit.txt" 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]] && ok "unsafe branches exit 2" || fail_t "expected exit 2, got $rc"
grep -q '\[branch\]\[ok\] origin/safe-delete fully merged -> safe-delete' "$TMP/audit.txt" \
  && ok "safe-delete classified" || fail_t "safe-delete missing"
grep -q '\[branch\]\[ok\] origin/open-pr open PR #12' "$TMP/audit.txt" \
  && ok "open-pr classified" || fail_t "open-pr missing"
grep -q '\[branch\]\[warn\] origin/merged-ahead PR #34 merged but branch has 1 commits not in origin/main' "$TMP/audit.txt" \
  && ok "merged-pr-but-ahead classified" || fail_t "merged-pr-but-ahead missing"
grep -q '\[branch\]\[block\] origin/orphan-ahead no open PR and 1 commits not in origin/main' "$TMP/audit.txt" \
  && ok "orphan-ahead classified" || fail_t "orphan-ahead missing"
grep -q '\[branch\]\[block\] origin/stale-ahead stale-ahead' "$TMP/audit.txt" \
  && ok "stale-ahead classified" || fail_t "stale-ahead missing"
grep -q 'merged-ahead' "$TMP/audit.txt" && grep -q 'orphan-ahead' "$TMP/audit.txt" \
  && ok "ahead branch logs are printed" || fail_t "ahead commit logs missing"

section "JSON schema"
set +e
PATH="$TMP/bin:$PATH" KG_BRANCH_AUDIT_ROOT="$TMP/work" "$AUDIT" --no-fetch --base origin/main --stale-days 1000 --json >"$TMP/audit.json" 2>"$TMP/audit_json.err"
json_rc=$?
set -e
[[ "$json_rc" -eq 2 ]] && ok "json keeps audit exit code" || fail_t "json expected rc=2 got $json_rc"
if jq -e '.schema=="kg.branch_audit.v1" and .summary.total==5 and .summary.warn==1 and .summary.block==2 and any(.branches[]; .status=="merged-pr-but-ahead" and .mergedPrNumber==34) and any(.branches[]; .status=="open-pr" and .openPrNumber==12)' "$TMP/audit.json" >/dev/null; then
  ok "json schema + counts"
else
  cat "$TMP/audit.json" >&2
  fail_t "json schema invalid"
fi

section "Delete merged dry-run"
PATH="$TMP/bin:$PATH" KG_BRANCH_AUDIT_ROOT="$TMP/work" "$AUDIT" --no-fetch --base origin/main --delete-merged --dry-run >"$TMP/delete.txt" 2>&1 || true
grep -q '\[branch\]\[delete\]\[dry-run\] would run: git push origin --delete safe-delete' "$TMP/delete.txt" \
  && ok "delete merged is dry-run by default" || fail_t "delete dry-run missing"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
