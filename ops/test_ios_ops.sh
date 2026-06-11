#!/usr/bin/env bash
# test_ios_ops.sh — structure tests for unified iOS ops entrypoint.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
IOS_OPS="$WORKSPACE/ops/ios_ops.sh"
IOS_OPS_XCODE_LIB="$WORKSPACE/ops/lib/ios_ops_xcode.sh"
IOS_OPS_LOGS_LIB="$WORKSPACE/ops/lib/ios_ops_logs.sh"
IOS_OPS_RUNS_LIB="$WORKSPACE/ops/lib/ios_ops_runs.sh"
IOS_OPS_SNAPSHOT_LIB="$WORKSPACE/ops/lib/ios_ops_snapshot.sh"
IOS_OPS_SIMULATOR_LIB="$WORKSPACE/ops/lib/ios_ops_simulator.sh"
IOS_OPS_CATALOG_LIB="$WORKSPACE/ops/lib/ios_ops_catalog.sh"
IOS_OPS_RELEASE_LIB="$WORKSPACE/ops/lib/ios_ops_release.sh"
IOS_OPS_COMMANDS_LIB="$WORKSPACE/ops/lib/ios_ops_commands.sh"
IOS_OPS_CORE_LIB="$WORKSPACE/ops/lib/ios_ops_core.sh"
IOS_ARCHIVE="$WORKSPACE/ops/ios_archive.sh"
IOS_DIAG="$WORKSPACE/ops/ios_diagnostics.py"

pass=0; fail=0
ok() { echo "  ✓ $*"; pass=$((pass+1)); }
fail_t() { echo "  ✗ $*"; fail=$((fail+1)); }
section() { echo ""; echo "── $* ──"; }

section "Syntax and executable bits"
for f in "$IOS_OPS" "$IOS_OPS_CORE_LIB" "$IOS_OPS_XCODE_LIB" "$IOS_OPS_LOGS_LIB" "$IOS_OPS_RUNS_LIB" "$IOS_OPS_SNAPSHOT_LIB" "$IOS_OPS_SIMULATOR_LIB" "$IOS_OPS_CATALOG_LIB" "$IOS_OPS_RELEASE_LIB" "$IOS_OPS_COMMANDS_LIB" "$IOS_ARCHIVE" "$IOS_DIAG"; do
  [[ -f "$f" ]] && ok "$(basename "$f") exists" || fail_t "$(basename "$f") missing"
done
bash -n "$IOS_OPS" && ok "ios_ops.sh syntax" || fail_t "ios_ops.sh syntax"
bash -n "$IOS_OPS_CORE_LIB" && ok "ios_ops_core.sh syntax" || fail_t "ios_ops_core.sh syntax"
bash -n "$IOS_OPS_XCODE_LIB" && ok "ios_ops_xcode.sh syntax" || fail_t "ios_ops_xcode.sh syntax"
bash -n "$IOS_OPS_LOGS_LIB" && ok "ios_ops_logs.sh syntax" || fail_t "ios_ops_logs.sh syntax"
bash -n "$IOS_OPS_RUNS_LIB" && ok "ios_ops_runs.sh syntax" || fail_t "ios_ops_runs.sh syntax"
bash -n "$IOS_OPS_SNAPSHOT_LIB" && ok "ios_ops_snapshot.sh syntax" || fail_t "ios_ops_snapshot.sh syntax"
bash -n "$IOS_OPS_SIMULATOR_LIB" && ok "ios_ops_simulator.sh syntax" || fail_t "ios_ops_simulator.sh syntax"
bash -n "$IOS_OPS_CATALOG_LIB" && ok "ios_ops_catalog.sh syntax" || fail_t "ios_ops_catalog.sh syntax"
bash -n "$IOS_OPS_RELEASE_LIB" && ok "ios_ops_release.sh syntax" || fail_t "ios_ops_release.sh syntax"
bash -n "$IOS_OPS_COMMANDS_LIB" && ok "ios_ops_commands.sh syntax" || fail_t "ios_ops_commands.sh syntax"
bash -n "$IOS_ARCHIVE" && ok "ios_archive.sh syntax" || fail_t "ios_archive.sh syntax"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_core.sh"' "$IOS_OPS" \
  && ok "ios_ops sources core lib" || fail_t "ios_ops does not source core lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_commands.sh"' "$IOS_OPS" \
  && ok "ios_ops sources commands lib" || fail_t "ios_ops does not source commands lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_xcode.sh"' "$IOS_OPS" \
  && ok "ios_ops sources xcode lib" || fail_t "ios_ops does not source xcode lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_logs.sh"' "$IOS_OPS" \
  && ok "ios_ops sources logs lib" || fail_t "ios_ops does not source logs lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_runs.sh"' "$IOS_OPS" \
  && ok "ios_ops sources runs lib" || fail_t "ios_ops does not source runs lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_snapshot.sh"' "$IOS_OPS" \
  && ok "ios_ops sources snapshot lib" || fail_t "ios_ops does not source snapshot lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_simulator.sh"' "$IOS_OPS" \
  && ok "ios_ops sources simulator lib" || fail_t "ios_ops does not source simulator lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_catalog.sh"' "$IOS_OPS" \
  && ok "ios_ops sources catalog lib" || fail_t "ios_ops does not source catalog lib"
grep -q 'source "$SCRIPT_DIR/lib/ios_ops_release.sh"' "$IOS_OPS" \
  && ok "ios_ops sources release lib" || fail_t "ios_ops does not source release lib"
prev_source_line=0
for lib in ios_ops_core.sh ios_ops_commands.sh ios_ops_logs.sh ios_ops_release.sh ios_ops_xcode.sh ios_ops_simulator.sh ios_ops_runs.sh ios_ops_snapshot.sh ios_ops_catalog.sh; do
  source_line="$(grep -n "source \"\\\$SCRIPT_DIR/lib/$lib\"" "$IOS_OPS" | head -1 | cut -d: -f1)"
  if [[ -n "$source_line" && "$source_line" -gt "$prev_source_line" ]]; then
    ok "source order: $lib"
    prev_source_line="$source_line"
  else
    fail_t "source order drift: $lib"
  fi
done

section "Core provider boundary"
for fn in read_project_settings read_organizer_latest read_testflight_latest_build read_asc_version_state read_xcode_version_text read_xcode_project_list_json read_xcode_destinations_text read_simctl_devices_json read_app_container_path read_app_process_pid read_app_launch_output read_app_terminate_output write_simulator_screenshot capture_source_text capture_source_json cleanup_tmp verdict_file_for verdict_json_file_for verdict_field path_exists_json_bool; do
  grep -qE "^${fn}\\(\\)" "$IOS_OPS_CORE_LIB" \
    && ok "core defines $fn" || fail_t "core missing $fn"
  grep -qE "^${fn}\\(\\)" "$IOS_OPS" \
    && fail_t "ios_ops should not redefine core function $fn" || ok "ios_ops keeps $fn out of façade"
done

section "Unified entrypoint help is safe"
help_out="$(bash "$IOS_OPS" --help 2>&1)"
echo "$help_out" | grep -q 'Usage:' && ok "ios_ops help prints Usage" || fail_t "ios_ops help missing Usage"
echo "$help_out" | grep -qE 'xcodebuild archive|xcodebuild test|xcodebuild .*build' \
  && fail_t "ios_ops help appears to run xcodebuild" || ok "ios_ops help is side-effect free"

section "Dispatch surface"
for sub in status build test archive archives issues logs sentry doctor workflow gate xcode simulator runs snapshot catalog commands; do
  if [[ "$sub" == "workflow" ]]; then
    grep -qE '^[[:space:]]*workflow\|flow\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "gate" ]]; then
    grep -qE '^[[:space:]]*gate\|verdict\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "runs" ]]; then
    grep -qE '^[[:space:]]*runs\|reports\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "xcode" ]]; then
    grep -qE '^[[:space:]]*xcode\|environment\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "simulator" ]]; then
    grep -qE '^[[:space:]]*simulator\|sim\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "snapshot" ]]; then
    grep -qE '^[[:space:]]*snapshot\|dashboard\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "catalog" ]]; then
    grep -qE '^[[:space:]]*catalog\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  elif [[ "$sub" == "commands" ]]; then
    grep -qE '^[[:space:]]*commands\|capabilities\)' "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  else
    grep -qE "^[[:space:]]*$sub\\)" "$IOS_OPS" \
      && ok "dispatch: $sub" || fail_t "dispatch missing: $sub"
  fi
done

section "Command catalog surface"
grep -q 'cmd_commands_json' "$IOS_OPS_COMMANDS_LIB" && grep -q 'kg.ios.commands.v1' "$IOS_OPS_COMMANDS_LIB" \
  && ok "commands catalog implementation lives in commands lib" || fail_t "commands catalog missing from commands lib"
grep -qE '^cmd_commands(_json)?\(\)' "$IOS_OPS" \
  && fail_t "ios_ops should not redefine commands catalog functions" || ok "ios_ops keeps commands catalog out of façade"
commands_json="$(bash "$IOS_OPS" commands --json)"
echo "$commands_json" | jq -e '.schema=="kg.ios.commands.v1" and (.commands|length >= 17) and all(.commands[]; has("delegate")) and any(.commands[]; .key=="status" and (.jsonSchemas|index("kg.ios.status.v1")) and (.command|test("--json"))) and any(.commands[]; .key=="build" and (.jsonSchemas|index("kg.ios.run.v1")) and (.jsonSchemas|index("kg.ios.diagnostics.v1")) and (.command|test("--json"))) and any(.commands[]; .key=="snapshot" and (.jsonSchemas|index("kg.ios.snapshot.v1")) and (.jsonSchemas|index("kg.ios.workflow.v1")) and (.jsonSchemas|index("kg.ios.gate.v1")) and (.jsonSchemas|index("kg.ios.sentry.v1")) and (.jsonSchemas|index("kg.ios.xcode.v1")) and (.jsonSchemas|index("kg.ios.simulator.v1")) and (.jsonSchemas|index("kg.ios.runs.v1")) and (.jsonSchemas|index("kg.ios.diagnostics.v1")) and (.jsonSchemas|index("kg.ios.logs.v1"))) and any(.commands[]; .key=="catalog" and (.jsonSchemas|index("kg.ios.catalog.v1")) and (.command|test("catalog prepare")) and (.command|test("catalog snapshots")) and (.command|test("catalog clean")) and (.command|test("--dataset <name>")) and (.command|test("--dataset-file <path>")) and (.sideEffect|test("local-test")) and (.sideEffect|test("local-artifact"))) and any(.commands[]; .key=="test" and (.jsonSchemas|index("kg.ios.run.v1")) and (.jsonSchemas|index("kg.ios.test-cache.v1")) and (.jsonSchemas|index("kg.ios.diagnostics.v1")) and (.command|test("--launch-benchmark")) and (.command|test("--cache-status")) and (.command|test("--prepare-cache")) and (.command|test("--clean-cache")) and (.command|test("--json"))) and any(.commands[]; .key=="logs" and .sideEffect=="read-only" and (.jsonSchemas|index("kg.ios.logs.v1"))) and any(.commands[]; .key=="sentry" and .sideEffect=="read-only" and (.jsonSchemas|index("kg.ios.sentry.v1")) and (.command|test("--json"))) and any(.commands[]; .key=="doctor" and (.jsonSchemas|index("kg.ios.doctor.v1")) and (.jsonSchemas|index("kg.ios.sentry.v1")) and .sideEffect=="read-only") and any(.commands[]; .key=="issues" and .delegate=="./ops/ios_diagnostics.py" and (.jsonSchemas|index("kg.ios.diagnostics.v1"))) and any(.commands[]; .key=="gate" and (.aliases|index("verdict")) and (.jsonSchemas|index("kg.ios.gate.v1")) and .sideEffect=="read-only") and any(.commands[]; .key=="xcode" and (.aliases|index("environment")) and (.jsonSchemas|index("kg.ios.xcode.v1")) and .sideEffect=="read-only") and any(.commands[]; .key=="simulator" and (.aliases|index("sim")) and (.jsonSchemas|index("kg.ios.simulator.v1")) and (.sideEffect|test("local-artifact screenshot")) and (.sideEffect|test("local-simulator-lifecycle")) and (.command|test("launch")) and (.command|test("terminate")) and (.command|test("ensure-booted"))) and any(.commands[]; .key=="runs" and (.jsonSchemas|index("kg.ios.runs.v1")) and (.jsonSchemas|index("kg.ios.diagnostics.v1")) and .sideEffect=="read-only") and any(.commands[]; .key=="archive" and (.aliases|index("release")) and (.jsonSchemas|index("kg.ios.archive.v1")) and (.jsonSchemas|index("kg.ios.diagnostics.v1")) and (.command|test("--json")) and (.sideEffect|test("external-upload only with --upload"))) and any(.commands[]; .key=="commands" and (.aliases|index("capabilities")))' >/dev/null \
  && ok "commands --json exposes machine-readable command catalog" || fail_t "commands --json invalid: $commands_json"
capabilities_json="$(bash "$IOS_OPS" capabilities --json)"
echo "$capabilities_json" | jq -e '.schema=="kg.ios.commands.v1" and any(.commands[]; .key=="commands")' >/dev/null \
  && ok "capabilities alias exposes command catalog" || fail_t "capabilities --json invalid: $capabilities_json"
commands_text="$(bash "$IOS_OPS" commands)"
echo "$commands_text" | grep -q 'key=snapshot' \
  && ok "commands text lists snapshot" || fail_t "commands text missing snapshot: $commands_text"
echo "$commands_text" | grep -q 'key=catalog' \
  && ok "commands text lists catalog" || fail_t "commands text missing catalog: $commands_text"
echo "$commands_text" | grep -q 'kg.ios.commands.v1' \
  && ok "commands text lists catalog schema" || fail_t "commands text missing schema: $commands_text"

section "Xcode environment surface"
status_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" status --json)"
echo "$status_json" | jq -e '.schema=="kg.ios.status.v1" and .project.version=="1.6" and .project.build=="4" and .organizer.latest.version=="1.6" and .organizer.latest.build=="4" and (.organizer.latest.archive|contains("BooksAndVocab.xcarchive")) and .testflight.latestBuild=="3"' >/dev/null \
  && ok "status --json exposes project, Organizer, and TestFlight summary" || fail_t "status --json invalid: $status_json"
