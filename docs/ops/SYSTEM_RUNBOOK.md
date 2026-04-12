# System Runbook

## Purpose
Provide one stable operations system so any agent can safely execute tasks from:
- repository root (global view)
- project subfolder (project-only view)

## Startup Checklist
1. Run `ops/devops_kg_safe.sh preflight`

## Allowed Production Entrypoints
- KG API: `ops/devops_kg_safe.sh`
- Global status: `ops/status_all.sh`

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
- Any command resembles destructive wildcard cleanup.
