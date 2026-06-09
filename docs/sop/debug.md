<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - backend/
  - ops/
verified_against: 98cac27d
-->
# 伺服器排障指南

> `./devops.sh *` 子指令的完整參考由 `devops` skill 作 SoT;本文件內的 `./devops.sh run "..."` 用法為診斷情境範例,非指令清單。
>
> ⚠️ **生產禁用指令邊界**：所有 ops 與診斷動作受 [`docs/policy/safety.md`](../policy/safety.md) 約束。`docker compose down -v`、`docker system prune -a`、`rm -rf` 涉及 data dir 一律禁止；診斷可讀不可破壞性清理。

## 核心資訊

- **伺服器 IP**: `13.193.212.134`（AWS Lightsail，ap-northeast-1a）
- **Domain**: `wordnexus.lol`（Porkbun DNS A record）
- **SSH**: `ssh -i ~/.ssh/lightsail_kg_prod ubuntu@13.193.212.134`（舊 `lightsail_default.pem` 已於 2026-05-31 洩漏後撤銷，勿再使用）
- **Stack**: Caddy（443/80）→ Docker FastAPI（localhost:8000）→ SQLite（/app/data/）

---

## 30 秒快速診斷

```bash
# 最快：不需 SSH、不需 auth
curl -s https://wordnexus.lol/api/system/info | uv run --python 3.13 python -m json.tool

# 詳細
cd ~/kg
./ops/devops_kg_safe.sh status   # HTTP code + 部署版本 + 部署記錄
./ops/devops_kg_safe.sh logs 50
```

```
HTTP 200 → API 正常，問題在 iOS App 或 DNS
HTTP 502 → Caddy 正常，FastAPI 掛了 → 看 Docker logs
HTTP 000 → Caddy 掛了或防火牆阻擋
DNS 失敗 → DNS 問題
```

---

## 症狀 → 診斷 → 修復

### HTTPS 連線失敗（iOS 無法連線）

```bash
# 1. DNS
nslookup wordnexus.lol                # 應返回 13.193.212.134
dig wordnexus.lol @8.8.8.8

# 2. 防火牆
aws lightsail describe-instance-firewall-rules \
  --instance-name booksbrowser-kg-api-2gb --region ap-northeast-1

# 3. Caddy
./devops.sh run "sudo systemctl status caddy"
./devops.sh run "sudo journalctl -u caddy -n 100 --no-pager"

# 4. SSL 憑證
./devops.sh run "ls -la /var/lib/caddy/.local/share/caddy/certificates/"
./devops.sh run "sudo ss -tlnp | grep -E ':80|:443|:8000'"
```

**修復：Caddy 掛了**
```bash
./devops.sh run "sudo systemctl restart caddy"
```

**修復：SSL 憑證問題**
```bash
./devops.sh run "sudo systemctl stop caddy"
./devops.sh run "sudo rm -rf /var/lib/caddy/.local/share/caddy/certificates/"
./devops.sh run "sudo systemctl start caddy"
# Caddy 啟動時自動向 Let's Encrypt 申請（需 DNS 已正確解析）
```

**修復：Caddyfile 配置錯誤**
```bash
./devops.sh run "cat /etc/caddy/Caddyfile"
# 正確格式（含 Claude Gateway；Antigravity Proxy 2026-05-23 撤出公網改本機執行）：
./devops.sh run "cat <<'CADDY' | sudo tee /etc/caddy/Caddyfile > /dev/null && sudo systemctl reload caddy
wordnexus.lol {
    handle /claude/* {
        uri strip_prefix /claude
        reverse_proxy localhost:8090
    }
    reverse_proxy localhost:8000
}
CADDY"
```

> 完整 routing 表詳見 `docs/reference/host_topology.md`（SoT）。

---

### API 無回應（HTTP 502）

```bash
./devops.sh run "docker ps"           # 容器是否在跑
./devops.sh logs 100                  # 詳細日誌
./devops.sh restart                   # 快速重啟
```

restart 後仍 502：
```bash
./devops.sh run "docker logs knowledge-graph-api -n 100"
# 通常是 .env 缺 key 或 Python import 錯誤
./devops.sh deploy                    # 重新 build
```

---

### DNS 問題

```bash
dig wordnexus.lol @8.8.8.8
# 期望：wordnexus.lol → 13.193.212.134
# 不對 → 去 Porkbun 後台確認 A record
# DNS 生效需 5-10 分鐘
```

---

### 防火牆阻擋

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
./devops.sh run "free -m"                         # 記憶體
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
./devops.sh run "cat ~/backend/data/users.json"
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

## 重要檔案位置（伺服器）

| 檔案 | 路徑 |
|------|------|
| Caddy 設定 | `/etc/caddy/Caddyfile` |
| API 代碼 | `/home/ubuntu/knowledge_graph_api/` |
| API .env | `/home/ubuntu/backend/.env` |
| 資料庫 | `/home/ubuntu/knowledge_graph_api/data/` |
| SSL 憑證 | `/var/lib/caddy/.local/share/caddy/certificates/` |
| Docker Compose | `/home/ubuntu/knowledge_graph_api/docker-compose.yml` |

---

## AWS Lightsail 指令

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
