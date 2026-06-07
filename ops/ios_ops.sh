#!/usr/bin/env bash
# ios_ops.sh — unified iOS ops entrypoint for agents and humans.
#
# Usage:
#   ./ops/ios_ops.sh status
#   ./ops/ios_ops.sh build [ios_build.sh args...]
#   ./ops/ios_ops.sh test [ios_test.sh args...]
#   ./ops/ios_ops.sh archive [--upload] [ios_release.sh args...]
#   ./ops/ios_ops.sh archives [list|latest|inspect ...]
#   ./ops/ios_ops.sh issues --log <xcodebuild.log> [--json]
#   ./ops/ios_ops.sh logs [--since 5m] [--predicate <predicate>]
#   ./ops/ios_ops.sh sentry
#   ./ops/ios_ops.sh doctor [--json]
#   ./ops/ios_ops.sh workflow release [--json]
#   ./ops/ios_ops.sh snapshot [--json]
#
# Side-effect model:
# - status/archives/issues/logs/sentry/doctor/workflow/snapshot/dashboard are read-only.
# - build/test/archive are local machine side effects.
# - archive only uploads when --upload is passed through explicitly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
XCODEPROJ="$ROOT/ios/BooksBrowser.xcodeproj"
SCHEME="BooksBrowser"

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }

cmd_status() {
  local version build
  read_project_settings version build
  echo "[ios][status] project_version=${version:-unknown} project_build=${build:-unknown}"
  "$SCRIPT_DIR/ios_archive.sh" latest 2>/dev/null | tail -1 | awk -F'\t' 'NF>=6 {printf "[ios][status] organizer_latest=%s(%s) archive=%s\n", $4, $5, $6}'
  "$SCRIPT_DIR/asc.sh" builds 2>/dev/null | sed 's/^/[ios][status] /' || true
}

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

if [[ "${KG_IOS_OPS_FIXTURE:-}" == "1" ]]; then
  read_project_settings() {
    local __version_var="$1" __build_var="$2"
    printf -v "$__version_var" '%s' "1.6"
    printf -v "$__build_var" '%s' "4"
  }

  read_organizer_latest() {
    printf '2026-06-07T05:00:00Z\tBooksBrowser\tcom.Max0228.BooksBrowser\t1.6\t4\t/tmp/BooksBrowser.xcarchive\n'
  }

  read_testflight_latest_build() {
    printf '3\n'
  }

  read_asc_version_state() {
    printf '1.6 REJECTED\n'
  }
fi

cleanup_tmp() {
  local path="$1" rc="${2:-0}"
  rm -f "$path"
  return "$rc"
}

emit_readiness() {
  local key="$1" status="$2" detail="$3"
  echo "[ios][readiness] $key status=$status $detail"
}

emit_readiness_json() {
  local out="$1" key="$2" status="$3" detail="$4"
  jq -nc --arg key "$key" --arg status "$status" --arg detail "$detail" \
    '{key:$key,status:$status,detail:$detail}' >>"$out"
}

emit_workflow_step() {
  local num="$1" key="$2" status="$3" command="$4" note="$5"
  echo "[ios][workflow] step=$num key=$key status=$status command=\"$command\" note=\"$note\""
}

emit_workflow_step_json() {
  local out="$1" num="$2" key="$3" status="$4" command="$5" note="$6"
  jq -nc --argjson step "$num" --arg key "$key" --arg status "$status" --arg command "$command" --arg note "$note" \
    '{step:$step,key:$key,status:$status,command:$command,note:$note}' >>"$out"
}

