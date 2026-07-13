IOS_EXPORT_PROFILE_NAME="${IOS_EXPORT_PROFILE_NAME:-KG App Store}"
IOS_EXPORT_CERTIFICATE_NAME="${IOS_EXPORT_CERTIFICATE_NAME:-Apple Distribution}"

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

sentry_summary_json() {
  local source="$ROOT/ios/BooksAndVocab/Services/AppCrashReporting.swift"
  local source_exists has_sdk has_dsn_key
  if [[ -n "${KG_IOS_OPS_SENTRY_SOURCE_FIXTURE:-}" ]]; then
    source="$KG_IOS_OPS_SENTRY_SOURCE_FIXTURE"
  fi
  if [[ -n "${KG_IOS_OPS_SENTRY_SOURCE_EXISTS_FIXTURE:-}" ]]; then
    source_exists="$KG_IOS_OPS_SENTRY_SOURCE_EXISTS_FIXTURE"
  elif [[ -f "$source" ]]; then
    source_exists=1
  else
    source_exists=0
  fi
  if [[ -n "${KG_IOS_OPS_SENTRY_CAN_IMPORT_FIXTURE:-}" ]]; then
    has_sdk="$KG_IOS_OPS_SENTRY_CAN_IMPORT_FIXTURE"
  elif [[ "$source_exists" == "1" ]] && grep -q 'canImport(Sentry)' "$source"; then
    has_sdk=1
  else
    has_sdk=0
  fi
  if [[ -n "${KG_IOS_OPS_SENTRY_DSN_FIXTURE:-}" ]]; then
    has_dsn_key="$KG_IOS_OPS_SENTRY_DSN_FIXTURE"
  elif rg -q 'SentryDSN|SENTRY_ENABLED_IN_DEBUG|-sentryTest' "$ROOT/ios"; then
    has_dsn_key=1
  else
    has_dsn_key=0
  fi
  jq -n \
    --arg schema "kg.ios.sentry.v1" \
    --arg source "$source" \
    --arg cmd "./ops/ios_ops.sh sentry --json" \
    --argjson sourceExists "$source_exists" \
    --argjson canImport "$has_sdk" \
    --argjson dsnReference "$has_dsn_key" \
    '{
      schema:$schema,
      source:{
        path:$source,
        exists:($sourceExists == true or $sourceExists == 1)
      },
      wiring:{
        canImportGuard:($canImport == 1),
        dsnKeyReference:($dsnReference == 1)
      },
      debug:{
        requiresEnv:"SENTRY_ENABLED_IN_DEBUG=1",
        testArgument:"-sentryTest"
      },
      release:{
        name:"bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION",
        dist:"CURRENT_PROJECT_VERSION"
      }
    }
    # issues[] is the single source of truth for sentry wiring failures: doctor
    # verdict, snapshot nextActions and sentryWarnings count all derive from it,
    # so adding a wiring check only edits this list.
    | .issues = ([
        (if (.source.exists) then empty else {key:"source",message:("source missing: "+$source),command:$cmd} end),
        (if (.wiring.canImportGuard) then empty else {key:"canImportGuard",message:"missing canImport(Sentry) guard",command:$cmd} end),
        (if (.wiring.dsnKeyReference) then empty else {key:"dsnKeyReference",message:"missing Sentry DSN/debug test wiring",command:$cmd} end)
      ])'
}

