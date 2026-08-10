<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - backend/
  - ops/
verified_against: a67653fdf
-->
# 伺服器排障指南

> `./devops.sh *` 子指令的完整參考由 `devops` skill 作 SoT;本文件內的 `./devops.sh run "..."` 用法為診斷情境範例,非指令清單。
>
> ⚠️ **生產禁用指令邊界**：所有 ops 與診斷動作受 [`docs/policy/safety.md`](../policy/safety.md) 約束。`docker compose down -v`、`docker system prune -a`、`rm -rf` 涉及 data dir 一律禁止；診斷可讀不可破壞性清理。
>
> **過渡狀態（2026-06-15 起）**：正式站已遷到家用常駐機 `standby`，經 Cloudflare Tunnel 對外（**無 Caddy / 不開 inbound 埠**）。以下「primary」段為 CF tunnel 語境；Caddy / Lightsail / 防火牆段保留於 §Lightsail rollback 排障（容器 STOP，僅回滾時相關）。Host topology SoT 見 [`docs/reference/host_topology.md`](../reference/host_topology.md)。

## 核心資訊（primary：standby + CF Tunnel）

- **primary 機器**: `chenliangyusAir`（M3 Air），user `chenliangyu`，Tailscale `100.118.39.104`，OrbStack docker
- **Edge**: Cloudflare Tunnel（名 `kg-standby`，CF 邊緣終結 TLS）；**無 Caddy、無 inbound 埠**
- **Domain**: `wordnexus.lol`（CF DNS apex proxied CNAME → tunnel）；CF anycast IP `104.21.85.113` / `172.67.204.212`
- **SSH**: `ssh chenliangyu@100.118.39.104`（主力機公鑰免密碼）
- **Stack**: CF 邊緣（TLS）→ cloudflared 隧道（outbound）→ standby localhost:8000 → Docker FastAPI → SQLite（/app/data/）

---

## 30 秒快速診斷

```bash
# 最快：不需 SSH、不需 auth
curl -s https://wordnexus.lol/api/system/info | uv run --python 3.13 python -m json.tool

# DNS 卡舊 IP 時繞過快取直打 CF 邊緣驗服務本身（回 200 + server:cloudflare + cf-ray = CF→tunnel→standby 全鏈健康）
curl -sD - --resolve wordnexus.lol:443:104.21.85.113 https://wordnexus.lol/api/system/info -o /dev/null

# 直連 standby（繞過 CF，分層定位）
./ops/devops_kg_safe.sh docker-ps; ./ops/devops_kg_safe.sh caddy-status --json
```

```
公網 HTTP 200 → API 正常，問題在 iOS App 或 DNS 傳播
公網 502/530 但 local:8000 健康 → cloudflared 隧道斷（連接器掛/重連中）
public + local:8000 都掛 → 容器掛 → 看 docker logs
public 失敗但 --resolve 直打 CF 邊緣 OK → 純 DNS 傳播問題（見下方 §DNS）
```

---

## 症狀 → 診斷 → 修復（primary）

### HTTPS 連線失敗（iOS 無法連線）

分層定位：CF 邊緣 → cloudflared 隧道 → 容器。

```bash
# 1. DNS 解析（期望 CF anycast，不是 13.193.212.134）
dig wordnexus.lol @8.8.8.8 +short        # 應回 104.21.85.113 / 172.67.204.212（CF）
dig wordnexus.lol @1.1.1.1 +short

# 2. 服務本身（繞過 DNS，直打 CF 邊緣）
curl -sD - --resolve wordnexus.lol:443:104.21.85.113 https://wordnexus.lol/api/system/info -o /dev/null
#   回 200 + cf-ray → CF→tunnel→standby 全鏈 OK，問題純在 DNS 傳播
#   回 502/530 → 隧道斷或容器掛，往下查

# 3. cloudflared 連接器（standby 上）
./ops/devops_kg_safe.sh caddy-status --json

# 4. 容器（standby 上）
ssh chenliangyu@100.118.39.104 'docker ps --filter name=knowledge-graph-api; curl -s -o /dev/null -w "local:8000=%{http_code}\n" http://localhost:8000/api/system/info'
```

