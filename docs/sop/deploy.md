<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - backend/
  - ops/
verified_against: d67bed12
-->
# 後端部署指南

> ⚠️ **生產禁用指令邊界**：本文件所有 ops 動作都受 [`docs/policy/safety.md`](../policy/safety.md) 約束。任何 `docker compose down -v`、`docker system prune -a`、`rm -rf` 涉及 data dir 的操作一律禁止，走 `ops/devops_kg_safe.sh` wrapper。
>
> **過渡狀態（2026-06-15 起）**：正式站已遷到家用常駐機 `standby`，經 Cloudflare Tunnel 對外（無 Caddy / 無 inbound 埠）。Lightsail 容器**已 STOP** 當 rollback。**目前 standby 走手動部署**（§標準部署流程）；`./ops/devops_kg_safe.sh deploy/restart/migrate` 仍寫死 Lightsail，已加 guard（`KG_ALLOW_LIGHTSAIL=1` 才放行），**直接跑會誤推到已停的 Lightsail**——只在回滾時用（§Lightsail rollback 部署流程）。Host topology SoT 見 [`docs/reference/host_topology.md`](../reference/host_topology.md)；服務層部署正本見 butler `~/butler/docs/kg-backend-deployment.md`。

## 核心資訊

- **primary 伺服器**: 家用常駐機 `chenliangyusAir`（M3 Air），user `chenliangyu`，Tailscale `100.118.39.104`，OrbStack docker
- **Edge**: Cloudflare Tunnel（名 `kg-standby`，CF 邊緣終結 TLS）；**無 Caddy、不開 inbound 埠**
- **Domain**: `wordnexus.lol`（CF DNS apex proxied CNAME → tunnel → standby localhost:8000）
- **SSH**: `ssh chenliangyu@100.118.39.104`（主力機公鑰免密碼）
- **primary 工作區**: `~/project/kg/backend`（git 同步，非 rsync）
- **rollback 伺服器**: AWS Lightsail `booksbrowser-kg-api-2gb`，IP `13.193.212.134`，SSH key `~/.secrets/lightsail_kg_prod`，工作區 `~/knowledge_graph_api`（容器 STOP）

---

## 標準部署流程（standby，手動）

> standby 程式碼靠 **git 同步**（非 rsync），部署 = git pull + 重建容器。

```bash
ssh chenliangyu@100.118.39.104
cd ~/project/kg/backend
git pull                                  # 程式碼靠 git 同步
git rev-parse --short HEAD > VERSION       # 更新 version 標記（/api/system/info 讀此檔）
docker compose up -d --build               # 重建+起；restart:always
curl -s http://localhost:8000/api/system/info   # 驗 version 對上
```

- 純 `.py`/`.html` 改動理論可只 `docker compose restart`，但 compose 用 build image，仍建議 `up -d --build`。
- **migration**：app 啟動自動跑（`migration_version` 暴露於 `/api/system/info`）；如需手動 `docker exec knowledge-graph-api <cmd>`。
- **.env 改動**：直接編輯 standby `~/project/kg/backend/.env` 後 `docker compose up -d --build`（容器讀新值需重建，不能只 restart）。⚠ `JWT_SECRET` 必須維持 prod 值，否則全用戶被登出。

### 部署後驗證（standby）

```bash
# 經公網（CF→tunnel→standby）
curl -s https://wordnexus.lol/api/system/info        # 期望 200 + version == git rev-parse --short HEAD
curl -s -o /dev/null -w '%{http_code}\n' https://wordnexus.lol/api/health   # 期望 401（CurrentUser 端點，無 JWT 本就擋）

# DNS 卡舊 IP 時繞過快取直打 CF 邊緣驗服務本身
curl -s --resolve wordnexus.lol:443:104.21.85.113 https://wordnexus.lol/api/system/info

# 直連 standby（繞過 CF，分層驗容器/隧道）
ssh chenliangyu@100.118.39.104 'docker ps --filter name=knowledge-graph-api --format "{{.Status}}"; curl -s -o /dev/null -w "local:8000=%{http_code}\n" http://localhost:8000/api/system/info; pgrep -lf "cloudflared.*tunnel"'
```

