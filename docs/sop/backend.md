<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - backend/
verified_against: 98cac27d
-->
# KG Backend Dev Guide

主入口：
- 部署 / env / migration：`docs/sop/deploy.md`
- incident / debug / 502 / users：`docs/sop/debug.md`
- app 與 backend 共用架構：`docs/sop/architecture.md`

參考附錄：
- backend 測試策略：`docs/reference/testing/backend_strategy.md`
- card 格式規範：`docs/reference/card_format.md`
- sync lifecycle：`docs/reference/sync_lifecycle.md`

保留在 backend 目錄的分析資料：
- `backend/docs/analysis/`
  原因：這些 markdown 與分析腳本綁在一起，屬於研究/分析工作區，不是主開發入口。

## 這份文件是幹嘛的

這份文件的角色是 backend 主入口，不是細節大全。

它回答 3 個問題：
- 後端日常開發先看哪裡
- 後端部署/事故去哪裡查
- backend 細節規範放在哪些 references

## 日常開發入口

後端相關任務，優先閱讀順序：

1. `docs/sop/backend.md`
2. `docs/sop/deploy.md` 或 `docs/sop/debug.md`
3. 視需要再讀 `docs/reference/*`

## 常見任務對應

### 跑測試

先看：
- `docs/reference/testing/backend_strategy.md`

標準命令（一律經由 uv，使用 `backend/.venv` 的 cpython-3.13）：

```bash
cd backend
uv run python -m pytest -q
```

不要在 `backend/` 下裸跑 `pytest`：系統 PATH 上有 Homebrew 的
`/opt/homebrew/bin/pytest`（Python 3.14，無 `kg` / `sentry-sdk`），會造成
`test_observability_alerts.py` 等出現假性失敗。`uv run` 配合
`backend/.python-version`（鎖 3.13）+ `pyproject.toml` 的
`requires-python = ">=3.13,<3.14"` 確保用對解譯器。

#### 為何 backend pytest 一律走 `python -m`

症狀：`test_observability_alerts.py` 約 11 個假性失敗、warning 路徑出現
`/opt/homebrew/lib/python3.14/...`。根因是 `.venv/bin/` 下的 console script
（如 `pytest`）shebang 寫死了已失效的絕對 interpreter 路徑（venv 曾在
worktree 間複製/搬移），kernel exec 失敗 → `pytest` 沿 PATH 落到 Homebrew 3.14。
這是 generated console script 的結構性限制，不是 `pytest` 本身可修的行為；
因此 repo 內的 canonical backend 測試入口固定使用 module form。

若你已經遇到壞掉的 console script，可用下列方式重建：

```bash
cd backend && uv sync --reinstall
```

平常跑測試則直接使用：

```bash
cd backend && uv run python -m pytest -q
```

### 查部署 / migration / env

先看：
- `docs/sop/deploy.md`

### 查 502 / caddy / API 不通 / user 狀態

先看：
- `docs/sop/debug.md`

### 查 card 匯入 / 匯出格式

先看：
- `docs/reference/card_format.md`

### 查 sync 與前後端資料流

先看：
- `docs/sop/architecture.md`
- `docs/reference/sync_lifecycle.md`

### 查 Sentry 錯誤追蹤

先看：
- `docs/sop/deploy.md`（env keys + opt-in 模式）
- `backend/src/kg/sentry_init.py`（scrubbing / integrations 實作）

### 查 LLM provider / 換模型 / A/B

- Provider registry：`backend/src/kg/llm/providers.py` —— Gemini / DeepSeek（未來 Qwen·GLM）皆 OpenAI-compatible，加 provider = 加一列 `REGISTRY`。
- 路由 `provider_for(call_type)` 依 env 解析（清單見 `docs/sop/deploy.md` 的「LLM Provider env vars」）。預設全 `gemini`，`embed` 永遠獨立留 Gemini。
- A/B / prompt / provider 品質比較：使用 `lab/llm_eval/` workbench；`kg.llm.ab` 僅保留 deprecated shim。

### 改 API 契約 / auth / 錯誤處理

- FastAPI validation handler 回 422 時必須讓 `RequestValidationError.errors()` 先過 `jsonable_encoder`；Pydantic v2 的 error `ctx` 可能含不可 JSON 序列化物件。
- 可匿名瀏覽但支援登入加權的 endpoint（目前 podcast browse）走 `get_current_user_optional`：無 `Authorization` header 才是 guest；header 存在但 malformed / 非 Bearer / token invalid 必須 401，不可 silent downgrade 成 guest。
- `llm_error_log.record()` / `TrackedLLM._record_failure()` 寫入 provider/SDK failure message 前必須遮罩 bearer/API key/token/password/secret-like 值；不要把 `str(exc)` 直接落 DB。

## 維護規則

- backend 主規則變更：
  優先更新這份文件或 `docs/sop/deploy.md` / `docs/sop/debug.md`
- backend 細節規範變更：
  更新 `docs/reference/*`
- backend 分析腳本或研究輸出：
  留在 `backend/docs/analysis/`

## 文檔邊界

- `docs/sop/backend.md`
  backend 開發主入口
- `docs/sop/deploy.md`
  安全部署、env、migration
- `docs/sop/debug.md`
  事故、健康檢查、debug
- `docs/reference/testing/backend_strategy.md`
  backend 測試體系
- `docs/reference/card_format.md`
  card data format
- `docs/sop/architecture.md`
  iOS + backend 共用資料流與產品脈絡