doctor_readiness() {
  local emitter="$1" out="${2:-}"
  local version build archive_line archive_version archive_build archive_path tf_latest
  read_project_settings version build
  if [[ -n "$version" && -n "$build" ]]; then
    "$emitter" "$out" "project" "ok" "version=$version build=$build"
  else
    "$emitter" "$out" "project" "warn" "version=${version:-unknown} build=${build:-unknown}"
  fi

  archive_line="$(read_organizer_latest)"
  if [[ -n "$archive_line" ]]; then
    archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
    archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"
    archive_path="$(awk -F'\t' '{print $6}' <<<"$archive_line")"
    if [[ "$archive_version" == "$version" && "$archive_build" == "$build" ]]; then
      "$emitter" "$out" "organizer" "ok" "latest=$archive_version($archive_build) archive=$archive_path"
    else
      "$emitter" "$out" "organizer" "warn" "latest=$archive_version($archive_build) project=$version($build) archive=$archive_path"
    fi
  else
    "$emitter" "$out" "organizer" "warn" "latest=unknown"
  fi

  tf_latest="$(read_testflight_latest_build)"
  if [[ -n "$tf_latest" && "$tf_latest" =~ ^[0-9]+$ && "$build" =~ ^[0-9]+$ ]]; then
    if (( build > tf_latest )); then
      "$emitter" "$out" "testflight" "ok" "latest=$tf_latest project_build=$build upload_allowed=true"
    else
      "$emitter" "$out" "testflight" "block" "latest=$tf_latest project_build=$build upload_allowed=false reason=build-number-not-increased"
    fi
  else
    "$emitter" "$out" "testflight" "warn" "latest=${tf_latest:-unknown} project_build=${build:-unknown}"
  fi

  local asc_state
  if asc_state="$(read_asc_version_state)"; then
    if [[ -n "$asc_state" ]]; then
      "$emitter" "$out" "asc_version" "ok" "latest=\"$asc_state\""
    else
      "$emitter" "$out" "asc_version" "warn" "latest=unknown"
    fi
  else
    "$emitter" "$out" "asc_version" "warn" "latest=timeout"
  fi

  if plutil -p "$ROOT/ios/ExportOptions.plist" 2>/dev/null | grep -q '"KG App Store"' \
     && plutil -p "$ROOT/ios/ExportOptions.plist" 2>/dev/null | grep -q '"Apple Distribution"'; then
    "$emitter" "$out" "signing" "ok" "exportOptions=manual profile=\"KG App Store\" certificate=\"Apple Distribution\""
  else
    "$emitter" "$out" "signing" "warn" "exportOptions=$ROOT/ios/ExportOptions.plist missing expected manual signing fields"
  fi

  if [[ -f "$ROOT/ios/BooksBrowser/Products.storekit" ]] \
     && rg -q 'Products\.storekit' "$ROOT/ios/BooksBrowser.xcodeproj/xcshareddata/xcschemes/BooksBrowser.xcscheme" 2>/dev/null; then
    "$emitter" "$out" "storekit" "ok" "scheme_reference=Products.storekit file=present"
  else
    "$emitter" "$out" "storekit" "warn" "scheme_reference_or_file=missing"
  fi

  if rg -q 'canImport\(Sentry\)' "$ROOT/ios/BooksBrowser/Services/AppCrashReporting.swift" \
     && rg -q 'SentryDSN|SENTRY_ENABLED_IN_DEBUG|-sentryTest' "$ROOT/ios"; then
    "$emitter" "$out" "sentry" "ok" "release_name=bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION dist=CURRENT_PROJECT_VERSION"
  else
    "$emitter" "$out" "sentry" "warn" "wiring=incomplete"
  fi
}

emit_readiness_text_adapter() {
  local _out="$1" key="$2" status="$3" detail="$4"
  emit_readiness "$key" "$status" "$detail"
}

cmd_logs() {
  local since="5m" predicate='process == "BooksBrowser" OR subsystem BEGINSWITH "com.Max0228.BooksBrowser" OR subsystem BEGINSWITH "com.wordnexus"'
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --since) since="${2:?--since needs value}"; shift 2 ;;
      --predicate) predicate="${2:?--predicate needs value}"; shift 2 ;;
      -h|--help) echo "Usage: ./ops/ios_ops.sh logs [--since 5m] [--predicate <predicate>]"; return 0 ;;
      *) echo "✗ unknown logs option: $1" >&2; return 1 ;;
    esac
  done
  echo "[ios][logs] since=$since predicate=$predicate" >&2
  log show --style compact --last "$since" --predicate "$predicate" 2>/dev/null \
    | grep -vE 'runningboard\.assertions\.webkit|RBSServiceErrorDomain|ProcessAssertion' \
    || true
}