status_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" status)"
echo "$status_text" | grep -q 'project_version=1.6 project_build=4' && echo "$status_text" | grep -q 'organizer_latest=1.6(4)' && echo "$status_text" | grep -q 'testflight_latest_build=3' \
  && ok "status text reports normalized summary lines" || fail_t "status text invalid: $status_text"
xcode_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" xcode --json)"
echo "$xcode_json" | jq -e '.schema=="kg.ios.xcode.v1" and (.errors|length)==0 and .xcode.version=="16.4" and .project.scheme=="BooksAndVocab" and (.project.list.schemes|index("BooksAndVocab")) and any(.destinations.available[]; .id=="fixture-iphone-17-pro-max" and .platform=="iOS Simulator" and .name=="iPhone 17 Pro Max") and any(.destinations.ineligible[]; .id=="fixture-ineligible" and (.error|contains("OS mismatch, please download runtime"))) and all(.destinations.available[]; .id!="fixture-ineligible") and .simulators.summary.booted==1' >/dev/null \
  && ok "xcode --json exposes project destinations and simulators" || fail_t "xcode --json invalid: $xcode_json"
xcode_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" environment)"
echo "$xcode_text" | grep -q 'schema=kg.ios.xcode.v1' && echo "$xcode_text" | grep -q 'destination id=fixture-iphone-17-pro-max' \
  && ok "environment text lists xcode schema and destination" || fail_t "environment text invalid: $xcode_text"
xcode_fail_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_XCODE_FAIL_FIXTURE=1 bash "$IOS_OPS" xcode --json)"
echo "$xcode_fail_json" | jq -e '.schema=="kg.ios.xcode.v1" and (.errors|length)==4 and all(.sources[]; .status=="error") and (.destinations.available|length)==0 and .simulators.summary.total==0' >/dev/null \
  && ok "xcode --json reports source failures without breaking schema" || fail_t "xcode failure schema invalid: $xcode_fail_json"
xcode_bad_developer_json="$(DEVELOPER_DIR=/tmp/kg-missing-xcode bash "$IOS_OPS" xcode --json)"
echo "$xcode_bad_developer_json" | jq -e '.schema=="kg.ios.xcode.v1" and (.errors|length >= 1) and .sources.xcode_version.status=="error" and any(.sources[]; .status=="error")' >/dev/null \
  && ok "xcode --json reports real Xcode source failures" || fail_t "xcode bad DEVELOPER_DIR schema invalid: $xcode_bad_developer_json"

section "Simulator interaction surface"
sim_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator status --json)"
echo "$sim_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="status" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .device.state=="Booted" and .app.bundleID=="com.Max0228.BooksBrowser" and .app.container.data=="/tmp/kg-sim-fixture/container" and .app.container.status=="ok" and .app.process.status=="running" and .app.process.pid=="74736" and .sources.app_process.status=="ok" and (.timings.totalMs|type)=="number" and (.timings.simctlDevicesMs|type)=="number" and (.timings.appContainerMs|type)=="number" and (.timings.appProcessMs|type)=="number"' >/dev/null \
  && ok "simulator status --json exposes booted device, app container, and process" || fail_t "simulator status --json invalid: $sim_json"
sim_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" sim status)"
echo "$sim_text" | grep -q 'schema=kg.ios.simulator.v1' && echo "$sim_text" | grep -q 'udid=fixture-iphone-17-pro-max' && echo "$sim_text" | grep -q 'app_process status=running pid=74736' && echo "$sim_text" | grep -q 'timings totalMs=' \
  && ok "sim alias text lists booted simulator" || fail_t "sim text invalid: $sim_text"
sim_stopped_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE=1 bash "$IOS_OPS" simulator status --json)"
echo "$sim_stopped_json" | jq -e '.schema=="kg.ios.simulator.v1" and .status=="ok" and .app.process.status=="stopped" and .app.process.pid==null and .sources.app_process.exitCode==1 and (.errors|length)==0' >/dev/null \
  && ok "simulator status --json reports stopped app process without failing" || fail_t "simulator stopped app invalid: $sim_stopped_json"
sim_launch_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE=1 bash "$IOS_OPS" simulator launch --json)"
echo "$sim_launch_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="launch" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .app.bundleID=="com.Max0228.BooksBrowser" and .app.lifecycle.exitCode==0 and .app.lifecycle.output=="74736" and .app.process.status=="running" and .app.process.pid=="74736" and (.timings.totalMs|type)=="number" and (.timings.statusMs|type)=="number" and (.timings.lifecycleMs|type)=="number" and (.timings.appProcessMs|type)=="number"' >/dev/null \
  && ok "simulator launch --json starts installed app and refreshes process state" || fail_t "simulator launch invalid: $sim_launch_json"
sim_launch_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" sim launch)"
echo "$sim_launch_text" | grep -q 'action=launch status=ok' && echo "$sim_launch_text" | grep -q 'app_process status=running pid=74736' && echo "$sim_launch_text" | grep -q 'timings totalMs=' \
  && ok "simulator launch text reports process state" || fail_t "simulator launch text invalid: $sim_launch_text"
sim_terminate_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator terminate --json)"
echo "$sim_terminate_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="terminate" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .app.bundleID=="com.Max0228.BooksBrowser" and .app.lifecycle.exitCode==0 and .app.process.status=="stopped" and .app.process.pid==null and (.timings.totalMs|type)=="number" and (.timings.statusMs|type)=="number" and (.timings.lifecycleMs|type)=="number" and (.timings.appProcessMs|type)=="number"' >/dev/null \
  && ok "simulator terminate --json stops installed app and refreshes process state" || fail_t "simulator terminate invalid: $sim_terminate_json"
sim_ensure_booted_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_NO_BOOTED_FIXTURE=1 bash "$IOS_OPS" simulator ensure-booted --json)"
echo "$sim_ensure_booted_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="ensure-booted" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .device.state=="Booted" and .boot.status=="ok" and .boot.exitCode==0 and .boot.wasAlreadyBooted==false and .boot.waitedForBootstatus==true and (.timings.totalMs|type)=="number" and (.timings.resolveMs|type)=="number" and (.timings.bootMs|type)=="number" and (.timings.bootstatusMs|type)=="number"' >/dev/null \
  && ok "simulator ensure-booted --json boots the default simulator when none are booted" || fail_t "simulator ensure-booted invalid: $sim_ensure_booted_json"
sim_ensure_booted_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator ensure-booted)"
echo "$sim_ensure_booted_text" | grep -q 'action=ensure-booted status=ok' && echo "$sim_ensure_booted_text" | grep -q 'wasAlreadyBooted=true' && echo "$sim_ensure_booted_text" | grep -q 'timings totalMs=' \
  && ok "simulator ensure-booted text reports warm-boot reuse" || fail_t "simulator ensure-booted text invalid: $sim_ensure_booted_text"
sim_shot_tmp="$(mktemp -d)"
sim_shot="$sim_shot_tmp/screenshot with spaces.png"
sim_shot_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator screenshot --out "$sim_shot" --json)"
echo "$sim_shot_json" | jq -e --arg path "$sim_shot" '.schema=="kg.ios.simulator.v1" and .action=="screenshot" and .status=="ok" and .artifact.path==$path and .artifact.exists==true and .artifact.bytes > 0 and .device.udid=="fixture-iphone-17-pro-max"' >/dev/null \
  && [[ -s "$sim_shot" ]] \
  && ok "simulator screenshot --json creates local artifact" || fail_t "simulator screenshot invalid: $sim_shot_json"
echo "$sim_shot_json" | jq -e '(.timings.totalMs|type)=="number" and (.timings.statusMs|type)=="number" and (.timings.screenshotMs|type)=="number"' >/dev/null \
  && ok "simulator screenshot --json exposes timing breakdown" || fail_t "simulator screenshot timings invalid: $sim_shot_json"
sim_shot_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator screenshot --out "$sim_shot_tmp/text.png")"
echo "$sim_shot_text" | grep -q 'artifact=' && echo "$sim_shot_text" | grep -q 'text.png' && echo "$sim_shot_text" | grep -q 'timings totalMs=' \
  && ok "simulator screenshot text reports artifact path" || fail_t "simulator screenshot text invalid: $sim_shot_text"
if KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator screenshot --out /dev/null/kg-shot.png --json >"$sim_shot_tmp/bad_parent.json" 2>"$sim_shot_tmp/bad_parent.err"; then
  fail_t "simulator screenshot reports unwritable parent as JSON error"
else
  rc=$?
  jq -e '.schema=="kg.ios.simulator.v1" and .action=="screenshot" and .status=="error" and .artifact.path=="/dev/null/kg-shot.png" and .artifact.exists==false and any(.errors[]; .key=="screenshot")' "$sim_shot_tmp/bad_parent.json" >/dev/null \
    && [[ "$rc" -ne 0 ]] \
    && ok "simulator screenshot reports unwritable parent as JSON error" || fail_t "simulator screenshot bad-parent invalid: $(cat "$sim_shot_tmp/bad_parent.json") stderr=$(cat "$sim_shot_tmp/bad_parent.err") rc=$rc"
fi
if KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_NO_BOOTED_FIXTURE=1 bash "$IOS_OPS" simulator status --json >"$sim_shot_tmp/no_booted.json" 2>"$sim_shot_tmp/no_booted.err"; then
  fail_t "simulator status reports missing booted device"
else
  rc=$?
  jq -e '.schema=="kg.ios.simulator.v1" and .action=="status" and .status=="error" and .device==null and any(.errors[]; .key=="booted-device")' "$sim_shot_tmp/no_booted.json" >/dev/null \
    && [[ "$rc" -eq 1 ]] \
    && ok "simulator status reports missing booted device" || fail_t "simulator missing-booted invalid: $(cat "$sim_shot_tmp/no_booted.json") stderr=$(cat "$sim_shot_tmp/no_booted.err") rc=$rc"
fi
sim_lease_tmp="$(mktemp -d)"
live_owner_pid=""
sleep 30 &
live_owner_pid=$!
lease_dir="$sim_lease_tmp/kg-pool-1"
mkdir -p "$lease_dir"
printf '%s\n' "$(( $(date +%s) - 120 ))" > "$lease_dir/created_at"
printf '%s\n' "$live_owner_pid" > "$lease_dir/owner_pid"
printf '%s\n' "fixture-udid" > "$lease_dir/udid"
printf '%s\n' "fixture-token" > "$lease_dir/owner_token"
lease_stale_status="$(
  ROOT="$WORKSPACE" KG_IOS_SIM_LEASE_ROOT="$sim_lease_tmp" KG_IOS_SIM_LEASE_TTL=1 \
    bash -lc 'source "'"$IOS_OPS_SIMULATOR_LIB"'"; if simulator_lease_is_stale "'"$lease_dir"'"; then echo stale; else echo live; fi'
)"
[[ "$lease_stale_status" == "live" ]] \
  && ok "simulator lease keeps live owner pid from stale reclaim" || fail_t "simulator lease stale-check ignored live owner pid: $lease_stale_status"
release_token_mismatch_json="$(
  ROOT="$WORKSPACE" KG_IOS_SIM_LEASE_ROOT="$sim_lease_tmp" \
    bash -lc 'source "'"$IOS_OPS_SIMULATOR_LIB"'"; cmd_simulator_release --device fixture-udid --owner-token wrong-token --json'
)"
echo "$release_token_mismatch_json" | jq -e '.schema=="kg.ios.sim-release.v1" and .status=="noop" and .error=="owner-token-mismatch:fixture-udid"' >/dev/null \
  && [[ -d "$lease_dir" ]] \
  && ok "simulator release refuses mismatched owner token" || fail_t "simulator release token mismatch invalid: $release_token_mismatch_json"
release_token_match_json="$(
  ROOT="$WORKSPACE" KG_IOS_SIM_LEASE_ROOT="$sim_lease_tmp" \
    bash -lc 'source "'"$IOS_OPS_SIMULATOR_LIB"'"; cmd_simulator_release --device fixture-udid --owner-token fixture-token --json'
)"
echo "$release_token_match_json" | jq -e '.schema=="kg.ios.sim-release.v1" and .status=="ok" and .udid=="fixture-udid"' >/dev/null \
  && [[ ! -d "$lease_dir" ]] \
  && ok "simulator release deletes lease only for matching owner token" || fail_t "simulator release token match invalid: $release_token_match_json"
kill "$live_owner_pid" 2>/dev/null || true
wait "$live_owner_pid" 2>/dev/null || true
rm -rf "$sim_lease_tmp"
rm -rf "$sim_shot_tmp"

section "Catalog snapshot export surface"
catalog_tmp="$(mktemp -d)"
catalog_xctestrun_tmp="$(mktemp -d)"
mkdir -p "$catalog_xctestrun_tmp/Build/Products"
touch "$catalog_xctestrun_tmp/Build/Products/BooksAndVocabCatalogSnapshots_BooksAndVocabCatalogSnapshots_iphonesimulator26.4-arm64.xctestrun"
touch "$catalog_xctestrun_tmp/Build/Products/BooksAndVocabCatalogSnapshots_BooksAndVocabCatalogSnapshots_iphonesimulator26.4-arm64.scoped.xctestrun"
catalog_xctestrun_path="$(
  ROOT="$WORKSPACE" \
  XCODEPROJ="$WORKSPACE/ios/BooksAndVocab.xcodeproj" \
  bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_find_xctestrun "'"$catalog_xctestrun_tmp"'"'
)"
[[ "$catalog_xctestrun_path" == *.xctestrun && "$catalog_xctestrun_path" != *.scoped.xctestrun ]] \
  && ok "catalog scoped cache prefers base xctestrun over scoped copy" || fail_t "catalog scoped cache selected wrong xctestrun: $catalog_xctestrun_path"
