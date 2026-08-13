#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
skill_root="$(cd "$script_dir/.." && pwd -P)"
helper="$script_dir/run_ui_evidence.sh"
repo_root="$(cd "$skill_root/../../.." && pwd -P)"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/kg-ui-evidence-helper.XXXXXX")"
trap 'rm -rf "$tmp_root"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -x "$helper" ]] || fail "missing executable helper: $helper"

help_out="$($helper --help 2>&1)"
for expected in --dataset --dataset-file --file --grep --method --device --lease --json-out; do
  grep -Fq -- "$expected" <<<"$help_out" || fail "help missing $expected"
done
source_repo="$tmp_root/source"
mkdir -p "$source_repo/ops/fixtures/ui_worlds"
printf '%s\n' '{"schema":"kg.fixture.dataset.v2","datasetID":"marketing_demo"}' \
  >"$source_repo/ops/fixtures/ui_worlds/marketing_demo.json"
printf '%s\n' 'build/' >"$source_repo/.gitignore"

cat >"$source_repo/ops/ui_world_manifest.py" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == validate && -f "${2:-}" ]]
EOF
chmod +x "$source_repo/ops/ui_world_manifest.py"

cat >"$source_repo/ops/ios_ops.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  xcode|simulator)
    printf '%s\n' '{"status":"ok"}'
    ;;
  test)
    mkdir -p "$FAKE_ROOT/build"
    printf '%s\n' "$@" >"$FAKE_ROOT/build/runner-args.txt"
    ui_root="$FAKE_ROOT/build/upstream/fake-run-123"
    xcresult="$FAKE_ROOT/build/upstream/Test.xcresult"
    mkdir -p "$ui_root/uitest-videos" "$xcresult"
    printf '%s\n' 'runner log' >"$FAKE_ROOT/build/upstream/test.log"
    printf '%s\n' '<title>KG UITest Run Review</title>' >"$ui_root/UIreview.html"
    printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=' \
      | base64 -D >"$ui_root/01-loaded.png"
    cp "$ui_root/01-loaded.png" "$ui_root/contact_sheet.png"
    cp "$ui_root/01-loaded.png" "$ui_root/quick4_contact_sheet.png"
    printf '%s\n' 'video' >"$ui_root/uitest-videos/flow.mp4"
    video_sha="$(shasum -a 256 "$ui_root/uitest-videos/flow.mp4" | awk '{print $1}')"
    png_bytes="$(wc -c <"$ui_root/01-loaded.png" | tr -d ' ')"
    png_sha="$(shasum -a 256 "$ui_root/01-loaded.png" | awk '{print $1}')"
    jq -n \
      --arg commit "$FAKE_COMMIT" \
      --arg datasetSha "$FAKE_DATASET_SHA256" \
      --arg device "$FAKE_DEVICE" \
      --arg selector "$KG_UI_TEST_EXACT_SELECTOR" \
      --arg pngSha "$png_sha" \
      --argjson pngBytes "$png_bytes" \
      '{
        schema:"kg.visual-review.sheet.v1",
        source:"uitest",
        provenance:{
          sourceCommit:$commit,
          datasetID:"marketing_demo",
          datasetSHA256:$datasetSha,
          device:$device,
          selector:$selector,
          variant:"dataset:marketing_demo"
        },
        items:[{
          assetID:"01-loaded", relPath:"01-loaded.png", stateLabel:"loaded",
          width:1, height:1, byteSize:$pngBytes, sha256:$pngSha
        }]
      }' >"$ui_root/review_manifest.json"

    mode="${FAKE_MODE:-ok}"
    output_device="$FAKE_DEVICE"
    output_video_sha="$video_sha"
    output_video_run_id='fake-run-123'
    [[ "$mode" == wrong-device ]] && output_device='11111111-1111-1111-1111-111111111111'
    [[ "$mode" == wrong-video-identity ]] && output_video_run_id='other-run'
    [[ "$mode" == missing-artifact ]] && rm -f "$ui_root/contact_sheet.png"
    if [[ "$mode" == invalid-json ]]; then
      printf '%s\n' "[ios_test] log=$FAKE_ROOT/build/upstream/test.log xcresult=$xcresult" >&2
      printf '%s\n' "[ios_test][ui-review] html=$ui_root/UIreview.html" >&2
      printf '%s\n' "[ios_test][ui-steps] contactSheet=$ui_root/contact_sheet.png" >&2
      printf '%s\n' "[ios_test][ui-steps] quick4=$ui_root/quick4_contact_sheet.png" >&2
      printf '%s\n' "[ios_test][ui-review] visualReviewManifest=$ui_root/review_manifest.json" >&2
      printf '%s\n' "[ios_test][ui-video] archived $ui_root/uitest-videos/flow.mp4" >&2
      printf '%s\n' 'not-json'
      exit 65
    fi

    jq -n \
      --arg commit "$FAKE_COMMIT" \
      --arg datasetSha "$FAKE_DATASET_SHA256" \
      --arg device "$output_device" \
      --arg root "$ui_root" \
      --arg log "$FAKE_ROOT/build/upstream/test.log" \
      --arg xcresult "$xcresult" \
      --arg mode "$mode" \
      --arg videoSha "$output_video_sha" \
      --arg videoRunID "$output_video_run_id" \
      '{
        schema:"kg.ios.run.v1", kind:"test",
        status:(if $mode == "runner-fail" then "fail" else "ok" end),
        result:(if $mode == "runner-fail" then "fail" else "ok" end),
        exit:(if $mode == "runner-fail" then "65" else "0" end),
        reason:(if $mode == "runner-fail" then "synthetic failure" else null end),
        executed:(if $mode == "zero-executed" then "0" else "1" end),
        options:{
          sourceCommit:$commit, sourceTreeDirty:false,
          datasetID:"marketing_demo", datasetSHA256:$datasetSha,
          device:("platform=iOS Simulator,id=" + $device)
        },
        device:$device,
        artifacts:{
          log:$log, xcresult:$xcresult,
          uiVideoIdentity:{runID:$videoRunID,file:"flow.mp4",sha256:$videoSha}
        },
        uiVisualReview:{
          screenshotDir:$root,
          contactSheet:($root + "/contact_sheet.png"), contactSheetExists:true,
          quick4Sheet:($root + "/quick4_contact_sheet.png"), quick4SheetExists:true,
          visualReviewManifest:($root + "/review_manifest.json"), visualReviewManifestExists:true,
          video:($root + "/uitest-videos/flow.mp4"), videoExists:true,
          videoIdentity:{runID:$videoRunID,file:"flow.mp4",sha256:$videoSha},
          reviewRoot:$root, reviewRootExists:true,
          reviewHtml:($root + "/UIreview.html"), reviewHtmlExists:true
        }
      }'
    [[ "$mode" != runner-fail ]] || exit 65
    ;;
  *) exit 64 ;;
