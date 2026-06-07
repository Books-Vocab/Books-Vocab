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
for sub in status build test archive archives issues logs sentry doctor workflow runs snapshot; do
  if [[ "$sub" == "workflow" ]]; then
    grep -qE '^[[:space:]]*workflow\|flow\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "runs" ]]; then
    grep -qE '^[[:space:]]*runs\|reports\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "snapshot" ]]; then
    grep -qE '^[[:space:]]*snapshot\|dashboard\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  else
    grep -qE "^[[:space:]]*$sub\\)" "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  fi
done

section "Doctor release readiness surface"
doctor_body="$(awk '/^doctor_readiness\(\)/,/^}/' "$IOS_OPS")"
for key in project organizer testflight asc_version signing storekit sentry; do
  grep -q "\"$key\"" <<<"$doctor_body" \
    && ok "doctor checks $key readiness" || fail_t "doctor missing $key readiness"
done
grep -q 'cmd_doctor_json' "$IOS_OPS" && grep -q 'kg.ios.doctor.v1' "$IOS_OPS" \
  && ok "doctor exposes machine-readable JSON schema" || fail_t "doctor missing JSON schema"
grep -q 'doctor_readiness emit_readiness_json' "$IOS_OPS" \
  && ok "doctor JSON reuses readiness checks" || fail_t "doctor JSON does not reuse readiness checks"
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
grep -q 'cmd_workflow_release_json' "$IOS_OPS" && grep -q 'kg.ios.workflow.v1' "$IOS_OPS" \
  && ok "workflow exposes machine-readable JSON schema" || fail_t "workflow missing JSON schema"
grep -q 'emit_workflow_step_json' "$IOS_OPS" \
  && ok "workflow JSON emits structured steps" || fail_t "workflow JSON missing structured step emitter"
grep -q './ops/ios_ops.sh test --all-targets --timeout 1200' "$IOS_OPS" \
  && ok "workflow includes all-targets test gate" || fail_t "workflow missing all-targets test command"
grep -q './ops/asc_text_bundle.py dump -o asc.json' "$IOS_OPS" \
  && ok "workflow includes ASC text bundle review" || fail_t "workflow missing asc_text_bundle dump"
grep -q 'ASC GUI' "$IOS_OPS" \
  && ok "workflow marks submit as GUI/manual" || fail_t "workflow missing GUI submit boundary"
grep -qE 'xcodebuild (archive|build|test)|altool --upload-app' "$IOS_OPS" \
  && fail_t "workflow contains direct Xcode side-effect path" \
  || ok "workflow stays orchestration/read-only"

section "Runtime log surface"
logs_json="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --json --since 1m --limit 1)"
echo "$logs_json" | jq -e '.schema=="kg.ios.logs.v1" and .since=="1m" and .limit==1 and .summary.rawCount==3 and .summary.filteredCount==1 and .summary.emittedCount==1 and .summary.byEventType.logEvent==1 and (.entries|length)==1 and .entries[0].message=="sync completed"' >/dev/null \
  && ok "logs --json emits filtered runtime log schema" || fail_t "logs --json invalid: $logs_json"
logs_leading_zero_json="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --json --limit 001)"
echo "$logs_leading_zero_json" | jq -e '.limit==1 and .summary.emittedCount==1' >/dev/null \
  && ok "logs --json normalizes numeric limit" || fail_t "logs --json leading-zero limit invalid: $logs_leading_zero_json"
logs_text="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --since 1m --limit 5 2>/dev/null)"
echo "$logs_text" | grep -q 'sync completed' \
  && ok "logs text emits app log entries" || fail_t "logs text missing app entry: $logs_text"
echo "$logs_text" | grep -q 'RBSServiceErrorDomain' \
  && fail_t "logs text failed to filter framework noise: $logs_text" || ok "logs text filters framework noise"
bad_logs_tmp="$(mktemp -d)"
if KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --limit nope >"$bad_logs_tmp/out" 2>"$bad_logs_tmp/err"; then
  fail_t "logs rejects non-numeric limit"
else
  grep -q -- '--limit must be' "$bad_logs_tmp/err" \
    && ok "logs rejects non-numeric limit" || fail_t "logs bad-limit message missing"
fi
rm -rf "$bad_logs_tmp"
fail_logs_tmp="$(mktemp -d)"
if KG_IOS_OPS_LOG_FAIL_FIXTURE=1 bash "$IOS_OPS" logs --since 1m >"$fail_logs_tmp/out" 2>"$fail_logs_tmp/err"; then
  fail_t "logs text propagates log show failure"
