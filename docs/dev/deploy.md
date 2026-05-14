<!-- doc-meta
tier: operational
scope:
  - backend/src/kg
  - ops
verified_against: d37c113
-->
# 後端部署指南

## 核心資訊

- **伺服器**: AWS Lightsail `booksbrowser-kg-api-2gb`（small_3_0, 2GB RAM），IP `13.193.212.134`
- **Domain**: `wordnexus.lol`（Porkbun DNS → Caddy → Docker FastAPI）
- **SSH Key**: `~/.ssh/lightsail_default.pem`
- **本地工作區**: `~/kg/`
- **devops.sh 位置**: KG workspace 根目錄

---

## Step 0：先判斷用哪個指令

```
你要做什麼？
│
├─ 首次部署 / .env 有改動？
│   └─→ ./devops.sh setup    ← push-env + deploy 一條龍
│
├─ 只是代碼更新（.env 未變）？
│   └─→ ./devops.sh deploy   ← rsync + build + migrate + health
│
├─ 只需重啟（不需重新 build）？
│   └─→ ./devops.sh restart  ← 快 10 倍，保留現有鏡像
│
└─ 只跑 DB migration？
    └─→ ./devops.sh migrate
```

**黃金原則**：`restart` 比 `deploy` 快 10 倍，只有代碼真的改了才 `deploy`。

---

## 標準部署流程

```bash
cd ~/kg

./devops.sh deploy      # rsync + build + migrate + health
./devops.sh status      # 確認健康
./devops.sh logs 50     # 如有問題查日誌
```

`deploy` 內部流程：backup → env-check → **寫入 VERSION（git SHA）** → rsync → docker build → migrate → 容器內 health check → env-drift → **追加 deploy.log** → **外部 smoke verify**（非通過自動中止）。

部署完成後可透過兩種方式確認遠端版本：
- `./devops.sh status` — 顯示部署版本 + 最近 5 筆部署記錄
- `curl https://wordnexus.lol/api/system/info` — 無需 auth，回傳 version、uptime、migration 狀態

### 外部 smoke verify（deploy 末段自動執行）

容器健康檢查只走 `localhost:8000/docs`，無法保證 Caddy/TLS/公網路徑完好。`cmd_deploy` 末段會從本地透過公網打三層 verify：

1. `GET https://wordnexus.lol/api/system/info` — 預期 HTTP 200，**且** body 內 `version` 欄位必須等於本次 `git rev-parse --short HEAD`。版本不對齊 = rsync/build 未生效，立刻失敗。
2. `GET https://wordnexus.lol/api/health` — unauth 預期 401/403（受 `Depends(get_current_user)` 保護，代表 endpoint 存在 + auth 系統 wire 正常）。HTTP 404 = endpoint 從 router 消失，**視為跳過**而非失敗（保留向後相容空間）；HTTP 000/500 = 真的壞，失敗。
3. `SENTRY_VERIFY=1` 時：`GET /api/system/sentry-test` — endpoint 是 admin-only，unauth 預期 401/403；若 endpoint 已被移除（404）則 fallback 檢查 `/api/system/info` body 是否含 `sentry` 欄位作為「DSN 已讀取」的存在性證據。

任何一層失敗：紅字錯誤 + 自動印出容器最近 30 行 log + 非零 exit。`deploy.log` 已寫入（無回滾語意），需人工 `./devops.sh logs 100` + 決定是否 rollback。

#### 控制 env

| Env | 預設 | 用途 |
|-----|------|------|
| `KG_SKIP_SMOKE=1` | 0 | 完全跳過 smoke verify（緊急 deploy 用，不建議） |
| `SENTRY_VERIFY=1` | 0 | 額外加做 sentry endpoint 探測 |
| `SMOKE_BASE_URL` | `https://wordnexus.lol` | 改打 staging / 自訂 domain |
| `CURL_BIN` | `curl` | 注入 mock curl（測試專用，見 `ops/tests/test_deploy_smoke.sh`） |

預估開銷：3 個 curl 串行，每個 `--max-time 10`，順利情況下加 < 1 秒；失敗情境最多多 ~30 秒。

#### 排查

- `version=X 不等於 deploy_sha=Y` → rsync 沒同步 / VERSION 檔沒寫入 / 容器沒 rebuild。檢查 `run_remote "cat $REMOTE_DIR/VERSION"` 與 `docker compose ps`。
- `health 000` → 公網斷線、TLS 失敗、Caddy 沒起。`./devops.sh run "sudo systemctl status caddy"`。
- `health 500` → app 起來但 auth middleware 起火。看 `docker compose logs --tail=100`。
- sentry endpoint 期待 401 但拿到 200 → admin auth 失效，立即查 `get_admin_user`。

