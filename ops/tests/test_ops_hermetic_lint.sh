#!/usr/bin/env bash
# test_ops_hermetic_lint.sh — no ops test may be able to reach production.
#
# Why this exists: 2026-10-09 an ops test ran `devops_kg_safe.sh run <cmd>` with no
# stub base, the guard let the command through, and the real devops.sh deleted the live
# data dir on felix over ssh (docs/runbook/incidents/2026-10-09-kg-data-deleted-by-test.md).
#
# THE RULE (deliberately simple, so it cannot be argued around):
#
#   R1  A test file that mentions devops.sh or devops_kg_safe.sh on a NON-comment line
#       must be hermetic on its own, i.e. satisfy ONE of (a) or (c):
#         (a) call `hermetic_ops_test_init` (ops/lib/hermetic_ops_test.sh) — .sh — or
#             reference KG_OPS_TEST — .py.  "Relies on the harness" alone is not enough:
#             ops/test_ops.sh sets the env for the tests it spawns, but a test run
#             standalone (`./ops/tests/test_x.sh`, how people and agents actually run one)
#             would not get it.  Self-initialising is idempotent under the harness.
#         (b) REMOVED (#2922): a file-level "some KG_DEVOPS_BASE= appears somewhere" is not a
#             per-call-site proof (stubbed SAFE loop + unstubbed BYPASS loop is the incident
#             shape).  A test that stubs its own seams still calls `hermetic_ops_test_init`
#             first; its own later assignments win over the deny stub.
#         (c) be listed in TEXT_ONLY below: files that only read devops.sh as text
#             (`bash -n`, grep) and never execute it; the lint re-checks that claim.
#       Scope: ops/**/test_*.sh, ops/tests/* (sh + py), ops/test_*.py.
#   R2  ops/test_ops.sh must call hermetic_ops_test_init BEFORE it runs any group
#       (line order), so every group inherits KG_OPS_TEST=1 + the PATH shim.
#   R3  ops/test_devops.sh must export a recording KG_DEVOPS_BASE BEFORE its first
#       devops_kg_safe.sh invocation, and every "must be blocked" check there must go
#       through expect_blocked_before_base (asserts the base trace is empty).
#   R4  The lint is not vacuous: its scanner is run on synthetic violating and
#       compliant files first (positive + negative control).
#
# Known limit: R1 sees direct mentions only.  A test that reaches production
# transitively (e.g. via release.sh) is protected by the harness (R2) and by the
# transport tripwire in devops.sh (KG_OPS_TEST=1 refuses real ssh/scp/rsync/curl).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../lib/hermetic_ops_test.sh
source "$ROOT/ops/lib/hermetic_ops_test.sh"
hermetic_ops_test_init "$ROOT"

pass=0; fail=0
ok()   { echo "  ✓ $*"; pass=$((pass+1)); }
no()   { echo "  ✗ $*"; fail=$((fail+1)); }

# Files that only read devops.sh as text (never execute it).  Keep this list tiny.
#   test_ios_signal_traps.sh: `bash -n` + grep over devops.sh to check the signal-trap wiring.
TEXT_ONLY=(ops/tests/test_ios_signal_traps.sh)

# lint_file <path> → prints a reason and returns 1 when the file violates R1.
lint_file() {  # <path> [root for relative TEXT_ONLY matching]
  local file="$1" body
  # Drop whole-line comments (# …); inline trailing comments are kept (conservative).
  body="$(grep -vE '^[[:space:]]*#' "$file" || true)"
  grep -qE 'devops\.sh|devops_kg_safe' <<<"$body" || return 0
  case "$file" in
    *.py)
      grep -q 'KG_OPS_TEST' <<<"$body" && return 0 ;;
    *)
      grep -q 'hermetic_ops_test_init' <<<"$body" && return 0 ;;
  esac
  # (c) text-only allowlist — and the claim is re-verified: no direct execution.
  local rel="${file#"${2:-$ROOT}/"}" t
  for t in "${TEXT_ONLY[@]}"; do
    if [[ "$rel" == "$t" ]]; then
      if grep -qE '(bash|sh|source|\.)[[:space:]]+"[^"]*devops(_kg_safe)?\.sh' <<<"$body"; then
        echo "is in TEXT_ONLY but executes devops.sh/devops_kg_safe.sh directly"
        return 1
      fi
      return 0
    fi
  done
  echo "mentions devops.sh/devops_kg_safe.sh but is neither hermetic (hermetic_ops_test_init / KG_OPS_TEST), nor TEXT_ONLY (a stub seam alone is not enough: it is a per-file, not per-call-site, proof)"
  return 1
}

