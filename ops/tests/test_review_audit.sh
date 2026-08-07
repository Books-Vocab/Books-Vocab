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

section "machine-repair is a CHECKED exemption"
# Every other token is a claim about the nature of a diff that this script cannot
# verify. `machine-repair` is emitted by a program (cutover's post-landing ledger
# repair), so it is held to a path constraint — otherwise adding a token for a
# machine to use is just a wider hole in the review gate.
#
# Each case gets a FRESH branch off main, and its verdict is read from that case's
# OWN [review] line. The first version reused one branch, so an early stray-file
# commit stayed in `main..HEAD` and returned exit 2 by itself: three assertions
# "passed" while testing nothing, and a mutation that waved empty commits through
# survived 21/21.
MR="$(mktemp -d)"
git init "$MR/repo" >/dev/null
git -C "$MR/repo" config user.name t
git -C "$MR/repo" config user.email t@t
mkdir -p "$MR/repo/docs/runbook/backlog"
printf 'root\n' >"$MR/repo/root.txt"
printf 'view\n' >"$MR/repo/docs/runbook/improvement_backlog.md"
printf '{}\n' >"$MR/repo/docs/runbook/backlog/SEED.json"
git -C "$MR/repo" add -A && git -C "$MR/repo" commit -qm root
git -C "$MR/repo" branch -M main

verdict_for() {
  local subject="$1"
  KG_REVIEW_AUDIT_ROOT="$MR/repo" "$AUDIT" --base main >"$MR/last.txt" 2>/dev/null || true
  if grep -q "\[review\]\[block\].*$subject" "$MR/last.txt"; then
    echo block
  elif grep -q "\[review\]\[ok\].*$subject" "$MR/last.txt"; then
    echo ok
  else
    echo missing
  fi
}

mr_case() { git -C "$MR/repo" checkout -q -B case main; }

mr_case
printf '{"a":1}\n' >"$MR/repo/docs/runbook/backlog/E1.json"
printf 'view2\n' >"$MR/repo/docs/runbook/improvement_backlog.md"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: LEDGERONLY re-derived ledger

Review-Exempt: machine-repair
EOF
[[ "$(verdict_for LEDGERONLY)" == "ok" ]] \
  && ok "a repair commit confined to the ledger is exempt" \
  || fail_t "ledger-only repair was not exempt: $(grep -m1 LEDGERONLY "$MR/last.txt")"

mr_case
printf 'sneaked in\n' >"$MR/repo/src.py"
printf '{"a":2}\n' >"$MR/repo/docs/runbook/backlog/E1.json"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: STRAYFILE ledger and something else

Review-Exempt: machine-repair
EOF
if [[ "$(verdict_for STRAYFILE)" == "block" ]] && grep -q 'src.py' "$MR/last.txt"; then
  ok "the same token over an unrelated file blocks, and NAMES the file"
else
  fail_t "stray file not blocked/named: $(grep -m1 STRAYFILE "$MR/last.txt")"
fi

# The SHAPE of the pattern, not just its existence: loosening it to `^docs/runbook/`
# left the suite green, because the only stray fixture was a `src.py` that every
# pattern rejects. A sibling runbook doc is the discriminator.
mr_case
printf 'not the ledger\n' >"$MR/repo/docs/runbook/system.md"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: SIBLINGDOC touches a runbook doc that is not the ledger

Review-Exempt: machine-repair
EOF
if [[ "$(verdict_for SIBLINGDOC)" == "block" ]] && grep -q 'docs/runbook/system.md' "$MR/last.txt"; then
  ok "a non-ledger file under docs/runbook/ still blocks"
else
  fail_t "sibling runbook doc slipped past: $(grep -m1 SIBLINGDOC "$MR/last.txt")"
fi

# Three shapes that produce an EMPTY file list — "could not look" dressed up as
# "nothing to object to". Each was measured passing before the fix.
mr_case
git -C "$MR/repo" commit -q --allow-empty -F - <<'EOF'
ops: EMPTYCOMMIT nothing at all

Review-Exempt: machine-repair
EOF
[[ "$(verdict_for EMPTYCOMMIT)" == "block" ]] \
  && ok "an empty commit cannot claim machine-repair" \
  || fail_t "empty commit passed: $(grep -m1 EMPTYCOMMIT "$MR/last.txt")"

mr_case
printf 'secret\n' >"$MR/repo/secret.txt"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
chore: SETUPSECRET add a file to move later

Review-Exempt: trivial-typo
EOF
git -C "$MR/repo" mv secret.txt docs/runbook/backlog/B.json
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: RENAMEIN move an arbitrary file into the ledger directory

Review-Exempt: machine-repair
EOF
if [[ "$(verdict_for RENAMEIN)" == "block" ]] && grep -q 'secret.txt' "$MR/last.txt"; then
  ok "a rename into the ledger directory is seen for what it moved"
else
  fail_t "rename slipped past: $(grep -m1 RENAMEIN "$MR/last.txt")"
fi

mr_case
git -C "$MR/repo" checkout -q -B side main
printf 'side\n' >"$MR/repo/side.txt"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
chore: SETUPSIDE side work

Review-Exempt: trivial-typo
EOF
git -C "$MR/repo" checkout -q case
GIT_EDITOR=true git -C "$MR/repo" merge -q --no-ff side -m "ops: EVILMERGE

Review-Exempt: machine-repair" >/dev/null 2>&1
if [[ "$(verdict_for EVILMERGE)" == "block" ]] && grep -q 'side.txt' "$MR/last.txt"; then
  ok "a merge commit's contents are actually inspected"
else
  fail_t "merge slipped past: $(grep -m1 EVILMERGE "$MR/last.txt")"
fi

rm -rf "$MR"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