**修復：cloudflared 隧道斷**（local:8000 健康但公網 502/530）
```bash
# system LaunchDaemon，KeepAlive 通常自動拉起；卡住時 kickstart
ssh chenliangyu@100.118.39.104 'sudo launchctl kickstart -k system/com.cloudflare.cloudflared'
```

**修復：容器掛**（local:8000 不回）
```bash
ssh chenliangyu@100.118.39.104 'docker logs --tail 100 knowledge-graph-api'   # 通常 .env 缺 key / Python import 錯誤
ssh chenliangyu@100.118.39.104 'cd ~/kg-prod/backend && docker compose up -d'   # restart:always，不應需要手動
```

> TLS 憑證由 CF 邊緣託管，standby 端**無**憑證可查/可清（不再有 Let's Encrypt / Caddy 流程）。

---

### API 無回應（HTTP 502 / 530）

```bash
# 先分層：是隧道斷還是容器掛？
./ops/devops_kg_safe.sh health --json; ./ops/devops_kg_safe.sh caddy-status --json
```
- `local:8000` 健康但公網 502/530 → cloudflared 隧道問題 → `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`
- `local:8000` 也掛 → 容器問題：
```bash
ssh chenliangyu@100.118.39.104 'docker logs --tail 100 knowledge-graph-api'
ssh chenliangyu@100.118.39.104 'cd ~/kg-prod/backend && docker compose up -d --build'   # .env 缺 key / import 錯誤需重 build
```

---

### DNS 問題

```bash
dig wordnexus.lol @8.8.8.8 +short
# 期望：CF anycast 104.21.85.113 / 172.67.204.212
# 仍回 13.193.212.134（舊 Lightsail）→ DNS 傳播未收斂或回滾後沒切回
```
- NS 已從 Porkbun 移到 CF（`damien/gabriella.ns.cloudflare.com`）。遷移初期「服務健康但部分用戶 502」多為**純 DNS 委派傳播**（舊 Porkbun NS 殘留舊 apex A，最久卡 24h）。成因鏈與緩解手段（強刷 resolver 快取、`/etc/hosts` 釘 CF IP）見 butler `~/butler/docs/kg-backend-deployment.md §8`。
- **驗服務本身排除 DNS 干擾**：永遠用 `--resolve wordnexus.lol:443:104.21.85.113` 直打 CF 邊緣。

---

## Lightsail rollback 排障（僅回滾時相關）

> 以下為舊 Lightsail + Caddy 語境。Lightsail instance **已 terminate**，僅在冷重建回滾後這些 Caddy/防火牆/SSL 診斷才生效。回滾程序見 [`docs/reference/host_topology.md` §Rollback](../reference/host_topology.md)。
> ⚠️ 本段 `KG_ALLOW_LIGHTSAIL=1 ./devops.sh ...` 為歷史寫法 —— 該 guard env var 2026-06-19 隨 wrapper retarget standby 移除。冷重建 Lightsail 時須將 wrapper transport（`KG_SERVER` 等）指向新站，或直接 ssh 進新站手動執行下列 Caddy/SSL 診斷。standby 現役無 Caddy，CF tunnel 排障見上方 §症狀→診斷→修復（primary）。

### HTTPS 連線失敗（Lightsail）

```bash
# 1. DNS（回滾後期望 13.193.212.134）
nslookup wordnexus.lol
dig wordnexus.lol @8.8.8.8

# 2. 防火牆
aws lightsail describe-instance-firewall-rules \
  --instance-name booksbrowser-kg-api-2gb --region ap-northeast-1

# 3. Caddy
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo systemctl status caddy"
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo journalctl -u caddy -n 100 --no-pager"

# 4. SSL 憑證
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "ls -la /var/lib/caddy/.local/share/caddy/certificates/"
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo ss -tlnp | grep -E ':80|:443|:8000'"
```

**修復：Caddy 掛了**
```bash
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo systemctl restart caddy"
```

