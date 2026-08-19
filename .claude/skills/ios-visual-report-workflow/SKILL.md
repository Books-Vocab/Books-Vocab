---
name: ios-visual-report-workflow
description: Turn the active P3-P15 iOS visual report references into four cluster contracts, complete source/fixture/UITest changes, and exact-head Simulator evidence with a machine-rendered report. Use when rebuilding a covered SwiftUI surface, operating the iOS Simulator, or closing an iOS UI review in one PR.
---

# iOS Visual Report Workflow

Use this as the multi-cluster workflow for report-driven iOS UI work. The report is an input, not a second source of truth: the executable cluster manifest and evidence matrix are evidence controls, not a local Issue／Project／PR control plane. Read `docs/reference/delivery_model.md` for the delivery boundary; the implementation ends in the Worker／Issue Solver's PR.

## Non-negotiable invariants

- Work in the declared Worker／Issue Solver worktree. Do not create a workaround tree for a late test, fixture, or evidence problem.
- Partition active P3-P15 requirements into exactly four clusters: Reader Runtime (P3-P7), Explore/Overview (P8-P10), Vocabulary/Review Card (P11-P13), Settings/Sync (P14-P15).
- A cluster hand-back contains the root cause, implementation, unit test, UI World fixture, exact XCTest selector, machine acceptance, run-scoped visual receipt, visual attestation, exact source thread ID, and current HEAD. Screenshots/video/xcresult are short-lived agent inspection material; the durable hand-back is the compact receipt and its provenance. Gate BLOCK returns to that source thread; fixes produce a new commit and hand-back.
- A selector PASS is not a requirement PASS. A requirement is verified only after fixture coverage, machine contract, counterexample coverage, complete visual attestation, and matrix provenance all pass.
- Every evidence claim binds the same clean source HEAD, UI World ID/SHA, Simulator UDID, selector, run ID, evidence root, manifest SHA, and reviewer identity.
- Evidence from a Simulator never proves physical-device, TestFlight, App Store, or production behavior.
- Keep one declared implementation worktree for the PR; after hand-back, keep ownership and evidence explicit. Do not create a second local merge or work-item state machine for cluster work.

## Phase 0 — freeze the executable plan before implementation

1. Confirm host, source base, declared implementation worktree, and registry. If another tree is dirty, inspect and protect its ownership; do not overwrite it.
2. Read the PDF text and inspect active references `p3.PNG` through `p15.PNG`. Run the bundled input audit:

   ```bash
   uv run --python 3.13 python .claude/skills/ios-visual-report-workflow/scripts/audit_report_inputs.py \
     --root . \
     --report-dir IOS2.0.1+7-UI-review-report \
     --clusters ops/fixtures/ios_ui_review_clusters.json \
     --matrix ops/fixtures/ios_ui_review_matrix.json \
     --json
   ```

3. Complete the cluster manifest before source edits. Each requirement must name: report image, source module, required states, counterexample, fixture IDs, exact selector, machine acceptance, visual acceptance, and evidence output root. Read `references/cluster-contract.md` for the contract.
4. Resolve unknowns from the relevant feature boundary and UI design SoT before implementation. Do not make each workstream reinterpret the PDF.

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

## Phase 2 — build once, run many (ephemeral visual tool)

Keep the source tree clean and pin one Simulator. Put all exact selector mappings in a JSON methods file. Use the existing runner, which prepares the build cache once and invokes each selector separately:

```bash
uv run --python 3.13 python ops/ios_ui_run_many.py run \
  --root "$PWD" \
  --helper "$PWD/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --methods-file <cluster-or-batch-methods.json> \
  --device <canonical-udid>
```

The runner creates a unique `run-manifest.json` under the system temporary
directory, keeps visual material only for the configured TTL (default 30
minutes), and records PID/HEAD/worktree provenance there. A success, failure,
or interruption is reclaimable after TTL; cleanup first proves that no
recorded PID, xcodebuild, runner, or shared lock is active. The source tree
remains free of visual run material unless an explicit promotion is requested.

When a human-facing report genuinely needs binary visual evidence, promote it
explicitly and only then:

```bash
uv run --python 3.13 python ops/ios_ui_run_many.py run \
  --root "$PWD" \
  --helper "$PWD/.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh" \
  --methods-file <cluster-or-batch-methods.json> \
  --device <canonical-udid> \
  --retain \
  --output-dir build/ios-report/retained/<batch>
```

`--retain` is the promotion boundary; it is required before `record-many` can
consume a visual bundle. The normal agent loop inspects the temporary bundle,
records a compact verdict/attestation, then reclaims the binaries.

After the batch finishes, inspect and then reclaim all expired ephemeral
staging content (including successful runs):