`version` 不等於 deploy sha = git pull 沒生效 / VERSION 沒寫 / 容器沒 `--build`。

---

## Lightsail rollback 部署流程（僅回滾時用）

> ⚠️ **僅在 standby 嚴重故障需回滾時執行**。`devops.sh` 仍寫死 Lightsail，受 `KG_ALLOW_LIGHTSAIL=1` guard 保護，避免常態誤推到已停的 Lightsail。回滾完整步驟（含 CF apex 改回 A 記錄）見 [`docs/reference/host_topology.md` §Rollback](../reference/host_topology.md) 與 butler `~/butler/docs/kg-backend-deployment.md §6`。

```
你要做什麼？（回滾到 Lightsail 後的運維）
│
├─ 首次部署 / .env 有改動？
│   └─→ KG_ALLOW_LIGHTSAIL=1 ./devops.sh setup    ← push-env + deploy 一條龍
│
├─ 只是代碼更新（.env 未變）？
│   └─→ KG_ALLOW_LIGHTSAIL=1 ./devops.sh deploy   ← rsync + build + migrate + health
│
├─ 只需重啟（不需重新 build）？
│   └─→ KG_ALLOW_LIGHTSAIL=1 ./devops.sh restart  ← 快 10 倍，保留現有鏡像
│
└─ 只跑 DB migration？
    └─→ KG_ALLOW_LIGHTSAIL=1 ./devops.sh migrate
```

**黃金原則**：`restart` 比 `deploy` 快 10 倍，只有代碼真的改了才 `deploy`。

`deploy` 內部流程：backup → env-check → **寫入 VERSION（git SHA）** → rsync → docker build + **force-recreate**（讓 `/api/system/info` 重新讀 `/app/VERSION`）→ migrate → 容器內 health check → env-drift → **追加 deploy.log** → **外部 smoke verify**（非通過自動中止）。

部署完成後可透過兩種方式確認遠端版本：
- `KG_ALLOW_LIGHTSAIL=1 ./devops.sh status` — 顯示部署版本 + 最近 5 筆部署記錄
- `curl https://wordnexus.lol/api/system/info` — 無需 auth，回傳 version、uptime、migration 狀態

> 📍 **以下到 §特殊情境 SOP 之間的段落（smoke verify / 排查 / Rollback）皆為 Lightsail rollback 語境**（Caddy / `13.193.212.134` / `devops.sh` 流程）。standby primary 的部署後驗證見上方 §標準部署流程；standby 上 TLS 由 CF 邊緣處理，無 Caddy。

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

- `version=X 不等於 deploy_sha=Y` → rsync 沒同步 / VERSION 檔沒寫入 / 容器沒 force-recreate（`/api/system/info` 啟動時快取 `/app/VERSION`）。檢查 `run_remote "cat $REMOTE_DIR/VERSION"` 與 `docker compose ps`。
- `health 000` → 公網斷線、TLS 失敗、Caddy 沒起。`./devops.sh run "sudo systemctl status caddy"`。
- `health 500` → app 起來但 auth middleware 起火。看 `docker compose logs --tail=100`。
- sentry endpoint 期待 401 但拿到 200 → admin auth 失效，立即查 `get_admin_user`。

### Rollback：deploy 失敗後的具體動作

> ⚠️ `devops.sh` **沒有** 內建 rollback 子指令。回滾＝重 deploy 上一個版本 + 視情況還原 data 備份。完整禁用指令邊界見 [`docs/policy/safety.md`](../policy/safety.md)。
>
> 📋 **演練狀態**：以下步驟對照 `devops.sh` 實際指令邏輯撰寫，但**尚未在 staging 跑過完整 dry-run**。首次執行請 step-by-step 對照 `devops.sh` 對應 `cmd_*` 函式（行號見 §Step 註解），不要照抄一鍵跑完。事故發生時優先保留現場再動手。

**Step 0：先確認上次成功的 sha**

