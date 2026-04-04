# Pipeline Telemetry — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 記錄每次 pipeline 執行的 run/step 層級 telemetry，在 admin 用戶詳情頁可視化。
**Architecture:** 新增 pipeline_log.py（singleton SQLite，同 token_tracker/judge_log pattern），instrument pipeline_service.py，新增 admin API + 前端 section。
**Tech Stack:** SQLite、FastAPI、vanilla JS

---

## Task 1: Pipeline Log Module

**Files:**
- Create: `backend/src/kg/pipeline_log.py`
- Test: `backend/tests/test_pipeline_log.py`

- [ ] **Step 1: 寫 failing test**
```python
# test_pipeline_log.py
def test_start_and_end_run(tmp_path):
    """Start a run, add steps, end it — verify full record."""
    
def test_start_step_and_end_step(tmp_path):
    """Step records include name, status, timing, items."""

def test_end_run_sets_status_and_ended_at(tmp_path):
    """Ending a run updates status and ended_at."""

def test_get_runs_returns_newest_first(tmp_path):
    """Runs ordered by started_at DESC."""

def test_get_runs_filters_by_user(tmp_path):
    """Only returns runs for specified user_id."""
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `python -m pytest backend/tests/test_pipeline_log.py -v`

- [ ] **Step 3: 實作 `pipeline_log.py`**

Module API:
```python
def start_run(run_id: str, user_id: str, notebook_id: str, trigger: str) -> None:
    """Insert a new pipeline run with status='running', steps='[]'."""

def start_step(run_id: str, name: str) -> None:
    """Append a step entry with status='running' to the run's steps JSON."""

def end_step(run_id: str, name: str, *, status: str = "ok", items: int = 0, error: str | None = None) -> None:
    """Update the step's status, ended_at, items, error in the steps JSON."""

def end_run(run_id: str, status: str) -> None:
    """Set ended_at and status on the run."""

def get_runs(user_id: str, *, limit: int = 20) -> list[dict]:
    """Return recent runs for a user, newest first. Parses steps JSON."""
```

Schema:
```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    notebook_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    steps TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_pr_user ON pipeline_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_pr_started ON pipeline_runs(started_at);
```

Pattern: singleton `_conn` + `_lock` + `_get_conn()`，同 `token_tracker.py`。

為了可測試，提供 `_reset()` 和接受可選 `db_path` 參數（同 judge_log pattern）。

- [ ] **Step 4: 跑 test 確認通過**
- [ ] **Step 5: Commit** `api: add pipeline_log module for run/step telemetry`

---

## Task 2: Instrument Pipeline Service

**Files:**
- Modify: `backend/src/kg/pipeline_service.py`
- Test: `backend/tests/test_pipeline_telemetry.py`（integration test）

- [ ] **Step 1: 寫 failing test**
```python
def test_pipeline_records_run_and_steps(tmp_path, monkeypatch):
    """After pipeline completes, pipeline_log has a run with 4 steps."""
```

- [ ] **Step 2: 跑 test 確認失敗**

- [ ] **Step 3: 修改 `pipeline_service.py`**

Changes:
1. `run_pipeline_background`: 在開頭生成 `run_id = uuid.uuid4().hex[:12]`，呼叫 `pipeline_log.start_run()`
2. `_run_step`: 新增 `run_id: str | None = None` kwarg。若有 run_id，在 coro 前呼叫 `start_step`，完成後呼叫 `end_step`
3. 每個 step 函數加 `return int`（items processed）：
   - `_step_enrich` → return `updated`
   - `_step_embed_and_judge` → return `len(created)`
   - `_step_difficulty` → return `scored`
   - `_step_external_sync` → return `stats["created"] + stats["updated"]`（or 0 if skipped）
4. `_run_step` 捕獲 step 回傳值作為 items
5. `run_pipeline_background` 結尾呼叫 `pipeline_log.end_run(run_id, "completed")` 或 `"failed"`

Key constraint: `_run_step` 的 error handling 不變（catch + log + continue），只是額外記錄到 pipeline_log。

- [ ] **Step 4: 跑 test 確認通過**
- [ ] **Step 5: Commit** `api: instrument pipeline with telemetry logging`

---

## Task 3: Admin API Endpoint

**Files:**
- Modify: `backend/src/kg/admin_wiring.py`
- Modify: `backend/src/kg/routers/admin.py`
- Test: `backend/tests/test_pipeline_log.py`（加 endpoint test）

- [ ] **Step 1: 加 endpoint test**
```python
def test_pipeline_runs_endpoint_returns_data(tmp_path):
    """GET /api/admin/pipeline-runs?user_id=... returns runs list."""
```

- [ ] **Step 2: Wire endpoint**
- `admin_wiring.py`: 新增 `admin_pipeline_runs` handler
- `routers/admin.py`: 註冊 `GET /api/admin/pipeline-runs`
- Endpoint: `GET /api/admin/pipeline-runs?user_id=...&limit=20`

Response:
```json
{
  "user_id": "xxx",
  "runs": [{
    "run_id": "abc",
    "trigger": "background",
    "started_at": "...",
    "ended_at": "...",
    "status": "completed",
    "duration_s": 12.3,
    "steps": [...]
  }]
}
```

`duration_s` 由 handler 計算：`(ended_at - started_at).total_seconds()`

- [ ] **Step 3: 跑 test 確認通過**
- [ ] **Step 4: Commit** `api: add pipeline-runs admin endpoint`

---

## Task 4: Frontend — Pipeline History Section

**Files:**
- Modify: `backend/src/kg/admin_user_detail.html`

- [ ] **Step 1: 加 Pipeline History section**

在 Graph Playback 下方加新 section：
```html
<div class="section-block">
  <div class="section-title">Pipeline History</div>
  <div id="pipeline-history"></div>
</div>
```

- [ ] **Step 2: 加 JS 載入與渲染邏輯**

在 `loadPage()` 中新增 fetch `/api/admin/pipeline-runs?user_id=...`

渲染：每個 run 一個可展開的 card：
- 摘要行：trigger badge、時間、status badge（✓ / ✗ / ⏳）、duration
- 展開區：每步一行 — name、status、duration、items、error（如有）

Steps status 顏色：
- ok → `var(--ink)` 
- failed → `var(--dev)` (紅)
- skipped → `var(--sub)` (灰)
- running → `var(--ink-light)`

- [ ] **Step 3: 確認 section 正確渲染（empty state: 「無 Pipeline 紀錄」）**
- [ ] **Step 4: Commit** `api: add pipeline history to admin user detail page`

---

## Task 5: Update CLAUDE.md + Deploy

- [ ] **Step 1: 更新 `CLAUDE.md`**

在 `Implemented Product Surface` 的 Backend 區塊加入：
```
pipeline telemetry（pipeline_log.db — per-run/step timing + status + items, admin UI history view）
```

- [ ] **Step 2: Deploy + verify on production**
