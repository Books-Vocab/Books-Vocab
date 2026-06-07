cmd_commands_json() {
  jq -n '{
    schema:"kg.ios.commands.v1",
    generated_at:(now | strftime("%Y-%m-%dT%H:%M:%SZ")),
    commands:[
      {
        key:"status",
        aliases:[],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh status",
        delegate:null,
        purpose:"project, Organizer, and TestFlight status summary",
        jsonSchemas:[]
      },
      {
        key:"build",
        aliases:[],
        sideEffect:"local-build",
        command:"./ops/ios_ops.sh build [ios_build.sh args...]",
        delegate:"./ops/ios_build.sh",
        purpose:"Release compile gate with xcresult/log diagnostics",
        jsonSchemas:[]
      },
      {
        key:"test",
        aliases:[],
        sideEffect:"local-test",
        command:"./ops/ios_ops.sh test [ios_test.sh args...]",
        delegate:"./ops/ios_test.sh",
        purpose:"scoped iOS verification with false-green protection",
        jsonSchemas:[]
      },
      {
        key:"archive",
        aliases:["release"],
        sideEffect:"local-archive; external-upload only with --upload",
        command:"./ops/ios_ops.sh archive [--upload] [ios_release.sh args...]",
        delegate:"./ops/ios_release.sh",
        purpose:"archive/export and optional TestFlight upload",
        jsonSchemas:[]
      },
      {
        key:"archives",
        aliases:[],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh archives [list|latest|inspect ...]",
        delegate:"./ops/ios_archive.sh",
        purpose:"inspect local Xcode Organizer archives",
        jsonSchemas:["kg.ios.archives.v1"]
      },
      {
        key:"issues",
        aliases:[],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh issues --log <xcodebuild.log> [--json]",
        delegate:"./ops/ios_diagnostics.py",
        purpose:"parse xcresult/log diagnostics",
        jsonSchemas:["kg.ios.diagnostics.v1"]
      },
      {
        key:"logs",
        aliases:[],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh logs [--since 5m] [--predicate <predicate>] [--limit 200] [--json]",
        delegate:null,
        purpose:"runtime log console with framework noise filtering",
        jsonSchemas:["kg.ios.logs.v1"]
      },
      {
        key:"sentry",
        aliases:[],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh sentry",
        delegate:null,
        purpose:"iOS Sentry wiring summary",
        jsonSchemas:[]
      },
      {
        key:"doctor",
        aliases:[],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh doctor [--json]",
        delegate:null,
        purpose:"release readiness checks",
        jsonSchemas:["kg.ios.doctor.v1"]
      },
      {
        key:"workflow",
        aliases:["flow"],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh workflow release [--json]",
        delegate:null,
        purpose:"release workflow steps and next commands",
        jsonSchemas:["kg.ios.workflow.v1"]
      },
      {
        key:"gate",
        aliases:["verdict"],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh gate release [--json]",
        delegate:null,
        purpose:"release hard-stop verdict with stable exit codes",
        jsonSchemas:["kg.ios.gate.v1"]
      },
      {
        key:"xcode",
        aliases:["environment"],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh xcode [--json]",
        delegate:null,
        purpose:"Xcode project, destination, and simulator inventory",
        jsonSchemas:["kg.ios.xcode.v1"]
      },
      {
        key:"simulator",
        aliases:["sim"],
        sideEffect:"read-only status; local-simulator-lifecycle launch/terminate; local-artifact screenshot",
        command:"./ops/ios_ops.sh simulator status [--json] | launch [--device booted] [--json] [-- app args...] | terminate [--device booted] [--json] | screenshot --out <png> [--device booted] [--json]",
        delegate:null,
        purpose:"booted simulator status, app launch/terminate, app data container lookup, and local screenshot artifact capture",
        jsonSchemas:["kg.ios.simulator.v1"]
      },
      {
        key:"runs",
        aliases:["reports"],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh runs [--json]",
        delegate:null,
        purpose:"latest build/test verdicts and artifacts",
        jsonSchemas:["kg.ios.runs.v1"]
      },
      {
        key:"snapshot",
        aliases:["dashboard"],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh snapshot [--json] [--skip-xcode] [--skip-simulator] [--include-logs] [--log-since 5m] [--log-limit 200]",
        delegate:null,
        purpose:"single-call project/readiness/workflow/xcode/simulator/runs dashboard, with optional runtime logs",
        jsonSchemas:["kg.ios.snapshot.v1","kg.ios.gate.v1","kg.ios.xcode.v1","kg.ios.simulator.v1","kg.ios.logs.v1"]
      },
      {
        key:"catalog",
        aliases:[],
        sideEffect:"local-test; local-artifact export",
        command:"./ops/ios_ops.sh catalog prepare [--destination <xcodebuild-destination>] [--json] | ./ops/ios_ops.sh catalog snapshots [--out-root <dir>] [--destination <xcodebuild-destination>] [--group <category>]... [--scenario <category/title>]... [--reuse-build] [--json] | ./ops/ios_ops.sh catalog clean [--json]",
        delegate:null,
        purpose:"prepare or reuse catalog snapshot build cache, batch-render Playbook scenarios, and clean local snapshot cache",
        jsonSchemas:["kg.ios.catalog.prepare.v1","kg.ios.catalog.v1","kg.ios.catalog.clean.v1"]
      },
      {
        key:"commands",
        aliases:["capabilities"],
        sideEffect:"read-only",
        command:"./ops/ios_ops.sh commands [--json]",
        delegate:null,
        purpose:"self-describing command catalog for agents",
        jsonSchemas:["kg.ios.commands.v1"]
      }
    ]
  }'
}

cmd_commands() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh commands [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown commands option: $1" >&2
        return 1
        ;;
    esac
  done

  if (( json )); then
    cmd_commands_json
    return
  fi

  cmd_commands_json | jq -r '.commands[] | "[ios][command] key=\(.key) sideEffect=\(.sideEffect) command=\"\(.command)\" schemas=\((.jsonSchemas // []) | join(","))"'
}
