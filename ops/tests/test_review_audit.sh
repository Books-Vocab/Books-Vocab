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

set +e
KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main --machine-gate >"$TMP/machine_gate_audit.txt" 2>&1
machine_gate_rc=$?
set -e
[[ "$machine_gate_rc" -eq 2 ]] && ok "machine-gate still blocks invalid exemptions" \
  || fail_t "machine-gate changed invalid exemption handling (rc=$machine_gate_rc)"
grep -q '\[review\]\[ok\] .* ops: missing receipt' "$TMP/machine_gate_audit.txt" \
  && grep -q 'deferred to this fresh machine gate' "$TMP/machine_gate_audit.txt" \
  && ok "machine-gate records missing receipts as deferred, not as fake review" \
  || fail_t "machine-gate did not expose deferred receipt"

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

set +e
KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main --machine-gate --json >"$TMP/machine_gate_audit.json" 2>/dev/null
machine_gate_json_rc=$?
set -e
if [[ "$machine_gate_json_rc" -eq 2 ]] && jq -e \
  '.summary.total==4 and .summary.ok==3 and .summary.block==1
   and .summary.machineGateDeferred==1
   and any(.commits[]; .status=="machine-gate-deferred")' \
   "$TMP/machine_gate_audit.json" >/dev/null; then
  ok "machine-gate JSON exposes deferred count while preserving invalid blocks"
else
  cat "$TMP/machine_gate_audit.json" >&2
  fail_t "machine-gate JSON schema/counts invalid"
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
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: LEDGERONLY re-derived ledger

Review-Exempt: machine-repair
EOF
[[ "$(verdict_for LEDGERONLY)" == "ok" ]] \
  && ok "a repair commit confined to the ledger is exempt" \
  || fail_t "ledger-only repair was not exempt: $(grep -m1 LEDGERONLY "$MR/last.txt")"

# The generated view left version control (IMP-20260807-b9526c), so it remains
# outside the machine-repair whitelist. A commit that still touches that path is a
# hand-written change wearing a token that means "a machine derived this", which is
# the exact confusion the whitelist exists to prevent. Positive control for the
# narrowing: a real markdown doc is allowed below, but this generated path is not.
mr_case
printf '{"a":9}\n' >"$MR/repo/docs/runbook/backlog/E1.json"
printf 'view2\n' >"$MR/repo/docs/runbook/improvement_backlog.md"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: VIEWSTRAY ledger plus the ex-generated view

Review-Exempt: machine-repair
EOF
[[ "$(verdict_for VIEWSTRAY)" == "block" ]] \
  && ok "machine-repair no longer covers the ex-generated view" \
  || fail_t "the view is still being waved through: $(grep -m1 VIEWSTRAY "$MR/last.txt")"

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

# Reanchored markdown docs are valid machine-repair paths; unrelated source files
# remain a hard block. The generated view above is the explicit excluded sibling.
mr_case
printf 'not the ledger\n' >"$MR/repo/docs/runbook/system.md"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: SIBLINGDOC touches a runbook doc that is not the ledger

Review-Exempt: machine-repair
EOF
if [[ "$(verdict_for SIBLINGDOC)" == "ok" ]]; then
  ok "a reanchored markdown doc under docs/runbook/ is allowed"
else
  fail_t "reanchored markdown doc was blocked: $(grep -m1 SIBLINGDOC "$MR/last.txt")"
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

section "backlog-grooming is a CHECKED data-only exemption"
# Grooming changes ledger data, not executable code. It still needs two separate
# machine proofs in the surrounding workflow (`backlog.py validate` and
# `audit-criteria`); this receipt only says that a code reviewer is not required
# for a commit confined to the ledger files. The path check is intentionally
# independent from content checks so a mixed tooling change cannot hide here.
mr_case
printf '{"plan":"groomed"}\n' >"$MR/repo/docs/runbook/backlog/G1.json"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
docs: GROOMONLY groom the backlog ledger

Review-Exempt: backlog-grooming
EOF
[[ "$(verdict_for GROOMONLY)" == "ok" ]] \
  && ok "a pure backlog grooming commit is exempt" \
  || fail_t "pure grooming was not exempt: $(grep -m1 GROOMONLY "$MR/last.txt")"

mr_case
printf '{"plan":"groomed"}\n' >"$MR/repo/docs/runbook/backlog/G1.json"
mkdir -p "$MR/repo/ops"
printf 'echo tool\n' >"$MR/repo/ops/tool.sh"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
docs: GROOMMIXED ledger plus tooling

Review-Exempt: backlog-grooming
EOF
if [[ "$(verdict_for GROOMMIXED)" == "block" ]] && grep -q 'ops/tool.sh' "$MR/last.txt"; then
  ok "grooming plus tooling blocks and names the tooling path"
else
  fail_t "mixed grooming slipped past: $(grep -m1 GROOMMIXED "$MR/last.txt")"
fi

mr_case
printf 'not json\n' >"$MR/repo/docs/runbook/backlog/G1.md"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
docs: GROOMNONJSON ledger-adjacent prose

Review-Exempt: backlog-grooming
EOF
if [[ "$(verdict_for GROOMNONJSON)" == "block" ]] && grep -q 'docs/runbook/backlog/G1.md' "$MR/last.txt"; then
  ok "a non-JSON backlog path blocks"
else
  fail_t "non-JSON grooming path slipped past: $(grep -m1 GROOMNONJSON "$MR/last.txt")"
fi

