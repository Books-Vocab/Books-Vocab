#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
pass=0
fail=0

ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*" >&2; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

section "Syntax"
for f in "$ROOT/ops/ui_token_lint.sh" "$ROOT/ops/injection_lint.sh" "$ROOT/ops/i18n_lint.sh"; do
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

section "Local Python helpers use uv"
f="$ROOT/ops/i18n_lint.sh"
name="$(basename "$f")"
bypass_hits="$(
  rg -n '(^[[:space:]]*python3[[:space:]-]|python3[[:space:]]+"\$|subprocess\.check_output\(\["python3")' "$f" \
    || true
)"
[[ -z "$bypass_hits" ]] \
  && ok "$name avoids local bare python3 helpers" \
  || fail_t "$name still has bare python3 helpers:\n$bypass_hits"
grep -q 'python find 3.13' "$f" \
  && ok "$name resolves Python 3.13 through uv" \
  || fail_t "$name missing uv-resolved Python 3.13 helpers"

section "All ops Python entrypoints avoid bare python3 shebang"
bad_shebangs="$(
  find "$ROOT/ops" -maxdepth 1 -type f -name '*.py' -print \
    | sort \
    | while IFS= read -r py; do
        first="$(head -1 "$py")"
        if [[ "$first" == '#!'*python3* ]]; then
          printf '%s\t%s\n' "$py" "$first"
        fi
      done
)"
if [[ -z "$bad_shebangs" ]]; then
  ok "no ops/*.py uses bare python3 shebang"
else
  fail_t "bare python3 shebangs found:\n$bad_shebangs"
fi

section "Executable Python entrypoints use uv shebang"
bad_exec="$(
  find "$ROOT/ops" -maxdepth 1 -type f -name '*.py' -perm +111 -print \
    | sort \
    | while IFS= read -r py; do
        first="$(head -1 "$py")"
        if [[ "$first" != '#!'*'uv run'* ]]; then
          printf '%s\t%s\n' "$py" "$first"
        fi
      done
)"
if [[ -z "$bad_exec" ]]; then
  ok "executable ops/*.py entrypoints use uv shebang"
else
  fail_t "executable ops/*.py without uv shebang:\n$bad_exec"
fi

section "Shebang Python tools are executable"
not_executable="$(
  find "$ROOT/ops" -maxdepth 1 -type f -name '*.py' -print \
    | sort \
    | while IFS= read -r py; do
        first="$(head -1 "$py")"
        if [[ "$first" == '#!'* && ! -x "$py" ]]; then
          printf '%s\t%s\n' "$py" "$first"
        fi
      done
)"
if [[ -z "$not_executable" ]]; then
  ok "all ops/*.py files with shebang are executable"
else
  fail_t "ops/*.py files with shebang but no executable bit:\n$not_executable"
fi

section "Smoke"
"$ROOT/ops/ui_token_lint.sh" --help >/dev/null \
  && ok "ui_token_lint --help" || fail_t "ui_token_lint --help"
"$ROOT/ops/injection_lint.sh" --help >/dev/null \
  && ok "injection_lint --help" || fail_t "injection_lint --help"
"$ROOT/ops/i18n_lint.sh" --report >/dev/null \
  && ok "i18n_lint --report" || fail_t "i18n_lint --report"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