# ── R4: positive + negative control for the scanner itself ───────────────────
echo "── scanner controls ──"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
printf '#!/usr/bin/env bash\nbash ops/devops_kg_safe.sh run "rm -rf /x"\n' > "$T/test_bad.sh"
printf '#!/usr/bin/env bash\nsource lib/hermetic_ops_test.sh\nhermetic_ops_test_init .\nbash devops.sh help\n' > "$T/test_good.sh"
printf '#!/usr/bin/env bash\n# devops.sh is only mentioned in a comment\necho hi\n' > "$T/test_comment_only.sh"
printf 'import subprocess\nsubprocess.run(["./devops.sh", "run", "ls"])\n' > "$T/test_bad.py"
printf 'import os\nos.environ["KG_OPS_TEST"] = "1"\nsubprocess.run(["./devops.sh", "help"])\n' > "$T/test_good.py"
lint_file "$T/test_bad.sh" >/dev/null && no "scanner missed a violating .sh (no init)" || ok "scanner flags a .sh that invokes the safe wrapper without hermetic init"
lint_file "$T/test_good.sh" >/dev/null && ok "scanner accepts a self-hermetic .sh" || no "scanner rejected a compliant .sh"
lint_file "$T/test_comment_only.sh" >/dev/null && ok "scanner ignores comment-only mentions" || no "scanner flagged a comment-only mention"
lint_file "$T/test_bad.py" >/dev/null && no "scanner missed a violating .py" || ok "scanner flags a .py that invokes devops.sh without KG_OPS_TEST"
lint_file "$T/test_good.py" >/dev/null && ok "scanner accepts a .py that references KG_OPS_TEST" || no "scanner rejected a compliant .py"
printf '#!/usr/bin/env bash\nKG_DEVOPS_BASE=/usr/bin/true bash ops/devops_kg_safe.sh status\n' > "$T/test_stubbed.sh"
lint_file "$T/test_stubbed.sh" >/dev/null && no "scanner accepted a .sh whose only protection is a file-level stub seam (#2922)" || ok "scanner rejects a .sh that only injects a stub KG_DEVOPS_BASE without hermetic init (file-level seam is not per-call-site)"
mkdir -p "$T/ops/tests"
printf '#!/usr/bin/env bash\nbash "$ROOT/devops.sh" run ls\n' > "$T/ops/tests/test_liar.sh"
printf '#!/usr/bin/env bash\nbash -n "$ROOT/devops.sh"\n' > "$T/ops/tests/test_honest.sh"
TEXT_ONLY_SAVE=("${TEXT_ONLY[@]}")
TEXT_ONLY=(ops/tests/test_liar.sh ops/tests/test_honest.sh)
lint_file "$T/ops/tests/test_liar.sh" "$T" >/dev/null && no "TEXT_ONLY entry that executes devops.sh was accepted" || ok "a TEXT_ONLY entry that executes devops.sh is rejected"
lint_file "$T/ops/tests/test_honest.sh" "$T" >/dev/null && ok "a TEXT_ONLY entry that only runs bash -n is accepted" || no "honest TEXT_ONLY entry rejected"
TEXT_ONLY=("${TEXT_ONLY_SAVE[@]}")

