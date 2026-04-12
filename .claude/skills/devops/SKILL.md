---
name: devops
description: "KG 生產環境運維 — 部署、狀態、用戶查詢、額度、遠端操作、系統健康"
allowed-tools: Bash, Read, Grep
---

# KG DevOps Skill

## Identity

| key | value |
|-----|-------|
| server | `ubuntu@13.193.212.134` |
| remote | `~/knowledge_graph_api` |
| domain | `wordnexus.lol` |
| container | `knowledge-graph-api` |
| port | `8000` |

## 安全規則

1. **生產環境操作前**先跑 preflight：`./ops/devops_kg_safe.sh preflight`
2. **deploy / migration 前**再加 backup：`./ops/devops_kg_safe.sh backup`
3. 禁止封鎖指令：`setup` `push-env` `delete-user` `ssh`、破壞性 `run` 字串

## 指令參考

### Safe Wrapper（`./ops/devops_kg_safe.sh`）

```bash
./ops/devops_kg_safe.sh preflight
./ops/devops_kg_safe.sh backup
./ops/devops_kg_safe.sh deploy
./ops/devops_kg_safe.sh restart
./ops/devops_kg_safe.sh status
./ops/devops_kg_safe.sh logs [n]
./ops/devops_kg_safe.sh env-check
./ops/devops_kg_safe.sh env-drift
./ops/devops_kg_safe.sh migrate
./ops/devops_kg_safe.sh users
./ops/devops_kg_safe.sh user-info <id>
./ops/devops_kg_safe.sh run "<cmd>"
./ops/devops_kg_safe.sh container-run "<cmd>"
./ops/devops_kg_safe.sh migrate-run "<cmd>"
./ops/devops_kg_safe.sh ops-cli <subcommand> [args]
./ops/devops_kg_safe.sh container-script <script> [args]
```

### ops-cli 子指令

```bash
ops-cli user-quota <uid>        # 24h 額度 + 逐時明細
ops-cli user-stats <uid>        # 單字庫統計
ops-cli quota-overview           # 全用戶額度總覽
ops-cli active-users [hours]    # 近 N 小時活躍用戶
ops-cli db-query <uid> SQL...   # 對用戶 DB 跑 SQL（不需要引號）
ops-cli analyze <uid> [level]  # 深度分析（1-6 或 all）
```

### data_inspect（本地用）

```bash
python3 ops/data_inspect.py [command]
# overview / sample N / gaps / graph / notes / search <keyword> / card <id> / sql "..."
```

## Deploy 機制

`deploy` 自動偵測改動範圍，決定路徑：

| 偵測結果 | 路徑 | 耗時 |
|----------|------|------|
| 只有 .py / .html / 靜態檔 | **fast**: rsync → restart → health | ~15s |
| Dockerfile / docker-compose / pyproject.toml | **full**: backup → env-check → rsync → build → migrate → health → env-drift | ~2min |
| 無上次 deploy 記錄 / sha 不存在 | **full** | ~2min |

偵測依據：`git diff <last_deploy_sha>..HEAD -- backend/`，last_deploy_sha 來自 `deploy.log`。

- `DEPLOY_FULL=1 ./ops/devops_kg_safe.sh deploy` — 強制完整部署
- `./ops/devops_kg_safe.sh restart` — 最快，僅重啟容器不 rsync（程式碼未變時用）

## 高頻操作範例

```bash
# 查用戶額度
./ops/devops_kg_safe.sh ops-cli user-quota <uid>

# 全用戶概覽
./ops/devops_kg_safe.sh ops-cli quota-overview

# 近 24h 活躍用戶
./ops/devops_kg_safe.sh ops-cli active-users 24

# 對用戶 DB 跑 SQL（不需要引號包覆）
./ops/devops_kg_safe.sh ops-cli db-query <uid> SELECT content, notebook_id FROM card LIMIT 5

# 臨時分析腳本
./ops/devops_kg_safe.sh container-script /tmp/my_script.py

# 部署（自動偵測 fast/full）
./ops/devops_kg_safe.sh deploy

# Logs 台北時區
KG_LOG_TZ=Asia/Taipei ./ops/devops_kg_safe.sh logs 50

# iOS 測試
./ops/ios_test.sh -g "sanitize"     # 跑含 "sanitize" 的 test
./ops/ios_test.sh                    # 跑全部 test
```

## 快速診斷流程

```bash
./ops/devops_kg_safe.sh status   # HTTP code 決定根因
./ops/devops_kg_safe.sh logs 50
```

```
HTTP 200 → API OK，問題在 iOS App 或 DNS
HTTP 502 → Caddy OK，FastAPI down → 查 Docker logs
HTTP 000 → Caddy down 或 firewall blocking
DNS fail → DNS issue
```

### 常用 Debug 指令

```bash
# Caddy
./ops/devops_kg_safe.sh run "sudo systemctl status caddy"
./ops/devops_kg_safe.sh run "cat /etc/caddy/Caddyfile"

# Docker
./ops/devops_kg_safe.sh run "docker ps"
./ops/devops_kg_safe.sh run "docker logs knowledge-graph-api -n 100"

# Resources
./ops/devops_kg_safe.sh run "df -h"
./ops/devops_kg_safe.sh run "free -m"
./ops/devops_kg_safe.sh run "docker stats --no-stream"

# Database
./ops/devops_kg_safe.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<uid>/cards.db '.tables'"
```

## 緊急恢復

```bash
# 1. Stop container
./ops/devops_kg_safe.sh run "cd ~/knowledge_graph_api && docker compose stop"

# 2. Backup broken data
scp -i ~/.ssh/lightsail_default.pem -r \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data \
  ~/Desktop/broken_data_$(date +%Y%m%d_%H%M)

# 3. Restore good backup
scp -i ~/.ssh/lightsail_default.pem -r \
  ~/kg/backups/data_<date> \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data

# 4. Restart
./ops/devops_kg_safe.sh restart
./ops/devops_kg_safe.sh status
```

## Deep Reference

- 完整部署指南：`docs/dev/deploy.md`
- 除錯指南：`docs/dev/debug.md`
