#!/usr/bin/env bash
# ios_ops_simulator.sh — sourceable simulator status/screenshot commands for ios_ops.sh.

simulator_now_ms() {
  perl -MTime::HiRes=time -e 'printf "%.0f\n", time()*1000'
}

file_size_bytes() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    printf '0'
  elif stat -f %z "$path" >/dev/null 2>&1; then
    stat -f %z "$path"
  else
    wc -c <"$path" | tr -d '[:space:]'
  fi
}

simulator_resolve_selector_json() {
  local selector="${1:-$DEFAULT_SIMULATOR_NAME}" devices_source
  devices_source="$(capture_source_json simctl_devices read_simctl_devices_json)"
  jq -n \
    --arg selector "$selector" \
    --arg defaultName "$DEFAULT_SIMULATOR_NAME" \
    --argjson devicesSource "$devices_source" '
      def all_devices: [($devicesSource.payload.devices // {}) | to_entries[]?.value[]?];
      def pick_target:
        if $selector == "booted" then (all_devices | map(select(.state == "Booted"))[0] // null)
        else (
          all_devices
          | map(select(.udid == $selector or .name == $selector))[0]
          // (if $selector == $defaultName then (all_devices | map(select(.name == $defaultName))[0] // null) else null end)
        )
        end;
      (pick_target) as $device
      | {
          selector:$selector,
          status:(
            if $devicesSource.status != "ok" then "error"
            elif $device == null then "error"
            else "ok"
            end
          ),
          device:(
            if $device == null then null else {
              name:($device.name // null),
              udid:($device.udid // null),
              state:($device.state // null),
              isAvailable:($device.isAvailable // null),
              deviceTypeIdentifier:($device.deviceTypeIdentifier // null),
              lastBootedAt:($device.lastBootedAt // null)
            } end
          ),
          errors:(
            (if $devicesSource.status != "ok" then [{key:"simctl-devices",status:$devicesSource.status,exitCode:$devicesSource.exitCode,error:$devicesSource.error}] else [] end)
            +
            (if $devicesSource.status == "ok" and $device == null then [{key:"simulator-device",status:"error",exitCode:null,error:("unresolved-device-selector:" + $selector)}] else [] end)
          )
        }'
}

cmd_simulator_status_json() {
  local devices_source container_source process_source generated_at payload status
  local start_ms end_ms devices_start_ms devices_end_ms container_start_ms container_end_ms process_start_ms process_end_ms
  local total_ms devices_ms container_ms process_ms
  start_ms="$(simulator_now_ms)"
  devices_start_ms="$(simulator_now_ms)"
  devices_source="$(capture_source_json simctl_devices read_simctl_devices_json)"
  devices_end_ms="$(simulator_now_ms)"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  devices_ms=$(( devices_end_ms - devices_start_ms ))
  container_ms=0
  process_ms=0

  local booted_udid
  booted_udid="$(jq -r '[.payload.devices // {} | to_entries[]?.value[]? | select(.state == "Booted")][0].udid // empty' <<<"$devices_source")"
  if [[ -n "$booted_udid" ]]; then
    container_start_ms="$(simulator_now_ms)"
    container_source="$(capture_source_text app_container read_app_container_path "$booted_udid" "$BUNDLE_ID" data)"
    container_end_ms="$(simulator_now_ms)"
    process_start_ms="$(simulator_now_ms)"
    process_source="$(capture_source_text app_process read_app_process_pid "$booted_udid" "$SCHEME")"
    process_end_ms="$(simulator_now_ms)"
    container_ms=$(( container_end_ms - container_start_ms ))
    process_ms=$(( process_end_ms - process_start_ms ))
  else
    container_source='null'
    process_source='null'
  fi
  end_ms="$(simulator_now_ms)"
  total_ms=$(( end_ms - start_ms ))

  payload="$(jq -n \
    --arg schema "kg.ios.simulator.v1" \
    --arg generated_at "$generated_at" \
    --arg bundle_id "$BUNDLE_ID" \
    --argjson devicesSource "$devices_source" \
    --argjson containerSource "$container_source" \
    --argjson processSource "$process_source" \
    --argjson totalMs "$total_ms" \
    --argjson simctlDevicesMs "$devices_ms" \
    --argjson appContainerMs "$container_ms" \
    --argjson appProcessMs "$process_ms" \
    '
      def trim_newlines: gsub("\\n+$"; "");
      ($devicesSource.payload.devices // {}) as $devices
      | [($devices | to_entries[]?.value[]? | select(.state == "Booted"))] as $booted
      | ($booted[0] // null) as $device
      | (if $processSource == null then null else (($processSource.output // "") | trim_newlines) end) as $process_pid
      | {
          schema:$schema,
          generated_at:$generated_at,
          action:"status",
          status:(
            if $devicesSource.status != "ok" then "error"
            elif $device == null then "error"
            elif ($containerSource != null and $containerSource.status != "ok") then "warn"
            else "ok"
            end
          ),
          device:(
            if $device == null then null else {
              name:($device.name // null),
              udid:($device.udid // null),
              state:($device.state // null),
              isAvailable:($device.isAvailable // null),
              deviceTypeIdentifier:($device.deviceTypeIdentifier // null),
              lastBootedAt:($device.lastBootedAt // null)
            } end
          ),
          app:{
            bundleID:$bundle_id,
            container:{
              data:(if $containerSource == null or $containerSource.status != "ok" then null else (($containerSource.output // "") | trim_newlines) end),
              status:(if $containerSource == null then "skipped" else $containerSource.status end),
              exitCode:(if $containerSource == null then null else $containerSource.exitCode end),
              error:(if $containerSource == null then null else $containerSource.error end)
            },
            process:{
              name:"BooksBrowser",
              pid:(if $processSource != null and $processSource.status == "ok" and $process_pid != "" then $process_pid else null end),
              status:(
                if $processSource == null then "skipped"
                elif $processSource.status == "ok" and $process_pid != "" then "running"
                elif $processSource.exitCode == 1 then "stopped"
                else "unknown"
                end
              ),
              exitCode:(if $processSource == null then null else $processSource.exitCode end),
              error:(if $processSource == null then null else $processSource.error end)
            }
          },
          sources:{
            simctl_devices:{status:$devicesSource.status,exitCode:$devicesSource.exitCode,error:$devicesSource.error},
            app_container:(if $containerSource == null then null else {status:$containerSource.status,exitCode:$containerSource.exitCode,error:$containerSource.error} end),
            app_process:(if $processSource == null then null else {status:$processSource.status,exitCode:$processSource.exitCode,error:$processSource.error} end)
          },
          timings:{
            totalMs:$totalMs,
            simctlDevicesMs:$simctlDevicesMs,
            appContainerMs:$appContainerMs,
            appProcessMs:$appProcessMs
          },
          errors:(
            (if $devicesSource.status != "ok" then [{key:"simctl-devices",status:$devicesSource.status,exitCode:$devicesSource.exitCode,error:$devicesSource.error}] else [] end)
            +
            (if $devicesSource.status == "ok" and $device == null then [{key:"booted-device",status:"error",exitCode:null,error:"no-booted-simulator"}] else [] end)
            +
            (if $containerSource != null and $containerSource.status != "ok" then [{key:"app-container",status:$containerSource.status,exitCode:$containerSource.exitCode,error:$containerSource.error}] else [] end)
            +
            (if $processSource != null and $processSource.status != "ok" and $processSource.exitCode != 1 then [{key:"app-process",status:$processSource.status,exitCode:$processSource.exitCode,error:$processSource.error}] else [] end)
          )
        }
    ')"
  printf '%s\n' "$payload"
  status="$(jq -r '.status' <<<"$payload")"
  [[ "$status" == "ok" || "$status" == "warn" ]]
}

cmd_simulator_status() {
  local json="$1" payload rc=0
  payload="$(cmd_simulator_status_json)" || rc=$?
  if (( json )); then
    printf '%s\n' "$payload"
    return "$rc"
  fi

  jq -r '
    "[ios][simulator] schema=\(.schema) action=\(.action) status=\(.status) bundleID=\(.app.bundleID)",
    (if .device == null then
      "[ios][simulator] device=none"
    else
      "[ios][simulator] device name=\"\(.device.name // "")\" udid=\(.device.udid // "") state=\(.device.state // "") available=\(.device.isAvailable // "")"
    end),
    "[ios][simulator] app_container status=\(.app.container.status) data=\(.app.container.data // "")",
    "[ios][simulator] app_process status=\(.app.process.status) pid=\(.app.process.pid // "") name=\(.app.process.name)",
    "[ios][simulator] timings totalMs=\(.timings.totalMs) simctlDevicesMs=\(.timings.simctlDevicesMs) appContainerMs=\(.timings.appContainerMs) appProcessMs=\(.timings.appProcessMs)",
    (.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
  ' <<<"$payload"
  return "$rc"
}

cmd_simulator_screenshot() {
  local json=0 out="" device_selector="booted"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --out) out="${2:?--out needs value}"; shift 2 ;;
      --device) device_selector="${2:?--device needs value}"; shift 2 ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh simulator screenshot --out <png> [--device booted] [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown simulator screenshot option: $1" >&2
        return 1
        ;;
    esac
  done
  if [[ -z "$out" ]]; then
    echo "✗ simulator screenshot requires --out <png>" >&2
    return 1
  fi

  local status_payload status_rc=0 resolved_device device_json err rc generated_at bytes exists payload
  local start_ms end_ms status_start_ms status_end_ms screenshot_start_ms screenshot_end_ms total_ms status_ms screenshot_ms
  start_ms="$(simulator_now_ms)"
  status_start_ms="$(simulator_now_ms)"
  status_payload="$(cmd_simulator_status_json)" || status_rc=$?
  status_end_ms="$(simulator_now_ms)"
  status_ms=$(( status_end_ms - status_start_ms ))
  if (( status_rc != 0 )); then
    end_ms="$(simulator_now_ms)"
    total_ms=$(( end_ms - start_ms ))
    payload="$(jq -n \
      --arg schema "kg.ios.simulator.v1" \
      --arg generated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg out "$out" \
      --argjson statusPayload "$status_payload" \
      --argjson totalMs "$total_ms" \
      --argjson statusMs "$status_ms" \
      '{
        schema:$schema,
        generated_at:$generated_at,
        action:"screenshot",
        status:"error",
        device:null,
        artifact:{path:$out,exists:false,bytes:0},
        timings:{totalMs:$totalMs,statusMs:$statusMs,screenshotMs:0},
        errors:($statusPayload.errors + [{key:"screenshot",status:"error",exitCode:null,error:"booted-simulator-required"}])
      }')"
    if (( json )); then
      printf '%s\n' "$payload"
    else
      jq -r '(.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) error=\(.error // "")")' <<<"$payload"
    fi
    return "$status_rc"
  fi

  if [[ "$device_selector" == "booted" ]]; then
    resolved_device="$(jq -r '.device.udid' <<<"$status_payload")"
    device_json="$(jq -c '.device' <<<"$status_payload")"
  else
    resolved_device="$device_selector"
    device_json="$(jq -n --arg udid "$device_selector" '{udid:$udid,state:null,name:null,isAvailable:null,deviceTypeIdentifier:null,lastBootedAt:null}')"
  fi

  err="$(mktemp)"
  screenshot_start_ms="$(simulator_now_ms)"
  if mkdir -p "$(dirname "$out")" 2>"$err" && write_simulator_screenshot "$resolved_device" "$out" 2>>"$err"; then
    rc=0
  else
    rc=$?
  fi
  screenshot_end_ms="$(simulator_now_ms)"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  screenshot_ms=$(( screenshot_end_ms - screenshot_start_ms ))
  end_ms="$(simulator_now_ms)"
  total_ms=$(( end_ms - start_ms ))
  bytes="$(file_size_bytes "$out")"
  exists="$(path_exists_json_bool file "$out")"
  payload="$(jq -n \
    --arg schema "kg.ios.simulator.v1" \
    --arg generated_at "$generated_at" \
    --arg out "$out" \
    --arg stderr "$(cat "$err")" \
    --argjson rc "$rc" \
    --argjson exists "$exists" \
    --argjson bytes "$bytes" \
    --argjson device "$device_json" \
    --argjson totalMs "$total_ms" \
    --argjson statusMs "$status_ms" \
    --argjson screenshotMs "$screenshot_ms" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      action:"screenshot",
      status:(if $rc == 0 then "ok" else "error" end),
      device:$device,
      artifact:{path:$out,exists:$exists,bytes:$bytes},
      timings:{totalMs:$totalMs,statusMs:$statusMs,screenshotMs:$screenshotMs},
      errors:(if $rc == 0 then [] else [{key:"screenshot",status:"error",exitCode:$rc,error:$stderr}] end)
    }')"
  rm -f "$err"

  if (( json )); then
    printf '%s\n' "$payload"
  else
    jq -r '
      "[ios][simulator] schema=\(.schema) action=\(.action) status=\(.status) device=\(.device.udid // "") artifact=\(.artifact.path) exists=\(.artifact.exists) bytes=\(.artifact.bytes)",
      "[ios][simulator] timings totalMs=\(.timings.totalMs) statusMs=\(.timings.statusMs) screenshotMs=\(.timings.screenshotMs)",
      (.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
    ' <<<"$payload"
  fi
  return "$rc"
}

cmd_simulator_lifecycle() {
  local action="$1" json=0 device_selector="booted"
  shift
  local -a app_args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --device) device_selector="${2:?--device needs value}"; shift 2 ;;
      --)
        shift
        app_args=("$@")
        break
        ;;
      -h|--help|help)
        if [[ "$action" == "launch" ]]; then
          echo "Usage: ./ops/ios_ops.sh simulator launch [--device booted] [--json] [-- app args...]"
        else
          echo "Usage: ./ops/ios_ops.sh simulator terminate [--device booted] [--json]"
        fi
        return 0
        ;;
      *)
        echo "✗ unknown simulator $action option: $1" >&2
        return 1
        ;;
    esac
  done

  local status_payload status_rc=0 resolved_device device_json generated_at payload lifecycle_out lifecycle_err rc process_source
  local start_ms end_ms status_start_ms status_end_ms lifecycle_start_ms lifecycle_end_ms process_start_ms process_end_ms total_ms status_ms lifecycle_ms process_ms
  start_ms="$(simulator_now_ms)"
  status_start_ms="$(simulator_now_ms)"
  status_payload="$(cmd_simulator_status_json)" || status_rc=$?
  status_end_ms="$(simulator_now_ms)"
  status_ms=$(( status_end_ms - status_start_ms ))
  if [[ "$device_selector" == "booted" ]]; then
    if (( status_rc != 0 )); then
      end_ms="$(simulator_now_ms)"
      total_ms=$(( end_ms - start_ms ))
      payload="$(jq -n \
        --arg schema "kg.ios.simulator.v1" \
        --arg generated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --arg action "$action" \
        --arg bundle_id "$BUNDLE_ID" \
        --argjson statusPayload "$status_payload" \
        --argjson totalMs "$total_ms" \
        --argjson statusMs "$status_ms" \
        '{
          schema:$schema,
          generated_at:$generated_at,
          action:$action,
          status:"error",
          device:null,
          app:{
            bundleID:$bundle_id,
            lifecycle:{status:"error",exitCode:null,output:null,error:"booted-simulator-required"},
            process:{name:"BooksBrowser",pid:null,status:"skipped",exitCode:null,error:null}
          },
          timings:{totalMs:$totalMs,statusMs:$statusMs,lifecycleMs:0,appProcessMs:0},
          errors:($statusPayload.errors + [{key:$action,status:"error",exitCode:null,error:"booted-simulator-required"}])
        }')"
      if (( json )); then
        printf '%s\n' "$payload"
      else
        jq -r '(.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) error=\(.error // "")")' <<<"$payload"
      fi
      return "$status_rc"
    fi
    resolved_device="$(jq -r '.device.udid' <<<"$status_payload")"
    device_json="$(jq -c '.device' <<<"$status_payload")"
  else
    resolved_device="$device_selector"
    device_json="$(jq -n --arg udid "$device_selector" '{udid:$udid,state:null,name:null,isAvailable:null,deviceTypeIdentifier:null,lastBootedAt:null}')"
  fi

  lifecycle_out="$(mktemp)"
  lifecycle_err="$(mktemp)"
  lifecycle_start_ms="$(simulator_now_ms)"
  if [[ "$action" == "launch" ]]; then
    if ((${#app_args[@]})); then
      if read_app_launch_output "$resolved_device" "$BUNDLE_ID" "${app_args[@]}" >"$lifecycle_out" 2>"$lifecycle_err"; then
        rc=0
      else
        rc=$?
      fi
    else
      if read_app_launch_output "$resolved_device" "$BUNDLE_ID" >"$lifecycle_out" 2>"$lifecycle_err"; then
        rc=0
      else
        rc=$?
      fi
    fi
  else
    if read_app_terminate_output "$resolved_device" "$BUNDLE_ID" >"$lifecycle_out" 2>"$lifecycle_err"; then
      rc=0
    else
      rc=$?
    fi
  fi
  lifecycle_end_ms="$(simulator_now_ms)"
  process_start_ms="$(simulator_now_ms)"
  process_source="$(capture_source_text app_process read_app_process_pid "$resolved_device" "$SCHEME")"
  process_end_ms="$(simulator_now_ms)"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  lifecycle_ms=$(( lifecycle_end_ms - lifecycle_start_ms ))
  process_ms=$(( process_end_ms - process_start_ms ))
  end_ms="$(simulator_now_ms)"
  total_ms=$(( end_ms - start_ms ))

  payload="$(jq -n \
    --arg schema "kg.ios.simulator.v1" \
    --arg generated_at "$generated_at" \
    --arg action "$action" \
    --arg bundle_id "$BUNDLE_ID" \
    --rawfile lifecycleOutput "$lifecycle_out" \
    --rawfile lifecycleError "$lifecycle_err" \
    --argjson rc "$rc" \
    --argjson device "$device_json" \
    --argjson processSource "$process_source" \
    --argjson totalMs "$total_ms" \
    --argjson statusMs "$status_ms" \
    --argjson lifecycleMs "$lifecycle_ms" \
    --argjson appProcessMs "$process_ms" \
    '
      def trim_newlines: gsub("\\n+$"; "");
      ($lifecycleOutput | trim_newlines) as $life_output
      | ($lifecycleError | trim_newlines) as $life_error
      | (($processSource.output // "") | trim_newlines) as $process_pid
      | {
          schema:$schema,
          generated_at:$generated_at,
          action:$action,
          status:(
            if $rc != 0 then "error"
            elif $action == "launch" and ($processSource.status == "ok" and $process_pid != "") then "ok"
            elif $action == "terminate" and ($processSource.exitCode == 1 or ($processSource.status == "ok" and $process_pid == "")) then "ok"
            else "warn"
            end
          ),
          device:$device,
          app:{
            bundleID:$bundle_id,
            lifecycle:{
              status:(if $rc == 0 then "ok" else "error" end),
              exitCode:$rc,
              output:(if $life_output == "" then null else $life_output end),
              error:(if $rc == 0 then null else $life_error end)
            },
            process:{
              name:"BooksBrowser",
              pid:(if $processSource.status == "ok" and $process_pid != "" then $process_pid else null end),
              status:(
                if $processSource.status == "ok" and $process_pid != "" then "running"
                elif $processSource.exitCode == 1 then "stopped"
                else "unknown"
                end
              ),
              exitCode:$processSource.exitCode,
              error:$processSource.error
            }
          },
          sources:{
            lifecycle:{status:(if $rc == 0 then "ok" else "error" end),exitCode:$rc,error:(if $rc == 0 then null else $life_error end)},
            app_process:{status:$processSource.status,exitCode:$processSource.exitCode,error:$processSource.error}
          },
          timings:{
            totalMs:$totalMs,
            statusMs:$statusMs,
            lifecycleMs:$lifecycleMs,
            appProcessMs:$appProcessMs
          },
          errors:(
            (if $rc == 0 then [] else [{key:$action,status:"error",exitCode:$rc,error:$life_error}] end)
            +
            (if $processSource.status != "ok" and $processSource.exitCode != 1 then [{key:"app-process",status:$processSource.status,exitCode:$processSource.exitCode,error:$processSource.error}] else [] end)
          )
        }
    ')"
  rm -f "$lifecycle_out" "$lifecycle_err"

  if (( json )); then
    printf '%s\n' "$payload"
  else
    jq -r '
      "[ios][simulator] schema=\(.schema) action=\(.action) status=\(.status) device=\(.device.udid // "") bundleID=\(.app.bundleID)",
      "[ios][simulator] lifecycle status=\(.app.lifecycle.status) exitCode=\(.app.lifecycle.exitCode) output=\(.app.lifecycle.output // "")",
      "[ios][simulator] app_process status=\(.app.process.status) pid=\(.app.process.pid // "") name=\(.app.process.name)",
      "[ios][simulator] timings totalMs=\(.timings.totalMs) statusMs=\(.timings.statusMs) lifecycleMs=\(.timings.lifecycleMs) appProcessMs=\(.timings.appProcessMs)",
      (.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
    ' <<<"$payload"
  fi
  if [[ "$(jq -r '.status' <<<"$payload")" == "error" ]]; then
    return 1
  fi
}

cmd_simulator_ensure_booted() {
  local json=0 device_selector="$DEFAULT_SIMULATOR_NAME"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --device) device_selector="${2:?--device needs value}"; shift 2 ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh simulator ensure-booted [--device <udid|name>] [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown simulator ensure-booted option: $1" >&2
        return 1
        ;;
    esac
  done

  local resolve_payload resolve_status resolve_errors device_json resolved_device already_booted
  local generated_at boot_out boot_err wait_out wait_err rc_boot=0 rc_wait=0 payload
  local start_ms end_ms resolve_start_ms resolve_end_ms boot_start_ms boot_end_ms wait_start_ms wait_end_ms total_ms resolve_ms boot_ms wait_ms
  start_ms="$(simulator_now_ms)"
  resolve_start_ms="$(simulator_now_ms)"
  resolve_payload="$(simulator_resolve_selector_json "$device_selector")"
  resolve_end_ms="$(simulator_now_ms)"
  resolve_status="$(jq -r '.status' <<<"$resolve_payload")"
  resolve_ms=$(( resolve_end_ms - resolve_start_ms ))
  if [[ "$resolve_status" != "ok" ]]; then
    end_ms="$(simulator_now_ms)"
    total_ms=$(( end_ms - start_ms ))
    payload="$(jq -n \
      --arg schema "kg.ios.simulator.v1" \
      --arg generated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg selector "$device_selector" \
      --argjson resolve "$resolve_payload" \
      --argjson totalMs "$total_ms" \
      --argjson resolveMs "$resolve_ms" '
      {
        schema:$schema,
        generated_at:$generated_at,
        action:"ensure-booted",
        status:"error",
        selector:$selector,
        device:$resolve.device,
        boot:{status:"error",exitCode:null,output:null,error:"unresolved-device-selector",wasAlreadyBooted:false,waitedForBootstatus:false},
        timings:{totalMs:$totalMs,resolveMs:$resolveMs,bootMs:0,bootstatusMs:0},
        errors:$resolve.errors
      }')"
    if (( json )); then
      printf '%s\n' "$payload"
    else
      jq -r '
        "[ios][simulator] schema=\(.schema) action=\(.action) status=\(.status) selector=\(.selector)",
        (.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
      ' <<<"$payload"
    fi
    return 1
  fi

  device_json="$(jq -c '.device' <<<"$resolve_payload")"
  resolved_device="$(jq -r '.device.udid' <<<"$resolve_payload")"
  already_booted="$(jq -r '.device.state == "Booted"' <<<"$resolve_payload")"
  boot_out="$(mktemp)"
  boot_err="$(mktemp)"
  wait_out="$(mktemp)"
  wait_err="$(mktemp)"
  boot_ms=0
  wait_ms=0

  if [[ "$already_booted" == "true" ]]; then
    printf 'already booted\n' >"$boot_out"
    printf 'bootstatus skipped: already booted\n' >"$wait_out"
  else
    boot_start_ms="$(simulator_now_ms)"
    if read_simctl_boot_output "$resolved_device" >"$boot_out" 2>"$boot_err"; then
      rc_boot=0
    else
      rc_boot=$?
    fi
    boot_end_ms="$(simulator_now_ms)"
    boot_ms=$(( boot_end_ms - boot_start_ms ))
    if [[ "$rc_boot" -eq 0 ]]; then
      wait_start_ms="$(simulator_now_ms)"
      if read_simctl_bootstatus_output "$resolved_device" >"$wait_out" 2>"$wait_err"; then
        rc_wait=0
      else
        rc_wait=$?
      fi
      wait_end_ms="$(simulator_now_ms)"
      wait_ms=$(( wait_end_ms - wait_start_ms ))
    fi
  fi

  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  end_ms="$(simulator_now_ms)"
  total_ms=$(( end_ms - start_ms ))
  payload="$(jq -n \
    --arg schema "kg.ios.simulator.v1" \
    --arg generated_at "$generated_at" \
    --arg selector "$device_selector" \
    --argjson device "$device_json" \
    --arg bootOutput "$(cat "$boot_out")" \
    --arg bootError "$(cat "$boot_err")" \
    --arg waitOutput "$(cat "$wait_out")" \
    --arg waitError "$(cat "$wait_err")" \
    --argjson bootExit "$rc_boot" \
    --argjson waitExit "$rc_wait" \
    --argjson alreadyBooted "$already_booted" \
    --argjson totalMs "$total_ms" \
    --argjson resolveMs "$resolve_ms" \
    --argjson bootMs "$boot_ms" \
    --argjson bootstatusMs "$wait_ms" '
      def trim_newlines: gsub("\\n+$"; "");
      {
        schema:$schema,
        generated_at:$generated_at,
        action:"ensure-booted",
        status:(if $bootExit == 0 and $waitExit == 0 then "ok" else "error" end),
        selector:$selector,
        device:($device + {state:"Booted"}),
        boot:{
          status:(if $bootExit == 0 and $waitExit == 0 then "ok" else "error" end),
          exitCode:(if $bootExit != 0 then $bootExit else $waitExit end),
          output:(
            (($bootOutput | trim_newlines) + (if ($waitOutput | trim_newlines) == "" then "" else "\n" + ($waitOutput | trim_newlines) end))
            | if . == "" then null else . end
          ),
          error:(
            if $bootExit != 0 then ($bootError | trim_newlines)
            elif $waitExit != 0 then ($waitError | trim_newlines)
            else null
            end
          ),
          wasAlreadyBooted:$alreadyBooted,
          waitedForBootstatus:(if $alreadyBooted then true else ($bootExit == 0) end)
        },
        timings:{
          totalMs:$totalMs,
          resolveMs:$resolveMs,
          bootMs:$bootMs,
          bootstatusMs:$bootstatusMs
        },
        errors:(
          []
          + (if $bootExit != 0 then [{key:"simctl-boot",status:"error",exitCode:$bootExit,error:($bootError | trim_newlines)}] else [] end)
          + (if $bootExit == 0 and $waitExit != 0 then [{key:"simctl-bootstatus",status:"error",exitCode:$waitExit,error:($waitError | trim_newlines)}] else [] end)
        )
      }')"
  rm -f "$boot_out" "$boot_err" "$wait_out" "$wait_err"

  if (( json )); then
    printf '%s\n' "$payload"
  else
    jq -r '
      "[ios][simulator] schema=\(.schema) action=\(.action) status=\(.status) selector=\(.selector) device=\(.device.udid // "")",
      "[ios][simulator] boot status=\(.boot.status) exitCode=\(.boot.exitCode // "") wasAlreadyBooted=\(.boot.wasAlreadyBooted) waitedForBootstatus=\(.boot.waitedForBootstatus)",
      "[ios][simulator] timings totalMs=\(.timings.totalMs) resolveMs=\(.timings.resolveMs) bootMs=\(.timings.bootMs) bootstatusMs=\(.timings.bootstatusMs)",
      (.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
    ' <<<"$payload"
  fi

  [[ "$(jq -r '.status' <<<"$payload")" == "ok" ]]
}

# ── Simulator lease pool ──────────────────────────────────────────────────
# A bounded pool of pre-named simulators (kg-pool-1..N) that parallel agents
# claim one-at-a-time so their test runs don't contend on a single shared
# device. Leasing is cross-process (lease and release are separate ios_ops
# invocations), so we use an atomic mkdir-based claim under a lease root rather
# than flock (which only holds while the locking process lives). A lease older
# than KG_IOS_SIM_LEASE_TTL is treated as stale and reclaimed, so a crashed
# agent never wedges a pool slot permanently.
SIM_LEASE_ROOT="${KG_IOS_SIM_LEASE_ROOT:-/tmp/kg-sim-leases}"
SIM_POOL_PREFIX="${KG_IOS_SIM_POOL_PREFIX:-kg-pool}"
SIM_POOL_SIZE="${KG_IOS_SIM_POOL_SIZE:-3}"
SIM_POOL_DEVICE_TYPE="${KG_IOS_SIM_POOL_DEVICE_TYPE:-iPhone 17 Pro Max}"
SIM_LEASE_TTL="${KG_IOS_SIM_LEASE_TTL:-1800}"

simulator_device_state() {
  # Print the simctl state ("Booted"/"Shutdown"/...) of UDID $1, or empty.
  xcrun simctl list devices --json 2>/dev/null \
    | jq -r --arg u "$1" '[.devices[]?[]? | select(.udid==$u)][0].state // empty'
}

simulator_pool_ensure_device() {
  # Ensure a simulator named $1 exists; print its UDID (create if missing).
  local name="$1" udid devtype runtime errf
  udid="$(xcrun simctl list devices --json 2>/dev/null \
    | jq -r --arg n "$name" '[.devices[]?[]? | select(.name==$n)][0].udid // empty')"
  if [[ -z "$udid" ]]; then
    devtype="$(xcrun simctl list devicetypes --json 2>/dev/null \
      | jq -r --arg d "$SIM_POOL_DEVICE_TYPE" '[.devicetypes[] | select(.name==$d)][0].identifier // empty')"
    if [[ -n "${KG_IOS_SIM_POOL_RUNTIME:-}" ]]; then
      runtime="$KG_IOS_SIM_POOL_RUNTIME"
    else
      # Newest available iOS runtime — sorted NUMERICALLY by version (simctl does
      # not guarantee array order, and lexical sort mis-ranks e.g. 9.0 vs 18.6).
      runtime="$(xcrun simctl list runtimes --json 2>/dev/null \
        | jq -r '[.runtimes[] | select(.isAvailable==true and (.identifier|test("iOS")))]
                 | sort_by(.version | split(".") | map(tonumber)) | last | .identifier // empty')"
    fi
    if [[ -z "$devtype" || -z "$runtime" ]]; then
      echo "[ios_ops] error: cannot resolve device type ('$SIM_POOL_DEVICE_TYPE'->'${devtype:-?}') or iOS runtime ('${runtime:-?}') for pool device $name" >&2
      return 1
    fi
    errf="$(mktemp)"
    if ! udid="$(xcrun simctl create "$name" "$devtype" "$runtime" 2>"$errf")"; then
      echo "[ios_ops] error: simctl create $name ($devtype, $runtime) failed: $(cat "$errf")" >&2
      rm -f "$errf"; return 1
    fi
    rm -f "$errf"
  fi
  [[ -n "$udid" ]] || return 1
  printf '%s' "$udid"
}

simulator_lease_is_stale() {
  local leasedir="$1" created
  created="$(cat "$leasedir/created_at" 2>/dev/null)"
  # No timestamp yet = a slot claimed but not finished initializing. Treat as
  # LIVE (not stale) so a concurrent lease never reclaims a just-claimed slot.
  [[ -n "$created" ]] || return 1
  (( $(date +%s) - created > SIM_LEASE_TTL ))
}

cmd_simulator_lease() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh simulator lease [--json]  # claim a pool simulator, boot it, print its UDID"
        return 0 ;;
      *) echo "✗ unknown simulator lease option: $1" >&2; return 1 ;;
    esac
  done
  mkdir -p "$SIM_LEASE_ROOT"
  local i name leasedir udid
  for (( i=1; i<=SIM_POOL_SIZE; i++ )); do
    name="${SIM_POOL_PREFIX}-${i}"
    leasedir="$SIM_LEASE_ROOT/$name"
    if ! mkdir "$leasedir" 2>/dev/null; then
      # Occupied — only reclaim if stale, and ATOMICALLY: a single `mv` can win
      # the stale dir (two racers cannot both move the same dir away), then one
      # `mkdir` wins the freed slot. This avoids the rm+mkdir window where two
      # processes could both end up "holding" the same slot.
      simulator_lease_is_stale "$leasedir" || continue
      if mv "$leasedir" "${leasedir}.reclaim.$$" 2>/dev/null; then
        rm -rf "${leasedir}.reclaim.$$" 2>/dev/null || true
      fi
      mkdir "$leasedir" 2>/dev/null || continue
    fi
    # Slot is ours. Write created_at FIRST so a concurrent stale-check never sees
    # us timestamp-less and reclaims a live lease. Any failure below frees the
    # slot so we never leak a zombie lease dir.
    date +%s > "$leasedir/created_at" 2>/dev/null || { rm -rf "$leasedir" 2>/dev/null; continue; }
    udid="$(simulator_pool_ensure_device "$name")" || { rm -rf "$leasedir" 2>/dev/null; continue; }
    [[ -n "$udid" ]] || { rm -rf "$leasedir" 2>/dev/null; continue; }
    printf '%s' "$udid" > "$leasedir/udid" 2>/dev/null || { rm -rf "$leasedir" 2>/dev/null; continue; }
    printf '%s' "$$" > "$leasedir/owner_pid" 2>/dev/null || true
    # Boot, and surface a real boot failure instead of returning ok with a dead
    # device. `simctl boot` errors when already booted, so on its failure we
    # re-check the state and only treat NON-Booted as a true failure.
    if ! xcrun simctl bootstatus "$udid" -b >/dev/null 2>&1 \
       && ! xcrun simctl boot "$udid" >/dev/null 2>&1 \
       && [[ "$(simulator_device_state "$udid")" != "Booted" ]]; then
      echo "[ios_ops] error: failed to boot leased simulator $name ($udid); trying next slot" >&2
      rm -rf "$leasedir" 2>/dev/null || true
      continue
    fi
    if [[ "$json" -eq 1 ]]; then
      jq -nc --arg name "$name" --arg udid "$udid" --arg leaseDir "$leasedir" \
        '{schema:"kg.ios.sim-lease.v1", status:"ok", name:$name, udid:$udid, leaseDir:$leaseDir}'
    else
      printf '%s\n' "$udid"
    fi
    return 0
  done
  if [[ "$json" -eq 1 ]]; then
    jq -nc --argjson size "$SIM_POOL_SIZE" '{schema:"kg.ios.sim-lease.v1", status:"error", error:("pool-exhausted:"+($size|tostring))}'
  else
    echo "✗ simulator pool exhausted (size=$SIM_POOL_SIZE) — raise KG_IOS_SIM_POOL_SIZE or release leases" >&2
  fi
  return 1
}

cmd_simulator_release() {
  local json=0 target="" shutdown=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --shutdown) shutdown=1; shift ;;
      --device|--name)
        [[ $# -ge 2 ]] || { echo "✗ $1 requires a value (udid or pool name)" >&2; return 1; }
        target="$2"; shift 2 ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh simulator release [--device <udid|name>] [--shutdown] [--json]"
        return 0 ;;
      *) [[ -z "$target" ]] && { target="$1"; shift; } || { echo "✗ unknown simulator release option: $1" >&2; return 1; } ;;
    esac
  done
  [[ -n "$target" ]] || { echo "✗ simulator release requires --device <udid|name>" >&2; return 1; }
  local leasedir udid name=""
  # Resolve the lease dir: target may be the pool name or the leased UDID.
  if [[ -d "$SIM_LEASE_ROOT/$target" ]]; then
    name="$target"
  else
    for leasedir in "$SIM_LEASE_ROOT"/*; do
      [[ -d "$leasedir" ]] || continue
      if [[ "$(cat "$leasedir/udid" 2>/dev/null)" == "$target" ]]; then name="$(basename "$leasedir")"; break; fi
    done
  fi
  if [[ -z "$name" ]]; then
    if [[ "$json" -eq 1 ]]; then jq -nc --arg t "$target" '{schema:"kg.ios.sim-release.v1",status:"noop",error:("no-active-lease:"+$t)}'
    else echo "[ios_ops] no active lease for '$target' (already released?)"; fi
    return 0
  fi
  leasedir="$SIM_LEASE_ROOT/$name"
  udid="$(cat "$leasedir/udid" 2>/dev/null)"
  [[ "$shutdown" -eq 1 && -n "$udid" ]] && xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true
  rm -rf "$leasedir" 2>/dev/null || true
  if [[ "$json" -eq 1 ]]; then
    jq -nc --arg name "$name" --arg udid "$udid" --argjson shutdown "$shutdown" \
      '{schema:"kg.ios.sim-release.v1", status:"ok", name:$name, udid:$udid, shutdown:($shutdown==1)}'
  else
    echo "[ios_ops] released lease $name${udid:+ (udid=$udid)}$([[ $shutdown -eq 1 ]] && echo ', shut down')"
  fi
}

cmd_simulator() {
  local action="${1:-status}"
  [[ $# -gt 0 ]] && shift || true
  case "$action" in
    status)
      local json=0
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --json) json=1; shift ;;
          -h|--help|help)
            echo "Usage: ./ops/ios_ops.sh simulator status [--json]"
            return 0
            ;;
          *)
            echo "✗ unknown simulator status option: $1" >&2
            return 1
            ;;
        esac
      done
      cmd_simulator_status "$json"
      ;;
    screenshot)
      cmd_simulator_screenshot "$@"
      ;;
    launch)
      cmd_simulator_lifecycle launch "$@"
      ;;
    ensure-booted|boot)
      cmd_simulator_ensure_booted "$@"
      ;;
    terminate|stop)
      cmd_simulator_lifecycle terminate "$@"
      ;;
    lease)
      cmd_simulator_lease "$@"
      ;;
    release|unlease)
      cmd_simulator_release "$@"
      ;;
    -h|--help|help)
      echo "Usage: ./ops/ios_ops.sh simulator status [--json] | ensure-booted [--device <udid|name>] [--json] | lease [--json] | release [--device <udid|name>] [--shutdown] [--json] | launch [--device booted] [--json] [-- app args...] | terminate [--device booted] [--json] | screenshot --out <png> [--device booted] [--json]"
      ;;
    *)
      echo "✗ unknown simulator action: $action" >&2
      return 1
      ;;
  esac
}
