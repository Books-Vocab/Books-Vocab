#!/usr/bin/env bash
# ios_ops_catalog.sh — sourceable catalog snapshot export commands for ios_ops.sh.

# shellcheck source=ios_cache_evict.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ios_cache_evict.sh"
# shellcheck source=fixture_dataset_env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fixture_dataset_env.sh"

CATALOG_SCHEME="BooksAndVocabCatalogSnapshots"
CATALOG_LAST_BUILD_WALL_MS=0
CATALOG_LAST_COMMAND_WALL_MS=0

catalog_default_root() {
  local base="${TMPDIR:-$ROOT}"
  printf '%s/build/snapshots\n' "${base%/}"
}

catalog_default_derived_data_root() {
  printf '%s\n' "${KG_IOS_OPS_CATALOG_CACHE_ROOT:-$ROOT/.cache/ios-catalog-derived-data}"
}

catalog_workspace_snapshot_root() {
  printf '%s\n' "${KG_IOS_OPS_CATALOG_PERSIST_ROOT:-$ROOT/build/snapshots}"
}

catalog_artifact_name_from_generated_at() {
  local generated_at="$1"
  printf 'catalog-full-%s\n' "$(sed -E 's/^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$/\1\2\3-\4\5\6/' <<<"$generated_at")"
}

catalog_persist_workspace_artifact_json() {
  local source_root="$1" generated_at="$2"
  local workspace_root artifact_name artifact_root
  workspace_root="$(catalog_workspace_snapshot_root)"
  artifact_name="$(catalog_artifact_name_from_generated_at "$generated_at")"
  artifact_root="$workspace_root/$artifact_name"

  if [[ ! -d "$source_root" ]]; then
    jq -n \
      --arg root "$workspace_root" \
      --arg name "$artifact_name" \
      '{
        status:"error",
        root:$root,
        name:$name,
        error:"source-root-missing"
      }'
    return 0
  fi

  mkdir -p "$workspace_root" || {
    jq -n \
      --arg root "$workspace_root" \
      --arg name "$artifact_name" \
      '{
        status:"error",
        root:$root,
        name:$name,
        error:"workspace-root-create-failed"
      }'
    return 0
  }
  rm -rf "$artifact_root"
  if ! cp -R "$source_root" "$artifact_root"; then
    jq -n \
      --arg root "$workspace_root" \
      --arg name "$artifact_name" \
      --arg artifactRoot "$artifact_root" \
      '{
        status:"error",
        root:$root,
        name:$name,
        artifactRoot:$artifactRoot,
        error:"artifact-copy-failed"
      }'
    return 0
  fi

  jq -n \
    --arg root "$workspace_root" \
    --arg name "$artifact_name" \
    --arg artifactRoot "$artifact_root" \
    --arg reviewHtml "$artifact_root/UIreview.html" \
    --arg reviewManifest "$artifact_root/review_manifest.json" \
    --arg reviewState "$artifact_root/review_state.json" \
    '{
      status:"ok",
      root:$root,
      name:$name,
      artifactRoot:$artifactRoot,
      reviewHtml:$reviewHtml,
      reviewManifest:$reviewManifest,
      reviewState:$reviewState
    }'
}

catalog_write_run_receipt_json() {
  local out_root="$1" source_commit="$2" dataset_id="$3" dataset_sha256="$4" fixed_clock="$5"
  local test_exit="$6" copy_exit="$7" validation_status="$8" review_status="$9" appearance_status="${10}"
  local status="block" receipt
  if [[ "$test_exit" -eq 0 && "$copy_exit" -eq 0 && "$validation_status" != "error" && "$review_status" == "ok" && "$appearance_status" == "pass" ]]; then
    status="pass"
  fi
  receipt="$(jq -n \
    --arg status "$status" \
    --arg sourceCommit "$source_commit" \
    --arg datasetID "$dataset_id" \
    --arg datasetSHA256 "$dataset_sha256" \
    --arg fixedClock "$fixed_clock" \
    --arg validationStatus "$validation_status" \
    --arg reviewStatus "$review_status" \
    --arg appearanceStatus "$appearance_status" \
    --argjson testExit "$test_exit" \
    --argjson copyExit "$copy_exit" \
    '{
      schema:"kg.ios.catalog.run_receipt.v1",
      status:$status,
      sourceCommit:$sourceCommit,
      datasetID:$datasetID,
      datasetSHA256:$datasetSHA256,
      fixedClock:$fixedClock,
      testExit:$testExit,
      copyExit:$copyExit,
      validationStatus:$validationStatus,
      reviewStatus:$reviewStatus,
      appearanceStatus:$appearanceStatus
    }')"
  printf '%s\n' "$receipt" >"$out_root/catalog_run_receipt.json"
  printf '%s\n' "$receipt"
}

catalog_now_ms() {
  perl -MTime::HiRes=time -e 'printf "%.0f\n", time() * 1000'
}

# catalog_phase_emit — always-on phase milestone to stderr (stdout stays a pure
# JSON contract). Unlike catalog_trace_phase, this is NOT gated behind a debug
# flag: long xcodebuild phases must surface a live signal so callers do not have
# to side-channel via ps/xcresult to tell whether work is progressing.
catalog_phase_emit() {
  local phase="$1" event="$2" detail="${3:-}"
  if [[ -n "$detail" ]]; then
    printf '[ios][catalog] phase=%s %s %s\n' "$phase" "$event" "$detail" >&2
  else
    printf '[ios][catalog] phase=%s %s\n' "$phase" "$event" >&2
  fi
}

catalog_log_tail_line() {
  local log_path="$1"
  [[ -f "$log_path" ]] || { printf '<no-log>'; return 0; }
  tail -n 1 "$log_path" 2>/dev/null | tr -d '\n' | cut -c1-120
}

# catalog_run_xcodebuild_heartbeat — run a long xcodebuild invocation in the
# background while emitting periodic phase heartbeats to stderr, then return the
# real exit code. Mirrors the proven ios_test.sh heartbeat loop so catalog long
# tasks stop being silent black boxes.
# usage: catalog_run_xcodebuild_heartbeat <label> <log> <err> <append:0|1> -- <cmd> [args...]
catalog_run_xcodebuild_heartbeat() {
  local label="$1" log_path="$2" err_path="$3" append="$4"
  shift 4
  [[ "${1:-}" == "--" ]] && shift
  local pid start now hb_at tick_at elapsed interval tick_interval rc
  interval="${KG_IOS_OPS_CATALOG_HEARTBEAT_SEC:-20}"     # detail line cadence
  tick_interval="${KG_IOS_OPS_CATALOG_TICK_SEC:-3}"      # short keep-alive tick
  if [[ "$append" == "1" ]]; then
    "$@" >>"$log_path" 2>>"$err_path" &
  else
    "$@" >"$log_path" 2>"$err_path" &
  fi
  pid=$!
  start="$(date +%s)"
  hb_at="$start"
  tick_at="$start"
  catalog_phase_emit "$label" "start" "pid=$pid log=$log_path"
  while kill -0 "$pid" 2>/dev/null; do
    now="$(date +%s)"
    elapsed=$(( now - start ))
    if (( now - hb_at >= interval )); then
      catalog_phase_emit "$label" "running" "${elapsed}s pid=$pid last=$(catalog_log_tail_line "$log_path")"
      hb_at="$now"
      tick_at="$now"
    elif (( now - tick_at >= tick_interval )); then
      catalog_phase_emit "$label" "tick" "${elapsed}s"
      tick_at="$now"
    fi
    sleep 2
  done
  if wait "$pid"; then rc=0; else rc=$?; fi
  catalog_phase_emit "$label" "done" "exitCode=$rc"
  return "$rc"
}

catalog_trace_phase() {
  local phase="$1" event="$2" detail="${3:-}"
  [[ "${KG_IOS_OPS_CATALOG_TRACE:-0}" == "1" ]] || return 0
  if [[ -n "$detail" ]]; then
    printf '[ios][catalog][trace] phase=%s event=%s %s\n' "$phase" "$event" "$detail" >&2
  else
    printf '[ios][catalog][trace] phase=%s event=%s\n' "$phase" "$event" >&2
  fi
}

catalog_fixture_write_png() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  swift - "$path" <<'SWIFT'
import AppKit
import Foundation

let path = CommandLine.arguments[1]
let size = NSSize(width: 8, height: 8)
let image = NSImage(size: size)
image.lockFocus()
if ProcessInfo.processInfo.environment["KG_IOS_OPS_CATALOG_FIXTURE_TRANSPARENT"] == "1" {
  image.unlockFocus()
  let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
  let png = bitmap.representation(using: .png, properties: [:])!
  try png.write(to: URL(fileURLWithPath: path))
  exit(0)
}
NSColor.white.setFill()
NSBezierPath(rect: NSRect(x: 0, y: 0, width: 8, height: 8)).fill()
if ProcessInfo.processInfo.environment["KG_IOS_OPS_CATALOG_FIXTURE_UNIFORM"] == "1" {
  image.unlockFocus()
  let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
  let png = bitmap.representation(using: .png, properties: [:])!
  try png.write(to: URL(fileURLWithPath: path))
  exit(0)
}
NSColor.black.setFill()
NSBezierPath(rect: NSRect(x: 0, y: 0, width: 4, height: 4)).fill()
NSColor.systemBlue.setFill()
NSBezierPath(rect: NSRect(x: 4, y: 4, width: 4, height: 4)).fill()
image.unlockFocus()
let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
let png = bitmap.representation(using: .png, properties: [:])!
try png.write(to: URL(fileURLWithPath: path))
SWIFT
}

