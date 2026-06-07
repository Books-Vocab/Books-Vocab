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
echo "$commands_json" | jq -e '.schema=="kg.ios.commands.v1" and (.commands|length >= 17) and all(.commands[]; has("delegate")) and any(.commands[]; .key=="snapshot" and (.jsonSchemas|index("kg.ios.snapshot.v1")) and (.jsonSchemas|index("kg.ios.gate.v1")) and (.jsonSchemas|index("kg.ios.xcode.v1")) and (.jsonSchemas|index("kg.ios.simulator.v1")) and (.jsonSchemas|index("kg.ios.logs.v1"))) and any(.commands[]; .key=="catalog" and (.jsonSchemas|index("kg.ios.catalog.v1")) and (.command|test("catalog prepare")) and (.command|test("catalog snapshots")) and (.command|test("catalog clean")) and (.command|test("--dataset <name>")) and (.command|test("--dataset-file <path>")) and (.sideEffect|test("local-test")) and (.sideEffect|test("local-artifact"))) and any(.commands[]; .key=="logs" and .sideEffect=="read-only" and (.jsonSchemas|index("kg.ios.logs.v1"))) and any(.commands[]; .key=="issues" and .delegate=="./ops/ios_diagnostics.py" and (.jsonSchemas|index("kg.ios.diagnostics.v1"))) and any(.commands[]; .key=="gate" and (.aliases|index("verdict")) and (.jsonSchemas|index("kg.ios.gate.v1")) and .sideEffect=="read-only") and any(.commands[]; .key=="xcode" and (.aliases|index("environment")) and (.jsonSchemas|index("kg.ios.xcode.v1")) and .sideEffect=="read-only") and any(.commands[]; .key=="simulator" and (.aliases|index("sim")) and (.jsonSchemas|index("kg.ios.simulator.v1")) and (.sideEffect|test("local-artifact screenshot")) and (.sideEffect|test("local-simulator-lifecycle")) and (.command|test("launch")) and (.command|test("terminate"))) and any(.commands[]; .key=="archive" and (.aliases|index("release")) and (.sideEffect|test("external-upload only with --upload"))) and any(.commands[]; .key=="commands" and (.aliases|index("capabilities")))' >/dev/null \
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
xcode_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" xcode --json)"
echo "$xcode_json" | jq -e '.schema=="kg.ios.xcode.v1" and (.errors|length)==0 and .xcode.version=="16.4" and .project.scheme=="BooksBrowser" and (.project.list.schemes|index("BooksBrowser")) and any(.destinations.available[]; .id=="fixture-iphone-17-pro-max" and .platform=="iOS Simulator" and .name=="iPhone 17 Pro Max") and any(.destinations.ineligible[]; .id=="fixture-ineligible" and (.error|contains("OS mismatch, please download runtime"))) and all(.destinations.available[]; .id!="fixture-ineligible") and .simulators.summary.booted==1' >/dev/null \
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
echo "$sim_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="status" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .device.state=="Booted" and .app.bundleID=="com.Max0228.BooksBrowser" and .app.container.data=="/tmp/kg-sim-fixture/container" and .app.container.status=="ok" and .app.process.status=="running" and .app.process.pid=="74736" and .sources.app_process.status=="ok"' >/dev/null \
  && ok "simulator status --json exposes booted device, app container, and process" || fail_t "simulator status --json invalid: $sim_json"
sim_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" sim status)"
echo "$sim_text" | grep -q 'schema=kg.ios.simulator.v1' && echo "$sim_text" | grep -q 'udid=fixture-iphone-17-pro-max' && echo "$sim_text" | grep -q 'app_process status=running pid=74736' \
  && ok "sim alias text lists booted simulator" || fail_t "sim text invalid: $sim_text"
sim_stopped_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE=1 bash "$IOS_OPS" simulator status --json)"
echo "$sim_stopped_json" | jq -e '.schema=="kg.ios.simulator.v1" and .status=="ok" and .app.process.status=="stopped" and .app.process.pid==null and .sources.app_process.exitCode==1 and (.errors|length)==0' >/dev/null \
  && ok "simulator status --json reports stopped app process without failing" || fail_t "simulator stopped app invalid: $sim_stopped_json"
sim_launch_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE=1 bash "$IOS_OPS" simulator launch --json)"
echo "$sim_launch_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="launch" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .app.bundleID=="com.Max0228.BooksBrowser" and .app.lifecycle.exitCode==0 and .app.lifecycle.output=="74736" and .app.process.status=="running" and .app.process.pid=="74736"' >/dev/null \
  && ok "simulator launch --json starts installed app and refreshes process state" || fail_t "simulator launch invalid: $sim_launch_json"
