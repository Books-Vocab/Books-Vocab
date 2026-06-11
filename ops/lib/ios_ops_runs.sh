#!/usr/bin/env bash
# ios_ops_runs.sh — sourceable build/test report commands for ios_ops.sh.

emit_run_verdict_json() {
  local kind="$1" file="$2"
  # JSON verdict always lives at "<text verdict>.json" — derive it from the
  # CALLER-CHOSEN text path so per-invocation pinned verdicts (multi-session
  # race guard) read their own JSON, never the machine-wide latest pointer.
  local json_file="$file.json"
  if [[ -f "$json_file" ]]; then
    if jq -e . "$json_file" >/dev/null 2>&1; then
      jq -c \
        --arg kind "$kind" \
        --arg verdictFile "$file" \
        --arg jsonVerdictFile "$json_file" \
        --argjson logExists "$(path_exists_json_bool file "$(jq -r '.artifacts.log // ""' "$json_file")")" \
        --argjson xcresultExists "$(path_exists_json_bool dir "$(jq -r '.artifacts.xcresult // ""' "$json_file")")" \
        --argjson uiContactSheetExists "$(path_exists_json_bool file "$(jq -r '.artifacts.uiContactSheet // ""' "$json_file")")" \
        --argjson uiQuick4SheetExists "$(path_exists_json_bool file "$(jq -r '.artifacts.uiQuick4Sheet // ""' "$json_file")")" \
        --argjson uiVisualReviewManifestExists "$(path_exists_json_bool file "$(jq -r '.artifacts.uiVisualReviewManifest // ""' "$json_file")")" \
        --argjson uiVideoExists "$(path_exists_json_bool file "$(jq -r '.artifacts.uiVideo // ""' "$json_file")")" \
        '{
          kind:$kind,
          status:(.status // .result // "unknown"),
          result:(.result // .status // "unknown"),
          exit:(.exit // null),
          reason:(.reason // null),
          caller:(.caller // null),
          elapsed:(.elapsed // null),
          executed:(.executed // null),
          device:(.device // null),
          options:(.options // null),
          cache:(.cache // null),
          timings:(.timings // null),
          coverage:(.coverage // null),
          verdictFile:$verdictFile,
          jsonVerdictFile:$jsonVerdictFile,
          artifacts:{
            log:(.artifacts.log // null),
            logExists:$logExists,
            xcresult:(.artifacts.xcresult // null),
            xcresultExists:$xcresultExists,
            uiContactSheet:(.artifacts.uiContactSheet // null),
            uiContactSheetExists:$uiContactSheetExists,
            uiQuick4Sheet:(.artifacts.uiQuick4Sheet // null),
            uiQuick4SheetExists:$uiQuick4SheetExists,
            uiVisualReviewManifest:(.artifacts.uiVisualReviewManifest // null),
            uiVisualReviewManifestExists:$uiVisualReviewManifestExists,
            uiScreenshotDir:(.artifacts.uiScreenshotDir // null),
            uiVideo:(.artifacts.uiVideo // null),
            uiVideoExists:$uiVideoExists
          },
          uiVisualReview:(
            if (.artifacts.uiScreenshotDir // .artifacts.uiContactSheet
                // .artifacts.uiQuick4Sheet // .artifacts.uiVisualReviewManifest
                // .artifacts.uiVideo) == null
            then null
            else {
              screenshotDir:(.artifacts.uiScreenshotDir // null),
              contactSheet:(.artifacts.uiContactSheet // null),
              contactSheetExists:$uiContactSheetExists,
              quick4Sheet:(.artifacts.uiQuick4Sheet // null),
              quick4SheetExists:$uiQuick4SheetExists,
              visualReviewManifest:(.artifacts.uiVisualReviewManifest // null),
              visualReviewManifestExists:$uiVisualReviewManifestExists,
              video:(.artifacts.uiVideo // null),
              videoExists:$uiVideoExists
            }
            end
          )
        }' "$json_file"
      return
    fi

    if [[ ! -f "$file" ]]; then
      jq -nc --arg kind "$kind" --arg verdictFile "$file" --arg jsonVerdictFile "$json_file" \
        '{
          kind:$kind,
          status:"malformed",
          result:"malformed",
          exit:null,
        reason:"malformed-json-verdict",
        caller:null,
        elapsed:null,
        executed:null,
        device:null,
        options:null,
        cache:null,
        timings:null,
        coverage:null,
        verdictFile:$verdictFile,
        jsonVerdictFile:$jsonVerdictFile,
        artifacts:{log:null,logExists:false,xcresult:null,xcresultExists:false},
        uiVisualReview:null
      }'
      return
    fi
  fi

  if [[ ! -f "$file" ]]; then
    jq -nc --arg kind "$kind" --arg verdictFile "$file" \
      '{
        kind:$kind,
        status:"missing",
        result:"missing",
        exit:null,
        reason:null,
        caller:null,
        elapsed:null,
        executed:null,
        device:null,
        options:null,
        cache:null,
        timings:null,
        coverage:null,
        verdictFile:$verdictFile,
        jsonVerdictFile:($verdictFile + ".json"),
        artifacts:{log:null,logExists:false,xcresult:null,xcresultExists:false},
        uiVisualReview:null
      }'
    return
  fi

  local result exit_code reason caller elapsed executed log_path xcresult_path log_exists xcresult_exists
  result="$(verdict_field "$file" RESULT)"
  exit_code="$(verdict_field "$file" EXIT)"
  reason="$(verdict_field "$file" reason)"
  caller="$(verdict_field "$file" caller)"
  elapsed="$(verdict_field "$file" elapsed)"
  executed="$(verdict_field "$file" executed)"
  log_path="$(verdict_field "$file" log)"
  xcresult_path="$(verdict_field "$file" xcresult)"
  log_exists="$(path_exists_json_bool file "$log_path")"
  xcresult_exists="$(path_exists_json_bool dir "$xcresult_path")"

  jq -nc \
    --arg kind "$kind" \
    --arg status "${result:-unknown}" \
    --arg result "${result:-unknown}" \
    --arg exit "${exit_code:-}" \
    --arg reason "${reason:-}" \
    --arg caller "${caller:-}" \
    --arg elapsed "${elapsed:-}" \
    --arg executed "${executed:-}" \
    --arg log "$log_path" \
    --arg xcresult "$xcresult_path" \
    --argjson options 'null' \
    --argjson cache 'null' \
    --argjson timings 'null' \
    --arg verdictFile "$file" \
    --arg jsonVerdictFile "$json_file" \
    --argjson logExists "$log_exists" \
    --argjson xcresultExists "$xcresult_exists" \
    '{
      kind:$kind,
      status:$status,
      result:$result,
      exit:(if $exit == "" then null else $exit end),
      reason:(if $reason == "" then null else $reason end),
      caller:(if $caller == "" then null else $caller end),
      elapsed:(if $elapsed == "" then null else $elapsed end),
      executed:(if $executed == "" then null else $executed end),
      device:null,
      options:$options,
      cache:$cache,
      timings:$timings,
      coverage:null,
      verdictFile:$verdictFile,
      jsonVerdictFile:$jsonVerdictFile,
      artifacts:{
        log:(if $log == "" then null else $log end),
        logExists:$logExists,
        xcresult:(if $xcresult == "" then null else $xcresult end),
        xcresultExists:$xcresultExists
      },
      uiVisualReview:null
    }'
}

empty_run_diagnostics_json() {
  local source="$1" error="${2:-}"
  jq -nc \
    --arg schema "kg.ios.diagnostics.v1" \
    --arg source "$source" \
    --arg error "$error" \
    '{
      schema:$schema,
      source:$source,
      result:"unknown",
      counts:{errors:0,warnings:0,swift6:0,storekit:0,spm:0,signing:0},
      diagnostics:[],
      truncated:false,
      totalDiagnostics:0,
      error:(if $error == "" then null else $error end)
    }'
}

emit_run_diagnostics_json() {
  local kind="$1" run_json="$2"
  local log_path xcresult_path log_exists xcresult_exists diag_json err
  local -a diag_args
  log_path="$(jq -r '.artifacts.log // empty' <<<"$run_json")"
  xcresult_path="$(jq -r '.artifacts.xcresult // empty' <<<"$run_json")"
  log_exists="$(jq -r '.artifacts.logExists // false' <<<"$run_json")"
  xcresult_exists="$(jq -r '.artifacts.xcresultExists // false' <<<"$run_json")"

  if [[ "$log_exists" != "true" && "$xcresult_exists" != "true" ]]; then
    empty_run_diagnostics_json "missing-artifacts"
    return
  fi

  diag_args=("$SCRIPT_DIR/ios_diagnostics.py" "--kind" "$kind" "--json" "--limit" "20")
  [[ "$xcresult_exists" == "true" ]] && diag_args+=("--xcresult" "$xcresult_path")
  [[ "$log_exists" == "true" ]] && diag_args+=("--log" "$log_path")

  err="$(mktemp)"
  if diag_json="$("${diag_args[@]}" 2>"$err")" && jq -e . >/dev/null 2>&1 <<<"$diag_json"; then
    rm -f "$err"
    jq -c . <<<"$diag_json"
    return
  fi

  empty_run_diagnostics_json "unavailable" "$(cat "$err")"
  rm -f "$err"
}

emit_run_report_json() {
  local kind="$1" file="$2" run_json diagnostics_json
  run_json="$(emit_run_verdict_json "$kind" "$file")"
  diagnostics_json="$(emit_run_diagnostics_json "$kind" "$run_json")"
  jq -c --argjson diagnostics "$diagnostics_json" '. + {diagnostics:$diagnostics}' <<<"$run_json"
}

emit_single_run_json() {
  local kind="$1" file="$2" report_json
  report_json="$(emit_run_report_json "$kind" "$file")"
  jq -c --arg schema "kg.ios.run.v1" '. + {schema:$schema}' <<<"$report_json"
}

runs_summary_json() {
  local build_json="$1" test_json="$2" archive_json="$3"
  jq -n \
    --argjson build "$build_json" \
    --argjson test "$test_json" \
    --argjson archive "$archive_json" \
    '
    def bad_result($run):
      (($run.result // "unknown") != "ok")
      and (($run.result // "unknown") != "missing");
    def missing_result($run): (($run.result // "unknown") == "missing");
    def malformed_result($run): (($run.result // "unknown") == "malformed");
    def diag_errors($run): ($run.diagnostics.counts.errors // 0);
    def diag_warnings($run): ($run.diagnostics.counts.warnings // 0);
    def failed_tests($run): ($run.diagnostics.counts.failedTests // 0);
    {
      verdict:(
        if (bad_result($build) or bad_result($test) or bad_result($archive) or diag_errors($build) > 0 or diag_errors($test) > 0 or diag_errors($archive) > 0 or failed_tests($test) > 0) then "block"
        elif (diag_warnings($build) + diag_warnings($test) + diag_warnings($archive)) > 0 then "warn"
        elif (missing_result($build) and missing_result($test) and missing_result($archive)) then "unknown"
        else "pass"
        end
      ),
      counts:{
        errors:(diag_errors($build) + diag_errors($test) + diag_errors($archive)),
        warnings:(diag_warnings($build) + diag_warnings($test) + diag_warnings($archive)),
        failedTests:failed_tests($test),
        missing:([ $build, $test, $archive ] | map(select(missing_result(.))) | length),
        malformed:([ $build, $test, $archive ] | map(select(malformed_result(.))) | length),
        failing:([ $build, $test, $archive ] | map(select(bad_result(.))) | length)
      }
    }'
}

cmd_runs_json() {
  local build_json test_json archive_json summary_json generated_at
  build_json="$(emit_run_report_json build "$(verdict_file_for build)")"
  test_json="$(emit_run_report_json test "$(verdict_file_for test)")"
  archive_json="$(emit_run_report_json archive "$(verdict_file_for archive)")"
  summary_json="$(runs_summary_json "$build_json" "$test_json" "$archive_json")"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  jq -n \
    --arg schema "kg.ios.runs.v1" \
    --arg generated_at "$generated_at" \
    --argjson build "$build_json" \
    --argjson test "$test_json" \
    --argjson archive "$archive_json" \
    --argjson summary "$summary_json" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      summary:$summary,
      build:$build,
      test:$test,
      archive:$archive
    }'
}

cmd_runs() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh runs [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown runs option: $1" >&2
        return 1
        ;;
    esac
  done

  if (( json )); then
    cmd_runs_json
    return
  fi

  local summary_json
  summary_json="$(cmd_runs_json | jq -c '.summary')"
  echo "[ios][runs] summary verdict=$(jq -r '.verdict' <<<"$summary_json") errors=$(jq -r '.counts.errors' <<<"$summary_json") warnings=$(jq -r '.counts.warnings' <<<"$summary_json") failedTests=$(jq -r '.counts.failedTests' <<<"$summary_json") missing=$(jq -r '.counts.missing' <<<"$summary_json") malformed=$(jq -r '.counts.malformed' <<<"$summary_json") failing=$(jq -r '.counts.failing' <<<"$summary_json")"

  local kind file run_json result reason caller elapsed executed log_path xcresult_path log_exists xcresult_exists diag_source diag_result diag_errors diag_warnings timing_summary cache_status
  for kind in build test archive; do
    file="$(verdict_file_for "$kind")"
    run_json="$(emit_run_report_json "$kind" "$file")"
    result="$(jq -r '.result // "unknown"' <<<"$run_json")"
    reason="$(jq -r '.reason // "none"' <<<"$run_json")"
    caller="$(jq -r '.caller // "unknown"' <<<"$run_json")"
    elapsed="$(jq -r '.elapsed // "unknown"' <<<"$run_json")"
    executed="$(jq -r '.executed // "n/a"' <<<"$run_json")"
    log_path="$(jq -r '.artifacts.log // empty' <<<"$run_json")"
    xcresult_path="$(jq -r '.artifacts.xcresult // empty' <<<"$run_json")"
    log_exists="$(jq -r '.artifacts.logExists' <<<"$run_json")"
    xcresult_exists="$(jq -r '.artifacts.xcresultExists' <<<"$run_json")"
    diag_source="$(jq -r '.diagnostics.source // "unknown"' <<<"$run_json")"
    diag_result="$(jq -r '.diagnostics.result // "unknown"' <<<"$run_json")"
    diag_errors="$(jq -r '.diagnostics.counts.errors // 0' <<<"$run_json")"
    diag_warnings="$(jq -r '.diagnostics.counts.warnings // 0' <<<"$run_json")"
    timing_summary="$(jq -r '
      if (.timings // null) == null then
        ""
      else
        (.timings | to_entries | map(select(.value != null) | "\(.key)=\(.value)") | join(" "))
      end
    ' <<<"$run_json")"
    cache_status="$(jq -r '.cache.status // empty' <<<"$run_json")"
    echo "[ios][run] kind=$kind status=${result:-unknown} caller=${caller:-unknown} elapsed=${elapsed:-unknown} executed=${executed:-n/a} reason=${reason:-none} verdict=$file"
    [[ -n "$log_path" ]] && echo "[ios][run] kind=$kind log=$log_path exists=$log_exists"
    [[ -n "$xcresult_path" ]] && echo "[ios][run] kind=$kind xcresult=$xcresult_path exists=$xcresult_exists"
    [[ -n "$cache_status" ]] && echo "[ios][run] kind=$kind cacheStatus=$cache_status"
    [[ -n "$timing_summary" ]] && echo "[ios][run] kind=$kind timings $timing_summary"
    echo "[ios][run] kind=$kind diagnostics source=$diag_source result=$diag_result errors=$diag_errors warnings=$diag_warnings"
    jq -r --arg kind "$kind" '.diagnostics.diagnostics[]? | "[ios][run][\(.severity)] kind=\($kind) category=\(.category) \(.message)"' <<<"$run_json"
  done
  return 0
}
