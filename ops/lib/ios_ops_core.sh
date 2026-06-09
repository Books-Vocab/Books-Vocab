ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$ROOT/ios/BooksAndVocab.xcodeproj"
SCHEME="BooksAndVocab"
BUNDLE_ID="com.Max0228.BooksBrowser"
DEFAULT_SIMULATOR_NAME="${KG_IOS_DEFAULT_SIMULATOR_NAME:-iPhone 17 Pro Max}"
DEFAULT_LOG_PREDICATE='process == "BooksAndVocab" OR subsystem BEGINSWITH "com.Max0228.BooksBrowser"'
LOG_NOISE_REGEX='runningboard\.assertions\.webkit|RBSServiceErrorDomain|ProcessAssertion'

read_project_settings() {
  local __version_var="$1" __build_var="$2" settings _version _build
  settings="$(xcodebuild -project "$XCODEPROJ" -target "$SCHEME" -configuration Release -showBuildSettings 2>/dev/null || true)"
  _version="$(awk -F' = ' '/ MARKETING_VERSION /{print $2; exit}' <<<"$settings" | tr -d '[:space:]')"
  _build="$(awk -F' = ' '/ CURRENT_PROJECT_VERSION /{print $2; exit}' <<<"$settings" | tr -d '[:space:]')"
  printf -v "$__version_var" '%s' "$_version"
  printf -v "$__build_var" '%s' "$_build"
}

read_organizer_latest() {
  "$SCRIPT_DIR/ios_archive.sh" latest 2>/dev/null | tail -1 || true
}

read_testflight_latest_build() {
  "$SCRIPT_DIR/asc.sh" builds 2>/dev/null | grep -Eo '[0-9]+' | tail -1 || true
}

read_asc_version_state() {
  local tmp pid waited=0
  tmp="$(mktemp)"
  "$SCRIPT_DIR/asc.sh" versions >"$tmp" 2>/dev/null &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if (( waited >= 12 )); then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      rm -f "$tmp"
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid" 2>/dev/null || true
  sed -n '/[^[:space:]]/p' "$tmp" | head -1
  rm -f "$tmp"
}

read_xcode_version_text() {
  local version developer_dir
  version="$(xcodebuild -version)" || return $?
  developer_dir="$(xcode-select -p)" || return $?
  printf '%s\nDeveloperDir %s\n' "$version" "$developer_dir"
}

read_xcode_project_list_json() {
  xcodebuild -list -json -project "$XCODEPROJ"
}

read_xcode_destinations_text() {
  xcodebuild -showdestinations -project "$XCODEPROJ" -scheme "$SCHEME"
}

read_simctl_devices_json() {
  xcrun simctl list devices --json
}

read_app_container_path() {
  local device="$1" bundle_id="$2" kind="${3:-data}"
  xcrun simctl get_app_container "$device" "$bundle_id" "$kind"
}

read_app_process_pid() {
  local device="$1" process_name="$2"
  local pid
  pid="$(
    ps -axo pid=,command= \
      | awk -v device="$device" -v needle="/${process_name}.app/${process_name}" '
          index($0, device) && index($0, needle) { print $1; exit }
        '
  )"
  if [[ -n "$pid" ]]; then
    printf '%s\n' "$pid"
    return 0
  fi
  return 1
}

read_app_launch_output() {
  local device="$1" bundle_id="$2"
  shift 2
  xcrun simctl launch "$device" "$bundle_id" "$@"
}

read_app_terminate_output() {
  local device="$1" bundle_id="$2"
  xcrun simctl terminate "$device" "$bundle_id"
}

write_simulator_screenshot() {
  local device="$1" out="$2"
  xcrun simctl io "$device" screenshot "$out"
}

read_simctl_boot_output() {
  local device="$1"
  xcrun simctl boot "$device"
}

read_simctl_bootstatus_output() {
  local device="$1"
  xcrun simctl bootstatus "$device" -b
}

