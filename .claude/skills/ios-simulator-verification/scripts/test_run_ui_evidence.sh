#!/usr/bin/env bash
set -euo pipefail

skill_root="$(cd "$(dirname "$0")/.." && pwd)"
helper="$skill_root/scripts/run_ui_evidence.sh"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/kg-ui-evidence-contract.XXXXXX")"
trap 'rm -rf "$tmp_root"' EXIT

repo="$tmp_root/repo"
mkdir -p "$repo/ops/fixtures/ui_worlds" "$repo/.claude/skills/ios-simulator-verification/scripts"
cp "$helper" "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh"
chmod +x "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh"
printf '%s\n' '{"datasetID":"marketing_demo"}' >"$repo/ops/fixtures/ui_worlds/marketing_demo.json"
printf '%s\n' 'build/' >"$repo/.gitignore"
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
    mkdir -p "$FAKE_ROOT/build"
    printf '%s\n' "$@" >"$FAKE_ROOT/build/test-args"
    fake_artifacts="$FAKE_ROOT/build/upstream"
    ui_root="$fake_artifacts/ui-review"
    mkdir -p "$ui_root/uitest-videos" "$fake_artifacts/Test.xcresult"
    printf '%s\n' '<html>review</html>' >"$ui_root/UIreview.html"
    printf '%s\n' 'log' >"$ui_root/missing.log"
    printf '%s\n' 'png' >"$ui_root/contact_sheet.png"
    printf '%s\n' 'png' >"$ui_root/quick4_contact_sheet.png"
    printf '%s\n' '{}' >"$ui_root/review_manifest.json"
    printf '%s\n' 'video' >"$ui_root/uitest-videos/run.mp4"
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
      --arg destination "$destination" --arg mode "${FAKE_MODE:-ok}" \
      '{schema:"kg.ios.run.v1",kind:"test",status:(if $mode == "nonzero" then "fail" else "ok" end),result:(if $mode == "nonzero" then "fail" else "ok" end),exit:(if $mode == "nonzero" then "65" else "0" end),reason:(if $mode == "nonzero" then "synthetic runner failure" else null end),executed:"1",options:{sourceCommit:$commit,sourceTreeDirty:false,datasetID:"marketing_demo",datasetSHA256:$sha,device:$destination},device:$device,uiVisualReview:{reviewRoot:$root,reviewRootExists:true,reviewHtml:($root + "/UIreview.html"),reviewHtmlExists:true,contactSheet:($root + "/contact_sheet.png"),contactSheetExists:true,quick4Sheet:($root + "/quick4_contact_sheet.png"),quick4SheetExists:true,visualReviewManifest:($root + "/review_manifest.json"),visualReviewManifestExists:true,video:($root + "/uitest-videos/run.mp4"),videoExists:true},artifacts:{log:($root + "/missing.log"),xcresult:$xc}}'
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

json_out="$tmp_root/success.json"
set +e
(cd "$repo" && "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --lease --method SettingsFlowUITests/testSettingsFlow --json-out "$json_out" \
  >"$tmp_root/success.out" 2>&1)
success_rc=$?
set -e
if [[ "$success_rc" -ne 0 ]]; then
  cat "$tmp_root/success.out" >&2
  exit "$success_rc"
fi

jq -e '
  .helper.schema == "kg.ios.ui-evidence.v1"
  and .options.sourceTreeDirty == false
  and .executed == "1"
  and .uiVisualReview.reviewHtmlExists == true
  and .uiVisualReview.contactSheetExists == true
  and .uiVisualReview.quick4SheetExists == true
  and .uiVisualReview.visualReviewManifestExists == true
  and .uiVisualReview.videoExists == true
' "$json_out" >/dev/null
bundle="$(jq -er '.helper.bundleRoot' "$json_out")"
test -f "$bundle/verdict.json"
test -f "$bundle/upstream-verdict.json"
test -f "$bundle/delegate.stderr.log"
test -f "$bundle/artifacts/ui-review/UIreview.html"
test -d "$bundle/artifacts/Test.xcresult"
grep -Fq 'SettingsFlowUITests/testSettingsFlow' "$repo/build/test-args"
! grep -Fq -- '--method' "$repo/build/test-args"

forwarded_out="$tmp_root/forwarded.json"
(cd "$repo" && "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset-file ops/fixtures/ui_worlds/marketing_demo.json --lease --grep SettingsFlow \
  --configuration Release --ui-launch-profile standard --build-lock-timeout 123 --json-out "$forwarded_out" \
  >"$tmp_root/forwarded.out" 2>&1)
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
(cd "$repo" && "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --device "$fake_device" --file SettingsFlowUITests.swift --json-out "$explicit_out" \
  >"$tmp_root/explicit.out" 2>&1)
jq -e '.helper.contractStatus == "pass" and .device == "43FA3E1B-16F8-4144-B17D-53D5E4728FC6"' "$explicit_out" >/dev/null

set +e
(cd "$repo" && FAKE_MODE=nonzero "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift --json-out "$tmp_root/nonzero.json" >"$tmp_root/nonzero.out" 2>&1)
nonzero_rc=$?
(cd "$repo" && FAKE_MODE=invalid-json "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift --json-out "$tmp_root/invalid.json" >"$tmp_root/invalid.out" 2>&1)
invalid_rc=$?
(cd "$repo" && FAKE_MODE=malformed-destination "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift >"$tmp_root/malformed.out" 2>&1)
malformed_rc=$?
(cd "$repo" && FAKE_MODE=missing-artifact "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
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
(cd "$repo" && FAKE_MODE=missing "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --lease --file SettingsFlowUITests.swift >"$tmp_root/missing.out" 2>&1)
missing_rc=$?
(cd "$repo" && FAKE_MODE=wrong-device "$repo/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --dataset marketing_demo --device "$fake_device" --file SettingsFlowUITests.swift >"$tmp_root/device.out" 2>&1)
device_rc=$?
set -e
[[ "$missing_rc" -eq 70 ]]
[[ "$device_rc" -eq 70 ]]
grep -Fq 'failed evidence contract' "$tmp_root/missing.out"
grep -Fq 'failed evidence contract' "$tmp_root/device.out"

echo "PASS: argument translation, fail-closed verdict, canonical device, and stable retention"
