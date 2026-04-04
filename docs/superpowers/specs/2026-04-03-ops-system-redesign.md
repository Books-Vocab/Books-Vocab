# Ops System Redesign — Spec

## 問題

1. **關注點混合** — CLAUDE.md 同時承載 dev 規則和 ops 指引，開發場景載入不必要的 ops 內容，ops 場景缺乏完整指引。
2. **devops skill 是空殼** — `disable-model-invocation: true`，僅為靜態參考，無法被觸發。
3. **遠端執行的引號地獄** — `container-run` 經過 SSH → docker exec 多層 shell，複雜 Python 腳本轉義幾乎必敗。
4. **高頻查詢無封裝** — 查用戶額度、活躍用戶等操作每次都即興組裝 SQL。
5. **Admin 登入不便** — `/admin` 依賴難記的 ADMIN_TOKEN，無登入頁面，cookie 過期後無法輕鬆重新進入。

## 解法

### 1. CLAUDE.md 拆分

**移入 devops skill 的內容：**
- `## 生產環境操作` 整段（safe entrypoint、指令表、data_inspect 用法）
- `## 對話啟動流程` 第 3 點（preflight/backup 時機規則）

**留在 CLAUDE.md 的：**
- Identity（保留，dev 也需要知道 project key 等基本資訊）
- 對話啟動流程（第 1、2 點）
- Skill 系統表（更新 devops 的觸發描述為寬範圍）
- 鐵律
- Git
- iOS 編譯
- iOS UI Design System
- Implemented Product Surface（含 Ops 一行的 surface inventory，這不是指令參考）
- Reference Docs
- Doc Freshness 規則

### 2. devops skill 升級

**Frontmatter：**
```yaml
---
name: devops
description: "KG 生產環境運維 — 部署、狀態、用戶查詢、額度、遠端操作、系統健康"
allowed-tools: Bash, Read, Grep
---
```

移除 `disable-model-invocation: true`，使 skill 可被觸發。

**內容結構：**
1. Identity（遠端相關：server、remote、domain、container、port）
2. 安全規則（preflight/backup 時機，從 CLAUDE.md 移入）
3. 指令參考（現有 + 新增的 ops-cli、container-script）
4. 高頻操作範例（user-quota、active-users 等一步到位的用法）
5. 快速診斷流程圖
6. 緊急恢復
7. Deep reference

**觸發範圍（寬）：**
部署、重啟、logs、status、backup、migration、任何涉及遠端伺服器、用戶資料查詢、生產環境互動、額度查詢、系統健康檢查。

### 3. ops_cli.py — 部署在 container 內的查詢工具

**位置：** `backend/ops_cli.py`
- Dockerfile 新增 `COPY ops_cli.py ./`，部署後路徑為 `/app/ops_cli.py`
- rsync 自動涵蓋（rsync 源已是 `backend/`）

**子指令：**

| 子指令 | 用途 | 資料來源 |
|--------|------|----------|
| `user-quota <uid>` | 24h 額度 + 逐時明細 | token_usage.db |
| `user-stats <uid>` | 單字庫統計（總數/有效/已刪/最近活動） | users/<uid>/cards.db |
| `quota-overview` | 全用戶 24h 額度總覽（只查近 24h） | token_usage.db |
| `active-users [hours]` | 近 N 小時活躍用戶 | token_usage.db |
| `db-query <uid> "<sql>"` | 對用戶 cards.db 跑任意 SQL | users/<uid>/cards.db |

**設計原則：**
- 直接讀 SQLite，不依賴 app 運行狀態
- 定價常數硬編碼（與 quota_service.py 一致：INPUT=0.10, OUTPUT=0.40, EMBED=0.00025 per 1M tokens）
- 額度上限從環境變數讀（PRO_DAILY_LIMIT_USD=0.30, FREE_DAILY_LIMIT_USD=0.03）
- Data dir：container 內從 `KG_DATA_DIR` 環境變數讀（Dockerfile 已設 `/app/data`）；本地測試透過腳本自身路徑推算 `Path(__file__).resolve().parent / "data"`（即 `backend/data`）
- 輸出格式化表格，人類可讀
- 單一檔案，無外部依賴（純 stdlib）

**定價公式（與 quota_service.py 完全一致）：**
- embed: `input_tokens / 1_000_000 * 0.00025`
- 其他: `input_tokens / 1_000_000 * 0.10 + output_tokens / 1_000_000 * 0.40`

**token_usage.db schema：**
```sql
token_usage(id, user_id, call_type, input_tokens, output_tokens, created_at)
-- created_at: ISO 8601 UTC string
-- call_type: translate_quick, translate_phrase, translate_explain, judge, enrich, embed, manual_link_judge
```

### 4. devops.sh 新增子指令