cmd_sentry() {
  local source="$ROOT/ios/BooksBrowser/Services/AppCrashReporting.swift"
  local has_sdk has_dsn_key
  grep -q 'canImport(Sentry)' "$source" && has_sdk=1 || has_sdk=0
  rg -q 'SentryDSN|SENTRY_ENABLED_IN_DEBUG|-sentryTest' "$ROOT/ios" && has_dsn_key=1 || has_dsn_key=0
  echo "[ios][sentry] source=$source"
  echo "[ios][sentry] can_import_guard=$has_sdk dsn_key_reference=$has_dsn_key"
  echo "[ios][sentry] debug_requires_env=SENTRY_ENABLED_IN_DEBUG=1 test_arg=-sentryTest"
  echo "[ios][sentry] release_name=bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION dist=CURRENT_PROJECT_VERSION"
}

cmd_doctor() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh doctor [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown doctor option: $1" >&2
        return 1
        ;;
    esac
  done

  if (( json )); then
    cmd_doctor_json
    return
  fi

  echo "[ios][doctor] phase=status"
  cmd_status
  echo "[ios][doctor] phase=sentry"
  cmd_sentry
  echo "[ios][doctor] phase=release-readiness"
  doctor_readiness emit_readiness_text_adapter
}

cmd_doctor_json() {
  local version build archive_line archive_version archive_build archive_path tf_latest
  read_project_settings version build
  archive_line="$(read_organizer_latest)"
  archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
  archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"
  archive_path="$(awk -F'\t' '{print $6}' <<<"$archive_line")"
  tf_latest="$(read_testflight_latest_build)"

  local readiness
  readiness="$(mktemp)"
  trap 'rm -f "$readiness"' RETURN
  if ! doctor_readiness emit_readiness_json "$readiness"; then
    trap - RETURN
    cleanup_tmp "$readiness" 1
    return 1
  fi

  if ! jq -s \
    --arg schema "kg.ios.doctor.v1" \
    --arg version "${version:-unknown}" \
    --arg build "${build:-unknown}" \
    --arg organizer_version "${archive_version:-unknown}" \
    --arg organizer_build "${archive_build:-unknown}" \
    --arg organizer_path "${archive_path:-}" \
    --arg testflight_latest "${tf_latest:-unknown}" \
    '{
      schema:$schema,
      project:{version:$version,build:$build},
      organizer:{latest:{version:$organizer_version,build:$organizer_build,path:$organizer_path}},
      testflight:{latest_build:$testflight_latest},
      readiness:.
    }' "$readiness"; then
    trap - RETURN
    cleanup_tmp "$readiness" 1
    return 1
  fi
  trap - RETURN
  cleanup_tmp "$readiness"
}

