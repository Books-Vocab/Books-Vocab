---
name: ios-visual-report-workflow
description: Turn an iOS visual report with PDF/PNG references into five cluster contracts, complete source/fixture/UITest changes, and exact-head Simulator evidence with a machine-rendered report. Use when working from P1-P15 screenshots, rebuilding a SwiftUI surface, operating the iOS Simulator, or closing an iOS UI review into one integrated delivery tree.
---

# iOS Visual Report Workflow

Use this as the integrator workflow for report-driven iOS UI work. The report is an input, not a second source of truth: the executable cluster manifest and evidence matrix are the control plane; the report is rendered/updated from those receipts.

## Non-negotiable invariants

- Work in the existing integration worktree. Do not create a workaround tree for a late test, fixture, or evidence problem.
- Collapse P1-P15 into exactly five clusters: Dictionary (P1-P2), Reader Runtime (P3-P7), Explore/Overview (P8-P10), Vocabulary/Review Card (P11-P13), Settings/Sync (P14-P15).
- A cluster hand-back contains the root cause, implementation, unit test, UI World fixture, exact XCTest selector, machine acceptance, stable evidence bundle, visual attestation, and current HEAD.
- A selector PASS is not a requirement PASS. A requirement is verified only after fixture coverage, machine contract, counterexample coverage, complete visual attestation, and matrix provenance all pass.
- Every evidence claim binds the same clean source HEAD, UI World ID/SHA, Simulator UDID, selector, run ID, evidence root, manifest SHA, and reviewer identity.
- Evidence from a Simulator never proves physical-device, TestFlight, App Store, or production behavior.
- Keep one integration tree alive; after hand-back, integrate or formally account for the child immediately. Do not leave stale child trees as the workflow's normal state.

## Phase 0 — freeze the executable plan before implementation

1. Confirm host, primary `main`, canonical integration worktree, and registry. If another tree is dirty, inspect and protect its ownership; do not overwrite it.
2. Read the PDF text and inspect `p1.PNG` through `p15.PNG`. Run the bundled input audit:

   ```bash
   uv run --python 3.13 python .claude/skills/ios-visual-report-workflow/scripts/audit_report_inputs.py \
     --root . \
     --report-dir IOS2.0.1+7-UI-review-report \
     --clusters ops/fixtures/ios_ui_review_clusters.json \
     --matrix ops/fixtures/ios_ui_review_matrix.json \
     --json
   ```

3. Complete the cluster manifest before source edits. Each requirement must name: report image, source module, required states, counterexample, fixture IDs, exact selector, machine acceptance, visual acceptance, and evidence output root. Read `references/cluster-contract.md` for the contract.
4. Resolve unknowns from the relevant feature boundary and UI design SoT before dispatching work. Do not make each child reinterpret the PDF.

## Phase 1 — implement one complete cluster unit

For each cluster, freeze these four values first:

```text
source module → UI World fixture → exact ClassName/testMethod selector → machine acceptance
```

Then deliver together:

1. root-cause proof and smallest coherent state-model/refactor;
2. production source and accessibility identifiers;
3. unit tests for the state transition and boundary;
4. UI World fixture with deterministic clock/data/error injection;
5. exact UITest and Page Object queries (no implicit first match);
6. focused machine verification and evidence contract;
7. visual acceptance notes and hand-back receipt.

Use TDD and root-cause-first debugging. If the same UI hypothesis misses twice, instrument the behavior instead of adding another timeout/retry. Review each independently committed unit before starting the next unit; never fabricate a review receipt.

## Phase 2 — build once, run many

Keep the source tree clean and pin one Simulator. Put all exact selector mappings in a JSON methods file. Use the existing runner, which prepares the build cache once and invokes each selector separately:

```bash
uv run --python 3.13 python ops/ios_ui_run_many.py run \
  --root "$PWD" \
  --helper "$PWD/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --methods-file <cluster-or-batch-methods.json> \
  --device <canonical-udid> \
  --output-dir build/snapshots/uitest-evidence/<batch>/raw \
  --publish-root build/snapshots/uitest-evidence/<batch>/bundles \
  --summary-out build/snapshots/uitest-evidence/<batch>/summary.json
```