**`ops-cli`** — 捷徑，自動 docker exec：
```bash
# Agent 一律走 safe wrapper
./ops/devops_kg_safe.sh ops-cli user-quota 000287...0228
# 底層等同: ssh → docker exec knowledge-graph-api python3 /app/ops_cli.py user-quota 000287...0228
```

**`container-script`** — 萬用，本地腳本上傳到 container 執行：
```bash
./ops/devops_kg_safe.sh container-script /tmp/analysis.py [args...]
# 流程: scp → docker cp → docker exec → 清理 remote /tmp 暫存
```

實作細節：
- scp 本地檔案到 remote `/tmp/<basename>`
- `docker cp` 進 container `/tmp/<basename>`
- `docker exec python3 /tmp/<basename> [args]`
- 清理 remote `/tmp/<basename>`（container 內的 /tmp 隨重啟消失，不需主動清）

安全邊界：`container-script` 的安全模型等同 `container-run`，依賴容器隔離和 appuser (UID 1000) 權限，不做腳本內容審查。副檔名限制（`.py`、`.sh`）僅為防止誤傳。

### 5. devops_kg_safe.sh 同步

白名單新增 `ops-cli` 和 `container-script`。

### 6. Admin 密碼登入

**現狀：**
- `/admin` 受 `get_admin_user` dependency 保護（router 層級 `dependencies=[Depends(get_admin_user)]`）
- 認證方式：Authorization header / ?token= query param / admin_session cookie
- 無登入頁面，cookie 過期後必須手動拼 token URL

**改動：**

**6a. 獨立 login router（不帶 admin dependency）：**

`/admin/login` 註冊在**獨立的 router** 上，不掛 `get_admin_user` dependency：
```python
# routers/admin.py
login_router = APIRouter()  # 無 dependencies

@login_router.get("/admin/login")   # 返回登入頁面
@login_router.post("/admin/login")  # 驗證密碼
```
在 `api.py` 的 `create_app()` 中，`login_router` 在 `admin_router` 之前註冊。

- GET：返回登入頁面（密碼欄 + 登入按鈕）
- POST：驗證密碼，成功則設 30 天 `admin_session` cookie → 302 到 `/admin`

**6b. HTML vs API 端點的未認證行為分離：**

新增 `get_admin_user_or_redirect` dependency，僅用於 HTML 端點（`/admin`、`/admin/tests`）：
- 認證通過 → 放行
- 認證失敗 → `RedirectResponse("/admin/login", 302)` 而非 raise 403

API 端點（`/api/admin/*`）維持現有 `get_admin_user`，繼續返回 403 JSON。

實作方式：將現有 `build_admin_router()` 拆為兩組路由：
- HTML 路由用 `dependencies=[Depends(get_admin_user_or_redirect)]`
- API 路由用 `dependencies=[Depends(get_admin_user)]`（不變）

**6c. 環境變數：**

新增 `ADMIN_PASSWORD`：
- `settings.py` dataclass 加 `admin_password: str = ""`
- `load_settings()` 加 `admin_password=os.getenv("ADMIN_PASSWORD", "")`
- 驗證使用 `hmac.compare_digest` 防 timing attack
- **若 `ADMIN_PASSWORD` 為空**：登入頁顯示「密碼登入未啟用，請使用 token 認證」，POST 直接返回 403

**保留現有機制：**
- ADMIN_TOKEN 繼續用於 API 呼叫和程式化存取
- cookie 機制完全不變（密碼登入成功後設的是同一個 `admin_session` cookie）
- 兩套並存，密碼登入只是多一個取得 cookie 的入口

**登入頁面：**
- 極簡 HTML，內嵌在 Python 字串中（與現有 admin_dashboard.html 同模式）
- 密碼錯誤顯示 inline 錯誤訊息
- 成功後 302 redirect 到 `/admin`

## 不做的事

- 不重構 devops.sh 整體架構（只加子指令）
- 不改現有 Admin API 端點的認證邏輯
- 不改 data_inspect.py（它是本地工具，職責不同）
- 不加 ops_cli.py 的寫入操作（只讀）
- 不做密碼 hash 持久化（密碼從環境變數讀，與 ADMIN_TOKEN 同等級）

## 驗證標準

1. `python3 backend/ops_cli.py --help` 顯示所有子指令
2. `python3 backend/ops_cli.py user-quota <uid>` 在本地（backend/data）和 container 內都能跑
3. `./ops/devops_kg_safe.sh ops-cli user-quota <uid>` 一步到位取得結果
4. `./ops/devops_kg_safe.sh container-script /tmp/test.py` 成功執行並清理
5. CLAUDE.md 的 `## 生產環境操作` 段落已移除，ops 指令參考只在 devops skill 中
6. devops skill 被正確觸發於 ops 相關對話
7. `/admin/login` 頁面可用密碼登入並取得 cookie
8. `/admin` 未認證時 redirect 到 `/admin/login`
9. 現有 ADMIN_TOKEN 認證仍正常運作
