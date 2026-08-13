---
name: ios-simulator-verification
description: Run isolated KG iOS Simulator and BooksAndVocab UI-test verification with a pinned UI World, exact selector, Simulator identity, stable visual artifacts, and fail-closed evidence validation. Use when operating an iOS Simulator, validating SwiftUI behavior or visual state, diagnosing a UI-test run, or producing a reproducible UIreview evidence bundle.
---

# iOS Simulator Verification

## Boundary

Verify Simulator behavior and visual output. Do not treat this evidence as proof for a physical device, TestFlight, App Store, or production release.

Keep source and tool identity separate: run from the source worktree being tested; let the helper resolve the validator from the repository that owns the helper. Require a clean source tree before collection.

## Required workflow

1. Confirm host, worktree, HEAD, and cleanliness.
2. Choose exactly one UI World and one test selector.
3. Prefer a Simulator lease. An explicit device must be a canonical UDID.
4. Run the helper. Do not invoke Xcode directly for evidence collection.
5. Read the normalized verdict, machine contract, UIreview, full and quick contact sheets, video, log, and xcresult.
6. Inspect the visual artifacts before claiming visual correctness. A machine pass proves integrity and provenance, not design quality.

```bash
hostname -s
git branch --show-current
git rev-parse HEAD
git status --short

./.claude/skills/ios-simulator-verification/scripts/run_ui_evidence.sh \
  --dataset marketing_demo \
  --method SettingsFlowUITests/testSettingsFlow \
  --json-out /tmp/settings-flow-evidence.json
```

Selectors map to the existing runner as follows:

- `--file FooUITests.swift` → `ios_ops.sh test --ui --file ...`
- `--grep FooUITests` → `ios_ops.sh test --ui --grep ...`
- `--method Class/testMethod` → positional `Class/testMethod`; never invent an `ios_test.sh --method` flag

Use `--device <UDID>` only for an already isolated Simulator. Otherwise omit it or pass `--lease`.

## Fail-closed reading

Treat helper exit `0` as runtime evidence only when `helper.contractStatus=pass` and `helper.artifactContractStatus=pass`. The helper also requires a clean matching source commit, matching UI World ID/hash, matching Simulator UDID, nonzero executed tests, and complete stable artifacts.

Treat these outcomes distinctly:

- `1`: test assertion failure
- `65`: build, runner, preflight, or other infrastructure failure
- `70`: upstream process returned successfully but the evidence contract was incomplete or inconsistent
- `128+N`: interrupted run; neither product pass nor product failure

Failure and inconclusive bundles remain diagnostic artifacts. Never reuse a prior green bundle for a newer source, UI World, device, or selector.

Read [references/evidence-contract.md](references/evidence-contract.md) before interpreting schema fields, hashes, containment checks, or atomic publication behavior. Run the helper regression after changing this skill or its script:

```bash
./.claude/skills/ios-simulator-verification/scripts/test_run_ui_evidence.sh
```
