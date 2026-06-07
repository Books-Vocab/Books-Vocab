#!/usr/bin/env bash
# test_ios_ops.sh — structure tests for unified iOS ops entrypoint.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
IOS_OPS="$WORKSPACE/ops/ios_ops.sh"
IOS_ARCHIVE="$WORKSPACE/ops/ios_archive.sh"
IOS_DIAG="$WORKSPACE/ops/ios_diagnostics.py"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

section "Syntax and executable bits"
for f in "$IOS_OPS" "$IOS_ARCHIVE" "$IOS_DIAG"; do
  [[ -f "$f" ]] && ok "$(basename "$f") exists" || fail_t "$(basename "$f") missing"
done
bash -n "$IOS_OPS" && ok "ios_ops.sh syntax" || fail_t "ios_ops.sh syntax"
bash -n "$IOS_ARCHIVE" && ok "ios_archive.sh syntax" || fail_t "ios_archive.sh syntax"

section "Unified entrypoint help is safe"
help_out="$(bash "$IOS_OPS" --help 2>&1)"
echo "$help_out" | grep -q 'Usage:' && ok "ios_ops help prints Usage" || fail_t "ios_ops help missing Usage"
echo "$help_out" | grep -qE 'xcodebuild archive|xcodebuild test|xcodebuild .*build' \
  && fail_t "ios_ops help appears to run xcodebuild" || ok "ios_ops help is side-effect free"

section "Dispatch surface"
for sub in status build test archive archives issues logs sentry doctor workflow; do
  if [[ "$sub" == "workflow" ]]; then
    grep -qE '^[[:space:]]*workflow\|flow\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  else
    grep -qE "^[[:space:]]*$sub\\)" "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  fi
done

section "Doctor release readiness surface"
doctor_body="$(awk '/^cmd_doctor\(\)/,/^}/' "$IOS_OPS")"
for key in project organizer testflight asc_version signing storekit sentry; do
  grep -q "emit_readiness \"$key\"" <<<"$doctor_body" \
    && ok "doctor checks $key readiness" || fail_t "doctor missing $key readiness"
done
grep -q 'read_asc_version_state' <<<"$doctor_body" && grep -q 'waited >= 12' "$IOS_OPS" \
  && ok "doctor bounds ASC version-state lookup" || fail_t "doctor missing bounded ASC version lookup"
grep -q 'ExportOptions.plist' <<<"$doctor_body" \
  && ok "doctor checks export signing options" || fail_t "doctor missing ExportOptions check"
grep -q 'Products\\.storekit' <<<"$doctor_body" \
  && ok "doctor checks StoreKit scheme/file" || fail_t "doctor missing StoreKit check"
grep -qE 'xcodebuild (archive|build|test)|altool --upload-app|--upload' <<<"$doctor_body" \
  && fail_t "doctor contains side-effecting build/archive/upload path" \
  || ok "doctor stays read-only"

section "Release workflow surface"
for key in preflight tests build archive upload asc-review metadata submit; do
  grep -q "\"$key\"" "$IOS_OPS" \
    && ok "workflow includes $key step" || fail_t "workflow missing $key step"
done
grep -q './ops/ios_ops.sh test --all-targets --timeout 1200' "$IOS_OPS" \
  && ok "workflow includes all-targets test gate" || fail_t "workflow missing all-targets test command"
grep -q './ops/asc_text_bundle.py dump -o asc.json' "$IOS_OPS" \
  && ok "workflow includes ASC text bundle review" || fail_t "workflow missing asc_text_bundle dump"
grep -q 'ASC GUI' "$IOS_OPS" \
  && ok "workflow marks submit as GUI/manual" || fail_t "workflow missing GUI submit boundary"
grep -qE 'xcodebuild (archive|build|test)|altool --upload-app' "$IOS_OPS" \
  && fail_t "workflow contains direct Xcode side-effect path" \
  || ok "workflow stays orchestration/read-only"

section "Archive fixture"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
archive="$tmp/2026-06-07/BooksBrowser 2026-6-7, 1.00 PM.xcarchive"
mkdir -p "$archive"
cat > "$archive/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Name</key><string>BooksBrowser</string>
  <key>CreationDate</key><date>2026-06-07T05:00:00Z</date>
  <key>ApplicationProperties</key>
  <dict>
    <key>CFBundleIdentifier</key><string>com.Max0228.BooksBrowser</string>
    <key>CFBundleShortVersionString</key><string>1.6</string>
    <key>CFBundleVersion</key><string>4</string>
  </dict>
</dict>
</plist>
PLIST
list_out="$(bash "$IOS_ARCHIVE" list --root "$tmp")"
echo "$list_out" | grep -q $'1.6\t4' && ok "archive list includes version/build" || fail_t "archive list missing version/build: $list_out"
json_out="$(bash "$IOS_ARCHIVE" latest --root "$tmp" --json)"
echo "$json_out" | grep -q '"version":"1.6"' && ok "archive latest --json includes version" || fail_t "archive json missing version"
echo "$json_out" | grep -q '"build":"4"' && ok "archive latest --json includes build" || fail_t "archive json missing build"

section "ios_build emits diagnostics"
grep -q 'ios_diagnostics.py' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build calls diagnostics parser" || fail_t "ios_build missing diagnostics parser"
grep -q 'kg_ios_build.*log' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build preserves raw log path" || fail_t "ios_build does not preserve log path"
grep -q -- '-resultBundlePath' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build emits xcresult bundle" || fail_t "ios_build missing -resultBundlePath"
grep -q -- '--xcresult' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build feeds xcresult to diagnostics" || fail_t "ios_build does not feed xcresult to diagnostics"

section "ios_test emits xcresult-first diagnostics"
grep -q -- '-resultBundlePath' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test emits xcresult bundle" || fail_t "ios_test missing -resultBundlePath"
grep -q -- '--kind test' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test reads xcresult test-results" || fail_t "ios_test missing --kind test diagnostics"
grep -q 'count_executed_tests_xcresult' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test counts executed tests from xcresult first" || fail_t "ios_test missing xcresult executed-count path"
grep -q 'xcresult=.*RESULT_BUNDLE' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test verdict records xcresult" || fail_t "ios_test verdict missing xcresult path"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
