---
name: steward
description: "程式碼管家模式 — 使用者設定目標改善數（「steward 50」「audit 100個」「steward backend/ 80」），自動多輪並行掃描 + 執行 behavior-preserving 優化直到達標，輸出 PR。"
user-invocable: true
version: 1.0.0
---

# Steward — 自動化 Codebase 健康度提升

## 觸發語境

- `/steward 100` — 對 backend/ 做 100 個改善
- `/steward backend/ 50` — 指定目錄 + 目標數
- 「audit codebase」「codebase 健康度」「自動修 N 個」「steward 幫我跑」
- 「用 workflow 修到 N 個」

## 核心思想

1. **使用者只給目標數**，其餘全自主
2. **每輪 5 維度並行掃描** → triage → fix → test → commit
3. **維度正交原則** — 每輪選從未做過的維度，不重複掃同一面向
4. **單一整合 PR** — 每輪結果 cherry-pick 進同一 branch，持續累積
5. **達標才停** — 計算已執行改善數，不足就自動加輪

---

## 啟動流程

### Step 0：解析參數

從使用者輸入提取：
- `TARGET`：目標改善數（整數，必填）
- `SCOPE_DIR`：掃描目錄（預設 `backend/src/`）
- `PR_BRANCH`：整合 branch 名（預設 `steward-audit-$(date +%Y%m%d)`）

```bash
# 建立整合 worktree（所有輪次的 cherry-pick 目標）
MAIN_ROOT=$(git rev-parse --path-format=absolute --git-common-dir | xargs -I{} dirname {})
git -C "$MAIN_ROOT" fetch origin main
git -C "$MAIN_ROOT" worktree add \
  "$MAIN_ROOT/.claude/worktrees/steward-integration" \
  -b "$PR_BRANCH" origin/main
# 開 PR（空的，後續 push 更新）
cd "$MAIN_ROOT/.claude/worktrees/steward-integration"
git commit --allow-empty -m "ops: steward audit — WIP"
git push -u origin "$PR_BRANCH"
gh pr create --title "ops: steward audit — 0/$TARGET improvements" \
  --body "Automated codebase steward audit. Progress tracked in commits." \
  --draft
```

### Step 1：初始化維度池

從下方「維度目錄」選出第一批。**每輪取 5 個未用過的維度**。

### Step 2：執行一輪

```
ROUND_IMPROVEMENTS = launch_workflow(ROUND_N, DIMENSIONS_BATCH, SCOPE_DIR)
```

- 建立獨立 worktree：`steward-r{N}-{date}`
- 在 worktree 內：5 維度並行掃描 → triage → fix → verify（pytest） → commit → push own branch
- cherry-pick commit 進整合 worktree
- 解衝突（見衝突處理規則）
- push 整合 branch → PR 自動更新

### Step 3：計算進度

```
TOTAL_DONE += ROUND_IMPROVEMENTS
if TOTAL_DONE >= TARGET:
    finalize_pr()
    STOP
else:
    select_next_dimensions()
    goto Step 2
```

---

## 維度目錄（每輪選 5 個未用維度）

每個維度一個識別碼。同一 session 不重用。

### 死碼與重複（DC）
- `DC-1` 未使用 import、未使用函數、未被呼叫的 class
- `DC-2` 重複 fixture、重複 helper（跨測試檔）
- `DC-3` 已被取代的程式碼路徑（dead branch）
- `DC-4` Compat/backcompat shim（沒人在用的別名）
- `DC-5` Orphan module（沒有任何 import）

### 複雜度（CX）
- `CX-1` Magic numbers → 命名常數
- `CX-2` 深巢狀 if/else → guard clause / early return
- `CX-3` 長函數（>50 行）拆分
- `CX-4` 重複 error handling pattern → helper/context manager
- `CX-5` 吞掉 traceback 的 except → exc_info=True

### 型別與介面（TY）
- `TY-1` 缺失 return type annotation（public function）
- `TY-2` `Any` 參數可換 Protocol/具體型別
- `TY-3` TypedDict / NamedTuple 取代 3+ element tuple / dict struct
- `TY-4` Pydantic field constraints（min_length, ge, le）
- `TY-5` TypeAlias for complex repeated types（>30 chars, 3+ sites）

### 一致性（CO）
- `CO-1` HTTPException status code 與 detail 格式統一
- `CO-2` 錯誤訊息 sentence-case 統一
- `CO-3` Import 順序（stdlib → third-party → local）
- `CO-4` Logger 設定模式（logging.getLogger vs structlog）
- `CO-5` f-string in log calls → % style（lazy evaluation）

### 測試品質（TE）
- `TE-1` 3+ 相似測試函數 → @pytest.mark.parametrize
- `TE-2` 本地 fixture def → conftest（跨 2+ 檔）
- `TE-3` 零斷言或 trivially-true 斷言
- `TE-4` 測試用 time.sleep → caplog poll / mock
- `TE-5` 高優先未覆蓋模組 → 新增基礎測試

### 資料層（DA）
- `DA-1` SELECT * → 顯式欄位列表
- `DA-2` 無 LIMIT 的 fetchall（OOM 風險）
- `DA-3` open() without context manager
- `DA-4` json.dumps without ensure_ascii=False（Unicode 內容）
- `DA-5` 未編譯 regex 在函數內（→ module-level compiled）

### 序列化與配置（SC）
- `SC-1` Pydantic v1 pattern → v2（@validator, class Config, .dict()）
- `SC-2` 散落的 os.getenv → 集中 Settings
- `SC-3` 重複的路徑解析 → 共用 helper
- `SC-4` 硬編碼 host/port → 配置
- `SC-5` Static JSON 每次 parse → module-level constant

