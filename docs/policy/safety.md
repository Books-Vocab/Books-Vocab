<!-- doc-meta
tier: policy
authority: SoT
update_trigger: manual
scope:
  - ops/
  - backend/
  - docs/runbook/
verified_against: 25e7148d
-->
# Safety Policy

## Non-Negotiable Rules
1. Production actions must go through project scripts.
2. Every deployment requires backup first.
3. Never run destructive Docker cleanup commands on production.

## Forbidden Commands (Production)
- `docker compose down -v`
- `docker system prune -a`
- `rm -rf /home/ubuntu/*`
- `rm -rf ~` / `rm -rf $HOME`（home 目錄遞迴刪除）
- `delete-user`（用戶資料刪除 CLI）

實作見 `ops/devops_kg_safe.sh:49` — `is_blocked_run` regex 同時攔截
`down -v` / `docker system prune` / `rm -rf /` / `rm -rf ~` / `delete-user`，
適用 `run` / `container-run` / `migrate-run` 三個遠端執行入口。

## Required Preflight
1. Confirm remote path (`~/knowledge_graph_api`).
2. Confirm domain (`wordnexus.lol`) and internal port (`8000`).
3. Confirm expected container name (`knowledge-graph-api`).

## Rollback Principle
- If health check fails after deploy, roll back to previous image/tag or previous synced directory snapshot.
- Do not patch production files manually before rollback attempt.

## Incident Logging
- Write incident summary with timestamp, root cause, and mitigation.
- Update relevant runbook before the next deployment.