# ── R1: every test file in scope ─────────────────────────────────────────────
echo "── R1: tests that mention devops.sh / devops_kg_safe.sh are hermetic ──"
scanned=0
while IFS= read -r f; do
  scanned=$((scanned+1))
  if reason="$(lint_file "$ROOT/$f")"; then
    :
  else
    no "$f: $reason"
  fi
done < <(cd "$ROOT" && {
  find ops -type f -name 'test_*.sh'
  find ops/tests -type f \( -name '*.sh' -o -name '*.py' \)
  find ops -maxdepth 1 -type f -name 'test_*.py'
} | LC_ALL=C sort -u)
[[ "$scanned" -ge 20 ]] && ok "R1 scanned $scanned test files (not vacuous)" || no "R1 scanned only $scanned test files — find paths are wrong"
[[ "$fail" -eq 0 ]] && ok "R1: every test that mentions devops.sh / devops_kg_safe.sh initialises the hermetic harness"

# ── R2: the aggregate runner initialises before any group runs ───────────────
echo "── R2: ops/test_ops.sh initialises the harness before running groups ──"
init_line="$(grep -n '^hermetic_ops_test_init' "$ROOT/ops/test_ops.sh" | head -1 | cut -d: -f1 || true)"
run_line="$(grep -n 'heavy_slots_run "\$name" run_one' "$ROOT/ops/test_ops.sh" | head -1 | cut -d: -f1 || true)"
if [[ -n "$init_line" && -n "$run_line" && "$init_line" -lt "$run_line" ]]; then
  ok "test_ops.sh calls hermetic_ops_test_init (line $init_line) before the first group runs (line $run_line)"
else
  no "test_ops.sh does not initialise the hermetic harness before running groups (init=$init_line run=$run_line)"
fi
# The harness really does what the comment says: a child process sees the shim and the flags.
child="$(env -i PATH=/usr/bin:/bin HOME="$HOME" bash -c '
  source "$1/ops/lib/hermetic_ops_test.sh"; hermetic_ops_test_init "$1"
  printf "%s|%s|%s|%s" "$KG_OPS_TEST" "$(command -v ssh)" "$(command -v rsync)" "$(command -v aws)"' _ "$ROOT")"
[[ "$child" == "1|$ROOT/.cache/ops-hermetic-shims/ssh|$ROOT/.cache/ops-hermetic-shims/rsync|$ROOT/.cache/ops-hermetic-shims/aws" ]] \
  && ok "harness: KG_OPS_TEST=1 and ssh/rsync/aws resolve to the deny shims" \
  || no "harness env wrong: $child"
for tool in ssh scp sftp rsync aws; do
  rc=0; err="$(KG_OPS_TEST_TRIPWIRE_LOG=/dev/null "$ROOT/.cache/ops-hermetic-shims/$tool" -o BatchMode=yes chenliangyu@host 'rm -rf /' 2>&1 >/dev/null)" || rc=$?
  if [[ "$rc" -eq 97 && "$err" == "FORBIDDEN: network/production access from an ops test: $tool -o BatchMode=yes chenliangyu@host rm -rf /" ]]; then
    ok "shim $tool: exit 97 + FORBIDDEN message carrying argv"
  else
    no "shim $tool: rc=$rc err=$err"
  fi
done
# A lone --version is a local flavor probe (devops.sh rsync_progress_flags), not network.
rm -f "$T/denied.log"
vout="$(KG_OPS_TEST_TRIPWIRE_LOG="$T/denied.log" "$ROOT/.cache/ops-hermetic-shims/rsync" --version 2>&1)" && vrc=0 || vrc=$?
if [[ "$vrc" -eq 0 && "$vout" != *FORBIDDEN* && ! -s "$T/denied.log" ]]; then
  ok "shim rsync --version passes through to the local binary (no denial logged)"
else
  no "shim rsync --version was denied or logged (rc=$vrc out=$vout)"
