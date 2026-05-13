<!-- doc-meta
tier: operational
scope:
  - backend/src/kg
verified_against: c16321f
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

標準命令：

```bash
cd backend
pytest -q
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