catalog_cache_root="$catalog_tmp/cache-root"
prepare_catalog_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_CACHE_ROOT="$catalog_cache_root" bash "$IOS_OPS" catalog prepare --json)"
echo "$prepare_catalog_json" | jq -e --arg root "$catalog_cache_root" '.schema=="kg.ios.catalog.prepare.v1" and .action=="prepare" and .status=="ok" and (.cache.root|startswith($root)) and (.cache.key|length > 8) and .cache.productsReady==true and (.cache.xctestrunPath|endswith(".xctestrun")) and .cache.status=="prepared" and (.build.command|contains("build-for-testing")) and .build.exitCode==0' >/dev/null \
  && ok "catalog prepare --json seeds reusable build cache" || fail_t "catalog prepare --json invalid: $prepare_catalog_json"
echo "$prepare_catalog_json" | jq -e '(.build.wallMs|type)=="number" and .build.wallMs >= 0' >/dev/null \
  && ok "catalog prepare --json exposes build wall time" || fail_t "catalog prepare timing invalid: $prepare_catalog_json"
prepare_xctestrun="$(echo "$prepare_catalog_json" | jq -r '.cache.xctestrunPath')"
[[ -f "$prepare_xctestrun" ]] \
  && ok "catalog prepare materializes xctestrun artifact" || fail_t "catalog prepare missing xctestrun: $prepare_xctestrun"
dataset_fixture_json="$catalog_tmp/dataset.json"
cat >"$dataset_fixture_json" <<'JSON'
{"schema":"kg.fixture.dataset.v1","datasetID":"fixture-catalog-test"}
JSON
dataset_fixture_b64="$(base64 <"$dataset_fixture_json" | tr -d '\n')"
dataset_scoped_xctestrun="$catalog_tmp/dataset.scoped.xctestrun"
ROOT="$WORKSPACE" XCODEPROJ="$WORKSPACE/ios/BooksAndVocab.xcodeproj" \
  bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_prepare_scoped_xctestrun "'"$prepare_xctestrun"'" "" "" "'"$dataset_fixture_b64"'" "'"$dataset_scoped_xctestrun"'"'
[[ "$(plutil -extract 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_FIXTURE_DATASET_B64' raw -o - "$dataset_scoped_xctestrun")" == "$dataset_fixture_b64" ]] \
  && [[ "$(plutil -extract 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_FIXTURE_DATASET_B64' raw -o - "$dataset_scoped_xctestrun")" == "$dataset_fixture_b64" ]] \
  && ok "catalog scoped xctestrun embeds fixture dataset env" || fail_t "catalog scoped xctestrun missing fixture dataset env"
prepare_catalog_hit_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_CACHE_ROOT="$catalog_cache_root" bash "$IOS_OPS" catalog prepare --json)"
echo "$prepare_catalog_hit_json" | jq -e '.schema=="kg.ios.catalog.prepare.v1" and .status=="ok" and .cache.status=="hit" and .build.exitCode==0' >/dev/null \
  && ok "catalog prepare reuses ready cache without rebuilding" || fail_t "catalog prepare hit invalid: $prepare_catalog_hit_json"
catalog_persist_root="$catalog_tmp/workspace-snapshots"
catalog_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_PERSIST_ROOT="$catalog_persist_root" TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json)"
echo "$catalog_json" | jq -e --arg root "$catalog_tmp/build/snapshots" --arg persistRoot "$catalog_persist_root" '.schema=="kg.ios.catalog.v1" and .action=="snapshots" and .status=="ok" and .mode=="fixture" and .artifacts.root==$root and .artifacts.pngCount==2 and (.artifacts.paths|length)==2 and (.scope.groups|length)==0 and (.scope.scenarios|length)==0 and all(.artifacts.paths[]; startswith($root)) and (.validation.status=="ok") and .validation.actualPngCount==2 and .validation.uniformImageCount==0 and .validation.transparentImageCount==0 and .validation.minPixelWidth==16 and .validation.maxPixelWidth==16 and .validation.minPixelHeight==16 and .validation.maxPixelHeight==16 and (.validation.images|length)==2 and (.validation.transparentImages|length)==0 and (.validation.warnings|length)==0 and .cache.status=="not-applicable" and .cache.key==null and .cache.root==null and (.test.command|contains("CatalogSnapshotTests")) and .test.exitCode==0 and .copy.exitCode==0 and .copy.containerDataPath=="/tmp/kg-sim-fixture/container" and .review.status=="ok" and (.review.reviewHtml|endswith("/UIreview.html")) and (.review.reviewManifest|endswith("/review_manifest.json")) and (.review.reviewState|endswith("/review_state.json")) and .workspaceArtifact.status=="ok" and (.workspaceArtifact.root==$persistRoot) and (.workspaceArtifact.name|startswith("catalog-full-")) and (.workspaceArtifact.artifactRoot|startswith($persistRoot)) and (.workspaceArtifact.reviewHtml|endswith("/UIreview.html")) and (.workspaceArtifact.reviewManifest|endswith("/review_manifest.json")) and (.workspaceArtifact.reviewState|endswith("/review_state.json")) and .flags.compileTimeFlag=="KG_RUN_CATALOG_SNAPSHOTS"' >/dev/null \
  && ok "catalog snapshots --json exports fixture PNG artifacts" || fail_t "catalog snapshots --json invalid: $catalog_json"
[[ -f "$(echo "$catalog_json" | jq -r '.review.reviewHtml')" ]] && [[ -f "$(echo "$catalog_json" | jq -r '.review.reviewManifest')" ]] && [[ -f "$(echo "$catalog_json" | jq -r '.review.reviewState')" ]] \
  && ok "catalog snapshots auto-generates review sidecar" || fail_t "catalog review sidecar missing: $catalog_json"
[[ -f "$(echo "$catalog_json" | jq -r '.workspaceArtifact.reviewHtml')" ]] && [[ -f "$(echo "$catalog_json" | jq -r '.workspaceArtifact.reviewManifest')" ]] && [[ -f "$(echo "$catalog_json" | jq -r '.workspaceArtifact.reviewState')" ]] \
  && ok "catalog snapshots persists full review artifact into workspace snapshot root" || fail_t "catalog workspace artifact missing: $catalog_json"
echo "$catalog_json" | jq -e '(.timings.wrapperWallMs|type)=="number" and .timings.wrapperWallMs >= 0 and (.timings.commandWallMs|type)=="number" and .timings.commandWallMs >= 0 and (.timings.testBodyMs|type)=="number" and .timings.testBodyMs >= 0 and (.timings.playbookBuildMs|type)=="number" and .timings.playbookBuildMs >= 0 and (.timings.snapshotRunMs|type)=="number" and .timings.snapshotRunMs >= 0 and (.timings.startupOverheadMs|type)=="number" and .timings.startupOverheadMs >= 0 and (.timings.simulatorStatusMs|type)=="number" and .timings.simulatorStatusMs >= 0 and (.timings.containerLookupMs|type)=="number" and .timings.containerLookupMs >= 0 and (.timings.copyMs|type)=="number" and .timings.copyMs >= 0 and (.timings.artifactIndexMs|type)=="number" and .timings.artifactIndexMs >= 0 and (.timings.validationMs|type)=="number" and .timings.validationMs >= 0' >/dev/null \
  && ok "catalog snapshots --json exposes timing breakdown" || fail_t "catalog snapshots timing invalid: $catalog_json"
catalog_text="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots)"
echo "$catalog_text" | grep -q '\[ios\]\[catalog\].*status=ok.*pngCount=2' && echo "$catalog_text" | grep -q 'validation status=ok' && echo "$catalog_text" | grep -q 'review status=ok' && echo "$catalog_text" | grep -q 'CatalogSnapshotTests' \
  && ok "catalog snapshots text reports artifact summary" || fail_t "catalog snapshots text invalid: $catalog_text"
scoped_catalog_json="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --group Bookshelf --group 'Today Review' --scenario 'Today Review/Front' --json)"
echo "$scoped_catalog_json" | jq -e '.schema=="kg.ios.catalog.v1" and (.scope.groups==["Bookshelf","Today Review"]) and (.scope.scenarios==["Today Review/Front"]) and (.validation.status=="ok") and .validation.actualPngCount==2 and .cache.status=="not-applicable" and (.test.command|contains("-scheme BooksAndVocabCatalogSnapshots")) and (.test.command|contains("build-for-testing")) and (.test.command|contains("test-without-building")) and (.test.command|contains("-xctestrun"))' >/dev/null \
  && ok "catalog snapshots --json reports scoped group/scenario filters" || fail_t "catalog scoped json invalid: $scoped_catalog_json"
dataset_catalog_json="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --dataset-file "$dataset_fixture_json" --json)"
echo "$dataset_catalog_json" | jq -e --arg path "$dataset_fixture_json" '.schema=="kg.ios.catalog.v1" and .status=="ok" and .dataset.requestedPath==$path and .dataset.status=="not-applicable"' >/dev/null \
  && ok "catalog snapshots accepts dataset-file option" || fail_t "catalog dataset-file json invalid: $dataset_catalog_json"
reuse_catalog_json="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --reuse-build --json)"
echo "$reuse_catalog_json" | jq -e '.schema=="kg.ios.catalog.v1" and .status=="ok" and .options.reuseBuild==true and .test.exitCode==0' >/dev/null \
  && ok "catalog snapshots accepts reuse-build option" || fail_t "catalog reuse-build json invalid: $reuse_catalog_json"
clean_catalog_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_CACHE_ROOT="$catalog_cache_root" bash "$IOS_OPS" catalog clean --json)"
echo "$clean_catalog_json" | jq -e --arg root "$catalog_cache_root" '.schema=="kg.ios.catalog.clean.v1" and .action=="clean" and .status=="ok" and .cache.root==$root and .cache.existedBefore==true and .cache.existsAfter==false and .cache.removed==true' >/dev/null \
  && ok "catalog clean --json removes reusable build cache" || fail_t "catalog clean --json invalid: $clean_catalog_json"
[[ ! -e "$catalog_cache_root" ]] \
  && ok "catalog clean removes cache root from disk" || fail_t "catalog clean left cache root behind: $catalog_cache_root"
bad_catalog_tmp="$(mktemp -d)"
if KG_IOS_OPS_FIXTURE=1 TMPDIR="$bad_catalog_tmp" bash "$IOS_OPS" catalog snapshots --unknown >"$bad_catalog_tmp/out" 2>"$bad_catalog_tmp/err"; then
  fail_t "catalog snapshots rejects unknown option"
else
  grep -q 'unknown catalog snapshots option' "$bad_catalog_tmp/err" \
    && ok "catalog snapshots rejects unknown option" || fail_t "catalog snapshots bad-arg message missing"
fi
if KG_IOS_OPS_FIXTURE=1 TMPDIR="$bad_catalog_tmp" bash "$IOS_OPS" catalog snapshots --dataset missing-dataset >"$bad_catalog_tmp/out2" 2>"$bad_catalog_tmp/err2"; then
  fail_t "catalog snapshots rejects missing named dataset"
else
  grep -q 'dataset file not found' "$bad_catalog_tmp/err2" \
    && ok "catalog snapshots rejects missing named dataset" || fail_t "catalog missing dataset message invalid: $(cat "$bad_catalog_tmp/err2")"
fi
if KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" catalog prepare --unknown >"$bad_catalog_tmp/prepare.out" 2>"$bad_catalog_tmp/prepare.err"; then
  fail_t "catalog prepare rejects unknown option"
else
  grep -q 'unknown catalog prepare option' "$bad_catalog_tmp/prepare.err" \
    && ok "catalog prepare rejects unknown option" || fail_t "catalog prepare bad-arg message missing"
fi
cachemiss_err="$catalog_tmp/cm.err"
cachemiss_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_FIXTURE_EXIT=87 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --reuse-build --json 2>"$cachemiss_err" || true)"
echo "$cachemiss_json" | jq -e '.schema=="kg.ios.catalog.v1" and .status=="cache-miss" and .test.exitCode==87 and .cache.status=="miss" and (any(.errors[]; .key=="catalog-cache" and .error=="reuse-build-cache-miss" and (.hint|test("catalog prepare")))) and (all(.errors[]; .error!="xcodebuild-test-failed"))' >/dev/null \
  && ok "catalog snapshots exitCode 87 surfaces cache-miss (not generic test-failure)" || fail_t "catalog cache-miss signal wrong: $cachemiss_json"
grep -q 'phase=cache miss' "$cachemiss_err" \
  && ok "catalog cache-miss emits human-readable stderr hint" || fail_t "catalog cache-miss stderr hint missing: $(cat "$cachemiss_err")"
salvage_err="$catalog_tmp/sv.err"
salvage_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_FIXTURE_EXIT=65 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json 2>"$salvage_err" || true)"
echo "$salvage_json" | jq -e '.schema=="kg.ios.catalog.v1" and .status=="error" and .test.exitCode==65 and .artifacts.containerPngCount==2 and .artifacts.pngCount==2 and .copy.salvaged==true and .copy.exitCode==0 and (any(.errors[]; .key=="catalog-salvage" and .status=="info" and .pngCount==2 and .containerPngCount==2)) and (all(.errors[]; .key!="catalog-copy"))' >/dev/null \
  && ok "catalog snapshots salvages container PNGs when test fails (distinguishes generated-but-not-copied)" || fail_t "catalog salvage failed: $salvage_json"
grep -q 'phase=salvage recovered' "$salvage_err" \
  && ok "catalog salvage emits stderr recovery notice" || fail_t "catalog salvage stderr missing: $(cat "$salvage_err")"
salvage_text="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_FIXTURE_EXIT=65 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots 2>/dev/null || true)"
echo "$salvage_text" | grep -q 'note key=catalog-salvage' && ! echo "$salvage_text" | grep -q 'error key=catalog-salvage' \
  && ok "catalog salvage info renders as note (not error) in text output" || fail_t "catalog salvage text mislabeled: $salvage_text"
ok_json="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json 2>/dev/null)"
echo "$ok_json" | jq -e '.status=="ok" and .copy.salvaged==false and .artifacts.containerPngCount==2 and (all(.errors[]; .key!="catalog-salvage"))' >/dev/null \
  && ok "catalog snapshots success path keeps salvaged=false and no salvage error" || fail_t "catalog success salvage regression: $ok_json"
