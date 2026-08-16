<!-- doc-meta
tier: reference
authority: derived
update_trigger: sop-change
scope:
  - backend/tests/
verified_against: 4c0efb3cc
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

## Backend Quality CI

`.github/workflows/backend-quality.yml` 只在 `backend/**` 或該 workflow 變更時於
push / pull request 觸發；另有每日 02:17 UTC 的 nightly schedule。文件或 iOS-only
變更不會啟動 push / pull request backend runner。job `backend-quality` 在乾淨 runner
執行：

1. checkout full history，固定 uv 版本後執行 `uv sync --locked`。
2. 以 module form 執行測試與 coverage data；push / pull request 執行完整 suite：
   `uv run python -m pytest -q --cov=src/kg --cov-report=term-missing --cov-report=xml:coverage.xml`；
   nightly schedule 使用同一命令加 `-k "not slow"` 的 non-slow lane。coverage data
   透過 `COVERAGE_FILE=${{ runner.temp }}/backend-quality/.coverage` 寫入 runner temp，
   不改寫 repo 內既有的 `backend/.coverage`。
3. 以 `uv run python -m coverage report --fail-under=85` 執行 coverage threshold，並
   明確拒絕缺少或空白的 `coverage.xml`。
4. 以 `uv run ruff check src tests` 執行 static quality check。

pytest 的既有 full-suite failure 保持為 `test-failure`，不以 `continue-on-error`
偽造成功；coverage threshold failure 標為 `coverage-failure`，Ruff failure 標為
`ruff-failure`。checkout、uv setup、provenance、locked sync 或未產生明確 step
結果時標為 `infrastructure-inconclusive`。所有非 `pass` 分類都以非零結束，讓
GitHub job 維持紅燈而不是把不可判定狀態當綠燈。

每次執行都嘗試上傳 `backend-quality-${GITHUB_SHA}` artifact（即使 quality step 失敗）；
缺少 artifact 檔案時以 error fail-closed。artifact 只包含 `coverage.xml` 與
provenance，不上傳 `.coverage`；provenance 包含 `HEAD_SHA` / `GITHUB_SHA`、
`LOCK_BLOB_SHA`、`LOCK_SHA256`、uv 版本、`PYTHON_VERSION`、`PYTHON_EXECUTABLE`、
run id 與 attempt，並將 Python interpreter 寫入 job summary。這使 coverage 證據不能
脫離被驗證的 HEAD、interpreter 或 `backend/uv.lock`。

## Gaps & Next Iteration
- 壓力/負載：高併發 `POST /api/vocab`、pipeline 排隊行為（非功能測試）
- 真實整合環境 smoke：staging 的 Google/Apple token flow
- Property-based tests：
  - parser/renderer round-trip（多語符號、邊界字元）
- Migration safety：
  - SQLite schema migration regression pack
