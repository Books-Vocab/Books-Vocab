# Graph Density Chart — Admin Frontend

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 在 admin dashboard 新增 link density vs cumulative cards 圖表，視覺化知識圖譜成長曲線。
**Architecture:** 新增一個 admin API endpoint 回傳時序資料，前端用 Chart.js 渲染折線圖。
**Tech Stack:** Chart.js CDN、FastAPI endpoint、SQLite + JSON 讀取

---

## 背景

- Admin 前端：純 HTML + vanilla JS（`admin_dashboard.html`，~1047 行）
- 無現有 chart library，需引入 Chart.js CDN
- 資料來源：`cards.db`（card.created_at）+ `graph_<notebook>.json`（link.created_at）
- Admin API pattern：`/api/admin/*`，需 admin auth（`Depends(get_admin_user)`）

## 資料格式

API 回傳：
```json
{
  "user_id": "xxx",
  "notebook_id": "default",
  "points": [
    {"ts": "2025-12-01T...", "event": "card", "cum_cards": 1, "cum_links": 0, "density": 0.0},
    {"ts": "2025-12-01T...", "event": "link", "cum_cards": 1, "cum_links": 1, "density": 1.0},
    ...
  ]
}
```

計算邏輯：
1. 從 cards.db 取所有 active cards 的 `(id, created_at)`
2. 從 graph_*.json 取所有 active links 的 `(created_at)`
3. 合併按 created_at 排序
4. 逐筆累計：每個事件點算 `density = cum_links / cum_cards`

---

### Task 1: Backend API Endpoint

**Files:**
- Create: `backend/src/kg/admin_graph_density.py`
- Modify: `backend/src/kg/admin_wiring.py` — 新增 wiring
- Modify: `backend/src/kg/routers/admin.py` — 註冊 endpoint
- Test: `backend/tests/test_admin_graph_density.py`

- [ ] **Step 1: 寫 failing test**
```python
# test_admin_graph_density.py
def test_graph_density_returns_sorted_points(tmp_path):
    """Given cards and links with known timestamps, density is correctly computed."""
    # Setup: create cards.db with 3 cards, graph json with 2 links
    # Assert: points sorted by ts, density = cum_links / cum_cards at each point
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `cd projects/kg && python -m pytest backend/tests/test_admin_graph_density.py -v`
Expected: ImportError (module doesn't exist)

- [ ] **Step 3: 寫 `admin_graph_density.py`**
```python
def compute_graph_density(user_dir: Path, notebook_id: str = "default") -> dict:
    """Read cards.db + graph json, return time-series density data."""
    # 1. Query cards.db: SELECT id, created_at FROM cards WHERE deleted=0 AND notebook_id=?
    # 2. Read graph_{notebook_id}.json, extract active links with created_at
    # 3. Merge events, sort by timestamp
    # 4. Cumulative scan: density = cum_links / cum_cards
    # Return {"user_id", "notebook_id", "points": [...]}
```

- [ ] **Step 4: 跑 test 確認通過**

- [ ] **Step 5: Wire endpoint**
- `admin_wiring.py`: 新增 `admin_graph_density` handler function
- `routers/admin.py`: 在 `build_api_admin_router` 加 `admin_graph_density` 參數
- Endpoint: `GET /api/admin/graph-density?user_id=...&notebook_id=default`

- [ ] **Step 6: Commit**
`api: add graph density endpoint for admin`

---

### Task 2: Frontend Chart

**Files:**
- Modify: `backend/src/kg/admin_dashboard.html`

- [ ] **Step 1: 加 Chart.js CDN**
在 `<head>` 加：
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
```

- [ ] **Step 2: 加 chart section**
在 dashboard 適當位置（stats cards 下方）加：
```html
<div class="section" id="density-section" style="display:none">
  <h3>Graph Density</h3>
  <div style="display:flex;gap:8px;margin-bottom:12px;">
    <select id="density-user"></select>
    <select id="density-notebook"><option value="default">default</option></select>
    <button onclick="loadDensity()">Load</button>
  </div>
  <canvas id="densityChart" height="300"></canvas>
</div>
```

- [ ] **Step 3: 加 JS 邏輯**
```javascript
async function loadDensity() {
  const uid = document.getElementById('density-user').value;
  const nb = document.getElementById('density-notebook').value;
  const data = await adminFetch(`/api/admin/graph-density?user_id=${uid}&notebook_id=${nb}`);
  renderDensityChart(data.points);
}

function renderDensityChart(points) {
  // X axis: cum_cards, Y axis: density
  // Line chart with tooltips showing timestamp
}
```

- [ ] **Step 4: 在 loadStats() 成功後填入 user selector，顯示 section**

- [ ] **Step 5: 本地跑 admin 頁面確認 chart 渲染正確**

- [ ] **Step 6: Commit**
`api: add graph density chart to admin dashboard`

---

### Task 3: Deploy & Verify

- [ ] **Step 1: preflight**
- [ ] **Step 2: deploy**
- [ ] **Step 3: 在 production admin 頁面確認 chart 正常載入**
