# iOS UI evidence contract

## Verdict identity

`ops/ios_test.sh --json` emits `kg.ios.run-verdict.v1`; the helper writes a normalized copy with `helper.schema=kg.ios.ui-evidence.v1` into a stable per-run bundle. Treat these fields as the minimum identity tuple:

| Field | Meaning | Required reading |
|---|---|---|
| `status` / `result` | `ok`, `fail`, or `inconclusive` | Never infer from process launch |
| `exit` / `reason` | process classification | `1` and `65` mean different failures |
| `options.sourceCommit` | source provenance | Bind screenshots to this commit |
| `options.sourceTreeDirty` | uncommitted source state | Dirty evidence is not a release claim |
| `options.datasetID` / `datasetSHA256` | UI World provenance | Prevent fixture drift |
| `device` | resolved Simulator UDID | Required for parallel-run attribution |
| `artifacts.log` / `xcresult` | raw diagnostics | Normalized paths must point inside the stable bundle and exist |
| `artifacts.uiReviewHtml` | navigable visual review | Preferred human entrypoint |
| `artifacts.uiContactSheet` / `uiQuick4Sheet` | screenshot overview | Inspect, do not merely archive |
| `artifacts.uiVideo` | full interaction recording | Use when timing or transition matters |

The runner also records timings such as `deviceRunLockWaitMs`, `buildForTestingMs`, `testBodyMs`, and `totalMs`. A high lock wait is queueing evidence, not app slowness.

## Helper success gate

`run_ui_evidence.sh` is fail-closed. It returns `0` only when all of these hold:

- `schema=kg.ios.run-verdict.v1`, `kind=test`, `status=result=ok`, `exit=0`, and `executed > 0`;
- `options.sourceCommit` equals the preflight HEAD and `options.sourceTreeDirty=false`;
- `options.datasetID` and `datasetSHA256` equal the validated local UI World;
- top-level `device` is a UUID and agrees with the `id=` in `options.device`; explicit `--device` must match it;
- `uiVisualReview.reviewHtml`, contact sheet, quick4 sheet, manifest, video and review root all exist;
- normalized log, xcresult and visual artifacts are copied under `build/snapshots/uitest-evidence/<run>/`.

The helper keeps `upstream-verdict.json`, the delegate stderr log, command metadata and every upstream artifact that still exists in the complete UI review directory even when the upstream runner's temporary paths are removed. For a non-zero runner it still emits a normalized `status=fail` verdict; for invalid JSON or a zero-exit contract violation it emits `status=inconclusive`. Missing upstream artifacts remain explicit `*Exists=false` fields and never become a pass.

## Evidence strength

Use the strongest available evidence and name what is missing:

1. **Source contract**: implementation and explicit source tests.
2. **Unit／integration**: store, coordinator, parser, geometry, or state-machine assertions.
3. **UI behavior**: exact UITest selector passed on a leased Simulator with a named UI World.
4. **Visual review**: inspected screenshot/contact sheet/HTML/video from the same run.
5. **Physical device／live service**: separate release or app-review evidence; never substitute with Simulator.

For a UI improvement, a source-only result is not a visual pass; a UI test pass with an uninspected screenshot is not a visual review; a visual review with a system prompt is invalid.

## Reproducibility rules

- Keep the exact command, branch, HEAD, dataset, UDID, verdict, log, xcresult, and visual artifact paths together.
- Re-run the same selector after a code fix. Do not compare a new source tree against an old simulator recording without naming the mismatch.
- If the test runner returns `0` but executes zero tests, treat it as false-green and investigate the runner／selector contract.
- If the test runner returns non-zero, read the helper's normalized stable bundle before changing code; its `upstreamStatus`, stable log, xcresult and any retained UI artifacts are the failure record.
- A parseable JSON object with `status=missing`, missing `uiVisualReview`, dirty source, mismatched dataset/device, or missing artifacts is still a failed evidence contract, never a pass.
- If another Xcode process shares the device or DerivedData, wait on the runner lock or use another leased pool device; do not manually mutate shared state.