uniform_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_FIXTURE_UNIFORM=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json 2>/dev/null)"
echo "$uniform_json" | jq -e '.schema=="kg.ios.catalog.v1" and .status=="warn" and .validation.status=="warn" and .validation.uniformImageCount==2 and (.validation.warnings==["uniform-image-detected"]) and (any(.warnings[]; .key=="catalog-validation" and .warning=="uniform-image-detected")) and .test.exitCode==0 and .artifacts.pngCount==2 and .review.status=="ok"' >/dev/null \
  && ok "catalog snapshots treats uniform-image-detected as warning (not fatal error)" || fail_t "catalog uniform warning invalid: $uniform_json"
uniform_text="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_FIXTURE_UNIFORM=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots 2>/dev/null || true)"
echo "$uniform_text" | grep -q '\[ios\]\[catalog\].*status=warn.*pngCount=2' && echo "$uniform_text" | grep -q 'warn key=catalog-validation' \
  && ok "catalog text surfaces validation warnings distinctly from errors" || fail_t "catalog uniform text invalid: $uniform_text"
# --- multi-device validation: expectedPng must scale with device variant count ---
variant_log="$catalog_tmp/variant.log"
printf ' - resolved.deviceVariantCount: 4\n' >"$variant_log"
variant_count="$(ROOT="$WORKSPACE" bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_extract_device_variant_count_from_log "'"$variant_log"'"')"
[[ "$variant_count" == "4" ]] \
  && ok "catalog log parser extracts resolved.deviceVariantCount" || fail_t "deviceVariantCount parse wrong: $variant_count"
variant_empty_dir="$(mktemp -d)"
variant_json="$(ROOT="$WORKSPACE" bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_inspect_pngs_json "'"$variant_empty_dir"'" 3 4')"
echo "$variant_json" | jq -e '.expectedPngCount==12' >/dev/null \
  && ok "catalog validation scales expectedPng by device variant count (3 scenarios x 4 variants)" || fail_t "variant-aware expectedPng wrong: $variant_json"
variant_default_json="$(ROOT="$WORKSPACE" bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_inspect_pngs_json "'"$variant_empty_dir"'" 3')"
echo "$variant_default_json" | jq -e '.expectedPngCount==6' >/dev/null \
  && ok "catalog validation defaults to 2 appearance variants when count absent (legacy logs)" || fail_t "legacy expectedPng default wrong: $variant_default_json"
transparent_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_FIXTURE_TRANSPARENT=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json 2>/dev/null || true)"
echo "$transparent_json" | jq -e '.schema=="kg.ios.catalog.v1" and .status=="error" and .validation.status=="error" and .validation.uniformImageCount==2 and .validation.transparentImageCount==2 and (.validation.transparentImages|length)==2 and (any(.validation.errors[]; .=="fully-transparent-image-detected")) and (any(.errors[]; .key=="catalog-validation" and .error=="fully-transparent-image-detected")) and .review.status=="ok"' >/dev/null \
  && ok "catalog snapshots treats fully transparent images as fatal validation error" || fail_t "catalog transparent validation invalid: $transparent_json"
hb_log="$catalog_tmp/hb.log"; hb_err="$catalog_tmp/hb.err"; hb_cap="$catalog_tmp/hb.cap"
hb_stdout="$(ROOT="$WORKSPACE" bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_run_xcodebuild_heartbeat "build-for-testing" "'"$hb_log"'" "'"$hb_err"'" 0 -- bash -c "echo building-stdout; exit 0"' 2>"$hb_cap")"
grep -q 'phase=build-for-testing start' "$hb_cap" && grep -q 'phase=build-for-testing done exitCode=0' "$hb_cap" \
  && ok "catalog heartbeat emits phase milestones to stderr" || fail_t "catalog heartbeat missing phase milestones: $(cat "$hb_cap")"
grep -q 'building-stdout' "$hb_log" && [[ -z "$hb_stdout" ]] \
  && ok "catalog heartbeat keeps stdout clean (command output to log, phases to stderr)" || fail_t "catalog heartbeat polluted stdout: '$hb_stdout'"
hb_tick_log="$catalog_tmp/hb_tick.log"; hb_tick_err="$catalog_tmp/hb_tick.err"; hb_tick_cap="$catalog_tmp/hb_tick.cap"
hb_tick_stdout="$(ROOT="$WORKSPACE" KG_IOS_OPS_CATALOG_HEARTBEAT_SEC=99 KG_IOS_OPS_CATALOG_TICK_SEC=1 bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_run_xcodebuild_heartbeat "build-for-testing" "'"$hb_tick_log"'" "'"$hb_tick_err"'" 0 -- bash -c "sleep 3; echo tick-stdout; exit 0"' 2>"$hb_tick_cap")"
grep -q 'phase=build-for-testing tick ' "$hb_tick_cap" \
  && ok "catalog heartbeat emits short keep-alive ticks before detail heartbeat" || fail_t "catalog heartbeat missing short tick: $(cat "$hb_tick_cap")"
grep -q 'tick-stdout' "$hb_tick_log" && [[ -z "$hb_tick_stdout" ]] \
  && ok "catalog heartbeat ticks keep stdout clean" || fail_t "catalog tick polluted stdout: '$hb_tick_stdout'"
hb_rc=0
ROOT="$WORKSPACE" bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_run_xcodebuild_heartbeat "full-test" "'"$hb_log"'" "'"$hb_err"'" 0 -- bash -c "exit 87"' 2>"$hb_cap" || hb_rc=$?
[[ "$hb_rc" -eq 87 ]] && grep -q 'phase=full-test done exitCode=87' "$hb_cap" \
  && ok "catalog heartbeat propagates real exit code" || fail_t "catalog heartbeat lost exit code: rc=$hb_rc cap=$(cat "$hb_cap")"
catalog_stderr_cap="$catalog_tmp/snap.stderr"
catalog_json_clean="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json 2>"$catalog_stderr_cap")"
echo "$catalog_json_clean" | jq -e '.schema=="kg.ios.catalog.v1"' >/dev/null \
  && ok "catalog snapshots --json stdout remains single valid JSON despite stderr observability" || fail_t "catalog snapshots stdout not clean JSON: $catalog_json_clean"
rm -rf "$catalog_tmp" "$catalog_xctestrun_tmp" "$bad_catalog_tmp"

section "UITest video archive surface"
IOS_TEST_VIDEO_ARCHIVE_LIB="$WORKSPACE/ops/lib/ios_test_video_archive.sh"
[[ -f "$IOS_TEST_VIDEO_ARCHIVE_LIB" ]] && ok "ios_test_video_archive.sh exists" || fail_t "ios_test_video_archive.sh missing"
bash -n "$IOS_TEST_VIDEO_ARCHIVE_LIB" 2>/dev/null && ok "ios_test_video_archive.sh syntax" || fail_t "ios_test_video_archive.sh syntax"
grep -q 'source "$SCRIPT_DIR/lib/ios_test_video_archive.sh"' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test sources video archive lib" || fail_t "ios_test does not source video archive lib"
# Archive must run after the recording is finalized (post contact sheet) and
# before any verdict write, so artifacts.uiVideo points at the stable copy.
awk '/^build_ui_step_contact_sheet$/{cs=NR} /^archive_ui_test_recording$/{ar=NR} /write_json_verdict "/{if (!v) v=NR} END{exit (cs && ar && v && cs<ar && ar<v) ? 0 : 1}' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test archives recording after contact sheet and before verdict writes" || fail_t "archive_ui_test_recording call missing or misordered"
va_tmp="$(mktemp -d)"
va_dest="$va_tmp/uitest-videos"
printf 'fake-mp4-bytes' >"$va_tmp/run_recording.mp4"
va_path="$(bash -lc 'source "'"$IOS_TEST_VIDEO_ARCHIVE_LIB"'"; uitest_video_archive "'"$va_tmp"'/run_recording.mp4" "'"$va_dest"'" ui test-caller 20260611-120000')"
[[ "$va_path" == "$va_dest/20260611-120000-ui.mp4" && -s "$va_path" && ! -e "$va_tmp/run_recording.mp4" ]] \
  && ok "archive moves recording to timestamped dest and echoes path" || fail_t "archive basic move wrong: path=$va_path"
jq -e '.schema=="kg.ios.uitest-videos.v1" and (.videos|length)==1 and .videos[0].file=="20260611-120000-ui.mp4" and .videos[0].scope=="ui" and .videos[0].caller=="test-caller" and .videos[0].sizeBytes>0' "$va_dest/index.json" >/dev/null \
  && ok "archive writes index.json entry with metadata" || fail_t "archive index wrong: $(cat "$va_dest/index.json" 2>/dev/null)"
printf 'fake-mp4-bytes-2' >"$va_tmp/run_recording.mp4"
va_path2="$(bash -lc 'source "'"$IOS_TEST_VIDEO_ARCHIVE_LIB"'"; uitest_video_archive "'"$va_tmp"'/run_recording.mp4" "'"$va_dest"'" ui test-caller 20260611-120000')"
[[ "$va_path2" == "$va_dest/20260611-120000-ui-2.mp4" && -s "$va_path2" ]] \
  && ok "archive disambiguates same-timestamp collisions" || fail_t "archive collision handling wrong: $va_path2"
jq -e '(.videos|length)==2 and .videos[0].file=="20260611-120000-ui-2.mp4"' "$va_dest/index.json" >/dev/null \
  && ok "archive index keeps newest-first ordering" || fail_t "archive index ordering wrong: $(cat "$va_dest/index.json")"
printf 'fake-mp4-bytes-3' >"$va_tmp/run_recording.mp4"
va_path3="$(bash -lc 'source "'"$IOS_TEST_VIDEO_ARCHIVE_LIB"'"; KG_UITEST_VIDEO_KEEP=2 uitest_video_archive "'"$va_tmp"'/run_recording.mp4" "'"$va_dest"'" all test-caller 20260611-130000')"
[[ -s "$va_path3" && ! -e "$va_dest/20260611-120000-ui.mp4" ]] \
  && ok "archive prunes oldest beyond KG_UITEST_VIDEO_KEEP" || fail_t "archive prune wrong: kept=$(ls "$va_dest")"
jq -e '(.videos|length)==2 and .videos[0].file=="20260611-130000-all.mp4" and .videos[1].file=="20260611-120000-ui-2.mp4"' "$va_dest/index.json" >/dev/null \
  && ok "archive prune drops pruned entries from index" || fail_t "archive prune index wrong: $(cat "$va_dest/index.json")"
va_noop="$(bash -lc 'source "'"$IOS_TEST_VIDEO_ARCHIVE_LIB"'"; uitest_video_archive "'"$va_tmp"'/missing.mp4" "'"$va_tmp"'/never-created" ui test-caller 20260611-140000')" || fail_t "archive no-op should return 0"
[[ -z "$va_noop" && ! -e "$va_tmp/never-created" ]] \
  && ok "archive is a no-op for missing/empty recordings" || fail_t "archive no-op created artifacts: '$va_noop'"
rm -rf "$va_tmp"

section "Doctor release readiness surface"
doctor_body="$(awk '/^doctor_readiness\(\)/,/^}/' "$IOS_OPS_RELEASE_LIB")"
for key in project organizer testflight asc_version signing storekit sentry; do
  grep -q "\"$key\"" <<<"$doctor_body" \
    && ok "doctor checks $key readiness" || fail_t "doctor missing $key readiness"
done
grep -q 'cmd_doctor_json' "$IOS_OPS_RELEASE_LIB" && grep -q 'kg.ios.doctor.v1' "$IOS_OPS_RELEASE_LIB" \
  && ok "doctor exposes machine-readable JSON schema" || fail_t "doctor missing JSON schema"
grep -q 'doctor_readiness emit_readiness_json' "$IOS_OPS_RELEASE_LIB" \
  && ok "doctor JSON reuses readiness checks" || fail_t "doctor JSON does not reuse readiness checks"
grep -q 'read_asc_version_state' <<<"$doctor_body" && grep -q 'waited >= 12' "$IOS_OPS_CORE_LIB" \
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
  grep -q "\"$key\"" "$IOS_OPS_RELEASE_LIB" \
    && ok "workflow includes $key step" || fail_t "workflow missing $key step"
done
grep -q 'cmd_workflow_release_json' "$IOS_OPS_RELEASE_LIB" && grep -q 'kg.ios.workflow.v1' "$IOS_OPS_RELEASE_LIB" \
  && ok "workflow exposes machine-readable JSON schema" || fail_t "workflow missing JSON schema"
grep -q 'emit_workflow_step_json' "$IOS_OPS_RELEASE_LIB" \
  && ok "workflow JSON emits structured steps" || fail_t "workflow JSON missing structured step emitter"
grep -q 'write_workflow_release_steps_json' "$IOS_OPS_RELEASE_LIB" \
  && ok "workflow step generation is centralized" || fail_t "workflow missing shared step generator"
grep -q './ops/ios_ops.sh test --all-targets --timeout 1200' "$IOS_OPS_RELEASE_LIB" \
  && ok "workflow includes all-targets test gate" || fail_t "workflow missing all-targets test command"
grep -q './ops/asc_text_bundle.py dump -o asc.json' "$IOS_OPS_RELEASE_LIB" \
  && ok "workflow includes ASC text bundle review" || fail_t "workflow missing asc_text_bundle dump"
grep -q 'ASC GUI' "$IOS_OPS_RELEASE_LIB" \
  && ok "workflow marks submit as GUI/manual" || fail_t "workflow missing GUI submit boundary"
grep -qE 'xcodebuild (archive|build|test)|altool --upload-app' "$IOS_OPS_RELEASE_LIB" \
  && fail_t "workflow contains direct Xcode side-effect path" \
  || ok "workflow stays orchestration/read-only"

section "Release gate surface"
gate_pass_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" gate release --json)"
echo "$gate_pass_json" | jq -e '.schema=="kg.ios.gate.v1" and .name=="release" and .verdict=="pass" and .exitCode==0 and .summary.blocks==0 and (.todos|length >= 1) and (.manual|length == 1)' >/dev/null \
  && ok "gate release --json emits pass verdict" || fail_t "gate release pass invalid: $gate_pass_json"
