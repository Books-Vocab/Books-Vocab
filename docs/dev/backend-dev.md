<!-- doc-meta
tier: operational
scope:
  - backend/src/kg
verified_against: 63ddd0f
-->
# KG Backend Dev Guide

主入口：
- 部署 / env / migration：`docs/dev/deploy.md`
- incident / debug / 502 / users：`docs/dev/debug.md`
- app 與 backend 共用架構：`docs/dev/architecture.md`

參考附錄：
- backend 測試策略：`docs/references/backend_testing_strategy.md`
- card 格式規範：`docs/references/backend_card_format.md`
- sync lifecycle：`docs/references/sync_lifecycle.md`

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

1. `docs/dev/backend-dev.md`
2. `docs/dev/deploy.md` 或 `docs/dev/debug.md`
3. 視需要再讀 `docs/references/*`

## 常見任務對應

### 跑測試

先看：
- `docs/references/backend_testing_strategy.md`

標準命令（一律經由 uv，使用 `backend/.venv` 的 cpython-3.13）：

```bash
cd backend
uv run pytest -q
```

不要在 `backend/` 下裸跑 `pytest`：系統 PATH 上有 Homebrew 的
`/opt/homebrew/bin/pytest`（Python 3.14，無 `kg` / `sentry-sdk`），會造成
`test_observability_alerts.py` 等出現假性失敗。`uv run` 配合
`backend/.python-version`（鎖 3.13）+ `pyproject.toml` 的
`requires-python = ">=3.13,<3.14"` 確保用對解譯器。

#### 若 `uv run pytest` 仍誤用 Python 3.14

症狀：`test_observability_alerts.py` 約 11 個假性失敗、warning 路徑出現
`/opt/homebrew/lib/python3.14/...`。根因是 `.venv/bin/` 下的 console script
（如 `pytest`）shebang 寫死了已失效的絕對 interpreter 路徑（venv 曾在
worktree 間複製/搬移），kernel exec 失敗 → `pytest` 沿 PATH 落到 Homebrew 3.14。

修法（重建 venv 內所有 console script，不需動 repo）：

```bash
cd backend && uv sync --reinstall
```

或直接以明確寫法跑測試，繞過 console-script shebang：

```bash
backend/.venv/bin/python -m pytest -q
```

### 查部署 / migration / env

先看：
- `docs/dev/deploy.md`

### 查 502 / caddy / API 不通 / user 狀態

先看：
- `docs/dev/debug.md`

### 查 card 匯入 / 匯出格式

先看：
- `docs/references/backend_card_format.md`

### 查 sync 與前後端資料流

先看：
- `docs/dev/architecture.md`
- `docs/references/sync_lifecycle.md`

### 查 Sentry 錯誤追蹤

先看：
- `docs/dev/deploy.md`（env keys + opt-in 模式）
- `backend/src/kg/sentry_init.py`（scrubbing / integrations 實作）

## 維護規則

- backend 主規則變更：
  優先更新這份文件或 `docs/dev/deploy.md` / `docs/dev/debug.md`
- backend 細節規範變更：
  更新 `docs/references/*`
- backend 分析腳本或研究輸出：
  留在 `backend/docs/analysis/`

## 文檔邊界

- `docs/dev/backend-dev.md`
  backend 開發主入口
- `docs/dev/deploy.md`
  安全部署、env、migration
- `docs/dev/debug.md`
  事故、健康檢查、debug
- `docs/references/backend_testing_strategy.md`
  backend 測試體系
- `docs/references/backend_card_format.md`
  card data format
- `docs/dev/architecture.md`
  iOS + backend 共用資料流與產品脈絡
