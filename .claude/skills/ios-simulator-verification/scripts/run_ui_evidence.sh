#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  run_ui_evidence.sh --dataset <name> (--file <file> | --grep <pattern> | --method <Class/method>) [options]

Options:
  --dataset <name>                 Named UI World under ops/fixtures/ui_worlds/
  --dataset-file <path>            Explicit UI World JSON path
  --file <file>                    Test file/type selector
  --grep <pattern>                 ios_test -g suite/method pattern
  --method <Class/method>          Positional ios_test Class/method selector
  --device <udid>                  Explicit canonical Simulator UDID only
  --lease                           Claim a disposable pool Simulator (default)
  --configuration <Debug|Release>  Forward build/test configuration
  --ui-launch-profile <profile>    Forward ui-smoke or standard profile
  --build-lock-timeout <seconds>   Forward ios_test build/device lock timeout
  --json-out <path>                Copy the normalized stable verdict JSON
EOF
}

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$repo_root" || ! -x "$repo_root/ops/ios_ops.sh" ]]; then
  echo "[ui-evidence] error: run from a KG worktree" >&2
  exit 64
fi
cd "$repo_root"

dataset=""
dataset_file=""
dataset_selector=""
selector_kind=""
selector_value=""
device=""
simulator_mode="default-lease"
json_out=""
forward=()

