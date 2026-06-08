#!/usr/bin/env bash
# ios_ops_snapshot.sh — sourceable first-screen dashboard commands for ios_ops.sh.

cmd_snapshot_json() {
  local include_xcode="$1" include_simulator="$2" include_logs="$3" log_since="$4" log_limit="$5" log_predicate="$6"
  local doctor_json workflow_json gate_json xcode_json simulator_json runs_json logs_json sentry_json generated_at simulator_rc
  if ! doctor_json="$(cmd_doctor_json)"; then
    return 1
  fi
  if ! workflow_json="$(cmd_workflow_release_json)"; then
    return 1
  fi
  if ! gate_json="$(cmd_gate_release_json_from_state "$doctor_json" "$workflow_json")"; then
    return 1
  fi
  if ! sentry_json="$(jq -c '.sentry' <<<"$doctor_json")"; then
    return 1
  fi
  if [[ -z "$sentry_json" || "$sentry_json" == "null" ]]; then
    return 1
  fi
  if (( include_xcode )); then
    if ! xcode_json="$(cmd_xcode_json)"; then
      return 1
    fi
  else
    xcode_json='null'
  fi
  if (( include_simulator )); then
    simulator_rc=0
    simulator_json="$(cmd_simulator_status_json)" || simulator_rc=$?
    if [[ -z "$simulator_json" ]]; then
      return "$simulator_rc"
    fi
  else
    simulator_json='null'
  fi
  if ! runs_json="$(cmd_runs_json)"; then
    return 1
  fi
  if (( include_logs )); then
    if logs_json="$(cmd_logs_json "$log_since" "$log_predicate" "$log_limit")"; then
      :
    else
      return $?
    fi
  else
    logs_json='null'
  fi
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  jq -n \
    --arg schema "kg.ios.snapshot.v1" \
    --arg generated_at "$generated_at" \
    --argjson doctor "$doctor_json" \
    --argjson workflow "$workflow_json" \
    --argjson gate "$gate_json" \
    --argjson sentry "$sentry_json" \
    --argjson xcode "$xcode_json" \
    --argjson simulator "$simulator_json" \
    --argjson runs "$runs_json" \
    --argjson logs "$logs_json" \
    '
    def n($v): ($v // 0);
    def diag_actions($kind; $diag):
      [($diag.diagnostics // [])[]? | {
        source:("runs." + $kind + ".diagnostics"),
        severity:(if .severity == "error" then "error" else "warn" end),
        category:(.category // null),
        message:(.message // ""),
        file:(.file // null),
        line:(.line // null),
        command:(
          if $kind == "build" then "./ops/ios_ops.sh build"
          elif $kind == "archive" then "./ops/ios_ops.sh archive"
          else "./ops/ios_ops.sh test"
          end
        )
      }];
    def gate_actions($items; $severity):
      [($items // [])[]? | {
        source:"gate",
        severity:$severity,
        key:(.key // null),
        status:(.status // null),
        command:(.command // null),
        message:(.detail // .note // "")
      }];
    def source_errors($source; $items; $severity; $command):
      [($items // [])[]? | {
        source:$source,
        severity:$severity,
        key:(.key // .source // null),
        status:(.status // null),
        command:$command,
        message:(.error // .detail // .note // "")
      }];
    def sentry_actions($sentry):
      [
        if ($sentry.source.exists // false) then empty else {
          source:"sentry",
          severity:"warn",
          key:"source",
          status:"warn",
          command:"./ops/ios_ops.sh sentry --json",
          message:("source missing: " + ($sentry.source.path // "unknown"))
        } end,
        if ($sentry.wiring.canImportGuard // false) then empty else {
          source:"sentry",
          severity:"warn",
          key:"canImportGuard",
          status:"warn",
          command:"./ops/ios_ops.sh sentry --json",
          message:"missing canImport(Sentry) guard"
        } end,
        if ($sentry.wiring.dsnKeyReference // false) then empty else {
          source:"sentry",
          severity:"warn",
          key:"dsnKeyReference",
          status:"warn",
          command:"./ops/ios_ops.sh sentry --json",
          message:"missing Sentry DSN/debug test wiring"
        } end
      ];
    def timing_summary($run):
      {
        cacheStatus:($run.cache.status // null),
        totalMs:($run.timings.totalMs // null),
        lockWaitMs:($run.timings.lockWaitMs // null),
        bootMs:($run.timings.bootMs // null),
        xcodebuildMs:($run.timings.xcodebuildMs // null),
        buildForTestingMs:($run.timings.buildForTestingMs // null),
        testInvocationMs:($run.timings.testInvocationMs // null),
        testBodyMs:($run.timings.testBodyMs // null),
        xcresultSessionMs:($run.timings.xcresultSessionMs // null),
        xcresultHarnessOverheadMs:($run.timings.xcresultHarnessOverheadMs // null),
        appLaunchAverageMs:($run.timings.appLaunchAverageMs // null),
        appLaunchSamples:($run.timings.appLaunchSamples // null),
        invocationOverheadMs:($run.timings.invocationOverheadMs // null)
      };
    def archive_timing_summary($run):
      {
        totalMs:($run.timings.totalMs // null),
        lockWaitMs:($run.timings.lockWaitMs // null),
        archiveMs:($run.timings.archiveMs // null),
        exportMs:($run.timings.exportMs // null),
        uploadMs:($run.timings.uploadMs // null)
      };
    def simulator_timing_summary($simulator):
      if $simulator == null then
        null
      else
        {
          totalMs:($simulator.timings.totalMs // null),
          simctlDevicesMs:($simulator.timings.simctlDevicesMs // null),
          appContainerMs:($simulator.timings.appContainerMs // null),
          appProcessMs:($simulator.timings.appProcessMs // null)
        }
      end;
    (
      n($doctor.summary.counts.ok) as $readinessOk
      | n($doctor.summary.counts.warn) as $readinessWarns
      | n($doctor.summary.counts.block) as $readinessBlocks
      | n($workflow.summary.counts.ready) as $workflowReady
      | n($workflow.summary.counts.todo) as $workflowTodos
      | n($workflow.summary.counts.warn) as $workflowWarns
      | n($workflow.summary.counts.block) as $workflowBlocks
      | n($workflow.summary.counts.manual) as $workflowManual
      | n($gate.summary.blocks) as $gateBlocks
      | n($gate.summary.warnings) as $gateWarnings
      | n($gate.summary.todos) as $gateTodos
      | n($gate.summary.manual) as $gateManual
      | n($runs.build.diagnostics.counts.errors) as $buildErrors
      | n($runs.build.diagnostics.counts.warnings) as $buildWarnings
      | n($runs.test.diagnostics.counts.errors) as $testErrors
      | n($runs.test.diagnostics.counts.warnings) as $testWarnings
      | n($runs.test.diagnostics.counts.failedTests) as $testFailures
      | n($runs.archive.diagnostics.counts.errors) as $archiveErrors
      | n($runs.archive.diagnostics.counts.warnings) as $archiveWarnings
      | (
          (if ($sentry.source.exists // false) then 0 else 1 end)
          + (if ($sentry.wiring.canImportGuard // false) then 0 else 1 end)
          + (if ($sentry.wiring.dsnKeyReference // false) then 0 else 1 end)
        ) as $sentryWarnings
      | (if $xcode == null then 0 else ($xcode.errors // [] | length) end) as $xcodeErrors
      | (if $simulator == null then 0 elif $simulator.status == "error" then (($simulator.errors // []) | length) else 0 end) as $simulatorErrors
      | (if $logs == null then 0 else n($logs.summary.filteredCount) end) as $runtimeLogs
      | (
          gate_actions($gate.blocks; "block")
          + diag_actions("build"; $runs.build.diagnostics)
          + diag_actions("test"; $runs.test.diagnostics)
          + diag_actions("archive"; $runs.archive.diagnostics)
          + sentry_actions($sentry)
          + source_errors("xcode"; (if $xcode == null then [] else $xcode.errors end); "warn"; "./ops/ios_ops.sh xcode --json")
          + source_errors("simulator"; (if $simulator == null then [] else $simulator.errors end); "warn"; "./ops/ios_ops.sh simulator status --json")
          + gate_actions($gate.warnings; "warn")
          + gate_actions($gate.todos; "todo")
          + gate_actions($gate.manual; "manual")
        ) as $nextActions
      | {
      schema:$schema,
      generated_at:$generated_at,
      summary:{
        verdict:(
          if ($gateBlocks + $buildErrors + $testErrors + $testFailures + $archiveErrors) > 0 then "block"
          elif ($gateWarnings + $buildWarnings + $testWarnings + $archiveWarnings + $sentryWarnings + $xcodeErrors + $simulatorErrors) > 0 then "warn"
          else "pass"
          end
        ),
        counts:{
          readinessOk:$readinessOk,
          readinessWarns:$readinessWarns,
          readinessBlocks:$readinessBlocks,
          workflowReady:$workflowReady,
          workflowTodos:$workflowTodos,
          workflowWarns:$workflowWarns,
          workflowBlocks:$workflowBlocks,
          workflowManual:$workflowManual,
          gateBlocks:$gateBlocks,
          gateWarnings:$gateWarnings,
          gateTodos:$gateTodos,
          gateManual:$gateManual,
          buildErrors:$buildErrors,
          buildWarnings:$buildWarnings,
          testErrors:$testErrors,
          testWarnings:$testWarnings,
          testFailures:$testFailures,
          archiveErrors:$archiveErrors,
          archiveWarnings:$archiveWarnings,
          sentryWarnings:$sentryWarnings,
          xcodeErrors:$xcodeErrors,
          simulatorErrors:$simulatorErrors,
          runtimeLogs:$runtimeLogs
        },
        nextActions:$nextActions,
        timings:{
          build: timing_summary($runs.build),
          test: timing_summary($runs.test),
          archive: archive_timing_summary($runs.archive),
          simulator: simulator_timing_summary($simulator)
        }
      },
      project:$doctor.project,
      organizer:$doctor.organizer,
      testflight:$doctor.testflight,
      readiness:$doctor.readiness,
      workflow:$workflow,
      gate:$gate,
      sentry:$sentry,
      xcode:$xcode,
      simulator:$simulator,
      runs:$runs,
      logs:$logs
      }
    )'
}

cmd_snapshot_text_from_json() {
  local payload="$1"
  jq -r '
    .summary.counts as $c
    | .summary.timings as $t
    | "[ios][summary] schema=\(.schema) verdict=\(.summary.verdict) readinessOk=\($c.readinessOk) readinessWarns=\($c.readinessWarns) readinessBlocks=\($c.readinessBlocks) workflowReady=\($c.workflowReady) workflowTodos=\($c.workflowTodos) workflowWarns=\($c.workflowWarns) workflowBlocks=\($c.workflowBlocks) workflowManual=\($c.workflowManual) gateBlocks=\($c.gateBlocks) gateWarnings=\($c.gateWarnings) gateTodos=\($c.gateTodos) buildErrors=\($c.buildErrors) buildWarnings=\($c.buildWarnings) testErrors=\($c.testErrors) testWarnings=\($c.testWarnings) testFailures=\($c.testFailures) archiveErrors=\($c.archiveErrors) archiveWarnings=\($c.archiveWarnings) sentryWarnings=\($c.sentryWarnings) xcodeErrors=\($c.xcodeErrors) simulatorErrors=\($c.simulatorErrors) runtimeLogs=\($c.runtimeLogs)",
      "[ios][timing] build cacheStatus=\($t.build.cacheStatus // "n/a") totalMs=\($t.build.totalMs // "n/a") bootMs=\($t.build.bootMs // "n/a") xcodebuildMs=\($t.build.xcodebuildMs // "n/a")",
      "[ios][timing] test cacheStatus=\($t.test.cacheStatus // "n/a") totalMs=\($t.test.totalMs // "n/a") bootMs=\($t.test.bootMs // "n/a") buildForTestingMs=\($t.test.buildForTestingMs // "n/a") testInvocationMs=\($t.test.testInvocationMs // "n/a") testBodyMs=\($t.test.testBodyMs // "n/a") xcresultSessionMs=\($t.test.xcresultSessionMs // "n/a") appLaunchAverageMs=\($t.test.appLaunchAverageMs // "n/a") appLaunchSamples=\($t.test.appLaunchSamples // "n/a") invocationOverheadMs=\($t.test.invocationOverheadMs // "n/a")",
      "[ios][timing] archive totalMs=\($t.archive.totalMs // "n/a") lockWaitMs=\($t.archive.lockWaitMs // "n/a") archiveMs=\($t.archive.archiveMs // "n/a") exportMs=\($t.archive.exportMs // "n/a") uploadMs=\($t.archive.uploadMs // "n/a")",
      (
        if $t.simulator == null then
          "[ios][timing] simulator totalMs=n/a simctlDevicesMs=n/a appContainerMs=n/a appProcessMs=n/a"
        else
          "[ios][timing] simulator totalMs=\($t.simulator.totalMs // "n/a") simctlDevicesMs=\($t.simulator.simctlDevicesMs // "n/a") appContainerMs=\($t.simulator.appContainerMs // "n/a") appProcessMs=\($t.simulator.appProcessMs // "n/a")"
        end
      ),
      (
        if (.summary.nextActions | length) == 0 then
          "[ios][next] none"
        else
          (.summary.nextActions[:12][] | "[ios][next] source=\(.source // "") severity=\(.severity // "info") key=\(.key // "") category=\(.category // "") command=\"\(.command // "")\" message=\"\(.message // "")\"")
        end
      ),
      "[ios][snapshot] project version=\(.project.version // "unknown") build=\(.project.build // "unknown") organizer=\(.organizer.latest.version // "unknown")(\(.organizer.latest.build // "unknown")) testflight=\(.testflight.latest_build // "unknown")",
      "[ios][snapshot] gate verdict=\(.gate.verdict // "unknown") blocks=\(.gate.summary.blocks // 0) warnings=\(.gate.summary.warnings // 0) todos=\(.gate.summary.todos // 0) manual=\(.gate.summary.manual // 0)",
      "[ios][snapshot] run kind=build result=\(.runs.build.result // "unknown") errors=\($c.buildErrors) warnings=\($c.buildWarnings) log=\(.runs.build.artifacts.log // "") xcresult=\(.runs.build.artifacts.xcresult // "")",
      "[ios][snapshot] run kind=test result=\(.runs.test.result // "unknown") executed=\(.runs.test.executed // "n/a") errors=\($c.testErrors) warnings=\($c.testWarnings) failures=\($c.testFailures) log=\(.runs.test.artifacts.log // "") xcresult=\(.runs.test.artifacts.xcresult // "")",
      "[ios][snapshot] run kind=archive result=\(.runs.archive.result // "unknown") errors=\($c.archiveErrors) warnings=\($c.archiveWarnings) log=\(.runs.archive.artifacts.log // "") xcresult=\(.runs.archive.artifacts.xcresult // "")",
      "[ios][snapshot] sentry sourceExists=\(.sentry.source.exists // false) canImportGuard=\(.sentry.wiring.canImportGuard // false) dsnKeyReference=\(.sentry.wiring.dsnKeyReference // false)",
      (if .xcode == null then "[ios][snapshot] xcode=skipped" else "[ios][snapshot] xcode version=\(.xcode.xcode.version // "unknown") build=\(.xcode.xcode.build // "unknown") destinations=\(.xcode.destinations.available | length) ineligible=\(.xcode.destinations.ineligible | length)" end),
      (if .simulator == null then "[ios][snapshot] simulator=skipped" else "[ios][snapshot] simulator status=\(.simulator.status) device=\(.simulator.device.name // "none") appProcess=\(.simulator.app.process.status // "unknown")" end),
      (if .logs == null then "[ios][snapshot] logs=skipped" else "[ios][snapshot] logs emitted=\(.logs.summary.emittedCount // 0) filtered=\(.logs.summary.filteredCount // 0) since=\(.logs.since // "")" end)
  ' <<<"$payload"
}

cmd_snapshot() {
  local json=0 include_xcode=1 include_simulator=1 include_logs=0 log_since="5m" log_limit=200 log_limit_num log_predicate="$DEFAULT_LOG_PREDICATE"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --include-xcode|--with-xcode) include_xcode=1; shift ;;
      --skip-xcode|--no-xcode) include_xcode=0; shift ;;
      --include-simulator|--with-simulator) include_simulator=1; shift ;;
      --skip-simulator|--no-simulator) include_simulator=0; shift ;;
      --include-logs|--with-logs) include_logs=1; shift ;;
      --log-since) log_since="${2:?--log-since needs value}"; shift 2 ;;
      --log-limit) log_limit="${2:?--log-limit needs value}"; shift 2 ;;
      --log-predicate) log_predicate="${2:?--log-predicate needs value}"; shift 2 ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh snapshot [--json] [--skip-xcode] [--skip-simulator] [--include-logs] [--log-since 5m] [--log-limit 200] [--log-predicate <predicate>]"
        return 0
        ;;
      *)
        echo "✗ unknown snapshot option: $1" >&2
        return 1
        ;;
    esac
  done
  if [[ -z "$log_limit" || "$log_limit" == *[!0-9]* ]]; then
    echo "✗ --log-limit must be a non-negative integer" >&2
    return 1
  fi
  log_limit_num="$((10#$log_limit))"

  if (( json )); then
    cmd_snapshot_json "$include_xcode" "$include_simulator" "$include_logs" "$log_since" "$log_limit_num" "$log_predicate"
    return
  fi

  local snapshot_json
  snapshot_json="$(cmd_snapshot_json "$include_xcode" "$include_simulator" "$include_logs" "$log_since" "$log_limit_num" "$log_predicate")" || return $?
  cmd_snapshot_text_from_json "$snapshot_json"
}