```bash
uv run --python 3.13 python ops/ios_ui_run_many.py cleanup \
  --staging-root "${KG_IOS_EPHEMERAL_ROOT:-${TMPDIR:-/tmp}/kg-ios-ui-run-many}"
uv run --python 3.13 python ops/ios_ui_run_many.py cleanup \
  --staging-root "${KG_IOS_EPHEMERAL_ROOT:-${TMPDIR:-/tmp}/kg-ios-ui-run-many}" --commit
uv run --python 3.13 python ops/ios_ui_run_many.py cleanup \
  --staging-root "${TMPDIR:-/tmp}/kg-ios-visual-runs" --commit
```

The cleanup receipt records bounded `du` allocation and `df` free-space
before/after values. Any recorded live PID, active xcodebuild/runner, or
unreadable/active shared lock blocks deletion.

The runner must emit heartbeat lines with phase, PID, elapsed time, and alive/exit state. During a long build or UI run, continue an independent queue: inspect the next cluster's source, validate fixtures, run static/contract tests, prepare matrix/report entries, and inspect prior failure artifacts. Waiting is not a work item.

For every run, validate the normalized verdict and evidence contract, then inspect the full contact sheet, quick sheet, UIreview HTML, video, and step images while the temporary bundle is alive. Use `ops/uitest_review_attest.py ... --all-steps` only after visual inspection. Keep machine verification and visual attestation as separate compact receipts; retain binary material only when an explicit report or hand-off requires it.

## Phase 3 — record and render the matrix

Record only from explicitly retained, already-attested bundles:

```bash
uv run --python 3.13 python ops/ios_ui_review_matrix.py record-many \
  ops/fixtures/ios_ui_review_matrix.json \
  --root . \
  --summary build/ios-report/retained/<batch>/summary.json \
  --strict-complete
```

Then validate again from the same clean HEAD:

```bash
uv run --python 3.13 python ops/ios_ui_review_matrix.py validate \
  ops/fixtures/ios_ui_review_matrix.json --root . --strict-complete
```

If validation says the evidence source commit differs from `HEAD`, stop unless the
current HEAD is a descendant whose only committed tree differences are the
tracked matrix `ops/fixtures/ios_ui_review_matrix.json`. This matrix-only
receipt case is the expected post-`record-many` handoff: preserve the evidence's
original `sourceCommit`, and report both the evidence source and receipt HEAD.
Any report, code, test, or other docs drift, dirty tree, non-ancestor source, or
provenance rewrite is still fail-closed and requires re-running evidence at the
new exact source HEAD.
If Git HEAD, ancestry, or cleanliness cannot be established, validation rejects
the bundle; a non-Git or partially observable root is never treated as clean.

Update the existing report directory only after the matrix receipt is valid. Keep historical batches explicitly labelled historical; current status must link the current matrix, batch summary, evidence root, Gate receipt, review receipt, and docs lint output. Do not create a parallel manual status ledger.

## Phase 4 — PR convergence and hand-back

CM owns PR convergence and merge; IM owns Issue intake／triage and does not prepare a local staging merge. Worker／Issue Solver owns the implementation branch and PR:

1. Keep all cluster source／test／fixture／evidence changes in the declared branch and commit them in reviewable units. A cluster manifest or visual matrix is evidence control, not a batch merge queue.
2. Test and review the exact worktree before hand-back. Do not reset, clean, or delete it while ownership is unresolved.
3. Run one fresh Gate on the PR branch's exact HEAD. Keep warnings and environment deviations visible, then update the PR with the command, exit status and evidence paths.
4. CR and DS review the PR; CM decides merge only after required Actions checks, review and safety conditions are satisfied. Do not cut over a local `main` or invent a local merge ledger.
5. Final audit must prove: one clean PR worktree, source/test/docs present, fresh exact-HEAD evidence, PR review/check state and docs lint. Worktree cleanup is an ownership operation after hand-back, not a product delivery state.

## Output contract

Return a compact receipt containing:

- four-cluster map and active report inputs;
- source/test/docs commits and any duplicate decisions;
- exact canonical path/branch/HEAD/tree/base;
- UI World, Simulator, selector, batch, bundle, matrix, visual reviewer identities;
- unit/UI/build/contract/visual/review/docs/Gate verdicts;
- remaining workstreams and formal disposition;
- deviations, blockers, and the single next action if not complete;
- report directory links and hand-back state.

## Bundled resources

- `scripts/audit_report_inputs.py`: read-only audit of PDF plus active PNG P3-P15 inputs and four-cluster/matrix coverage.
- `references/cluster-contract.md`: compact cluster manifest and evidence contract; load before editing the manifest.
- `.claude/skills/ios-simulator-verification/`: low-level Simulator/evidence runner and artifact contract.