catalog_fixture_seed_snapshots() {
  local container_root="$1" source_commit="$2" dataset_id="$3" dataset_sha256="$4" fixed_clock="$5"
  local snapshot_root="$container_root/tmp/kg-catalog-snapshots"
  catalog_fixture_write_png "$snapshot_root/iPhone15Pro/Bookshelf/bookshelf-grid.png"
  catalog_fixture_write_png "$snapshot_root/iPhone15Pro/Today Review/review-card.png"
  cat >"$snapshot_root/catalog_index.json" <<'JSON'
{
  "version": 1,
  "surfaces": {
    "Bookshelf": {
      "kind": "featureScreen",
      "feature": "bookshelf",
      "screen": "bookshelf",
      "backing": "BookshelfView"
    },
    "Today Review": {
      "kind": "featureScreen",
      "feature": "todayReview",
      "screen": "todayReview",
      "backing": "TodayReviewView"
    }
  }
}
JSON
  cat >"$snapshot_root/ui_graph.json" <<'JSON'
{
  "schema": "kg.ui.graph.v1",
  "nodeCount": 2,
  "edgeCount": 0,
  "nodes": [
    {
      "id": "BookshelfView",
      "kind": "struct",
      "name": "BookshelfView",
      "file": "ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift",
      "surfaces": ["Bookshelf"]
    },
    {
      "id": "TodayReviewView",
      "kind": "struct",
      "name": "TodayReviewView",
      "file": "ios/BooksAndVocab/Views/TodayReview/TodayReviewView.swift",
      "surfaces": ["Today Review"]
    }
  ],
  "edges": []
}
JSON
  local appearance_status observed_at bookshelf_sha review_sha
  appearance_status="${KG_IOS_OPS_CATALOG_FIXTURE_APPEARANCE_STATUS:-pass}"
  observed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  bookshelf_sha="$(shasum -a 256 "$snapshot_root/iPhone15Pro/Bookshelf/bookshelf-grid.png" | awk '{print $1}')"
  review_sha="$(shasum -a 256 "$snapshot_root/iPhone15Pro/Today Review/review-card.png" | awk '{print $1}')"
  jq -n \
    --arg status "$appearance_status" \
    --arg sourceCommit "$source_commit" \
    --arg datasetID "$dataset_id" \
    --arg datasetSHA256 "$dataset_sha256" \
    --arg fixedClock "$fixed_clock" \
    --arg observedAt "$observed_at" \
    --arg bookshelfSHA "$bookshelf_sha" \
    --arg reviewSHA "$review_sha" \
    '{
      schema:"kg.catalog.appearance.v1",
      verdict:{status:$status,proofCount:2},
      sourceCommit:$sourceCommit,
      datasetID:$datasetID,
      datasetSHA256:$datasetSHA256,
      fixedClock:$fixedClock,
      observedAt:$observedAt,
      captures:[
        {id:"fixture-bookshelf-light",requestedAppearance:"light",actualAppearance:"light",pixelSHA256:$bookshelfSHA},
        {id:"fixture-review-dark",requestedAppearance:"dark",actualAppearance:"dark",pixelSHA256:$reviewSHA}
      ]
    }' >"$snapshot_root/catalog_appearance.json"
}

catalog_fixture_seed_cache() {
  local derived_data_root="$1"
  local products_root app_bundle test_bundle xctestrun_path
  products_root="$derived_data_root/Build/Products"
  app_bundle="$products_root/Debug-iphonesimulator/BooksAndVocab.app"
  test_bundle="$app_bundle/PlugIns/BooksAndVocabTests.xctest"
  xctestrun_path="$products_root/BooksAndVocabCatalogSnapshots_BooksAndVocabCatalogSnapshots_iphonesimulator26.4-arm64.xctestrun"

  mkdir -p "$test_bundle"
  cat >"$xctestrun_path" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>TestConfigurations</key>
  <array>
    <dict>
      <key>TestTargets</key>
      <array>
        <dict>
          <key>BlueprintName</key>
          <string>BooksAndVocabTests</string>
        </dict>
      </array>
    </dict>
  </array>
</dict>
</plist>
EOF
}

catalog_snapshot_root_from_log() {
  local log_path="$1"
  [[ -f "$log_path" ]] || return 1
  sed -n 's/^KG catalog snapshots written to: //p' "$log_path" | tail -n 1
}

catalog_prepare_output_root() {
  local out_root="$1"
  mkdir -p "$out_root"
  find "$out_root" -mindepth 1 -delete 2>/dev/null || true
}

catalog_find_xctestrun() {
  local derived_data_root="$1"
  [[ -d "$derived_data_root/Build/Products" ]] || return 1
  rg --files "$derived_data_root/Build/Products" -g '*.xctestrun' -g '!*.scoped.xctestrun' 2>/dev/null | head -1
}

catalog_build_input_paths() {
  {
    printf '%s\n' \
      "ios/Info.plist" \
      "ios/BooksAndVocab.xcodeproj/project.pbxproj" \
      "ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocab.xcscheme" \
      "ios/BooksAndVocab.xcodeproj/xcshareddata/xcschemes/BooksAndVocabCatalogSnapshots.xcscheme" \
      "ios/BooksAndVocab.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
    rg --files ios/BooksAndVocab ios/BooksAndVocabTests -g '*.swift' -g '*.plist'
  } | sort -u
}

catalog_build_cache_key() {
  local destination="$1"
  local xcode_version
  xcode_version="$(xcodebuild -version 2>/dev/null || true)"
  {
    printf 'destination=%s\n' "$destination"
    printf 'xcode=%s\n' "$xcode_version"
    # Hash all inputs in a single shasum process instead of one fork per file
    # (~5.3s -> ~0.05s). Paths are already sorted+unique and relative to the
    # repo root, so the digest stays stable across worktrees and listing order.
    catalog_build_input_paths \
      | ( cd "$ROOT" && tr '\n' '\0' | xargs -0 shasum -a 256 2>/dev/null )
  } | shasum -a 256 | awk '{print $1}'
}

catalog_resolve_derived_data_root() {
  local destination="$1"
  local cache_root cache_key
  cache_root="$(catalog_default_derived_data_root)"
  cache_key="$(catalog_build_cache_key "$destination")"
  mkdir -p "$cache_root"
  printf '%s/%s\n' "$cache_root" "$cache_key"
}

catalog_cached_products_ready() {
  local derived_data_root="$1"
  local xctestrun_path="$2"
  local products_root app_bundle test_bundle
  [[ -n "$xctestrun_path" && -f "$xctestrun_path" ]] || return 1
  products_root="$(dirname "$xctestrun_path")"
  app_bundle="$products_root/Debug-iphonesimulator/BooksAndVocab.app"
  test_bundle="$app_bundle/PlugIns/BooksAndVocabTests.xctest"
  [[ -d "$app_bundle" && -d "$test_bundle" ]]
}

catalog_scope_file_path() {
  local device_udid="$1"
  printf '%s/Library/Developer/CoreSimulator/Devices/%s/data/tmp/kg-catalog-scope.json\n' "$HOME" "$device_udid"
}

catalog_named_dataset_path() {
  local dataset_name="$1"
  printf '%s/ops/fixtures/ui_worlds/%s.json\n' "$ROOT" "$dataset_name"
}

catalog_write_scope_file() {
  local device_udid="$1" groups_csv="$2" scenarios_csv="$3"
  local scope_path groups_json scenarios_json
  scope_path="$(catalog_scope_file_path "$device_udid")"
  mkdir -p "$(dirname "$scope_path")"
  if [[ -z "$groups_csv" && -z "$scenarios_csv" ]]; then
    rm -f "$scope_path"
    return 0
  fi
  groups_json="$(jq -Rn --arg value "$groups_csv" '$value | if . == "" then [] else split(",") end')"
  scenarios_json="$(jq -Rn --arg value "$scenarios_csv" '$value | if . == "" then [] else split(",") end')"
  jq -n \
    --argjson groups "$groups_json" \
    --argjson scenarios "$scenarios_json" \
    '{groups:$groups, scenarios:$scenarios}' >"$scope_path"
}

catalog_scope_command_args_json() {
  local groups_csv="$1" scenarios_csv="$2"
  jq -n \
    --arg groups "$groups_csv" \
    --arg scenarios "$scenarios_csv" '
      [
        (if $groups == "" then [] else ["-KG_CATALOG_GROUPS", $groups] end),
        (if $scenarios == "" then [] else ["-KG_CATALOG_SCENARIOS", $scenarios] end)
      ]
      | add
    '
}

catalog_upsert_plist_string() {
  local plist_path="$1" key_path="$2" value="$3"
  if ! plutil -replace "$key_path" -string "$value" "$plist_path" 2>/dev/null; then
    plutil -insert "$key_path" -string "$value" "$plist_path"
  fi
}

catalog_upsert_plist_json() {
  local plist_path="$1" key_path="$2" json_value="$3"
  if ! plutil -replace "$key_path" -json "$json_value" "$plist_path" 2>/dev/null; then
    plutil -insert "$key_path" -json "$json_value" "$plist_path"
  fi
}

catalog_ensure_plist_dict() {
  local plist_path="$1" key_path="$2"
  plutil -extract "$key_path" raw -o - "$plist_path" >/dev/null 2>&1 && return 0
  plutil -insert "$key_path" -json '{}' "$plist_path"
}

catalog_remove_plist_key() {
  local plist_path="$1" key_path="$2"
  plutil -remove "$key_path" "$plist_path" >/dev/null 2>&1 || true
}

# base64(raw DEFLATE) — plaintext base64 of a multi-MB world overflows the
# ~1MB spawn env block and the app silently sees no dataset (see
# ops/lib/fixture_dataset_env.sh).
catalog_dataset_base64() {
  kg_fixture_dataset_deflate_b64 "$1"
}

catalog_uv_bin() {
  if [[ -n "${UV_BIN:-}" ]]; then
    printf '%s\n' "$UV_BIN"
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    printf '%s\n' "$HOME/.local/bin/uv"
  else
    printf '%s\n' "uv"
  fi
}

