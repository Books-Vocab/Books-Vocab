#!/usr/bin/env bash
# Regression tests for the bounded review-cycle state machine.

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
TOOL="$WORKSPACE/ops/review_cycle.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STATE="$TMP/review-cycles.json"
EVIDENCE="$TMP/review.txt"
printf 'review evidence: measured diff and targeted tests\n' >"$EVIDENCE"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

run_json() {
  run_state_json "$STATE" "$@"
}

run_state_json() {
  local state="$1"
  shift
  uv run --no-project --python 3.13 "$TOOL" --state "$state" --json "$@" 2>/dev/null
}

expect_record_refused() {
  local scope="$1" sha="$2" label="$3" reason="$4"
  set +e
  run_json record --scope "$scope" --commit-sha "$sha" --outcome pass \
    --reviewer "late reviewer" --evidence-file "$EVIDENCE" >"$TMP/refused.json"
  local rc=$?
  set -e
  if [[ "$rc" -eq 2 ]] && jq -e --arg reason "$reason" \
      '.ok==false and (.error | contains($reason))' \
      "$TMP/refused.json" >/dev/null; then
    ok "$label cannot append after a terminal decision"
  else
    fail_t "$label unexpectedly accepted a terminal append (rc=$rc)"
    cat "$TMP/refused.json" >&2
  fi
}

section "Two blocker-bearing passes stop at adjudication"
SCOPE="ops/review-cycle"
SHA="0123456789abcdef0123456789abcdef01234567"
run_json start --scope "$SCOPE" --commit-sha "$SHA" >"$TMP/start1.json"
jq -e '.action=="review" and .allowed==true and .attempt==1' "$TMP/start1.json" >/dev/null \
  && ok "first review is allowed" || fail_t "first review was not allowed"
run_json start --scope "$SCOPE" --commit-sha "$SHA" >"$TMP/start-duplicate.json"
jq -e '.action=="review_in_progress" and .allowed==false and .attempt==1' "$TMP/start-duplicate.json" >/dev/null \
  && ok "duplicate start cannot reserve the same attempt" || fail_t "duplicate start reserved another attempt"
run_json record --scope "$SCOPE" --commit-sha "$SHA" --outcome findings \
  --reviewer "reviewer one" --evidence-file "$EVIDENCE" \
  --block-count 1 --nit-count 2 --tooling-debt-count 1 >"$TMP/record1.json"
jq -e '.action=="fix_then_review_once" and .status=="review_again" and .finding_totals.block==1 and .finding_totals.nit==2 and .finding_totals.tooling_debt==1' \
  "$TMP/record1.json" >/dev/null \
  && ok "first BLOCK pass routes to one final review" || fail_t "first BLOCK pass routing is wrong"
run_json start --scope "$SCOPE" --commit-sha "$SHA" >"$TMP/start2.json"
jq -e '.action=="review" and .attempt==2' "$TMP/start2.json" >/dev/null \
  && ok "second review is the final automatic attempt" || fail_t "second review was not allowed"
run_json record --scope "$SCOPE" --commit-sha "$SHA" --outcome findings \
  --reviewer "reviewer two" --evidence-file "$EVIDENCE" \
  --block-count 1 --nit-count 1 --tooling-debt-count 2 >"$TMP/record2.json"
jq -e '.action=="adjudication_required" and .allowed==null and .finding_totals.block==2 and .finding_totals.nit==3 and .finding_totals.tooling_debt==3' \
  "$TMP/record2.json" >/dev/null \
  && ok "second BLOCK pass requires adjudication and exposes buckets" \
  || fail_t "second BLOCK pass did not expose adjudication/buckets"
run_json start --scope "$SCOPE" --commit-sha "$SHA" >"$TMP/start3.json"
jq -e '.action=="adjudication_required" and .allowed==false' "$TMP/start3.json" >/dev/null \
  && ok "third automatic review is refused" || fail_t "third automatic review was allowed"
expect_record_refused "$SCOPE" "$SHA" "adjudication-required cycle" "review attempt limit"
run_json adjudicate --scope "$SCOPE" --commit-sha "$SHA" --decision accept \
  --reason "second pass confirmed the remaining BLOCK is outside this commit scope" >"$TMP/adjudicate.json"
