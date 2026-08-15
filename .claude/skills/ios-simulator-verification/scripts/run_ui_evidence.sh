#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  run_ui_evidence.sh (--dataset <name> | --dataset-file <path>) \
    (--file <file> | --grep <pattern> | --method <Class/method>) [options]

Options:
  --dataset <name>                 Named UI World under ops/fixtures/ui_worlds/
  --dataset-file <path>            Explicit UI World JSON path inside the source worktree
  --file <file>                    Test file/type selector
  --grep <pattern>                 ios_test -g suite/method pattern
  --method <Class/method>          Positional ios_test Class/method selector
  --device <udid>                  Explicit canonical Simulator UDID only
  --lease                          Claim a Simulator pool lease (default)
  --configuration <Debug|Release>  Forward build/test configuration
  --ui-launch-profile <profile>    Forward ui-smoke or standard profile
  --build-lock-timeout <seconds>   Forward ios_test build/device lock timeout
  --evidence-root <dir>             Put this run bundle below an explicit in-repo root
  --json-out <path>                Atomically publish the normalized stable verdict JSON
  -h, --help                       Show this help
EOF
}

helper_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/$(basename "${BASH_SOURCE[0]}")"
helper_dir="$(dirname "$helper_path")"
tool_root="$(cd "$helper_dir/../../../.." 2>/dev/null && pwd -P || true)"
canonical_validator="$tool_root/ops/uitest_evidence_contract.py"
canonical_manifest_normalizer="$tool_root/ops/uitest_manifest_normalize.py"
tool_resolution="helper-skill-repo"

source_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$source_root" || ! -x "$source_root/ops/ios_ops.sh" ]]; then
  echo "[ui-evidence] error: run from a KG source worktree" >&2
  exit 64
fi
cd "$source_root"

dataset=""
dataset_file=""
dataset_selector=""
selector_kind=""
selector_value=""
device=""
simulator_mode="lease"
json_out=""
evidence_root=""
forward=()

