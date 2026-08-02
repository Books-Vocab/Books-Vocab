#!/usr/bin/env bash
# Offline regression tests for ops/injection_lint.sh sunset enforcement.
#
# 為什麼存在：baseline 的 `# sunset:` 原本只在過期時印一行 WARN 到 stderr，
# 然後照樣 `return 0`。也就是「這批債務的寬限期到了」這個事實**不會改變任何
# gate 的顏色**。2026-08-03 實測：sunset 已過期 21 天，CI / cutover / 本機
# 全部照樣綠，沒有任何人知道。
#
# 過期必須是紅的，否則 sunset 只是一句沒有後果的註解。

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"
LINT="$WORKSPACE/ops/injection_lint.sh"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# A baseline holding exactly today's findings, so nothing reads as a regression
# and the only variable under test is the sunset header.
CURRENT_FINDINGS="$TMP/current.txt"
"$LINT" --report 2>/dev/null | grep -E '^ios/.*\.swift' >"$CURRENT_FINDINGS" || true

write_baseline() {  # $1 = destination, $2 = sunset line (empty = omit header)
  local dest="$1" sunset_line="$2"
  {
    echo "# injection_lint baseline — synthesized by test_injection_lint.sh"
    [[ -n "$sunset_line" ]] && echo "$sunset_line"
    echo ""
    cat "$CURRENT_FINDINGS"
  } >"$dest"
}

run_check() {  # $1 = baseline path -> echoes exit code
  local rc=0
  KG_INJECTION_BASELINE="$1" "$LINT" --baseline-check >/dev/null 2>&1 || rc=$?
  echo "$rc"
}

section "baseline path is overridable (siblings already are)"
# Discriminating probe: an EMPTY baseline must read as a regression. A passing
# result here would mean the override was ignored and the real (passing)
# baseline answered instead — the probe has to be able to fail for the right
# reason, or every later assertion in this file is vacuous.
write_baseline "$TMP/empty.txt" "# sunset: 2099-01-01"
: >"$TMP/empty-findings.txt"
{ echo "# synthesized"; echo "# sunset: 2099-01-01"; } >"$TMP/empty.txt"
rc="$(run_check "$TMP/empty.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "KG_INJECTION_BASELINE honoured (empty baseline reads as regression, exit $rc)"
else
  fail_t "KG_INJECTION_BASELINE ignored — an empty baseline still exits 0, so the real baseline answered; injection_lint is the only lint of its family without a baseline override and its sunset behaviour cannot be tested"
fi

write_baseline "$TMP/future.txt" "# sunset: 2099-01-01"
rc="$(run_check "$TMP/future.txt")"
if [[ "$rc" -eq 0 ]]; then
  ok "a synthesized baseline holding today's findings with a future sunset passes"
else
  fail_t "synthesized current-findings baseline exits $rc — expected 0"
fi

section "an expired sunset must change the verdict, not just print a warning"
write_baseline "$TMP/expired.txt" "# sunset: 2000-01-01"
rc="$(run_check "$TMP/expired.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "expired sunset exits $rc"
else
  fail_t "expired sunset still exits 0 — the grace period has no teeth"
fi

section "a missing sunset header is not an unlimited grace period"
write_baseline "$TMP/nosunset.txt" ""
rc="$(run_check "$TMP/nosunset.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "baseline without a sunset exits $rc"
else
  fail_t "baseline with no sunset header exits 0 — debt with no expiry date is permanent by default"
fi

section "a malformed sunset must not silently disable the check"
write_baseline "$TMP/garbage.txt" "# sunset: not-a-date"
rc="$(run_check "$TMP/garbage.txt")"
if [[ "$rc" -ne 0 ]]; then
  ok "malformed sunset exits $rc"
else
  fail_t "malformed sunset exits 0 — a typo in the date silently removes the expiry"
fi

section "the checked-in baseline's sunset is still in the future"
sunset="$(sed -n 's/^# sunset: *//p' ops/injection_baseline.txt | head -1)"
if [[ -z "$sunset" ]]; then
  fail_t "ops/injection_baseline.txt has no sunset header"
elif [[ "$sunset" > "$(date -u +%F)" ]]; then
  ok "checked-in sunset $sunset is in the future"
else
  fail_t "checked-in sunset $sunset has passed — resolve the outstanding items or make an explicit, dated decision to extend"
fi

echo ""
echo "injection-lint: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