```bash
# 本地 deploy.log（位於 ~/kg/backups/deploy.log）
tail -5 ~/kg/backups/deploy.log
# 或遠端 VERSION 檔（容器啟動時讀的）
./devops.sh run "cat ~/knowledge_graph_api/VERSION"
```

每行格式 `<ISO-timestamp> sha=<short-sha> user=<who>`。倒數第二行通常是「上一個會動的版本」。

**Step 1：純程式碼問題（DB schema / data 未動）→ 回滾 code only**

```bash
cd ~/kg
git checkout <previous-sha>      # 例：git checkout c2f2a27
./devops.sh deploy               # 走 fast/full 自動判斷；DEPLOY_FULL=1 強制 full
./devops.sh status               # 確認 VERSION 已切回
```

注意：`devops.sh deploy` 會拒絕 dirty working tree（`DEVOPS_YES=1` 不再 bypass）。先 `git stash` 或在乾淨 tree 上 checkout。

**Step 2：DB migration 已執行 / 資料已被破壞 → 還原 data 備份**

`cmd_backup`（full deploy 自動執行）會先把 `$REMOTE_DIR/data` rsync 到本地 `~/kg/backups/data_<YYYYMMDD_HHMM>/`（rsync 以 `--info=progress2 --human-readable` 顯示總量進度）、跑 SQLite integrity check，再打包成 `~/kg/backups/data_<YYYYMMDD_HHMM>.tar.gz` 並產生 `.sha256`。deploy backup 會排除 `data/_ops_backups/` 與 `data/_ops_world_backups/`，避免把寫入工具產生的備份再備份一次。

```bash
# 1. 找最新的可信備份
ls -lht ~/kg/backups/data_*.tar.gz | head -5
# 2. 驗 checksum
sha256sum -c ~/kg/backups/data_<timestamp>.tar.gz.sha256
# 3. 停容器（不刪 volume！docker compose down -v 是鐵律 7 禁用）
./devops.sh run "cd ~/knowledge_graph_api && docker compose down"
# 4. scp 備份上去並用「原子 mv」還原 — 保留壞掉的 data 以便事故後回查 / 救回
scp -i ~/.ssh/lightsail_kg_prod ~/kg/backups/data_<timestamp>.tar.gz ubuntu@13.193.212.134:/tmp/
./devops.sh run "cd /tmp && tar -xzf data_<timestamp>.tar.gz && \
  sudo mv ~/knowledge_graph_api/data ~/knowledge_graph_api/data.broken.\$(date +%s) && \
  sudo mv data_<timestamp> ~/knowledge_graph_api/data"
# （鐵律 7 精神：data dir 不直接 rm -rf。data.broken.* 之後人工確認再清。）
# 5. 起容器並 health check（compose down 後容器已移除，restart 對不存在的容器無效，必須 up）
./devops.sh run "cd ~/knowledge_graph_api && docker compose up -d"
./devops.sh status
```

**Step 3：smoke verify 失敗但 health 200 → 部署只是部分壞**

通常是 Caddy 路由或 env drift 問題，**不要立即 rollback**：
- `./devops.sh env-drift` 查本地 / 遠端 `.env` 差異
- `./devops.sh logs 100` 看容器 log
- 修完 env / Caddy 後 `./devops.sh restart`（沒改 code 用 restart，比 deploy 快 10 倍）

**何時必須 rollback vs 何時前推修復**

| 情境 | 動作 |
|------|------|
| app 啟動就 crash / health 500 持續 | rollback code（Step 1）|
| 用戶資料被誤刪 / migration 寫壞 | rollback data（Step 2）|
| 只是 .env 或 Caddy 設定漂移 | 前推修（Step 3），rollback 反而更慢 |
| LLM provider 切換造成 4xx | 改 `LLM_PROVIDER_*` env → push-env → restart |

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

### Secret 加密金鑰（`SECRET_ENC_KEY`）與 JWT_SECRET 輪換

`secret_store.py` 對 `enc:` stored secret 做對稱加密。加密根金鑰：