gate_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" gate release)"
echo "$gate_text" | grep -q 'verdict=pass' \
  && ok "gate release text emits verdict" || fail_t "gate release text missing verdict: $gate_text"
gate_warn_tmp="$(mktemp -d)"
if KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_FIXTURE_TF_LATEST=unknown bash "$IOS_OPS" gate release --json >"$gate_warn_tmp/out" 2>"$gate_warn_tmp/err"; then
  fail_t "gate release warns on unknown TestFlight build"
else
  rc=$?
  jq -e '.schema=="kg.ios.gate.v1" and .verdict=="warn" and .exitCode==1 and .summary.warnings >= 1 and any(.warnings[]; .key=="testflight")' "$gate_warn_tmp/out" >/dev/null \
    && [[ "$rc" -eq 1 ]] \
    && ok "gate release warns on unknown TestFlight build" || fail_t "gate release warn invalid: $(cat "$gate_warn_tmp/out") stderr=$(cat "$gate_warn_tmp/err") rc=$rc"
fi
rm -rf "$gate_warn_tmp"
gate_block_tmp="$(mktemp -d)"
if KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_FIXTURE_TF_LATEST=4 bash "$IOS_OPS" gate release --json >"$gate_block_tmp/out" 2>"$gate_block_tmp/err"; then
  fail_t "gate release blocks duplicate TestFlight build"
else
  rc=$?
  jq -e '.schema=="kg.ios.gate.v1" and .verdict=="block" and .exitCode==2 and .summary.blocks >= 1 and any(.blocks[]; .key=="testflight")' "$gate_block_tmp/out" >/dev/null \
    && [[ "$rc" -eq 2 ]] \
    && ok "gate release blocks duplicate TestFlight build" || fail_t "gate release block invalid: $(cat "$gate_block_tmp/out") stderr=$(cat "$gate_block_tmp/err") rc=$rc"
fi
rm -rf "$gate_block_tmp"

section "Sentry wiring surface"
sentry_json="$(bash "$IOS_OPS" sentry --json)"
echo "$sentry_json" | jq -e '.schema=="kg.ios.sentry.v1" and .source.path=="'"$WORKSPACE"'/ios/BooksAndVocab/Services/AppCrashReporting.swift" and .source.exists==true and (.wiring.canImportGuard|type)=="boolean" and (.wiring.dsnKeyReference|type)=="boolean" and .debug.requiresEnv=="SENTRY_ENABLED_IN_DEBUG=1" and .debug.testArgument=="-sentryTest" and .release.name=="bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION" and .release.dist=="CURRENT_PROJECT_VERSION"' >/dev/null \
  && ok "sentry --json exposes machine-readable wiring summary" || fail_t "sentry --json invalid: $sentry_json"
sentry_text="$(bash "$IOS_OPS" sentry)"
echo "$sentry_text" | grep -q '\[ios\]\[sentry\] source=' && echo "$sentry_text" | grep -q 'can_import_guard=' && echo "$sentry_text" | grep -q 'debug_requires_env=' && echo "$sentry_text" | grep -q 'release_name=' \
  && ok "sentry text reports wiring summary" || fail_t "sentry text invalid: $sentry_text"
sentry_warn_json="$(KG_IOS_OPS_SENTRY_SOURCE_FIXTURE=/tmp/kg-missing-sentry.swift KG_IOS_OPS_SENTRY_SOURCE_EXISTS_FIXTURE=0 KG_IOS_OPS_SENTRY_CAN_IMPORT_FIXTURE=0 KG_IOS_OPS_SENTRY_DSN_FIXTURE=0 bash "$IOS_OPS" sentry --json)"
echo "$sentry_warn_json" | jq -e '.schema=="kg.ios.sentry.v1" and .source.path=="/tmp/kg-missing-sentry.swift" and .source.exists==false and .wiring.canImportGuard==false and .wiring.dsnKeyReference==false' >/dev/null \
  && ok "sentry --json supports fixture-driven warning surface" || fail_t "sentry warning fixture invalid: $sentry_warn_json"
echo "$sentry_warn_json" | jq -e '(.issues|type)=="array" and (.issues|length)==3 and (.issues|map(.key)|sort)==["canImportGuard","dsnKeyReference","source"] and all(.issues[]; (.message|length)>0 and (.command|test("sentry --json")))' >/dev/null \
  && ok "sentry --json issues[] is single source of wiring failures" || fail_t "sentry issues invalid: $sentry_warn_json"
echo "$sentry_json" | jq -e '(.issues|type)=="array" and (.issues|length)==0' >/dev/null \
  && ok "sentry --json issues[] empty when wiring healthy" || fail_t "sentry healthy issues invalid: $sentry_json"

section "Runtime log surface"
logs_json="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --json --since 1m --limit 1)"
echo "$logs_json" | jq -e '.schema=="kg.ios.logs.v1" and .since=="1m" and .limit==1 and .summary.rawCount==3 and .summary.filteredCount==1 and .summary.emittedCount==1 and .summary.byEventType.logEvent==1 and (.entries|length)==1 and .entries[0].message=="sync completed"' >/dev/null \
  && ok "logs --json emits filtered runtime log schema" || fail_t "logs --json invalid: $logs_json"
logs_sim_json="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --json --simulator --device TEST-UDID --debug --since 1m --limit 1)"
echo "$logs_sim_json" | jq -e '.schema=="kg.ios.logs.v1" and (.source|contains("xcrun simctl spawn TEST-UDID log show --debug --info --style ndjson")) and .summary.emittedCount==1' >/dev/null \
  && ok "logs --json exposes simulator debug source" || fail_t "logs --json simulator debug source invalid: $logs_sim_json"
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

# logs --follow (live stream) fixtures
follow_text="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --follow 2>/dev/null)"
echo "$follow_text" | grep -q 'sync completed' && echo "$follow_text" | grep -q 'reader opened' \
  && ok "logs --follow streams app entries" || fail_t "logs --follow missing app entries: $follow_text"
echo "$follow_text" | grep -q 'RBSServiceErrorDomain' \
  && fail_t "logs --follow failed to filter framework noise: $follow_text" || ok "logs --follow filters framework noise"
follow_limit_text="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --follow --limit 1 2>/dev/null)"
[[ "$(echo "$follow_limit_text" | grep -c .)" -eq 1 ]] && echo "$follow_limit_text" | grep -q 'sync completed' \
  && ok "logs --follow honors --limit" || fail_t "logs --follow limit invalid: $follow_limit_text"
follow_json="$(KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" logs --follow --json --limit 1 2>/dev/null)"
echo "$follow_json" | jq -e '.schema=="kg.ios.log-stream.v1" and .message=="sync completed" and .category=="sync"' >/dev/null \
  && ok "logs --follow --json emits ndjson entries" || fail_t "logs --follow --json invalid: $follow_json"
follow_fail_tmp="$(mktemp -d)"
if KG_IOS_OPS_LOG_FAIL_FIXTURE=1 bash "$IOS_OPS" logs --follow >"$follow_fail_tmp/out" 2>"$follow_fail_tmp/err"; then
  fail_t "logs --follow propagates stream failure"
else
  grep -q 'fixture log failure' "$follow_fail_tmp/err" \
    && ok "logs --follow propagates stream failure" || fail_t "logs --follow failure stderr missing"
fi
rm -rf "$follow_fail_tmp"
# real SIGPIPE(141) path: unbounded producer + --limit stop gate must exit 0 with N lines
stream_text="$(KG_IOS_OPS_LOG_STREAM_FIXTURE=1 bash "$IOS_OPS" logs --follow --limit 1 2>/dev/null)"; stream_rc=$?
[[ "$stream_rc" -eq 0 && "$(echo "$stream_text" | grep -c .)" -eq 1 ]] && echo "$stream_text" | grep -q 'sync completed' \
  && ok "logs --follow handles producer SIGPIPE at limit (text)" || fail_t "logs --follow SIGPIPE text rc=$stream_rc out=$stream_text"
stream_json="$(KG_IOS_OPS_LOG_STREAM_FIXTURE=1 bash "$IOS_OPS" logs --follow --json --limit 1 2>/dev/null)"; stream_json_rc=$?
[[ "$stream_json_rc" -eq 0 ]] && echo "$stream_json" | jq -e '.schema=="kg.ios.log-stream.v1" and .message=="sync completed"' >/dev/null \
  && ok "logs --follow handles producer SIGPIPE at limit (json)" || fail_t "logs --follow SIGPIPE json rc=$stream_json_rc out=$stream_json"
# pipefail must not leak out of the sourceable follow helpers
leak_check="$(set -o pipefail; source "$IOS_OPS_LOGS_LIB"; KG_IOS_OPS_LOG_STREAM_FIXTURE=1 cmd_logs_follow_text 'p' 1 >/dev/null 2>&1; if set -o | grep -q 'pipefail.*on'; then echo intact; else echo leaked; fi)"
[[ "$leak_check" == "intact" ]] \
  && ok "logs --follow does not leak pipefail to caller" || fail_t "logs --follow leaked pipefail: $leak_check"

section "JSON smoke fixtures"
delegate_tmp="$(mktemp -d)"
cat > "$delegate_tmp/build_stub.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
verdict="${TMPDIR:-/tmp}/kg_ios_build_verdict"
json="$verdict.json"
printf 'RESULT=ok EXIT=0 caller=stub-build elapsed=1s log=%s/build.log xcresult=%s/Build.xcresult\n' "${TMPDIR:-/tmp}" "${TMPDIR:-/tmp}" >"$verdict"
mkdir -p "${TMPDIR:-/tmp}/Build.xcresult"
: > "${TMPDIR:-/tmp}/build.log"
jq -nc --arg log "${TMPDIR:-/tmp}/build.log" --arg xcresult "${TMPDIR:-/tmp}/Build.xcresult" '{schema:"kg.ios.run-verdict.v1",kind:"build",status:"ok",result:"ok",exit:"0",reason:null,caller:"stub-build",elapsed:"1s",executed:null,timings:{bootMs:11,xcodebuildMs:22,totalMs:33},artifacts:{log:$log,xcresult:$xcresult}}' >"$json"
echo "build stub stdout"
SH
cat > "$delegate_tmp/test_stub.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if printf '%s\n' "$@" | grep -qx -- '--cache-status'; then
  jq -nc '{schema:"kg.ios.test-cache.v1",scope:"unit",status:"ok",cache:{status:"hit"}}'
  exit 0
fi
verdict="${TMPDIR:-/tmp}/kg_ios_test_verdict"
json="$verdict.json"
printf 'RESULT=ok EXIT=0 caller=stub-test elapsed=2s executed=7 log=%s/test.log xcresult=%s/Test.xcresult\n' "${TMPDIR:-/tmp}" "${TMPDIR:-/tmp}" >"$verdict"
mkdir -p "${TMPDIR:-/tmp}/Test.xcresult"
: > "${TMPDIR:-/tmp}/test.log"
mkdir -p "${TMPDIR:-/tmp}/ui-steps"
: > "${TMPDIR:-/tmp}/ui-steps/contact_sheet.png"
: > "${TMPDIR:-/tmp}/ui-steps/quick4_contact_sheet.png"
: > "${TMPDIR:-/tmp}/ui-steps/review_manifest.json"
: > "${TMPDIR:-/tmp}/ui-steps/run_recording.mp4"
jq -nc --arg log "${TMPDIR:-/tmp}/test.log" --arg xcresult "${TMPDIR:-/tmp}/Test.xcresult" --arg sheet "${TMPDIR:-/tmp}/ui-steps/contact_sheet.png" --arg quick4 "${TMPDIR:-/tmp}/ui-steps/quick4_contact_sheet.png" --arg manifest "${TMPDIR:-/tmp}/ui-steps/review_manifest.json" --arg screenshotDir "${TMPDIR:-/tmp}/ui-steps" --arg video "${TMPDIR:-/tmp}/ui-steps/run_recording.mp4" --arg device "STUB-UDID-1234" '{schema:"kg.ios.run-verdict.v1",kind:"test",status:"ok",result:"ok",exit:"0",reason:null,caller:"stub-test",elapsed:"2s",executed:"7",device:$device,options:{uiLaunchProfile:"standard"},cache:{status:"hit"},timings:{bootMs:44,buildForTestingMs:0,testInvocationMs:55,testBodyMs:21,xcresultSessionMs:34,xcresultHarnessOverheadMs:13,appLaunchAverageMs:8,appLaunchSamples:5,invocationOverheadMs:21,xcodebuildMs:55,totalMs:99},artifacts:{log:$log,xcresult:$xcresult,uiContactSheet:$sheet,uiQuick4Sheet:$quick4,uiVisualReviewManifest:$manifest,uiScreenshotDir:$screenshotDir,uiVideo:$video}}' >"$json"
echo "test stub stdout"
SH
cat > "$delegate_tmp/archive_stub.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
verdict="${TMPDIR:-/tmp}/kg_ios_archive_verdict"
json="$verdict.json"
mkdir -p "${TMPDIR:-/tmp}/Archive.xcresult" "${TMPDIR:-/tmp}/export"
: > "${TMPDIR:-/tmp}/archive.log"
: > "${TMPDIR:-/tmp}/export/BooksAndVocab.ipa"
printf 'RESULT=ok EXIT=0 caller=stub-archive archive=%s/BooksAndVocab.xcarchive log=%s/archive.log xcresult=%s/Archive.xcresult\n' "${TMPDIR:-/tmp}" "${TMPDIR:-/tmp}" "${TMPDIR:-/tmp}" >"$verdict"
jq -nc --arg archive "${TMPDIR:-/tmp}/BooksAndVocab.xcarchive" --arg log "${TMPDIR:-/tmp}/archive.log" --arg xcresult "${TMPDIR:-/tmp}/Archive.xcresult" --arg exportDir "${TMPDIR:-/tmp}/export" --arg ipa "${TMPDIR:-/tmp}/export/BooksAndVocab.ipa" '{schema:"kg.ios.archive.v1",status:"ok",exit:"0",caller:"stub-archive",options:{keyId:"TCXVHFRXMS",uploadRequested:false},archive:{status:"ok",elapsed:"12s",path:$archive,log:$log,xcresult:$xcresult},export:{status:"ok",directory:$exportDir,ipa:$ipa},upload:{status:"skipped",requested:false,completed:false}}' >"$json"
echo "archive stub stdout"
SH
chmod +x "$delegate_tmp/build_stub.sh" "$delegate_tmp/test_stub.sh" "$delegate_tmp/archive_stub.sh"
build_direct_json="$(TMPDIR="$delegate_tmp" KG_IOS_BUILD_DELEGATE="$delegate_tmp/build_stub.sh" bash "$IOS_OPS" build --json 2>"$delegate_tmp/build_stderr")"
echo "$build_direct_json" | jq -e '.schema=="kg.ios.run.v1" and .kind=="build" and .result=="ok" and .caller=="stub-build" and .timings.totalMs==33 and .uiVisualReview==null and .diagnostics.schema=="kg.ios.diagnostics.v1"' >/dev/null \
  && ok "build --json emits machine-readable run report" || fail_t "build --json invalid: $build_direct_json"