while (($# > 0)); do
  case "$1" in
    --dataset)
      (($# >= 2)) || { echo "[ui-evidence] error: --dataset needs a value" >&2; exit 64; }
      [[ -z "$dataset_selector" ]] || { echo "[ui-evidence] error: provide exactly one dataset selector" >&2; exit 64; }
      [[ -n "$2" && "$2" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "[ui-evidence] error: invalid dataset name" >&2; exit 64; }
      dataset_selector="named"
      dataset="$2"
      shift 2
      ;;
    --dataset-file)
      (($# >= 2)) || { echo "[ui-evidence] error: --dataset-file needs a value" >&2; exit 64; }
      [[ -z "$dataset_selector" ]] || { echo "[ui-evidence] error: provide exactly one dataset selector" >&2; exit 64; }
      dataset_selector="file"
      dataset_file="$2"
      shift 2
      ;;
    --file|--grep|--method)
      (($# >= 2)) || { echo "[ui-evidence] error: $1 needs a value" >&2; exit 64; }
      [[ -z "$selector_kind" ]] || { echo "[ui-evidence] error: provide exactly one test selector" >&2; exit 64; }
      [[ -n "$2" ]] || { echo "[ui-evidence] error: $1 needs a non-empty value" >&2; exit 64; }
      if [[ "$1" == "--method" && "$2" != */* ]]; then
        echo "[ui-evidence] error: --method requires Class/method" >&2
        exit 64
      fi
      selector_kind="$1"
      selector_value="$2"
      shift 2
      ;;
    --device)
      (($# >= 2)) || { echo "[ui-evidence] error: --device needs a value" >&2; exit 64; }
      [[ "$simulator_mode" != "explicit-lease" ]] || { echo "[ui-evidence] error: --device and --lease are mutually exclusive" >&2; exit 64; }
      [[ "$2" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]] \
        || { echo "[ui-evidence] error: --device accepts a canonical Simulator UDID only" >&2; exit 64; }
      device="$2"
      simulator_mode="device"
      shift 2
      ;;
    --lease)
      [[ "$simulator_mode" != "device" ]] || { echo "[ui-evidence] error: --device and --lease are mutually exclusive" >&2; exit 64; }
      simulator_mode="explicit-lease"
      shift
      ;;
    --configuration|--ui-launch-profile|--build-lock-timeout)
      (($# >= 2)) || { echo "[ui-evidence] error: $1 needs a value" >&2; exit 64; }
      forward+=("${1/--build-lock-timeout/--timeout}" "$2")
      shift 2
      ;;
    --json-out)
      (($# >= 2)) || { echo "[ui-evidence] error: --json-out needs a value" >&2; exit 64; }
      json_out="$2"
      shift 2
      ;;
    --evidence-root)
      (($# >= 2)) || { echo "[ui-evidence] error: --evidence-root needs a value" >&2; exit 64; }
      [[ -z "$evidence_root" ]] || { echo "[ui-evidence] error: --evidence-root may be specified once" >&2; exit 64; }
      evidence_root="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ui-evidence] error: unknown option $1" >&2
      usage
      exit 64
      ;;
  esac
done

[[ "$dataset_selector" == "named" || "$dataset_selector" == "file" ]] \
  || { echo "[ui-evidence] error: provide exactly one of --dataset or --dataset-file" >&2; exit 64; }
[[ -n "$selector_kind" ]] \
  || { echo "[ui-evidence] error: provide exactly one of --file, --grep, or --method" >&2; exit 64; }
command -v jq >/dev/null 2>&1 \
  || { echo "[ui-evidence] error: jq is required" >&2; exit 69; }

if [[ -n "$dataset" ]]; then
  dataset_path="$source_root/ops/fixtures/ui_worlds/$dataset.json"
elif [[ "$dataset_file" = /* ]]; then
  dataset_path="$dataset_file"
else
  dataset_path="$source_root/$dataset_file"
fi
[[ -f "$dataset_path" ]] \
  || { echo "[ui-evidence] error: UI World dataset not found: $dataset_path" >&2; exit 64; }
dataset_path_real="$(realpath "$dataset_path" 2>/dev/null || true)"
[[ -n "$dataset_path_real" ]] \
  || { echo "[ui-evidence] error: cannot resolve UI World dataset: $dataset_path" >&2; exit 65; }
case "$dataset_path_real" in
  "$source_root"/*) dataset_path="$dataset_path_real" ;;
  *)
    echo "[ui-evidence] error: --dataset-file must resolve inside this KG worktree: $dataset_path" >&2
    exit 65
    ;;
esac

./ops/ui_world_manifest.py validate "$dataset_path" >&2 \
  || { echo "[ui-evidence] error: UI World manifest validation failed: $dataset_path" >&2; exit 65; }
expected_dataset_id="$(jq -er '.datasetID | strings | select(length > 0)' "$dataset_path")" \
  || { echo "[ui-evidence] error: UI World has no datasetID" >&2; exit 65; }
expected_dataset_sha256="$(shasum -a 256 "$dataset_path" | awk '{print $1}')"

source_commit="$(git rev-parse HEAD)"
source_tree_dirty=false
[[ -n "$(git status --porcelain)" ]] && source_tree_dirty=true
[[ "$source_tree_dirty" == false ]] \
  || { echo "[ui-evidence] error: source tree is dirty; commit before collecting evidence" >&2; exit 65; }

run_id="$(date -u '+%Y%m%d-%H%M%S')-${BASHPID:-$$}-${RANDOM:-0}"
if [[ -n "$evidence_root" ]]; then
  case "$evidence_root" in
    /*) evidence_root_candidate="$evidence_root" ;;
    *) evidence_root_candidate="$source_root/$evidence_root" ;;
  esac
  mkdir -p "$evidence_root_candidate"
  evidence_root_real="$(cd "$evidence_root_candidate" && pwd -P)"
  case "$evidence_root_real" in
    "$source_root"/*) ;;
    *) echo "[ui-evidence] error: --evidence-root must resolve inside this worktree: $evidence_root" >&2; exit 65 ;;
  esac
else
  evidence_root_real="$source_root/build/snapshots/uitest-evidence"
  mkdir -p "$evidence_root_real"
fi
bundle_root="$evidence_root_real/$run_id"
mkdir -p "$(dirname "$bundle_root")"
if ! mkdir "$bundle_root"; then
  echo "[ui-evidence] error: refusing to overwrite existing bundle: $bundle_root" >&2
  exit 65
fi
mkdir "$bundle_root/artifacts"

mark_abandoned() {
  local signal_name="${1:-unknown}"
  set +e
  if [[ ! -f "$normalized_verdict" ]]; then
    jq -n \
      --arg schema "kg.ios.ui-evidence.abandoned.v1" \
      --arg runId "$run_id" \
      --arg signal "$signal_name" \
      --arg sourceCommit "$source_commit" \
      --arg datasetID "$expected_dataset_id" \
      --arg datasetSHA256 "$expected_dataset_sha256" \
      --arg device "$device" \
      --arg bundle "$bundle_root" \
      --arg startedAt "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      '{schema:$schema,runID:$runId,status:"abandoned",reason:("signal:" + $signal),sourceCommit:$sourceCommit,datasetID:$datasetID,datasetSHA256:$datasetSHA256,device:$device,bundleRoot:$bundle,abandonedAt:$startedAt,runnerAlive:false,consumerCheck:"pending",reusableAsFinalEvidence:false}' \
      >"$bundle_root/abandoned.json"
  fi
  exit 130
}

trap 'mark_abandoned SIGINT' INT
trap 'mark_abandoned SIGTERM' TERM
trap 'mark_abandoned SIGHUP' HUP

upstream_stdout="$bundle_root/upstream-verdict.json"
runner_log="$bundle_root/delegate.stderr.log"
stable_log="$bundle_root/artifacts/delegate.stderr.log"
command_log="$bundle_root/command.txt"
normalized_verdict="$bundle_root/verdict.json"
normalized_verdict_tmp="$bundle_root/.verdict.json.tmp"
failure_review_root="$bundle_root/artifacts/ui-review"
failure_review_html="$failure_review_root/UIreview.html"
failure_contact="$failure_review_root/contact_sheet.png"
failure_quick4="$failure_review_root/quick4_contact_sheet.png"
failure_manifest="$failure_review_root/review_manifest.json"
failure_video="$failure_review_root/uitest-videos/uitest.mp4"
failure_xcresult="$bundle_root/artifacts/Test.xcresult"

printf '%s\n' \
  "sourceWorktree=$source_root" \
  "helper=$helper_path" \
  "toolRoot=$tool_root" \
  "validator=$canonical_validator" \
  "branch=$(git branch --show-current)" \
  "sourceCommit=$source_commit" \
  "dataset=$expected_dataset_id" \
  "datasetSHA256=$expected_dataset_sha256" \
  "selector=$selector_kind $selector_value" \
  "simulatorMode=$simulator_mode" >"$command_log"

publish_json_out() {
  [[ -n "$json_out" ]] || return 0
  local output_parent output_tmp
  output_parent="$(dirname "$json_out")"
  mkdir -p "$output_parent"
  output_tmp="$(mktemp "$output_parent/.ui-evidence-verdict.XXXXXX")"
  cp "$normalized_verdict" "$output_tmp"
  mv -f "$output_tmp" "$json_out"
}

copy_file_if_present() {
  local source="$1" target="$2"
  [[ -n "$source" && -f "$source" ]] || return 0
  mkdir -p "$(dirname "$target")"
  cp "$source" "$target"
}

copy_tree_if_present() {
  local source="$1" target="$2"
  [[ -n "$source" && -d "$source" ]] || return 0
  mkdir -p "$target"
  cp -R "$source/." "$target/"
}

discover_failure_artifacts() {
  local discovered_html discovered_contact discovered_quick4 discovered_manifest discovered_video discovered_xcresult discovered_root
  discovered_html="$(sed -n 's/.*html=\([^[:space:]]*\).*/\1/p' "$runner_log" | tail -1)"
  discovered_contact="$(sed -n 's/.*contactSheet=\([^[:space:]]*\).*/\1/p' "$runner_log" | tail -1)"
  discovered_quick4="$(sed -n 's/.*quick4=\([^[:space:]]*\).*/\1/p' "$runner_log" | tail -1)"
  discovered_manifest="$(sed -n 's/.*visualReviewManifest=\([^[:space:]]*\).*/\1/p' "$runner_log" | tail -1)"
  discovered_video="$(sed -n 's/.*archived \([^[:space:]]*\).*/\1/p' "$runner_log" | tail -1)"
  discovered_xcresult="$(sed -n 's/.*xcresult=\([^[:space:]]*\).*/\1/p' "$runner_log" | tail -1)"
  discovered_root=""
  [[ -n "$discovered_html" ]] && discovered_root="$(dirname "$discovered_html")"
  copy_tree_if_present "$discovered_root" "$failure_review_root"
  copy_file_if_present "$discovered_contact" "$failure_contact"
  copy_file_if_present "$discovered_quick4" "$failure_quick4"
  copy_file_if_present "$discovered_manifest" "$failure_manifest"
  copy_file_if_present "$discovered_video" "$failure_video"
  if [[ -n "$discovered_xcresult" && -e "$discovered_xcresult" ]]; then
    cp -R "$discovered_xcresult" "$failure_xcresult"
  fi
}

write_fallback_verdict() {
  local status="$1" result="$2" exit_value="$3" reason="$4" contract_status="$5"
  local review_root_exists=false review_html_exists=false contact_exists=false quick4_exists=false manifest_exists=false video_exists=false xcresult_exists=false
  if [[ -s "$runner_log" ]]; then
    cp "$runner_log" "$stable_log"
  else
    printf '%s\n' 'no delegate stderr output' >"$stable_log"
  fi
  [[ -d "$failure_review_root" ]] && review_root_exists=true
  [[ -f "$failure_review_html" ]] && review_html_exists=true
  [[ -f "$failure_contact" ]] && contact_exists=true
  [[ -f "$failure_quick4" ]] && quick4_exists=true
  [[ -f "$failure_manifest" ]] && manifest_exists=true
  [[ -f "$failure_video" ]] && video_exists=true
  [[ -d "$failure_xcresult" || -f "$failure_xcresult" ]] && xcresult_exists=true

  jq -n \
    --arg status "$status" \
    --arg result "$result" \
    --arg exitValue "$exit_value" \
    --arg reason "$reason" \
    --arg contractStatus "$contract_status" \
    --arg bundle "$bundle_root" \
    --arg runId "$run_id" \
    --arg commandLog "$command_log" \
    --arg toolRoot "$tool_root" \
    --arg validator "$canonical_validator" \
    --arg toolResolution "$tool_resolution" \
    --arg selector "$selector_kind $selector_value" \
    --arg sourceCommit "$source_commit" \
    --arg datasetID "$expected_dataset_id" \
    --arg datasetSHA256 "$expected_dataset_sha256" \
    --arg device "$device" \
    --arg log "$stable_log" \
    --arg xcresult "$failure_xcresult" \
    --arg reviewRoot "$failure_review_root" \
    --arg reviewHtml "$failure_review_html" \
    --arg contact "$failure_contact" \
    --arg quick4 "$failure_quick4" \
    --arg manifest "$failure_manifest" \
    --arg video "$failure_video" \
    --argjson reviewRootExists "$review_root_exists" \
    --argjson reviewHtmlExists "$review_html_exists" \
    --argjson contactExists "$contact_exists" \
    --argjson quick4Exists "$quick4_exists" \
    --argjson manifestExists "$manifest_exists" \
    --argjson videoExists "$video_exists" \
    --argjson xcresultExists "$xcresult_exists" '
    {
      schema:"kg.ios.ui-evidence.v1", kind:"test", runId:$runId,
      status:$status, result:$result, exit:$exitValue, reason:$reason, executed:"0",
      options:{
        sourceCommit:$sourceCommit, sourceTreeDirty:false,
        datasetID:$datasetID, datasetSHA256:$datasetSHA256,
        device:(if $device == "" then null else $device end)
      },
      artifacts:{
        log:$log, logExists:true,
        xcresult:(if $xcresultExists then $xcresult else null end), xcresultExists:$xcresultExists,
        uiContactSheet:(if $contactExists then $contact else null end), uiContactSheetExists:$contactExists,
        uiQuick4Sheet:(if $quick4Exists then $quick4 else null end), uiQuick4SheetExists:$quick4Exists,
        uiVisualReviewManifest:(if $manifestExists then $manifest else null end), uiVisualReviewManifestExists:$manifestExists,
        uiScreenshotDir:(if $reviewRootExists then $reviewRoot else null end),
        uiVideo:(if $videoExists then $video else null end), uiVideoExists:$videoExists,
        uiReviewRoot:(if $reviewRootExists then $reviewRoot else null end), uiReviewRootExists:$reviewRootExists,
        uiReviewHtml:(if $reviewHtmlExists then $reviewHtml else null end), uiReviewHtmlExists:$reviewHtmlExists
      },
      uiVisualReview:{
        screenshotDir:(if $reviewRootExists then $reviewRoot else null end),
        contactSheet:(if $contactExists then $contact else null end), contactSheetExists:$contactExists,
        quick4Sheet:(if $quick4Exists then $quick4 else null end), quick4SheetExists:$quick4Exists,
        visualReviewManifest:(if $manifestExists then $manifest else null end), visualReviewManifestExists:$manifestExists,
        video:(if $videoExists then $video else null end), videoExists:$videoExists,
        reviewRoot:(if $reviewRootExists then $reviewRoot else null end), reviewRootExists:$reviewRootExists,
        reviewHtml:(if $reviewHtmlExists then $reviewHtml else null end), reviewHtmlExists:$reviewHtmlExists
      },
      helper:{
        schema:"kg.ios.ui-evidence.v1", bundleRoot:$bundle,
        commandLog:$commandLog, selector:$selector,
        retention:"stable-per-run-bundle", contractStatus:$contractStatus,
        toolRoot:$toolRoot, validator:$validator, toolResolution:$toolResolution,
        normalizedVerdict:($bundle + "/verdict.json")
      }
    }' >"$normalized_verdict_tmp"
  mv -f "$normalized_verdict_tmp" "$normalized_verdict"
  publish_json_out
}

run_evidence_validator() {
  if [[ -x "$tool_root/.venv/bin/python" ]]; then
    "$tool_root/.venv/bin/python" "$canonical_validator" "$@"
  else
    (cd "$tool_root" && uv run --python 3.13 python "$canonical_validator" "$@")
  fi
}

echo "[ui-evidence] phase=preflight branch=$(git branch --show-current) head=$source_commit dirty=$source_tree_dirty bundle=$bundle_root" >&2
if [[ -z "$tool_root" || ! -f "$canonical_validator" ]]; then
  reason="missing canonical evidence validator: $canonical_validator"
  printf '%s\n' "$reason" >"$bundle_root/helper-error.txt"
  write_fallback_verdict inconclusive inconclusive 70 "$reason" tool-missing
  echo "[ui-evidence] error: $reason; bundle=$bundle_root" >&2
  exit 70
fi
if ! run_evidence_validator --help >"$bundle_root/validator-preflight.txt" 2>&1; then
  reason="canonical evidence validator contract preflight failed: $canonical_validator"
  printf '%s\n' "$reason" >"$bundle_root/helper-error.txt"
  write_fallback_verdict inconclusive inconclusive 70 "$reason" tool-invalid
  echo "[ui-evidence] error: $reason; bundle=$bundle_root" >&2
  exit 70
fi
if ! ./ops/ios_ops.sh xcode --json >>"$runner_log" 2>&1; then
  write_fallback_verdict inconclusive inconclusive 65 'Xcode preflight failed' preflight-failed
  echo "[ui-evidence] error: Xcode preflight failed; bundle=$bundle_root" >&2
  exit 65
fi
if ! ./ops/ios_ops.sh simulator status --json >>"$runner_log" 2>&1; then
  write_fallback_verdict inconclusive inconclusive 65 'Simulator preflight failed' preflight-failed
  echo "[ui-evidence] error: Simulator preflight failed; bundle=$bundle_root" >&2
  exit 65
fi

run_args=(test --ui --json)
if [[ -n "$dataset" ]]; then
  run_args+=(--dataset "$dataset")
else
  run_args+=(--dataset-file "$dataset_file")
fi
if [[ -n "$device" ]]; then
  run_args+=(--device "$device")
else
  run_args+=(--lease)
fi
if ((${#forward[@]})); then
  run_args+=("${forward[@]}")
fi
case "$selector_kind" in
  --file) run_args+=(--file "$selector_value") ;;
  --grep) run_args+=(--grep "$selector_value") ;;
  --method) run_args+=("$selector_value") ;;
esac

printf 'runner=' >>"$command_log"
printf '%q ' ./ops/ios_ops.sh "${run_args[@]}" >>"$command_log"
printf '\n' >>"$command_log"
echo "[ui-evidence] phase=run selector=$selector_kind $selector_value" >&2
set +e
KG_UI_TEST_EXACT_SELECTOR="$selector_kind $selector_value" \
  ./ops/ios_ops.sh "${run_args[@]}" >"$upstream_stdout" 2>>"$runner_log"
run_rc=$?
set -e

if [[ ! -s "$upstream_stdout" ]] || ! jq -e 'type == "object"' "$upstream_stdout" >/dev/null 2>&1; then
  [[ -s "$upstream_stdout" ]] && cp "$upstream_stdout" "$bundle_root/upstream-verdict.raw"
  discover_failure_artifacts
  if [[ "$run_rc" -eq 0 ]]; then
    write_fallback_verdict inconclusive inconclusive 70 'ios_ops did not emit a JSON object' invalid-upstream
    exit 70
  fi
  write_fallback_verdict fail fail "$run_rc" 'ios_ops did not emit a JSON object' invalid-upstream
  exit "$run_rc"
fi

upstream_review_root="$(jq -r '.uiVisualReview.reviewRoot // .artifacts.uiReviewRoot // empty' "$upstream_stdout")"
upstream_xcresult="$(jq -r '.artifacts.xcresult // empty' "$upstream_stdout")"
upstream_contact="$(jq -r '.uiVisualReview.contactSheet // .artifacts.uiContactSheet // empty' "$upstream_stdout")"
upstream_quick4="$(jq -r '.uiVisualReview.quick4Sheet // .artifacts.uiQuick4Sheet // empty' "$upstream_stdout")"
upstream_manifest="$(jq -r '.uiVisualReview.visualReviewManifest // .artifacts.uiVisualReviewManifest // empty' "$upstream_stdout")"
upstream_variant=""
if [[ -n "$upstream_manifest" && -f "$upstream_manifest" ]]; then
  upstream_variant="$(jq -r '.provenance.variant // empty' "$upstream_manifest" 2>/dev/null || true)"
fi
upstream_video="$(jq -r '.uiVisualReview.video // .artifacts.uiVideo // empty' "$upstream_stdout")"
upstream_video_run_id="$(jq -r '.uiVisualReview.videoIdentity.runID // .artifacts.uiVideoIdentity.runID // empty' "$upstream_stdout")"
upstream_video_file="$(jq -r '.uiVisualReview.videoIdentity.file // .artifacts.uiVideoIdentity.file // empty' "$upstream_stdout")"
upstream_video_sha256="$(jq -r '.uiVisualReview.videoIdentity.sha256 // .artifacts.uiVideoIdentity.sha256 // empty' "$upstream_stdout")"
upstream_log="$(jq -r '.artifacts.log // empty' "$upstream_stdout")"
upstream_review_run_id=""
[[ -n "$upstream_review_root" ]] && upstream_review_run_id="$(basename "$upstream_review_root")"

stable_review_root="$bundle_root/artifacts/ui-review"
copy_tree_if_present "$upstream_review_root" "$stable_review_root"
stable_review_html="$stable_review_root/UIreview.html"
stable_contact="$stable_review_root/$(basename "${upstream_contact:-contact_sheet.png}")"
stable_quick4="$stable_review_root/$(basename "${upstream_quick4:-quick4_contact_sheet.png}")"
stable_manifest="$stable_review_root/$(basename "${upstream_manifest:-review_manifest.json}")"
stable_video="$stable_review_root/uitest-videos/$(basename "${upstream_video:-uitest.mp4}")"
copy_file_if_present "$upstream_contact" "$stable_contact"
copy_file_if_present "$upstream_quick4" "$stable_quick4"
copy_file_if_present "$upstream_manifest" "$stable_manifest"
copy_file_if_present "$upstream_video" "$stable_video"
if [[ -n "$upstream_log" && -f "$upstream_log" ]]; then
  cp "$upstream_log" "$stable_log"
elif [[ -s "$runner_log" ]]; then
  cp "$runner_log" "$stable_log"
else
  printf '%s\n' 'no delegate stderr output' >"$stable_log"
fi

# Rebind legacy manifests to the copied step PNG bytes and current provenance
# in the stable bundle; never mutate the producer's source artifact.
normalize_stable_manifest() {
  [[ -d "$stable_review_root" && -s "$stable_manifest" ]] || return 0
  local normalize_device="$1"
  local normalize_selector="$2"
  local normalize_variant="${3:-}"
  local normalize_args=(
    "$canonical_manifest_normalizer"
    --manifest "$stable_manifest"
    --screenshot-dir "$stable_review_root"
    --source-commit "$source_commit"
    --dataset-id "$expected_dataset_id"
    --dataset-sha256 "$expected_dataset_sha256"
    --device "$normalize_device"
    --selector "$normalize_selector"
  )
  [[ -n "$normalize_variant" ]] && normalize_args+=(--variant "$normalize_variant")
  if [[ -x "$tool_root/.venv/bin/python" ]]; then
    "$tool_root/.venv/bin/python" "${normalize_args[@]}" >/dev/null 2>>"$runner_log" || return 0
  else
    (cd "$tool_root" && uv run --python 3.13 python "${normalize_args[@]}") >/dev/null 2>>"$runner_log" || return 0
  fi
}

stable_xcresult="$bundle_root/artifacts/Test.xcresult"
if [[ -n "$upstream_xcresult" && -e "$upstream_xcresult" ]]; then
  cp -R "$upstream_xcresult" "$stable_xcresult"
fi

review_root_exists=false
review_html_exists=false
contact_exists=false
quick4_exists=false
manifest_exists=false
video_exists=false
xcresult_exists=false
[[ -d "$stable_review_root" ]] && review_root_exists=true
[[ -f "$stable_review_html" ]] && review_html_exists=true
[[ -f "$stable_contact" ]] && contact_exists=true
[[ -f "$stable_quick4" ]] && quick4_exists=true
[[ -f "$stable_manifest" ]] && manifest_exists=true
[[ -f "$stable_video" ]] && video_exists=true
[[ -d "$stable_xcresult" || -f "$stable_xcresult" ]] && xcresult_exists=true

artifact_contract_status=fail
artifact_contract_reason='visual evidence artifact contract not run'
artifact_contract_json="$bundle_root/artifacts/ui-evidence-contract.json"
upstream_device="$(jq -r '.device // empty' "$upstream_stdout")"
normalize_stable_manifest "$upstream_device" "$selector_kind $selector_value" "$upstream_variant"
validator_args=(
  validate
  --screenshot-dir "$stable_review_root"
  --manifest "$stable_manifest"
  --contact-sheet "$stable_contact"
  --quick4-sheet "$stable_quick4"
  --video "$stable_video"
  --video-run-id "$upstream_video_run_id"
  --review-run-id "$upstream_review_run_id"
  --video-file "$upstream_video_file"
  --video-sha256 "$upstream_video_sha256"
  --review-html "$stable_review_html"
  --source-commit "$source_commit"
  --dataset-id "$expected_dataset_id"
  --dataset-sha256 "$expected_dataset_sha256"
  --device "$upstream_device"
  --selector "$selector_kind $selector_value"
)
[[ -n "$upstream_variant" ]] && validator_args+=(--variant "$upstream_variant")
if run_evidence_validator "${validator_args[@]}" >"$artifact_contract_json" 2>&1; then
  artifact_contract_status=pass
  artifact_contract_reason=''
else
  artifact_contract_reason="$(tail -1 "$artifact_contract_json" 2>/dev/null || printf '%s' 'artifact validator failed')"
fi

current_commit="$(git rev-parse HEAD)"
current_dirty=false
[[ -n "$(git status --porcelain)" ]] && current_dirty=true

verdict_filter='(.schema == "kg.ios.run.v1") and (.kind == "test")'
verdict_filter+=' and (.status == "ok") and (.result == "ok") and ((.exit | tostring) == "0")'
verdict_filter+=' and (((.executed | tostring | tonumber?) // 0) > 0)'
verdict_filter+=' and (.options.sourceCommit == $sourceCommit) and (.options.sourceTreeDirty == false)'
verdict_filter+=' and (.options.datasetID == $datasetID) and (.options.datasetSHA256 == $datasetSHA256)'
verdict_filter+=' and (if (.device | type) == "string" then (.device | test("^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")) else false end)'
verdict_filter+=' and (if (.options.device | type) == "string" then ((.options.device | test("^platform=iOS Simulator(,|$)")) and (.options.device | test("(^|,)id=" + $udid + "(,|$)"))) else false end)'
verdict_filter+=' and (($expectedDevice == "") or ((.device | ascii_downcase) == ($expectedDevice | ascii_downcase)))'
verdict_filter+=' and (.uiVisualReview | type == "object")'
verdict_filter+=' and (.uiVisualReview.reviewHtmlExists == true) and (.uiVisualReview.contactSheetExists == true)'
verdict_filter+=' and (.uiVisualReview.quick4SheetExists == true) and (.uiVisualReview.visualReviewManifestExists == true)'
verdict_filter+=' and (.uiVisualReview.videoExists == true) and (.uiVisualReview.reviewRootExists == true)'
verdict_filter+=' and (.uiVisualReview.videoIdentity | type == "object") and (.artifacts.uiVideoIdentity == .uiVisualReview.videoIdentity)'
verdict_filter+=' and (.uiVisualReview.videoIdentity.runID == $videoRunID) and (.uiVisualReview.videoIdentity.file == $videoFile) and (.uiVisualReview.videoIdentity.sha256 == $videoSHA256)'
verdict_filter+=' and ($videoRunID == $reviewRunID)'

contract_status=runner-failed
normalized_status=fail
normalized_result=fail
normalized_exit="$run_rc"
normalized_reason="upstream runner exited rc=$run_rc"
if [[ "$run_rc" -eq 0 ]]; then
  contract_status=contract-failed
  normalized_status=inconclusive
  normalized_result=inconclusive
  normalized_exit=70
  normalized_reason='upstream verdict failed evidence contract'
  if jq -e \
      --arg sourceCommit "$source_commit" \
      --arg datasetID "$expected_dataset_id" \
      --arg datasetSHA256 "$expected_dataset_sha256" \
      --arg expectedDevice "$device" \
      --arg udid "$upstream_device" \
      --arg videoRunID "$upstream_video_run_id" \
      --arg videoFile "$upstream_video_file" \
      --arg videoSHA256 "$upstream_video_sha256" \
      --arg reviewRunID "$upstream_review_run_id" \
      "$verdict_filter" "$upstream_stdout" >/dev/null 2>&1 \
    && [[ "$current_commit" == "$source_commit" && "$current_dirty" == false ]] \
    && [[ -f "$stable_review_html" && -f "$stable_contact" && -f "$stable_quick4" ]] \
    && [[ -f "$stable_manifest" && -f "$stable_video" && -e "$stable_xcresult" ]] \
    && [[ "$artifact_contract_status" == pass ]]; then
    contract_status=pass
    normalized_status=ok
    normalized_result=ok
    normalized_exit=0
    normalized_reason=''
  fi
fi

jq \
  --arg bundle "$bundle_root" \
  --arg runId "$run_id" \
  --arg commandLog "$command_log" \
  --arg runnerLog "$stable_log" \
  --arg toolRoot "$tool_root" \
  --arg validator "$canonical_validator" \
  --arg toolResolution "$tool_resolution" \
  --arg xcresult "$stable_xcresult" \
  --arg reviewRoot "$stable_review_root" \
  --arg reviewHtml "$stable_review_html" \
  --arg contactSheet "$stable_contact" \
  --arg quick4Sheet "$stable_quick4" \
  --arg manifest "$stable_manifest" \
  --arg video "$stable_video" \
  --arg videoRunID "$upstream_video_run_id" \
  --arg videoFile "$upstream_video_file" \
  --arg videoSHA256 "$upstream_video_sha256" \
  --arg selector "$selector_kind $selector_value" \
  --arg contractStatus "$contract_status" \
  --arg normalizedStatus "$normalized_status" \
  --arg normalizedResult "$normalized_result" \
  --arg normalizedExit "$normalized_exit" \
  --arg normalizedReason "$normalized_reason" \
  --arg upstreamPath "$upstream_stdout" \
  --arg runnerExit "$run_rc" \
  --arg artifactContractStatus "$artifact_contract_status" \
  --arg artifactContractReason "$artifact_contract_reason" \
  --arg artifactContract "$artifact_contract_json" \
  --argjson reviewRootExists "$review_root_exists" \
  --argjson reviewHtmlExists "$review_html_exists" \
  --argjson contactExists "$contact_exists" \
  --argjson quick4Exists "$quick4_exists" \
  --argjson manifestExists "$manifest_exists" \
  --argjson videoExists "$video_exists" \
  --argjson xcresultExists "$xcresult_exists" '
  .runId = $runId
  | .upstreamStatus = {
      status:(.status // null), result:(.result // null),
      exit:(.exit // null), reason:(.reason // null), executed:(.executed // null)
    }
  | .upstreamArtifacts = (.artifacts // {})
  | .upstreamUiVisualReview = (.uiVisualReview // null)
  | .status = $normalizedStatus
  | .result = $normalizedResult
  | .exit = $normalizedExit
  | .reason = (if $normalizedReason == "" then null else $normalizedReason end)
  | .artifacts = {
      log:$runnerLog, logExists:true,
      xcresult:(if $xcresultExists then $xcresult else null end), xcresultExists:$xcresultExists,
      uiContactSheet:(if $contactExists then $contactSheet else null end), uiContactSheetExists:$contactExists,
      uiQuick4Sheet:(if $quick4Exists then $quick4Sheet else null end), uiQuick4SheetExists:$quick4Exists,
      uiVisualReviewManifest:(if $manifestExists then $manifest else null end), uiVisualReviewManifestExists:$manifestExists,
      uiScreenshotDir:(if $reviewRootExists then $reviewRoot else null end),
      uiVideo:(if $videoExists then $video else null end), uiVideoExists:$videoExists,
      uiVideoIdentity:(if $videoExists then {runID:$videoRunID,file:$videoFile,sha256:$videoSHA256} else null end),
      uiReviewRoot:(if $reviewRootExists then $reviewRoot else null end), uiReviewRootExists:$reviewRootExists,
      uiReviewHtml:(if $reviewHtmlExists then $reviewHtml else null end), uiReviewHtmlExists:$reviewHtmlExists
    }
  | .uiVisualReview = {
      screenshotDir:(if $reviewRootExists then $reviewRoot else null end),
      contactSheet:(if $contactExists then $contactSheet else null end), contactSheetExists:$contactExists,
      quick4Sheet:(if $quick4Exists then $quick4Sheet else null end), quick4SheetExists:$quick4Exists,
      visualReviewManifest:(if $manifestExists then $manifest else null end), visualReviewManifestExists:$manifestExists,
      video:(if $videoExists then $video else null end), videoExists:$videoExists,
      videoIdentity:(if $videoExists then {runID:$videoRunID,file:$videoFile,sha256:$videoSHA256} else null end),
      reviewRoot:(if $reviewRootExists then $reviewRoot else null end), reviewRootExists:$reviewRootExists,
      reviewHtml:(if $reviewHtmlExists then $reviewHtml else null end), reviewHtmlExists:$reviewHtmlExists
    }
  | .helper = {
      schema:"kg.ios.ui-evidence.v1", bundleRoot:$bundle,
      commandLog:$commandLog, selector:$selector,
      retention:"stable-per-run-bundle", contractStatus:$contractStatus,
      toolRoot:$toolRoot, validator:$validator, toolResolution:$toolResolution,
      artifactContractStatus:$artifactContractStatus,
      artifactContractReason:(if $artifactContractReason == "" then null else $artifactContractReason end),
      artifactContract:$artifactContract,
      runnerExit:$runnerExit, upstreamVerdict:$upstreamPath,
      normalizedVerdict:($bundle + "/verdict.json")
    }' "$upstream_stdout" >"$normalized_verdict_tmp"
mv -f "$normalized_verdict_tmp" "$normalized_verdict"
publish_json_out

jq -r '
  "[ui-evidence] verdict=\(.status) exit=\(.exit) reason=\(.reason // "")",
  "[ui-evidence] contract=\(.helper.contractStatus)",
  "[ui-evidence] bundle=\(.helper.bundleRoot)",
  "[ui-evidence] uiReview=\(.artifacts.uiReviewHtml)",
  "[ui-evidence] contactSheet=\(.artifacts.uiContactSheet)",
  "[ui-evidence] video=\(.artifacts.uiVideo)"
' "$normalized_verdict" >&2

if [[ "$run_rc" -ne 0 ]]; then
  exit "$run_rc"
fi
[[ "$contract_status" == pass ]] || exit 70
exit 0