jq -e '.action=="adjudicated" and .status=="adjudicated"' "$TMP/adjudicate.json" >/dev/null \
  && ok "adjudication closes the cycle" || fail_t "adjudication did not close the cycle"

section "Pass and follow-up-only outcomes are terminal"
PASS_SCOPE="ops/review-cycle-pass"
PASS_SHA="abcdef0123456789abcdef0123456789abcdef01"
run_json start --scope "$PASS_SCOPE" --commit-sha "$PASS_SHA" >/dev/null
run_json record --scope "$PASS_SCOPE" --commit-sha "$PASS_SHA" --outcome pass \
  --reviewer "reviewer pass" --evidence-file "$EVIDENCE" >"$TMP/pass.json"
jq -e '.action=="complete" and .status=="passed" and .finding_totals == {block:0,nit:0,tooling_debt:0}' \
  "$TMP/pass.json" >/dev/null \
  && ok "PASS closes without a second review" || fail_t "PASS did not close cleanly"
expect_record_refused "$PASS_SCOPE" "$PASS_SHA" "passed cycle" "terminal"

FOLLOW_SCOPE="ops/review-cycle-followups"
FOLLOW_SHA="fedcba9876543210fedcba9876543210fedcba98"
run_json start --scope "$FOLLOW_SCOPE" --commit-sha "$FOLLOW_SHA" >/dev/null
run_json record --scope "$FOLLOW_SCOPE" --commit-sha "$FOLLOW_SHA" --outcome findings \
  --reviewer "reviewer followups" --evidence-file "$EVIDENCE" \
  --nit-count 1 --tooling-debt-count 2 >"$TMP/followups.json"
jq -e '.action=="complete_with_followups" and .status=="pass_with_followups" and .finding_totals.nit==1 and .finding_totals.tooling_debt==2' "$TMP/followups.json" >/dev/null \
  && ok "NIT/TOOLING-DEBT-only result closes with named follow-ups" \
  || fail_t "follow-up-only result did not close cleanly"
expect_record_refused "$FOLLOW_SCOPE" "$FOLLOW_SHA" "follow-up-only cycle" "terminal"

section "Abandoned reservations have an explicit recovery path"
REC_SCOPE="ops/review-cycle-recovery"
REC_SHA="2222222222222222222222222222222222222222"
run_json start --scope "$REC_SCOPE" --commit-sha "$REC_SHA" >/dev/null
run_json cancel --scope "$REC_SCOPE" --commit-sha "$REC_SHA" \
  --reason "reviewer process exited before producing evidence" >"$TMP/cancel.json"
jq -e '.action=="review_cancelled" and .status=="ready" and .active_attempt==null and (.cancellations|length)==1' "$TMP/cancel.json" >/dev/null \
  && ok "abandoned reservation can be cancelled with a reason" || fail_t "abandoned reservation had no recovery path"
run_json start --scope "$REC_SCOPE" --commit-sha "$REC_SHA" >"$TMP/recovery-start.json"
jq -e '.action=="review" and .attempt==1' "$TMP/recovery-start.json" >/dev/null \
  && ok "cancellation releases the same review slot" || fail_t "cancellation consumed or duplicated the review slot"
run_json record --scope "$REC_SCOPE" --commit-sha "$REC_SHA" --outcome pass \
  --reviewer "recovery reviewer" --evidence-file "$EVIDENCE" >"$TMP/recovery-record.json"
jq -e '.action=="complete" and .status=="passed"' "$TMP/recovery-record.json" >/dev/null \
  && ok "recovered reservation can complete normally" || fail_t "recovered reservation could not complete"

section "Invalid state transitions refuse"
UNKNOWN_SCOPE="ops/review-cycle-unknown"
UNKNOWN_SHA="1111111111111111111111111111111111111111"
set +e
run_json record --scope "$UNKNOWN_SCOPE" --commit-sha "$UNKNOWN_SHA" --outcome pass \
  --reviewer "nobody" --evidence-file "$EVIDENCE" >"$TMP/unknown.json"