while (($# > 0)); do
  case "$1" in
    --dataset)
      (($# >= 2)) || { echo "[ui-evidence] error: --dataset needs a value" >&2; exit 64; }
      [[ -z "$dataset_selector" ]] || { echo "[ui-evidence] error: dataset selector may be supplied only once" >&2; exit 64; }
      [[ -n "$2" && "$2" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "[ui-evidence] error: --dataset needs a dataset name" >&2; exit 64; }
      dataset_selector="named"
      dataset="$2"; shift 2 ;;
    --dataset-file)
      (($# >= 2)) || { echo "[ui-evidence] error: --dataset-file needs a value" >&2; exit 64; }
      [[ -z "$dataset_selector" ]] || { echo "[ui-evidence] error: dataset selector may be supplied only once" >&2; exit 64; }
      dataset_selector="file"
      dataset_file="$2"; shift 2 ;;
    --file|--grep|--method)
      (($# >= 2)) || { echo "[ui-evidence] error: $1 needs a value" >&2; exit 64; }
      [[ -z "$selector_kind" ]] || { echo "[ui-evidence] error: provide exactly one of --file, --grep, or --method" >&2; exit 64; }
      [[ -n "$2" ]] || { echo "[ui-evidence] error: $1 needs a non-empty value" >&2; exit 64; }
      if [[ "$1" == "--method" && "$2" != */* ]]; then
        echo "[ui-evidence] error: --method requires a Class/method selector" >&2
        exit 64
      fi
      selector_kind="$1"
      selector_value="$2"; shift 2 ;;
    --device)
      (($# >= 2)) || { echo "[ui-evidence] error: --device needs a value" >&2; exit 64; }
      [[ "$simulator_mode" != "explicit-lease" ]] || { echo "[ui-evidence] error: --device and --lease are mutually exclusive" >&2; exit 64; }
      [[ "$2" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]] || { echo "[ui-evidence] error: --device accepts a canonical Simulator UDID only; use --lease for a device name" >&2; exit 64; }
      device="$2"; simulator_mode="device"; shift 2 ;;
    --lease)
      [[ "$simulator_mode" != "device" ]] || { echo "[ui-evidence] error: --device and --lease are mutually exclusive" >&2; exit 64; }
      simulator_mode="explicit-lease"; shift ;;
    --configuration|--ui-launch-profile|--build-lock-timeout)
      (($# >= 2)) || { echo "[ui-evidence] error: $1 needs a value" >&2; exit 64; }
      forward+=("${1/--build-lock-timeout/--timeout}" "$2"); shift 2 ;;
    --json-out)
      (($# >= 2)) || { echo "[ui-evidence] error: --json-out needs a value" >&2; exit 64; }
      json_out="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "[ui-evidence] error: unknown option $1" >&2
      usage
      exit 64 ;;
  esac
done

if [[ "$dataset_selector" != "named" && "$dataset_selector" != "file" ]]; then
  echo "[ui-evidence] error: provide exactly one of --dataset or --dataset-file" >&2
  exit 64
fi
if [[ -z "$selector_kind" ]]; then
  echo "[ui-evidence] error: provide exactly one test selector (--file, --grep, or --method)" >&2
  exit 64
fi
command -v jq >/dev/null 2>&1 || {
  echo "[ui-evidence] error: jq is required by the KG iOS ops contract" >&2
  exit 69
}

if [[ -n "$dataset" ]]; then
  dataset_path="$repo_root/ops/fixtures/ui_worlds/$dataset.json"
else
  if [[ "$dataset_file" = /* ]]; then dataset_path="$dataset_file"; else dataset_path="$repo_root/$dataset_file"; fi
fi
[[ -f "$dataset_path" ]] || { echo "[ui-evidence] error: UI World dataset not found: $dataset_path" >&2; exit 64; }
./ops/ui_world_manifest.py validate "$dataset_path" >&2 || { echo "[ui-evidence] error: UI World manifest validation failed: $dataset_path" >&2; exit 65; }
expected_dataset_id="$(jq -er '.datasetID | strings | select(length > 0)' "$dataset_path")" || { echo "[ui-evidence] error: UI World has no datasetID" >&2; exit 65; }
expected_dataset_sha256="$(shasum -a 256 "$dataset_path" | awk '{print $1}')"

source_tree_dirty=false
[[ -n "$(git status --porcelain)" ]] && source_tree_dirty=true
source_commit="$(git rev-parse HEAD)"
[[ "$source_tree_dirty" == false ]] || { echo "[ui-evidence] error: source tree is dirty; commit before collecting evidence" >&2; exit 65; }

run_id="$(date -u '+%Y%m%d-%H%M%S')-$$"
bundle_root="$repo_root/build/snapshots/uitest-evidence/$run_id"
mkdir -p "$bundle_root/artifacts"
upstream_stdout="$bundle_root/upstream-verdict.json"
runner_log="$bundle_root/delegate.stderr.log"
stable_log="$bundle_root/artifacts/delegate.stderr.log"
command_log="$bundle_root/command.txt"
normalized_verdict="$bundle_root/verdict.json"
failure_review_root="$bundle_root/artifacts/ui-review"
failure_review_html="$failure_review_root/UIreview.html"
failure_contact="$failure_review_root/contact_sheet.png"
failure_quick4="$failure_review_root/quick4_contact_sheet.png"
failure_manifest="$failure_review_root/review_manifest.json"
failure_video="$failure_review_root/uitest-videos/uitest.mp4"
failure_xcresult="$bundle_root/artifacts/Test.xcresult"
printf '%s\n' "worktree=$repo_root" "branch=$(git branch --show-current)" "sourceCommit=$source_commit" \
  "dataset=$expected_dataset_id" "datasetSHA256=$expected_dataset_sha256" "selector=$selector_kind $selector_value" \
  "simulatorMode=$simulator_mode" >"$command_log"

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
  if [[ -n "$discovered_root" && -d "$discovered_root" ]]; then
    mkdir -p "$failure_review_root"
    cp -R "$discovered_root/." "$failure_review_root/"
  fi
  if [[ -n "$discovered_contact" && -f "$discovered_contact" ]]; then mkdir -p "$failure_review_root"; cp "$discovered_contact" "$failure_contact"; fi
  if [[ -n "$discovered_quick4" && -f "$discovered_quick4" ]]; then mkdir -p "$failure_review_root"; cp "$discovered_quick4" "$failure_quick4"; fi
  if [[ -n "$discovered_manifest" && -f "$discovered_manifest" ]]; then mkdir -p "$failure_review_root"; cp "$discovered_manifest" "$failure_manifest"; fi
  if [[ -n "$discovered_video" && -f "$discovered_video" ]]; then mkdir -p "$(dirname "$failure_video")"; cp "$discovered_video" "$failure_video"; fi
  if [[ -n "$discovered_xcresult" && -e "$discovered_xcresult" ]]; then cp -R "$discovered_xcresult" "$failure_xcresult"; fi
}

write_fallback_verdict() {
  local status="$1" result="$2" exit_value="$3" reason="$4" contract_status="$5"
  local review_root_exists=false review_html_exists=false contact_exists=false quick4_exists=false manifest_exists=false video_exists=false xcresult_exists=false
  if [[ -s "$runner_log" ]]; then cp "$runner_log" "$stable_log"; else printf '%s\n' "no delegate stderr output" >"$stable_log"; fi
  [[ -d "$failure_review_root" ]] && review_root_exists=true
  [[ -f "$failure_review_html" ]] && review_html_exists=true
  [[ -f "$failure_contact" ]] && contact_exists=true
  [[ -f "$failure_quick4" ]] && quick4_exists=true
  [[ -f "$failure_manifest" ]] && manifest_exists=true
  [[ -f "$failure_video" ]] && video_exists=true
  [[ -d "$failure_xcresult" || -f "$failure_xcresult" ]] && xcresult_exists=true
  jq -n \
    --arg status "$status" --arg result "$result" --arg exitValue "$exit_value" --arg reason "$reason" \
    --arg contractStatus "$contract_status" --arg bundle "$bundle_root" --arg commandLog "$command_log" \
    --arg selector "$selector_kind $selector_value" --arg sourceCommit "$source_commit" \
    --arg datasetID "$expected_dataset_id" --arg datasetSHA256 "$expected_dataset_sha256" \
    --arg device "$device" --arg log "$stable_log" --arg xcresult "$failure_xcresult" --arg reviewRoot "$failure_review_root" \
    --arg reviewHtml "$failure_review_html" --arg contact "$failure_contact" --arg quick4 "$failure_quick4" --arg manifest "$failure_manifest" --arg video "$failure_video" \
    --argjson reviewRootExists "$review_root_exists" --argjson reviewHtmlExists "$review_html_exists" --argjson contactExists "$contact_exists" \
    --argjson quick4Exists "$quick4_exists" --argjson manifestExists "$manifest_exists" --argjson videoExists "$video_exists" --argjson xcresultExists "$xcresult_exists" \
    '{schema:"kg.ios.ui-evidence.v1",kind:"test",status:$status,result:$result,exit:$exitValue,reason:$reason,executed:"0",
      options:{sourceCommit:$sourceCommit,sourceTreeDirty:false,datasetID:$datasetID,datasetSHA256:$datasetSHA256,
        device:(if $device == "" then null else $device end)},
      artifacts:{log:$log,logExists:true,xcresult:(if $xcresultExists then $xcresult else null end),xcresultExists:$xcresultExists,
        uiContactSheet:(if $contactExists then $contact else null end),uiContactSheetExists:$contactExists,
        uiQuick4Sheet:(if $quick4Exists then $quick4 else null end),uiQuick4SheetExists:$quick4Exists,
        uiVisualReviewManifest:(if $manifestExists then $manifest else null end),uiVisualReviewManifestExists:$manifestExists,
        uiScreenshotDir:(if $reviewRootExists then $reviewRoot else null end),uiVideo:(if $videoExists then $video else null end),uiVideoExists:$videoExists,
        uiReviewRoot:(if $reviewRootExists then $reviewRoot else null end),uiReviewRootExists:$reviewRootExists,
        uiReviewHtml:(if $reviewHtmlExists then $reviewHtml else null end),uiReviewHtmlExists:$reviewHtmlExists},
      uiVisualReview:{screenshotDir:(if $reviewRootExists then $reviewRoot else null end),contactSheet:(if $contactExists then $contact else null end),contactSheetExists:$contactExists,
        quick4Sheet:(if $quick4Exists then $quick4 else null end),quick4SheetExists:$quick4Exists,visualReviewManifest:(if $manifestExists then $manifest else null end),visualReviewManifestExists:$manifestExists,
        video:(if $videoExists then $video else null end),videoExists:$videoExists,reviewRoot:(if $reviewRootExists then $reviewRoot else null end),reviewRootExists:$reviewRootExists,
        reviewHtml:(if $reviewHtmlExists then $reviewHtml else null end),reviewHtmlExists:$reviewHtmlExists},
      helper:{schema:"kg.ios.ui-evidence.v1",bundleRoot:$bundle,commandLog:$commandLog,selector:$selector,
        retention:"stable-per-run-bundle",contractStatus:$contractStatus,normalizedVerdict:($bundle + "/verdict.json")}}' >"$normalized_verdict"
  if [[ -n "$json_out" ]]; then
    json_parent="$(dirname "$json_out")"
    mkdir -p "$json_parent"
    cp "$normalized_verdict" "$json_out"
  fi
}

echo "[ui-evidence] phase=preflight branch=$(git branch --show-current) head=$source_commit dirty=$source_tree_dirty bundle=$bundle_root" >&2
if ! ./ops/ios_ops.sh xcode --json >>"$runner_log" 2>&1; then
  printf '%s\n' "Xcode preflight failed" >>"$runner_log"
  write_fallback_verdict "inconclusive" "inconclusive" "65" "Xcode preflight failed" "preflight-failed"
  echo "[ui-evidence] error: Xcode preflight failed; bundle=$bundle_root" >&2
  exit 65
fi
if ! ./ops/ios_ops.sh simulator status --json >>"$runner_log" 2>&1; then
  printf '%s\n' "Simulator preflight failed" >>"$runner_log"
  write_fallback_verdict "inconclusive" "inconclusive" "65" "Simulator preflight failed" "preflight-failed"
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
  --file|--grep) run_args+=("$selector_kind" "$selector_value") ;;
  --method) run_args+=("$selector_value") ;;
esac

printf 'runner=' >>"$command_log"
printf '%q ' ./ops/ios_ops.sh "${run_args[@]}" >>"$command_log"
printf '\n' >>"$command_log"
echo "[ui-evidence] phase=run selector=$selector_kind $selector_value" >&2
set +e
./ops/ios_ops.sh "${run_args[@]}" >"$upstream_stdout" 2>>"$runner_log"
run_rc=$?
set -e

if [[ ! -s "$upstream_stdout" ]] || ! jq -e 'type == "object"' "$upstream_stdout" >/dev/null 2>&1; then
  if [[ -s "$upstream_stdout" ]]; then cp "$upstream_stdout" "$bundle_root/upstream-verdict.raw"; fi
  discover_failure_artifacts
  printf '%s\n' "invalid upstream verdict JSON (runner rc=$run_rc)" >"$bundle_root/helper-error.txt"
  write_fallback_verdict \
    "$(if [[ "$run_rc" -eq 0 ]]; then echo inconclusive; else echo fail; fi)" \
    "$(if [[ "$run_rc" -eq 0 ]]; then echo inconclusive; else echo fail; fi)" \
    "$run_rc" "ios_ops did not emit a JSON object" "invalid-upstream"
  echo "[ui-evidence] error: ios_ops did not emit a JSON object rc=$run_rc bundle=$bundle_root" >&2
  if [[ "$run_rc" -eq 0 ]]; then exit 70; else exit "$run_rc"; fi
fi

upstream_review_root="$(jq -r '.uiVisualReview.reviewRoot // .artifacts.uiReviewRoot // empty' "$upstream_stdout" 2>/dev/null || true)"
upstream_xcresult="$(jq -r '.artifacts.xcresult // empty' "$upstream_stdout" 2>/dev/null || true)"
upstream_contact="$(jq -r '.uiVisualReview.contactSheet // .artifacts.uiContactSheet // empty' "$upstream_stdout" 2>/dev/null || true)"
upstream_quick4="$(jq -r '.uiVisualReview.quick4Sheet // .artifacts.uiQuick4Sheet // empty' "$upstream_stdout" 2>/dev/null || true)"
upstream_manifest="$(jq -r '.uiVisualReview.visualReviewManifest // .artifacts.uiVisualReviewManifest // empty' "$upstream_stdout" 2>/dev/null || true)"
upstream_video="$(jq -r '.uiVisualReview.video // .artifacts.uiVideo // empty' "$upstream_stdout" 2>/dev/null || true)"
upstream_log="$(jq -r '.artifacts.log // empty' "$upstream_stdout" 2>/dev/null || true)"

stable_review_root="$bundle_root/artifacts/ui-review"
review_root_exists=false
if [[ -n "$upstream_review_root" && -d "$upstream_review_root" ]]; then
  mkdir -p "$stable_review_root"
  cp -R "$upstream_review_root/." "$stable_review_root/"
  review_root_exists=true
fi

copy_optional() {
  local source="$1" target="$2"
  mkdir -p "$(dirname "$target")"
  if [[ -n "$source" && -f "$source" ]]; then cp "$source" "$target"; fi
}

stable_review_html="$stable_review_root/UIreview.html"
stable_contact="$stable_review_root/$(basename "${upstream_contact:-contact_sheet.png}")"
stable_quick4="$stable_review_root/$(basename "${upstream_quick4:-quick4_contact_sheet.png}")"
stable_manifest="$stable_review_root/$(basename "${upstream_manifest:-review_manifest.json}")"
stable_video="$stable_review_root/uitest-videos/$(basename "${upstream_video:-uitest.mp4}")"
copy_optional "$upstream_contact" "$stable_contact"
copy_optional "$upstream_quick4" "$stable_quick4"
copy_optional "$upstream_manifest" "$stable_manifest"
copy_optional "$upstream_video" "$stable_video"
if [[ -n "$upstream_log" && -f "$upstream_log" ]]; then cp "$upstream_log" "$stable_log"; elif [[ -s "$runner_log" ]]; then cp "$runner_log" "$stable_log"; else printf '%s\n' "no delegate stderr output" >"$stable_log"; fi

stable_xcresult="$bundle_root/artifacts/Test.xcresult"
xcresult_exists=false
if [[ -n "$upstream_xcresult" && -e "$upstream_xcresult" ]]; then
  cp -R "$upstream_xcresult" "$stable_xcresult"
  xcresult_exists=true
fi
review_html_exists=false; contact_exists=false; quick4_exists=false; manifest_exists=false; video_exists=false
[[ -f "$stable_review_html" ]] && review_html_exists=true
[[ -f "$stable_contact" ]] && contact_exists=true
[[ -f "$stable_quick4" ]] && quick4_exists=true
[[ -f "$stable_manifest" ]] && manifest_exists=true
[[ -f "$stable_video" ]] && video_exists=true

artifact_contract_status="fail"
artifact_contract_reason="visual evidence artifact contract not run"
artifact_contract_json="$bundle_root/artifacts/ui-evidence-contract.json"

current_commit="$(git rev-parse HEAD)"
current_dirty=false
[[ -n "$(git status --porcelain)" ]] && current_dirty=true
upstream_device="$(jq -r '.device // empty' "$upstream_stdout")"

if "$repo_root/.venv/bin/python" --version >/dev/null 2>&1; then
  evidence_python=("$repo_root/.venv/bin/python")
else
  evidence_python=(uv run --python 3.13 python)
fi
if "${evidence_python[@]}" "$repo_root/ops/uitest_evidence_contract.py" validate \
    --screenshot-dir "$stable_review_root" \
    --manifest "$stable_manifest" \
    --contact-sheet "$stable_contact" \
    --quick4-sheet "$stable_quick4" \
    --video "$stable_video" \
    --review-html "$stable_review_html" \
    --source-commit "$source_commit" \
    --dataset-id "$expected_dataset_id" \
    --dataset-sha256 "$expected_dataset_sha256" \
    --device "$upstream_device" >"$artifact_contract_json" 2>&1; then
  artifact_contract_status="pass"
  artifact_contract_reason=""
else
  artifact_contract_status="fail"
  artifact_contract_reason="$(tail -1 "$artifact_contract_json" 2>/dev/null || printf '%s' 'artifact validator failed')"
fi

verdict_filter='(.schema == "kg.ios.run.v1") and (.kind == "test") and (.status == "ok") and (.result == "ok") and ((.exit | tostring) == "0")'
verdict_filter+=' and (((.executed | tostring | tonumber?) // 0) > 0)'
verdict_filter+=' and (.options.sourceCommit == $sourceCommit) and (.options.sourceTreeDirty == false)'
verdict_filter+=' and (.options.datasetID == $datasetID) and (.options.datasetSHA256 == $datasetSHA256)'
verdict_filter+=' and (if (.device | type) == "string" then (.device | test("^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")) else false end)'
verdict_filter+=' and (if (.options.device | type) == "string" then ((.options.device | test("^platform=iOS Simulator(,|$)")) and (.options.device | test("(^|,)id=" + $udid + "(,|$)"))) else false end)'
verdict_filter+=' and (($expectedDevice == "") or ((.device | ascii_downcase) == ($expectedDevice | ascii_downcase)))'
verdict_filter+=' and (.uiVisualReview | type == "object") and (.uiVisualReview.reviewHtmlExists == true)'
verdict_filter+=' and (.uiVisualReview.contactSheetExists == true) and (.uiVisualReview.quick4SheetExists == true)'
verdict_filter+=' and (.uiVisualReview.visualReviewManifestExists == true) and (.uiVisualReview.videoExists == true)'
verdict_filter+=' and (.uiVisualReview.reviewRootExists == true)'

contract_status="runner-failed"
normalized_status="fail"
normalized_result="fail"
normalized_exit="$run_rc"
normalized_reason="upstream runner exited rc=$run_rc"
if [[ "$run_rc" -eq 0 ]]; then
  contract_status="contract-failed"
  normalized_status="inconclusive"
  normalized_result="inconclusive"
  normalized_exit="70"
  normalized_reason="upstream verdict failed evidence contract"
  if jq -e --arg sourceCommit "$source_commit" --arg datasetID "$expected_dataset_id" \
    --arg datasetSHA256 "$expected_dataset_sha256" --arg expectedDevice "$device" --arg udid "$upstream_device" \
    "$verdict_filter" "$upstream_stdout" >/dev/null 2>&1 \
    && [[ "$current_commit" == "$source_commit" && "$current_dirty" == false ]] \
    && [[ "$review_root_exists" == true && "$review_html_exists" == true && "$contact_exists" == true && "$quick4_exists" == true && "$manifest_exists" == true && "$video_exists" == true && "$xcresult_exists" == true ]] \
    && [[ "$artifact_contract_status" == "pass" ]]; then
    contract_status="pass"
    normalized_status="ok"
    normalized_result="ok"
    normalized_exit="0"
    normalized_reason=""
  fi
fi

jq --arg bundle "$bundle_root" --arg commandLog "$command_log" --arg runnerLog "$stable_log" \
  --arg xcresult "$stable_xcresult" --arg reviewRoot "$stable_review_root" --arg reviewHtml "$stable_review_html" \
  --arg contactSheet "$stable_contact" --arg quick4Sheet "$stable_quick4" --arg manifest "$stable_manifest" \
  --arg video "$stable_video" --arg selector "$selector_kind $selector_value" --arg contractStatus "$contract_status" \
  --arg normalizedStatus "$normalized_status" --arg normalizedResult "$normalized_result" --arg normalizedExit "$normalized_exit" \
  --arg normalizedReason "$normalized_reason" --arg upstreamPath "$upstream_stdout" --arg runnerExit "$run_rc" \
  --arg artifactContractStatus "$artifact_contract_status" --arg artifactContractReason "$artifact_contract_reason" --arg artifactContract "$artifact_contract_json" \
  --argjson reviewRootExists "$review_root_exists" --argjson reviewHtmlExists "$review_html_exists" \
  --argjson contactExists "$contact_exists" --argjson quick4Exists "$quick4_exists" --argjson manifestExists "$manifest_exists" \
  --argjson videoExists "$video_exists" --argjson xcresultExists "$xcresult_exists" \
  '.upstreamStatus = {status:(.status // null),result:(.result // null),exit:(.exit // null),reason:(.reason // null),executed:(.executed // null)}
   | .upstreamArtifacts = (.artifacts // {})
   | .upstreamUiVisualReview = (.uiVisualReview // null)
   | .status = $normalizedStatus | .result = $normalizedResult | .exit = $normalizedExit | .reason = $normalizedReason
   | .artifacts = {log:$runnerLog,logExists:true,xcresult:(if $xcresultExists then $xcresult else null end),xcresultExists:$xcresultExists,
       uiContactSheet:(if $contactExists then $contactSheet else null end),uiContactSheetExists:$contactExists,
       uiQuick4Sheet:(if $quick4Exists then $quick4Sheet else null end),uiQuick4SheetExists:$quick4Exists,
       uiVisualReviewManifest:(if $manifestExists then $manifest else null end),uiVisualReviewManifestExists:$manifestExists,
       uiScreenshotDir:(if $reviewRootExists then $reviewRoot else null end),uiVideo:(if $videoExists then $video else null end),uiVideoExists:$videoExists,
       uiReviewRoot:(if $reviewRootExists then $reviewRoot else null end),uiReviewRootExists:$reviewRootExists,
       uiReviewHtml:(if $reviewHtmlExists then $reviewHtml else null end),uiReviewHtmlExists:$reviewHtmlExists}
   | .uiVisualReview = {screenshotDir:(if $reviewRootExists then $reviewRoot else null end),contactSheet:(if $contactExists then $contactSheet else null end),contactSheetExists:$contactExists,
       quick4Sheet:(if $quick4Exists then $quick4Sheet else null end),quick4SheetExists:$quick4Exists,visualReviewManifest:(if $manifestExists then $manifest else null end),visualReviewManifestExists:$manifestExists,
       video:(if $videoExists then $video else null end),videoExists:$videoExists,reviewRoot:(if $reviewRootExists then $reviewRoot else null end),reviewRootExists:$reviewRootExists,
       reviewHtml:(if $reviewHtmlExists then $reviewHtml else null end),reviewHtmlExists:$reviewHtmlExists}
   | .helper = {schema:"kg.ios.ui-evidence.v1",bundleRoot:$bundle,commandLog:$commandLog,selector:$selector,retention:"stable-per-run-bundle",contractStatus:$contractStatus,artifactContractStatus:$artifactContractStatus,artifactContractReason:(if $artifactContractReason == "" then null else $artifactContractReason end),artifactContract:$artifactContract,runnerExit:$runnerExit,upstreamVerdict:$upstreamPath,normalizedVerdict:($bundle + "/verdict.json")}' \
  "$upstream_stdout" >"$normalized_verdict"
if [[ -n "$json_out" ]]; then
  json_parent="$(dirname "$json_out")"
  mkdir -p "$json_parent"
  cp "$normalized_verdict" "$json_out"
fi

jq -r '
  "[ui-evidence] verdict=\(.status // .result // "unknown") exit=\(.exit // "unknown") reason=\(.reason // "")",
  "[ui-evidence] source=\(.options.sourceCommit // "unknown") dirty=\(if (.options | has("sourceTreeDirty")) then .options.sourceTreeDirty else "unknown" end) dataset=\(.options.datasetID // "unknown") device=\(.device // "unknown")",
  "[ui-evidence] contract=\(.helper.contractStatus)",
  "[ui-evidence] bundle=\(.helper.bundleRoot)",
  "[ui-evidence] log=\(.artifacts.log)",
  "[ui-evidence] xcresult=\(.artifacts.xcresult)",
  "[ui-evidence] uiReview=\(.artifacts.uiReviewHtml)",
  "[ui-evidence] contactSheet=\(.artifacts.uiContactSheet)",
  "[ui-evidence] video=\(.artifacts.uiVideo)"
' "$normalized_verdict" >&2

if [[ "$run_rc" -ne 0 ]]; then exit "$run_rc"; fi
if [[ "$contract_status" != "pass" ]]; then exit 70; fi
exit 0