grep -q 'build stub stdout' "$delegate_tmp/build_stderr" \
  && ok "build --json redirects delegate stdout to stderr" || fail_t "build --json missing delegate output forwarding"
test_direct_json="$(TMPDIR="$delegate_tmp" KG_IOS_TEST_DELEGATE="$delegate_tmp/test_stub.sh" bash "$IOS_OPS" test --json 2>"$delegate_tmp/test_stderr")"
echo "$test_direct_json" | jq -e '.schema=="kg.ios.run.v1" and .kind=="test" and .result=="ok" and .executed=="7" and .cache.status=="hit" and .timings.appLaunchAverageMs==8 and .artifacts.uiContactSheetExists==true and .artifacts.uiQuick4SheetExists==true and .artifacts.uiVisualReviewManifestExists==true and .artifacts.uiVideoExists==true and .device=="STUB-UDID-1234" and .diagnostics.schema=="kg.ios.diagnostics.v1"' >/dev/null \
  && ok "test --json emits machine-readable run report" || fail_t "test --json invalid: $test_direct_json"
echo "$test_direct_json" | jq -e '.uiVisualReview.contactSheet==.artifacts.uiContactSheet and .uiVisualReview.contactSheetExists==true and .uiVisualReview.quick4Sheet==.artifacts.uiQuick4Sheet and .uiVisualReview.quick4SheetExists==true and .uiVisualReview.visualReviewManifest==.artifacts.uiVisualReviewManifest and .uiVisualReview.visualReviewManifestExists==true and .uiVisualReview.screenshotDir==.artifacts.uiScreenshotDir and .uiVisualReview.video==.artifacts.uiVideo and .uiVisualReview.videoExists==true' >/dev/null \
  && ok "test --json exposes uiVisualReview block" || fail_t "test --json missing uiVisualReview block: $test_direct_json"
grep -q 'test stub stdout' "$delegate_tmp/test_stderr" \
  && ok "test --json redirects delegate stdout to stderr" || fail_t "test --json missing delegate output forwarding"
test_cache_json="$(TMPDIR="$delegate_tmp" KG_IOS_TEST_DELEGATE="$delegate_tmp/test_stub.sh" bash "$IOS_OPS" test --cache-status --json)"
echo "$test_cache_json" | jq -e '.schema=="kg.ios.test-cache.v1" and .cache.status=="hit"' >/dev/null \
  && ok "test --cache-status --json keeps native cache schema" || fail_t "test cache native json invalid: $test_cache_json"
archive_direct_json="$(TMPDIR="$delegate_tmp" KG_IOS_RELEASE_DELEGATE="$delegate_tmp/archive_stub.sh" bash "$IOS_OPS" archive --json 2>"$delegate_tmp/archive_stderr")"
echo "$archive_direct_json" | jq -e '.schema=="kg.ios.archive.v1" and .status=="ok" and .caller=="stub-archive" and .archive.status=="ok" and .archive.elapsed=="12s" and .export.status=="ok" and .upload.status=="skipped"' >/dev/null \
  && ok "archive --json emits machine-readable archive report" || fail_t "archive --json invalid: $archive_direct_json"
grep -q 'archive stub stdout' "$delegate_tmp/archive_stderr" \
  && ok "archive --json redirects delegate stdout to stderr" || fail_t "archive --json missing delegate output forwarding"
rm -rf "$delegate_tmp"

runs_parent="$(mktemp -d)"
runs_tmp="$runs_parent/with spaces"
mkdir -p "$runs_tmp"
mkdir -p "$runs_tmp/Build.xcresult" "$runs_tmp/Test.xcresult" "$runs_tmp/Archive.xcresult"
cat > "$runs_tmp/build.log" <<'LOG'
warning: StoreKit Configuration file for scheme "BooksAndVocab" can't be found at path "/tmp/missing.storekit"
** BUILD SUCCEEDED **
LOG
cat > "$runs_tmp/test.log" <<'LOG'
** TEST SUCCEEDED **
LOG
cat > "$runs_tmp/archive.log" <<'LOG'
warning: StoreKit Configuration file for scheme "BooksAndVocab" can't be found at path "/tmp/archive-missing.storekit"
** BUILD SUCCEEDED **
LOG
echo "RESULT=legacy" > "$runs_tmp/kg_ios_build_verdict"
jq -nc --arg log "$runs_tmp/build.log" --arg xcresult "$runs_tmp/Build.xcresult" \
  '{schema:"kg.ios.run-verdict.v1",kind:"build",status:"ok",result:"ok",exit:"0",reason:null,caller:"fixture with spaces",elapsed:"3s",executed:null,timings:{lockWaitMs:90,bootMs:120,xcodebuildMs:3000,totalMs:3120,probeMs:777},artifacts:{log:$log,xcresult:$xcresult}}' \
  > "$runs_tmp/kg_ios_build_verdict.json"
jq -nc --arg log "$runs_tmp/test.log" --arg xcresult "$runs_tmp/Test.xcresult" \
  '{schema:"kg.ios.run-verdict.v1",kind:"test",status:"ok",result:"ok",exit:"0",reason:null,caller:"fixture with spaces",elapsed:"5s",executed:"12",options:{uiLaunchProfile:"standard"},cache:{status:"hit"},timings:{lockWaitMs:140,bootMs:250,buildForTestingMs:0,testInvocationMs:6000,testBodyMs:2000,xcresultSessionMs:3500,xcresultHarnessOverheadMs:1500,appLaunchAverageMs:1450,appLaunchSamples:5,invocationOverheadMs:2500,xcodebuildMs:6000,totalMs:6500},artifacts:{log:$log,xcresult:$xcresult}}' \
  > "$runs_tmp/kg_ios_test_verdict.json"
jq -nc --arg log "$runs_tmp/archive.log" --arg xcresult "$runs_tmp/Archive.xcresult" --arg archive "$runs_tmp/BooksAndVocab.xcarchive" --arg exportDir "$runs_tmp/export" --arg ipa "$runs_tmp/export/BooksAndVocab.ipa" \
  '{schema:"kg.ios.archive.v1",status:"ok",exit:"0",caller:"fixture with spaces",options:{keyId:"TCXVHFRXMS",uploadRequested:false},archive:{status:"ok",elapsed:"14s",path:$archive,log:$log,xcresult:$xcresult},export:{status:"ok",directory:$exportDir,ipa:$ipa},upload:{status:"skipped",requested:false,completed:false},timings:{lockWaitMs:10,archiveMs:12000,exportMs:1500,uploadMs:0,totalMs:13510},artifacts:{log:$log,xcresult:$xcresult,archive:$archive,exportDirectory:$exportDir,ipa:$ipa}}' \
  > "$runs_tmp/kg_ios_archive_verdict.json"
runs_json="$(TMPDIR="$runs_tmp" bash "$IOS_OPS" runs --json)"
echo "$runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .summary.verdict=="warn" and .summary.counts.errors==0 and .summary.counts.warnings==2 and .summary.counts.failedTests==0 and .summary.counts.missing==0 and .summary.counts.malformed==0 and .summary.counts.failing==0 and .build.result=="ok" and .build.caller=="fixture with spaces" and .test.executed=="12" and .archive.result=="ok" and .archive.timings.totalMs==13510 and .archive.timings.archiveMs==12000 and .archive.artifacts.logExists==true and .archive.artifacts.xcresultExists==true and .build.artifacts.logExists==true and .test.artifacts.xcresultExists==true and .build.diagnostics.schema=="kg.ios.diagnostics.v1" and .archive.diagnostics.schema=="kg.ios.diagnostics.v1" and .build.diagnostics.counts.warnings==1 and .archive.diagnostics.counts.warnings==1 and .build.timings.totalMs==3120 and .build.timings.lockWaitMs==90 and .test.timings.lockWaitMs==140 and .test.cache.status=="hit" and .test.options.uiLaunchProfile=="standard" and .test.timings.appLaunchAverageMs==1450 and .test.timings.appLaunchSamples==5' >/dev/null \
  && ok "runs --json parses latest build/test/archive verdicts (incl lockWaitMs passthrough)" || fail_t "runs --json invalid: $runs_json"
echo "$runs_json" | jq -e 'all([.build,.test,.archive][]; has("kind") and has("status") and has("result") and has("exit") and has("reason") and has("caller") and has("elapsed") and has("executed") and has("device") and has("options") and has("cache") and has("timings") and has("verdictFile") and has("jsonVerdictFile") and has("artifacts") and has("uiVisualReview") and has("diagnostics"))' >/dev/null \
  && ok "runs --json uses stable verdict object keys" || fail_t "runs --json missing stable keys: $runs_json"
runs_text="$(TMPDIR="$runs_tmp" bash "$IOS_OPS" runs)"
printf '%s\n' "$runs_text" | grep -q '^\[ios\]\[runs\] summary verdict=warn errors=0 warnings=2 failedTests=0 missing=0 malformed=0 failing=0' \
  && ok "runs text reports aggregate summary" || fail_t "runs text missing summary: $runs_text"
missing_runs_tmp="$(mktemp -d)"
missing_runs_json="$(TMPDIR="$missing_runs_tmp" bash "$IOS_OPS" runs --json)"
echo "$missing_runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .summary.verdict=="unknown" and .summary.counts.missing==3 and .summary.counts.malformed==0 and .summary.counts.failing==0 and .build.status=="missing" and .build.artifacts.log==null and .build.artifacts.logExists==false and .test.result=="missing" and .archive.result=="missing"' >/dev/null \
  && ok "runs --json has stable missing-verdict schema" || fail_t "runs missing-verdict schema invalid: $missing_runs_json"
rm -rf "$missing_runs_tmp"
malformed_runs_tmp="$(mktemp -d)"
echo "RESULT=ok caller=legacy elapsed=1s log=$malformed_runs_tmp/build.log xcresult=$malformed_runs_tmp/Build.xcresult" > "$malformed_runs_tmp/kg_ios_build_verdict"
echo '{bad json' > "$malformed_runs_tmp/kg_ios_build_verdict.json"
echo '{bad json' > "$malformed_runs_tmp/kg_ios_test_verdict.json"
echo '{bad json' > "$malformed_runs_tmp/kg_ios_archive_verdict.json"
malformed_runs_json="$(TMPDIR="$malformed_runs_tmp" bash "$IOS_OPS" runs --json 2>"$malformed_runs_tmp/stderr")"
echo "$malformed_runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .summary.verdict=="block" and .summary.counts.malformed==2 and .summary.counts.failing==2 and .build.result=="ok" and .test.status=="malformed" and .test.reason=="malformed-json-verdict" and .archive.status=="malformed" and .archive.reason=="malformed-json-verdict"' >/dev/null \
  && ok "runs --json falls back or reports malformed JSON verdicts" || fail_t "runs malformed-verdict schema invalid: $malformed_runs_json"
echo "$malformed_runs_json" | jq -e 'all([.build,.test,.archive][]; has("jsonVerdictFile") and has("artifacts"))' >/dev/null \
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
echo "$doctor_json" | jq -e '.schema=="kg.ios.doctor.v1" and (.readiness|length >= 7) and any(.readiness[]; .key=="testflight") and (.summary.verdict|inside("passwarnblock")) and .summary.counts.ok >= 1 and .summary.counts.block==0 and .summary.counts.total == (.readiness|length) and (.summary.counts.ok + .summary.counts.warn + .summary.counts.block == .summary.counts.total) and .sentry.schema=="kg.ios.sentry.v1" and .sentry.source.exists==true and (.sentry.wiring.canImportGuard|type)=="boolean" and (.sentry.wiring.dsnKeyReference|type)=="boolean"' >/dev/null \
  && ok "doctor --json parses with readiness array summary and embedded sentry summary" || fail_t "doctor --json invalid: $doctor_json"
doctor_sentry_warn_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SENTRY_SOURCE_FIXTURE=/tmp/kg-missing-sentry.swift KG_IOS_OPS_SENTRY_SOURCE_EXISTS_FIXTURE=0 KG_IOS_OPS_SENTRY_CAN_IMPORT_FIXTURE=0 KG_IOS_OPS_SENTRY_DSN_FIXTURE=0 bash "$IOS_OPS" doctor --json)"
echo "$doctor_sentry_warn_json" | jq -e '.summary.verdict=="warn" and .summary.counts.warn >= 1 and .sentry.source.path=="/tmp/kg-missing-sentry.swift" and .sentry.source.exists==false and .sentry.wiring.canImportGuard==false and .sentry.wiring.dsnKeyReference==false and any(.readiness[]; .key=="sentry" and .status=="warn" and (.detail|contains("source_exists=false")) and (.detail|contains("can_import_guard=false")) and (.detail|contains("dsn_key_reference=false")))' >/dev/null \
  && ok "doctor --json reuses sentry fixture-driven warning surface" || fail_t "doctor sentry warning invalid: $doctor_sentry_warn_json"
doctor_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" doctor)"
echo "$doctor_text" | grep -Eq '^\[ios\]\[doctor\] summary verdict=(pass|warn|block) ok=' \
  && ok "doctor text reports readiness summary" || fail_t "doctor text missing summary: $doctor_text"