unknown_rc=$?
set -e
if [[ "$unknown_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("start"))' "$TMP/unknown.json" >/dev/null; then
  ok "record before start is refused"
else
  fail_t "record before start was not refused (rc=$unknown_rc)"
fi

section "Identity and input failures are structured"
UPPER="$(printf '%s' "$SHA" | tr '[:lower:]' '[:upper:]')"
run_json start --scope "$SCOPE" --commit-sha "$UPPER" >"$TMP/uppercase.json"
jq -e '.action=="no_review_needed" and .commit_sha=="0123456789abcdef0123456789abcdef01234567"' "$TMP/uppercase.json" >/dev/null \
  && ok "uppercase SHA is canonicalized to the existing cycle" || fail_t "uppercase SHA created an alias cycle"
set +e
run_json start --scope "short-sha" --commit-sha "0123456" >"$TMP/short-sha.json"
short_rc=$?
set -e
if [[ "$short_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("full 40- or 64"))' "$TMP/short-sha.json" >/dev/null; then
  ok "short SHA is refused instead of becoming an alias"
else
  fail_t "short SHA was not refused (rc=$short_rc)"
fi
set +e
run_json start --scope "$SCOPE" >"$TMP/arg-error.json"
arg_rc=$?
set -e
if [[ "$arg_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("commit-sha"))' "$TMP/arg-error.json" >/dev/null; then
  ok "argument errors use the JSON refusal contract"
else
  fail_t "argument error was not structured (rc=$arg_rc)"
fi

BAD_STATE="$TMP/bad-state.json"
printf '{"schema":"kg.review_cycle.v1","cycles":[1]}\n' >"$BAD_STATE"
set +e
run_state_json "$BAD_STATE" status >"$TMP/bad-state-result.json"
bad_state_rc=$?
set -e
if [[ "$bad_state_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("expected object"))' "$TMP/bad-state-result.json" >/dev/null; then
  ok "malformed state is rejected structurally"
else
  fail_t "malformed state escaped as a crash (rc=$bad_state_rc)"
fi

UPPER_STATE="$TMP/uppercase-state.json"
printf '{"schema":"kg.review_cycle.v1","cycles":[{"scope":"ops/state","commit_sha":"ABCDEF0123456789ABCDEF0123456789ABCDEF01","attempts":[],"status":"ready"}]}\n' >"$UPPER_STATE"
set +e
run_state_json "$UPPER_STATE" status >"$TMP/uppercase-state-result.json"
upper_state_rc=$?
set -e
if [[ "$upper_state_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("lowercase canonical"))' "$TMP/uppercase-state-result.json" >/dev/null; then
  ok "persisted non-canonical SHA is rejected"
else
  fail_t "persisted uppercase SHA bypassed canonical state (rc=$upper_state_rc)"
fi

BAD_ACTIVE="$TMP/bad-active.json"
printf '{"schema":"kg.review_cycle.v1","cycles":[{"scope":"ops/state","commit_sha":"abcdef0123456789abcdef0123456789abcdef01","attempts":[],"status":"reviewing","active_attempt":{"number":99}}]}\n' >"$BAD_ACTIVE"
set +e
run_state_json "$BAD_ACTIVE" status >"$TMP/bad-active-result.json"
bad_active_rc=$?
set -e
if [[ "$bad_active_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("active attempt number/status"))' "$TMP/bad-active-result.json" >/dev/null; then
  ok "inconsistent active attempt number is rejected"
else
  fail_t "inconsistent active attempt bypassed the bound (rc=$bad_active_rc)"
fi

UTF_STATE="$TMP/utf-state.json"
BAD_EVIDENCE="$TMP/bad-evidence.txt"
printf '\377' >"$BAD_EVIDENCE"
run_state_json "$UTF_STATE" start --scope "ops/review-cycle-utf8" --commit-sha "$PASS_SHA" >/dev/null
set +e
run_state_json "$UTF_STATE" record --scope "ops/review-cycle-utf8" --commit-sha "$PASS_SHA" \
  --outcome pass --reviewer "bad evidence" --evidence-file "$BAD_EVIDENCE" >"$TMP/utf-error.json"
utf_rc=$?
set -e
if [[ "$utf_rc" -eq 2 ]] && jq -e '.ok==false and (.error | contains("cannot read evidence"))' "$TMP/utf-error.json" >/dev/null; then
  ok "invalid UTF-8 evidence is a structured refusal"
else
  fail_t "invalid UTF-8 evidence escaped as a crash (rc=$utf_rc)"
fi

echo ""
echo "passed: $pass failed: $fail"
[[ "$fail" -eq 0 ]]
