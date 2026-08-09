#!/usr/bin/env bash
# Sourceable agent-only Catalog launcher for ios_ops.sh.

# shellcheck source=fixture_dataset_env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fixture_dataset_env.sh"

CATALOG_SESSION_ROOT="${KG_IOS_CATALOG_SESSION_ROOT:-$ROOT/.cache/catalog-agent}"
CATALOG_ACTIVE_SESSION=""
CATALOG_ACTIVE_UDID=""
CATALOG_ACTIVE_KEEPER_PID=""
CATALOG_ACTIVE_LEASE_DIR=""
CATALOG_ACTIVE_SESSION_MAX_SECONDS=""
CATALOG_RELEASE_JSON=""

catalog_start_keeper() {
  local session="$1" lifetime_seconds="$2"
  [[ "$lifetime_seconds" =~ ^[0-9]+$ && "$lifetime_seconds" -gt 0 ]] || {
    echo "✗ Catalog keeper lifetime must be a positive integer" >&2
    return 1
  }

  # Keep the lease alive after the short-lived `catalog open` process exits,
  # but stop at the pool TTL so a forgotten session can become reclaimable.
  nohup bash -c '
    limit="$1"
    while (( SECONDS < limit )); do
      remaining=$((limit - SECONDS))
      (( remaining > 15 )) && sleep 15 || sleep "$remaining"
    done
  ' "$session" "$lifetime_seconds" </dev/null >/dev/null 2>&1 &
  CATALOG_ACTIVE_KEEPER_PID="$!"
  disown "$CATALOG_ACTIVE_KEEPER_PID" 2>/dev/null || true
}

catalog_stop_keeper() {
  local session="$1" keeper_pid="$2" command=""
  [[ "$keeper_pid" =~ ^[0-9]+$ ]] || return 0
  command="$(ps -p "$keeper_pid" -o command= 2>/dev/null || true)"
  if [[ "$command" == *"$session"* ]]; then
    kill "$keeper_pid" >/dev/null 2>&1 || true
  fi
}

catalog_disarm_cleanup() {
  trap - EXIT INT TERM HUP
}

catalog_abort_active_session() {
  local exit_status=$? state="" keeper_pid=""
  catalog_disarm_cleanup
  if [[ -n "$CATALOG_ACTIVE_SESSION" ]]; then
    state="$CATALOG_SESSION_ROOT/$CATALOG_ACTIVE_SESSION.json"
  fi
  if [[ -n "$state" && -f "$state" ]]; then
    keeper_pid="$(jq -r '.keeperPid // empty' "$state" 2>/dev/null || true)"
    catalog_release_session "$CATALOG_ACTIVE_SESSION" >/dev/null 2>&1 || true
  elif catalog_active_lease_is_current; then
    xcrun simctl terminate "$CATALOG_ACTIVE_UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
    xcrun simctl shutdown "$CATALOG_ACTIVE_UDID" >/dev/null 2>&1 || true
    xcrun simctl erase "$CATALOG_ACTIVE_UDID" >/dev/null 2>&1 || true
    cmd_simulator_release \
      --device "$CATALOG_ACTIVE_UDID" \
      --owner-token "$CATALOG_ACTIVE_SESSION" \
      --shutdown --json >/dev/null 2>&1 || true
  fi
  catalog_stop_keeper "$CATALOG_ACTIVE_SESSION" "${keeper_pid:-$CATALOG_ACTIVE_KEEPER_PID}"
  return "$exit_status"
}

catalog_arm_cleanup() {
  trap 'catalog_abort_active_session' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
}