---

## 特殊情境 SOP

### 新增 / 修改 env 變數

```bash
# 1. 更新本地 .env
# 2. 同步更新 devops.sh 頂部的 REQUIRED_ENV_KEYS
./devops.sh push-env
./devops.sh deploy
```
**注意**：`.env` 變動不能只 `restart`，容器讀不到新值。

### App Store 訂閱驗簽必備 env

production 現在預設只接受 signed App Store payload。下列 key 缺一不可：

```bash
APP_STORE_ROOT_CA_PATH=/home/ubuntu/knowledge_graph_api/certs/apple_root_ca.pem
APP_STORE_CONNECT_ISSUER_ID=<issuer-id>
APP_STORE_CONNECT_KEY_ID=<key-id>
APP_STORE_CONNECT_PRIVATE_KEY_PATH=/home/ubuntu/knowledge_graph_api/certs/appstore_connect.p8
```

補充規則：
- `APP_STORE_ALLOW_UNSIGNED_SYNC` 不應在 production 設為 `true`
- `APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS` 不應在 production 設為 `true`
- `APPLE_BUNDLE_ID` 必須與 App Store Connect 訂閱商品所屬 app 相同

`./devops.sh env-check` 現在會同時檢查：
- 必要 App Store 驗簽 key 是否存在
- unsigned fallback 開關是否被錯誤打開

`./devops.sh env-drift` 會在 deploy 後檢查本地/遠端 `.env` 是否一致：
- 一般 key 要求值完全相同
- host-specific path key（例如 App Store cert path）允許本地/遠端主機路徑不同，但要求檔名一致且位於各自主機的預期 `certs/` 目錄
- 若 drift 存在，deploy 會直接失敗，避免 runtime 配置悄悄偏離

### Sentry 錯誤追蹤

Sentry 為 **opt-in** — `SENTRY_DSN` 留空時 SDK 完全 no-op，整層免費。

#### Backend env vars

| Env | Default | 用途 |
|-----|---------|------|
| `SENTRY_DSN` | （空）| 主開關；填入 DSN 才會啟動 |
| `SENTRY_ENVIRONMENT` | `production` | release/staging/dev 環境標籤 |
| `SENTRY_RELEASE` | fallback：`KG_VERSION` → `/app/VERSION` | deploy 寫的 git SHA，通常無需手動設 |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0`（哨兵）| **非 0** 時整層 flat 取樣（debug override）；**0** 時走 per-path `_traces_sampler`：LLM hot paths（pipeline/translate/explain）0.05、health/info 0.0、其他 baseline 0.01 |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.0` | profile 取樣率（保留，目前生產不開）|

實作：`backend/src/kg/sentry_init.py`
- **Scrub**：`Authorization` / `Cookie` / `X-Admin-Token` header，含 `session` / `token` 的 cookie 鍵，OAuth query（`token` / `admin_session` / `code` / `id_token` / `access_token`）
- **Hardening**：`send_default_pii=False`、`include_local_variables=False`、`max_request_body_size="never"`、`attach_stacktrace=True`
- **User context**：auth dependency 透過 `bind_user(user_id)` 標記 scope，登出無 PII 洩漏
- **Logging**：WARNING+ 轉 breadcrumb，event_level=None 避免與 Starlette exception capture 重複
- 狀態暴露於 `/api/system/info`

#### iOS env / Info.plist

iOS 端（`ios/BooksBrowser/Services/AppCrashReporting.swift`）：
- `Info.plist` `SentryDSN` 鍵為主開關（空 → 全 no-op）
- `Info.plist` `SentryEnvironment` 可覆寫；無覆寫時 `#if DEBUG` → `"debug"`，release → `"production"`
- `releaseName = <bundleId>@<CFBundleShortVersionString>+<CFBundleVersion>`、`dist = CFBundleVersion`（區分共用版號的 TestFlight build）
- `tracesSampleRate`：release 預設 `0.05`、DEBUG 預設 `0.0`；env `SENTRY_TRACES_SAMPLE_RATE`（launch arg / scheme env）可覆寫
- DEBUG build 預設 `enabled=false`；`SENTRY_ENABLED_IN_DEBUG=1` 或 `-sentryTest` launch arg 啟用
- `setUser(id:)` 連動 `authManager.isLoggedIn` — 登出時清除避免多帳戶污染
- HTTP breadcrumb 自動 strip query string、`CancellationError`/`NSURLErrorCancelled` 由 `beforeSend` 丟棄

