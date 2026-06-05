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

## 指令參考 **(SoT)**

本段為 `./ops/devops_kg_safe.sh`（與 repo-local shortcut `./devops.sh`）的權威指令清單；`docs/sop/deploy.md` / `docs/sop/debug.md` 內任何 `./devops.sh *` 用法以本表為準。

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
ops-cli user-quota <uid>                  # 24h 額度 + 逐時明細
ops-cli user-stats <uid>                  # 單字庫統計
ops-cli quota-overview                     # 全用戶 24h 額度總覽
ops-cli active-users [hours]              # 近 N 小時活躍用戶
ops-cli card-find <uid> <substring>       # byte-exact 子字串搜尋 card.content（免寫 SQL；ASCII case-insensitive；repr 顯示，trailing comma/空白可見）
ops-cli card-get <uid> <id|content>       # 單卡 byte-exact 垂直 dump 全欄（寬表 SELECT * 難讀時用）
ops-cli db-query <uid> SQL...             # 唯讀查用戶 DB（只放行單一 SELECT/WITH/EXPLAIN）
ops-cli db-query <uid> --schema           # 免寫 SQL 列出各表 DDL（先看 schema 再查，省盲猜欄位）
ops-cli analyze <uid> [level]            # 深度分析（1-6 或 all）
ops-cli cost <uid> [--range R]            # 單用戶 cost-by-call_type 拆解（provider-aware）
ops-cli cost-overview [--range R]         # 全用戶 cost 排名
ops-cli sync-trace <uid> [--date YYYY-MM-DD] # 用戶單日 sync 時間線（cards+API+judge+translate 合併按時間排序；預設今天）

# 統一輸出契約：以上所有 data-query 命令（analyze 除外，它是人讀報告）皆支援 --json，
#   吐結構化結果供 agent 機讀；db-query 的 --json 可置於 SQL 前後皆可。
#   診斷 banner（[Preflight]/▶progress）一律走 stderr，stdout 只有純 JSON，
#   可直接 `... --json 2>/dev/null | jq`（或 json.loads）。
#   list 類命令（card-find/active-users/quota-overview/cost-overview/sync-trace/db-query）
#   的 JSON 皆含頂層 count，免自己 len()。
# --range: 24h | 7d | 30d | month | all（預設 month）
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
| Dockerfile / docker-compose / pyproject.toml | **full**: backup（rsync 增量）→ env-check → rsync → build → migrate → health → env-drift | ~2min |
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

# 找含某字串的卡片，byte-exact（首選；免寫 SQL、免處理引號）
./ops/devops_kg_safe.sh ops-cli card-find <uid> chateau

# 對用戶 DB 跑任意 SQL —— transport 已 %q 安全序列化，引號/括號/% 一律可用，
# SQL 字串字面建議用單引號包覆（如 LIKE '%x%'、WHERE word = 'foo'）
./ops/devops_kg_safe.sh ops-cli db-query <uid> "SELECT content, notebook_id FROM card LIMIT 5"

# 單用戶當月 cost by call_type（judge/enrich/translate 拆解，provider-aware）
./ops/devops_kg_safe.sh ops-cli cost <uid> --range month --json

# 全用戶 24h cost 排名
./ops/devops_kg_safe.sh ops-cli cost-overview --range 24h

# 用戶單日 sync 時間線（debug 同步問題：何時建卡/呼叫 API/judge/translate，按時序合併）
./ops/devops_kg_safe.sh ops-cli sync-trace <uid> --date 2026-06-05

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

- 完整部署指南：`docs/sop/deploy.md`
- 除錯指南：`docs/sop/debug.md`
