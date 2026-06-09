<!-- doc-meta
tier: runbook
authority: derived
update_trigger: sop-change
scope:
  - ops/
verified_against: 94bb8f24
-->
# System Runbook

## Purpose
Provide one stable operations system so any agent can safely execute tasks from:
- repository root (global view)
- project subfolder (project-only view)

## Startup Checklist
1. For a new or cross-surface task, trigger `kg-router`.
2. Run `ops/devops_kg_safe.sh preflight` before production work.
3. Before cleanup / promote / branch convergence, run `ops/branch_audit.sh`.
4. Before touching unfamiliar control-plane surfaces, run `ops/capability_matrix.py --json`.
5. If a typed tool is confusing or nudges agents toward bypassing it, classify the friction; fix medium/large tool issues before continuing the original workflow.

## Allowed Production Entrypoints
- KG API: `ops/devops_kg_safe.sh`
- Global status: `ops/devops_kg_safe.sh status` + `ops/devops_kg_safe.sh health`
- Compatibility status wrapper: `ops/status_all.sh`
- Branch convergence audit: `ops/branch_audit.sh`
- Capability contract: `ops/capability_matrix.py`
- Cold-start routing: `.claude/skills/kg-router`
- Docs control-plane flow: `.claude/skills/kg-docs-control-plane`
- Completion receipt flow: `.claude/skills/kg-receipt`

Do not bypass these entrypoints unless explicitly required and reviewed.

## Change Types and Required Flow

### A) Feature Delivery
1. Work inside project directory.
2. Implement and test code changes.
3. Run preflight.
4. Backup production state.
5. Deploy via safe script.
6. Validate service health (host-local + public URL).

### B) Maintenance/Incident
1. Run status and logs via safe wrapper.
2. If deploy needed, backup first.
3. If health fails post-deploy, rollback to previous artifact/snapshot.
4. Record incident summary and update runbook docs.

### C) Convergence Maintenance
1. Treat `cleanup` as Workflow 1: user defines blacklist, absorb all non-blacklist work into `main`, push/sync remote, then rebase every blacklist branch onto the new `main`.
2. Treat `promote` as Workflow 2: lift only the chosen committed snapshot from an active branch into `main`, then rebase the original branch onto the new `main`.
3. Preserve work identity before any `main` reset or sync; if blacklisted work is sitting on `main`, extract it to a branch/worktree first.
4. `promote` may delete its temporary integration container, but does not automatically delete the original branch/worktree.

## Operational Definition of Done
- `preflight` succeeded.
- Backup exists and path recorded.
- Health checks return expected HTTP codes.
- Relevant docs updated.

## Hard Stop Conditions
- Missing SSH key or unreachable host.
- No backup path before deploy/migration.
- `ops/branch_audit.sh` reports `merged-pr-but-ahead`, `orphan-ahead`, or `stale-ahead` during cleanup; PR state is metadata, commit reachability is the source of truth.
- Any convergence attempt would reset `main` before preserving blacklisted work identity.
- Any command resembles destructive wildcard cleanup.