doctor_readiness() {
  local emitter="$1" out="${2:-}"
  local version build archive_line archive_version archive_build archive_path tf_latest sentry_json sentry_source_exists sentry_can_import sentry_dsn_reference
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

  if plutil -p "$ROOT/ios/ExportOptions.plist" 2>/dev/null | grep -q "\"$IOS_EXPORT_PROFILE_NAME\"" \
     && plutil -p "$ROOT/ios/ExportOptions.plist" 2>/dev/null | grep -q "\"$IOS_EXPORT_CERTIFICATE_NAME\""; then
    "$emitter" "$out" "signing" "ok" "exportOptions=manual profile=\"$IOS_EXPORT_PROFILE_NAME\" certificate=\"$IOS_EXPORT_CERTIFICATE_NAME\""
  else
    "$emitter" "$out" "signing" "warn" "exportOptions=$ROOT/ios/ExportOptions.plist missing expected manual signing fields"
  fi

  if [[ -f "$ROOT/ios/BooksAndVocab/Products.storekit" ]] \
     && rg -q 'Products\.storekit' "$ROOT/ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocab.xcscheme" 2>/dev/null; then
    "$emitter" "$out" "storekit" "ok" "scheme_reference=Products.storekit file=present"
  else
    "$emitter" "$out" "storekit" "warn" "scheme_reference_or_file=missing"
  fi

  sentry_json="$(sentry_summary_json)"
  sentry_source_exists="$(jq -r '.source.exists' <<<"$sentry_json")"
  sentry_can_import="$(jq -r '.wiring.canImportGuard' <<<"$sentry_json")"
  sentry_dsn_reference="$(jq -r '.wiring.dsnKeyReference' <<<"$sentry_json")"
  # Verdict derives from issues[] (single source of truth); detail keeps the
  # per-field booleans for human readability.
  if [[ "$(jq -r '.issues | length' <<<"$sentry_json")" -eq 0 ]]; then
    "$emitter" "$out" "sentry" "ok" "release_name=bundleId@MARKETING_VERSION+CURRENT_PROJECT_VERSION dist=CURRENT_PROJECT_VERSION"
  else
    "$emitter" "$out" "sentry" "warn" "source_exists=$sentry_source_exists can_import_guard=$sentry_can_import dsn_key_reference=$sentry_dsn_reference"
  fi
}

emit_readiness_text_adapter() {
  local _out="$1" key="$2" status="$3" detail="$4"
  emit_readiness "$key" "$status" "$detail"
}

doctor_summary_json_from_file() {
  local readiness_file="$1"
  jq -s '
    {
      verdict:(
        if any(.[]; .status == "block") then "block"
        elif any(.[]; .status == "warn") then "warn"
        else "pass"
        end
      ),
      counts:{
        ok:([.[] | select(.status == "ok")] | length),
        warn:([.[] | select(.status == "warn")] | length),
        block:([.[] | select(.status == "block")] | length),
        total:length
      }
    }' "$readiness_file"
}

workflow_summary_json_from_file() {
  local steps_file="$1"
  jq -s '
    {
      verdict:(
        if any(.[]; .status == "block") then "block"
        elif any(.[]; .status == "warn") then "warn"
        else "pass"
        end
      ),
      counts:{
        ready:([.[] | select(.status == "ready")] | length),
        todo:([.[] | select(.status == "todo")] | length),
        block:([.[] | select(.status == "block")] | length),
        warn:([.[] | select(.status == "warn")] | length),
        manual:([.[] | select(.status == "manual")] | length),
        total:length
      }
    }' "$steps_file"
}

app_review_latest_spec_path() {
  find "$ROOT/ops/app_review" -maxdepth 1 -type f -name '[0-9]*.[0-9]*.[0-9]*.json' 2>/dev/null | sort -V | tail -n 1
}

