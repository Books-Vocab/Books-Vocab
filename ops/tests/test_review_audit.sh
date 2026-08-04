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
# set +e is load-bearing under `set -euo pipefail`: without it a non-zero rc aborts the
# whole file here, and every section BELOW this line silently never runs.
set +e
KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main >"$TMP/clean_review_audit.txt" 2>&1
clean_rc=$?
set -e
[[ "$clean_rc" -eq 0 ]] && ok "all reviewed commits exit 0" || fail_t "expected exit 0, got $clean_rc"

section "Audited root follows the caller (IMP-0049)"
# Without the env override this used to cd to the SCRIPT's own repo, so an invocation
# from anywhere else silently audited KG's own history. That is not theoretical: the
# review-receipts red proof in ops/tests/test_gate_can_fail.sh was written as
# `( cd "$TMP/repo" && review_audit.sh )` and therefore had a verdict that depended on
# whether KG's own recent commits carried trailers. It went green — i.e. the proof
# stopped proving — the moment they all did.
set +e
( cd "$TMP/repo" && "$AUDIT" --base main ) >"$TMP/cwd_audit.txt" 2>"$TMP/cwd_audit.err"
cwd_rc=$?
set -e
expect_root="$(cd "$TMP/repo" && pwd -P)"
if grep -qF "auditing $expect_root" "$TMP/cwd_audit.err"; then
  ok "stderr names the repo actually audited"
else
  fail_t "did not name $expect_root as the audited root — an invisible root is what made the wrong one survive"
  head -3 "$TMP/cwd_audit.err" | sed 's/^/      /' >&2
fi
grep -qF "ops: reviewed clean commit" "$TMP/cwd_audit.txt" \
  && ok "audits the caller's repo" || fail_t "audited some other repo than the caller's cwd"
# exit 0 alone is vacuous here: pointed at the WRONG repo, `main..HEAD` is usually
# empty, and auditing zero commits also exits 0. Bind the green to the count, so it
# can only be satisfied by having actually audited the fixture's one commit.
set +e
( cd "$TMP/repo" && "$AUDIT" --base main --json ) >"$TMP/cwd_audit.json" 2>/dev/null
cwd_json_rc=$?
set -e
if [[ "$cwd_rc" -eq 0 ]] && jq -e '.summary.total==1 and .summary.reviewed==1' \
     "$TMP/cwd_audit.json" >/dev/null 2>&1; then
  ok "cwd-rooted run exits 0 having audited exactly the fixture's commit"
else
  fail_t "expected exit 0 over 1 reviewed commit; got rc=$cwd_rc json_rc=$cwd_json_rc $(tr -d '\n' <"$TMP/cwd_audit.json" | cut -c1-120)"
fi

# The env override must still win — the gate and the fixtures above depend on it.
set +e
KG_REVIEW_AUDIT_ROOT="$TMP/repo" bash -c "cd '$WORKSPACE' && '$AUDIT' --base main" \
  >"$TMP/env_audit.txt" 2>"$TMP/env_audit.err"
env_rc=$?
set -e
grep -qF "auditing $expect_root" "$TMP/env_audit.err" \
  && ok "KG_REVIEW_AUDIT_ROOT still overrides the caller's cwd" \
  || fail_t "env override lost to cwd"
[[ "$env_rc" -eq 0 ]] && ok "override keeps the fixture verdict" || fail_t "expected exit 0, got $env_rc"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
