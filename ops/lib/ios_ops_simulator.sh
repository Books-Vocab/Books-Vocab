#!/usr/bin/env bash
# ios_ops_simulator.sh — sourceable simulator status/screenshot commands for ios_ops.sh.

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

cmd_simulator_status_json() {
  local devices_source container_source process_source generated_at payload status
  devices_source="$(capture_source_json simctl_devices read_simctl_devices_json)"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  local booted_udid
  booted_udid="$(jq -r '[.payload.devices // {} | to_entries[]?.value[]? | select(.state == "Booted")][0].udid // empty' <<<"$devices_source")"
  if [[ -n "$booted_udid" ]]; then
    container_source="$(capture_source_text app_container read_app_container_path "$booted_udid" "$BUNDLE_ID" data)"
    process_source="$(capture_source_text app_process read_app_process_pid "$booted_udid" "$SCHEME")"
  else
    container_source='null'
    process_source='null'
  fi

  payload="$(jq -n \
    --arg schema "kg.ios.simulator.v1" \
    --arg generated_at "$generated_at" \
    --arg bundle_id "$BUNDLE_ID" \
    --argjson devicesSource "$devices_source" \
    --argjson containerSource "$container_source" \
    --argjson processSource "$process_source" \
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
  status_payload="$(cmd_simulator_status_json)" || status_rc=$?
  if (( status_rc != 0 )); then
    payload="$(jq -n \
      --arg schema "kg.ios.simulator.v1" \
      --arg generated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg out "$out" \
      --argjson statusPayload "$status_payload" \
      '{
        schema:$schema,
        generated_at:$generated_at,
        action:"screenshot",
        status:"error",
        device:null,
        artifact:{path:$out,exists:false,bytes:0},
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
  if mkdir -p "$(dirname "$out")" 2>"$err" && write_simulator_screenshot "$resolved_device" "$out" 2>>"$err"; then
    rc=0
  else
    rc=$?
  fi
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
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
    '{
      schema:$schema,
      generated_at:$generated_at,
      action:"screenshot",
      status:(if $rc == 0 then "ok" else "error" end),
      device:$device,
      artifact:{path:$out,exists:$exists,bytes:$bytes},
      errors:(if $rc == 0 then [] else [{key:"screenshot",status:"error",exitCode:$rc,error:$stderr}] end)
    }')"
  rm -f "$err"

  if (( json )); then
    printf '%s\n' "$payload"
  else
    jq -r '
      "[ios][simulator] schema=\(.schema) action=\(.action) status=\(.status) device=\(.device.udid // "") artifact=\(.artifact.path) exists=\(.artifact.exists) bytes=\(.artifact.bytes)",
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
  status_payload="$(cmd_simulator_status_json)" || status_rc=$?
  if [[ "$device_selector" == "booted" ]]; then
    if (( status_rc != 0 )); then
      payload="$(jq -n \
        --arg schema "kg.ios.simulator.v1" \
        --arg generated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        --arg action "$action" \
        --arg bundle_id "$BUNDLE_ID" \
        --argjson statusPayload "$status_payload" \
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
  process_source="$(capture_source_text app_process read_app_process_pid "$resolved_device" "$SCHEME")"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

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
      (.errors[]? | "[ios][simulator] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
    ' <<<"$payload"
  fi
  if [[ "$(jq -r '.status' <<<"$payload")" == "error" ]]; then
    return 1
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
    terminate|stop)
      cmd_simulator_lifecycle terminate "$@"
      ;;
    -h|--help|help)
      echo "Usage: ./ops/ios_ops.sh simulator status [--json] | launch [--device booted] [--json] [-- app args...] | terminate [--device booted] [--json] | screenshot --out <png> [--device booted] [--json]"
      ;;
    *)
      echo "✗ unknown simulator action: $action" >&2
      return 1
      ;;
  esac
}
