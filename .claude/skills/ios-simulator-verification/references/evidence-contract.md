# iOS UI evidence contract

## Verdict identity

`ops/ios_test.sh --json` emits `kg.ios.run-verdict.v1`; the visual helper writes a normalized
copy with `helper.schema=kg.ios.ui-evidence.v1` into a run-scoped bundle. The bundle is
ephemeral by default and is promoted only by explicit `--retain`. Treat these fields as the
minimum identity tuple:

| Field | Meaning | Required reading |
|---|---|---|
| `status` / `result` | `ok`, `fail`, or `inconclusive` | Never infer from process launch |
| `exit` / `reason` | process classification | helper-normalized `65` identifies lease exhaustion; raw producer status stays in the bundle |
| `options.sourceCommit` | source provenance | Bind screenshots to this commit |
| `options.sourceTreeDirty` | uncommitted source state | Dirty evidence is not a release claim |
| `options.datasetID` / `datasetSHA256` | UI World provenance | Prevent fixture drift |
| `device` | resolved Simulator UDID | Required for parallel-run attribution |
| `artifacts.log` / `xcresult` | raw diagnostics | Normalized paths must point inside the run bundle and exist while it is alive |
| `artifacts.uiReviewHtml` | navigable visual review | Preferred human entrypoint |
| `artifacts.uiContactSheet` / `uiQuick4Sheet` | screenshot overview | Inspect, do not merely archive |
| `artifacts.uiVideo` | full interaction recording | Use when timing or transition matters |

The runner also records timings such as `deviceRunLockWaitMs`, `buildForTestingMs`, `testBodyMs`,
and `totalMs`. A high lock wait is queueing evidence, not app slowness.

`artifacts/ui-evidence-contract.json` must bind every step PNG, contact sheet, quick4 sheet,
video and `UIreview.html` to current bytes. In addition to `stepSha256`, it records
`videoSha256` and `reviewHtmlSha256`; byte size or a retained HTML marker alone is not evidence
integrity.

## Helper success gate

`run_ui_evidence.sh` is fail-closed. It returns `0` only when all of these hold:

- `schema=kg.ios.run-verdict.v1`, `kind=test`, `status=result=ok`, `exit=0`, and `executed > 0`;
- `options.sourceCommit` equals the preflight HEAD and `options.sourceTreeDirty=false`;
- `options.datasetID` and `datasetSHA256` equal the validated local UI World;
- top-level `device` is a UUID and agrees with the `id=` in `options.device`; explicit `--device` must match it;
- `uiVisualReview.reviewHtml`, contact sheet, quick4 sheet, manifest, video and review root all exist;
- normalized log, xcresult and visual artifacts are inside the ephemeral run bundle; only an explicit `--retain` promotion places them under `build/ios-report/retained/<run>/`;
- the visual manifest resolves every `relPath` inside its stable screenshot root; symlink escapes are rejected before PNG metadata is trusted.

When the helper is invoked from a different source worktree, it resolves `toolRoot` from the
helper's own skill repository, not from the caller's git root. The validator must therefore be
`<toolRoot>/ops/uitest_evidence_contract.py`; a missing or unusable canonical validator is a
named `tool-missing`/`tool-invalid` preflight failure with exit `70`, never a source-worktree
copy or a contract downgrade. Successful normalized verdicts retain `helper.toolRoot`,
`helper.validator`, and `helper.toolResolution` so the tool provenance is auditable.

The helper keeps `upstream-verdict.json`, the delegate stderr log, command metadata and every
upstream artifact that still exists in the complete UI review directory while the run bundle is
alive, then bounded cleanup removes binary artifacts after TTL. For a non-zero runner it emits a
normalized failure or typed infrastructure verdict; for invalid JSON or a zero-exit contract
violation it emits `status=inconclusive`. Missing upstream artifacts remain explicit `*Exists=false`
fields and never become a pass.

## Lease availability classification

The `--lease` producer can fail before `ios_test.sh` writes a verdict JSON. When the pool has no
available slot, the producer emits the exact stderr marker
`[ios_test] error: --lease requested but simulator pool is exhausted` and exits `1`. The helper
recognizes that marker only for an invocation without explicit `--device` and normalizes it to:

- `status=inconclusive` and `result=inconclusive`;
- `exit=65`, the typed lease-unavailable result (and helper process exit `65`);
- `helper.contractStatus=lease-exhausted`;
- `reason` containing `simulator pool exhausted` and an explicit-device recovery hint;
- `helper.recoveryHint=retry with an explicit --device <UDID> after confirming a dedicated Simulator is available`.

This is resource availability evidence, not a product test failure or pass. The run-scoped
delegate stderr and bundle remain the diagnostic record, and the hint means to rerun with a
known dedicated Simulator UDID after confirming that device is available. Account-disposability
or unverifiable identity messages do not match this classification and must retain their own raw
failure evidence; do not turn them into capacity advice.

## Evidence strength

Use the strongest available evidence and name what is missing:

1. **Source contract**: implementation and explicit source tests.
2. **Unit／integration**: store, coordinator, parser, geometry, or state-machine assertions.
3. **UI behavior**: exact UITest selector passed on a leased Simulator with a named UI World.
4. **Visual review**: inspected screenshot/contact sheet/HTML/video from the same run.
5. **Physical device／live service**: separate release or app-review evidence; never substitute with Simulator.

For a UI improvement, a source-only result is not a visual pass; a UI test pass with an
uninspected screenshot is not a visual review; a visual review with a system prompt is invalid.

The matrix recorder accepts only the latest append-only `review_state.json` entry, which must be
`kg.ui.review-state.v2`, a complete `pass`, and hash/provenance-equal to the current bundle. A
later `fail` invalidates earlier `pass` entries. Required steps and counterexamples must map to
disjoint screenshot assets.

## Reproducibility rules

- Keep the exact command, branch, HEAD, dataset, UDID, verdict, log, xcresult, and visual artifact paths together.
- Re-run the same selector after a code fix. Do not compare a new source tree against an old simulator recording without naming the mismatch.
- If the test runner returns `0` but executes zero tests, treat it as false-green and investigate the runner／selector contract.
- If the test runner returns non-zero, read the helper's normalized run bundle before changing code; its `upstreamStatus`, log, xcresult and any visual artifacts are the failure record while the TTL is alive.
- A parseable JSON object with `status=missing`, missing `uiVisualReview`, dirty source, mismatched dataset/device, or missing artifacts is still a failed evidence contract, never a pass.
- If another Xcode process shares the device or DerivedData, wait on the runner lock or use another leased pool device; do not manually mutate shared state.
