---
name: devops
description: KG API dev operations - status, preflight, deploy, logs, debug, user management
disable-model-invocation: true
allowed-tools: Bash, Read, Grep
---

# KG DevOps Skill

## Identity
- local: `projects/kg`
- backend: `projects/kg/backend`
- remote: `~/knowledge_graph_api`
- domain: `wordnexus.lol`
- container: `knowledge-graph-api`
- port: `8000`

## devops_kg_safe.sh Commands
```bash
./ops/devops_kg_safe.sh preflight   # sanity check before any prod change
./ops/devops_kg_safe.sh backup      # backup before deploy/migration
./ops/devops_kg_safe.sh deploy      # rsync + build + migrate + health
./ops/devops_kg_safe.sh restart     # restart container only (10x faster)
./ops/devops_kg_safe.sh status      # container + HTTP health check
./ops/devops_kg_safe.sh logs 120    # tail last 120 lines of container logs
./ops/devops_kg_safe.sh env-check   # verify remote .env keys
./ops/devops_kg_safe.sh migrate     # run DB migrations only
./ops/devops_kg_safe.sh users       # list users + optional integrations
./ops/devops_kg_safe.sh user-info <id>  # user vocab stats
```

## Standard Deploy Workflow
```
preflight → backup → deploy → status → smoke test
```

**Golden rule**: `restart` is 10x faster than `deploy`. Only `deploy` when code actually changed.

## 30-Second Quick Diagnosis
```bash
./ops/devops_kg_safe.sh status   # HTTP code determines root cause
./ops/devops_kg_safe.sh logs 50
```

```
HTTP 200 → API OK, problem is iOS App or DNS
HTTP 502 → Caddy OK, FastAPI down → check Docker logs
HTTP 000 → Caddy down or firewall blocking
DNS fail → DNS issue
```

## Common Debug Commands
```bash
# Caddy
./devops.sh run "sudo systemctl status caddy"
./devops.sh run "cat /etc/caddy/Caddyfile"

# Docker
./devops.sh run "docker ps"
./devops.sh run "docker logs knowledge-graph-api -n 100"

# Resources
./devops.sh run "df -h"
./devops.sh run "free -m"
./devops.sh run "docker stats --no-stream"

# Database
./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<uid>/cards.db '.tables'"
```

## User Management
```bash
./devops.sh users                         # list all users
./devops.sh user-info <user_id>           # vocab stats
./devops.sh delete-user <user_id> --yes   # delete account + all data (irreversible)
```

## Emergency Recovery
```bash
# 1. Stop container
./devops.sh run "cd ~/knowledge_graph_api && docker compose stop"

# 2. Backup broken data
scp -i ~/.ssh/lightsail_default.pem -r \
  ubuntu@54.95.189.179:~/knowledge_graph_api/data \
  ~/Desktop/broken_data_$(date +%Y%m%d_%H%M)

# 3. Restore good backup
scp -i ~/.ssh/lightsail_default.pem -r \
  ~/MPSO/projects/kg/backups/data_<date> \
  ubuntu@54.95.189.179:~/knowledge_graph_api/data

# 4. Restart
./devops.sh restart
./devops.sh status
```

## Deep Reference
- Full deploy guide: `docs/deploy.md`
- Full debug guide: `docs/debug.md`