cmd_workflow_release() {
  local version build tf_latest archive_line archive_version archive_build asc_state
  read_project_settings version build
  tf_latest="$(read_testflight_latest_build)"
  archive_line="$(read_organizer_latest)"
  archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
  archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"

  echo "[ios][workflow] name=release mode=read-only version=${version:-unknown} build=${build:-unknown}"

  emit_workflow_step 1 "preflight" "todo" "./ops/ios_ops.sh doctor" "readiness dashboard; fix status=block before upload"
  emit_workflow_step 2 "tests" "todo" "./ops/ios_ops.sh test --all-targets --timeout 1200" "prove unit+UI scheme behavior before release claim"
  emit_workflow_step 3 "build" "todo" "./ops/ios_ops.sh build" "compile gate; first screen shows xcresult warnings/errors"

  if [[ -n "$archive_line" && "$archive_version" == "$version" && "$archive_build" == "$build" ]]; then
    emit_workflow_step 4 "archive" "ready" "./ops/ios_ops.sh archives latest" "Organizer already has matching archive $archive_version($archive_build)"
  else
    emit_workflow_step 4 "archive" "todo" "./ops/ios_ops.sh archive" "create matching Organizer archive/export; no upload by default"
  fi

  if [[ -n "$tf_latest" && "$tf_latest" =~ ^[0-9]+$ && "$build" =~ ^[0-9]+$ ]]; then
    if (( build > tf_latest )); then
      emit_workflow_step 5 "upload" "ready" "./ops/ios_ops.sh archive --upload" "project build $build is greater than TestFlight latest $tf_latest"
    else
      emit_workflow_step 5 "upload" "block" "./ops/release.sh bump ios <next-version>" "project build $build is not greater than TestFlight latest $tf_latest"
    fi
  else
    emit_workflow_step 5 "upload" "warn" "./ops/ios_ops.sh doctor" "cannot prove TestFlight latest build"
  fi

  if asc_state="$(read_asc_version_state)"; then
    case "$asc_state" in
      *REJECTED*|*UNRESOLVED_ISSUES*)
        emit_workflow_step 6 "asc-review" "todo" "./ops/asc.sh review-status && ./ops/asc.sh review-detail" "current ASC state requires rejection-resolution workflow: $asc_state"
        ;;
      *READY_FOR_REVIEW*|*PREPARE_FOR_SUBMISSION*|*DEVELOPER_REJECTED*)
        emit_workflow_step 6 "asc-review" "ready" "./ops/asc_text_bundle.py dump -o asc.json" "metadata can be reviewed before submission: $asc_state"
        ;;
      "")
        emit_workflow_step 6 "asc-review" "warn" "./ops/asc.sh versions" "ASC version state unknown"
        ;;
      *)
        emit_workflow_step 6 "asc-review" "ready" "./ops/asc.sh versions" "ASC state: $asc_state"
        ;;
    esac
  else
    emit_workflow_step 6 "asc-review" "warn" "./ops/asc.sh versions" "ASC version-state lookup timed out"
  fi

  emit_workflow_step 7 "metadata" "todo" "./ops/asc_text_bundle.py dump -o asc.json" "review/apply low-risk ASC text bundle; apply is dry-run unless --yes"
  emit_workflow_step 8 "submit" "manual" "ASC GUI" "bind uploaded build, inspect screenshots/privacy/rejection notes, submit/resubmit"
}

cmd_workflow_release_json() {
  local version build tf_latest archive_line archive_version archive_build asc_state
  local steps
  steps="$(mktemp)"
  trap 'rm -f "$steps"' RETURN

  read_project_settings version build
  tf_latest="$(read_testflight_latest_build)"
  archive_line="$(read_organizer_latest)"
  archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
  archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"

  emit_workflow_step_json "$steps" 1 "preflight" "todo" "./ops/ios_ops.sh doctor" "readiness dashboard; fix status=block before upload"
  emit_workflow_step_json "$steps" 2 "tests" "todo" "./ops/ios_ops.sh test --all-targets --timeout 1200" "prove unit+UI scheme behavior before release claim"
  emit_workflow_step_json "$steps" 3 "build" "todo" "./ops/ios_ops.sh build" "compile gate; first screen shows xcresult warnings/errors"

  if [[ -n "$archive_line" && "$archive_version" == "$version" && "$archive_build" == "$build" ]]; then
    emit_workflow_step_json "$steps" 4 "archive" "ready" "./ops/ios_ops.sh archives latest" "Organizer already has matching archive $archive_version($archive_build)"
  else
    emit_workflow_step_json "$steps" 4 "archive" "todo" "./ops/ios_ops.sh archive" "create matching Organizer archive/export; no upload by default"
  fi

  if [[ -n "$tf_latest" && "$tf_latest" =~ ^[0-9]+$ && "$build" =~ ^[0-9]+$ ]]; then
    if (( build > tf_latest )); then
      emit_workflow_step_json "$steps" 5 "upload" "ready" "./ops/ios_ops.sh archive --upload" "project build $build is greater than TestFlight latest $tf_latest"
    else
      emit_workflow_step_json "$steps" 5 "upload" "block" "./ops/release.sh bump ios <next-version>" "project build $build is not greater than TestFlight latest $tf_latest"
    fi
  else
    emit_workflow_step_json "$steps" 5 "upload" "warn" "./ops/ios_ops.sh doctor" "cannot prove TestFlight latest build"
  fi

  if asc_state="$(read_asc_version_state)"; then
    case "$asc_state" in
      *REJECTED*|*UNRESOLVED_ISSUES*)
        emit_workflow_step_json "$steps" 6 "asc-review" "todo" "./ops/asc.sh review-status && ./ops/asc.sh review-detail" "current ASC state requires rejection-resolution workflow: $asc_state"
        ;;
      *READY_FOR_REVIEW*|*PREPARE_FOR_SUBMISSION*|*DEVELOPER_REJECTED*)
        emit_workflow_step_json "$steps" 6 "asc-review" "ready" "./ops/asc_text_bundle.py dump -o asc.json" "metadata can be reviewed before submission: $asc_state"
        ;;
      "")
        emit_workflow_step_json "$steps" 6 "asc-review" "warn" "./ops/asc.sh versions" "ASC version state unknown"
        ;;
      *)
        emit_workflow_step_json "$steps" 6 "asc-review" "ready" "./ops/asc.sh versions" "ASC state: $asc_state"
        ;;
    esac
  else
    emit_workflow_step_json "$steps" 6 "asc-review" "warn" "./ops/asc.sh versions" "ASC version-state lookup timed out"
  fi

  emit_workflow_step_json "$steps" 7 "metadata" "todo" "./ops/asc_text_bundle.py dump -o asc.json" "review/apply low-risk ASC text bundle; apply is dry-run unless --yes"
  emit_workflow_step_json "$steps" 8 "submit" "manual" "ASC GUI" "bind uploaded build, inspect screenshots/privacy/rejection notes, submit/resubmit"

  if ! jq -s \
    --arg schema "kg.ios.workflow.v1" \
    --arg name "release" \
    --arg mode "read-only" \
    --arg version "${version:-unknown}" \
    --arg build "${build:-unknown}" \
    '{
      schema:$schema,
      name:$name,
      mode:$mode,
      version:$version,
      build:$build,
      steps:.
    }' "$steps"; then
    trap - RETURN
    cleanup_tmp "$steps" 1
    return 1
  fi
  trap - RETURN
  cleanup_tmp "$steps"
}