### API 表面（AP）
- `AP-1` APIRouter 缺 tags=（Swagger 分組）
- `AP-2` dict return → 具名 Pydantic response model
- `AP-3` None-as-error → 明確 raise
- `AP-4` Response model 與實際回傳型別不符
- `AP-5` 缺失 summary/description on important endpoints

### 結構品質（ST）
- `ST-1` @dataclass(frozen=True, slots=True) for hot-path value objects
- `ST-2` contextlib.suppress 取代 try/except: pass
- `ST-3` 重複的 KG_DATA_DIR 解析 → 共用 helper
- `ST-4` __all__ 缺失或不完整（public package）
- `ST-5` 重複的 error detail string → 常數

### 安全性（SE）
- `SE-1` logging sensitive data（token/password in log）
- `SE-2` String field 缺 min_length=1（empty string bypass）
- `SE-3` 邊界校驗缺失（self-link, confidence range, empty ID）
- `SE-4` 缺失 rate limiting 標記
- `SE-5` JWT verify options 完整性

---

## Workflow 模板（每輪調用）

每輪的 workflow 接受：
- `round_num`：輪次號碼（R1/R2/...）
- `dimensions`：本輪 5 個維度 ID + 描述
- `worktree`：本輪專用 worktree 路徑
- `backend`：掃描目錄
- `already_done`：前幾輪已覆蓋的改善描述（避免重複）

Workflow 執行：
1. **Scan phase**：5 個並行 opus agent，各自負責一個維度
2. **Triage phase**：1 個 opus agent 綜合所有 finding，輸出 ≤20 個 tiny/small/none-low risk 改善
3. **Fix phase**：pipeline 逐一執行（每個 agent 實作一個改善）
4. **Verify phase**：syntax check → pytest → commit → push own branch

---

## Cherry-pick 整合規則

每輪 commit 完成後：
1. `git fetch origin <round-branch>`
2. `git cherry-pick <commit-hash>` 進整合 worktree
3. 衝突解決原則：
   - **兩輪都加新內容** → 保留兩者（append）
   - **兩輪都改同一行** → 取「更改善的那個」（通常是後輪）
   - **一輪刪、另一輪改** → 保留刪除（避免復活死碼）
4. Push 整合 branch → PR commit 自動更新

如果 cherry-pick 有衝突無法自動解決：派 agent 在整合 worktree 內處理衝突，完成後重新驗證並 commit。

---

## PR 管理

- 整合 PR 從一開始就開好（draft）
- 每輪推新 commit 後更新 PR title：`ops: steward audit — {DONE}/{TARGET} improvements`
- 達標後 undraft：`gh pr ready`
- PR body 包含每輪的 commit 和改善清單

---

## 進度報告格式（每輪結束後）

```
R{N} 完成：{done}/{target}（+{this_round}）
維度：{dim1}、{dim2}、...
Tests：{pass_count} PASS
Commit：{hash}

{如果未達標} → 啟動 R{N+1}，維度：{next_dims}
{如果達標} → PR #XXX ready，全部執行完成。
```

---

## 實作入口（orchestrator 直接執行）

收到 `/steward N` 後，orchestrator（你）：

1. **解析 N 和 SCOPE**
2. **跑 Step 0 的 bash**（建整合 worktree + 開 PR）
3. **選第一批 5 維度**（從維度目錄選，優先 DC/CX/TE 這三個最肥的類別）
4. **用 `Workflow` tool 啟動第一輪**（帶 worktree + dimensions + target 作為 args）
5. **收到 notification 後**：cherry-pick → 更新進度 → 決定是否繼續
6. **若未達標**：選下一批維度，啟動下一輪 Workflow
7. **達標**：`gh pr ready` + 報告

### 每輪 Workflow args 格式

```json
{
  "round": 1,
  "worktree": "/Users/.../steward-r1-20260605",
  "backend": "/Users/.../backend",
  "integration_worktree": "/Users/.../steward-integration",
  "dimensions": [
    {"id": "DC-1", "label": "dead imports and dead functions"},
    {"id": "CX-1", "label": "magic numbers to constants"},
    {"id": "TE-1", "label": "parametrize duplicate tests"},
    {"id": "DA-1", "label": "SELECT * to explicit columns"},
    {"id": "AP-1", "label": "router tags missing"}
  ],
  "target": 100,
  "already_done": 0
}
```

### 維度選擇策略

```
輪次 1：DC-1, CX-1, TE-1, DA-1, CO-5  （最高 ROI 維度）
輪次 2：DC-2, CX-4, TE-2, TY-1, AP-1  （第二批）
輪次 3：DC-3, CX-5, TE-3, DA-4, CO-1  （第三批）
... 依此類推，循環所有維度
```

如果第一輪就找到大量改善（>20），不需要更多維度組合。
如果某維度已在前幾輪中確認「此 codebase 已乾淨」，跳過那個維度。

---

## 鐵律

1. **每輪獨立 worktree** — 不同輪次不共用 worktree，避免並行寫入衝突
2. **所有 fix 必須 pytest PASS** — verify 階段失敗的輪次不 cherry-pick
3. **不 count 失敗或 skip 的改善** — 只有 status=done 的才計入 TOTAL
4. **整合 PR 唯一** — 所有輪次的工作集中到一個 PR，不開多個
5. **達標就停** — 不超量，不追求完美；使用者設了目標就是 SLA
6. **每輪報告** — 讓使用者知道進度，不悄悄跑幾百個 agent