sim_launch_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" sim launch)"
echo "$sim_launch_text" | grep -q 'action=launch status=ok' && echo "$sim_launch_text" | grep -q 'app_process status=running pid=74736' \
  && ok "simulator launch text reports process state" || fail_t "simulator launch text invalid: $sim_launch_text"
sim_terminate_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator terminate --json)"
echo "$sim_terminate_json" | jq -e '.schema=="kg.ios.simulator.v1" and .action=="terminate" and .status=="ok" and .device.udid=="fixture-iphone-17-pro-max" and .app.bundleID=="com.Max0228.BooksBrowser" and .app.lifecycle.exitCode==0 and .app.process.status=="stopped" and .app.process.pid==null' >/dev/null \
  && ok "simulator terminate --json stops installed app and refreshes process state" || fail_t "simulator terminate invalid: $sim_terminate_json"
sim_shot_tmp="$(mktemp -d)"
sim_shot="$sim_shot_tmp/screenshot with spaces.png"
sim_shot_json="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator screenshot --out "$sim_shot" --json)"
echo "$sim_shot_json" | jq -e --arg path "$sim_shot" '.schema=="kg.ios.simulator.v1" and .action=="screenshot" and .status=="ok" and .artifact.path==$path and .artifact.exists==true and .artifact.bytes > 0 and .device.udid=="fixture-iphone-17-pro-max"' >/dev/null \
  && [[ -s "$sim_shot" ]] \
  && ok "simulator screenshot --json creates local artifact" || fail_t "simulator screenshot invalid: $sim_shot_json"
sim_shot_text="$(KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" simulator screenshot --out "$sim_shot_tmp/text.png")"
echo "$sim_shot_text" | grep -q 'artifact=' && echo "$sim_shot_text" | grep -q 'text.png' \
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
rm -rf "$sim_shot_tmp"

section "Catalog snapshot export surface"
catalog_tmp="$(mktemp -d)"
catalog_xctestrun_tmp="$(mktemp -d)"
mkdir -p "$catalog_xctestrun_tmp/Build/Products"
touch "$catalog_xctestrun_tmp/Build/Products/BooksBrowserCatalogSnapshots_BooksBrowserCatalogSnapshots_iphonesimulator26.4-arm64.xctestrun"
touch "$catalog_xctestrun_tmp/Build/Products/BooksBrowserCatalogSnapshots_BooksBrowserCatalogSnapshots_iphonesimulator26.4-arm64.scoped.xctestrun"
catalog_xctestrun_path="$(
  ROOT="$WORKSPACE" \
  XCODEPROJ="$WORKSPACE/ios/BooksBrowser.xcodeproj" \
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
ROOT="$WORKSPACE" XCODEPROJ="$WORKSPACE/ios/BooksBrowser.xcodeproj" \
  bash -lc 'source "'"$IOS_OPS_CATALOG_LIB"'"; catalog_prepare_scoped_xctestrun "'"$prepare_xctestrun"'" "" "" "'"$dataset_fixture_b64"'" "'"$dataset_scoped_xctestrun"'"'
[[ "$(plutil -extract 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_FIXTURE_DATASET_B64' raw -o - "$dataset_scoped_xctestrun")" == "$dataset_fixture_b64" ]] \
  && [[ "$(plutil -extract 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_FIXTURE_DATASET_B64' raw -o - "$dataset_scoped_xctestrun")" == "$dataset_fixture_b64" ]] \
  && ok "catalog scoped xctestrun embeds fixture dataset env" || fail_t "catalog scoped xctestrun missing fixture dataset env"
prepare_catalog_hit_json="$(KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_CATALOG_CACHE_ROOT="$catalog_cache_root" bash "$IOS_OPS" catalog prepare --json)"
echo "$prepare_catalog_hit_json" | jq -e '.schema=="kg.ios.catalog.prepare.v1" and .status=="ok" and .cache.status=="hit" and .build.exitCode==0' >/dev/null \
  && ok "catalog prepare reuses ready cache without rebuilding" || fail_t "catalog prepare hit invalid: $prepare_catalog_hit_json"