workflow_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" workflow release --json)"
echo "$workflow_json" | jq -e '.schema=="kg.ios.workflow.v1" and (.summary.verdict|inside("passwarnblock")) and .summary.counts.ready >= 1 and .summary.counts.todo >= 1 and .summary.counts.manual == 1 and (.summary.counts.ready + .summary.counts.todo + .summary.counts.block + .summary.counts.warn + .summary.counts.manual == .summary.counts.total) and .summary.counts.total == (.steps|length) and (.steps|length == 8) and any(.steps[]; .key=="upload")' >/dev/null \
  && ok "workflow release --json parses with steps array" || fail_t "workflow release --json invalid: $workflow_json"
workflow_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" workflow release)"
echo "$workflow_text" | grep -Eq '^\[ios\]\[workflow\] summary verdict=(pass|warn|block) ready=' \
  && ok "workflow text reports aggregate summary" || fail_t "workflow text missing summary: $workflow_text"
snapshot_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json)"
echo "$snapshot_json" | jq -e '.schema=="kg.ios.snapshot.v1" and (.readiness|length >= 7) and (.workflow.steps|length == 8) and .gate.schema=="kg.ios.gate.v1" and .gate.verdict=="pass" and .gate.exitCode==0 and .summary.verdict=="warn" and .summary.counts.readinessOk==([.readiness[] | select(.status=="ok")] | length) and .summary.counts.readinessWarns==([.readiness[] | select(.status=="warn")] | length) and .summary.counts.readinessBlocks==([.readiness[] | select(.status=="block")] | length) and .summary.counts.workflowReady==.workflow.summary.counts.ready and .summary.counts.workflowTodos==.workflow.summary.counts.todo and .summary.counts.workflowWarns==.workflow.summary.counts.warn and .summary.counts.workflowBlocks==.workflow.summary.counts.block and .summary.counts.workflowManual==.workflow.summary.counts.manual and .summary.counts.buildWarnings==1 and .summary.counts.archiveWarnings==1 and .summary.counts.sentryWarnings==0 and .summary.timings.build.totalMs==3120 and .summary.timings.build.lockWaitMs==90 and .summary.timings.build.probeMs==777 and .summary.timings.test.lockWaitMs==140 and .summary.timings.test.cacheStatus=="hit" and .summary.timings.test.appLaunchAverageMs==1450 and .summary.timings.test.appLaunchSamples==5 and .summary.timings.archive.totalMs==13510 and .summary.timings.archive.archiveMs==12000 and (.summary.timings.simulator.totalMs|type)=="number" and (.summary.timings.simulator.simctlDevicesMs|type)=="number" and (.summary.timings.simulator.appContainerMs|type)=="number" and (.summary.timings.simulator.appProcessMs|type)=="number" and any(.summary.nextActions[]; .source=="runs.build.diagnostics" and .severity=="warn" and .category=="storekit" and (.message|contains("StoreKit Configuration"))) and any(.summary.nextActions[]; .source=="runs.archive.diagnostics" and .severity=="warn" and .category=="storekit" and (.message|contains("StoreKit Configuration"))) and any(.summary.nextActions[]; .source=="gate" and .severity=="manual" and .key=="submit") and .sentry.schema=="kg.ios.sentry.v1" and .sentry.source.exists==true and .sentry.wiring.canImportGuard==true and .sentry.wiring.dsnKeyReference==true and .xcode.schema=="kg.ios.xcode.v1" and .xcode.simulators.summary.booted==1 and .simulator.schema=="kg.ios.simulator.v1" and .simulator.app.process.status=="running" and .project.version=="1.6" and .runs.test.executed=="12" and .runs.archive.result=="ok" and .runs.archive.diagnostics.counts.warnings==1 and .logs==null' >/dev/null \
  && ok "snapshot --json combines readiness and workflow" || fail_t "snapshot --json invalid: $snapshot_json"

# Verdict three-tier consistency contract. The "blocks>0 -> block; elif warns>0
# -> warn; else pass" rule is deliberately NOT extracted into a shared helper
# (doctor/workflow/gate/snapshot inputs are heterogeneous; runs adds a justified
# 'unknown' branch — extracting would force a fragile cross-file jq def for a
# 3-line rule). Instead this contract locks the 3 count-based surfaces against a
# single canonical rule so any drift (e.g. swapping warn/block precedence) fails.
verdict_rule='def rule($b;$w): if $b>0 then "block" elif $w>0 then "warn" else "pass" end;'
echo "$doctor_json" | jq -e "$verdict_rule"' .summary.verdict == rule(.summary.counts.block; .summary.counts.warn)' >/dev/null \
  && ok "doctor verdict follows canonical three-tier rule" || fail_t "doctor verdict drifted: $doctor_json"
echo "$workflow_json" | jq -e "$verdict_rule"' .summary.verdict == rule(.summary.counts.block; .summary.counts.warn)' >/dev/null \
  && ok "workflow verdict follows canonical three-tier rule" || fail_t "workflow verdict drifted: $workflow_json"
echo "$snapshot_json" | jq -e "$verdict_rule"' .gate.verdict == rule(.gate.summary.blocks; .gate.summary.warnings)' >/dev/null \
  && ok "gate verdict follows canonical three-tier rule" || fail_t "gate verdict drifted: $snapshot_json"
snapshot_skip_xcode_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json --skip-xcode)"
echo "$snapshot_skip_xcode_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and .sentry.schema=="kg.ios.sentry.v1" and .xcode==null and .simulator.schema=="kg.ios.simulator.v1" and .runs.test.executed=="12"' >/dev/null \
  && ok "snapshot --json can skip xcode inventory" || fail_t "snapshot --json --skip-xcode invalid: $snapshot_skip_xcode_json"
snapshot_skip_simulator_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json --skip-simulator)"
echo "$snapshot_skip_simulator_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and .sentry.schema=="kg.ios.sentry.v1" and .xcode.schema=="kg.ios.xcode.v1" and .simulator==null and .runs.test.executed=="12"' >/dev/null \
  && ok "snapshot --json can skip simulator status" || fail_t "snapshot --json --skip-simulator invalid: $snapshot_skip_simulator_json"
snapshot_no_booted_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_NO_BOOTED_FIXTURE=1 bash "$IOS_OPS" snapshot --json)"
echo "$snapshot_no_booted_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and .sentry.schema=="kg.ios.sentry.v1" and any(.summary.nextActions[]; .source=="simulator" and .severity=="warn" and .key=="booted-device") and .simulator.schema=="kg.ios.simulator.v1" and .simulator.status=="error" and any(.simulator.errors[]; .key=="booted-device") and .runs.test.executed=="12"' >/dev/null \
  && ok "snapshot --json embeds simulator error without failing" || fail_t "snapshot no-booted simulator invalid: $snapshot_no_booted_json"
snapshot_sentry_warn_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SENTRY_SOURCE_FIXTURE=/tmp/kg-missing-sentry.swift KG_IOS_OPS_SENTRY_SOURCE_EXISTS_FIXTURE=0 KG_IOS_OPS_SENTRY_CAN_IMPORT_FIXTURE=0 KG_IOS_OPS_SENTRY_DSN_FIXTURE=0 bash "$IOS_OPS" snapshot --json --skip-xcode --skip-simulator)"
echo "$snapshot_sentry_warn_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and .summary.counts.sentryWarnings==3 and .summary.counts.sentryWarnings==(.sentry.issues|length) and (.sentry.issues|map(.key)|sort)==["canImportGuard","dsnKeyReference","source"] and any(.summary.nextActions[]; .source=="sentry" and .key=="source" and .severity=="warn") and any(.summary.nextActions[]; .source=="sentry" and .key=="canImportGuard" and .severity=="warn") and any(.summary.nextActions[]; .source=="sentry" and .key=="dsnKeyReference" and .severity=="warn") and .sentry.source.exists==false and .sentry.wiring.canImportGuard==false and .sentry.wiring.dsnKeyReference==false' >/dev/null \
  && ok "snapshot --json surfaces sentry wiring drift as warnings" || fail_t "snapshot sentry warning invalid: $snapshot_sentry_warn_json"
snapshot_logs_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" snapshot --json --include-logs --log-since 1m --log-limit 1)"
echo "$snapshot_logs_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.counts.runtimeLogs==1 and .sentry.schema=="kg.ios.sentry.v1" and .simulator.schema=="kg.ios.simulator.v1" and .logs.schema=="kg.ios.logs.v1" and .logs.since=="1m" and .logs.limit==1 and .logs.summary.filteredCount==1 and (.logs.entries|length)==1' >/dev/null \
  && ok "snapshot --json can include runtime logs" || fail_t "snapshot --json logs invalid: $snapshot_logs_json"
snapshot_text="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --skip-xcode --skip-simulator)"
printf '%s\n' "$snapshot_text" | sed -n '1p' | grep -q '^\[ios\]\[summary\].*verdict=warn.*readinessWarns=.*workflowManual=1.*buildWarnings=1.*sentryWarnings=0' \
  && ok "snapshot text starts with summary verdict" || fail_t "snapshot text first line missing summary: $snapshot_text"
printf '%s\n' "$snapshot_text" | sed -n '2p' | grep -q '^\[ios\]\[timing\] build cacheStatus=n/a totalMs=3120 bootMs=120 xcodebuildMs=3000' \
  && ok "snapshot text prints build timing line" || fail_t "snapshot text missing build timing line: $snapshot_text"
printf '%s\n' "$snapshot_text" | sed -n '3p' | grep -q '^\[ios\]\[timing\] test cacheStatus=hit totalMs=6500 bootMs=250 buildForTestingMs=0 testInvocationMs=6000 testBodyMs=2000 xcresultSessionMs=3500 appLaunchAverageMs=1450 appLaunchSamples=5 invocationOverheadMs=2500' \
  && ok "snapshot text prints test timing line" || fail_t "snapshot text missing test timing line: $snapshot_text"
printf '%s\n' "$snapshot_text" | sed -n '4p' | grep -q '^\[ios\]\[timing\] archive totalMs=13510 lockWaitMs=10 archiveMs=12000 exportMs=1500 uploadMs=0' \
  && ok "snapshot text prints archive timing line" || fail_t "snapshot text missing archive timing line: $snapshot_text"
printf '%s\n' "$snapshot_text" | sed -n '5p' | grep -q '^\[ios\]\[timing\] simulator totalMs=n/a simctlDevicesMs=n/a appContainerMs=n/a appProcessMs=n/a' \
  && ok "snapshot text prints simulator timing line when simulator is skipped" || fail_t "snapshot text missing simulator timing line: $snapshot_text"
echo "$snapshot_text" | grep -q '\[ios\]\[next\].*source=runs.build.diagnostics.*severity=warn.*category=storekit' \
  && ok "snapshot text lists next actions" || fail_t "snapshot text missing next action: $snapshot_text"
echo "$snapshot_text" | grep -q '\[ios\]\[next\].*source=gate.*severity=manual.*key=submit' \
  && ok "snapshot text surfaces manual workflow action" || fail_t "snapshot text missing manual action: $snapshot_text"
echo "$snapshot_text" | grep -q '\[ios\]\[snapshot\] sentry sourceExists=true canImportGuard=true dsnKeyReference=true' \
  && ok "snapshot text reports sentry wiring summary" || fail_t "snapshot text missing sentry summary: $snapshot_text"
echo "$snapshot_text" | grep -q 'phase=doctor' \
  && fail_t "snapshot text should not start with phase dump: $snapshot_text" || ok "snapshot text avoids phase dump"
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
archive="$tmp/2026-06-07/BooksAndVocab 2026-6-7, 1.00 PM.xcarchive"
mkdir -p "$archive"
cat > "$archive/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Name</key><string>BooksAndVocab</string>
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
grep -q 'simulator ensure-booted' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build warms simulator before xcodebuild when targeting simulator" || fail_t "ios_build missing simulator preboot"
grep -q 'lockWaitMs:' "$WORKSPACE/ops/ios_build.sh" \
  && grep -q 'bootMs:' "$WORKSPACE/ops/ios_build.sh" \
  && grep -q 'xcodebuildMs:' "$WORKSPACE/ops/ios_build.sh" \
  && grep -q 'totalMs:' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build verdict records timing breakdown (incl lock wait)" || fail_t "ios_build verdict missing timing fields"
grep -qE 'lockWaitMs=\$LOCK_WAIT_MS' "$WORKSPACE/ops/ios_build.sh" \
  && ok "ios_build surfaces lock wait time on stdout" || fail_t "ios_build does not surface lock wait on stdout"
monitor_probe="$(
  perl -e 'alarm 5; exec @ARGV' bash -lc '
    source "'"$WORKSPACE"'/ops/lib/ios_build_progress.sh"
    log="$(mktemp "${TMPDIR:-/tmp}/kg_ios_monitor_probe.XXXXXX.log")"
    baseline="$(mktemp "${TMPDIR:-/tmp}/kg_ios_monitor_probe.XXXXXX.baseline")"
    pid="$(start_build_monitor "$log" "$baseline" "[probe]" "$(date +%s)")"
    printf "pid=%s\n" "$pid"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  ' 2>/dev/null
)"
echo "$monitor_probe" | grep -qE '^pid=[0-9]+$' \
  && ok "ios_build progress monitor returns PID from command substitution" || fail_t "ios_build progress monitor command substitution hung/failed: $monitor_probe"

