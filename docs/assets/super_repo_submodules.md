# Monorepo Workflow (Detailed)

This document is the detailed workflow guide for the workspace after migration to a single git repository.

## Repository Topology
- One root git repository tracks:
  - iOS app: `ios/`
  - backend API: `backend/`
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
1. edit under `ios/`
2. validate iOS build/tests as needed
3. commit with iOS-focused message

### B) API-only change
1. edit under `backend/`
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
git status --short ios
git status --short backend

# fast search
rg "pattern" ios backend docs
```

## Migration Note
- Previous nested child `.git` metadata was moved to:
  - `backups/git_metadata_<timestamp>/ios.git`
  - `backups/git_metadata_<timestamp>/backend.git`
- Current source of truth is the root monorepo git history.