The runner must emit heartbeat lines with phase, PID, elapsed time, and alive/exit state. During a long build or UI run, continue an independent queue: inspect the next cluster's source, validate fixtures, run static/contract tests, prepare matrix/report entries, and inspect prior failure artifacts. Waiting is not a work item.

For every bundle, validate the normalized verdict and evidence contract, then inspect the full contact sheet, quick sheet, UIreview HTML, video, and step images. Use `ops/uitest_review_attest.py ... --all-steps` only after visual inspection. Keep machine verification and visual attestation as separate receipts.

## Phase 3 — record and render the matrix

Record only from durable, already-attested bundles:

```bash
uv run --python 3.13 python ops/ios_ui_review_matrix.py record-many \
  ops/fixtures/ios_ui_review_matrix.json \
  --root . \
  --summary build/snapshots/uitest-evidence/<batch>/summary.json \
  --strict-complete
```

Then validate again from the same clean HEAD:

```bash
uv run --python 3.13 python ops/ios_ui_review_matrix.py validate \
  ops/fixtures/ios_ui_review_matrix.json --root . --strict-complete
```

If validation says the evidence source commit differs from `HEAD`, stop unless the
current HEAD is a descendant whose only committed tree differences are the
tracked matrix and existing report receipts:
`ops/fixtures/ios_ui_review_matrix.json`,
`IOS2.0.1+7-UI-review-report/CURRENT-STATUS-2026-08-13.md`, and
`IOS2.0.1+7-UI-review-report/evidence-manifest-2026-08-13.json`. This
receipt-only case is the expected post-`record-many` handoff: preserve the
evidence's original `sourceCommit`, and report both the evidence source and
receipt HEAD. Any other code/test/docs drift, dirty tree, non-ancestor source,
or provenance rewrite is still fail-closed and requires re-running evidence at
the new exact source HEAD.
If Git HEAD, ancestry, or cleanliness cannot be established, validation rejects
the bundle; a non-Git or partially observable root is never treated as clean.

Update the existing report directory only after the matrix receipt is valid. Keep historical batches explicitly labelled historical; current status must link the current matrix, batch summary, evidence root, Gate receipt, review receipt, and docs lint output. Do not create a parallel manual status ledger.

## Phase 4 — convergence and hand-back

The integrator owns convergence, not just code collection:

1. Read registry hand-back seals and source tips. Integrate each returned child into the one canonical tree in bounded batches; late children are appended before the one final Gate. Never cherry-pick a commit already proven by ancestry, patch-id, or identical tree.
2. A dirty child is first tested and reviewed in its own path, then committed and handed back. Do not reset, clean, or delete it while ownership is unresolved.
3. Run one fresh Gate on the final exact HEAD using that tree's own orchestrator. A non-block Gate is required; warnings and environment deviations remain visible.
4. Cut over to local `main`, sync `origin/main` only when backup authorization exists, and resolve every source/integration tree through `worktree_orchestrate.py`. Do not use manual directory deletion or force-reset.
5. Final audit must prove: one clean canonical tree, source/test/docs present, fresh exact-HEAD evidence, review receipt state, registry closure, `main == origin/main == ls-remote`, and zero scoped worktree/branch residue.

## Output contract

Return a compact receipt containing:

- five-cluster map and report inputs;
- integrated source/test/docs commits and duplicate decisions;
- exact canonical path/branch/HEAD/tree/base;
- UI World, Simulator, selector, batch, bundle, matrix, visual reviewer identities;
- unit/UI/build/contract/visual/review/docs/Gate verdicts;
- remaining children and formal disposition;
- deviations, blockers, and the single next action if not complete;
- report directory links and hand-back state.

## Bundled resources

- `scripts/audit_report_inputs.py`: read-only audit of PDF/PNG P1-P15 inputs and five-cluster/matrix coverage.
- `references/cluster-contract.md`: compact cluster manifest and evidence contract; load before editing the manifest.
- `.claude/skills/ios-simulator-verification/`: low-level Simulator/evidence runner and artifact contract.
