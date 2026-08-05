<!-- doc-meta
tier: reference
authority: derived
update_trigger: sop-change
scope:
  - backend/tests/
verified_against: c4a8f8bf1
-->
# KG Backend Testing Strategy

## Goal
建立一套可持續維護的後端測試體系，覆蓋：
- 核心資料一致性（SQLite / JSON 儲存）
- API 契約與授權行為
- 背景 Pipeline 的併發安全與容錯
- 外部整合（Gemini / OAuth）在 mock 下的可預測行為

## Current Test Layers

### 1) Unit tests (純函式/單模組)
- `difficulty.py`: tier mapping 與 Zipf 規則
- `graph/`: link/candidate 去重與狀態邏輯（package：`store` / `links` / `candidates` / `persistence` / `models`）
- `embeddings.py`: 相似度查詢、存在檢查

### 2) Integration tests (本地 I/O + FastAPI in-process)
- `CardStore`：count / soft-delete / modified_since
- `api.py`（`TestClient`）：
  - `/api/vocab` lifecycle（新增、重複、刪除、since 增量）
  - `/api/graph/links` 僅回 active links
  - `/api/translate/*` 成功/失敗路徑
  - `/auth/verify` provider 驗證與 email account linking
  - `/api/admin/*` token gate + stats/logs 回傳
  - `/api/user/*` config 與 account deletion
  - `/api/pipeline` lock/re-entry/failure logging

### 3) Contract & safety checks
- 不允許 pipeline 核心模組出現 `print()`
- 背景任務失敗必須寫入 `ERROR` logs
- concurrent config writes 不得損壞 `users.json`

## Test Isolation Rules
- 每個測試使用 `tmp_path` 建立獨立 data 目錄
- `KG_DATA_DIR/JWT_SECRET/GEMINI_API_KEY` 使用測試預設值
- 外部 API 一律 mock（Gemini/Google/Apple）
- 不觸碰 production data，不依賴網路

## Runbook

```bash
cd backend
uv run python -m pytest -q
```

> `pytest.ini` 已設定只收集 `tests/`，避免手動腳本 (`test_api.py`, `test_option_b.py`) 混入測試流程。

## Visual Test Matrix (Admin)

提供一個可視化測試入口，可在瀏覽器一鍵執行測試並查看 matrix。

- UI:
  - `GET /admin/tests?token=<ADMIN_TOKEN>`
- API:
  - `POST /api/admin/tests/run?token=<ADMIN_TOKEN>`：執行 `python -m pytest tests -vv --maxfail=0 --disable-warnings`
  - `GET /api/admin/tests/last?token=<ADMIN_TOKEN>`：讀取最近一次執行結果

回傳資料包含：
- `totals`：passed / failed / errors / skipped / total
- `matrix`：依測試模組聚合的統計
- `cases`：每個測試案例狀態（`tests/...::...`）
- `stdoutTail` / `stderrTail`：輸出尾段便於快速除錯

操作流程：
1. 設定 `ADMIN_TOKEN` 並啟動 API。
2. 開啟 `/admin/tests?token=...`。
3. 點擊 `Run Tests` 觸發整包測試，結果會即時刷新在 matrix。

## CI Recommendation
- PR gate:
  - `uv run python -m pytest -q`
- Nightly:
  - `uv run python -m pytest -q -k "not slow"`（目前皆可快速執行）
- Optional future:
  - coverage gate (`--cov=src/kg --cov-fail-under=85`)

## Gaps & Next Iteration
- 壓力/負載：高併發 `POST /api/vocab`、pipeline 排隊行為（非功能測試）
- 真實整合環境 smoke：staging 的 Google/Apple token flow
- Property-based tests：
  - parser/renderer round-trip（多語符號、邊界字元）
- Migration safety：
  - SQLite schema migration regression pack