**修復：SSL 憑證問題**
```bash
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo systemctl stop caddy"
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo rm -rf /var/lib/caddy/.local/share/caddy/certificates/"
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "sudo systemctl start caddy"
# Caddy 啟動時自動向 Let's Encrypt 申請（需 DNS 已正確解析）
```

**修復：Caddyfile 配置錯誤**
```bash
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "cat /etc/caddy/Caddyfile"
# 正確格式（含 Claude Gateway；Antigravity Proxy 2026-05-23 撤出公網改本機執行）：
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "cat <<'CADDY' | sudo tee /etc/caddy/Caddyfile > /dev/null && sudo systemctl reload caddy
wordnexus.lol {
    handle /claude/* {
        uri strip_prefix /claude
        reverse_proxy localhost:8090
    }
    reverse_proxy localhost:8000
}
CADDY"
```

### API 無回應（HTTP 502，Lightsail）

```bash
KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "docker ps"
KG_ALLOW_LIGHTSAIL=1 ./devops.sh logs 100
KG_ALLOW_LIGHTSAIL=1 ./devops.sh restart
```

### 防火牆阻擋（Lightsail）

```bash
aws lightsail put-instance-public-ports \
  --instance-name booksbrowser-kg-api-2gb \
  --port-infos \
    fromPort=80,toPort=80,protocol=tcp \
    fromPort=443,toPort=443,protocol=tcp \
    fromPort=22,toPort=22,protocol=tcp \
  --region ap-northeast-1
```

---

## 症狀 → 診斷 → 修復（平台無關）

> 以下 pipeline / 用戶管理 / DB 直查走容器內，standby 與 Lightsail 通用。standby 上把 `./devops.sh run "..."` 換成 `ssh chenliangyu@100.118.39.104 "..."`；rollback 後在 Lightsail 用 `KG_ALLOW_LIGHTSAIL=1 ./devops.sh run "..."`。

### Pipeline 卡住

Pipeline 有 per-user `asyncio.Lock`，crash 後可能鎖住。

```bash
./devops.sh restart                   # 重啟釋放鎖
./devops.sh logs 100                  # 找 "pipeline started/completed/locked"
```

**各 Step 常見錯誤**：
```
Step 1 Enrich → Gemini API key 無效/額度用完
  → ./devops.sh run "docker exec knowledge-graph-api env | grep GEMINI"

Step 2 Embed+Judge → pending_judge 積累 / judge 全 reject
  → 查 judge_log：./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<id>/cards.db 'SELECT * FROM judge_log ORDER BY created_at DESC LIMIT 20;'"
  → 查 acceptance rate：admin dashboard 或 /api/admin/stats

```

**Pipeline Telemetry 查詢**：
```bash
# 查 pipeline 執行歷史
./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/pipeline_log.db 'SELECT * FROM runs ORDER BY started_at DESC LIMIT 10;'"

# 查 translate_log（LLM 呼叫追蹤）
./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<id>/cards.db 'SELECT * FROM translate_log ORDER BY created_at DESC LIMIT 20;'"
```

---

## 用戶管理

```bash
./devops.sh users                    # 列出所有用戶及可選第三方整合設定
./devops.sh user-info <user_id>      # 用戶單字統計
./devops.sh delete-user <user_id> --yes  # 刪除帳號 + 所有資料（不可恢復）
```

### 刪除用戶所有單字（保留帳號）

```bash
# 確認資料量
./devops.sh user-info <user_id>

# 在容器內刪除
./devops.sh run "docker exec knowledge-graph-api sh -c '
  rm -f /app/data/users/<user_id>/cards.db
  rm -f /app/data/users/<user_id>/cards.db-shm
  rm -f /app/data/users/<user_id>/cards.db-wal
  rm -f /app/data/users/<user_id>/embeddings.npy
  rm -f /app/data/users/<user_id>/graph.json
  rm -f /app/data/users/<user_id>/candidates.json
  rm -f /app/data/users/<user_id>/card_ids.json

'"

# 確認清空
./devops.sh run "docker exec knowledge-graph-api ls /app/data/users/<user_id>/"
```

---

## 資源診斷