section "ios_test emits xcresult-first diagnostics"
grep -q -- '-resultBundlePath' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test emits xcresult bundle" || fail_t "ios_test missing -resultBundlePath"
grep -q 'simulator ensure-booted' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test warms simulator before xcodebuild" || fail_t "ios_test missing simulator preboot"
grep -q -- '--kind test' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test reads xcresult test-results" || fail_t "ios_test missing --kind test diagnostics"
grep -q 'count_executed_tests_xcresult' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test counts executed tests from xcresult first" || fail_t "ios_test missing xcresult executed-count path"
grep -q 'effectiveTests' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test treats skipped-only xcresult summaries as non-executed" || fail_t "ios_test still counts skipped-only summaries as executed"
grep -q "head -20 || true" "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test failure summary cannot abort verdict writing" || fail_t "ios_test failure summary can abort before verdict"
grep -q 'emit_ui_runner_lifecycle' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q '\[ios_test\]\[ui-lifecycle\]' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'screenshot=' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test emits UI runner lifecycle diagnostics on abnormal UI outcomes" || fail_t "ios_test missing UI runner lifecycle diagnostics"
grep -q 'KG_UI_TEST_SCREENSHOT_DIR' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'catalog_contact_sheet.py' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test captures UI step screenshots into a contact sheet" || fail_t "ios_test missing UI step contact sheet capture"
grep -q 'xcresulttool' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'export attachments' "$WORKSPACE/ops/ios_test.sh" \
  && grep -Fq 'Step ([0-9]{2}-' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test falls back to xcresult step attachments" || fail_t "ios_test missing xcresult step attachment fallback"
prepare_def_line="$(grep -n '^prepare_ui_step_screenshot_dir()' "$WORKSPACE/ops/ios_test.sh" | cut -d: -f1 | head -1)"
prepare_call_line="$(grep -n '^[[:space:]]*prepare_ui_step_screenshot_dir$' "$WORKSPACE/ops/ios_test.sh" | cut -d: -f1 | head -1)"
[[ -n "$prepare_def_line" && -n "$prepare_call_line" && "$prepare_def_line" -lt "$prepare_call_line" ]] \
  && ok "ios_test defines UI step helper before first use" || fail_t "ios_test UI step helper order invalid"
grep -q 'test-without-building' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'build-for-testing' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test supports cache-first xctestrun reuse path" || fail_t "ios_test missing reuse-build path"
grep -q 'ensure_xctestrun_ready_or_fail' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test guards missing xctestrun artifacts before test-without-building" || fail_t "ios_test missing xctestrun readiness guard"
# Functional regression: fake UI step screenshots must yield the full visual
# review trio — full contact sheet + quick4 sheet + selection manifest — and
# generated sheets must never re-enter the manifest as fake steps.
ui_steps_tmp="$(mktemp -d)"
ui_step_png_b64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
for ui_step_name in 01-launch 02-bookshelf 03-series-detail 04-episode-list 05-player-open 06-play-tapped 07-playback-started 08-playback-sustained; do
  printf '%s' "$ui_step_png_b64" | base64 -d >"$ui_steps_tmp/$ui_step_name.png"
done
bash -c '
  set -euo pipefail
  SCRIPT_DIR="'"$WORKSPACE"'/ops"
  UI_TEST_SCREENSHOT_DIR="'"$ui_steps_tmp"'"
  UI_TEST_CONTACT_SHEET=""
  UI_TEST_QUICK4_SHEET=""
  UI_TEST_SCREENSHOT_MANIFEST=""
  export_ui_step_attachments_from_xcresult() { :; }
  eval "$(sed -n "/^build_ui_step_contact_sheet()/,/^}/p" "$SCRIPT_DIR/ios_test.sh")"
  build_ui_step_contact_sheet
' >"$ui_steps_tmp/snippet.log" 2>&1 || true
if [[ -s "$ui_steps_tmp/contact_sheet.png" && -s "$ui_steps_tmp/quick4_contact_sheet.png" && -s "$ui_steps_tmp/review_manifest.json" ]] \
  && jq -e '.schema=="kg.visual-review.sheet.v1" and (.items|length)==8 and all(.items[]; (.relPath|test("contact_sheet"))|not)' "$ui_steps_tmp/review_manifest.json" >/dev/null; then
  ok "ios_test builds full + quick4 contact sheets and manifest from step screenshots"
  rm -rf "$ui_steps_tmp"
else
  # keep $ui_steps_tmp as the debug artifact — the failure message points at it
  fail_t "ios_test ui-step visual review trio missing in $ui_steps_tmp: $(tail -3 "$ui_steps_tmp/snippet.log" 2>/dev/null | tr '\n' ' ')"
fi
ios_test_xctestrun_tmp="$(mktemp -d)"
mkdir -p "$ios_test_xctestrun_tmp/Build/Products"
touch "$ios_test_xctestrun_tmp/Build/Products/BooksAndVocabUnitTests_BooksAndVocabUnitTests_iphonesimulator26.4-arm64.xctestrun"
touch "$ios_test_xctestrun_tmp/Build/Products/BooksAndVocabUnitTests_BooksAndVocabUnitTests_iphonesimulator26.4-arm64.scoped.xctestrun"
ios_test_xctestrun_path="$(
  bash -lc '
    eval "$(sed -n '"'"'/^ios_test_find_xctestrun()/,/^}/p'"'"' "'"$WORKSPACE/ops/ios_test.sh"'")"
    ios_test_find_xctestrun "'"$ios_test_xctestrun_tmp"'"
  '
)"
[[ "$ios_test_xctestrun_path" == *.xctestrun && "$ios_test_xctestrun_path" != *.scoped.xctestrun ]] \
  && ok "ios_test xctestrun lookup prefers base artifact over scoped copy" || fail_t "ios_test xctestrun lookup selected wrong artifact: $ios_test_xctestrun_path"
rm -rf "$ios_test_xctestrun_tmp"
grep -q 'BooksAndVocabUnitTests' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test uses unit-only scheme for default scope" || fail_t "ios_test missing unit-only scheme"
grep -q 'lockWaitMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -qE 'lockWaitMs=\$LOCK_WAIT_MS' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test verdict records lock wait time and surfaces it on stdout" || fail_t "ios_test missing lock wait timing"
grep -q 'BooksAndVocabUITests' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test uses dedicated UI scheme for UI scope" || fail_t "ios_test missing UI-only scheme"
grep -q 'deviceRunLockWaitMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'acquire_test_device_lock' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test records per-device execution lock timing" || fail_t "ios_test missing per-device execution lock timing"
ios_test_isolation_required="$(
  PROJECT_ROOT="/tmp/.codex/worktrees/91de/kg" \
  DESTINATION="platform=iOS Simulator,name=iPhone 17 Pro Max" \
  DEVICE_OVERRIDE="" \
  DESTINATION_OVERRIDE="" \
  AUTO_LEASE=0 \
  LIST_ONLY=0 \
  TEST_CACHE_ACTION="" \
  KG_IOS_TEST_ALLOW_SHARED_SIM=0 \
  CI="" \
  WORKTREE_BRANCH="" \
    bash -lc '
      eval "$(sed -n "/^destination_requires_device_lock()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^env_flag_enabled()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^running_in_isolation_enforced_context()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^should_require_isolated_simulator()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      if should_require_isolated_simulator; then echo require; else echo allow; fi
    '
)"
[[ "$ios_test_isolation_required" == "require" ]] \
  && ok "ios_test requires --lease/--device in agent worktree context" || fail_t "ios_test did not require isolated simulator in agent context: $ios_test_isolation_required"
ios_test_isolation_autolease="$(
  PROJECT_ROOT="/tmp/.codex/worktrees/91de/kg" \
  DESTINATION="platform=iOS Simulator,name=iPhone 17 Pro Max" \
  DEVICE_OVERRIDE="" \
  DESTINATION_OVERRIDE="" \
  AUTO_LEASE=1 \
  LIST_ONLY=0 \
  TEST_CACHE_ACTION="" \
  KG_IOS_TEST_ALLOW_SHARED_SIM=0 \
  CI="" \
  WORKTREE_BRANCH="" \
    bash -lc '
      eval "$(sed -n "/^destination_requires_device_lock()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^env_flag_enabled()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^running_in_isolation_enforced_context()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^should_require_isolated_simulator()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      if should_require_isolated_simulator; then echo require; else echo allow; fi
    '
)"
[[ "$ios_test_isolation_autolease" == "allow" ]] \
  && ok "ios_test skips isolation guard when auto-lease is enabled" || fail_t "ios_test isolation guard ignored auto-lease: $ios_test_isolation_autolease"
ios_test_isolation_override="$(
  PROJECT_ROOT="/tmp/.codex/worktrees/91de/kg" \
  DESTINATION="platform=iOS Simulator,name=iPhone 17 Pro Max" \
  DEVICE_OVERRIDE="" \
  DESTINATION_OVERRIDE="" \
  AUTO_LEASE=0 \
  LIST_ONLY=0 \
  TEST_CACHE_ACTION="" \
  KG_IOS_TEST_ALLOW_SHARED_SIM=1 \
  CI="" \
  WORKTREE_BRANCH="" \
    bash -lc '
      eval "$(sed -n "/^destination_requires_device_lock()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^env_flag_enabled()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^running_in_isolation_enforced_context()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      eval "$(sed -n "/^should_require_isolated_simulator()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      if should_require_isolated_simulator; then echo require; else echo allow; fi
    '
)"
[[ "$ios_test_isolation_override" == "allow" ]] \
  && ok "ios_test allows explicit shared-simulator override" || fail_t "ios_test isolation guard ignored override: $ios_test_isolation_override"
grep -q -- '--ui-launch-profile' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q -- '--launch-benchmark' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'KG_UI_TEST_APP_ARGS_JSON' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test can inject UI app launch profiles into XCUIApplication" || fail_t "ios_test missing UI launch-profile injection"
grep -Eq 'TEST \(EXECUTE \)\?SUCCEEDED|TEST\( EXECUTE\)\? SUCCEEDED|TEST\( EXECUTE\)\?SUCCEEDED|TEST \(EXECUTE\)\? FAILED|TEST\( EXECUTE\)\?FAILED' "$WORKSPACE/ops/ios_test.sh" \
  || grep -qE 'TEST\( EXECUTE\)\? SUCCEEDED|TEST \(EXECUTE \)\? SUCCEEDED|TEST \(EXECUTE \)\? FAILED' "$WORKSPACE/ops/ios_test.sh"
if [[ $? -eq 0 ]]; then
  ok "ios_test recognizes test-without-building success banner"
else
  fail_t "ios_test missing TEST EXECUTE SUCCEEDED handling"
fi
grep -q 'xcresult=.*RESULT_BUNDLE' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test verdict records xcresult" || fail_t "ios_test verdict missing xcresult path"
grep -q 'bootMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'testBodyMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'xcresultSessionMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'appLaunchAverageMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'appLaunchSamples:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'invocationOverheadMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'xcodebuildMs:' "$WORKSPACE/ops/ios_test.sh" \
  && grep -q 'totalMs:' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test verdict records timing breakdown" || fail_t "ios_test verdict missing timing fields"
grep -q 'VERDICT_JSON_FILE' "$WORKSPACE/ops/ios_test.sh" \
  && ok "ios_test writes JSON verdict" || fail_t "ios_test missing JSON verdict"
ios_test_retry_tmp="$(mktemp -d)"
cat > "$ios_test_retry_tmp/test_failed.log" <<'LOG'
Test Suite 'All tests' started
Test Case '-[BooksAndVocabTests PollutedStateTests testPollutedState]' failed (0.123 seconds)
** TEST FAILED **
LOG
cat > "$ios_test_retry_tmp/cache_corrupt.log" <<'LOG'
xcodebuild: error: Failed to read xctestrun file
LOG
retry_should_not_rebuild="$(
  TMPOUT="$ios_test_retry_tmp/test_failed.log" \
    bash -lc '
      eval "$(sed -n "/^should_rebuild_after_test_without_building_failure()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      if should_rebuild_after_test_without_building_failure; then echo rebuild; else echo preserve; fi
    '
)"
[[ "$retry_should_not_rebuild" == "preserve" ]] \
  && ok "ios_test preserves genuine TEST FAILED result without rebuild" || fail_t "ios_test retries genuine test failure: $retry_should_not_rebuild"
retry_should_rebuild="$(
  TMPOUT="$ios_test_retry_tmp/cache_corrupt.log" \
    bash -lc '
      eval "$(sed -n "/^should_rebuild_after_test_without_building_failure()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      if should_rebuild_after_test_without_building_failure; then echo rebuild; else echo preserve; fi
    '
)"
[[ "$retry_should_rebuild" == "rebuild" ]] \
  && ok "ios_test rebuilds only cache/infrastructure failure" || fail_t "ios_test did not rebuild cache corruption failure: $retry_should_rebuild"
missing_log_count="$(
  TMPOUT="$ios_test_retry_tmp/does-not-exist.log" \
    bash -lc '
      eval "$(sed -n "/^test_log_line_count()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      if test_log_line_count; then echo present; else echo missing; fi
    '
)"
[[ "$missing_log_count" == "missing" ]] \
  && ok "ios_test treats missing xcodebuild log as structured infra failure input" || fail_t "ios_test missing-log guard invalid: $missing_log_count"
missing_log_marker="$(
  TMPOUT="$ios_test_retry_tmp/does-not-exist.log" \
    bash -lc '
      eval "$(sed -n "/^write_missing_test_log_marker()/,/^}/p" "'"$WORKSPACE/ops/ios_test.sh"'")"
      write_missing_test_log_marker
      cat "$TMPOUT"
    '
)"
echo "$missing_log_marker" | grep -q 'xcodebuild log path disappeared before diagnostics could read it' \
  && ok "ios_test can synthesize a readable placeholder when the log path disappears" || fail_t "ios_test missing-log marker invalid: $missing_log_marker"
missing_diag_json="$("$IOS_DIAG" --kind test --xcresult "$ios_test_retry_tmp/Missing.xcresult" --log "$ios_test_retry_tmp/never-created.log" --json --result fail)"
echo "$missing_diag_json" | jq -e --arg log "$ios_test_retry_tmp/never-created.log" '.schema=="kg.ios.diagnostics.v1" and .source=="raw-log-missing" and .result=="fail" and .counts.errors==0 and .logError=="log file not found: \($log)" and (.xcresultError|length > 0) and .artifacts.log==$log' >/dev/null \
  && ok "ios_diagnostics reports missing fallback log as machine-readable error" || fail_t "ios_diagnostics missing-log fallback invalid: $missing_diag_json"
rm -rf "$ios_test_retry_tmp"

echo ""
echo "══════════════════════════════"
echo "  passed: $pass  failed: $fail"
echo "══════════════════════════════"
[[ $fail -eq 0 ]]
