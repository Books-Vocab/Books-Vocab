#!/usr/bin/env bash
# Offline regression tests for ops/review_audit.sh.

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
AUDIT="$WORKSPACE/ops/review_audit.sh"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

setup_repo() {
  TMP="$(mktemp -d)"
  export TMP
  trap 'rm -rf "$TMP"' EXIT
  git init "$TMP/repo" >/dev/null
  git -C "$TMP/repo" config user.name "Review Audit Test"
  git -C "$TMP/repo" config user.email "review-audit@example.test"
  printf 'root\n' >"$TMP/repo/root.txt"
  git -C "$TMP/repo" add root.txt
  git -C "$TMP/repo" commit -m "root" >/dev/null
  git -C "$TMP/repo" branch -M main

  git -C "$TMP/repo" checkout -B feature/review-audit >/dev/null
}

commit_with_message() {
  local file="$1"
  local body="$2"
  printf '%s\n' "$file" >"$TMP/repo/$file.txt"
  git -C "$TMP/repo" add "$file.txt"
  git -C "$TMP/repo" commit -F - >/dev/null <<EOF
$body
EOF
}

section "Syntax"
bash -n "$AUDIT" && ok "review_audit syntax" || fail_t "review_audit syntax"
[[ -x "$AUDIT" ]] && ok "review_audit executable" || fail_t "review_audit not executable"

setup_repo

commit_with_message "reviewed" $'feat: reviewed change\n\nReviewed-by: Background Reviewer <review@example.test>'
commit_with_message "exempt" $'docs: trivial typo\n\nReview-Exempt: trivial-typo'
commit_with_message "missing" $'ops: missing receipt'
commit_with_message "invalid" $'refactor: too broad for exemption\n\nReview-Exempt: bulk-refactor'

section "Text mode"
set +e
KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main >"$TMP/review_audit.txt" 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]] && ok "missing or invalid receipt exits 2" || fail_t "expected exit 2, got $rc"
grep -q '\[review\]\[ok\] .* feat: reviewed change' "$TMP/review_audit.txt" \
  && ok "reviewed commit classified" || fail_t "reviewed commit missing"
grep -q '\[review\]\[ok\] .* docs: trivial typo' "$TMP/review_audit.txt" \
  && ok "exempt commit classified" || fail_t "exempt commit missing"
grep -q '\[review\]\[block\] .* ops: missing receipt' "$TMP/review_audit.txt" \
  && ok "missing receipt classified" || fail_t "missing receipt missing"
grep -q '\[review\]\[block\] .* refactor: too broad for exemption' "$TMP/review_audit.txt" \
  && ok "invalid exemption classified" || fail_t "invalid exemption missing"

section "JSON schema"
set +e
KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main --json >"$TMP/review_audit.json" 2>"$TMP/review_audit_json.err"
json_rc=$?
set -e
[[ "$json_rc" -eq 2 ]] && ok "json keeps audit exit code" || fail_t "json expected rc=2 got $json_rc"
if jq -e '.schema=="kg.review_audit.v1"
  and .summary.total==4
  and .summary.ok==2
  and .summary.block==2
  and .summary.reviewed==1
  and .summary.exempt==1
  and .summary.missing==1
  and .summary.invalidExemption==1
  and any(.commits[]; .status=="reviewed" and .trailers.reviewedBy=="Background Reviewer <review@example.test>")
  and any(.commits[]; .status=="invalid-exemption" and .trailers.reviewExempt=="bulk-refactor")' "$TMP/review_audit.json" >/dev/null; then
  ok "json schema + counts"
else
  cat "$TMP/review_audit.json" >&2
  fail_t "json schema invalid"
fi

section "Clean branch"
git -C "$TMP/repo" checkout main >/dev/null
git -C "$TMP/repo" checkout -B feature/clean >/dev/null
commit_with_message "clean" $'ops: reviewed clean commit\n\nReviewed-by: Safe Reviewer <safe@example.test>'
KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main >"$TMP/clean_review_audit.txt" 2>&1
clean_rc=$?
[[ "$clean_rc" -eq 0 ]] && ok "all reviewed commits exit 0" || fail_t "expected exit 0, got $clean_rc"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