mr_case
git -C "$MR/repo" commit -q --allow-empty -F - <<'EOF'
docs: GROOMEMPTY no ledger files

Review-Exempt: backlog-grooming
EOF
[[ "$(verdict_for GROOMEMPTY)" == "block" ]] \
  && ok "an empty grooming commit cannot claim the exemption" \
  || fail_t "empty grooming passed: $(grep -m1 GROOMEMPTY "$MR/last.txt")"

section "generated-snapshot is a checked artifact exemption"
# The allowlist is deliberately one exact tracked output today. A broad
# snapshot glob would turn hand-edited snapshots and unrelated ledger changes
# into review-free commits.
mr_case
mkdir -p "$MR/repo/ops"
printf 'baseline\n' >"$MR/repo/ops/injection_baseline.txt"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: GENERATEDONLY refresh the declared generated artifact

Review-Exempt: generated-snapshot
EOF
[[ "$(verdict_for GENERATEDONLY)" == "ok" ]] \
  && ok "a pure declared generated artifact is exempt" \
  || fail_t "declared generated artifact was not exempt: $(grep -m1 GENERATEDONLY "$MR/last.txt")"

mr_case
mkdir -p "$MR/repo/docs/runbook/backlog"
mkdir -p "$MR/repo/ops"
printf '{"plan":"groomed"}\n' >"$MR/repo/docs/runbook/backlog/G2.json"
printf 'baseline\n' >"$MR/repo/ops/injection_baseline.txt"
git -C "$MR/repo" add -A
git -C "$MR/repo" commit -q -F - <<'EOF'
ops: GENERATEDMIXED generated artifact plus ledger

Review-Exempt: generated-snapshot
EOF
if [[ "$(verdict_for GENERATEDMIXED)" == "block" ]] \
   && grep -q 'docs/runbook/backlog/G2.json' "$MR/last.txt"; then
  ok "generated-snapshot blocks and names an undeclared path"
else
  fail_t "undeclared generated path slipped past: $(grep -m1 GENERATEDMIXED "$MR/last.txt")"
fi

mr_case
git -C "$MR/repo" commit -q --allow-empty -F - <<'EOF'
ops: INVALIDTOKEN invalid exemption

Review-Exempt: not-a-token
EOF
if [[ "$(verdict_for INVALIDTOKEN)" == "block" ]] \
   && grep -q 'trivial-typo' "$MR/last.txt" \
   && grep -q 'machine-repair' "$MR/last.txt"; then
  ok "invalid exemption names the allowed token set"
else
  fail_t "invalid exemption omitted allowed tokens: $(grep -m1 INVALIDTOKEN "$MR/last.txt")"
fi

rm -rf "$MR"

section "single-line-small-file exemption is machine-checked (IMP-0065)"

# One branch per case, one commit each, so the earlier JSON count assertions stay
# scoped to their original fixture.
sl_case() {  # $1=branch $2=file $3=content $4=commit message
  git -C "$TMP/repo" checkout -q main
  git -C "$TMP/repo" checkout -q -B "$1"
  printf '%s' "$3" >"$TMP/repo/$2"
  git -C "$TMP/repo" add "$2"
  git -C "$TMP/repo" commit -q -F - <<EOF
$4
EOF
  set +e
  KG_REVIEW_AUDIT_ROOT="$TMP/repo" "$AUDIT" --base main --json >"$TMP/sl_$1.json" 2>/dev/null
  sl_rc=$?
  set -e
}

sl_case slplain plain.txt $'a plain one line note\n' \
  $'docs: plain one-liner\n\nReview-Exempt: single-line-small-file'
if [[ "$sl_rc" -eq 0 ]] && jq -e '.summary.exempt==1 and .summary.block==0' "$TMP/sl_slplain.json" >/dev/null; then
  ok "single-line exemption survives a genuine one-liner"
else
  fail_t "single-line exemption survives a genuine one-liner (rc=$sl_rc)"
fi

sl_case slnorm normative.txt $'這條規則:所有 agent 必須送審\n' \
  $'docs: one line that legislates\n\nReview-Exempt: single-line-small-file'
if [[ "$sl_rc" -eq 2 ]] && jq -e '.summary.invalidExemption==1 and .summary.block==1' "$TMP/sl_slnorm.json" >/dev/null; then
  ok "single-line exemption blocked by normative wording"
else
  fail_t "single-line exemption blocked by normative wording (rc=$sl_rc)"
fi

sl_case slmulti twolines.txt $'line one\nline two\n' \
  $'docs: two lines\n\nReview-Exempt: single-line-small-file'
if [[ "$sl_rc" -eq 2 ]] && jq -e '.summary.invalidExemption==1' "$TMP/sl_slmulti.json" >/dev/null; then
  ok "single-line exemption blocked by a two-line change"
else
  fail_t "single-line exemption blocked by a two-line change (rc=$sl_rc)"
fi

# The other semantic exemptions stay trailer-only on purpose: multi-line and
# normative still exempt. Without this, the change would silently narrow all five.
sl_case sltypo typo.txt $'規則一 必須\n規則二 禁止\n' \
  $'docs: fix typo\n\nReview-Exempt: trivial-typo'
if [[ "$sl_rc" -eq 0 ]] && jq -e '.summary.exempt==1' "$TMP/sl_sltypo.json" >/dev/null; then
  ok "trivial-typo exemption still trailer-only"
else
  fail_t "trivial-typo exemption still trailer-only (rc=$sl_rc)"
fi

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