esac
EOF
chmod +x "$source_repo/ops/ios_ops.sh"

git -C "$source_repo" init -q
git -C "$source_repo" config user.name 'UI Evidence Test'
git -C "$source_repo" config user.email 'ui-evidence@example.test'
git -C "$source_repo" add .
git -C "$source_repo" commit -q -m fixture

fake_commit="$(git -C "$source_repo" rev-parse HEAD)"
fake_device='43FA3E1B-16F8-4144-B17D-53D5E4728FC6'
fake_dataset_sha="$(shasum -a 256 "$source_repo/ops/fixtures/ui_worlds/marketing_demo.json" | awk '{print $1}')"
export FAKE_ROOT="$source_repo" FAKE_COMMIT="$fake_commit" FAKE_DEVICE="$fake_device" FAKE_DATASET_SHA256="$fake_dataset_sha"

success_json="$tmp_root/success.json"
(cd "$source_repo" && "$helper" \
  --dataset marketing_demo \
  --method SettingsFlowUITests/testSettingsFlow \
  --json-out "$success_json" >"$tmp_root/success.out" 2>&1)

bundle="$(jq -er '.helper.bundleRoot' "$success_json")"
jq -e \
  --arg bundle "$bundle" \
  --arg commit "$fake_commit" \
  --arg datasetSha "$fake_dataset_sha" \
  --arg device "$fake_device" '
  def under_bundle: type == "string" and startswith($bundle + "/");
  .schema == "kg.ios.run.v1"
  and .status == "ok" and .result == "ok" and .exit == "0"
  and .options.sourceCommit == $commit
  and .options.sourceTreeDirty == false
  and .options.datasetID == "marketing_demo"
  and .options.datasetSHA256 == $datasetSha
  and .device == $device
  and .helper.schema == "kg.ios.ui-evidence.v1"
  and .helper.contractStatus == "pass"
  and .helper.artifactContractStatus == "pass"
  and (.helper.artifactContract | under_bundle)
  and (.helper.normalizedVerdict | under_bundle)
  and (.artifacts.log | under_bundle)
  and (.artifacts.xcresult | under_bundle)
  and (.uiVisualReview.reviewRoot | under_bundle)
  and .artifacts.uiVideoIdentity == {runID:"fake-run-123",file:"flow.mp4",sha256:.artifacts.uiVideoIdentity.sha256}
  and .uiVisualReview.videoIdentity == .artifacts.uiVideoIdentity