capture_source_text() {
  local key="$1"; shift
  local tmp rc
  tmp="$(mktemp)"
  if "$@" >"$tmp" 2>/dev/null; then
    rc=0
  else
    rc=$?
  fi
  jq -n \
    --arg key "$key" \
    --arg status "$([[ "$rc" -eq 0 ]] && printf ok || printf error)" \
    --argjson exitCode "$rc" \
    --rawfile output "$tmp" \
    '{key:$key,status:$status,exitCode:$exitCode,output:$output,error:(if $exitCode == 0 then null else "command-failed" end)}'
  rm -f "$tmp"
}

capture_source_json() {
  local key="$1"; shift
  local tmp rc
  tmp="$(mktemp)"
  if "$@" >"$tmp" 2>/dev/null; then
    rc=0
  else
    rc=$?
  fi
  if [[ "$rc" -eq 0 ]] && jq -e . "$tmp" >/dev/null 2>&1; then
    jq -n \
      --arg key "$key" \
      --rawfile output "$tmp" \
      --argjson payload "$(cat "$tmp")" \
      '{key:$key,status:"ok",exitCode:0,payload:$payload,error:null,output:$output}'
  else
    jq -n \
      --arg key "$key" \
      --argjson exitCode "$rc" \
      --rawfile output "$tmp" \
      '{key:$key,status:"error",exitCode:$exitCode,payload:null,error:(if $exitCode == 0 then "invalid-json" else "command-failed" end),output:$output}'
  fi
  rm -f "$tmp"
}

