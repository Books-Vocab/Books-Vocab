# Monorepo Workflow (Detailed)

This document is the detailed workflow guide for the workspace after migration to a single git repository.

## Repository Topology
- One root git repository tracks:
  - iOS app: `booksbrowser_ios/`
  - backend API: `knowledge_graph_api/`
  - workspace ops/docs: `docs/`, `ops/`, `devops.sh`, policy/support pages

## Commit Strategy
- Keep commit scope narrow and explicit.
- Recommended prefixes:
  - `ios:` iOS-only changes
  - `api:` backend-only changes
  - `ops:` deploy/runbook/tooling
  - `docs:` documentation-only

## Typical Flows

### A) iOS-only change
1. edit under `booksbrowser_ios/`
2. validate iOS build/tests as needed
3. commit with iOS-focused message

### B) API-only change
1. edit under `knowledge_graph_api/`
2. run API tests
3. commit with API-focused message

### C) Cross-cutting release change
1. apply iOS + API changes
2. run both validation paths
3. commit with explicit release context

## Operational Safety
- Before production changes, run preflight and backup via project-safe scripts.
- Do not run destructive cleanup commands on production host.
- If task scope is ambiguous, clarify before executing risky operations.

## Useful Commands
```bash
# repo overview
git status --short
git log --oneline -n 20

# scope-limited status checks
git status --short booksbrowser_ios
git status --short knowledge_graph_api

# fast search
rg "pattern" booksbrowser_ios knowledge_graph_api docs
```

## Migration Note
- Previous nested child `.git` metadata was moved to:
  - `backups/git_metadata_<timestamp>/booksbrowser_ios.git`
  - `backups/git_metadata_<timestamp>/knowledge_graph_api.git`
- Current source of truth is the root monorepo git history.
