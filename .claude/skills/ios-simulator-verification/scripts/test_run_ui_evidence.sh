#!/usr/bin/env bash
set -euo pipefail

skill_root="$(cd "$(dirname "$0")/.." && pwd)"
helper="$skill_root/scripts/run_ui_evidence.sh"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/kg-ui-evidence-contract.XXXXXX")"
trap 'rm -rf "$tmp_root"' EXIT

repo="$tmp_root/repo"
mkdir -p "$repo/ops/fixtures/ui_worlds" "$repo/.claude/skills/ios-simulator-verification/scripts"
source_ops="$skill_root/../../../ops"
for source_file in "$source_ops"/uitest_*.py; do
  [[ "$(basename "$source_file")" == "uitest_evidence_contract.py" ]] && continue
  cp "$source_file" "$repo/ops/"
done
cp "$helper" "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh"
chmod +x "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh"
feature_helper="$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh"
printf '%s\n' '{"datasetID":"marketing_demo"}' >"$repo/ops/fixtures/ui_worlds/marketing_demo.json"
printf '%s\n' '{"datasetID":"marketing_demo"}' >"$tmp_root/outside-dataset.json"
ln -s "$tmp_root/outside-dataset.json" "$repo/ops/fixtures/ui_worlds/escaped.json"
printf '%s\n' $'build/\nops/__pycache__/' >"$repo/.gitignore"
cat >"$repo/ops/ui_world_manifest.py" <<'EOF'
#!/usr/bin/env bash
[[ "${1:-}" == validate ]] && { echo marketing_demo; exit 0; }
exit 1
EOF
chmod +x "$repo/ops/ui_world_manifest.py"
cat >"$repo/ops/ios_ops.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  xcode) printf '%s\n' '{"status":"ok"}' ;;
  simulator) printf '%s\n' '{"status":"ok"}' ;;
  test)
    if [[ "${FAKE_MODE:-ok}" == lease-exhausted ]]; then
      printf '%s\n' '[ios_test] error: --lease requested but simulator pool is exhausted' >&2
      exit 1
    fi
    mkdir -p "$FAKE_ROOT/build"
    printf '%s\n' "$@" >"$FAKE_ROOT/build/test-args"
    fake_selector="${KG_UI_TEST_EXACT_SELECTOR:-}"
    fake_args=("$@")
    for ((fake_index = 0; fake_index < ${#fake_args[@]} - 1; fake_index++)); do
      case "${fake_args[$fake_index]}" in
        --method|--grep|--file) fake_selector="${fake_args[$fake_index]} ${fake_args[$((fake_index + 1))]}"; break ;;
      esac
    done
    fake_artifacts="$FAKE_ROOT/build/upstream"
    ui_root="$fake_artifacts/ui-review"
    mkdir -p "$ui_root/uitest-videos" "$fake_artifacts/Test.xcresult"
    printf '%s\n' '<html>KG UITest Run Review</html>' >"$ui_root/UIreview.html"
    printf '%s\n' 'log' >"$ui_root/missing.log"
    printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=' | base64 -D >"$ui_root/step-1.png"
    cp "$ui_root/step-1.png" "$ui_root/contact_sheet.png"
    cp "$ui_root/step-1.png" "$ui_root/quick4_contact_sheet.png"
    png_size="$(wc -c <"$ui_root/step-1.png" | tr -d ' ')"
    png_sha="$(shasum -a 256 "$ui_root/step-1.png" | awk '{print $1}')"
    jq -n --arg commit "$FAKE_COMMIT" --arg sha "$FAKE_DATASET_SHA256" --arg device "$FAKE_DEVICE" \
      --arg selector "$fake_selector" --arg size "$png_size" --arg pngSha "$png_sha" \
      '{schema:"kg.visual-review.sheet.v1",source:"uitest",provenance:{sourceCommit:$commit,datasetID:"marketing_demo",datasetSHA256:$sha,device:$device,selector:$selector},items:[{assetID:"step-1",relPath:"step-1.png",stateLabel:"settings-loaded",width:1,height:1,byteSize:($size|tonumber),sha256:$pngSha}]}' \
      >"$ui_root/review_manifest.json"
    if [[ "${FAKE_MODE:-ok}" == legacy-manifest ]]; then
      jq 'del(.provenance) | .items |= map(del(.byteSize, .sha256))' \
        "$ui_root/review_manifest.json" >"$ui_root/review_manifest.legacy.json"
      mv "$ui_root/review_manifest.legacy.json" "$ui_root/review_manifest.json"
    fi
    printf '%s\n' 'video' >"$ui_root/uitest-videos/run.mp4"
    video_sha="$(shasum -a 256 "$ui_root/uitest-videos/run.mp4" | awk '{print $1}')"
    video_run_id="$(basename "$ui_root")"
    if [[ "${FAKE_MODE:-ok}" == invalid-json ]]; then
      printf '%s\n' "[ios_test] log=$ui_root/missing.log xcresult=$fake_artifacts/Test.xcresult" >&2
      printf '%s\n' "[ios_test][ui-review] html=$ui_root/UIreview.html" >&2
      printf '%s\n' "[ios_test][ui-steps] contactSheet=$ui_root/contact_sheet.png" >&2
      printf '%s\n' "[ios_test][ui-steps] quick4=$ui_root/quick4_contact_sheet.png" >&2
      printf '%s\n' "[ios_test][ui-review] visualReviewManifest=$ui_root/review_manifest.json" >&2
      printf '%s\n' "[ios_test][ui-video] archived $ui_root/uitest-videos/run.mp4" >&2
      printf '%s\n' 'not-json'
      exit 65
    fi
    if [[ "${FAKE_MODE:-ok}" == missing ]]; then
      jq -n --arg device "$FAKE_DEVICE" '{schema:"kg.ios.run.v1",kind:"test",status:"missing",result:"missing",exit:"0",reason:null,executed:"0",options:{sourceCommit:$ENV.FAKE_COMMIT,sourceTreeDirty:false,datasetID:"marketing_demo",datasetSHA256:$ENV.FAKE_DATASET_SHA256,device:("platform=iOS Simulator,id=" + $device)},device:$device,uiVisualReview:null,artifacts:{}}'
      exit 0
    fi
    output_device="$FAKE_DEVICE"
    [[ "${FAKE_MODE:-ok}" == wrong-device ]] && output_device="11111111-1111-1111-1111-111111111111"
    destination="platform=iOS Simulator,id=$output_device"
    [[ "${FAKE_MODE:-ok}" == malformed-destination ]] && destination="platform=iOS Simulator,id=$output_device-evil"
    [[ "${FAKE_MODE:-ok}" == missing-artifact ]] && rm -f "$ui_root/contact_sheet.png"
    jq -n --arg commit "$FAKE_COMMIT" --arg sha "$FAKE_DATASET_SHA256" --arg device "$output_device" --arg root "$ui_root" --arg xc "$fake_artifacts/Test.xcresult" \
      --arg destination "$destination" --arg mode "${FAKE_MODE:-ok}" --arg videoRunID "$video_run_id" --arg videoSha "$video_sha" \
      '{schema:"kg.ios.run.v1",kind:"test",status:(if $mode == "nonzero" then "fail" else "ok" end),result:(if $mode == "nonzero" then "fail" else "ok" end),exit:(if $mode == "nonzero" then "65" else "0" end),reason:(if $mode == "nonzero" then "synthetic runner failure" else null end),executed:"1",options:{sourceCommit:$commit,sourceTreeDirty:false,datasetID:"marketing_demo",datasetSHA256:$sha,device:$destination},device:$device,uiVisualReview:{reviewRoot:$root,reviewRootExists:true,reviewHtml:($root + "/UIreview.html"),reviewHtmlExists:true,contactSheet:($root + "/contact_sheet.png"),contactSheetExists:true,quick4Sheet:($root + "/quick4_contact_sheet.png"),quick4SheetExists:true,visualReviewManifest:($root + "/review_manifest.json"),visualReviewManifestExists:true,video:($root + "/uitest-videos/run.mp4"),videoExists:true,videoIdentity:{runID:$videoRunID,file:"run.mp4",sha256:$videoSha}},artifacts:{log:($root + "/missing.log"),xcresult:$xc,uiVideoIdentity:{runID:$videoRunID,file:"run.mp4",sha256:$videoSha}}}'
    if [[ "${FAKE_MODE:-ok}" == nonzero ]]; then exit 65; fi
    ;;
  *) exit 64 ;;
esac
EOF
chmod +x "$repo/ops/ios_ops.sh"

git -C "$repo" init -q
git -C "$repo" config user.name "UI Evidence Contract"
git -C "$repo" config user.email "ui-evidence@example.test"
git -C "$repo" add .
git -C "$repo" commit -q -m "fixture"
[[ -z "$(git -C "$repo" status --porcelain)" ]] || { git -C "$repo" status --short >&2; exit 1; }

fake_commit="$(git -C "$repo" rev-parse HEAD)"
fake_device="43FA3E1B-16F8-4144-B17D-53D5E4728FC6"
fake_sha="$(shasum -a 256 "$repo/ops/fixtures/ui_worlds/marketing_demo.json" | awk '{print $1}')"
export FAKE_ROOT="$repo" FAKE_COMMIT="$fake_commit" FAKE_DEVICE="$fake_device" FAKE_DATASET_SHA256="$fake_sha"

set +e
missing_tool_json="$tmp_root/missing-tool.json"
(cd "$repo" && "$feature_helper" \
  --dataset marketing_demo --lease --method SettingsFlowUITests/testSettingsFlow --json-out "$missing_tool_json" \
  >"$tmp_root/missing-tool.out" 2>&1)
missing_tool_rc=$?
set -e
[[ "$missing_tool_rc" -eq 70 ]]
grep -Fq -- 'missing canonical evidence validator' "$tmp_root/missing-tool.out"
test ! -e "$repo/ops/uitest_evidence_contract.py"
jq -e --arg source "$repo" --arg helper "$feature_helper" '
  .status == "inconclusive"
  and .exit == "70"
  and .helper.contractStatus == "tool-missing"
  and (.reason | contains("missing canonical evidence validator"))
  and (.helper.validator | endswith("/ops/uitest_evidence_contract.py"))
  and .helper.toolRoot != $source
  and .helper.commandLog != null
' "$missing_tool_json" >/dev/null

# The source fixture intentionally has no validator. The helper itself is the
# canonical control-plane entrypoint and must resolve its validator from the
# repository that owns the skill, not from the feature worktree under test.
runner="$helper"

lease_exhausted_json="$tmp_root/lease-exhausted.json"
set +e
(cd "$repo" && FAKE_MODE=lease-exhausted "$runner" \
  --dataset marketing_demo --lease --method SettingsFlowUITests/testSettingsFlow --json-out "$lease_exhausted_json" \
  >"$tmp_root/lease-exhausted.out" 2>&1)
lease_exhausted_rc=$?
set -e
[[ "$lease_exhausted_rc" -eq 65 ]]
lease_exhausted_bundle="$(jq -er '.helper.bundleRoot' "$lease_exhausted_json")"
grep -Fq -- '--lease requested but simulator pool is exhausted' \
  "$lease_exhausted_bundle/artifacts/delegate.stderr.log"
grep -Fq -- '--device <UDID>' "$tmp_root/lease-exhausted.out"
test -f "$lease_exhausted_bundle/run-manifest.json"
test -f "$lease_exhausted_bundle/command.txt"
jq -e '
  .status == "inconclusive"
  and .result == "inconclusive"
  and .exit == "65"
  and (.reason | contains("pool exhausted"))
  and (.reason | contains("--device <UDID>"))
  and .helper.contractStatus == "lease-exhausted"
  and (.helper.recoveryHint | contains("--device <UDID>"))
' "$lease_exhausted_json" >/dev/null

set +e
(cd "$repo" && "$runner" \
  --dataset-file ops/fixtures/ui_worlds/escaped.json --lease --method SettingsFlowUITests/testSettingsFlow \
  >"$tmp_root/escaped-dataset.out" 2>&1)
escaped_dataset_rc=$?
set -e
[[ "$escaped_dataset_rc" -eq 65 ]]
grep -Fq -- 'must resolve inside this KG worktree' "$tmp_root/escaped-dataset.out"

legacy_json="$tmp_root/legacy-manifest.json"
set +e
(cd "$repo" && FAKE_MODE=legacy-manifest "$runner" \
  --dataset marketing_demo --lease --method SettingsFlowUITests/testSettingsFlow --json-out "$legacy_json" \
  >"$tmp_root/legacy-manifest.out" 2>&1)
legacy_rc=$?
set -e
if [[ "$legacy_rc" -ne 0 ]]; then
  cat "$tmp_root/legacy-manifest.out" >&2
  exit "$legacy_rc"
fi
legacy_bundle="$(jq -er '.helper.bundleRoot' "$legacy_json")"
jq -e '
  (.helper.contractStatus == "pass")
  and (.artifacts.uiVisualReviewManifest | endswith("/review_manifest.json"))
' "$legacy_json" >/dev/null
if ! jq -e --arg fakeCommit "$FAKE_COMMIT" --arg fakeDevice "$FAKE_DEVICE" '
  .items[0].byteSize > 0
  and (.items[0].sha256 | length) == 64
  and .provenance.sourceCommit == $fakeCommit
  and .provenance.device == $fakeDevice
' "$legacy_bundle/artifacts/ui-review/review_manifest.json" >/dev/null; then
  cat "$legacy_bundle/artifacts/ui-review/review_manifest.json" >&2
  cat "$legacy_bundle/artifacts/ui-evidence-contract.json" >&2
  exit 1
fi

json_out="$tmp_root/success.json"
set +e
(cd "$repo" && "$runner" \
  --dataset marketing_demo --lease --method SettingsFlowUITests/testSettingsFlow --json-out "$json_out" \
  >"$tmp_root/success.out" 2>&1)
success_rc=$?
set -e
if [[ "$success_rc" -ne 0 ]]; then
  cat "$tmp_root/success.out" >&2
  if [[ -s "$json_out" ]]; then
    bundle_debug="$(jq -r '.helper.bundleRoot // empty' "$json_out" 2>/dev/null || true)"
    [[ -n "$bundle_debug" && -f "$bundle_debug/artifacts/ui-evidence-contract.json" ]] && cat "$bundle_debug/artifacts/ui-evidence-contract.json" >&2
  fi
  exit "$success_rc"
fi

bundle="$(jq -er '.helper.bundleRoot' "$json_out")"
jq -e --arg sourceCommit "$fake_commit" --arg datasetSha "$fake_sha" --arg device "$fake_device" --arg bundle "$bundle" '
  def stable_path: . != null and startswith($bundle + "/");
  .helper.schema == "kg.ios.ui-evidence.v1"
  and .options.sourceCommit == $sourceCommit
  and .options.sourceTreeDirty == false
  and .options.datasetID == "marketing_demo"
  and .options.datasetSHA256 == $datasetSha
  and .device == $device
  and (.options.device | contains($device))
  and .executed == "1"
  and .helper.contractStatus == "pass"
  and .helper.toolResolution == "helper-skill-repo"
  and (.helper.validator | endswith("/ops/uitest_evidence_contract.py"))
  and .helper.artifactContract == ($bundle + "/artifacts/ui-evidence-contract.json")
  and .uiVisualReview.reviewHtmlExists == true
  and .uiVisualReview.contactSheetExists == true
  and .uiVisualReview.quick4SheetExists == true
  and .uiVisualReview.visualReviewManifestExists == true
  and .uiVisualReview.videoExists == true
  and ([
    .artifacts.log, .artifacts.xcresult, .artifacts.uiContactSheet,
    .artifacts.uiQuick4Sheet, .artifacts.uiVisualReviewManifest,
    .artifacts.uiScreenshotDir, .artifacts.uiVideo, .artifacts.uiReviewRoot,
    .artifacts.uiReviewHtml, .uiVisualReview.screenshotDir,
    .uiVisualReview.contactSheet, .uiVisualReview.quick4Sheet,
    .uiVisualReview.visualReviewManifest, .uiVisualReview.video,
    .uiVisualReview.reviewRoot, .uiVisualReview.reviewHtml
  ] | all(stable_path))
' "$json_out" >/dev/null
test -f "$bundle/verdict.json"
test -f "$bundle/upstream-verdict.json"
test -f "$bundle/delegate.stderr.log"
test -f "$bundle/artifacts/ui-review/UIreview.html"
test -d "$bundle/artifacts/Test.xcresult"
contract="$bundle/artifacts/ui-evidence-contract.json"
test -f "$contract"
step_png="$bundle/artifacts/ui-review/step-1.png"
video="$bundle/artifacts/ui-review/uitest-videos/run.mp4"
review_html="$bundle/artifacts/ui-review/UIreview.html"
png_size="$(wc -c <"$step_png" | tr -d ' ')"
png_sha="$(shasum -a 256 "$step_png" | awk '{print $1}')"
video_size="$(wc -c <"$video" | tr -d ' ')"
video_sha="$(shasum -a 256 "$video" | awk '{print $1}')"
review_html_sha="$(shasum -a 256 "$review_html" | awk '{print $1}')"
jq -e --arg pngSha "$png_sha" --argjson pngBytes "$png_size" \
  --arg videoSha "$video_sha" --argjson videoBytes "$video_size" \
  --arg reviewHtmlSha "$review_html_sha" '
  .schema == "kg.ios.ui-evidence-contract.v1"
  and .valid == true
  and .stepCount == 1
  and .stepSha256 == [$pngSha]
  and .contactSheet.sha256 == $pngSha
  and .contactSheet.byteSize == $pngBytes
  and .quick4Sheet.sha256 == $pngSha
  and .quick4Sheet.byteSize == $pngBytes
  and .videoByteSize == $videoBytes
  and .videoSha256 == $videoSha
  and .reviewHtmlSha256 == $reviewHtmlSha
  and .provenance.sourceCommit == $ENV.FAKE_COMMIT
  and .provenance.datasetSHA256 == $ENV.FAKE_DATASET_SHA256
  and .provenance.device == $ENV.FAKE_DEVICE
' "$contract" >/dev/null
grep -Fq 'SettingsFlowUITests/testSettingsFlow' "$repo/build/test-args"
! grep -Fq -- '--method' "$repo/build/test-args"

forwarded_out="$tmp_root/forwarded.json"
set +e
(cd "$repo" && "$runner" \
  --dataset-file ops/fixtures/ui_worlds/marketing_demo.json --lease --grep SettingsFlow \
  --configuration Release --ui-launch-profile standard --build-lock-timeout 123 --json-out "$forwarded_out" \
  >"$tmp_root/forwarded.out" 2>&1)
forwarded_rc=$?
set -e
if [[ "$forwarded_rc" -ne 0 ]]; then
  cat "$tmp_root/forwarded.out" >&2
  git -C "$repo" status --short >&2 || true
  if [[ -s "$forwarded_out" ]]; then
    bundle_debug="$(jq -r '.helper.bundleRoot // empty' "$forwarded_out" 2>/dev/null || true)"
    [[ -n "$bundle_debug" && -f "$bundle_debug/artifacts/ui-evidence-contract.json" ]] && cat "$bundle_debug/artifacts/ui-evidence-contract.json" >&2
  fi
  exit "$forwarded_rc"
fi
jq -e '.helper.contractStatus == "pass"' "$forwarded_out" >/dev/null
grep -Fq -- '--dataset-file' "$repo/build/test-args"
grep -Fq -- '--grep' "$repo/build/test-args"
grep -Fq -- 'SettingsFlow' "$repo/build/test-args"
grep -Fq -- '--configuration' "$repo/build/test-args"
grep -Fq -- 'Release' "$repo/build/test-args"
grep -Fq -- '--ui-launch-profile' "$repo/build/test-args"
grep -Fq -- 'standard' "$repo/build/test-args"
grep -Fq -- '--timeout' "$repo/build/test-args"
grep -Fq -- '123' "$repo/build/test-args"

explicit_out="$tmp_root/explicit.json"
(cd "$repo" && "$runner" \
  --dataset marketing_demo --device "$fake_device" --file SettingsFlowUITests.swift --json-out "$explicit_out" \
  >"$tmp_root/explicit.out" 2>&1)
jq -e '.helper.contractStatus == "pass" and .device == "43FA3E1B-16F8-4144-B17D-53D5E4728FC6"' "$explicit_out" >/dev/null

set +e
(cd "$repo" && FAKE_MODE=nonzero "$runner" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift --json-out "$tmp_root/nonzero.json" >"$tmp_root/nonzero.out" 2>&1)
nonzero_rc=$?
(cd "$repo" && FAKE_MODE=invalid-json "$runner" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift --json-out "$tmp_root/invalid.json" >"$tmp_root/invalid.out" 2>&1)
invalid_rc=$?
(cd "$repo" && FAKE_MODE=malformed-destination "$runner" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift >"$tmp_root/malformed.out" 2>&1)
malformed_rc=$?
(cd "$repo" && FAKE_MODE=missing-artifact "$runner" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift >"$tmp_root/artifact.out" 2>&1)
artifact_rc=$?
set -e
[[ "$nonzero_rc" -eq 65 ]]
[[ "$invalid_rc" -eq 65 ]]
[[ "$malformed_rc" -eq 70 ]]
[[ "$artifact_rc" -eq 70 ]]
jq -e '.status == "fail" and .helper.contractStatus == "runner-failed" and .artifacts.logExists == true and .upstreamStatus.exit == "65"' "$tmp_root/nonzero.json" >/dev/null
jq -e '.status == "fail" and .helper.contractStatus == "invalid-upstream" and .artifacts.logExists == true and .artifacts.xcresultExists == true and .uiVisualReview.reviewHtmlExists == true and .uiVisualReview.contactSheetExists == true and .uiVisualReview.quick4SheetExists == true and .uiVisualReview.visualReviewManifestExists == true and .uiVisualReview.videoExists == true' "$tmp_root/invalid.json" >/dev/null
invalid_bundle="$(jq -er '.helper.bundleRoot' "$tmp_root/invalid.json")"
test -f "$invalid_bundle/artifacts/ui-review/UIreview.html"
test -f "$invalid_bundle/artifacts/ui-review/contact_sheet.png"
test -f "$invalid_bundle/artifacts/ui-review/quick4_contact_sheet.png"
test -f "$invalid_bundle/artifacts/ui-review/review_manifest.json"
test -f "$invalid_bundle/artifacts/ui-review/uitest-videos/uitest.mp4"
test -d "$invalid_bundle/artifacts/Test.xcresult"
grep -Fq 'failed evidence contract' "$tmp_root/malformed.out"
grep -Fq 'failed evidence contract' "$tmp_root/artifact.out"

set +e
(cd "$repo" && FAKE_MODE=missing "$runner" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift >"$tmp_root/missing.out" 2>&1)
missing_rc=$?
(cd "$repo" && FAKE_MODE=wrong-device "$runner" \
  --dataset marketing_demo --device "$fake_device" --file SettingsFlowUITests.swift >"$tmp_root/device.out" 2>&1)
device_rc=$?
set -e
[[ "$missing_rc" -eq 70 ]]
[[ "$device_rc" -eq 70 ]]
grep -Fq 'failed evidence contract' "$tmp_root/missing.out"
grep -Fq 'failed evidence contract' "$tmp_root/device.out"

echo "PASS: argument translation, fail-closed verdict, canonical device, and stable retention"
