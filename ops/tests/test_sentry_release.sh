#!/usr/bin/env bash
# test_sentry_release.sh — offline tests for ops/sentry_release.sh
#
# No network: curl, the dSYM uploader and uvx are replaced by fakes that log
# their argv, stdin and environment. The token used here is a fixed fake value;
# every test that touches it also asserts it never reaches argv or output.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HELPER="$ROOT/ops/sentry_release.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0; fail=0
ok()      { echo "  ✓ $*"; pass=$((pass+1)); }
bad()     { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

TOKEN="sntrys_FAKEtokenVALUE0123456789"
SHA="0123456789abcdef0123456789abcdef01234567"
ENC="kg-backend%40$SHA"

# ── fakes ────────────────────────────────────────────────────────────────────
FAKE_CURL="$TMP/fake_curl.sh"
cat >"$FAKE_CURL" <<'EOF'
#!/usr/bin/env bash
log="$FAKE_CURL_LOG"
n=$(( $(cat "$log.count" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$log.count"
printf 'ARGV:%s\n' "$*" >> "$log"
printf 'STDIN:%s\n' "$(cat)" >> "$log.stdin"
out=""; prev=""
for a in "$@"; do [[ "$prev" == "-o" ]] && out="$a"; prev="$a"; done
read -r -a codes <<<"${FAKE_CURL_CODES:-201 200 201}"
code="${codes[$((n-1))]:-201}"
if [[ "$code" == timeout ]]; then exit 28; fi
[[ -n "$out" ]] && printf '{"detail":"fake answer %s"}' "$code" > "$out"
printf '%s' "$code"
EOF
FAKE_CLI="$TMP/fake_sentry_cli.sh"
cat >"$FAKE_CLI" <<'EOF'
#!/usr/bin/env bash
{
  printf 'ARGV:%s\n' "$*"
  printf 'TOKEN_SET:%s\n' "${SENTRY_AUTH_TOKEN:+yes}"
  printf 'SENTRY_URL:%s\n' "${SENTRY_URL:-}"
} >> "$FAKE_CLI_LOG"
case "${FAKE_CLI_MODE:-ok}" in
  ok)   exit 0 ;;
  fail) echo "error: fake upload failed" >&2; exit 1 ;;
  hang) sleep 30 & echo "$!" > "$FAKE_CLI_LOG.child"; wait; exit 0 ;;
esac
EOF
mkdir -p "$TMP/uvxbin"
cat >"$TMP/uvxbin/uvx" <<'EOF'
#!/usr/bin/env bash
printf 'UVX:%s\n' "$*" >> "$FAKE_CLI_LOG"
exit 0
EOF
chmod +x "$FAKE_CURL" "$FAKE_CLI" "$TMP/uvxbin/uvx"

NO_FILE="$TMP/no-such-sentry.env"
ENVFILE="$TMP/sentry.env"
cat >"$ENVFILE" <<EOF
# comment line
export SENTRY_AUTH_TOKEN="$TOKEN"
SENTRY_ORG='kg-org'
SENTRY_PROJECT_BACKEND=kg-backend-proj
SENTRY_PROJECT_IOS = kg-ios-proj
EOF

# run_helper <case-name> [VAR=value ...] -- <args...>
# Clean environment: only what the case passes plus the fakes. stdout/stderr and
# exit code land in $OUT/$ERR/$RC; the curl log in $CLOG.
run_helper() {
  local name="$1"; shift
  local envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  shift
  CLOG="$TMP/$name.curl.log"; OUT="$TMP/$name.out"; ERR="$TMP/$name.err"
  : > "$CLOG"
  env -i HOME="$TMP/home" PATH="/usr/bin:/bin" \
    KG_SENTRY_CURL="$FAKE_CURL" FAKE_CURL_LOG="$CLOG" \
    SENTRY_ENV_FILE="$NO_FILE" FAKE_CLI_LOG="$TMP/$name.cli.log" \
    ${envs[@]+"${envs[@]}"} \
    bash "$HELPER" "$@" >"$OUT" 2>"$ERR"
  RC=$?
}
calls() { cat "$CLOG.count" 2>/dev/null || echo 0; }
no_token_leak() {
  local where
  for where in "$CLOG" "$OUT" "$ERR" "$TMP/$1.cli.log"; do
    if [[ -f "$where" ]] && grep -q "$TOKEN" "$where"; then
      bad "$1: token leaked into $(basename "$where")"; return
    fi
  done
  ok "$1: token absent from argv, stdout and stderr"
}
FULLCFG=(SENTRY_AUTH_TOKEN="$TOKEN" SENTRY_ORG=kg-org SENTRY_PROJECT_BACKEND=kg-backend-proj SENTRY_PROJECT_IOS=kg-ios-proj)

section "Syntax + help"
bash -n "$HELPER" && ok "syntax" || bad "syntax"
[[ -x "$HELPER" ]] && ok "executable" || bad "not executable"
help_out="$(bash "$HELPER" --help 2>&1)"; help_rc=$?
[[ $help_rc -eq 0 ]] && ok "--help exit 0" || bad "--help exit $help_rc"
grep -q 'record-backend' <<<"$help_out" && grep -q 'upload-dsyms' <<<"$help_out" \
  && ok "--help names both subcommands" || bad "--help missing subcommands"

section "record-backend: preconditions SKIP (exit 3) without touching the network"
run_helper short "${FULLCFG[@]}" -- record-backend --sha 0123456
[[ $RC -eq 3 ]] && ok "short sha → exit 3" || bad "short sha → exit $RC"
[[ "$(calls)" == 0 ]] && ok "short sha → no HTTP call" || bad "short sha made $(calls) call(s)"
grep -q 'SKIP' "$ERR" && grep -q '40' "$ERR" && ok "short sha SKIP explains the full-sha contract" || bad "short sha message: $(cat "$ERR")"

run_helper missing -- record-backend --sha "$SHA"
[[ $RC -eq 3 ]] && ok "no config → exit 3" || bad "no config → exit $RC"
[[ "$(calls)" == 0 ]] && ok "no config → no HTTP call" || bad "no config made $(calls) call(s)"
grep -q 'SKIP' "$ERR" && grep -q 'SENTRY_AUTH_TOKEN' "$ERR" && grep -q 'SENTRY_PROJECT_BACKEND' "$ERR" \
  && ok "no config SKIP names the missing keys" || bad "no config message: $(cat "$ERR")"

run_helper badtoken SENTRY_AUTH_TOKEN='abc"def' SENTRY_ORG=kg-org SENTRY_PROJECT_BACKEND=p -- record-backend --sha "$SHA"
[[ $RC -eq 3 && "$(calls)" == 0 ]] && ok "token with quote characters → SKIP, no call" || bad "bad token rc=$RC calls=$(calls)"

run_helper badorg SENTRY_AUTH_TOKEN="$TOKEN" SENTRY_ORG='../x' SENTRY_PROJECT_BACKEND=p -- record-backend --sha "$SHA"
[[ $RC -eq 3 && "$(calls)" == 0 ]] && ok "unsafe org path segment → SKIP, no call" || bad "bad org rc=$RC calls=$(calls)"

run_helper insecure "${FULLCFG[@]}" SENTRY_API_URL=http://sentry.example.com -- record-backend --sha "$SHA"
[[ $RC -eq 3 && "$(calls)" == 0 ]] && ok "non-HTTPS remote API URL → SKIP, no call" || bad "http url rc=$RC calls=$(calls)"

section "record-backend: create + finalize + deploy"
run_helper success "${FULLCFG[@]}" -- record-backend --sha "$SHA" --environment production --name reconciler
[[ $RC -eq 0 ]] && ok "exit 0" || bad "exit $RC ($(cat "$ERR"))"
[[ "$(calls)" == 3 ]] && ok "three API calls" || bad "$(calls) API call(s)"
l1="$(sed -n 1p "$CLOG")"; l2="$(sed -n 2p "$CLOG")"; l3="$(sed -n 3p "$CLOG")"
[[ "$l1" == *"-X POST"* && "$l1" == *"https://sentry.io/api/0/organizations/kg-org/releases/"* ]] \
  && ok "create POSTs to the org releases endpoint" || bad "create call: $l1"
[[ "$l1" == *"\"version\":\"kg-backend@$SHA\""* && "$l1" == *"\"projects\":[\"kg-backend-proj\"]"* ]] \
  && ok "create names kg-backend@<full sha> for the backend project" || bad "create body: $l1"
[[ "$l2" == *"-X PUT"* && "$l2" == *"/organizations/kg-org/releases/$ENC/"* && "$l2" == *dateReleased* ]] \
  && ok "finalize PUTs dateReleased on the url-encoded release" || bad "finalize call: $l2"
[[ "$l3" == *"-X POST"* && "$l3" == *"/organizations/kg-org/releases/$ENC/deploys/"* \
   && "$l3" == *'"environment":"production"'* && "$l3" == *'"name":"reconciler"'* ]] \
  && ok "deploy records environment + name" || bad "deploy call: $l3"
[[ "$(grep -c -- '--max-time' "$CLOG")" == 3 && "$(grep -c -- '--connect-timeout' "$CLOG")" == 3 ]] \
  && ok "every call is time-bounded" || bad "missing timeouts in some call"
[[ "$(grep -c 'Authorization: Bearer' "$CLOG.stdin")" == 3 ]] \
  && ok "token travels on curl's stdin config, once per call" || bad "auth header not on stdin"
[[ ! -s "$OUT" ]] && ok "stdout stays empty (callers reserve it for machine output)" || bad "stdout: $(cat "$OUT")"
no_token_leak success

run_helper exists "${FULLCFG[@]}" FAKE_CURL_CODES="208 200 201" -- record-backend --sha "$SHA"
[[ $RC -eq 0 && "$(calls)" == 3 ]] && ok "release that already exists (208) is still finalized + deployed" || bad "208 rc=$RC calls=$(calls)"

run_helper envfile SENTRY_ENV_FILE="$ENVFILE" -- record-backend --sha "$SHA"
[[ $RC -eq 0 ]] && ok "config read from env file (export / quotes / spaces)" || bad "env file rc=$RC ($(cat "$ERR"))"
grep -q '/organizations/kg-org/' "$CLOG" && ok "env-file org used" || bad "env-file org missing"
no_token_leak envfile

run_helper envwins SENTRY_ENV_FILE="$ENVFILE" SENTRY_ORG=env-org -- record-backend --sha "$SHA"
grep -q '/organizations/env-org/' "$CLOG" && ! grep -q '/organizations/kg-org/' "$CLOG" \
  && ok "process env wins over the env file" || bad "env precedence wrong: $(head -1 "$CLOG")"

run_helper selfhost "${FULLCFG[@]}" SENTRY_API_URL=https://sentry.example.com/ -- record-backend --sha "$SHA"
grep -q 'https://sentry.example.com/api/0/organizations/' "$CLOG" \
  && ok "API URL without /api/0 is normalised" || bad "normalisation: $(head -1 "$CLOG")"

run_helper loopback "${FULLCFG[@]}" SENTRY_API_URL=http://127.0.0.1:9000/api/0 -- record-backend --sha "$SHA"
[[ $RC -eq 0 ]] && grep -q 'http://127.0.0.1:9000/api/0/organizations/' "$CLOG" \
  && ok "loopback http allowed (local test servers)" || bad "loopback rc=$RC"

section "record-backend: failures are reported, bounded, and stop early"
run_helper forbidden "${FULLCFG[@]}" FAKE_CURL_CODES="403" -- record-backend --sha "$SHA"
[[ $RC -eq 1 ]] && ok "403 → exit 1" || bad "403 → exit $RC"
[[ "$(calls)" == 1 ]] && ok "403 on create stops before finalize/deploy" || bad "403 made $(calls) call(s)"
grep -q 'HTTP 403' "$ERR" && grep -q 'fake answer 403' "$ERR" && ok "403 surfaces status + Sentry detail" || bad "403 message: $(cat "$ERR")"
no_token_leak forbidden

run_helper timeout "${FULLCFG[@]}" FAKE_CURL_CODES="timeout" -- record-backend --sha "$SHA"
[[ $RC -eq 1 && "$(calls)" == 1 ]] && ok "curl timeout on create → exit 1, one call" || bad "timeout rc=$RC calls=$(calls)"

run_helper deployfail "${FULLCFG[@]}" FAKE_CURL_CODES="201 200 500" -- record-backend --sha "$SHA"
[[ $RC -eq 1 ]] && ok "deploy 500 → exit 1" || bad "deploy 500 → exit $RC"

section "check --json: presence only, never values"
run_helper check SENTRY_ENV_FILE="$ENVFILE" -- check --json
[[ $RC -eq 0 ]] && ok "check exit 0" || bad "check exit $RC"
grep -q '"schema":"kg.sentry.release.check.v1"' "$OUT" && ok "check schema" || bad "check schema: $(cat "$OUT")"
grep -q '"SENTRY_AUTH_TOKEN":true' "$OUT" && grep -q '"SENTRY_PROJECT_IOS":true' "$OUT" \
  && grep -q '"env_file":"present"' "$OUT" && ok "check reports key presence + env file" || bad "check body: $(cat "$OUT")"
grep -q "\"sentry_cli\":\"3\." "$OUT" && ok "check reports the pinned sentry-cli version" || bad "check missing pin: $(cat "$OUT")"
no_token_leak check
run_helper checkempty -- check --json
grep -q '"SENTRY_AUTH_TOKEN":false' "$OUT" && grep -q '"env_file":"missing"' "$OUT" \
  && ok "check reports absence" || bad "check empty: $(cat "$OUT")"

section "upload-dsyms"
DSYMS="$TMP/archive/dSYMs"; mkdir -p "$DSYMS/BooksAndVocab.app.dSYM/Contents"
run_helper dsym_ok "${FULLCFG[@]}" KG_SENTRY_CLI="$FAKE_CLI" -- upload-dsyms "$DSYMS"
CL="$TMP/dsym_ok.cli.log"
[[ $RC -eq 0 ]] && ok "upload → exit 0" || bad "upload exit $RC ($(cat "$ERR"))"
grep -q "ARGV:debug-files upload --org kg-org --project kg-ios-proj --type dsym $DSYMS" "$CL" \
  && ok "uploader gets org/project/type/path" || bad "uploader argv: $(cat "$CL" 2>/dev/null)"
grep -q 'TOKEN_SET:yes' "$CL" && ok "token passed via SENTRY_AUTH_TOKEN env" || bad "token not in uploader env"
grep -q 'SENTRY_URL:https://sentry.io$' "$CL" && ok "SENTRY_URL derived from API URL (no /api/0)" || bad "SENTRY_URL: $(grep SENTRY_URL "$CL")"
no_token_leak dsym_ok

run_helper dsym_noproj SENTRY_AUTH_TOKEN="$TOKEN" SENTRY_ORG=kg-org KG_SENTRY_CLI="$FAKE_CLI" -- upload-dsyms "$DSYMS"
[[ $RC -eq 3 && ! -s "$TMP/dsym_noproj.cli.log" ]] && grep -q 'SENTRY_PROJECT_IOS' "$ERR" \
  && ok "missing SENTRY_PROJECT_IOS → SKIP, uploader never runs" || bad "noproj rc=$RC"

mkdir -p "$TMP/empty-dsyms"
run_helper dsym_none "${FULLCFG[@]}" KG_SENTRY_CLI="$FAKE_CLI" -- upload-dsyms "$TMP/empty-dsyms"
[[ $RC -eq 3 && ! -s "$TMP/dsym_none.cli.log" ]] && ok "no .dSYM bundles → SKIP" || bad "no dsyms rc=$RC"

run_helper dsym_fail "${FULLCFG[@]}" KG_SENTRY_CLI="$FAKE_CLI" FAKE_CLI_MODE=fail -- upload-dsyms "$DSYMS"
[[ $RC -eq 1 ]] && ok "uploader failure → exit 1" || bad "uploader failure → exit $RC"

start=$(date +%s)
run_helper dsym_hang "${FULLCFG[@]}" KG_SENTRY_CLI="$FAKE_CLI" FAKE_CLI_MODE=hang KG_SENTRY_DSYM_TIMEOUT=2 -- upload-dsyms "$DSYMS"
elapsed=$(( $(date +%s) - start ))
[[ $RC -ne 0 && $RC -ne 3 && $elapsed -lt 10 ]] && ok "hung uploader killed by the time bound (${elapsed}s, exit $RC)" \
  || bad "hung uploader rc=$RC elapsed=${elapsed}s"
grep -qi 'time' "$ERR" && ok "time-bound kill is reported" || bad "hang message: $(cat "$ERR")"
child="$(cat "$TMP/dsym_hang.cli.log.child" 2>/dev/null)"
sleep 0.5
[[ -n "$child" ]] && ! kill -0 "$child" 2>/dev/null \
  && ok "the uploader's own children die with it (process-group kill)" || bad "uploader child $child survived the time bound"

run_helper dsym_uvx "${FULLCFG[@]}" PATH="$TMP/uvxbin:/usr/bin:/bin" -- upload-dsyms "$DSYMS"
[[ $RC -eq 0 ]] && grep -q 'UVX:--from sentry-cli==3\.[0-9]*\.[0-9]* sentry-cli debug-files upload' "$TMP/dsym_uvx.cli.log" \
  && ok "default uploader is uvx with a pinned sentry-cli" || bad "uvx default rc=$RC log=$(cat "$TMP/dsym_uvx.cli.log" 2>/dev/null)"

run_helper dsym_nouvx "${FULLCFG[@]}" -- upload-dsyms "$DSYMS"
[[ $RC -eq 3 ]] && grep -q 'uvx' "$ERR" && ok "no uvx on PATH → SKIP naming uvx" || bad "no uvx rc=$RC ($(cat "$ERR"))"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