app_review_workflow_gate_json() {
  local spec_path fixture output rc=0
  spec_path="$(app_review_latest_spec_path)"
  fixture="${KG_IOS_OPS_APP_REVIEW_GATE_FIXTURE:-}"
  if [[ "${KG_IOS_OPS_FIXTURE:-}" == "1" && -z "$fixture" ]]; then
    fixture="pass"
  fi
  if [[ "$fixture" == "pass" ]]; then
    jq -n --arg spec "$spec_path" '{spec:$spec,verdict:{status:"pass",blockCount:0},blocks:[]}'
    return 0
  elif [[ "$fixture" == "block" ]]; then
    jq -n --arg spec "$spec_path" '{spec:$spec,verdict:{status:"block",blockCount:1},blocks:[{code:"fixture.block",expected:"pass",actual:"block"}]}'
    return 0
  elif [[ "$fixture" == "missing" ]]; then
    jq -n '{spec:null,verdict:{status:"block",blockCount:1},blocks:[{code:"gate.spec.missing",expected:"ops/app_review/<latest>.json",actual:"missing"}]}'
    return 0
  elif [[ -n "$fixture" && -f "$fixture" ]]; then
    if output="$(jq -c --arg spec "$spec_path" '. + {spec:$spec}' "$fixture" 2>/dev/null)" \
      && jq -e '(.verdict.status == "pass" or .verdict.status == "block") and (.verdict.blockCount | type == "number") and (.blocks | type == "array")' >/dev/null 2>&1 <<<"$output"; then
      printf '%s\n' "$output"
    else
      jq -n --arg spec "$spec_path" '{spec:$spec,verdict:{status:"block",blockCount:1},blocks:[{code:"gate.report.invalid",expected:"typed App Review gate report",actual:"malformed"}]}'
    fi
    return 0
  fi
  if [[ -z "$spec_path" ]]; then
    jq -n '{spec:null,verdict:{status:"block",blockCount:1},blocks:[{code:"gate.spec.missing",expected:"ops/app_review/<latest>.json",actual:"missing"}]}'
    return 0
  fi
  output="$("$(catalog_uv_bin)" run --python 3.13 python "$ROOT/ops/app_review_gate.py" dry-run --spec "$spec_path" --workspace-root "$ROOT" --observation-mode online)" || rc=$?
  if [[ -z "$output" || ( "$rc" -ne 0 && "$rc" -ne 2 ) ]]; then
    jq -n --arg spec "$spec_path" --argjson rc "$rc" '{spec:$spec,verdict:{status:"block",blockCount:1},blocks:[{code:"gate.execution",expected:"valid gate report",actual:{exitCode:$rc}}]}'
    return 0
  fi
  if jq -e '(.verdict.status == "pass" or .verdict.status == "block") and (.verdict.blockCount | type == "number") and (.blocks | type == "array")' >/dev/null 2>&1 <<<"$output"; then
    jq --arg spec "$spec_path" '. + {spec:$spec}' <<<"$output"
  else
    jq -n --arg spec "$spec_path" '{spec:$spec,verdict:{status:"block",blockCount:1},blocks:[{code:"gate.report.invalid",expected:"typed App Review gate report",actual:"malformed"}]}'
  fi
}