if [[ "${KG_IOS_OPS_FIXTURE:-}" == "1" ]]; then
  read_project_settings() {
    local __version_var="$1" __build_var="$2"
    printf -v "$__version_var" '%s' "1.6"
    printf -v "$__build_var" '%s' "4"
  }

  read_organizer_latest() {
    printf '2026-06-07T05:00:00Z\tBooksAndVocab\tcom.Max0228.BooksBrowser\t1.6\t4\t/tmp/BooksAndVocab.xcarchive\n'
  }

  read_testflight_latest_build() {
    printf '%s\n' "${KG_IOS_OPS_FIXTURE_TF_LATEST:-3}"
  }

  read_asc_version_state() {
    printf '1.6 REJECTED\n'
  }

  read_xcode_version_text() {
    if [[ "${KG_IOS_OPS_XCODE_FAIL_FIXTURE:-}" == "1" ]]; then
      return 9
    fi
    cat <<'EOF'
Xcode 16.4
Build version 16F6
DeveloperDir /Applications/Xcode.app/Contents/Developer
EOF
  }

  read_xcode_project_list_json() {
    if [[ "${KG_IOS_OPS_XCODE_FAIL_FIXTURE:-}" == "1" ]]; then
      return 9
    fi
    jq -n '{
      project:{
        configurations:["Debug","Release"],
        name:"BooksAndVocab",
        schemes:["BooksAndVocab"],
        targets:["BooksAndVocab","BooksAndVocabTests","BooksAndVocabUITests"]
      }
    }'
  }

  read_xcode_destinations_text() {
    if [[ "${KG_IOS_OPS_XCODE_FAIL_FIXTURE:-}" == "1" ]]; then
      return 9
    fi
    cat <<'EOF'
Available destinations for the "BooksAndVocab" scheme:
    { platform:iOS Simulator, arch:arm64, id:fixture-iphone-17-pro-max, OS:26.4, name:iPhone 17 Pro Max }
    { platform:macOS, arch:arm64, variant:Mac Catalyst, id:fixture-my-mac, name:My Mac }
Ineligible destinations for the "BooksAndVocab" scheme:
    { platform:iOS Simulator, id:fixture-ineligible, OS:26.4, name:iPhone 17, error:OS mismatch, please download runtime }
EOF
  }

  read_simctl_devices_json() {
    if [[ "${KG_IOS_OPS_XCODE_FAIL_FIXTURE:-}" == "1" ]]; then
      return 9
    fi
    if [[ "${KG_IOS_OPS_SIM_NO_BOOTED_FIXTURE:-}" == "1" ]]; then
      jq -n '{
        devices:{
          "com.apple.CoreSimulator.SimRuntime.iOS-26-4":[
            {
              name:"iPhone 17 Pro Max",
              udid:"fixture-iphone-17-pro-max",
              state:"Shutdown",
              isAvailable:true,
              deviceTypeIdentifier:"com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max"
            },
            {
              name:"iPhone 17",
              udid:"fixture-iphone-17",
              state:"Shutdown",
              isAvailable:true,
              deviceTypeIdentifier:"com.apple.CoreSimulator.SimDeviceType.iPhone-17"
            }
          ]
        }
      }'
      return 0
    fi
    jq -n '{
      devices:{
        "com.apple.CoreSimulator.SimRuntime.iOS-26-4":[
          {
            name:"iPhone 17 Pro Max",
            udid:"fixture-iphone-17-pro-max",
            state:"Booted",
            isAvailable:true,
            deviceTypeIdentifier:"com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max",
            lastBootedAt:"2026-06-07T04:00:00Z"
          },
          {
            name:"iPhone 17",
            udid:"fixture-iphone-17",
            state:"Shutdown",
            isAvailable:true,
            deviceTypeIdentifier:"com.apple.CoreSimulator.SimDeviceType.iPhone-17"
          }
        ]
      }
    }'
  }

  read_app_container_path() {
    local device="$1" bundle_id="$2" kind="${3:-data}"
    [[ "$device" == "fixture-iphone-17-pro-max" && "$bundle_id" == "com.Max0228.BooksBrowser" && "$kind" == "data" ]] || return 9
    printf '/tmp/kg-sim-fixture/container\n'
  }

  read_app_process_pid() {
    local device="$1" process_name="$2"
    [[ "$device" == "fixture-iphone-17-pro-max" && "$process_name" == "BooksAndVocab" ]] || return 9
    if [[ "${KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE:-}" == "1" ]]; then
      return 1
    fi
    printf '74736\n'
  }

  read_app_launch_output() {
    local device="$1" bundle_id="$2"
    [[ "$device" == "fixture-iphone-17-pro-max" && "$bundle_id" == "com.Max0228.BooksBrowser" ]] || return 9
    export KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE=0
    printf '74736\n'
  }

  read_app_terminate_output() {
    local device="$1" bundle_id="$2"
    [[ "$device" == "fixture-iphone-17-pro-max" && "$bundle_id" == "com.Max0228.BooksBrowser" ]] || return 9
    export KG_IOS_OPS_SIM_APP_STOPPED_FIXTURE=1
  }

  write_simulator_screenshot() {
    local _device="$1" out="$2"
    mkdir -p "$(dirname "$out")"
    printf 'fixture png\n' >"$out"
  }

  read_simctl_boot_output() {
    local device="$1"
    [[ "$device" == "fixture-iphone-17-pro-max" || "$device" == "iPhone 17 Pro Max" ]] || return 9
    export KG_IOS_OPS_SIM_NO_BOOTED_FIXTURE=0
    printf 'booted %s\n' "$device"
  }

  read_simctl_bootstatus_output() {
    local device="$1"
    [[ "$device" == "fixture-iphone-17-pro-max" || "$device" == "iPhone 17 Pro Max" ]] || return 9
    printf 'bootstatus %s ready\n' "$device"
  }
fi

cleanup_tmp() {
  local path="$1" rc="${2:-0}"
  rm -f "$path"
  return "$rc"
}

verdict_file_for() {
  local kind="$1" base="${TMPDIR:-/tmp}"
  case "$kind" in
    build) printf '%s/kg_ios_build_verdict\n' "${base%/}" ;;
    test) printf '%s/kg_ios_test_verdict\n' "${base%/}" ;;
    archive) printf '%s/kg_ios_archive_verdict\n' "${base%/}" ;;
    *) return 1 ;;
  esac
}

verdict_json_file_for() {
  local kind="$1"
  printf '%s.json\n' "$(verdict_file_for "$kind")"
}

verdict_field() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  tr ' ' '\n' <"$file" | awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}'
}

path_exists_json_bool() {
  local kind="$1" path="$2"
  if [[ -z "$path" ]]; then
    printf 'false'
  elif [[ "$kind" == "dir" && -d "$path" ]]; then
    printf 'true'
  elif [[ "$kind" == "file" && -f "$path" ]]; then
    printf 'true'
  else
    printf 'false'
  fi
}
