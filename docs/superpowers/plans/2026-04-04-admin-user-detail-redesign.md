# Admin User Detail Redesign — Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 重構 admin user detail 頁面：5 卡→3 表、雙欄佈局、pipeline per-run waterfall
**Architecture:** 純前端單檔重構，修改 CSS + HTML 結構 + JS 渲染邏輯
**Tech Stack:** HTML/CSS/JS, Chart.js (density only), d3-force (playback)

---

### Task 1: CSS — 雙欄佈局 + waterfall 樣式

**Files:** `backend/src/kg/admin_user_detail.html` L160-218（CSS section）

**步驟：**

1. **移除 `.info-grid` 樣式**（L161-166）— 整塊 grid 佈局不再使用，刪除：
   ```css
   .info-grid {
     display: grid;
     grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
     gap: 16px;
     margin-bottom: 32px;
   }
   ```

2. **新增雙欄佈局樣式**，插入在同位置：
   ```css
   .two-col { display: flex; gap: 24px; }
   .col-left { width: 340px; flex-shrink: 0; position: sticky; top: 52px; align-self: flex-start; max-height: calc(100vh - 68px); overflow-y: auto; }
   .col-right { flex: 1; min-width: 0; }
   ```

3. **新增 waterfall 樣式**，插入在 pipeline CSS 區塊（L398-431 附近）之後：
   ```css
   .waterfall { position: relative; margin: 8px 0; }
   .waterfall-axis { display: flex; justify-content: space-between; font-size: 9px; color: var(--sub); font-family: 'JetBrains Mono', monospace; border-bottom: 1px solid var(--border-l); padding-bottom: 4px; margin-bottom: 4px; }
   .waterfall-row { display: flex; align-items: center; gap: 8px; height: 24px; }
   .waterfall-label { width: 100px; font-size: 10px; font-family: 'JetBrains Mono', monospace; flex-shrink: 0; }
   .waterfall-track { flex: 1; position: relative; height: 16px; background: var(--border-l); border-radius: 2px; }
   .waterfall-bar { position: absolute; height: 100%; border-radius: 2px; min-width: 2px; }
   .waterfall-bar.s-ok { background: var(--ink); }
   .waterfall-bar.s-failed { background: var(--dev); }
   .waterfall-bar.s-skipped { background: var(--sub); }
   .waterfall-meta { font-size: 10px; font-family: 'JetBrains Mono', monospace; color: var(--sub); white-space: nowrap; width: 100px; flex-shrink: 0; text-align: right; }
   ```

4. **保留所有仍在使用的樣式**：`.detail-section`、`.detail-kv`、`.bar`、`.pipeline-run`、`.pipeline-step`、`.section-block`、`.chart-wrap`、`.playback-*` 全部不動。

**驗證：** 本地 deploy，確認頁面無 CSS parse error（DevTools Console 無警告）。

---

### Task 2: HTML 結構重組

**Files:** `backend/src/kg/admin_user_detail.html` L445-500（`#app` 內部結構）

**步驟：**

1. **替換 `#info-grid` 與三個 `section-block`**，將 L450-500 改為雙欄容器：

   ```html
   <!-- Two-column layout -->
   <div class="two-col">
     <div class="col-left">
       <div class="detail-section" id="tbl-account"></div>
       <div class="detail-section" id="tbl-subscription" style="margin-top:12px"></div>
       <div class="detail-section" id="tbl-quota" style="margin-top:12px"></div>
     </div>
     <div class="col-right">
       <!-- Pipeline Analytics -->
       <div class="section-block">
         <div class="section-title">Pipeline Analytics</div>
         <div id="pipeline-no-data" class="no-data" style="display:none">無 Pipeline 紀錄</div>
         <div id="pipeline-analytics" style="display:none">
           <div class="section-title" style="margin-top:8px">執行紀錄</div>
           <div id="pipeline-runs"></div>
         </div>
       </div>
       <!-- Graph Density -->
       <div class="section-block">
         <div class="section-title">Graph Density</div>
         <div class="chart-wrap">
           <canvas id="density-chart" height="300"></canvas>
           <div id="density-no-data" class="no-data" style="display:none">無圖譜密度資料</div>
         </div>
       </div>
       <!-- Graph Playback -->
       <div class="section-block">
         <div class="section-title">Graph Playback</div>
         <div class="playback-wrap">
           <div class="playback-canvas-container" id="playback-container">
             <canvas id="playback-canvas"></canvas>
             <div class="graph-tooltip" id="tooltip"></div>
           </div>
           <div class="playback-controls" id="playback-controls">
             <button id="btn-play" title="Play/Pause">▶</button>
             <select id="speed-select">
               <option value="1">1x</option>
               <option value="5">5x</option>
               <option value="10">10x</option>
             </select>
             <input type="range" id="timeline-slider" class="playback-slider" min="0" max="0" value="0">
             <span class="playback-label" id="event-counter">0 / 0 events</span>
             <span class="playback-label" id="time-label">—</span>
           </div>
           <div id="playback-no-data" class="no-data" style="display:none">無圖譜播放資料</div>
         </div>
       </div>
     </div>
   </div>
   ```

