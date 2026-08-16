# Four-cluster contract

The report's PNG/PDF material is an input contract. Visual inspection is an agent-only, on-demand step; the durable control plane is `ops/fixtures/ios_ui_review_clusters.json` plus `ops/fixtures/ios_ui_review_matrix.json` and compact provenance receipts.

## Required shape

The active cluster manifest must have exactly four unique cluster IDs and requirements `P3` through `P15` exactly once:

```json
{
  "schema": "kg.ios.ui-review-clusters.v1",
  "clusters": [
    {
      "id": "reader-runtime",
      "requirements": ["P3", "P4", "P5", "P6", "P7"],
      "sourceModules": ["ios/BooksAndVocab/..."],
      "datasetIDs": ["marketing_demo"],
      "runs": [
        {
          "requirementID": "P3",
          "selector": "ReaderFlowUITests/test...",
          "requiredStates": ["idle", "loading", "success"],
          "counterexamples": ["runtime-timeout", "retry-after-timeout"],
          "requiredFixtureIDs": ["..."],
          "acceptance": ["..."],
          "visualAcceptance": ["..."],
          "evidenceRoot": "build/ios-report/retained/..."
        }
      ]
    }
  ]
}
```

The repository's actual schema may use equivalent field names, but the invariants are fixed:

- selectors are exact `ClassName/testMethodName`, never a file/grep wildcard;
- every requirement has at least one required state and one counterexample;
- every fixture ID is declared by the selected UI World;
- every method maps to one requirement/cluster contract;
- a shared selector is allowed only when the matrix preserves distinct requirement mappings;
- evidence roots are unique run directories in the ephemeral bundle, or in `build/ios-report/retained/` only after explicit promotion;
- source commit, dataset SHA, device UDID, run ID, manifest SHA, and reviewer are machine-readable.

## Four clusters

| ID | Requirements | State-model boundary |
|---|---:|---|
| `reader-runtime` | P3-P7 | TOC/runtime loading, progress, settings round-trip and preview |
| `explore-overview` | P8-P10 | loading/empty/error, projection clock, calendar and forecast |
| `vocabulary-review-card` | P11-P13 | review-state filter projection, information hierarchy, natural card layout |
| `settings-sync` | P14-P15 | sync lifecycle, IA, optimistic-state boundaries and reset |

## Acceptance layers

1. Source layer: root cause and coherent state model are present.
2. Unit layer: transition/error boundary tests fail before the fix and pass after it.
3. Fixture layer: UI World deterministically injects data, clock, auth, and counterexample.
4. Selector layer: exact UITest selector reaches the intended production accessibility node.
5. Machine layer: normalized verdict and evidence contract pass with current source HEAD.
6. Visual layer: every manifest step is inspected and explicitly attested; contact sheets are for batching review, not replacing step inspection.
7. Matrix layer: record-many/strict validation passes and binds all identities.
8. Delivery layer: fresh Gate, review receipt, docs lint, clean canonical tree, and formal integration closure pass.