catalog_validate_dataset_file() {
  local dataset_path="$1"
  [[ -n "$dataset_path" ]] || return 0
  [[ -f "$dataset_path" ]] || return 1
  local uv_bin
  uv_bin="$(catalog_uv_bin)"
  "$uv_bin" run --python 3.13 python "$ROOT/ops/ui_world_manifest.py" validate "$dataset_path" --label "Catalog UI World dataset" >/dev/null
}

catalog_dataset_sha256() {
  shasum -a 256 "$1" | awk '{print $1}'
}

catalog_dataset_id() {
  jq -er '.datasetID | select(type == "string" and length > 0)' "$1"
}

catalog_dataset_fixed_clock() {
  jq -r '.marketingCapture.reviewClock.frozenNow // empty' "$1"
}

catalog_source_commit() {
  local commit
  commit="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" || return 1
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || return 1
  printf '%s\n' "$commit"
}

catalog_validate_appearance_json() {
  local sidecar_path="$1" source_commit="$2" dataset_id="$3" dataset_sha256="$4" fixed_clock="$5"
  local uv_bin validation rc=0
  uv_bin="$(catalog_uv_bin)"
  validation="$(
    "$uv_bin" run --python 3.13 python "$ROOT/ops/catalog_appearance_proof.py" \
      "$sidecar_path" \
      --source-commit "$source_commit" \
      --dataset-id "$dataset_id" \
      --dataset-sha256 "$dataset_sha256" \
      --fixed-clock "$fixed_clock"
  )" || rc=$?
  if [[ -z "$validation" ]]; then
    validation='{"status":"block","issues":[{"code":"appearance.validator","expected":"validator JSON","actual":"empty"}],"proofCount":0}'
  fi
  jq -n \
    --arg path "$sidecar_path" \
    --arg sourceCommit "$source_commit" \
    --arg datasetID "$dataset_id" \
    --arg datasetSHA256 "$dataset_sha256" \
    --arg fixedClock "$fixed_clock" \
    --argjson validatorExit "$rc" \
    --argjson validation "$validation" \
    '$validation + {
      path:$path,
      sourceCommit:$sourceCommit,
      datasetID:$datasetID,
      datasetSHA256:$datasetSHA256,
      fixedClock:$fixedClock,
      validatorExit:$validatorExit
    }'
}

catalog_prepare_scoped_xctestrun() {
  local base_xctestrun="$1" groups_csv="$2" scenarios_csv="$3" dataset_b64="$4" source_commit="$5" dataset_sha256="$6" scoped_xctestrun="$7"
  local args_json
  cp "$base_xctestrun" "$scoped_xctestrun"
  args_json="$(catalog_scope_command_args_json "$groups_csv" "$scenarios_csv")"

  catalog_upsert_plist_json "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.CommandLineArguments' "$args_json"
  catalog_ensure_plist_dict "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables'
  catalog_ensure_plist_dict "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables'
  catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_REVIEW_SOURCE_COMMIT' "$source_commit"
  catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_REVIEW_SOURCE_COMMIT' "$source_commit"
  catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_FIXTURE_DATASET_SHA256' "$dataset_sha256"
  catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_FIXTURE_DATASET_SHA256' "$dataset_sha256"
  if [[ -n "$groups_csv" ]]; then
    catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_CATALOG_GROUPS' "$groups_csv"
    catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_CATALOG_GROUPS' "$groups_csv"
  else
    catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_CATALOG_GROUPS'
    catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_CATALOG_GROUPS'
  fi
  if [[ -n "$scenarios_csv" ]]; then
    catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_CATALOG_SCENARIOS' "$scenarios_csv"
    catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_CATALOG_SCENARIOS' "$scenarios_csv"
  else
    catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_CATALOG_SCENARIOS'
    catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_CATALOG_SCENARIOS'
  fi
  if [[ -n "$dataset_b64" ]]; then
    catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_FIXTURE_DATASET_DEFLATE_B64' "$dataset_b64"
    catalog_upsert_plist_string "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_FIXTURE_DATASET_DEFLATE_B64' "$dataset_b64"
  else
    catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_FIXTURE_DATASET_DEFLATE_B64'
    catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_FIXTURE_DATASET_DEFLATE_B64'
  fi
  # Legacy plaintext key: never co-stage — both keys set is a fail-loud error
  # in the app (ambiguous UI World source).
  catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.EnvironmentVariables.KG_FIXTURE_DATASET_B64'
  catalog_remove_plist_key "$scoped_xctestrun" 'TestConfigurations.0.TestTargets.0.TestingEnvironmentVariables.KG_FIXTURE_DATASET_B64'
}

catalog_run_scoped_xctestrun() {
  local xctestrun_path="$1" destination="$2" log_path="$3" err_path="$4"
  local start_ms end_ms rc
  start_ms="$(catalog_now_ms)"
  if catalog_run_xcodebuild_heartbeat "test-without-building" "$log_path" "$err_path" 1 -- \
    xcodebuild test-without-building \
    -xctestrun "$xctestrun_path" \
    -destination "$destination" \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled NO \
    -only-testing:BooksAndVocabTests/CatalogSnapshotTests; then
    rc=0
  else
    rc=$?
  fi
  end_ms="$(catalog_now_ms)"
  CATALOG_LAST_COMMAND_WALL_MS=$(( end_ms - start_ms ))
  return "$rc"
}

catalog_rebuild_scoped_cache() {
  local destination="$1" derived_data_root="$2" log_path="$3" err_path="$4"
  local start_ms end_ms rc
  rm -rf "$derived_data_root"
  mkdir -p "$derived_data_root"
  # Keyed catalog caches grow unbounded (31G on 2026-06-10). No shared lock
  # here — concurrent runs are protected by the min-age window plus each
  # run's own key being touched. Logs go to stderr; stdout stays pure JSON.
  kg_ios_cache_evict "$(dirname "$derived_data_root")" "$(basename "$derived_data_root")"
  start_ms="$(catalog_now_ms)"
  if catalog_run_xcodebuild_heartbeat "build-for-testing" "$log_path" "$err_path" 0 -- \
    xcodebuild build-for-testing \
    -project "$XCODEPROJ" \
    -scheme "$CATALOG_SCHEME" \
    -destination "$destination" \
    -parallel-testing-enabled NO \
    -test-timeouts-enabled NO \
    -derivedDataPath "$derived_data_root" \
    OTHER_SWIFT_FLAGS='$(inherited) -DKG_RUN_CATALOG_SNAPSHOTS'; then
    rc=0
  else
    rc=$?
  fi
  end_ms="$(catalog_now_ms)"
  CATALOG_LAST_BUILD_WALL_MS=$(( end_ms - start_ms ))
  return "$rc"
}

catalog_build_for_testing_command() {
  local destination="$1" derived_data_root="$2"
  printf 'xcodebuild build-for-testing -project %s -scheme %s -destination %s -parallel-testing-enabled NO -test-timeouts-enabled NO -derivedDataPath %s OTHER_SWIFT_FLAGS=$(inherited) -DKG_RUN_CATALOG_SNAPSHOTS' \
    "$XCODEPROJ" "$CATALOG_SCHEME" "$destination" "$derived_data_root"
}

catalog_test_without_building_command() {
  local xctestrun_path="$1" destination="$2"
  printf 'xcodebuild test-without-building -xctestrun %s -destination %s -parallel-testing-enabled NO -test-timeouts-enabled NO -only-testing:BooksAndVocabTests/CatalogSnapshotTests' \
    "$xctestrun_path" "$destination"
}

catalog_collect_pngs_json() {
  local out_root="$1"
  find "$out_root" -type f -name '*.png' | sort | jq -R . | jq -s --arg root "$out_root" '{
    root:$root,
    pngCount:length,
    paths:.
  }'
}