catalog_active_lease_is_current() {
  [[ -n "$CATALOG_ACTIVE_SESSION" \
     && -n "$CATALOG_ACTIVE_UDID" \
     && -n "$CATALOG_ACTIVE_LEASE_DIR" \
     && "$CATALOG_ACTIVE_LEASE_DIR" == "$SIM_LEASE_ROOT"/* \
     && -d "$CATALOG_ACTIVE_LEASE_DIR" \
     && "$(cat "$CATALOG_ACTIVE_LEASE_DIR/udid" 2>/dev/null)" == "$CATALOG_ACTIVE_UDID" \
     && "$(cat "$CATALOG_ACTIVE_LEASE_DIR/owner_token" 2>/dev/null)" == "$CATALOG_ACTIVE_SESSION" ]]
}

catalog_usage() {
  cat <<'EOF'
Usage:
  ./ops/ios_ops.sh catalog list --dataset <name>|--dataset-file <path> [--appearance light|dark] [--json]
  ./ops/ios_ops.sh catalog open --dataset <name>|--dataset-file <path> [--scenario <category/title>] [--appearance light|dark] [--json]
  ./ops/ios_ops.sh catalog capture --session <id> --out <png> [--json]
  ./ops/ios_ops.sh catalog close --session <id> [--json]

Catalog is an agent-only, on-demand UI workbench. It launches a disposable
iOS Simulator with an explicit UI World and captures the real Simulator window.
It does not provide an export or release-artifact pipeline.
EOF
}

catalog_resolve_dataset() {
  local name="$1" file="$2"
  if [[ -n "$name" && -n "$file" ]]; then
    echo "✗ choose exactly one of --dataset or --dataset-file" >&2
    return 1
  fi
  if [[ -n "$name" ]]; then
    file="$ROOT/ops/fixtures/ui_worlds/$name.json"
  fi
  [[ -n "$file" ]] || {
    echo "✗ Catalog requires an explicit UI World: --dataset <name> or --dataset-file <path>" >&2
    return 1
  }
  [[ -f "$file" ]] || {
    echo "✗ UI World not found: $file" >&2
    return 1
  }
  printf '%s\n' "$(cd "$(dirname "$file")" && pwd)/$(basename "$file")"
}

catalog_shared_derived_data_root() {
  local common_dir
  common_dir="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$common_dir" && -d "$common_dir" ]]; then
    printf '%s/.cache/ios-build-derived-data\n' "$(dirname "$common_dir")"
  else
    printf '%s/.cache/ios-build-derived-data\n' "$ROOT"
  fi
}

catalog_emit() {
  local json="$1" payload="$2"
  if (( json )); then
    printf '%s\n' "$payload"
    return
  fi
  jq -r '
    "[ios][catalog] status=\(.status) action=\(.action) session=\(.session // \"\")",
    (if .device then "[ios][catalog] device=\(.device.udid) name=\(.device.name)" else empty end),
    (if .scenario then "[ios][catalog] scenario=\(.scenario)" else empty end),
    (if .artifact then "[ios][catalog] png=\(.artifact.path) \(.artifact.width)x\(.artifact.height)" else empty end),
    (if .sessionLifetimeSeconds then "[ios][catalog] keeper-lifetime=\(.sessionLifetimeSeconds)s" else empty end),
    (if .scenarios then (.scenarios[] | "[ios][catalog] \(.id)") else empty end),
    (if .closeCommand then "[ios][catalog] close=\(.closeCommand)" else empty end)
  ' <<<"$payload"
}

catalog_parse_world_options() {
  CATALOG_DATASET_NAME=""
  CATALOG_DATASET_FILE=""
  CATALOG_APPEARANCE="light"
  CATALOG_JSON=0
  CATALOG_SCENARIO=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dataset)
        [[ $# -ge 2 ]] || { echo "✗ --dataset requires a name" >&2; return 1; }
        CATALOG_DATASET_NAME="$2"; shift 2 ;;
      --dataset-file)
        [[ $# -ge 2 ]] || { echo "✗ --dataset-file requires a path" >&2; return 1; }
        CATALOG_DATASET_FILE="$2"; shift 2 ;;
      --appearance)
        [[ $# -ge 2 ]] || { echo "✗ --appearance requires light or dark" >&2; return 1; }
        CATALOG_APPEARANCE="$2"; shift 2 ;;
      --scenario)
        [[ $# -ge 2 ]] || { echo "✗ --scenario requires category/title" >&2; return 1; }
        CATALOG_SCENARIO="$2"; shift 2 ;;
      --json) CATALOG_JSON=1; shift ;;
      -h|--help|help) catalog_usage; return 2 ;;
      *) echo "✗ unknown Catalog option: $1" >&2; return 1 ;;
    esac
  done
  case "$CATALOG_APPEARANCE" in
    light|dark) ;;
    *) echo "✗ --appearance must be light or dark" >&2; return 1 ;;
  esac
  CATALOG_DATASET_FILE="$(catalog_resolve_dataset "$CATALOG_DATASET_NAME" "$CATALOG_DATASET_FILE")" || return 1
  "$ROOT/ops/ui_world_manifest.py" validate "$CATALOG_DATASET_FILE" --label catalog-agent >/dev/null
}

catalog_assert_session_ownership() {
  local session="$1" state lease_dir udid owner_token
  state="$CATALOG_SESSION_ROOT/$session.json"
  [[ -f "$state" ]] || {
    echo "✗ Catalog session not found: $session" >&2
    return 1
  }
  lease_dir="$(jq -r '.leaseDir // empty' "$state")"
  udid="$(jq -r '.udid' "$state")"
  owner_token="$(jq -r '.ownerToken' "$state")"
  [[ -n "$lease_dir" && "$lease_dir" == "$SIM_LEASE_ROOT"/* && -d "$lease_dir" ]] || {
    echo "✗ Catalog session no longer owns a live simulator lease: $session" >&2
    return 1
  }
  [[ "$(cat "$lease_dir/udid" 2>/dev/null)" == "$udid" \
     && "$(cat "$lease_dir/owner_token" 2>/dev/null)" == "$owner_token" ]] || {
    echo "✗ Catalog session lease ownership changed; refusing to touch simulator: $session" >&2
    return 1
  }
}

catalog_prepare_clean_simulator() {
  local udid="$1"
  xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true
  xcrun simctl erase "$udid" >/dev/null || {
    echo "✗ Catalog could not erase its disposable Simulator" >&2
    return 1
  }
  xcrun simctl boot "$udid" >/dev/null || {
    echo "✗ Catalog could not boot its erased Simulator" >&2
    return 1
  }
  uv run --python 3.13 python "$ROOT/ops/lib/streaming_command.py" \
    --cwd "$ROOT" \
    --label "catalog-boot:$CATALOG_ACTIVE_SESSION" \
    --heartbeat-interval "${KG_IOS_OPS_HEARTBEAT_INTERVAL:-20}" \
    --timeout-seconds "${KG_IOS_CATALOG_BOOT_TIMEOUT:-300}" \
    -- xcrun simctl bootstatus "$udid" -b >/dev/null || {
    echo "✗ Catalog disposable Simulator did not finish booting" >&2
    return 1
  }
}

catalog_release_session() {
  local session="$1" state udid owner_token keeper_pid release_json release_status
  state="$CATALOG_SESSION_ROOT/$session.json"
  catalog_assert_session_ownership "$session" || return 1
  udid="$(jq -r '.udid' "$state")"
  owner_token="$(jq -r '.ownerToken' "$state")"
  keeper_pid="$(jq -r '.keeperPid // empty' "$state")"
  xcrun simctl terminate "$udid" "$BUNDLE_ID" >/dev/null 2>&1 || true
  xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true
  xcrun simctl erase "$udid" >/dev/null || {
    echo "✗ Catalog could not erase its disposable Simulator during close" >&2
    return 1
  }
  # Release transfers the simulator back to the shared pool. From this point
  # onward an EXIT/signal trap must never run the destructive fallback against
  # the same UDID: another process may lease it immediately. If this command is
  # interrupted or refuses, the bounded keeper leaves the still-owned lease
  # recoverable instead of guessing that ownership survived.
  catalog_disarm_cleanup
  release_json="$(cmd_simulator_release --device "$udid" --owner-token "$owner_token" --json)" || return 1
  release_status="$(jq -r '.status' <<<"$release_json")"
  [[ "$release_status" == "ok" ]] || {
    echo "✗ Catalog simulator release refused: $(jq -r '.error // .status' <<<"$release_json")" >&2
    return 1
  }
  catalog_stop_keeper "$session" "$keeper_pid"
  rm -f "$state"
  CATALOG_RELEASE_JSON="$release_json"
}

catalog_wait_for_ready() {
  local ready_path="$1" session="$2" started elapsed last_report=0
  started="$(date +%s)"
  while [[ ! -s "$ready_path" ]]; do
    elapsed=$(( $(date +%s) - started ))
    if (( elapsed >= 45 )); then
      echo "✗ Catalog app did not report a visible window within 45s" >&2
      return 1
    fi
    if (( elapsed >= last_report + 5 )); then
      echo "[ios][catalog] phase=window-ready elapsed=${elapsed}s session=$session" >&2
      last_report="$elapsed"
    fi
    sleep 0.25
  done
  jq -e --arg session "$session" '.schema == "kg.ios.catalog-agent.ready.v1" and .session == $session' "$ready_path" >/dev/null || {
    echo "✗ Catalog app wrote an invalid readiness receipt" >&2
    return 1
  }
  if [[ "$(jq -r '.status' "$ready_path")" != "ok" ]]; then
    echo "✗ Catalog app rejected the request: $(jq -r '.error // "unknown"' "$ready_path")" >&2
    return 1
  fi
}

catalog_start_session() {
  local index_only="$1" dataset_file="$2" appearance="$3" scenario="$4"
  local lease_json lease_status lease_dir derived_data app_bundle build_log dataset_b64
  local launch_args data_container ready_path index_path

  CATALOG_ACTIVE_SESSION="catalog-$(date -u '+%Y%m%dT%H%M%SZ')-$$-$RANDOM"
  CATALOG_ACTIVE_UDID=""
  CATALOG_ACTIVE_LEASE_DIR=""
  CATALOG_ACTIVE_SESSION_MAX_SECONDS="${KG_IOS_CATALOG_SESSION_MAX_SECONDS:-${SIM_LEASE_TTL:-1800}}"
  [[ "$CATALOG_ACTIVE_SESSION_MAX_SECONDS" =~ ^[0-9]+$ \
     && "$CATALOG_ACTIVE_SESSION_MAX_SECONDS" -gt 0 ]] || {
    echo "✗ KG_IOS_CATALOG_SESSION_MAX_SECONDS must be a positive integer" >&2
    return 1
  }
  mkdir -p "$CATALOG_SESSION_ROOT"
  build_log="$CATALOG_SESSION_ROOT/$CATALOG_ACTIVE_SESSION.build.log"

  catalog_start_keeper "$CATALOG_ACTIVE_SESSION" "$CATALOG_ACTIVE_SESSION_MAX_SECONDS" || return 1
  catalog_arm_cleanup

  SIM_LEASE_OWNER_PID="$CATALOG_ACTIVE_KEEPER_PID"
  SIM_LEASE_OWNER_TOKEN="$CATALOG_ACTIVE_SESSION"
  lease_json="$(SIM_LEASE_SKIP_BOOT=1 cmd_simulator_lease --json)" || {
    echo "✗ Catalog could not lease a disposable Simulator" >&2
    return 1
  }
  lease_status="$(jq -r '.status' <<<"$lease_json")"
  if [[ "$lease_status" != "ok" ]]; then
    echo "✗ Catalog could not lease a disposable Simulator" >&2
    return 1
  fi
  CATALOG_ACTIVE_UDID="$(jq -r '.udid' <<<"$lease_json")"
  CATALOG_ACTIVE_DEVICE_NAME="$(jq -r '.name' <<<"$lease_json")"
  lease_dir="$(jq -r '.leaseDir' <<<"$lease_json")"
  CATALOG_ACTIVE_LEASE_DIR="$lease_dir"
  catalog_prepare_clean_simulator "$CATALOG_ACTIVE_UDID" || return 1

  if ! uv run --python 3.13 python "$ROOT/ops/lib/streaming_command.py" \
    --cwd "$ROOT" \
    --label "catalog-build:$CATALOG_ACTIVE_SESSION" \
    --heartbeat-interval "${KG_IOS_OPS_HEARTBEAT_INTERVAL:-20}" \
    --timeout-seconds "${KG_IOS_CATALOG_BUILD_TIMEOUT:-900}" \
    -- "$ROOT/ops/ios_build.sh" --destination "platform=iOS Simulator,id=$CATALOG_ACTIVE_UDID" \
    >"$build_log"; then
    echo "✗ Catalog build failed; log: $build_log" >&2
    return 1
  fi

  derived_data="$(catalog_shared_derived_data_root)"
  app_bundle="$derived_data/Build/Products/Debug-iphonesimulator/BooksAndVocab.app"
  if [[ ! -d "$app_bundle" ]]; then
    echo "✗ built app not found: $app_bundle" >&2
    return 1
  fi

  xcrun simctl install "$CATALOG_ACTIVE_UDID" "$app_bundle" >/dev/null || {
    echo "✗ Catalog app install failed" >&2
    return 1
  }
  xcrun simctl ui "$CATALOG_ACTIVE_UDID" appearance "$appearance" || {
    echo "✗ Catalog could not set simulator appearance" >&2
    return 1
  }
  data_container="$(xcrun simctl get_app_container "$CATALOG_ACTIVE_UDID" "$BUNDLE_ID" data)" || {
    echo "✗ Catalog could not resolve app data container" >&2
    return 1
  }
  ready_path="$data_container/Documents/catalog-agent/$CATALOG_ACTIVE_SESSION/ready.json"
  index_path="$data_container/Documents/catalog-agent/$CATALOG_ACTIVE_SESSION/index.json"
  dataset_b64="$(kg_fixture_dataset_deflate_b64 "$dataset_file")" || {
    echo "✗ Catalog could not encode UI World" >&2
    return 1
  }

  launch_args=(-ui-testing -skipWelcome -catalog -catalogAgentSession "$CATALOG_ACTIVE_SESSION")
  [[ -n "$scenario" ]] && launch_args+=(-catalogScenario "$scenario")
  (( index_only )) && launch_args+=(-catalogIndexOnly)
  if ! SIMCTL_CHILD_KG_FIXTURE_DATASET_DEFLATE_B64="$dataset_b64" \
    SIMCTL_CHILD_KG_UI_TEST_SERVER_URL="http://127.0.0.1:9" \
    xcrun simctl launch --terminate-running-process \
      "$CATALOG_ACTIVE_UDID" "$BUNDLE_ID" "${launch_args[@]}" >/dev/null; then
    echo "✗ Catalog launch failed" >&2
    return 1
  fi

  if ! jq -n \
    --arg session "$CATALOG_ACTIVE_SESSION" \
    --arg udid "$CATALOG_ACTIVE_UDID" \
    --arg name "$CATALOG_ACTIVE_DEVICE_NAME" \
    --arg ownerToken "$CATALOG_ACTIVE_SESSION" \
    --arg dataset "$dataset_file" \
    --arg appearance "$appearance" \
    --arg scenario "$scenario" \
    --arg readyPath "$ready_path" \
    --arg indexPath "$index_path" \
    --arg leaseDir "$lease_dir" \
    --argjson keeperPid "$CATALOG_ACTIVE_KEEPER_PID" \
    --argjson sessionMaxSeconds "$CATALOG_ACTIVE_SESSION_MAX_SECONDS" \
    '{
      schema:"kg.ios.catalog-agent.session.v1",
      session:$session,
      udid:$udid,
      deviceName:$name,
      ownerToken:$ownerToken,
      leaseDir:$leaseDir,
      keeperPid:$keeperPid,
      sessionMaxSeconds:$sessionMaxSeconds,
      dataset:$dataset,
      appearance:$appearance,
      scenario:(if $scenario == "" then null else $scenario end),
      readyPath:$readyPath,
      indexPath:$indexPath
    }' >"$CATALOG_SESSION_ROOT/$CATALOG_ACTIVE_SESSION.json"; then
    echo "✗ Catalog could not write session receipt" >&2
    return 1
  fi

  if ! catalog_wait_for_ready "$ready_path" "$CATALOG_ACTIVE_SESSION"; then
    catalog_release_session "$CATALOG_ACTIVE_SESSION" >/dev/null || true
    return 1
  fi
  CATALOG_ACTIVE_READY_PATH="$ready_path"
  CATALOG_ACTIVE_INDEX_PATH="$index_path"
}

catalog_list() {
  catalog_parse_world_options "$@"
  local parse_status=$?
  (( parse_status == 2 )) && return 0
  (( parse_status == 0 )) || return "$parse_status"
  [[ -z "$CATALOG_SCENARIO" ]] || { echo "✗ catalog list does not accept --scenario" >&2; return 1; }

  catalog_start_session 1 "$CATALOG_DATASET_FILE" "$CATALOG_APPEARANCE" "" || return 1
  local scenarios release payload
  scenarios="$(jq -ce '.scenarios | arrays' "$CATALOG_ACTIVE_INDEX_PATH")" || {
    echo "✗ Catalog app wrote an invalid scenario index" >&2
    return 1
  }
  catalog_release_session "$CATALOG_ACTIVE_SESSION" || return 1
  release="$CATALOG_RELEASE_JSON"
  payload="$(jq -n \
    --argjson scenarios "$scenarios" \
    --argjson release "$release" \
    '{schema:"kg.ios.catalog-agent.v1",status:"ok",action:"list",renderer:"simulator-window",scenarios:$scenarios,release:$release}')"
  catalog_emit "$CATALOG_JSON" "$payload"
}

catalog_open() {
  catalog_parse_world_options "$@"
  local parse_status=$?
  (( parse_status == 2 )) && return 0
  (( parse_status == 0 )) || return "$parse_status"

  catalog_start_session 0 "$CATALOG_DATASET_FILE" "$CATALOG_APPEARANCE" "$CATALOG_SCENARIO" || return 1
  local payload scenario_json
  scenario_json="$(jq -c '.scenario' "$CATALOG_ACTIVE_READY_PATH")"
  payload="$(jq -n \
    --arg session "$CATALOG_ACTIVE_SESSION" \
    --arg udid "$CATALOG_ACTIVE_UDID" \
    --arg name "$CATALOG_ACTIVE_DEVICE_NAME" \
    --arg dataset "$CATALOG_DATASET_FILE" \
    --arg appearance "$CATALOG_APPEARANCE" \
    --argjson scenario "$scenario_json" \
    --argjson sessionLifetimeSeconds "$CATALOG_ACTIVE_SESSION_MAX_SECONDS" \
    --arg closeCommand "./ops/ios_ops.sh catalog close --session $CATALOG_ACTIVE_SESSION" \
    '{
      schema:"kg.ios.catalog-agent.v1",status:"ok",action:"open",session:$session,
      renderer:"simulator-window",device:{udid:$udid,name:$name,appearance:$appearance},
      dataset:{path:$dataset},scenario:($scenario.id // null),
      sessionLifetimeSeconds:$sessionLifetimeSeconds,closeCommand:$closeCommand
    }')"
  catalog_emit "$CATALOG_JSON" "$payload"
  catalog_disarm_cleanup
}

catalog_capture() {
  local session="" out="" json=0 state udid absolute_out width height sha payload
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --session) [[ $# -ge 2 ]] || { echo "✗ --session requires an id" >&2; return 1; }; session="$2"; shift 2 ;;
      --out) [[ $# -ge 2 ]] || { echo "✗ --out requires a PNG path" >&2; return 1; }; out="$2"; shift 2 ;;
      --json) json=1; shift ;;
      -h|--help|help) catalog_usage; return 0 ;;
      *) echo "✗ unknown catalog capture option: $1" >&2; return 1 ;;
    esac
  done
  [[ "$session" =~ ^catalog-[A-Za-z0-9T-]+$ ]] || { echo "✗ invalid Catalog session id" >&2; return 1; }
  [[ -n "$out" && "${out##*.}" == "png" ]] || { echo "✗ --out must end in .png" >&2; return 1; }
  state="$CATALOG_SESSION_ROOT/$session.json"
  [[ -f "$state" ]] || { echo "✗ Catalog session not found: $session" >&2; return 1; }
  catalog_assert_session_ownership "$session" || return 1
  udid="$(jq -r '.udid' "$state")"
  mkdir -p "$(dirname "$out")"
  absolute_out="$(cd "$(dirname "$out")" && pwd)/$(basename "$out")"
  xcrun simctl io "$udid" screenshot --type=png "$absolute_out" >/dev/null
  width="$(sips -g pixelWidth "$absolute_out" | awk '/pixelWidth/{print $2}')"
  height="$(sips -g pixelHeight "$absolute_out" | awk '/pixelHeight/{print $2}')"
  sha="$(shasum -a 256 "$absolute_out" | awk '{print $1}')"
  payload="$(jq -n \
    --arg session "$session" --arg path "$absolute_out" --arg sha "$sha" \
    --argjson width "$width" --argjson height "$height" \
    '{schema:"kg.ios.catalog-agent.v1",status:"ok",action:"capture",session:$session,
      renderer:"simulator-window",artifact:{path:$path,sha256:$sha,width:$width,height:$height}}')"
  catalog_emit "$json" "$payload"
}

catalog_close() {
  local session="" json=0 release payload state
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --session) [[ $# -ge 2 ]] || { echo "✗ --session requires an id" >&2; return 1; }; session="$2"; shift 2 ;;
      --json) json=1; shift ;;
      -h|--help|help) catalog_usage; return 0 ;;
      *) echo "✗ unknown catalog close option: $1" >&2; return 1 ;;
    esac
  done
  [[ "$session" =~ ^catalog-[A-Za-z0-9T-]+$ ]] || { echo "✗ invalid Catalog session id" >&2; return 1; }
  state="$CATALOG_SESSION_ROOT/$session.json"
  [[ -f "$state" ]] || { echo "✗ Catalog session not found: $session" >&2; return 1; }
  CATALOG_ACTIVE_SESSION="$session"
  CATALOG_ACTIVE_UDID="$(jq -r '.udid' "$state")"
  CATALOG_ACTIVE_LEASE_DIR="$(jq -r '.leaseDir' "$state")"
  catalog_arm_cleanup
  catalog_release_session "$session" || return 1
  release="$CATALOG_RELEASE_JSON"
  payload="$(jq -n --arg session "$session" --argjson release "$release" \
    '{schema:"kg.ios.catalog-agent.v1",status:"ok",action:"close",session:$session,release:$release}')"
  catalog_emit "$json" "$payload"
}

cmd_catalog() {
  local action="${1:-help}"
  [[ $# -gt 0 ]] && shift || true
  case "$action" in
    list) catalog_list "$@" ;;
    open) catalog_open "$@" ;;
    capture) catalog_capture "$@" ;;
    close) catalog_close "$@" ;;
    -h|--help|help) catalog_usage ;;
    snapshots|prepare|clean)
      echo "✗ Catalog '$action' was removed. Use list/open/capture/close." >&2
      return 2 ;;
    *) echo "✗ unknown catalog action: $action" >&2; catalog_usage >&2; return 1 ;;
  esac
}