```bash
./devops.sh run "df -h"                           # 磁碟
./ops/devops_kg_safe.sh memory-usage --json       # Felix macOS 記憶體 / swap
./devops.sh run "docker stats --no-stream"        # 容器資源
./devops.sh run "docker ps -a"                    # 所有容器

# 深度日誌
./devops.sh logs 200
./devops.sh run "docker logs knowledge-graph-api -n 200 2>&1 | grep -i error"
./devops.sh run "docker logs knowledge-graph-api -n 200 2>&1 | grep -i pipeline"
```

---

## 資料庫直接操作

```bash
./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<uid>/cards.db '.tables'"
./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<uid>/cards.db 'SELECT COUNT(*) FROM cards;'"
./devops.sh run "docker exec knowledge-graph-api sqlite3 /app/data/users/<uid>/cards.db 'PRAGMA table_info(cards);'"
./devops.sh run "cat ~/kg-data/users.json"   # host data 2026-06-16 移至 ~/kg-data（原 backend/data）
```

---

## Docker 操作

```bash
./devops.sh run "docker inspect knowledge-graph-api"
./devops.sh run "docker exec knowledge-graph-api env"    # 確認 .env 讀到
./devops.sh run "cd ~/knowledge_graph_api && docker compose config"
./devops.sh run "cd ~/knowledge_graph_api && docker compose up -d --build --force-recreate"
```

---

## 緊急恢復 SOP

```bash
# 1. 停止容器（防止繼續寫入）
./devops.sh run "cd ~/knowledge_graph_api && docker compose stop"

# 2. 備份當前損壞資料
scp -i ~/.ssh/lightsail_kg_prod -r \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data \
  ~/Desktop/broken_data_$(date +%Y%m%d_%H%M)

# 3. 推回好的備份
scp -i ~/.ssh/lightsail_kg_prod -r \
  ~/kg/backups/data_<日期> \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data

# 4. 重啟
./devops.sh restart
./devops.sh status
```

---

## 重要檔案位置

### primary（standby，macOS）
| 檔案 | 路徑 |
|------|------|
| API 代碼 / compose | `~/kg-prod/backend/`（user `chenliangyu`；生產 checkout） |
| API .env | `~/kg-prod/backend/.env` |
| 資料庫 | `~/kg-data/`（felix；2026-06-16 移出 git worktree） |
| cloudflared daemon | `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` |
| backup launchd | `~/Library/LaunchAgents/com.kg.backup.plist`（源 `ops/launchd/com.kg.backup.plist`） |
| TLS 憑證 | 無（CF 邊緣託管） |

> `~/kg-prod` 是生產 checkout；`~/project/kg` 僅供 dev / resume 使用，不要在其 backend 跑 compose。

### rollback（Lightsail，Ubuntu）
| 檔案 | 路徑 |
|------|------|
| Caddy 設定 | `/etc/caddy/Caddyfile` |
| API 代碼 | `/home/ubuntu/knowledge_graph_api/` |
| API .env | `/home/ubuntu/knowledge_graph_api/.env` |
| 資料庫 | `/home/ubuntu/knowledge_graph_api/data/` |
| SSL 憑證 | `/var/lib/caddy/.local/share/caddy/certificates/` |
| Docker Compose | `/home/ubuntu/knowledge_graph_api/docker-compose.yml` |

---

## AWS Lightsail 指令（rollback 語境）

```bash
# 查看實例狀態
aws lightsail get-instance --instance-name booksbrowser-kg-api-2gb --region ap-northeast-1

# 查看防火牆規則
aws lightsail describe-instance-firewall-rules \
  --instance-name booksbrowser-kg-api-2gb --region ap-northeast-1

# 臨時開放額外 port（如 8080 debug）
aws lightsail put-instance-public-ports \
  --instance-name booksbrowser-kg-api-2gb \
  --port-infos \
    fromPort=80,toPort=80,protocol=tcp \
    fromPort=443,toPort=443,protocol=tcp \
    fromPort=22,toPort=22,protocol=tcp \
    fromPort=8080,toPort=8080,protocol=tcp \
  --region ap-northeast-1
```
