<!-- doc-meta
tier: operational
scope:
  - backend/src/kg
  - ops
verified_against: a5bcffc
-->
# 後端部署指南

## 核心資訊

- **伺服器**: AWS Lightsail `booksbrowser-kg-api-2gb`（small_3_0, 2GB RAM），IP `13.193.212.134`
- **Domain**: `wordnexus.lol`（Porkbun DNS → Caddy → Docker FastAPI）
- **SSH Key**: `~/.ssh/lightsail_default.pem`
- **本地工作區**: `projects/kg/`
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
cd ~/MPSO/projects/kg

./devops.sh deploy      # rsync + build + migrate + health
./devops.sh status      # 確認健康
./devops.sh logs 50     # 如有問題查日誌
```

`deploy` 內部流程：backup → env-check → **寫入 VERSION（git SHA）** → rsync → docker build → migrate → health check → env-drift → **追加 deploy.log**（非通過自動中止）。

部署完成後可透過兩種方式確認遠端版本：
- `./devops.sh status` — 顯示部署版本 + 最近 5 筆部署記錄
- `curl https://wordnexus.lol/api/system/info` — 無需 auth，回傳 version、uptime、migration 狀態

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
cd ~/MPSO/projects/kg
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
  ~/MPSO/projects/kg/backups/data_<日期> \
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
  ~/MPSO/projects/kg/backend/ \
  ubuntu@13.193.212.134:~/knowledge_graph_api/
```