- **`SECRET_ENC_KEY` 已設** → `sha256(SECRET_ENC_KEY)` 派生 Fernet key，加密與 `JWT_SECRET` **完全脫鉤**。
- **`SECRET_ENC_KEY` 未設** → fallback `sha256(JWT_SECRET)`（legacy，零破壞）。

**為什麼建議設獨立 `SECRET_ENC_KEY`**：未設時，輪換 `JWT_SECRET` 會**同時**令所有已簽發 JWT 失效**且**所有 `enc:` stored secret 無法解密（雙重 outage）。設了獨立 `SECRET_ENC_KEY` 後，輪換 `JWT_SECRET` 只影響 JWT，不再波及 secret 解密。

**首次導入 `SECRET_ENC_KEY`（平滑遷移，無需停機）**：
```bash
# 1. 產生強隨機值（任意 ≥32 字元字串即可，sha256 會再派生）
openssl rand -hex 32
# 2. 寫入本地 .env：SECRET_ENC_KEY=<上一步輸出>
#    同步更新 devops.sh 的 REQUIRED_ENV_KEYS（若有強制檢查）
./devops.sh push-env && ./devops.sh deploy
```
解密採多金鑰容錯（當前 `SECRET_ENC_KEY` 先試，失敗退回 legacy `sha256(JWT_SECRET)`），故**舊 `enc:` 值仍可解、新寫入自動改用 `SECRET_ENC_KEY`**，無需一次性 re-encrypt migration。

**警告**：`SECRET_ENC_KEY` 設定後**勿任意變更**——改了它且舊值未 re-encrypt，會落到 legacy fallback；若此時 `JWT_SECRET` 也已輪換，舊值將無金鑰可解。輪換 `SECRET_ENC_KEY` 須另案做 re-encrypt migration。

### App Store 訂閱驗簽必備 env

production 現在預設只接受 signed App Store payload。下列 key 缺一不可：

```bash
# .env 放 HOST 路徑（裸機 ops CLI 直接讀；oscar/felix 同 user 故兩機一致、可攜）
APP_STORE_ROOT_CA_PATH=/Users/chenliangyu/project/kg/backend/certs/apple_root_ca.pem
APP_STORE_CONNECT_ISSUER_ID=<issuer-id>
APP_STORE_CONNECT_KEY_ID=<key-id>
APP_STORE_CONNECT_PRIVATE_KEY_PATH=/Users/chenliangyu/project/kg/backend/certs/AuthKey_<key-id>.p8
```

> **容器部署的路徑分裂（2026-06-16，比照 `KG_DATA_DIR`）**：上列為 **host 路徑**；容器內 app 需 `/app/certs/…`，由 `docker-compose.yml` 的 `environment:` 注入並覆蓋 `env_file`。**勿在 `.env` 寫 `/app/certs`**——那會讓 host 裸機 ops CLI 讀不到 cert，且破壞 `.env` 兩機可攜性。

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

### Sentry 錯誤追蹤 **(SoT)**

Sentry 為 **opt-in** — `SENTRY_DSN` 留空時 SDK 完全 no-op，整層免費。本段為 Sentry 環境變數 / 取樣 / 隱私規範的權威來源；iOS bootstrap 程式碼層 wiring 見 `docs/sop/ios.md §Crash Reporting`，架構層概覽見 `docs/sop/architecture.md §Crash Reporting Layer`。

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

Smoke test: `POST /api/admin/sentry/ping` after deploy to verify DSN wired — endpoint is admin-only, dispatches a `capture_message` + caught `capture_exception` via the SDK and returns `{sent, is_active, event_id}` JSON (never raises). 也可從 `/admin` dashboard 右上「Sentry Ping」按鈕直接觸發，按鈕旁顯示 event_id 前 8 碼或 `inactive (no DSN)`。

#### LLM Provider env vars **(SoT)**

LLM 走可插拔 provider registry（`backend/src/kg/llm/providers.py`）。所有 provider 皆 OpenAI-compatible，切換只改 env、不動 code。

