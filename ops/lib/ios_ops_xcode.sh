#!/usr/bin/env bash
# ios_ops_xcode.sh — sourceable Xcode inventory commands for ios_ops.sh.

cmd_xcode_json() {
  local version_source project_list_source destinations_source simctl_source generated_at
  version_source="$(capture_source_text xcode_version read_xcode_version_text)"
  project_list_source="$(capture_source_json xcode_project_list read_xcode_project_list_json)"
  destinations_source="$(capture_source_text xcode_destinations read_xcode_destinations_text)"
  simctl_source="$(capture_source_json simctl_devices read_simctl_devices_json)"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

  jq -n \
    --arg schema "kg.ios.xcode.v1" \
    --arg generated_at "$generated_at" \
    --arg projectPath "$XCODEPROJ" \
    --arg scheme "$SCHEME" \
    --argjson versionSource "$version_source" \
    --argjson projectListSource "$project_list_source" \
    --argjson destinationsSource "$destinations_source" \
    --argjson simctlSource "$simctl_source" \
    '
    def trim: gsub("^\\s+|\\s+$";"");
    def parse_destination_line($line):
      ($line | capture("\\{\\s*(?<body>.*)\\s*\\}").body)
      | gsub(", platform:";"\u0000platform:")
      | gsub(", arch:";"\u0000arch:")
      | gsub(", variant:";"\u0000variant:")
      | gsub(", id:";"\u0000id:")
      | gsub(", OS:";"\u0000OS:")
      | gsub(", name:";"\u0000name:")
      | gsub(", error:";"\u0000error:")
      | split("\u0000")
      | map(try (capture("(?<key>[^:]+):(?<value>.*)") | {key:(.key|trim), value:(.value|trim)}) catch empty)
      | from_entries;
    def destination_sections($text):
      reduce ($text | split("\n")[]) as $line
        ({section:null, available:[], ineligible:[]};
          if ($line | test("Available destinations")) then
            .section = "available"
          elif ($line | test("Ineligible destinations")) then
            .section = "ineligible"
          elif (.section != null and ($line | test("\\{.*\\}"))) then
            (try parse_destination_line($line) catch null) as $destination
            | if $destination == null then
                .
              elif .section == "available" then
                .available += [$destination]
              else
                .ineligible += [$destination]
              end
          else
            .
          end
        );

    ($versionSource.output // "") as $versionText
    | ($projectListSource.payload.project // {configurations:[],name:null,schemes:[],targets:[]}) as $projectList
    | (destination_sections($destinationsSource.output // "")) as $destinations
    | (($simctlSource.payload.devices // {})) as $devices
    | [($devices | to_entries[]?.value[]?)] as $allDevices
    | {
        schema:$schema,
        generated_at:$generated_at,
        errors:(
          [$versionSource,$projectListSource,$destinationsSource,$simctlSource]
          | map(select(.status != "ok") | {source:.key,status,exitCode,error})
        ),
        sources:{
          xcode_version:{status:$versionSource.status,exitCode:$versionSource.exitCode,error:$versionSource.error},
          xcode_project_list:{status:$projectListSource.status,exitCode:$projectListSource.exitCode,error:$projectListSource.error},
          xcode_destinations:{status:$destinationsSource.status,exitCode:$destinationsSource.exitCode,error:$destinationsSource.error},
          simctl_devices:{status:$simctlSource.status,exitCode:$simctlSource.exitCode,error:$simctlSource.error}
        },
        xcode:{
          version:(($versionText | split("\n") | map(select(startswith("Xcode "))) | first // "") | sub("^Xcode "; "") | if . == "" then null else . end),
          build:(($versionText | split("\n") | map(select(startswith("Build version "))) | first // "") | sub("^Build version "; "") | if . == "" then null else . end),
          developerDir:(($versionText | split("\n") | map(select(startswith("DeveloperDir "))) | first // "") | sub("^DeveloperDir "; "") | if . == "" then null else . end)
        },
        project:{
          path:$projectPath,
          scheme:$scheme,
          list:$projectList
        },
        destinations:{
          source:"xcodebuild -showdestinations",
          status:$destinationsSource.status,
          exitCode:$destinationsSource.exitCode,
          error:$destinationsSource.error,
          available:$destinations.available,
          ineligible:$destinations.ineligible
        },
        simulators:{
          source:"xcrun simctl list devices --json",
          status:$simctlSource.status,
          exitCode:$simctlSource.exitCode,
          error:$simctlSource.error,
          summary:{
            total:($allDevices | length),
            available:($allDevices | map(select(.isAvailable == true)) | length),
            booted:($allDevices | map(select(.state == "Booted")) | length)
          },
          runtimes:(
            $devices
            | to_entries
            | map({
                runtime:.key,
                devices:(.value | map({
                  name,
                  udid,
                  state,
                  isAvailable:(.isAvailable // null),
                  deviceTypeIdentifier:(.deviceTypeIdentifier // null),
                  lastBootedAt:(.lastBootedAt // null)
                }))
              })
          )
        }
      }'
}

cmd_xcode() {
  local json=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh xcode [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown xcode option: $1" >&2
        return 1
        ;;
    esac
  done

  local payload
  payload="$(cmd_xcode_json)"
  if (( json )); then
    printf '%s\n' "$payload"
    return 0
  fi

  jq -r '
    "[ios][xcode] schema=\(.schema) version=\(.xcode.version // "unknown") build=\(.xcode.build // "unknown") developerDir=\(.xcode.developerDir // "unknown")",
    "[ios][xcode] project=\(.project.list.name // "unknown") scheme=\(.project.scheme) schemes=\((.project.list.schemes // []) | join(",")) targets=\((.project.list.targets // []) | join(","))",
    "[ios][xcode] destinations available=\(.destinations.available | length) ineligible=\(.destinations.ineligible | length)",
    "[ios][xcode] simulators total=\(.simulators.summary.total) available=\(.simulators.summary.available) booted=\(.simulators.summary.booted)",
    (.errors[]? | "[ios][xcode] error source=\(.source) status=\(.status) exitCode=\(.exitCode) error=\(.error // "")"),
    (.destinations.available[]? | "[ios][xcode] destination id=\(.id // "") platform=\(.platform // "") name=\(.name // "") os=\(.OS // .os // "") variant=\(.variant // "")")
  ' <<<"$payload"
}