write_workflow_release_steps_json() {
  local out="$1" version="$2" build="$3" tf_latest="$4" archive_line="$5" archive_version="$6" archive_build="$7" asc_state="$8" app_review_gate="$9"
  emit_workflow_step_json "$out" 1 "preflight" "todo" "./ops/ios_ops.sh doctor" "readiness dashboard; fix status=block before upload"
  emit_workflow_step_json "$out" 2 "tests" "todo" "./ops/ios_ops.sh test --all-targets --timeout 1200" "prove unit+UI scheme behavior before release claim"
  emit_workflow_step_json "$out" 3 "build" "todo" "./ops/ios_ops.sh build" "compile gate; first screen shows xcresult warnings/errors"

  if [[ -n "$archive_line" && "$archive_version" == "$version" && "$archive_build" == "$build" ]]; then
    emit_workflow_step_json "$out" 4 "archive" "ready" "./ops/ios_ops.sh archives latest" "Organizer already has matching archive $archive_version($archive_build)"
  else
    emit_workflow_step_json "$out" 4 "archive" "todo" "./ops/ios_ops.sh archive" "create matching Organizer archive/export; no upload by default"
  fi

  if [[ -n "$tf_latest" && "$tf_latest" =~ ^[0-9]+$ && "$build" =~ ^[0-9]+$ ]]; then
    if (( build > tf_latest )); then
      emit_workflow_step_json "$out" 5 "upload" "ready" "./ops/ios_ops.sh archive --upload" "project build $build is greater than TestFlight latest $tf_latest"
    else
      emit_workflow_step_json "$out" 5 "upload" "block" "./ops/release.sh bump ios <next-version> --yes" "project build $build is not greater than TestFlight latest $tf_latest"
    fi
  else
    emit_workflow_step_json "$out" 5 "upload" "warn" "./ops/ios_ops.sh doctor" "cannot prove TestFlight latest build"
  fi

  if [[ "${asc_state:-}" == "__ASC_TIMEOUT__" ]]; then
    emit_workflow_step_json "$out" 6 "asc-review" "warn" "./ops/asc.sh versions" "ASC version-state lookup timed out"
  elif [[ -n "${asc_state:-}" ]]; then
    case "$asc_state" in
      *REJECTED*|*UNRESOLVED_ISSUES*)
        emit_workflow_step_json "$out" 6 "asc-review" "todo" "./ops/asc.sh review-status && ./ops/asc.sh review-detail" "current ASC state requires rejection-resolution workflow: $asc_state"
        ;;
      *READY_FOR_REVIEW*|*PREPARE_FOR_SUBMISSION*|*DEVELOPER_REJECTED*)
        emit_workflow_step_json "$out" 6 "asc-review" "ready" "./ops/asc_text_bundle.py dump -o asc.json" "metadata can be reviewed before submission: $asc_state"
        ;;
      *)
        emit_workflow_step_json "$out" 6 "asc-review" "ready" "./ops/asc.sh versions" "ASC state: $asc_state"
        ;;
    esac
  else
    emit_workflow_step_json "$out" 6 "asc-review" "warn" "./ops/asc.sh versions" "ASC version state unknown"
  fi

  emit_workflow_step_json "$out" 7 "metadata" "todo" "./ops/asc_text_bundle.py dump -o asc.json" "review/apply low-risk ASC text bundle; apply is dry-run unless --yes"
  local gate_status gate_spec gate_blocks
  gate_status="$(jq -r '.verdict.status // "block"' <<<"$app_review_gate")"
  gate_spec="$(jq -r '.spec // "ops/app_review/<latest>.json"' <<<"$app_review_gate")"
  gate_blocks="$(jq -r '.verdict.blockCount // (.blocks | length) // 1' <<<"$app_review_gate")"
  if [[ "$gate_status" == "pass" ]]; then
    emit_workflow_step_json "$out" 8 "submit" "manual" "ASC GUI" "App Review evidence gate PASS; bind uploaded build and submit/resubmit"
  else
    emit_workflow_step_json "$out" 8 "submit" "block" "./ops/app_review_evidence.py status --spec $gate_spec" "App Review evidence gate BLOCK ($gate_blocks blocker(s)); produce required evidence before ASC GUI"
  fi
}

