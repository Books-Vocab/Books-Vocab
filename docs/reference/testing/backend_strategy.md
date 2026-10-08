<!-- doc-meta
tier: reference
authority: derived
update_trigger: sop-change
scope:
  - backend/tests/
verified_against: af224fa2d86d76db01efe47b092706c80988e82e
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
- 受管 router 的 `async def` route 不得在 event loop 直接呼叫 store／SQLite／`pipeline_log`／LLM（`tests/test_async_route_blocking_guard.py` 的 AST guard；新模組在 `GUARDED_ROUTE_MODULES` 加一列）
- 背景任務失敗必須寫入 `ERROR` logs
- concurrent config writes 不得損壞 `users.json`
- `orphan_scan --fix`（含 dry-run）在 `users.json` 缺失／損毀／空而 log 表仍有資料時必須 fail closed（`UserRegistryUnavailable`、CLI exit 1、零刪除；`tests/test_orphan_scan.py`）

## Test Isolation Rules
- 每個測試使用 `tmp_path` 建立獨立 data 目錄
- `KG_DATA_DIR` 每個 pytest process 專屬：`tests/conftest.py` 在任何 `kg` import 前覆寫（含繼承值）為新的 `tempfile.mkdtemp(prefix="kg_test_")`，process 結束時刪除；import 時建立的全域 `app` 的 `.worker.lock` 與 startup reaper 只碰這個目錄，並行 run（其他 worktree、container 內 admin test matrix）互不干擾。測試模組不得在 module level 改寫它（`tests/test_data_dir_isolation.py` 守護）
- `JWT_SECRET/GEMINI_API_KEY` 使用測試預設值
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
  - `GET /admin/tests`（先於 `/admin/login` 登入取得 cookie）
- API:
  - `POST /api/admin/tests/run`（`Authorization: Bearer <ADMIN_TOKEN>`）：執行 `python -m pytest tests -vv --maxfail=0 --disable-warnings`
  - `GET /api/admin/tests/last`（`Authorization: Bearer <ADMIN_TOKEN>`）：讀取最近一次執行結果

回傳資料包含：
- `totals`：passed / failed / errors / skipped / total
- `matrix`：依測試模組聚合的統計
- `cases`：每個測試案例狀態（`tests/...::...`）
- `stdoutTail` / `stderrTail`：輸出尾段便於快速除錯

操作流程：
1. 設定 `ADMIN_TOKEN` 並啟動 API。
2. 經 `/admin/login` 登入後開啟 `/admin/tests`。
3. 點擊 `Run Tests` 觸發整包測試，結果會即時刷新在 matrix。

## Backend Quality CI