else
  grep -q 'fixture log failure' "$fail_logs_tmp/err" \
    && ok "logs text propagates log show failure" || fail_t "logs text failure stderr missing"
fi
if KG_IOS_OPS_LOG_FAIL_FIXTURE=1 bash "$IOS_OPS" logs --json --since 1m >"$fail_logs_tmp/json_out" 2>"$fail_logs_tmp/json_err"; then
  fail_t "logs --json propagates log show failure"
else
  rc=$?
  grep -q 'fixture log failure' "$fail_logs_tmp/json_err" && [[ "$rc" -eq 42 ]] \
    && ok "logs --json propagates log show failure" || fail_t "logs --json failure stderr missing"
fi
rm -rf "$fail_logs_tmp"

section "JSON smoke fixtures"
runs_parent="$(mktemp -d)"
runs_tmp="$runs_parent/with spaces"
mkdir -p "$runs_tmp"
mkdir -p "$runs_tmp/Build.xcresult" "$runs_tmp/Test.xcresult"
touch "$runs_tmp/build.log" "$runs_tmp/test.log"
echo "RESULT=legacy" > "$runs_tmp/kg_ios_build_verdict"
jq -nc --arg log "$runs_tmp/build.log" --arg xcresult "$runs_tmp/Build.xcresult" \
  '{schema:"kg.ios.run-verdict.v1",kind:"build",status:"ok",result:"ok",exit:"0",reason:null,caller:"fixture with spaces",elapsed:"3s",executed:null,artifacts:{log:$log,xcresult:$xcresult}}' \
  > "$runs_tmp/kg_ios_build_verdict.json"
jq -nc --arg log "$runs_tmp/test.log" --arg xcresult "$runs_tmp/Test.xcresult" \
  '{schema:"kg.ios.run-verdict.v1",kind:"test",status:"ok",result:"ok",exit:"0",reason:null,caller:"fixture with spaces",elapsed:"5s",executed:"12",artifacts:{log:$log,xcresult:$xcresult}}' \
  > "$runs_tmp/kg_ios_test_verdict.json"
runs_json="$(TMPDIR="$runs_tmp" bash "$IOS_OPS" runs --json)"
echo "$runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .build.result=="ok" and .build.caller=="fixture with spaces" and .test.executed=="12" and .build.artifacts.logExists==true and .test.artifacts.xcresultExists==true' >/dev/null \
  && ok "runs --json parses latest build/test verdicts" || fail_t "runs --json invalid: $runs_json"
echo "$runs_json" | jq -e 'all([.build,.test][]; has("kind") and has("status") and has("result") and has("exit") and has("reason") and has("caller") and has("elapsed") and has("executed") and has("verdictFile") and has("jsonVerdictFile") and has("artifacts"))' >/dev/null \
  && ok "runs --json uses stable verdict object keys" || fail_t "runs --json missing stable keys: $runs_json"
missing_runs_tmp="$(mktemp -d)"
missing_runs_json="$(TMPDIR="$missing_runs_tmp" bash "$IOS_OPS" runs --json)"
echo "$missing_runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .build.status=="missing" and .build.artifacts.log==null and .build.artifacts.logExists==false and .test.result=="missing"' >/dev/null \
  && ok "runs --json has stable missing-verdict schema" || fail_t "runs missing-verdict schema invalid: $missing_runs_json"
rm -rf "$missing_runs_tmp"
malformed_runs_tmp="$(mktemp -d)"
echo "RESULT=ok caller=legacy elapsed=1s log=$malformed_runs_tmp/build.log xcresult=$malformed_runs_tmp/Build.xcresult" > "$malformed_runs_tmp/kg_ios_build_verdict"
echo '{bad json' > "$malformed_runs_tmp/kg_ios_build_verdict.json"
echo '{bad json' > "$malformed_runs_tmp/kg_ios_test_verdict.json"
malformed_runs_json="$(TMPDIR="$malformed_runs_tmp" bash "$IOS_OPS" runs --json 2>"$malformed_runs_tmp/stderr")"
echo "$malformed_runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .build.result=="ok" and .test.status=="malformed" and .test.reason=="malformed-json-verdict"' >/dev/null \
  && ok "runs --json falls back or reports malformed JSON verdicts" || fail_t "runs malformed-verdict schema invalid: $malformed_runs_json"