cmd_sentry() {
  local json=0 sentry_json
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh sentry [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown sentry option: $1" >&2
        return 1
        ;;
    esac
  done

  sentry_json="$(sentry_summary_json)"
  if (( json )); then
    printf '%s\n' "$sentry_json"
    return 0
  fi

  echo "[ios][sentry] source=$(jq -r '.source.path' <<<"$sentry_json")"
  echo "[ios][sentry] can_import_guard=$(jq -r '.wiring.canImportGuard | if . then 1 else 0 end' <<<"$sentry_json") dsn_key_reference=$(jq -r '.wiring.dsnKeyReference | if . then 1 else 0 end' <<<"$sentry_json")"
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

  local readiness summary
  readiness="$(mktemp)"
  trap 'rm -f "$readiness"' RETURN

  echo "[ios][doctor] phase=status"
  cmd_status
  echo "[ios][doctor] phase=sentry"
  cmd_sentry
  echo "[ios][doctor] phase=release-readiness"
  if ! doctor_readiness emit_readiness_json "$readiness"; then
    trap - RETURN
    cleanup_tmp "$readiness" 1
    return 1
  fi
  jq -r '. | "[ios][readiness] \(.key) status=\(.status) \(.detail)"' "$readiness"
  summary="$(doctor_summary_json_from_file "$readiness")"
  echo "[ios][doctor] summary verdict=$(jq -r '.verdict' <<<"$summary") ok=$(jq -r '.counts.ok' <<<"$summary") warn=$(jq -r '.counts.warn' <<<"$summary") block=$(jq -r '.counts.block' <<<"$summary") total=$(jq -r '.counts.total' <<<"$summary")"
  trap - RETURN
  cleanup_tmp "$readiness"
}

cmd_doctor_json() {
  local version build archive_line archive_version archive_build archive_path tf_latest sentry_json summary_json
  read_project_settings version build
  archive_line="$(read_organizer_latest)"
  archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
  archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"
  archive_path="$(awk -F'\t' '{print $6}' <<<"$archive_line")"
  tf_latest="$(read_testflight_latest_build)"
  sentry_json="$(sentry_summary_json)"

  local readiness
  readiness="$(mktemp)"
  trap 'rm -f "$readiness"' RETURN
  if ! doctor_readiness emit_readiness_json "$readiness"; then
    trap - RETURN
    cleanup_tmp "$readiness" 1
    return 1
  fi
  summary_json="$(doctor_summary_json_from_file "$readiness")"

  if ! jq -s \
    --arg schema "kg.ios.doctor.v1" \
    --arg version "${version:-unknown}" \
    --arg build "${build:-unknown}" \
    --arg organizer_version "${archive_version:-unknown}" \
    --arg organizer_build "${archive_build:-unknown}" \
    --arg organizer_path "${archive_path:-}" \
    --arg testflight_latest "${tf_latest:-unknown}" \
    --argjson sentry "$sentry_json" \
    --argjson summary "$summary_json" \
    '{
      schema:$schema,
      project:{version:$version,build:$build},
      organizer:{latest:{version:$organizer_version,build:$organizer_build,path:$organizer_path}},
      testflight:{latest_build:$testflight_latest},
      summary:$summary,
      sentry:$sentry,
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
  local steps summary app_review_gate
  read_project_settings version build
  tf_latest="$(read_testflight_latest_build)"
  archive_line="$(read_organizer_latest)"
  archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
  archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"

  echo "[ios][workflow] name=release mode=read-only version=${version:-unknown} build=${build:-unknown}"
  steps="$(mktemp)"
  trap 'rm -f "$steps"' RETURN
  if asc_state="$(read_asc_version_state)"; then
    :
  else
    asc_state="__ASC_TIMEOUT__"
  fi
  app_review_gate="$(app_review_workflow_gate_json)"
  write_workflow_release_steps_json "$steps" "${version:-unknown}" "${build:-unknown}" "${tf_latest:-}" "$archive_line" "${archive_version:-}" "${archive_build:-}" "$asc_state" "$app_review_gate"
  jq -r '"[ios][workflow] step=\(.step) key=\(.key) status=\(.status) command=\"\(.command)\" note=\"\(.note)\""' "$steps"
  summary="$(workflow_summary_json_from_file "$steps")"
  echo "[ios][workflow] summary verdict=$(jq -r '.verdict' <<<"$summary") ready=$(jq -r '.counts.ready' <<<"$summary") todo=$(jq -r '.counts.todo' <<<"$summary") block=$(jq -r '.counts.block' <<<"$summary") warn=$(jq -r '.counts.warn' <<<"$summary") manual=$(jq -r '.counts.manual' <<<"$summary") total=$(jq -r '.counts.total' <<<"$summary")"
  trap - RETURN
  cleanup_tmp "$steps"
}

cmd_workflow_release_json() {
  local version build tf_latest archive_line archive_version archive_build asc_state
  local steps summary_json app_review_gate
  steps="$(mktemp)"
  trap 'rm -f "$steps"' RETURN

  read_project_settings version build
  tf_latest="$(read_testflight_latest_build)"
  archive_line="$(read_organizer_latest)"
  archive_version="$(awk -F'\t' '{print $4}' <<<"$archive_line")"
  archive_build="$(awk -F'\t' '{print $5}' <<<"$archive_line")"
  if asc_state="$(read_asc_version_state)"; then
    :
  else
    asc_state="__ASC_TIMEOUT__"
  fi
  app_review_gate="$(app_review_workflow_gate_json)"
  write_workflow_release_steps_json "$steps" "${version:-unknown}" "${build:-unknown}" "${tf_latest:-}" "$archive_line" "${archive_version:-}" "${archive_build:-}" "$asc_state" "$app_review_gate"
  summary_json="$(workflow_summary_json_from_file "$steps")"

  if ! jq -s \
    --arg schema "kg.ios.workflow.v1" \
    --arg name "release" \
    --arg mode "read-only" \
    --arg version "${version:-unknown}" \
    --arg build "${build:-unknown}" \
    --argjson summary "$summary_json" \
    --argjson appReviewGate "$app_review_gate" \
    '{
      schema:$schema,
      name:$name,
      mode:$mode,
      version:$version,
      build:$build,
      appReviewGate:$appReviewGate,
      summary:$summary,
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

cmd_gate_release_json_from_state() {
  local doctor_json="$1" workflow_json="$2" generated_at
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  jq -n \
    --arg schema "kg.ios.gate.v1" \
    --arg generated_at "$generated_at" \
    --arg name "release" \
    --argjson doctor "$doctor_json" \
    --argjson workflow "$workflow_json" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      name:$name,
      sources:{
        doctor_schema:$doctor.schema,
        workflow_schema:$workflow.schema
      },
      blocks:(
        ($doctor.readiness // [] | map(select(.status=="block") | {source:"readiness",key,status,detail}))
        +
        ($workflow.steps // [] | map(select(.status=="block") | {source:"workflow",key,status,step,command,note}))
      ),
      warnings:(
        ($doctor.readiness // [] | map(select(.status=="warn") | {source:"readiness",key,status,detail}))
        +
        ($workflow.steps // [] | map(select(.status=="warn") | {source:"workflow",key,status,step,command,note}))
      ),
      todos:($workflow.steps // [] | map(select(.status=="todo") | {source:"workflow",key,status,step,command,note})),
      manual:($workflow.steps // [] | map(select(.status=="manual") | {source:"workflow",key,status,step,command,note}))
    }
    | .summary = {
        blocks:(.blocks|length),
        warnings:(.warnings|length),
        todos:(.todos|length),
        manual:(.manual|length)
      }
    | .verdict = (if (.summary.blocks > 0) then "block" elif (.summary.warnings > 0) then "warn" else "pass" end)
    | .exitCode = (if .verdict=="block" then 2 elif .verdict=="warn" then 1 else 0 end)'
}

cmd_gate_release_json_payload() {
  local doctor_json workflow_json
  if ! doctor_json="$(cmd_doctor_json)"; then
    return 1
  fi
  if ! workflow_json="$(cmd_workflow_release_json)"; then
    return 1
  fi
  cmd_gate_release_json_from_state "$doctor_json" "$workflow_json"
}

cmd_gate_release() {
  local json="$1" payload exit_code
  if ! payload="$(cmd_gate_release_json_payload)"; then
    return 1
  fi
  exit_code="$(jq -r '.exitCode' <<<"$payload")"

  if (( json )); then
    printf '%s\n' "$payload"
    return "$exit_code"
  fi

  jq -r '
    "[ios][gate] name=\(.name) verdict=\(.verdict) exitCode=\(.exitCode) blocks=\(.summary.blocks) warnings=\(.summary.warnings) todos=\(.summary.todos) manual=\(.summary.manual)",
    (.blocks[]? | "[ios][gate] block source=\(.source) key=\(.key) status=\(.status) detail=\"\(.detail // .note // "")\" command=\"\(.command // "")\""),
    (.warnings[]? | "[ios][gate] warn source=\(.source) key=\(.key) status=\(.status) detail=\"\(.detail // .note // "")\" command=\"\(.command // "")\""),
    (.todos[]? | "[ios][gate] todo key=\(.key) command=\"\(.command)\" note=\"\(.note)\""),
    (.manual[]? | "[ios][gate] manual key=\(.key) command=\"\(.command)\" note=\"\(.note)\"")
  ' <<<"$payload"
  return "$exit_code"
}

cmd_gate() {
  local name="release" json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      release) name="release"; shift ;;
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh gate release [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown gate option: $1" >&2
        return 1
        ;;
    esac
  done

  case "$name" in
    release) cmd_gate_release "$json" ;;
    *)
      echo "✗ unknown gate: $name" >&2
      return 1
      ;;
  esac
}