cmd_workflow() {
  local name="release" json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      release) name="release"; shift ;;
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh workflow release [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown workflow option: $1" >&2
        return 1
        ;;
    esac
  done

  case "$name" in
    release)
      if (( json )); then
        cmd_workflow_release_json
      else
        cmd_workflow_release
      fi
      ;;
    *)
      echo "✗ unknown workflow: $name" >&2
      return 1
      ;;
  esac
}

cmd_snapshot_json() {
  local doctor_json workflow_json generated_at
  if ! doctor_json="$(cmd_doctor_json)"; then
    return 1
  fi
  if ! workflow_json="$(cmd_workflow_release_json)"; then
    return 1
  fi
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  jq -n \
    --arg schema "kg.ios.snapshot.v1" \
    --arg generated_at "$generated_at" \
    --argjson doctor "$doctor_json" \
    --argjson workflow "$workflow_json" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      project:$doctor.project,
      organizer:$doctor.organizer,
      testflight:$doctor.testflight,
      readiness:$doctor.readiness,
      workflow:$workflow
    }'
}

cmd_snapshot() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh snapshot [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown snapshot option: $1" >&2
        return 1
        ;;
    esac
  done

  if (( json )); then
    cmd_snapshot_json
    return
  fi

  echo "[ios][snapshot] phase=doctor"
  cmd_doctor
  echo "[ios][snapshot] phase=workflow"
  cmd_workflow_release
}

cmd="${1:-}"
[[ -n "$cmd" ]] || { usage; exit 0; }
shift || true

case "$cmd" in
  status) cmd_status "$@" ;;
  build) "$SCRIPT_DIR/ios_build.sh" "$@" ;;
  test) "$SCRIPT_DIR/ios_test.sh" "$@" ;;
  archive) "$SCRIPT_DIR/ios_release.sh" "$@" ;;
  release) "$SCRIPT_DIR/ios_release.sh" "$@" ;;
  archives) "$SCRIPT_DIR/ios_archive.sh" "${@:-list}" ;;
  issues) "$SCRIPT_DIR/ios_diagnostics.py" "$@" ;;
  logs) cmd_logs "$@" ;;
  sentry) cmd_sentry "$@" ;;
  doctor) cmd_doctor "$@" ;;
  workflow|flow) cmd_workflow "$@" ;;
  snapshot|dashboard) cmd_snapshot "$@" ;;
  -h|--help|help) usage ;;
  *)
    echo "✗ unknown subcommand: $cmd" >&2
    usage >&2
    exit 1
    ;;
esac