catalog_render_review_json() {
  local out_root="$1" derived_data_root="${2:-}"
  local renderer="$ROOT/ops/render_catalog_review.py"
  local ui_graph_cli="$ROOT/ops/ui_graph.py"
  local catalog_index="$out_root/catalog_index.json"
  local ui_graph_json="$out_root/ui_graph.json"
  local profile="$ROOT/ops/catalog_review_profile.json"
  local review_html="$out_root/UIreview.html"
  local review_manifest="$out_root/review_manifest.json"
  local review_state="$out_root/review_state.json"
  local render_output=""
  local detail=""
  local graph_json='{"status":"skipped"}'
  local graph_err=""
  local graph_store=""

  if [[ -f "$catalog_index" && -f "$ui_graph_json" ]]; then
    graph_json="$(jq -n --arg path "$ui_graph_json" --arg mode "sidecar" --argjson payload "$(cat "$ui_graph_json")" '{
      status:"ok",
      path:$path,
      mode:$mode,
      nodeCount:($payload.nodeCount // null),
      edgeCount:($payload.edgeCount // null)
    }')"
  elif [[ -f "$catalog_index" && -f "$ui_graph_cli" ]]; then
    if [[ -n "$derived_data_root" && -d "$derived_data_root/Index.noindex/DataStore" ]]; then
      graph_store="$derived_data_root/Index.noindex/DataStore"
      if "$ui_graph_cli" --store-path "$graph_store" --catalog-index "$catalog_index" --json >"$ui_graph_json" 2>"$review_state.ui_graph.stderr"; then
        graph_json="$(jq -n --arg path "$ui_graph_json" --arg mode "store-path" --argjson payload "$(cat "$ui_graph_json")" '{
          status:"ok",
          path:$path,
          mode:$mode,
          nodeCount:($payload.nodeCount // null),
          edgeCount:($payload.edgeCount // null)
        }')"
      else
        graph_err="$(tail -n 1 "$review_state.ui_graph.stderr" 2>/dev/null || true)"
        rm -f "$ui_graph_json"
        graph_json="$(jq -n --arg path "$ui_graph_json" --arg mode "store-path" --arg detail "$graph_err" '{
          status:"warn",
          path:$path,
          mode:$mode,
          error:"ui-graph-render-failed",
          detail:($detail | select(length > 0))
        }')"
      fi
    else
      if "$ui_graph_cli" --build --catalog-index "$catalog_index" --json >"$ui_graph_json" 2>"$review_state.ui_graph.stderr"; then
        graph_json="$(jq -n --arg path "$ui_graph_json" --arg mode "build" --argjson payload "$(cat "$ui_graph_json")" '{
          status:"ok",
          path:$path,
          mode:$mode,
          nodeCount:($payload.nodeCount // null),
          edgeCount:($payload.edgeCount // null)
        }')"
      else
        graph_err="$(tail -n 1 "$review_state.ui_graph.stderr" 2>/dev/null || true)"
        rm -f "$ui_graph_json"
        graph_json="$(jq -n --arg path "$ui_graph_json" --arg mode "build" --arg detail "$graph_err" '{
          status:"warn",
          path:$path,
          mode:$mode,
          error:"ui-graph-render-failed",
          detail:($detail | select(length > 0))
        }')"
      fi
    fi
    rm -f "$review_state.ui_graph.stderr"
  fi

  if [[ ! -x "$renderer" && ! -f "$renderer" ]]; then
    jq -n \
      --arg root "$out_root" \
      --arg reviewHtml "$review_html" \
      --arg reviewManifest "$review_manifest" \
      --arg reviewState "$review_state" \
      --argjson uiGraph "$graph_json" \
      '{
        status:"warn",
        root:$root,
        reviewHtml:$reviewHtml,
        reviewManifest:$reviewManifest,
        reviewState:$reviewState,
        uiGraph:$uiGraph,
        error:"review-renderer-missing"
      }'
    return 0
  fi
  if render_output="$("$renderer" "$out_root" --output-root "$out_root" --profile "$profile" 2>&1)"; then
    jq -n \
      --arg root "$out_root" \
      --arg reviewHtml "$review_html" \
      --arg reviewManifest "$review_manifest" \
      --arg reviewState "$review_state" \
      --argjson uiGraph "$graph_json" \
      --argjson render "${render_output:-null}" \
      '($render // {}) as $render
      | {
          status:(if $uiGraph.status == "warn" then "warn" else "ok" end),
          root:$root,
          reviewHtml:$reviewHtml,
          reviewManifest:$reviewManifest,
          reviewState:$reviewState,
          uiGraph:$uiGraph,
          totalImages:($render.totalImages // null),
          promiseCounts:($render.promiseCounts // {})
        }'
    return 0
  fi
  detail="$(printf '%s' "$render_output" | tail -n 1)"
  jq -n \
    --arg root "$out_root" \
    --arg reviewHtml "$review_html" \
    --arg reviewManifest "$review_manifest" \
    --arg reviewState "$review_state" \
    --argjson uiGraph "$graph_json" \
    --arg detail "$detail" \
    '{
      status:"warn",
      root:$root,
      reviewHtml:$reviewHtml,
      reviewManifest:$reviewManifest,
      reviewState:$reviewState,
      uiGraph:$uiGraph,
      error:"review-render-failed",
      detail:($detail | select(length > 0))
    }'
}

catalog_extract_scenario_count_from_log() {
  local log_path="$1"
  [[ -f "$log_path" ]] || return 1
  sed -n 's/^ - resolved\.scenarioCount: //p' "$log_path" | tail -n 1
}

catalog_extract_timing_ms_from_log() {
  local log_path="$1" metric="$2"
  [[ -f "$log_path" ]] || return 1
  sed -n "s/^ - timing\\.${metric}: //p" "$log_path" | tail -n 1
}

# Device variant count = entries in the Swift test's `devices:` array (dark
# variants are separate entries). Printed by CatalogSnapshotTests as
# `resolved.deviceVariantCount`; absent in legacy logs → caller falls back to 2.
catalog_extract_device_variant_count_from_log() {
  local log_path="$1"
  [[ -f "$log_path" ]] || return 1
  sed -n 's/^ - resolved\.deviceVariantCount: //p' "$log_path" | tail -n 1
}

catalog_inspect_pngs_json() {
  local out_root="$1" expected_scenarios="${2:-}" device_variants="${3:-2}"
  local inspector="$ROOT/ops/catalog_png_inspect.swift"
  local paths=() report_json expected_png_count="" count_matches="false"
  while IFS= read -r path; do
    [[ -n "$path" ]] && paths+=("$path")
  done < <(find "$out_root" -type f -name '*.png' | sort)

  if ((${#paths[@]} == 0)); then
    jq -n \
      --argjson expectedScenarios "${expected_scenarios:-null}" \
      --argjson deviceVariants "${device_variants}" \
      '{
        status:"error",
        expectedScenarioCount:$expectedScenarios,
        expectedPngCount:(if $expectedScenarios == null then null else ($expectedScenarios * $deviceVariants) end),
        actualPngCount:0,
        pngCountMatches:false,
        uniformImageCount:0,
        minPixelWidth:null,
        maxPixelWidth:null,
        minPixelHeight:null,
        maxPixelHeight:null,
        images:[],
        errors:["no-png-artifacts"]
      }'
    return 0
  fi

  report_json="$(swift "$inspector" "${paths[@]}")" || return $?
  if [[ -n "$expected_scenarios" ]]; then
    expected_png_count=$(( expected_scenarios * device_variants ))
    if [[ "$expected_png_count" -eq "${#paths[@]}" ]]; then
      count_matches="true"
    fi
  fi

  jq -n \
    --argjson images "$report_json" \
    --argjson actualPngCount "${#paths[@]}" \
    --argjson expectedScenarios "${expected_scenarios:-null}" \
    --argjson expectedPngCount "${expected_png_count:-null}" \
    --argjson countMatches "$count_matches" '
      {
        status:(
          if ($images | any(.pixelWidth <= 1 or .pixelHeight <= 1 or .isFullyTransparent))
          then "error"
          elif ($expectedPngCount != null and ($countMatches | not))
          then "error"
          elif ($images | any(.isUniform))
          then "warn"
          else "ok"
          end
        ),
        expectedScenarioCount:$expectedScenarios,
        expectedPngCount:$expectedPngCount,
        actualPngCount:$actualPngCount,
        pngCountMatches:(
          if $expectedPngCount == null then null else $countMatches end
        ),
        uniformImageCount:($images | map(select(.isUniform)) | length),
        transparentImageCount:($images | map(select(.isFullyTransparent)) | length),
        minPixelWidth:($images | map(.pixelWidth) | min),
        maxPixelWidth:($images | map(.pixelWidth) | max),
        minPixelHeight:($images | map(.pixelHeight) | min),
        maxPixelHeight:($images | map(.pixelHeight) | max),
        images:$images,
        transparentImages:($images | map(select(.isFullyTransparent) | .path)),
        errors:(
          []
          + (if ($images | any(.pixelWidth <= 1 or .pixelHeight <= 1)) then ["degenerate-dimensions"] else [] end)
          + (if ($images | any(.isFullyTransparent)) then ["fully-transparent-image-detected"] else [] end)
          + (if $expectedPngCount != null and ($countMatches | not) then ["png-count-mismatch"] else [] end)
        ),
        warnings:(
          []
          + (if ($images | any(.isUniform)) then ["uniform-image-detected"] else [] end)
        )
      }
    '
}

catalog_resolve_destination_device_udid() {
  local destination="$1"
  local devices_json device_id device_name
  devices_json="$(read_simctl_devices_json 2>/dev/null || true)"
  [[ -n "$devices_json" ]] || return 1

  device_id="$(sed -n 's/.*id=\([^,]*\).*/\1/p' <<<"$destination" | head -1)"
  if [[ -n "$device_id" ]]; then
    jq -r --arg id "$device_id" '[.devices // {} | to_entries[]?.value[]? | select(.udid == $id)][0].udid // empty' <<<"$devices_json"
    return 0
  fi

  device_name="$(sed -n 's/.*name=\(.*\)$/\1/p' <<<"$destination" | head -1)"
  if [[ -z "$device_name" ]]; then
    return 1
  fi
  jq -r --arg name "$device_name" '
    [
      .devices // {} | to_entries[]?.value[]? | select(.name == $name)
    ]
    | (map(select(.state == "Booted"))[0].udid // .[0].udid // empty)
  ' <<<"$devices_json"
}

cmd_catalog_snapshots_json() {
  local out_root="$1" destination="$2" groups_csv="${3:-}" scenarios_csv="${4:-}" dataset_path="${5:-}" reuse_build_only="${6:-0}" persist_workspace_artifact="${7:-0}"
  local generated_at mode container_data snapshot_source xcode_log xcode_err rc test_cmd
  local sim_payload sim_rc=0 copy_rc=0 pngs_json payload resolved_device container_source
  local validation_json expected_scenario_count="" device_variant_count="" command_wall_ms=0 test_body_ms=0 playbook_build_ms=0 snapshot_run_ms=0 startup_overhead_ms=0
  local wrapper_start_ms wrapper_wall_ms=0 sim_status_ms=0 container_lookup_ms=0 copy_ms=0 artifact_index_ms=0 validation_ms=0
  local phase_start_ms phase_end_ms
  local fixture_root="" derived_data_root="" base_xctestrun="" run_xctestrun=""
  local build_cmd="" scope_test_cmd="" use_cached_xctestrun=0 scope_requested=0
  local cache_key="" cache_status="not-applicable"
  local dataset_status="not-requested" dataset_rc=0 dataset_simulator_path="" dataset_b64=""
  local dataset_id="" dataset_sha256="" dataset_fixed_clock="" source_commit=""
  local container_png_count=0 salvaged="false"
  local review_json='{"status":"skipped"}'
  local workspace_artifact_json='{"status":"skipped"}'
  local appearance_json='{"status":"block","issues":[{"code":"appearance.not-validated","expected":"validated sidecar","actual":"not-run"}],"proofCount":0}'
  local run_receipt_json='{"status":"block"}'

  wrapper_start_ms="$(catalog_now_ms)"
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  catalog_prepare_output_root "$out_root"
  resolved_device="$(catalog_resolve_destination_device_udid "$destination")"
  if [[ -n "$resolved_device" ]]; then
    catalog_write_scope_file "$resolved_device" "$groups_csv" "$scenarios_csv"
  fi

  mode="live"
  xcode_log="$(mktemp)"
  xcode_err="$(mktemp)"
  build_cmd="$(catalog_build_for_testing_command "$destination" "<derived-data-root>")"
  scope_test_cmd="xcodebuild test-without-building -xctestrun <cached-xctestrun> -destination $destination -parallel-testing-enabled NO -test-timeouts-enabled NO -only-testing:BooksAndVocabTests/CatalogSnapshotTests"
  test_cmd="xcodebuild test -project $XCODEPROJ -scheme $CATALOG_SCHEME -destination $destination -parallel-testing-enabled NO -test-timeouts-enabled NO -only-testing:BooksAndVocabTests/CatalogSnapshotTests OTHER_SWIFT_FLAGS=\$(inherited) -DKG_RUN_CATALOG_SNAPSHOTS"
  if [[ -n "$groups_csv" || -n "$scenarios_csv" ]]; then
    scope_requested=1
  fi
  if [[ "$scope_requested" -eq 1 || "$reuse_build_only" -eq 1 || -n "$dataset_path" ]]; then
    derived_data_root="$(catalog_resolve_derived_data_root "$destination")"
    cache_key="$(basename "$derived_data_root")"
    use_cached_xctestrun=1
    build_cmd="$(catalog_build_for_testing_command "$destination" "$derived_data_root")"
    test_cmd="$build_cmd && $scope_test_cmd"
  fi

  if [[ -n "$dataset_path" ]]; then
    if ! catalog_validate_dataset_file "$dataset_path"; then
      dataset_rc=64
      dataset_status="invalid"
    elif ! source_commit="$(catalog_source_commit)"; then
      dataset_rc=65
      dataset_status="source-commit-failed"
    elif ! dataset_id="$(catalog_dataset_id "$dataset_path")"; then
      dataset_rc=66
      dataset_status="dataset-id-failed"
    elif ! dataset_sha256="$(catalog_dataset_sha256 "$dataset_path")"; then
      dataset_rc=67
      dataset_status="dataset-sha256-failed"
    elif ! dataset_b64="$(catalog_dataset_base64 "$dataset_path")"; then
      dataset_rc=89
      dataset_status="encode-failed"
    else
      dataset_fixed_clock="$(catalog_dataset_fixed_clock "$dataset_path")"
      if [[ "${KG_IOS_OPS_FIXTURE:-}" == "1" && -z "$dataset_fixed_clock" ]]; then
        dataset_fixed_clock="2026-07-13T08:00:00Z"
      fi
      dataset_status="validated"
    fi
  fi

  if [[ "${KG_IOS_OPS_FIXTURE:-}" == "1" ]]; then
    mode="fixture"
    derived_data_root=""
    cache_key=""
    cache_status="not-applicable"
    fixture_root="$(mktemp -d)"
    catalog_fixture_seed_snapshots "$fixture_root" "$source_commit" "$dataset_id" "$dataset_sha256" "$dataset_fixed_clock"
    container_data="$fixture_root"
    snapshot_source="$fixture_root/tmp/kg-catalog-snapshots"
    printf 'fixture xcodebuild test\n' >"$xcode_log"
    : >"$xcode_err"
    # Test seam: inject a failure exit code to exercise the cache-miss (87) and
    # salvage-on-failure JSON paths without a real simulator/xcodebuild run.
    if [[ "$dataset_rc" -ne 0 ]]; then
      rc="$dataset_rc"
    else
      rc="${KG_IOS_OPS_CATALOG_FIXTURE_EXIT:-0}"
    fi
    if [[ "$rc" == "87" ]]; then
      cache_status="miss"
    fi
  else
    if [[ "$dataset_rc" -ne 0 ]]; then
      rc="$dataset_rc"
    elif [[ "$use_cached_xctestrun" -eq 1 ]]; then
      base_xctestrun="$(catalog_find_xctestrun "$derived_data_root")"
      if catalog_cached_products_ready "$derived_data_root" "$base_xctestrun"; then
        cache_status="hit"
        # LRU liveness：hit 讀者必須 touch 自己的 key，否則並行 rebuild 的
        # eviction 可能把正在讀的產物抽走（無共用鎖，靠 mtime+min-age 保護）。
        touch "$derived_data_root" 2>/dev/null || true
        : >"$xcode_log"
        : >"$xcode_err"
        if [[ "$scope_requested" -eq 1 || -n "$dataset_b64" ]]; then
          run_xctestrun="$(dirname "$base_xctestrun")/$(basename "${base_xctestrun%.xctestrun}").scoped.xctestrun"
          catalog_prepare_scoped_xctestrun "$base_xctestrun" "$groups_csv" "$scenarios_csv" "$dataset_b64" "$source_commit" "$dataset_sha256" "$run_xctestrun"
        else
          run_xctestrun="$base_xctestrun"
        fi
        test_cmd="$(catalog_test_without_building_command "$run_xctestrun" "$destination")"
        if catalog_run_scoped_xctestrun "$run_xctestrun" "$destination" "$xcode_log" "$xcode_err"; then
          rc=0
        else
          rc=$?
          cache_status="stale"
        fi
      else
        cache_status="miss"
      fi

      if [[ "$cache_status" != "hit" || "${rc:-1}" -ne 0 ]]; then
        if [[ "$reuse_build_only" -eq 1 ]]; then
          rc=87
        else
          if catalog_rebuild_scoped_cache "$destination" "$derived_data_root" "$xcode_log" "$xcode_err"; then
            base_xctestrun="$(catalog_find_xctestrun "$derived_data_root")"
            if [[ -z "$base_xctestrun" ]]; then
              rc=86
            else
              if [[ "$scope_requested" -eq 1 || -n "$dataset_b64" ]]; then
                run_xctestrun="$(dirname "$base_xctestrun")/$(basename "${base_xctestrun%.xctestrun}").scoped.xctestrun"
                catalog_prepare_scoped_xctestrun "$base_xctestrun" "$groups_csv" "$scenarios_csv" "$dataset_b64" "$source_commit" "$dataset_sha256" "$run_xctestrun"
              else
                run_xctestrun="$base_xctestrun"
              fi
              test_cmd="$build_cmd && $(catalog_test_without_building_command "$run_xctestrun" "$destination")"
              if catalog_run_scoped_xctestrun "$run_xctestrun" "$destination" "$xcode_log" "$xcode_err"; then
                rc=0
                if [[ "$cache_status" == "hit" || "$cache_status" == "stale" ]]; then
                  cache_status="rebuilt-after-failure"
                else
                  cache_status="rebuilt"
                fi
              else
                rc=$?
              fi
            fi
          else
            rc=$?
          fi
        fi
      fi
    else
      local full_test_start_ms full_test_end_ms
      full_test_start_ms="$(catalog_now_ms)"
      if catalog_run_xcodebuild_heartbeat "full-test" "$xcode_log" "$xcode_err" 0 -- \
        xcodebuild test \
        -project "$XCODEPROJ" \
        -scheme "$CATALOG_SCHEME" \
        -destination "$destination" \
        -parallel-testing-enabled NO \
        -test-timeouts-enabled NO \
        -only-testing:BooksAndVocabTests/CatalogSnapshotTests \
        OTHER_SWIFT_FLAGS='$(inherited) -DKG_RUN_CATALOG_SNAPSHOTS'; then
        rc=0
      else
        rc=$?
      fi
      full_test_end_ms="$(catalog_now_ms)"
      CATALOG_LAST_COMMAND_WALL_MS=$(( full_test_end_ms - full_test_start_ms ))
    fi
  fi

  phase_start_ms="$(catalog_now_ms)"
  catalog_trace_phase "simulator_status" "start" "destination=\"$destination\""
  sim_payload="$(cmd_simulator_status_json)" || sim_rc=$?
  phase_end_ms="$(catalog_now_ms)"
  sim_status_ms=$(( phase_end_ms - phase_start_ms ))
  catalog_trace_phase "simulator_status" "done" "wallMs=$sim_status_ms exitCode=$sim_rc"

  phase_start_ms="$(catalog_now_ms)"
  catalog_trace_phase "container_lookup" "start" "resolvedDevice=${resolved_device:-<empty>}"
  if [[ -n "$resolved_device" ]]; then
    container_source="$(capture_source_text app_container read_app_container_path "$resolved_device" "$BUNDLE_ID" data)"
    container_data="$(jq -r 'if .status == "ok" then (.output | sub("\n+$"; "")) else empty end' <<<"$container_source")"
  else
    container_source='null'
    container_data=""
  fi
  if [[ -z "$container_data" ]]; then
    container_data="$(jq -r '.app.container.data // empty' <<<"$sim_payload")"
  fi
  if [[ -z "${snapshot_source:-}" ]]; then
    snapshot_source="$container_data/tmp/kg-catalog-snapshots"
  fi
  if [[ "$rc" -eq 0 ]] && [[ -z "$container_data" ]]; then
    local logged_snapshot_root
    logged_snapshot_root="$(catalog_snapshot_root_from_log "$xcode_log")"
    if [[ -n "$logged_snapshot_root" ]]; then
      snapshot_source="$logged_snapshot_root"
      if [[ "$snapshot_source" == */tmp/kg-catalog-snapshots ]]; then
        container_data="${snapshot_source%/tmp/kg-catalog-snapshots}"
      fi
    fi
  elif [[ "$rc" -eq 0 ]] && [[ ! -d "$snapshot_source" ]]; then
    snapshot_source="$(catalog_snapshot_root_from_log "$xcode_log")"
    if [[ "$snapshot_source" == */tmp/kg-catalog-snapshots ]]; then
      container_data="${snapshot_source%/tmp/kg-catalog-snapshots}"
    fi
  fi
  phase_end_ms="$(catalog_now_ms)"
  container_lookup_ms=$(( phase_end_ms - phase_start_ms ))
  catalog_trace_phase "container_lookup" "done" "wallMs=$container_lookup_ms container=${container_data:-<empty>} source=${snapshot_source:-<empty>}"

  # Count PNGs already produced inside the simulator container BEFORE copy, so a
  # failed run can still distinguish "nothing was generated" from "generated but
  # not copied back". This is the salvage source of truth.
  if [[ -d "$snapshot_source" ]]; then
    container_png_count="$(find "$snapshot_source" -type f -name '*.png' 2>/dev/null | wc -l | tr -d ' ')"
  else
    container_png_count=0
  fi

  phase_start_ms="$(catalog_now_ms)"
  catalog_trace_phase "copy" "start" "source=${snapshot_source:-<empty>} outRoot=$out_root containerPngCount=$container_png_count"
  # Salvage even on failure: if the container has snapshots, copy them back so a
  # crash in a later phase does not make already-rendered PNGs invisible.
  if [[ -d "$snapshot_source" ]]; then
    if mkdir -p "$out_root" && cp -R "$snapshot_source/." "$out_root/"; then
      copy_rc=0
    else
      copy_rc=$?
    fi
  else
    copy_rc=1
  fi
  phase_end_ms="$(catalog_now_ms)"
  copy_ms=$(( phase_end_ms - phase_start_ms ))
  if [[ "$rc" -ne 0 && "$rc" != "87" && "$copy_rc" -eq 0 && "$container_png_count" -gt 0 ]]; then
    salvaged="true"
    catalog_phase_emit "salvage" "recovered" "test failed (exitCode=$rc) but $container_png_count container PNG(s) copied to $out_root"
  fi
  catalog_trace_phase "copy" "done" "wallMs=$copy_ms exitCode=$copy_rc salvaged=$salvaged"

  phase_start_ms="$(catalog_now_ms)"
  catalog_trace_phase "artifact_index" "start" "outRoot=$out_root"
  pngs_json="$(catalog_collect_pngs_json "$out_root")"
  phase_end_ms="$(catalog_now_ms)"
  artifact_index_ms=$(( phase_end_ms - phase_start_ms ))
  catalog_trace_phase "artifact_index" "done" "wallMs=$artifact_index_ms pngCount=$(jq -r '.pngCount // 0' <<<"$pngs_json")"

  expected_scenario_count="$(catalog_extract_scenario_count_from_log "$xcode_log" || true)"
  command_wall_ms="${CATALOG_LAST_COMMAND_WALL_MS:-0}"
  playbook_build_ms="$(catalog_extract_timing_ms_from_log "$xcode_log" "playbookBuildMs" || true)"
  snapshot_run_ms="$(catalog_extract_timing_ms_from_log "$xcode_log" "snapshotRunMs" || true)"
  test_body_ms="$(catalog_extract_timing_ms_from_log "$xcode_log" "testBodyMs" || true)"
  command_wall_ms="${command_wall_ms:-0}"
  playbook_build_ms="${playbook_build_ms:-0}"
  snapshot_run_ms="${snapshot_run_ms:-0}"
  test_body_ms="${test_body_ms:-0}"
  if [[ "$command_wall_ms" =~ ^[0-9]+$ && "$test_body_ms" =~ ^[0-9]+$ ]] && (( command_wall_ms >= test_body_ms )); then
    startup_overhead_ms=$(( command_wall_ms - test_body_ms ))
  else
    startup_overhead_ms=0
  fi

  device_variant_count="$(catalog_extract_device_variant_count_from_log "$xcode_log" || true)"
  [[ "$device_variant_count" =~ ^[0-9]+$ ]] || device_variant_count=2

  phase_start_ms="$(catalog_now_ms)"
  catalog_trace_phase "validation" "start" "expectedScenarios=${expected_scenario_count:-<empty>} deviceVariants=$device_variant_count"
  validation_json="$(catalog_inspect_pngs_json "$out_root" "$expected_scenario_count" "$device_variant_count")"
  phase_end_ms="$(catalog_now_ms)"
  validation_ms=$(( phase_end_ms - phase_start_ms ))
  catalog_trace_phase "validation" "done" "wallMs=$validation_ms status=$(jq -r '.status' <<<"$validation_json")"

  appearance_json="$(catalog_validate_appearance_json \
    "$out_root/catalog_appearance.json" \
    "$source_commit" \
    "$dataset_id" \
    "$dataset_sha256" \
    "$dataset_fixed_clock")"
  catalog_trace_phase "appearance" "done" "status=$(jq -r '.status' <<<"$appearance_json") proofCount=$(jq -r '.proofCount' <<<"$appearance_json")"

  if [[ "$copy_rc" -eq 0 && "$(jq -r '.pngCount // 0' <<<"$pngs_json")" -gt 0 ]]; then
    phase_start_ms="$(catalog_now_ms)"
    catalog_trace_phase "review" "start" "outRoot=$out_root"
    review_json="$(catalog_render_review_json "$out_root" "$derived_data_root")"
    phase_end_ms="$(catalog_now_ms)"
    catalog_trace_phase "review" "done" "wallMs=$(( phase_end_ms - phase_start_ms )) status=$(jq -r '.status' <<<"$review_json")"
  fi

  run_receipt_json="$(catalog_write_run_receipt_json \
    "$out_root" \
    "$source_commit" \
    "$dataset_id" \
    "$dataset_sha256" \
    "$dataset_fixed_clock" \
    "$rc" \
    "$copy_rc" \
    "$(jq -r '.status' <<<"$validation_json")" \
    "$(jq -r '.status' <<<"$review_json")" \
    "$(jq -r '.status' <<<"$appearance_json")")"

  if [[ "$persist_workspace_artifact" -eq 1 && "$(jq -r '.status' <<<"$run_receipt_json")" == "pass" && "$(jq -r '.pngCount // 0' <<<"$pngs_json")" -gt 0 ]]; then
    if [[ "$mode" != "fixture" || -n "${KG_IOS_OPS_CATALOG_PERSIST_ROOT:-}" ]]; then
    phase_start_ms="$(catalog_now_ms)"
    catalog_trace_phase "persist" "start" "source=$out_root"
    workspace_artifact_json="$(catalog_persist_workspace_artifact_json "$out_root" "$generated_at")"
    phase_end_ms="$(catalog_now_ms)"
    catalog_trace_phase "persist" "done" "wallMs=$(( phase_end_ms - phase_start_ms )) status=$(jq -r '.status' <<<"$workspace_artifact_json") root=$(jq -r '.artifactRoot // .root' <<<"$workspace_artifact_json")"
    fi
  fi

  wrapper_wall_ms=$(( $(catalog_now_ms) - wrapper_start_ms ))
  payload="$(jq -n \
    --arg schema "kg.ios.catalog.v1" \
    --arg generated_at "$generated_at" \
    --arg destination "$destination" \
    --arg mode "$mode" \
    --arg groups "$groups_csv" \
    --arg scenarios "$scenarios_csv" \
    --arg command "$test_cmd" \
    --arg log "$xcode_log" \
    --arg errorLog "$xcode_err" \
    --arg container "$container_data" \
    --arg resolvedDevice "$resolved_device" \
    --arg sourcePath "$snapshot_source" \
    --arg cacheKey "$cache_key" \
    --arg cacheRoot "$derived_data_root" \
    --arg cacheStatus "$cache_status" \
    --arg datasetRequestedPath "$dataset_path" \
    --arg datasetSimulatorPath "$dataset_simulator_path" \
    --arg datasetStatus "$dataset_status" \
    --arg datasetID "$dataset_id" \
    --arg datasetSHA256 "$dataset_sha256" \
    --arg datasetFixedClock "$dataset_fixed_clock" \
    --arg sourceCommit "$source_commit" \
    --argjson containerPngCount "$container_png_count" \
    --argjson salvaged "$salvaged" \
    --argjson reuseBuild "$reuse_build_only" \
    --argjson commandWallMs "$command_wall_ms" \
    --argjson playbookBuildMs "$playbook_build_ms" \
    --argjson snapshotRunMs "$snapshot_run_ms" \
    --argjson testBodyMs "$test_body_ms" \
    --argjson startupOverheadMs "$startup_overhead_ms" \
    --argjson wrapperWallMs "$wrapper_wall_ms" \
    --argjson simulatorStatusMs "$sim_status_ms" \
    --argjson containerLookupMs "$container_lookup_ms" \
    --argjson copyMs "$copy_ms" \
    --argjson artifactIndexMs "$artifact_index_ms" \
    --argjson validationMs "$validation_ms" \
    --argjson testExit "$rc" \
    --argjson datasetExit "$dataset_rc" \
    --argjson copyExit "$copy_rc" \
    --argjson artifacts "$pngs_json" \
    --argjson validation "$validation_json" \
    --argjson appearanceProof "$appearance_json" \
    --argjson runReceipt "$run_receipt_json" \
    --argjson review "$review_json" \
    --argjson workspaceArtifact "$workspace_artifact_json" \
    --argjson simulator "$sim_payload" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      action:"snapshots",
      status:(
        if $testExit == 87 then "cache-miss"
        elif $testExit != 0 then "error"
        elif $datasetExit != 0 then "error"
        elif $copyExit != 0 then "error"
        elif ($artifacts.pngCount // 0) == 0 then "error"
        elif $validation.status == "error" then "error"
        elif $appearanceProof.status != "pass" then "error"
        elif $workspaceArtifact.status == "error" then "error"
        elif $validation.status == "warn" or $review.status == "warn" then "warn"
        else "ok"
        end
      ),
      mode:$mode,
      destination:$destination,
      options:{
        reuseBuild:($reuseBuild == 1)
      },
      dataset:{
        requestedPath:(if $datasetRequestedPath == "" then null else $datasetRequestedPath end),
        simulatorPath:(if $datasetSimulatorPath == "" then null else $datasetSimulatorPath end),
        status:$datasetStatus,
        id:(if $datasetID == "" then null else $datasetID end),
        sha256:(if $datasetSHA256 == "" then null else $datasetSHA256 end),
        fixedClock:(if $datasetFixedClock == "" then null else $datasetFixedClock end),
        sourceCommit:(if $sourceCommit == "" then null else $sourceCommit end)
      },
      scope:{
        groups:(if $groups == "" then [] else ($groups | split(",")) end),
        scenarios:(if $scenarios == "" then [] else ($scenarios | split(",")) end)
      },
      artifacts:($artifacts + {containerPngCount:$containerPngCount}),
      timings:{
        wrapperWallMs:$wrapperWallMs,
        commandWallMs:$commandWallMs,
        playbookBuildMs:$playbookBuildMs,
        snapshotRunMs:$snapshotRunMs,
        testBodyMs:$testBodyMs,
        startupOverheadMs:$startupOverheadMs,
        simulatorStatusMs:$simulatorStatusMs,
        containerLookupMs:$containerLookupMs,
        copyMs:$copyMs,
        artifactIndexMs:$artifactIndexMs,
        validationMs:$validationMs
      },
      validation:$validation,
      appearanceProof:$appearanceProof,
      runReceipt:$runReceipt,
      review:$review,
      workspaceArtifact:$workspaceArtifact,
      cache:{
        key:(if $cacheKey == "" then null else $cacheKey end),
        root:(if $cacheRoot == "" then null else $cacheRoot end),
        status:$cacheStatus
      },
      test:{
        command:$command,
        exitCode:$testExit,
        log:$log,
        errorLog:$errorLog
      },
      copy:{
        resolvedDeviceUDID:(if $resolvedDevice == "" then null else $resolvedDevice end),
        containerDataPath:$container,
        sourcePath:$sourcePath,
        exitCode:$copyExit,
        salvaged:$salvaged
      },
      simulator:$simulator,
      flags:{
        compileTimeFlag:"KG_RUN_CATALOG_SNAPSHOTS"
      },
      errors:(
        (if $datasetExit != 0 then [{key:"catalog-dataset",status:"error",exitCode:$datasetExit,error:"dataset-injection-failed"}] else [] end)
        +
        (if $testExit != 0 and $testExit != 87 then [{key:"catalog-test",status:"error",exitCode:$testExit,error:"xcodebuild-test-failed"}] else [] end)
        +
        (if $testExit == 87 then [{key:"catalog-cache",status:"cache-miss",exitCode:$testExit,error:"reuse-build-cache-miss",hint:"run `catalog prepare` first or drop --reuse-build"}] else [] end)
        +
        (if $testExit == 0 and $container == "" then [{key:"catalog-container",status:"error",exitCode:null,error:"app-container-required"}] else [] end)
        +
        (if $copyExit != 0 and $containerPngCount > 0 then [{key:"catalog-copy",status:"error",exitCode:$copyExit,error:"snapshot-copy-failed"}] else [] end)
        +
        (if $salvaged then [{key:"catalog-salvage",status:"info",exitCode:null,error:"snapshots-salvaged-after-failure",pngCount:($artifacts.pngCount // 0),containerPngCount:$containerPngCount}] else [] end)
        +
        (if $testExit == 0 and $copyExit == 0 and ($artifacts.pngCount // 0) == 0 then [{key:"catalog-artifacts",status:"error",exitCode:null,error:"no-png-artifacts"}] else [] end)
        +
        (if $workspaceArtifact.status == "error" then [{key:"catalog-workspace-artifact",status:"error",exitCode:null,error:($workspaceArtifact.error // "workspace-artifact-persist-failed")}] else [] end)
        +
        (if $appearanceProof.status != "pass" then ($appearanceProof.issues | map({key:"catalog-appearance-proof",status:"error",exitCode:null,error:.code,expected:.expected,actual:.actual})) else [] end)
        +
        (if $validation.status == "error" then ($validation.errors | map({key:"catalog-validation",status:"error",exitCode:null,error:.})) else [] end)
      ),
      warnings:(
        (if $validation.status == "warn" then ($validation.warnings | map({key:"catalog-validation",status:"warn",exitCode:null,warning:.})) else [] end)
        +
        (if $review.status == "warn" then [{key:"catalog-review",status:"warn",exitCode:null,warning:($review.error // "review-sidecar-warning"),detail:($review.detail // null)}] else [] end)
      )
    }')"
  printf '%s\n' "$payload"
  local final_status
  final_status="$(jq -r '.status' <<<"$payload")"
  if [[ "$final_status" == "cache-miss" ]]; then
    catalog_phase_emit "cache" "miss" "reuse-build requested but cache is stale/absent — run \`catalog prepare\` first or drop --reuse-build"
  fi
  if [[ "$final_status" != "ok" && "$final_status" != "warn" ]]; then
    return 1
  fi
}

cmd_catalog_snapshots() {
  local json=0
  local out_root destination
  local groups=()
  local scenarios=()
  local dataset_name=""
  local dataset_path=""
  local reuse_build_only=0
  local explicit_out_root=0
  out_root="$(catalog_default_root)"
  destination='platform=iOS Simulator,name=iPhone 17 Pro Max'

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --out-root) out_root="${2:?--out-root needs value}"; explicit_out_root=1; shift 2 ;;
      --destination) destination="${2:?--destination needs value}"; shift 2 ;;
      --group) groups+=("${2:?--group needs value}"); shift 2 ;;
      --scenario) scenarios+=("${2:?--scenario needs value}"); shift 2 ;;
      --dataset) dataset_name="${2:?--dataset needs value}"; shift 2 ;;
      --dataset-file) dataset_path="${2:?--dataset-file needs value}"; shift 2 ;;
      --reuse-build) reuse_build_only=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh catalog snapshots [--out-root <dir>] [--destination <xcodebuild-destination>] [--group <category>]... [--scenario <category/title>]... [--dataset <name> | --dataset-file <path>] [--reuse-build] [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown catalog snapshots option: $1" >&2
        return 1
        ;;
    esac
  done

  local payload rc=0
  local groups_csv=""
  local scenarios_csv=""
  if ((${#groups[@]})); then
    groups_csv="$(IFS=,; printf '%s' "${groups[*]}")"
  fi
  if ((${#scenarios[@]})); then
    scenarios_csv="$(IFS=,; printf '%s' "${scenarios[*]}")"
  fi
  if [[ -n "$dataset_name" && -n "$dataset_path" ]]; then
    echo "✗ choose either --dataset or --dataset-file" >&2
    return 64
  fi
  if [[ -n "$dataset_name" ]]; then
    dataset_path="$(catalog_named_dataset_path "$dataset_name")"
  fi
  if [[ -z "$dataset_path" ]]; then
    echo "✗ catalog snapshots requires --dataset <name> or --dataset-file <path> (UI World SoT)" >&2
    return 64
  fi
  if [[ -n "$dataset_path" && ! -f "$dataset_path" ]]; then
    echo "✗ dataset file not found: $dataset_path" >&2
    return 64
  fi

  local persist_workspace_artifact=0
  if [[ "$explicit_out_root" -eq 0 && -z "$groups_csv" && -z "$scenarios_csv" ]]; then
    persist_workspace_artifact=1
  fi

  payload="$(cmd_catalog_snapshots_json "$out_root" "$destination" "$groups_csv" "$scenarios_csv" "$dataset_path" "$reuse_build_only" "$persist_workspace_artifact")" || rc=$?
  if (( json )); then
    printf '%s\n' "$payload"
    return "$rc"
  fi

  jq -r '
    "[ios][catalog] schema=\(.schema) action=\(.action) status=\(.status) mode=\(.mode) pngCount=\(.artifacts.pngCount) root=\(.artifacts.root)",
    "[ios][catalog] scope groups=\(.scope.groups | join(", ")) scenarios=\(.scope.scenarios | join(", "))",
    "[ios][catalog] dataset status=\(.dataset.status) requested=\(.dataset.requestedPath // "") simulator=\(.dataset.simulatorPath // "")",
    "[ios][catalog] cache status=\(.cache.status) key=\(.cache.key // "") root=\(.cache.root // "")",
    "[ios][catalog] timings wrapperWallMs=\(.timings.wrapperWallMs) commandWallMs=\(.timings.commandWallMs) startupOverheadMs=\(.timings.startupOverheadMs) testBodyMs=\(.timings.testBodyMs) playbookBuildMs=\(.timings.playbookBuildMs) snapshotRunMs=\(.timings.snapshotRunMs) simulatorStatusMs=\(.timings.simulatorStatusMs) containerLookupMs=\(.timings.containerLookupMs) copyMs=\(.timings.copyMs) artifactIndexMs=\(.timings.artifactIndexMs) validationMs=\(.timings.validationMs)",
    "[ios][catalog] validation status=\(.validation.status) expectedScenarios=\(.validation.expectedScenarioCount // "") expectedPng=\(.validation.expectedPngCount // "") actualPng=\(.validation.actualPngCount) uniformImages=\(.validation.uniformImageCount) transparentImages=\(.validation.transparentImageCount // 0) width=\(.validation.minPixelWidth // "")-\(.validation.maxPixelWidth // "") height=\(.validation.minPixelHeight // "")-\(.validation.maxPixelHeight // "")",
    "[ios][catalog] appearance status=\(.appearanceProof.status) proofCount=\(.appearanceProof.proofCount) path=\(.appearanceProof.path // "")",
    "[ios][catalog] review status=\(.review.status) html=\(.review.reviewHtml // "") manifest=\(.review.reviewManifest // "")",
    "[ios][catalog] workspaceArtifact status=\(.workspaceArtifact.status) root=\(.workspaceArtifact.artifactRoot // "")",
    "[ios][catalog] test exitCode=\(.test.exitCode) command=\"\(.test.command // "")\"",
    "[ios][catalog] copy exitCode=\(.copy.exitCode) source=\(.copy.sourcePath // "") container=\(.copy.containerDataPath // "")",
    (.warnings[]? | "[ios][catalog] warn key=\(.key) status=\(.status) exitCode=\(.exitCode // "") warning=\(.warning // "") detail=\(.detail // "")"),
    (.errors[]? | "[ios][catalog] \(if .status == "info" then "note" else "error" end) key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
  ' <<<"$payload"
  return "$rc"
}

cmd_catalog_prepare_json() {
  local destination="$1"
  local generated_at derived_data_root cache_key base_xctestrun build_cmd xcode_log xcode_err payload
  local rc=0 cache_status="miss" products_ready=false build_wall_ms=0

  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  derived_data_root="$(catalog_resolve_derived_data_root "$destination")"
  cache_key="$(basename "$derived_data_root")"
  build_cmd="$(catalog_build_for_testing_command "$destination" "$derived_data_root")"
  xcode_log="$(mktemp)"
  xcode_err="$(mktemp)"
  base_xctestrun="$(catalog_find_xctestrun "$derived_data_root" || true)"

  if catalog_cached_products_ready "$derived_data_root" "$base_xctestrun"; then
    cache_status="hit"
    # LRU liveness：同上，hit 讀者 touch 續命。
    touch "$derived_data_root" 2>/dev/null || true
    : >"$xcode_log"
    : >"$xcode_err"
  elif [[ "${KG_IOS_OPS_FIXTURE:-}" == "1" ]]; then
    rm -rf "$derived_data_root"
    mkdir -p "$derived_data_root"
    catalog_fixture_seed_cache "$derived_data_root"
    cache_status="prepared"
    printf 'fixture xcodebuild build-for-testing\n' >"$xcode_log"
    : >"$xcode_err"
  else
    if catalog_rebuild_scoped_cache "$destination" "$derived_data_root" "$xcode_log" "$xcode_err"; then
      cache_status="prepared"
    else
      rc=$?
      cache_status="error"
    fi
    build_wall_ms="${CATALOG_LAST_BUILD_WALL_MS:-0}"
  fi

  base_xctestrun="$(catalog_find_xctestrun "$derived_data_root" || true)"
  if catalog_cached_products_ready "$derived_data_root" "$base_xctestrun"; then
    products_ready=true
  fi

  payload="$(jq -n \
    --arg schema "kg.ios.catalog.prepare.v1" \
    --arg generated_at "$generated_at" \
    --arg destination "$destination" \
    --arg cacheRoot "$derived_data_root" \
    --arg cacheKey "$cache_key" \
    --arg cacheStatus "$cache_status" \
    --arg xctestrunPath "$base_xctestrun" \
    --arg command "$build_cmd" \
    --arg log "$xcode_log" \
    --arg errorLog "$xcode_err" \
    --argjson buildWallMs "$build_wall_ms" \
    --argjson buildExit "$rc" \
    --argjson productsReady "$products_ready" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      action:"prepare",
      status:(if $buildExit == 0 and $productsReady then "ok" else "error" end),
      destination:$destination,
      cache:{
        key:$cacheKey,
        root:$cacheRoot,
        status:$cacheStatus,
        productsReady:$productsReady,
        xctestrunPath:(if $xctestrunPath == "" then null else $xctestrunPath end)
      },
      build:{
        command:$command,
        exitCode:$buildExit,
        wallMs:$buildWallMs,
        log:$log,
        errorLog:$errorLog
      },
      flags:{
        compileTimeFlag:"KG_RUN_CATALOG_SNAPSHOTS"
      },
      errors:(
        if $buildExit != 0 then [{key:"catalog-prepare",status:"error",exitCode:$buildExit,error:"build-for-testing-failed"}]
        elif ($productsReady | not) then [{key:"catalog-prepare",status:"error",exitCode:null,error:"cache-products-missing"}]
        else []
        end
      )
    }')"
  printf '%s\n' "$payload"
  if [[ "$(jq -r '.status' <<<"$payload")" != "ok" ]]; then
    return 1
  fi
}

cmd_catalog_prepare() {
  local json=0
  local destination='platform=iOS Simulator,name=iPhone 17 Pro Max'

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      --destination) destination="${2:?--destination needs value}"; shift 2 ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh catalog prepare [--destination <xcodebuild-destination>] [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown catalog prepare option: $1" >&2
        return 1
        ;;
    esac
  done

  local payload rc=0
  payload="$(cmd_catalog_prepare_json "$destination")" || rc=$?
  if (( json )); then
    printf '%s\n' "$payload"
    return "$rc"
  fi

  jq -r '
    "[ios][catalog-prepare] schema=\(.schema) action=\(.action) status=\(.status) destination=\(.destination)",
    "[ios][catalog-prepare] cache status=\(.cache.status) key=\(.cache.key) root=\(.cache.root) productsReady=\(.cache.productsReady) xctestrun=\(.cache.xctestrunPath // "")",
    "[ios][catalog-prepare] build exitCode=\(.build.exitCode) wallMs=\(.build.wallMs) command=\"\(.build.command)\"",
    (.errors[]? | "[ios][catalog-prepare] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
  ' <<<"$payload"
  return "$rc"
}

cmd_catalog_clean_json() {
  local generated_at cache_root existed_before=false exists_after=false removed=true rc=0 payload
  generated_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  cache_root="$(catalog_default_derived_data_root)"
  [[ -e "$cache_root" ]] && existed_before=true
  if ! rm -rf "$cache_root"; then
    rc=$?
    removed=false
  fi
  [[ -e "$cache_root" ]] && exists_after=true
  if [[ "$exists_after" == "true" ]]; then
    removed=false
  fi

  payload="$(jq -n \
    --arg schema "kg.ios.catalog.clean.v1" \
    --arg generated_at "$generated_at" \
    --arg cacheRoot "$cache_root" \
    --argjson existedBefore "$existed_before" \
    --argjson existsAfter "$exists_after" \
    --argjson removed "$removed" \
    --argjson exitCode "$rc" \
    '{
      schema:$schema,
      generated_at:$generated_at,
      action:"clean",
      status:(if $exitCode == 0 and ($existsAfter | not) then "ok" else "error" end),
      cache:{
        root:$cacheRoot,
        existedBefore:$existedBefore,
        existsAfter:$existsAfter,
        removed:$removed
      },
      errors:(
        if $exitCode != 0 then [{key:"catalog-clean",status:"error",exitCode:$exitCode,error:"cache-remove-failed"}]
        elif $existsAfter then [{key:"catalog-clean",status:"error",exitCode:null,error:"cache-still-exists"}]
        else []
        end
      )
    }')"
  printf '%s\n' "$payload"
  if [[ "$(jq -r '.status' <<<"$payload")" != "ok" ]]; then
    return 1
  fi
}

cmd_catalog_clean() {
  local json=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) json=1; shift ;;
      -h|--help|help)
        echo "Usage: ./ops/ios_ops.sh catalog clean [--json]"
        return 0
        ;;
      *)
        echo "✗ unknown catalog clean option: $1" >&2
        return 1
        ;;
    esac
  done

  local payload rc=0
  payload="$(cmd_catalog_clean_json)" || rc=$?
  if (( json )); then
    printf '%s\n' "$payload"
    return "$rc"
  fi

  jq -r '
    "[ios][catalog-clean] schema=\(.schema) action=\(.action) status=\(.status) root=\(.cache.root)",
    "[ios][catalog-clean] existedBefore=\(.cache.existedBefore) existsAfter=\(.cache.existsAfter) removed=\(.cache.removed)",
    (.errors[]? | "[ios][catalog-clean] error key=\(.key) status=\(.status) exitCode=\(.exitCode // "") error=\(.error // "")")
  ' <<<"$payload"
  return "$rc"
}

cmd_catalog() {
  local action="${1:-help}"
  [[ $# -gt 0 ]] && shift || true
  case "$action" in
    prepare)
      cmd_catalog_prepare "$@"
      ;;
    snapshots)
      cmd_catalog_snapshots "$@"
      ;;
    clean)
      cmd_catalog_clean "$@"
      ;;
    -h|--help|help)
      echo "Usage: ./ops/ios_ops.sh catalog prepare [--destination <xcodebuild-destination>] [--json]"
      echo "       ./ops/ios_ops.sh catalog snapshots [--out-root <dir>] [--destination <xcodebuild-destination>] [--group <category>]... [--scenario <category/title>]... [--dataset <name> | --dataset-file <path>] [--reuse-build] [--json]"
      echo "       ./ops/ios_ops.sh catalog clean [--json]"
      ;;
    *)
      echo "✗ unknown catalog action: $action" >&2
      return 1
      ;;
  esac
}
