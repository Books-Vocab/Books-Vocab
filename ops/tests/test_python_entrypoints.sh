#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
pass=0
fail=0

ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

section "Syntax"
for f in "$ROOT/ops/ui_token_lint.sh" "$ROOT/ops/injection_lint.sh"; do
  bash -n "$f" && ok "$(basename "$f") syntax" || fail_t "$(basename "$f") syntax"
done

section "Local Python wrappers use uv"
for f in "$ROOT/ops/ui_token_lint.sh" "$ROOT/ops/injection_lint.sh"; do
  name="$(basename "$f")"
  if rg -n 'exec python3|python3[[:space:]]+ops/' "$f" >/dev/null; then
    fail_t "$name still invokes bare python3"
  else
    ok "$name avoids bare python3"
  fi
  grep -q 'run --python 3.13 python' "$f" \
    && ok "$name uses uv Python 3.13" \
    || fail_t "$name missing uv Python 3.13 entrypoint"
done

section "Smoke"
"$ROOT/ops/ui_token_lint.sh" --help >/dev/null \
  && ok "ui_token_lint --help" || fail_t "ui_token_lint --help"
"$ROOT/ops/injection_lint.sh" --help >/dev/null \
  && ok "injection_lint --help" || fail_t "injection_lint --help"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