2. **移除 pipeline HTML 中的摘要與圖表元素**：
   - 刪除 `<div class="stats" id="pipeline-summary" ...>`（原 L491）
   - 刪除 `<div class="chart-wrap" ...><canvas id="pipeline-chart" ...></div>`（原 L493-495）
   - Pipeline section 內只保留 `#pipeline-runs` 容器

3. **移除 Chart.js CDN**（L10）— pipeline 堆疊圖已不需要…**等等，density chart 仍用 Chart.js**，所以保留 `<script src="...chart.js...">` 不動。

**驗證：** 本地 deploy，確認 HTML 結構正確、三個表格容器與右欄三個 section 都出現在 DOM 中。

---

### Task 3: renderUserInfo() — 3 表格渲染

**Files:** `backend/src/kg/admin_user_detail.html` L607-683（`renderUserInfo` 函式）

**步驟：**

1. **重寫 `renderUserInfo(u)`**，由渲染到 `#info-grid` 改為分別渲染到 `#tbl-account`、`#tbl-subscription`、`#tbl-quota` 三個容器。

2. **Table 1 — 帳戶基本資訊**（`#tbl-account`）：
   保持現有 6 列不變（User ID / Email / Provider / 最後登入 / 單字數 / Mochi 整合），只是渲染目標改為 `#tbl-account`。

3. **Table 2 — 訂閱狀態**（`#tbl-subscription`）：
   合併原「訂閱狀態」8 列 + 「Admin Grant」6 列，中間加 divider + 子標題：
   ```html
   <div class="detail-section-title">訂閱狀態</div>
   <!-- 8 列訂閱 -->
   <div style="border-top:1px solid var(--border);margin:8px 0;padding-top:6px">
     <div class="detail-section-title" style="margin-bottom:4px">Admin Grant</div>
   </div>
   <!-- 5 列 grant（移除原「狀態」列，保留啟用/授權者/原因/授權時間/到期日）-->
   ```

4. **Table 3 — 額度使用狀態**（`#tbl-quota`）：
   合併原「每日翻譯額度」+「Token 消耗明細」為單一表格：

   - **頂部**：`used / limit + progress bar`（維持現有邏輯）
   - **中段**：每種 type 一列，合併 quota.calls 與 tokens 資料：
     ```
     type_label | ×count = $cost | input↑ output↓
     ```
     Type 對應關係：
     - `translate_quick` → `translate_quick`
     - `translate_phrase` → `translate_phrase`
     - `translate_explain` → `translate_explain`
     - `enrich` → `enrich`
     - `judge` → `judge`
     - `manual_link_judge` → tokens only（無 quota call）
     - `embed` → quota only（通常無 token 資料）

     實作邏輯：收集所有出現在 `q.calls` 或 `u.tokens` 中的 type key，取聯集，逐一渲染。若該 type 有 calls 資料則顯示 `×count = $cost`，否則 `—`；若有 tokens 資料則顯示 `input↑ output↓`，否則 `—`。

   - **底部**：divider + 預估總費用（`u.est_cost_usd`）

5. **移除** `document.getElementById('info-grid').innerHTML = ...` 整段（原 L641-682），改為三段分別 `.innerHTML`。

**驗證：** 本地 deploy，確認左欄三張表格正確渲染、資料完整、divider 正確顯示。

---

### Task 4: renderPipelineAnalytics() — waterfall 替代

**Files:** `backend/src/kg/admin_user_detail.html` L1048-1172（`renderPipelineAnalytics` 函式）

**步驟：**

1. **刪除 `_pipelineChart` 變數**（L1049）與所有 Chart.js 相關程式碼（L1083-1137）。

