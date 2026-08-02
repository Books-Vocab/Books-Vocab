#!/usr/bin/env bash
# Offline regression tests for lint baseline health.
#
# Division of labour — the two halves pin the watermark to reality:
#   <lint> --baseline-check   擋「債務增加」 current ⊄ baseline
#   this test                 擋「門檻鬆弛」 baseline ⊄ current
#
# 沒有下半，baseline 會變成化石：債務被掃乾淨之後水位線沒跟著降，
# 於是那道 lint 安靜地允許 N 個免費違規，而且每次跑都回綠。
# (2026-08-03 實例：i18n baseline 停在 51，實際 findings 是 0。)
#
# 判準必須是**集合包含**而非計數。`|baseline| <= |current|` 在
# `new >= stale` 時恆真，會放行 stale key —— 而 key 是 line-number-free 的
# (`<relpath>::<pattern>::<snippet>`)，所以一個 stale key 是**永久**的再犯額度：
# 刪掉某個 magic number、日後在同檔重新加回同一個字面，--baseline-check 永遠放行。
# 取得「當前 keys 的 baseline 形式」靠各 lint 的 KG_*_BASELINE override 寫到 temp。

set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$WORKSPACE"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

keys_of() { grep -vE '^[[:space:]]*(#|$)' "$1" 2>/dev/null | sort -u; }

# Emit today's findings in baseline key form, without touching the real file.
emit_current_keys() {  # $1 = lint entrypoint, $2 = env var name, $3 = out path
  env "$2=$3" "./ops/$1" --baseline >/dev/null 2>&1 || return 1
}

assert_subset() {  # $1 = label, $2 = real baseline, $3 = current-keys file, $4 = regen hint
  local label="$1" real="$2" cur="$3" hint="$4" stale
  stale="$(comm -23 <(keys_of "$real") <(keys_of "$cur") || true)"
  if [[ -z "$stale" ]]; then
    ok "$label — baseline ⊆ current ($(keys_of "$real" | wc -l | tr -d ' ') key(s), no stale)"
  else
    local n; n="$(printf '%s\n' "$stale" | wc -l | tr -d ' ')"
    fail_t "$label — $n stale baseline key(s) = $n permanent re-offence slot(s). Ratchet: $hint"
    printf '%s\n' "$stale" | head -3 | sed 's/^/      /'
  fi
}

# ---------------------------------------------------------------- key-set lints
declare -a SET_LINTS=(
  "ui_token_lint.sh|ops/ui_token_baseline.txt|KG_UI_TOKEN_BASELINE"
  "plain_deadzone_lint.sh|ops/plain_deadzone_baseline.txt|KG_DEADZONE_BASELINE"
  "injection_lint.sh|ops/injection_baseline.txt|KG_INJECTION_BASELINE"
)

section "key-set baselines must be a subset of today's findings"
for spec in "${SET_LINTS[@]}"; do
  IFS='|' read -r entry real envvar <<<"$spec"
  cur="$TMP/$(basename "$real")"
  if ! emit_current_keys "$entry" "$envvar" "$cur"; then
    fail_t "$entry — could not emit current keys via $envvar; the probe itself is broken"
    continue
  fi
  assert_subset "${entry%.sh}" "$real" "$cur" "bash ops/$entry --baseline"
done

section "the subset check can actually fail (self-test)"
# A detector for false greens must prove it fires, or it is one itself.
printf '# self-test\n# sunset: 2099-01-01\n\nfake/Stale.swift::padding::.padding(9)\n' >"$TMP/synthetic-baseline.txt"
: >"$TMP/synthetic-current.txt"
if [[ -n "$(comm -23 <(keys_of "$TMP/synthetic-baseline.txt") <(keys_of "$TMP/synthetic-current.txt") || true)" ]]; then
  ok "a baseline key absent from current findings is detected as stale"
else
  fail_t "the stale-key predicate does not fire on a known-stale fixture — this file cannot detect anything"
fi

# ------------------------------------------------------------- count-based lint
section "i18n_lint — both watermarks pinned"
i18n_findings_base="$(sed -n 's/^findings=\([0-9][0-9]*\)$/\1/p' ops/i18n_baseline.txt | head -1 || true)"
i18n_calls_base="$(sed -n 's/^localized_calls=\([0-9][0-9]*\)$/\1/p' ops/i18n_baseline.txt | head -1 || true)"
if [[ -z "$i18n_findings_base" ]]; then
  if grep -qE '^[0-9]+$' ops/i18n_baseline.txt; then
    fail_t "i18n baseline uses the legacy bare-integer shape — regenerate with ops/i18n_lint.sh --baseline so the localized_calls guard is armed"
  else
    fail_t "i18n baseline has no findings= line; the probe cannot read a watermark"
  fi
fi
report="$(./ops/i18n_lint.sh --report 2>&1 || true)"
i18n_findings_cur="$(sed -n 's/.*total: \([0-9][0-9]*\).*/\1/p' <<<"$report" | head -1 || true)"
i18n_calls_cur="$(sed -n 's/.*localized_calls=\([0-9][0-9]*\).*/\1/p' <<<"$report" | head -1 || true)"

assert_count() {  # $1 = label, $2 = baseline, $3 = current
  if [[ -z "$2" || -z "$3" ]]; then
    fail_t "$1 — could not read baseline ($2) or current ($3); the probe itself is broken"
  elif [[ "$2" -le "$3" ]]; then
    ok "$1 baseline=$2 current=$3 — no slack"
  else
    fail_t "$1 baseline=$2 exceeds current=$3 — $(( $2 - $3 )) free slot(s). Ratchet: bash ops/i18n_lint.sh --baseline"
  fi
}
assert_count "i18n findings" "$i18n_findings_base" "$i18n_findings_cur"
# localized_calls is ratchet-down debt too (docs/sop/i18n_lint.md §掃描範圍 5:
# 「只能持平或下降」). Leaving it unpinned recreates the `51` fossil in a new field.
assert_count "i18n localized_calls" "$i18n_calls_base" "$i18n_calls_cur"

# ------------------------------------------------------------------- coverage
section "every checked-in baseline is covered by this test"
for f in ops/*_baseline.txt; do
  case "$f" in
    ops/i18n_baseline.txt) continue ;;
  esac
  covered=0
  for spec in "${SET_LINTS[@]}"; do
    IFS='|' read -r _ real _ <<<"$spec"
    [[ "$real" == "$f" ]] && covered=1
  done
  if [[ "$covered" -eq 1 ]]; then
    ok "$f is covered"
  else
    fail_t "$f has no coverage here — a new lint baseline can rot unnoticed; add it to SET_LINTS"
  fi
done

echo ""
echo "lint-baselines: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
