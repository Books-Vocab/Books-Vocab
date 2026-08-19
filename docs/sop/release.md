<!-- doc-meta
tier: sop
authority: derived
update_trigger: release-change
scope:
  - .github/workflows/
  - ops/release.sh
  - ops/devops_kg_safe.sh
  - ops/kg_reconcile.sh
  - backend/
  - ios/
verified_against: 51ce9228ce64c1897850b8fcab672364b17f8731
-->
# Release SOP

## Mental model

[`docs/reference/delivery_model.md`](../reference/delivery_model.md) 定義 CM 對 codebase、merge 與 release／deploy 邊界的責任。GitHub `main` is the merged product truth. A PR merge records code review and required checks; it is not by itself permission to publish or deploy. A release is an explicit, traceable action with a version, target surface, approval, health verification and rollback path.

| Concern | Source of truth | Entry |
|---|---|---|
| Code and review | GitHub PR merged to `main` | GitHub |
| Version and release notes | repository release metadata | `ops/release.sh status/changelog` |
| Backend production state | production ref／container health | `ops/release.sh` + `ops/devops_kg_safe.sh` |
| iOS build/TestFlight | App Store Connect and build artifacts | `docs/sop/ios.md`、`ops/ios_release.sh` |
| Rollback | previous known-good version／image／ref | deploy SOP and safety wrapper |

## Required sequence

1. CM confirms the PR is merged to the intended `main` and the merged SHA is known.
2. Run release status and inspect changed surfaces, migrations, configuration and compatibility risks.
3. Select backend, iOS, or both. Do not publish a surface that was not explicitly selected.
4. Run the release entrypoint in dry-run mode first. Confirm target, version, approval and rollback candidate.
5. Execute only the approved release command. Production writes must pass the safety wrapper and health gate.
6. Verify the deployed/build state independently and record the exact version and evidence.
7. If health verification fails, stop traffic or revert according to `docs/sop/deploy.md`; do not improvise a second path.

## Backend

Use `ops/release.sh` as the release entry and `ops/devops_kg_safe.sh` for remote or production operations. `ops/kg_reconcile.sh` is the host-side convergence service when enabled; its health gate and rollback behavior are part of the deployment contract. Database migrations, secrets, domain routing, container ports and host ownership remain governed by `docs/sop/deploy.md` and `docs/reference/host_topology.md`.

## iOS

Use `docs/sop/ios.md` for signing, build, TestFlight and App Store Connect operations. Keep build verification, metadata changes and submission as separate decisions; an uploaded build is not an approved store release.

## Hard stops

- No production action without explicit release intent and approval.
- No force-push, destructive cleanup or guessed rollback target.
- No claim of release success without current health／store evidence.
- If a required external approval can only be performed by the account owner, report it immediately and continue only with safe parallel work.