' "$success_json" >/dev/null

contract="$bundle/artifacts/ui-evidence-contract.json"
jq -e '
  .schema == "kg.ios.ui-evidence-contract.v1"
  and .valid == true
  and .stepCount == 1
  and (.bundleSHA256 | test("^[0-9a-f]{64}$"))
  and (.videoSha256 | test("^[0-9a-f]{64}$"))
  and .videoIdentity.runID == "fake-run-123"
  and .videoIdentity.file == "flow.mp4"
  and .videoIdentity.sha256 == .videoSha256
  and (.reviewHtmlSha256 | test("^[0-9a-f]{64}$"))
' "$contract" >/dev/null
test -f "$bundle/verdict.json"
test -f "$bundle/upstream-verdict.json"
test -f "$bundle/delegate.stderr.log"
test -d "$bundle/artifacts/Test.xcresult"
grep -Fxq -- 'SettingsFlowUITests/testSettingsFlow' "$source_repo/build/runner-args.txt"
! grep -Fxq -- '--method' "$source_repo/build/runner-args.txt"

for mode in zero-executed wrong-device missing-artifact wrong-video-identity; do
  set +e
  (cd "$source_repo" && FAKE_MODE="$mode" "$helper" \
    --dataset marketing_demo --method SettingsFlowUITests/testSettingsFlow \
    --json-out "$tmp_root/$mode.json" >"$tmp_root/$mode.out" 2>&1)
  rc=$?
  set -e
  [[ "$rc" -eq 70 ]] || fail "$mode expected rc=70, got $rc"
  jq -e '.status == "inconclusive" and .helper.contractStatus == "contract-failed"' \
    "$tmp_root/$mode.json" >/dev/null
  if [[ "$mode" == missing-artifact ]]; then
    jq -e '.uiVisualReview.contactSheet == null and .uiVisualReview.contactSheetExists == false' \
      "$tmp_root/$mode.json" >/dev/null
  fi
done

set +e
(cd "$source_repo" && FAKE_MODE=runner-fail "$helper" \
  --dataset marketing_demo --method SettingsFlowUITests/testSettingsFlow \
  --json-out "$tmp_root/runner-fail.json" >"$tmp_root/runner-fail.out" 2>&1)
runner_fail_rc=$?
(cd "$source_repo" && FAKE_MODE=invalid-json "$helper" \
  --dataset marketing_demo --method SettingsFlowUITests/testSettingsFlow \
  --json-out "$tmp_root/invalid-json.json" >"$tmp_root/invalid-json.out" 2>&1)
invalid_json_rc=$?
set -e
[[ "$runner_fail_rc" -eq 65 ]] || fail "runner failure rc drifted: $runner_fail_rc"
[[ "$invalid_json_rc" -eq 65 ]] || fail "invalid JSON rc drifted: $invalid_json_rc"
jq -e '.status == "fail" and .helper.contractStatus == "runner-failed"' "$tmp_root/runner-fail.json" >/dev/null
jq -e '
  .status == "fail"
  and .helper.contractStatus == "invalid-upstream"
  and .uiVisualReview.reviewHtmlExists == true
  and .uiVisualReview.videoExists == true
' "$tmp_root/invalid-json.json" >/dev/null
! find "$source_repo/build/snapshots/uitest-evidence" -name '.verdict.json.tmp' -print -quit | grep -q .
! find "$tmp_root" -name '.ui-evidence-verdict.*' -print -quit | grep -q .

echo "PASS: run_ui_evidence helper contract"
