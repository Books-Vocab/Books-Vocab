#!/usr/bin/env bash
# Install provenance regression for IMP-20260809-031b05.
#
# The test is offline: xcrun is replaced with a recording stub.  The negative
# controls must fail before the install command is reached; a warning-only
# implementation is not a valid fix.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL="$WORKSPACE/ops/ios_install.sh"
BUILD="$WORKSPACE/ops/ios_build.sh"
PROBE="$WORKSPACE/ops/review_flip_probe.sh"
IOS_SOP="$WORKSPACE/docs/sop/ios.md"
# shellcheck source=../lib/ios_install_provenance.sh
source "$WORKSPACE/ops/lib/ios_install_provenance.sh"

PASS=0
FAIL=0
ok() { echo "  ✓ $*"; PASS=$((PASS + 1)); }
bad() { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }
check() {
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 (got=$2 want=$3)"; fi
}
expect_true() { if "$@"; then ok "${*:2}"; else bad "${*:2}"; fi; }
expect_absent() { if "$@"; then bad "unexpected match: ${*:2}"; else ok "absent: ${*:2}"; fi; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/kg_ios_install_provenance.XXXXXX")"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

DERIVED="$TMP/derived"
APP="$DERIVED/Build/Products/Debug-iphonesimulator/BooksAndVocab.app"
SIDE="$APP.kg-provenance.json"
STUB_BIN="$TMP/bin"
XCRUN_LOG="$TMP/xcrun.log"
mkdir -p "$APP" "$STUB_BIN"
: >"$XCRUN_LOG"

cat >"$STUB_BIN/xcrun" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$KG_XCRUN_LOG"
EOF
chmod +x "$STUB_BIN/xcrun"

HEAD="$(git -C "$WORKSPACE" rev-parse HEAD)"
PARENT="$(git -C "$WORKSPACE" rev-parse HEAD^ 2>/dev/null || true)"
[[ -n "$PARENT" ]] || { echo "FATAL: repository needs a parent commit" >&2; exit 1; }

write_sidecar() {
  local root="$1" head="$2"
  jq -n \
    --arg schema "kg.ios.install-provenance.v1" \
    --arg projectRoot "$root" \
    --arg head "$head" \
    --arg configuration Debug \
    --arg destination "platform=iOS Simulator" \
    '{schema:$schema, projectRoot:$projectRoot, head:$head,
      configuration:$configuration, destination:$destination, builtAt:"test"}' \
    >"$SIDE"
}

run_install() {
  PATH="$STUB_BIN:$PATH" KG_XCRUN_LOG="$XCRUN_LOG" \
    "$INSTALL" --simulator SIM-UDID --app "$APP"
}

assert_rejected() {
  local label="$1" expected_artifact_head="$2"
  local output rc
  : >"$XCRUN_LOG"
  set +e
  output="$(run_install 2>&1)"
  rc=$?
  set -e
  check "$label: exit != 0" "$([[ "$rc" -ne 0 ]] && echo yes || echo no)" yes
  expect_true grep -qF "artifact source:" <<<"$output"
  expect_true grep -qF "head=$expected_artifact_head" <<<"$output"
  expect_true grep -qF "current HEAD:" <<<"$output"
  expect_true grep -qF "head=$HEAD" <<<"$output"
  check "$label: xcrun not called" "$(wc -c <"$XCRUN_LOG" | tr -d ' ')" "0"
  expect_true test ! -e "$SIDE.tmp"
}

echo "── structural wiring ──"
expect_true test -x "$INSTALL"
expect_true grep -qF 'kg_ios_write_install_provenance' "$BUILD"
expect_true grep -qF 'ios_install.sh" --simulator' "$PROBE"
expect_true grep -qF 'ios_install.sh" --device' "$PROBE"
expect_absent grep -qF 'xcrun simctl install' "$PROBE"
expect_true grep -qF '視覺驗收前先過安裝入口' "$IOS_SOP"
expect_absent grep -qF 'xcrun simctl install' "$IOS_SOP"

echo "── positive control ──"
kg_ios_write_install_provenance "$WORKSPACE" "$DERIVED" Debug \
  "platform=iOS Simulator,name=iPhone 17 Pro Max" >"$TMP/build-provenance.log"
check "build writes provenance schema" "$(jq -r '.schema' "$SIDE")" "kg.ios.install-provenance.v1"
check "build writes current HEAD" "$(jq -r '.head' "$SIDE")" "$HEAD"
check "build writes current worktree" "$(jq -r '.projectRoot' "$SIDE")" "$WORKSPACE"
: >"$XCRUN_LOG"
set +e
positive_output="$(run_install 2>&1)"
positive_rc=$?
set -e
check "matching source: exit 0" "$positive_rc" "0"
expect_true grep -qF 'simctl install SIM-UDID' "$XCRUN_LOG"
expect_true grep -qF "verified HEAD=$HEAD" <<<"$positive_output"

echo "── forged sidecar negative control ──"
FORGED="0000000000000000000000000000000000000000000000000000000000000000"
write_sidecar "$WORKSPACE" "$FORGED"
assert_rejected "forged HEAD" "$FORGED"

echo "── stale artifact negative control ──"
write_sidecar "$WORKSPACE" "$PARENT"
assert_rejected "stale HEAD after worktree advanced" "$PARENT"

echo "── summary ──"
echo "passed=$PASS failed=$FAIL"
[[ "$FAIL" -eq 0 ]]
