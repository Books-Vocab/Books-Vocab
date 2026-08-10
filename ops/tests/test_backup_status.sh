#!/usr/bin/env bash
# test_backup_status.sh — offline regression tests for the scheduled S3 backup health check.

set -o pipefail

WORKTREE="$(cd "$(dirname "$0")/../.." && pwd)"
HELPER="$WORKTREE/ops/backup_status.sh"
TMPDIR="$(mktemp -d -t kg_backup_status_XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass + 1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail + 1)); }
section() { echo ""; echo "── $* ──"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "✗ test 需要 $1，未安裝" >&2; exit 1; }
}
require_cmd date

timestamp_epoch() {
  local timestamp="$1"
  date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$timestamp" '+%s' 2>/dev/null \
    || date -u -d "$timestamp" '+%s'
}

NOW_STAMP='2026-08-09T03:00:00Z'
NOW_EPOCH=$(( $(timestamp_epoch "$NOW_STAMP") + 3600 ))
STALE_EPOCH=$(( NOW_EPOCH + 129601 ))
SHA=$(printf 'a%.0s' {1..64})

write_log() {
  local path="$1" timestamp="$2" exit_code="$3" bytes="$4" sha="$5" key_date="$6"
  printf '%s exit=%s bytes=%s sha256=%s key=data/%s.tar.gz\n' \
    "$timestamp" "$exit_code" "$bytes" "$sha" "$key_date" >"$path"
}

run_status() {
  local log="$1" now="$2" job_state="$3" output="$TMPDIR/output_$RANDOM"
  "$HELPER" --log "$log" --now "$now" --job-state "$job_state" >"$output" 2>&1
  local rc=$?
  printf '%s|%s\n' "$rc" "$output"
}

assert_rc() {
  local name="$1" expected="$2" result="$3" output got
  output="${result#*|}"
  got="${result%%|*}"
  if [[ "$got" == "$expected" ]]; then
    ok "$name (rc=$got)"
  else
    fail_t "$name expect rc=$expected got rc=$got"
    sed 's/^/      /' "$output" >&2
  fi
}

assert_contains() {
  local name="$1" needle="$2" result="$3" output
  output="${result#*|}"
  if grep -qF -- "$needle" "$output"; then
    ok "$name contains \"$needle\""
  else
    fail_t "$name missing \"$needle\""
    sed 's/^/      /' "$output" >&2
  fi
}

section "Syntax and help"
bash -n "$HELPER" 2>/dev/null && ok "backup_status.sh syntax" || fail_t "backup_status.sh syntax"
help_out="$TMPDIR/help"
"$HELPER" --help >"$help_out" 2>&1; help_rc=$?
[[ "$help_rc" == 0 ]] && ok "help exits 0" || fail_t "help exits 0 (rc=$help_rc)"
grep -qF -- "--job-state" "$help_out" && ok "help documents offline job seam" || fail_t "help documents offline job seam"
grep -qF -- "--now" "$help_out" && ok "help documents clock seam" || fail_t "help documents clock seam"

section "Healthy recent record"
healthy_log="$TMPDIR/healthy.log"
write_log "$healthy_log" "$NOW_STAMP" 0 12345 "$SHA" '2026-08-09'
healthy=$(run_status "$healthy_log" "$NOW_EPOCH" loaded)
assert_rc "healthy recent record" 0 "$healthy"
assert_contains "healthy recent record" "backup status healthy" "$healthy"

section "Fail-closed cases"
missing_job=$(run_status "$healthy_log" "$NOW_EPOCH" missing)
assert_rc "missing launchd job" 1 "$missing_job"

missing_log=$(run_status "$TMPDIR/no-such.log" "$NOW_EPOCH" loaded)
assert_rc "missing log" 1 "$missing_log"

failed_log="$TMPDIR/failed.log"
write_log "$failed_log" "$NOW_STAMP" 7 12345 "$SHA" '2026-08-09'
failed=$(run_status "$failed_log" "$NOW_EPOCH" loaded)
assert_rc "non-zero backup exit" 1 "$failed"

bad_format_log="$TMPDIR/bad-format.log"
write_log "$bad_format_log" "$NOW_STAMP" 0 12345 "${SHA%?}" '2026-08-09'
bad_format=$(run_status "$bad_format_log" "$NOW_EPOCH" loaded)
assert_rc "malformed record" 1 "$bad_format"

stale=$(run_status "$healthy_log" "$STALE_EPOCH" loaded)
assert_rc "stale record" 1 "$stale"

wrong_key_log="$TMPDIR/wrong-key.log"
write_log "$wrong_key_log" "$NOW_STAMP" 0 12345 "$SHA" '2026-08-08'
wrong_key=$(run_status "$wrong_key_log" "$NOW_EPOCH" loaded)
assert_rc "key date mismatch" 1 "$wrong_key"

section "Wrapper preserves helper command and remote failure"
STUB="$TMPDIR/base.sh"
cat >"$STUB" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == run ]]; then
  printf 'REMOTE_COMMAND:%s\n' "${2:-}"
  exit "${BACKUP_STATUS_TEST_REMOTE_RC:-0}"
fi
printf 'UNEXPECTED_BASE_CALL:%s\n' "$*" >&2
exit 99
STUB
chmod +x "$STUB"

wrapper_output="$TMPDIR/wrapper-output"
wrapper_rc=0
KG_DEVOPS_BASE="$STUB" \
KG_REMOTE_DIR='~/kg-prod/backend' \
BACKUP_STATUS_TEST_REMOTE_RC=23 \
  "$WORKTREE/ops/devops_kg_safe.sh" backup-s3-test >"$wrapper_output" 2>&1 || wrapper_rc=$?
[[ "$wrapper_rc" == 23 ]] && ok "wrapper preserves helper non-zero rc" || fail_t "wrapper preserves helper non-zero rc (rc=$wrapper_rc)"
grep -qF -- 'REMOTE_COMMAND:cd ~/kg-prod/backend && ../ops/backup_status.sh' "$wrapper_output" \
  && ok "wrapper invokes backup_status.sh from production checkout" \
  || fail_t "wrapper invokes backup_status.sh from production checkout"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ "$fail" -eq 0 ]]
