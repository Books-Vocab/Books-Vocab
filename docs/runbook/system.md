<!-- doc-meta
tier: runbook
authority: derived
update_trigger: sop-change
scope:
  - ops/
verified_against: 94a66d63
-->
# System Runbook

## Purpose
Provide one stable operations system so any agent can safely execute tasks from:
- repository root (global view)
- project subfolder (project-only view)

## Startup Checklist
1. Run `ops/devops_kg_safe.sh preflight`
2. Before cleanup / branch convergence, run `ops/branch_audit.sh`
3. Before touching unfamiliar control-plane surfaces, run `ops/capability_matrix.py --json`

## Allowed Production Entrypoints
- KG API: `ops/devops_kg_safe.sh`
- Global status: `ops/devops_kg_safe.sh status` + `ops/devops_kg_safe.sh health`
- Compatibility status wrapper: `ops/status_all.sh`
- Branch convergence audit: `ops/branch_audit.sh`
- Capability contract: `ops/capability_matrix.py`

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

## Operational Definition of Done
- `preflight` succeeded.
- Backup exists and path recorded.
- Health checks return expected HTTP codes.
- Relevant docs updated.

## Hard Stop Conditions
- Missing SSH key or unreachable host.
- No backup path before deploy/migration.
- `ops/branch_audit.sh` reports `merged-pr-but-ahead`, `orphan-ahead`, or `stale-ahead` during cleanup; PR state is metadata, commit reachability is the source of truth.
- Any command resembles destructive wildcard cleanup.
