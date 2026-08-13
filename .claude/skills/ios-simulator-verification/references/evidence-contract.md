# iOS UI evidence contract

## Verdict identity

`ops/ios_ops.sh test --ui --json` emits `kg.ios.run.v1`. The helper preserves that schema on a valid upstream JSON payload and adds `helper.schema=kg.ios.ui-evidence.v1`. A pre-upstream failure uses `kg.ios.ui-evidence.v1` as the normalized fallback schema.

Bind every interpretation to this tuple:

| Field | Requirement |
|---|---|
| `status`, `result`, `exit` | Read the final normalized state; do not infer it from process launch. |
| `executed` | Must parse to a number greater than zero for pass. |
| `options.sourceCommit` | Must equal the clean preflight HEAD and the post-run HEAD. |
| `options.sourceTreeDirty` | Must be exactly `false`; the helper also rechecks the worktree after the run. |
| `options.datasetID`, `options.datasetSHA256` | Must equal the validated local UI World bytes. |
| `device`, `options.device` | Top-level device must be a UUID and must match the Simulator destination `id=`. |
| `helper.selector` | Must identify exactly one `--file`, `--grep`, or `--method` request. |
| `uiVisualReview.videoIdentity` | `runID` must equal the upstream review-root basename; `file` and `sha256` must match the retained video. `artifacts.uiVideoIdentity` must be identical. |

## Stable bundle

Each invocation creates a unique directory under `build/snapshots/uitest-evidence/<run-id>/` and refuses to reuse an existing directory. The stable bundle contains:

```text
command.txt
delegate.stderr.log
upstream-verdict.json
verdict.json
artifacts/delegate.stderr.log
artifacts/Test.xcresult
artifacts/ui-evidence-contract.json
artifacts/ui-review/UIreview.html
artifacts/ui-review/contact_sheet.png
artifacts/ui-review/quick4_contact_sheet.png
artifacts/ui-review/review_manifest.json
artifacts/ui-review/uitest-videos/<run>.mp4
artifacts/ui-review/<step>.png
```

`verdict.json` is written to a sibling temporary path and atomically renamed into place. `--json-out` is likewise a temporary-file-plus-rename publication; it is an alias to the per-run verdict, not a replacement for the stable bundle. A nonzero runner or malformed upstream JSON still publishes a failure bundle and truthful existence booleans for artifacts that were actually retained.

## Machine contract and canonical hash

`ops/uitest_evidence_contract.py validate` emits `kg.ios.ui-evidence-contract.v1`. Pass requires:

- a `kg.visual-review.sheet.v1` manifest with `source=uitest`, matching provenance, at least one step, and valid PNG metadata and SHA-256 for each step;
- nonempty full contact sheet, quick contact sheet, video, and UIreview HTML;
- a nonempty video run identity whose filename and SHA-256 match the canonical video bytes;
- UIreview HTML containing the expected KG run-review root;
- every manifest path contained within the screenshot root and every canonical artifact contained within the run root;
- no canonical symlink, path replacement, or byte mutation observed across containment, descriptor open, and hashing.

`bundleSHA256` uses `kg.ios.ui-evidence-bundle.v1` role framing and hashes, in order: manifest, every manifest step keyed by relative path, full contact sheet, quick contact sheet, the sole video, and UIreview HTML. It excludes `review_state.json`, so appending a human attestation does not invalidate itself. The attestation writer uses an exclusive file lock and atomic replacement; its latest complete pass must still match the current canonical bundle hash before it can support a visual claim.

## Success predicate

The helper returns `0` only when all of these are true:

- upstream schema/kind/status/result/exit are `kg.ios.run.v1`, `test`, `ok`, `ok`, and `0`;
- `executed > 0`;
- source, UI World, device, selector, review-root, and video identities match;
- stable log, xcresult, manifest, step PNGs, contact sheets, video, and UIreview exist;
- the canonical machine contract passes.

If the runner exits nonzero, preserve its exit code. If the runner exits zero but the success predicate fails, normalize to `status=result=inconclusive`, `exit=70`, and `helper.contractStatus=contract-failed`.

## Human review boundary

Machine validation proves provenance and current-byte integrity. It does not prove that loading, empty, error, long-content, dark-appearance, accessibility, or interaction states look correct. Inspect the full step sequence and video. If the visual state is incomplete or polluted by a system prompt, report the bundle as diagnostic or visual-review pending, never as visually passed.