fi
# The shim dir twice in PATH under different spellings must not make `--version` exec a shim copy
# forever (#2922): without a real binary anywhere, the second copy has to deny, not loop.
alias_dir="$ROOT/.cache/ops-hermetic-shims/../ops-hermetic-shims"
loop_log="$T/loop.out"
(
  PATH="$ROOT/.cache/ops-hermetic-shims:$alias_dir" KG_OPS_TEST_TRIPWIRE_LOG="$T/loop.tripwire" \
    "$ROOT/.cache/ops-hermetic-shims/rsync" --version >"$loop_log" 2>&1 &
  lpid=$!
  ( sleep 5; kill -9 "$lpid" 2>/dev/null ) &
  kpid=$!
  wait "$lpid" && lrc=0 || lrc=$?; echo "rc=$lrc" >>"$loop_log"
  kill "$kpid" 2>/dev/null || true
) 2>/dev/null
if grep -q '^rc=97$' "$loop_log" && grep -q FORBIDDEN "$loop_log"; then
  ok "shim --version with the shim dir duplicated in PATH denies instead of looping"
else
  no "shim --version recursion guard failed: $(tr '\n' ' ' <"$loop_log")"
fi
# A real binary behind two spellings of the shim dir is still found.
vout="$(PATH="$ROOT/.cache/ops-hermetic-shims:$alias_dir:/usr/bin:/bin" "$ROOT/.cache/ops-hermetic-shims/rsync" --version 2>&1)" && vrc=0 || vrc=$?
[[ "$vrc" -eq 0 && "$vout" != *FORBIDDEN* ]] \
  && ok "shim --version still reaches the real binary past a duplicated shim dir" \
  || no "shim --version lost the real binary (rc=$vrc out=$vout)"
rc=0; KG_OPS_TEST_TRIPWIRE_LOG=/dev/null "$KG_SSH_CMD" host 'ls' >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 97 ]] && ok "KG_SSH_CMD is a deny stub (exit 97)" || no "KG_SSH_CMD deny stub rc=$rc"
rc=0; KG_OPS_TEST_TRIPWIRE_LOG=/dev/null "$KG_SCP_CMD" a b >/dev/null 2>&1 || rc=$?
[[ "$rc" -eq 97 ]] && ok "KG_SCP_CMD is a deny stub (exit 97)" || no "KG_SCP_CMD deny stub rc=$rc"
rm -f "$T/denied.log"
KG_OPS_TEST_TRIPWIRE_LOG="$T/denied.log" "$ROOT/.cache/ops-hermetic-shims/ssh" prod-host 'rm -rf ~/kg-data' 2>/dev/null || true
grep -q "ssh prod-host rm -rf ~/kg-data" "$T/denied.log" 2>/dev/null \
  && ok "a denied attempt leaves a durable log line (visible even if the test swallows the status)" \
  || no "shim did not log the denied attempt"

# ── R3: test_devops.sh seals the base before it touches the wrapper ──────────
echo "── R3: ops/test_devops.sh uses a recording stub base ──"
td="$ROOT/ops/test_devops.sh"
base_line="$(grep -n '^export KG_DEVOPS_BASE=' "$td" | head -1 | cut -d: -f1 || true)"
first_use="$(grep -n 'devops_kg_safe\.sh' "$td" | grep -v '^[0-9]*:[[:space:]]*#' | head -1 | cut -d: -f1 || true)"
if [[ -n "$base_line" && -n "$first_use" && "$base_line" -lt "$first_use" ]]; then
  ok "test_devops.sh exports the recording KG_DEVOPS_BASE (line $base_line) before its first wrapper use (line $first_use)"
else
  no "test_devops.sh does not seal KG_DEVOPS_BASE before first wrapper use (base=$base_line first_use=$first_use)"
fi
grep -q 'expect_blocked_before_base' "$td" && grep -q '! -s "\$BASE_TRACE"' "$td" \
  && ok "blocked checks assert the base trace is empty (never reached base)" \
  || no "blocked checks do not assert an empty base trace"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