`.github/workflows/backend-quality.yml` 是 reusable workflow。`main` 的 direct push 只會在
`backend/**`、`.claude/skills/devops/SKILL.md` 或該 workflow 變更時啟動；另有每日
02:17 UTC 的 nightly schedule。PR 則由 `pr-gate` 依 `ops/ci_scope_router.sh` 選出的
backend lane 呼叫；該 router 將 backend-facing DevOps skill roster 視為 backend
confidence。文件或 iOS-only 變更本身不會選到 backend lane；`required`／`confidence`
的總體語義以 [`delivery_model.md`](../delivery_model.md#required-merge-gate-confidence-fan-out)
為準。job `backend-quality` 在乾淨 runner 執行：

1. checkout full history，固定 uv 版本後執行 `uv sync --locked`；再以 apt 安裝 `ffmpeg`
   （Debian 套件同時提供 `ffmpeg`／`ffprobe`，`tests/test_podcast_preview_backfill.py`
   缺任一就 skip）並探測兩者版本。job 固定 `runs-on: ubuntu-24.04` 而非會移動的
   `ubuntu-latest`，apt archive 與 ffmpeg 系列隨 image 固定；實際版本寫入 provenance
   的 `FFMPEG_VERSION`。安裝失敗歸類為 `infrastructure-inconclusive`，不執行測試。
2. 以 module form 執行測試與 coverage data；push、pull request 與 nightly schedule
   都執行同一個完整 suite，不依 event 分支或以 `-k`／`-m` 取子集：
   `uv run python -m pytest -q -rs --skip-allowlist=tests/skip_allowlist.json --cov=src/kg --cov-report=term-missing --cov-report=xml:coverage.xml`。
   `-rs` 列出每個 skip 原因；`--skip-allowlist`（`backend/tests/_skip_allowlist_gate.py`，
   由 `tests/conftest.py` 載入）讓任何未列入 `tests/skip_allowlist.json` 的 skip、以及
   已列入卻實際執行的過期條目都使 pytest 以非零結束。每個條目必須是
   `{"nodeid", "issue", "reason"}`，`issue` 必須連到 Books-Vocab Issue；未帶此參數的
   本機執行不受影響。CI 的預期是 0 skipped。
   nightly 是對同一 suite 的 drift 偵測，不是較窄的 lane。contract test 以假 `uv`
   逐 event 實際執行該 step，比對各 event 的 pytest argv 相同且不含選取參數。
   coverage data 透過 `COVERAGE_FILE=${{ runner.temp }}/backend-quality/.coverage`
   寫入 runner temp，不改寫 repo 內既有的 `backend/.coverage`。
3. 以 `uv run python -m coverage report --fail-under=85` 執行 coverage threshold，並
   明確拒絕缺少或空白的 `coverage.xml`。
4. 以 `uv run ruff check src tests` 執行 static quality check；`backend/pyproject.toml`
   宣告 Ruff 相容版本約束，`backend/uv.lock` 將解析版本固定為 `0.16.3`；兩者須保持一致，
   避免依賴 runner 的外部工具快取。`backend/tests/test_backend_quality_workflow_contract.py`
   會同時驗證 workflow contract、locked toolchain、Ruff resolved version、
   coverage/artifact provenance 與 failure classification。

pytest 的既有 full-suite failure 保持為 `test-failure`，不以 `continue-on-error`
偽造成功；coverage threshold failure 標為 `coverage-failure`，Ruff failure 標為
`ruff-failure`。checkout、uv setup、provenance、locked sync、ffmpeg 安裝或未產生明確 step
結果時標為 `infrastructure-inconclusive`。所有非 `pass` 分類都以非零結束，讓
GitHub job 維持紅燈而不是把不可判定狀態當綠燈。

每次執行都嘗試上傳 `backend-quality-${GITHUB_SHA}` artifact（即使 quality step 失敗）；
缺少 artifact 檔案時以 error fail-closed。artifact 只包含 `coverage.xml` 與
`backend/ci-artifacts/backend-quality-provenance.txt`、
`backend/ci-artifacts/backend-quality-verdict.txt`，不包含 `.coverage`；也就是
coverage XML + provenance + verdict。provenance 包含 `HEAD_SHA` / `GITHUB_SHA`、
`LOCK_BLOB_SHA`、`LOCK_SHA256`、uv 版本、`PYTHON_VERSION`、`PYTHON_EXECUTABLE`、
`FFMPEG_VERSION`、run id 與 attempt，並將 Python interpreter 寫入 job summary。這使 coverage 證據不能
脫離被驗證的 HEAD、interpreter 或 `backend/uv.lock`。

同一 workflow 的 job `image-lock` 驗證 production image 與 lock 一致（#2088）：以
`backend/Dockerfile` build image，再執行
`uv run --locked python scripts/check_image_lock.py --image kg-api:image-lock --allow-group image-test`。
腳本在容器內讀 `importlib.metadata` 與 PEP 508 marker 環境，從 `backend/uv.lock` 的 root
project 依該環境展開 runtime closure；缺少 runtime 依賴、版本與 lock 不同、lock 未涵蓋的
distribution（base image 的 `pip` 除外）或重複安裝都以 exit 1 失敗。Visual Test Matrix 在
容器內跑 pytest，所以 `pyproject.toml` 有專用 dependency group `image-test`（pytest、
pytest-asyncio）：Dockerfile 以 `uv export --no-default-groups --group image-test` 只匯出它，
腳本的 `--allow-group` 也只接受 `image-test`（`dev` 會被 argparse 拒絕）。因此 `dev` 之後
新增的任何工具（Ruff、pytest-cov、未來的 linter／debugger）都不會進 image，若出現即為
`unexpected`。本地等價：在 `backend/` 先
`docker build -t <tag> .`，再以同一命令帶 `--image <tag>`。

## Gaps & Next Iteration
- 壓力/負載：高併發 `POST /api/vocab`、pipeline 排隊行為（非功能測試）
- 真實整合環境 smoke：staging 的 Google/Apple token flow
- Property-based tests：
  - parser/renderer round-trip（多語符號、邊界字元）
- Migration safety：
  - SQLite schema migration regression pack
