# Safety Policy

## Non-Negotiable Rules
1. Production actions must go through project scripts.
2. Every deployment requires backup first.
3. Never run destructive Docker cleanup commands on production.

## Forbidden Commands (Production)
- `docker compose down -v`
- `docker system prune -a`
- `rm -rf /home/ubuntu/*`

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