2. **刪除摘要統計渲染**（L1064-1081 的計算 + `#pipeline-summary` innerHTML 賦值）。

3. **新增 `renderWaterfall(run)` 函式**：
   ```javascript
   function renderWaterfall(run) {
     const totalDuration = run.duration_s || 1;
     const runStart = new Date(run.started_at).getTime();
     const steps = run.steps || [];
     if (!steps.length) return '<div style="padding:8px;color:var(--sub);font-size:11px">無步驟資料</div>';

     // 時間軸標記
     let html = '<div class="waterfall">';
     html += '<div class="waterfall-axis">';
     html += '<span>0s</span>';
     html += `<span>${(totalDuration * 0.25).toFixed(1)}s</span>`;
     html += `<span>${(totalDuration * 0.5).toFixed(1)}s</span>`;
     html += `<span>${(totalDuration * 0.75).toFixed(1)}s</span>`;
     html += `<span>${totalDuration.toFixed(1)}s</span>`;
     html += '</div>';

     for (const step of steps) {
       const stepStart = step.started_at ? new Date(step.started_at).getTime() : runStart;
       const leftPct = ((stepStart - runStart) / 1000) / totalDuration * 100;
       const widthPct = (step.duration_s || 0) / totalDuration * 100;
       const statusClass = 's-' + (step.status || 'ok');
       const dur = step.duration_s != null ? step.duration_s.toFixed(1) + 's' : '—';
       const items = step.items ? step.items.toString() : '';

       html += '<div class="waterfall-row">';
       html += `<span class="waterfall-label">${escapeHtml(step.name)}</span>`;
       html += '<div class="waterfall-track">';
       html += `<div class="waterfall-bar ${statusClass}" style="left:${leftPct.toFixed(1)}%;width:${Math.max(widthPct, 0.5).toFixed(1)}%"></div>`;
       html += '</div>';
       html += `<span class="waterfall-meta">${dur}${items ? '  ' + items : ''}</span>`;
       html += '</div>';

       // Failed step 顯示錯誤訊息
       if (step.error) {
         html += `<div class="pipeline-step-error" style="margin-left:108px">${escapeHtml(step.error)}</div>`;
       }
     }
     html += '</div>';
     return html;
   }
   ```

4. **修改 run list 渲染**（原 L1139-1171），在每個 `.pipeline-run-steps` 中加入 waterfall：
   - 將原本的 step 列表（`stepsHtml`）替換為 `renderWaterfall(run)` 的輸出
   - 保留原有的 `.pipeline-run-header` 點擊展開邏輯不變

5. **清理**：移除所有 `#pipeline-summary`、`#pipeline-chart`、`_pipelineChart` 的引用。

**驗證：** 本地 deploy，展開任一 pipeline run，確認 waterfall 時間軸正確渲染、bar 位置與寬度對應 step 時間、顏色對應 status。

---

### Task 5: 整合驗證

**Files:** `backend/src/kg/admin_user_detail.html`（全檔）

**步驟：**

1. **確認 `loadPage()`**（L1174-1227）無需結構性修改 — 渲染目標 ID 在 Task 2/3 中已對齊，四個 fetch + render 呼叫維持不變。

2. **全檔搜尋清理**：
   - 搜尋 `info-grid` — 應無任何殘留引用
   - 搜尋 `pipeline-summary` — 應無任何殘留引用
   - 搜尋 `pipeline-chart` — 應無任何殘留引用
   - 搜尋 `_pipelineChart` — 應無任何殘留引用

3. **本地部署驗證**（`devops_kg_safe.sh` 或直接起本地 server）：
   - [ ] 頁面載入無 JS error
   - [ ] 左欄 sticky 行為正確：捲動右欄時左欄固定
   - [ ] 左欄超長內容可獨立捲動
   - [ ] 三張表格資料完整（帳戶 / 訂閱+grant / 額度+token）
   - [ ] Pipeline run 列表正常展開收合
   - [ ] Waterfall bar 位置與寬度正確
   - [ ] Failed step 顯示紅色 bar + 錯誤訊息
   - [ ] Density chart（Chart.js）正常渲染
   - [ ] Graph playback（d3-force）正常運作
   - [ ] Grant / Revoke Pro 按鈕功能正常

4. **預估行數驗證**：重構後全檔應在 1300-1400 行範圍內（移除 ~60 行摘要/圖表、新增 ~100 行 waterfall + 雙欄 CSS/HTML）。