| Env | Default | 用途 |
|-----|---------|------|
| `GEMINI_API_KEY` | （必填）| Gemini key；embedding 一律走 Gemini，故永遠必填 |
| `DEEPSEEK_API_KEY` | （空）| DeepSeek key；路由到 deepseek 時必填 |
| `LLM_PROVIDER_DEFAULT` | `gemini` | 所有 chat call_type 的預設 provider |
| `LLM_PROVIDER_TRANSLATE` | 繼承 DEFAULT | 整組 `translate_*`（quick / phrase / explain）|
| `LLM_PROVIDER_<CALL_TYPE>` | 繼承 group/DEFAULT | 單一 call_type 覆寫，如 `LLM_PROVIDER_JUDGE`、`LLM_PROVIDER_ENRICH` |
| `LLM_PROVIDER_EMBED` | `gemini` | embedding provider；**不繼承 DEFAULT**（DeepSeek 無 embedding 端點）|
| `GEMINI_MODEL` / `DEEPSEEK_MODEL` | registry 預設 | 覆寫該 provider 的 chat model |

- 路由優先序：`LLM_PROVIDER_<CALL_TYPE>` > `LLM_PROVIDER_<GROUP>` > `LLM_PROVIDER_DEFAULT` > `gemini`。
- `LLM_PROVIDER_JUDGE` 同時涵蓋 auto pipeline judge（call_type `judge`）與手動連結判定（call_type `judge_manual`）—— 兩者同屬 `JUDGE` group，一個旋鈕同步切換。
- 遷移 DeepSeek：設 `DEEPSEEK_API_KEY` + `LLM_PROVIDER_DEFAULT=deepseek`（embedding 自動留 Gemini）。分階段可只設 `LLM_PROVIDER_TRANSLATE=deepseek` 先驗證。
- 未知 provider 名、或把 `embed` 路由到無 embedding 能力的 provider → 啟動即 `ValueError`，不 silent fallback。
- A/B / prompt / provider 品質比較：使用 `lab/llm_eval/` workbench（需對應 key）；`kg.llm.ab` 僅保留 deprecated shim。

#### iOS env / Info.plist

iOS 端（`ios/BooksAndVocab/Services/AppCrashReporting.swift`）：
- `Info.plist` `SentryDSN` 鍵為主開關（空 → 全 no-op）
- `Info.plist` `SentryEnvironment` 可覆寫；無覆寫時 `#if DEBUG` → `"debug"`，release → `"production"`
- `releaseName = <bundleId>@<CFBundleShortVersionString>+<CFBundleVersion>`、`dist = CFBundleVersion`（區分共用版號的 TestFlight build）
- `tracesSampleRate`：release 預設 `0.05`、DEBUG 預設 `0.0`；env `SENTRY_TRACES_SAMPLE_RATE`（launch arg / scheme env）可覆寫
- DEBUG build 預設 `enabled=false`；`SENTRY_ENABLED_IN_DEBUG=1` 或 `-sentryTest` launch arg 啟用
- `setUser(id:)` 連動 `authManager.isLoggedIn` — 登出時清除避免多帳戶污染
- HTTP breadcrumb 自動 strip query string、`CancellationError`/`NSURLErrorCancelled` 由 `beforeSend` 丟棄

### 新增 Card Schema 欄位（SQLite）

```bash
# 1. 在 src/kg/cards/model.py 新增欄位（migration SQL 加在 cards/schema.py）
# 2. 在 devops.sh 的 cmd_migrate() 的 MIGRATIONS 清單加 SQL：
#    ALTER TABLE cards ADD COLUMN <col> <type> DEFAULT <val>;
#    （必須 idempotent，SQLite 不支援 IF NOT EXISTS，用 try/except）
./devops.sh deploy
```

### 首次部署 / 全新伺服器（Lightsail；rollback 重建用）