### 新增 Card Schema 欄位（SQLite）

```bash
# 1. 在 src/kg/cards.py 新增欄位
# 2. 在 devops.sh 的 cmd_migrate() 的 MIGRATIONS 清單加 SQL：
#    ALTER TABLE cards ADD COLUMN <col> <type> DEFAULT <val>;
#    （必須 idempotent，SQLite 不支援 IF NOT EXISTS，用 try/except）
./devops.sh deploy
```

### 首次部署 / 全新伺服器

```bash
# 1. 安裝 Docker
ssh ubuntu@13.193.212.134
curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh
sudo apt-get install docker-compose-plugin -y

# 2. 安裝 Caddy
sudo apt update && sudo apt install -y caddy
echo "wordnexus.lol { reverse_proxy localhost:8000 }" | \
  sudo tee /etc/caddy/Caddyfile > /dev/null
sudo systemctl restart caddy && sudo systemctl enable caddy

# 3. 部署
cd ~/kg
./devops.sh setup

# 4. 開放防火牆
aws lightsail put-instance-public-ports \
  --instance-name booksbrowser-kg-api-2gb \
  --port-infos \
    fromPort=80,toPort=80,protocol=tcp \
    fromPort=443,toPort=443,protocol=tcp \
    fromPort=22,toPort=22,protocol=tcp \
  --region ap-northeast-1
```

**重要**：Caddyfile 必須是全文反向代理（`reverse_proxy localhost:8000`），不要只代理 `/api/*`。

### 緊急只重啟

```bash
./devops.sh restart
```

---

## 部署失敗診斷

```
deploy 失敗
│
├─ env-check → 遠端 .env 缺 key → ./devops.sh push-env
├─ rsync → SSH 問題 → 測試 ssh -i ~/.ssh/lightsail_default.pem ubuntu@13.193.212.134
├─ docker build → Python 依賴錯誤 → ./devops.sh logs 100
├─ migrate → SQL 語法錯誤 → 確認 MIGRATIONS 是 idempotent
└─ health check 非 200 → FastAPI 啟動失敗 → ./devops.sh logs 100
```

---

## 常用指令速查

```bash
./devops.sh status          # 健康狀態 + 部署版本 + 最近部署記錄
./devops.sh logs [n]        # 查日誌（預設 50 行）
./devops.sh users           # 列出用戶 + 可選第三方整合設定
./devops.sh user-info <id>  # 用戶單字統計
./devops.sh backup          # 備份 data/ 到本地
./devops.sh env-check       # 確認遠端 .env 必要 key 齊全
./devops.sh env-drift       # 檢查本地/遠端 .env 一致性（含 path 正規化）
./devops.sh run "<cmd>"     # 在遠端 host 執行任意指令
./devops.sh push-env        # 推送本地 .env 到遠端
./devops.sh migrate         # 只跑 DB migration
```

---

## 備份 SOP

```bash
./devops.sh backup
# 等同：scp -r ubuntu@13.193.212.134:~/knowledge_graph_api/data backups/data_YYYYMMDD

# 恢復
scp -i ~/.ssh/lightsail_default.pem -r \
  ~/kg/backups/data_<日期> \
  ubuntu@13.193.212.134:~/knowledge_graph_api/data
./devops.sh restart
```

---

## Docker 資料安全

`docker-compose.yml` 的 `volumes: ./data:/app/data`：
- ✅ `deploy` / `restart` 均不刪除 SQLite / embeddings / graph
- ✅ `restart: always`，伺服器重啟後自動恢復

---

## 路徑陷阱

| 路徑 | 有效位置 |
|------|---------|
| `/app/data/` | 容器內（`docker exec` 才能用） |
| `/home/ubuntu/knowledge_graph_api/data/` | host（`devops.sh run` 用這個） |

data 目錄由容器 root 寫入，host ubuntu user 無法直接 rm，需進容器操作：

```bash
./devops.sh run "docker exec knowledge-graph-api sh -c '<指令>'"
```

---

## rsync 手動指令

```bash
rsync -avz --delete \
  -e "ssh -i ~/.ssh/lightsail_default.pem" \
  --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  ~/kg/backend/ \
  ubuntu@13.193.212.134:~/knowledge_graph_api/
```