catalog_json="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --json)"
echo "$catalog_json" | jq -e --arg root "$catalog_tmp/build/snapshots" '.schema=="kg.ios.catalog.v1" and .action=="snapshots" and .status=="ok" and .mode=="fixture" and .artifacts.root==$root and .artifacts.pngCount==2 and (.artifacts.paths|length)==2 and (.scope.groups|length)==0 and (.scope.scenarios|length)==0 and all(.artifacts.paths[]; startswith($root)) and (.validation.status=="ok") and .validation.actualPngCount==2 and .validation.uniformImageCount==0 and .validation.minPixelWidth==16 and .validation.maxPixelWidth==16 and .validation.minPixelHeight==16 and .validation.maxPixelHeight==16 and (.validation.images|length)==2 and .cache.status=="not-applicable" and .cache.key==null and .cache.root==null and (.test.command|contains("CatalogSnapshotTests")) and .test.exitCode==0 and .copy.exitCode==0 and .copy.containerDataPath=="/tmp/kg-sim-fixture/container" and .flags.compileTimeFlag=="KG_RUN_CATALOG_SNAPSHOTS"' >/dev/null \
  && ok "catalog snapshots --json exports fixture PNG artifacts" || fail_t "catalog snapshots --json invalid: $catalog_json"
echo "$catalog_json" | jq -e '(.timings.wrapperWallMs|type)=="number" and .timings.wrapperWallMs >= 0 and (.timings.commandWallMs|type)=="number" and .timings.commandWallMs >= 0 and (.timings.testBodyMs|type)=="number" and .timings.testBodyMs >= 0 and (.timings.playbookBuildMs|type)=="number" and .timings.playbookBuildMs >= 0 and (.timings.snapshotRunMs|type)=="number" and .timings.snapshotRunMs >= 0 and (.timings.startupOverheadMs|type)=="number" and .timings.startupOverheadMs >= 0 and (.timings.simulatorStatusMs|type)=="number" and .timings.simulatorStatusMs >= 0 and (.timings.containerLookupMs|type)=="number" and .timings.containerLookupMs >= 0 and (.timings.copyMs|type)=="number" and .timings.copyMs >= 0 and (.timings.artifactIndexMs|type)=="number" and .timings.artifactIndexMs >= 0 and (.timings.validationMs|type)=="number" and .timings.validationMs >= 0' >/dev/null \
  && ok "catalog snapshots --json exposes timing breakdown" || fail_t "catalog snapshots timing invalid: $catalog_json"
catalog_text="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots)"
echo "$catalog_text" | grep -q '\[ios\]\[catalog\].*status=ok.*pngCount=2' && echo "$catalog_text" | grep -q 'validation status=ok' && echo "$catalog_text" | grep -q 'CatalogSnapshotTests' \
  && ok "catalog snapshots text reports artifact summary" || fail_t "catalog snapshots text invalid: $catalog_text"
scoped_catalog_json="$(KG_IOS_OPS_FIXTURE=1 TMPDIR="$catalog_tmp" bash "$IOS_OPS" catalog snapshots --group Bookshelf --group 'Today Review' --scenario 'Today Review/Front' --json)"
echo "$scoped_catalog_json" | jq -e '.schema=="kg.ios.catalog.v1" and (.scope.groups==["Bookshelf","Today Review"]) and (.scope.scenarios==["Today Review/Front"]) and (.validation.status=="ok") and .validation.actualPngCount==2 and .cache.status=="not-applicable" and (.test.command|contains("-scheme BooksBrowserCatalogSnapshots")) and (.test.command|contains("build-for-testing")) and (.test.command|contains("test-without-building")) and (.test.command|contains("-xctestrun"))' >/dev/null \
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
rm -rf "$catalog_tmp" "$catalog_xctestrun_tmp" "$bad_catalog_tmp"

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
cat > "$runs_tmp/build.log" <<'LOG'
warning: StoreKit Configuration file for scheme "BooksBrowser" can't be found at path "/tmp/missing.storekit"
** BUILD SUCCEEDED **
LOG
cat > "$runs_tmp/test.log" <<'LOG'
** TEST SUCCEEDED **
LOG
echo "RESULT=legacy" > "$runs_tmp/kg_ios_build_verdict"
jq -nc --arg log "$runs_tmp/build.log" --arg xcresult "$runs_tmp/Build.xcresult" \
  '{schema:"kg.ios.run-verdict.v1",kind:"build",status:"ok",result:"ok",exit:"0",reason:null,caller:"fixture with spaces",elapsed:"3s",executed:null,artifacts:{log:$log,xcresult:$xcresult}}' \
  > "$runs_tmp/kg_ios_build_verdict.json"
jq -nc --arg log "$runs_tmp/test.log" --arg xcresult "$runs_tmp/Test.xcresult" \
  '{schema:"kg.ios.run-verdict.v1",kind:"test",status:"ok",result:"ok",exit:"0",reason:null,caller:"fixture with spaces",elapsed:"5s",executed:"12",artifacts:{log:$log,xcresult:$xcresult}}' \
  > "$runs_tmp/kg_ios_test_verdict.json"
