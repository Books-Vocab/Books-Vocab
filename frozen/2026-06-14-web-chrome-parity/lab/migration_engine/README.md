# migration_engine — iOS→Web transduction (distilled from the parity rewrite)

Distills the hand-aligned 63-case pixel-parity web rewrite (`web/src/surfaces/*`)
into a reusable iOS→Web conversion system. Three layers: L1 deterministic token
mapping · L2 platform-difference codex · L3 parity-rig oracle loop.

## Layout

| path | what |
|---|---|
| `audit/extract.py` | one-shot extractor: scans surface+component+harness CSS, pulls every hard-coded literal w/ selector+comment provenance, classifies token vs L2 vs orphan, clusters cross-surface. `uv run python audit/extract.py` |
| `audit/report.py` | renders `audit/report.md` from the JSON. `uv run python audit/report.py` |
| `audit/measured_values.json` | full extraction (899 records, 237 clusters) — regenerate, don't hand-edit |
| `audit/report.md` | core numbers: 70% token / 18% L2 / 12% orphan; top clusters |
| `codex/l2_rules.yaml` | **L2 law v1** — 11 rules + 4 candidates. Each = token+named-delta, provenance ≥2 surfaces (single-surface → `candidates:`, never emitted) |
| `engine/DESIGN.md` | engine skeleton: L1→L2→L3 pipeline + holdout generalization score (anti-overfit) |

## Regenerate

```
uv run python lab/migration_engine/audit/extract.py
uv run python lab/migration_engine/audit/report.py
```

Audit source-of-truth = the parity surfaces themselves; re-run after any surface CSS
change to refresh the delta inventory.