> standby 的機器層建置（OrbStack / cloudflared / launchd）見 butler `~/butler/docs/standby-host-setup.md`，**不走**下方 Lightsail+Caddy 流程。

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
├─ rsync → SSH 問題 → 測試 ssh -i ~/.ssh/lightsail_kg_prod ubuntu@13.193.212.134
├─ docker build → Python 依賴錯誤 → ./devops.sh logs 100
├─ migrate → SQL 語法錯誤 → 確認 MIGRATIONS 是 idempotent
└─ health check 非 200 → FastAPI 啟動失敗 → ./devops.sh logs 100
```

---

## 常用指令速查

`./devops.sh` 子指令完整清單(含 ops-cli / container-script / migrate-run / data_inspect 等進階指令)在 `devops` skill,由其作 SoT。日常常用：`status` / `logs [n]` / `users` / `user-info <id>` / `backup` / `env-check` / `env-drift` / `run "<cmd>"` / `push-env` / `migrate`;觸發 `devops` skill 取完整參考。

---

## 備份 SOP

> 🔒 **異地 S3 backup**：遷移後由 **standby launchd**（`ops/launchd/com.kg.backup.plist`，每日 11:00 台北 = UTC 03:00）跑 `ops/kg_backup.sh`，把 `data/` 串流上傳到 `s3://kg-backups-prod-967512079054/data/<UTC-date>.tar.gz`（同一 PutObject-only IAM principal `kg-backup-agent`）。舊 Lightsail `/etc/cron.d/kg-backup` 已停用。三層備份的過渡現實（L1/L2 失效、L3 移 standby）與從零還原的權威 SOP 見 [`docs/sop/backup.md`](backup.md) / [`docs/sop/backup_restore.md`](backup_restore.md)，不是本段。`devops_kg_safe.sh backup-s3-test`（受 `KG_ALLOW_LIGHTSAIL` guard）為 Lightsail 語境，rollback 時才用。

standby 手動快照：

```bash
ssh chenliangyu@100.118.39.104 'tar czf ~/kg_data_$(date +%Y%m%d).tgz -C ~/project/kg/backend data'
# WAL 一致性需冷快照：先 docker compose stop 再 tar
```

---

## 單 worker 不變式（勿改）

後端**必須以單一 uvicorn worker 部署**。`Dockerfile` 的 CMD 已顯式鎖定 `--workers 1`，**不可移除或調高**。

原因：部分狀態是 **process-local**，不跨 worker 共享：

- `quota_service._reservations` — in-flight 額度預留（PR #538）。多 worker 時每個 worker 各有一份，同用戶請求落在不同 worker 時預留互不可見，額度 over-spend 上限變成 `N_workers × 真實限額`，直接繞過額度防線。
- 同類 process-local state：`translate_service` 的 singleflight dedup、in-memory log capture、rate-limit 計數等。

未來若要 scale-out（多 worker / 多容器），**必須先**把上述狀態改為共享儲存（Redis / DB），才能解除單 worker 限制。

---

## Docker 資料安全

`docker-compose.yml` 的 `volumes: ${KG_DATA_DIR:-./data}:/app/data`（2026-06-16 起 data 移出 git worktree → felix host `~/kg-data`，見下方「路徑陷阱」）：
- ✅ `deploy` / `restart` 均不刪除 SQLite / embeddings / graph
- ✅ `restart: always`，伺服器重啟後自動恢復

---

## 路徑陷阱

| 路徑 | 有效位置 |
|------|---------|
| `/app/data/` | 容器內（`docker exec` 才能用） |
| `~/kg-data/`（felix） | **現役 host data 根**（2026-06-16 移出 worktree；`KG_DATA_DIR` 指向它，host 端 ops CLI 讀此） |
| `/home/ubuntu/knowledge_graph_api/data/` | ~~Lightsail host~~ 已隨 Lightsail terminate（保留為歷史） |

data 目錄由容器 root 寫入，host ubuntu user 無法直接 rm，需進容器操作：

```bash
./devops.sh run "docker exec knowledge-graph-api sh -c '<指令>'"
```

---

## rsync 手動指令（Lightsail only）

> standby 程式碼靠 git 同步（`git pull`），**不用 rsync**。下方僅適用回滾到 Lightsail。

```bash
rsync -avz --delete \
  -e "ssh -i ~/.secrets/lightsail_kg_prod" \
  --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  ~/kg/backend/ \
  ubuntu@13.193.212.134:~/knowledge_graph_api/
```