runs_json="$(TMPDIR="$runs_tmp" bash "$IOS_OPS" runs --json)"
echo "$runs_json" | jq -e '.schema=="kg.ios.runs.v1" and .build.result=="ok" and .build.caller=="fixture with spaces" and .test.executed=="12" and .build.artifacts.logExists==true and .test.artifacts.xcresultExists==true and .build.diagnostics.schema=="kg.ios.diagnostics.v1" and .build.diagnostics.counts.warnings==1 and .build.diagnostics.counts.storekit==1' >/dev/null \
  && ok "runs --json parses latest build/test verdicts" || fail_t "runs --json invalid: $runs_json"
echo "$runs_json" | jq -e 'all([.build,.test][]; has("kind") and has("status") and has("result") and has("exit") and has("reason") and has("caller") and has("elapsed") and has("executed") and has("verdictFile") and has("jsonVerdictFile") and has("artifacts") and has("diagnostics"))' >/dev/null \
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
echo "$snapshot_json" | jq -e '.schema=="kg.ios.snapshot.v1" and (.readiness|length >= 7) and (.workflow.steps|length == 8) and .gate.schema=="kg.ios.gate.v1" and .gate.verdict=="pass" and .gate.exitCode==0 and .summary.verdict=="warn" and .summary.counts.buildWarnings==1 and any(.summary.nextActions[]; .source=="runs.build.diagnostics" and .severity=="warn" and .category=="storekit" and (.message|contains("StoreKit Configuration"))) and .xcode.schema=="kg.ios.xcode.v1" and .xcode.simulators.summary.booted==1 and .simulator.schema=="kg.ios.simulator.v1" and .simulator.app.process.status=="running" and .project.version=="1.6" and .runs.test.executed=="12" and .runs.build.diagnostics.counts.warnings==1 and .runs.build.diagnostics.diagnostics[0].category=="storekit" and .logs==null' >/dev/null \
  && ok "snapshot --json combines readiness and workflow" || fail_t "snapshot --json invalid: $snapshot_json"
snapshot_skip_xcode_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json --skip-xcode)"
echo "$snapshot_skip_xcode_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and .xcode==null and .simulator.schema=="kg.ios.simulator.v1" and .runs.test.executed=="12"' >/dev/null \
  && ok "snapshot --json can skip xcode inventory" || fail_t "snapshot --json --skip-xcode invalid: $snapshot_skip_xcode_json"
snapshot_skip_simulator_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --json --skip-simulator)"
echo "$snapshot_skip_simulator_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and .xcode.schema=="kg.ios.xcode.v1" and .simulator==null and .runs.test.executed=="12"' >/dev/null \
  && ok "snapshot --json can skip simulator status" || fail_t "snapshot --json --skip-simulator invalid: $snapshot_skip_simulator_json"
snapshot_no_booted_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_SIM_NO_BOOTED_FIXTURE=1 bash "$IOS_OPS" snapshot --json)"
echo "$snapshot_no_booted_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.verdict=="warn" and any(.summary.nextActions[]; .source=="simulator" and .severity=="warn" and .key=="booted-device") and .simulator.schema=="kg.ios.simulator.v1" and .simulator.status=="error" and any(.simulator.errors[]; .key=="booted-device") and .runs.test.executed=="12"' >/dev/null \
  && ok "snapshot --json embeds simulator error without failing" || fail_t "snapshot no-booted simulator invalid: $snapshot_no_booted_json"
snapshot_logs_json="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 KG_IOS_OPS_LOG_FIXTURE=1 bash "$IOS_OPS" snapshot --json --include-logs --log-since 1m --log-limit 1)"
echo "$snapshot_logs_json" | jq -e '.schema=="kg.ios.snapshot.v1" and .summary.counts.runtimeLogs==1 and .simulator.schema=="kg.ios.simulator.v1" and .logs.schema=="kg.ios.logs.v1" and .logs.since=="1m" and .logs.limit==1 and .logs.summary.filteredCount==1 and (.logs.entries|length)==1' >/dev/null \
  && ok "snapshot --json can include runtime logs" || fail_t "snapshot --json logs invalid: $snapshot_logs_json"
snapshot_text="$(TMPDIR="$runs_tmp" KG_IOS_OPS_FIXTURE=1 bash "$IOS_OPS" snapshot --skip-xcode --skip-simulator)"
printf '%s\n' "$snapshot_text" | sed -n '1p' | grep -q '^\[ios\]\[summary\].*verdict=warn.*buildWarnings=1' \
  && ok "snapshot text starts with summary verdict" || fail_t "snapshot text first line missing summary: $snapshot_text"
echo "$snapshot_text" | grep -q '\[ios\]\[next\].*source=runs.build.diagnostics.*severity=warn.*category=storekit' \
  && ok "snapshot text lists next actions" || fail_t "snapshot text missing next action: $snapshot_text"
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