echo "$malformed_runs_json" | jq -e 'all([.build,.test][]; has("jsonVerdictFile") and has("artifacts"))' >/dev/null \
  && ok "runs malformed/legacy fallback keeps stable keys" || fail_t "runs malformed/legacy fallback missing stable keys: $malformed_runs_json"
[[ ! -s "$malformed_runs_tmp/stderr" ]] \
  && ok "runs --json suppresses malformed verdict parser noise" || fail_t "runs malformed-verdict stderr not clean: $(cat "$malformed_runs_tmp/stderr")"
malformed_runs_text="$(TMPDIR="$malformed_runs_tmp" bash "$IOS_OPS" runs 2>"$malformed_runs_tmp/text_stderr")"
echo "$malformed_runs_text" | grep -q 'kind=build status=ok' \
  && ok "runs text uses normalized verdict fallback" || fail_t "runs text malformed fallback invalid: $malformed_runs_text"
[[ ! -s "$malformed_runs_tmp/text_stderr" ]] \
  && ok "runs text suppresses malformed verdict parser noise" || fail_t "runs text malformed-verdict stderr not clean: $(cat "$malformed_runs_tmp/text_stderr")"
rm -rf "$malformed_runs_tmp"
doctor_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" doctor --json)"
echo "$doctor_json" | jq -e '.schema=="kg.ios.doctor.v1" and (.readiness|length >= 7) and any(.readiness[]; .key=="testflight")' >/dev/null \
  && ok "doctor --json parses with readiness array" || fail_t "doctor --json invalid: $doctor_json"
workflow_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" workflow release --json)"
echo "$workflow_json" | jq -e '.schema=="kg.ios.workflow.v1" and (.steps|length == 8) and any(.steps[]; .key=="upload")' >/dev/null \
  && ok "workflow release --json parses with steps array" || fail_t "workflow release --json invalid: $workflow_json"
snapshot_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json)"
echo "$snapshot_json" | jq -e '.schema=="kg.ios.snapshot.v1" and (.readiness|length >= 7) and (.workflow.steps|length == 8) and .project.version=="1.6" and .runs.test.executed=="12" and .logs==null' >/dev/null \
  && ok "snapshot --json combines readiness and workflow" || fail_t "snapshot --json invalid: $snapshot_json"
snapshot_logs_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" snapshot --json --include-logs --log-since 1m --log-limit 1)"
echo "$snapshot_logs_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .logs.schema=="kg.ios.logs.v1" and .logs.since=="1m" and .logs.limit==1 and .logs.summary.filteredCount==1 and (.logs.entries|length)==1' >/dev/null \
  && ok "snapshot --json can include runtime logs" || fail_t "snapshot --json logs invalid: $snapshot_logs_json"
rm -rf "$runs_parent"
bad_args_tmp="$(mktemp -d)"
if KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" doctor --json garbage >"$bad_args_tmp/out" 2>"$bad_args_tmp/err"; then
  fail_t "doctor --json rejects unknown trailing args"
else
  grep -q 'unknown doctor option' "$bad_args_tmp/err" \
    && ok "doctor --json rejects unknown trailing args" || fail_t "doctor --json bad-arg message missing"
fi
rm -rf "$bad_args_tmp"
bad_snapshot_tmp="$(mktemp -d)"
if KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json --log-limit nope >"$bad_snapshot_tmp/out" 2>"$bad_snapshot_tmp/err"; then
  fail_t "snapshot rejects non-numeric log limit"
else
  grep -q -- '--log-limit must be' "$bad_snapshot_tmp/err" \
    && ok "snapshot rejects non-numeric log limit" || fail_t "snapshot bad-log-limit message missing"
fi
if KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_LOG_FAIL_FIXTURE=1 bash "$IOS_OPS" snapshot --json --include-logs --log-since 1m >"$bad_snapshot_tmp/log_out" 2>"$bad_snapshot_tmp/log_err"; then
  fail_t "snapshot --include-logs propagates log failure"
else
  rc=$?
  grep -q 'fixture log failure' "$bad_snapshot_tmp/log_err" && [[ "$rc" -eq 42 ]] \
    && ok "snapshot --include-logs propagates log failure" || fail_t "snapshot include-logs failure stderr missing"
fi
rm -rf "$bad_snapshot_tmp"

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
grep -q 'VERDICT_JSON_FILE' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build writes JSON verdict" || fail_t "ios_build missing JSON verdict"
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
grep -q 'VERDICT_JSON_FILE' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test writes JSON verdict" || fail_t "ios_test missing JSON verdict"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
