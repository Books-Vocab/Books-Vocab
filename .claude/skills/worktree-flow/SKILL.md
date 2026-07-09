---
name: worktree-flow
description: "隔離工作樹 intent→cutover 全流程。當使用者開新 session 丟一個 debug / dev / research intent 並要在隔離 git worktree 自動開發到 merge 進 main 時觸發。編排 ops/worktree_orchestrate.py 原語（preflight / open / gate / cutover / resolve）串起 P1 健康判定 + P2 登記簿 + 既有 gate 工具；純 research/唯讀不開 worktree。deploy 生產不含在內。"
user-invocable: true
version: 1.1.0
---

# worktree-flow

把「使用者丟 intent → 隔離工作樹開發 → gate → 進 main」串成一條可執行流水線。你是**單一執行 agent**，逐步呼叫原語 `ops/worktree_orchestrate.py`（下稱 `orchestrate`）。它只**編排**：P1 `ops/lib/worktree_state.py`（純健康判定）、P2 `ops/worktree_registry.py`（誕生→解決登記簿 + 孤兒哨兵）、與既有 gate 工具（`ios_ops.sh` / `verify_design_system.sh` / `docs_lint.sh` / `pytest`）。**絕不重造 gate 判斷**。

所有 mutation 子指令 **dry-run 預設，`--commit` 才落地**。`--json` 給機器判讀。

## 流程（照序）

### 1. preflight — 清殘骸 + fetch
```
ops/worktree_orchestrate.py preflight --json          # dry-run 先看
ops/worktree_orchestrate.py preflight --commit --json # 確認殘骸可清才落地
```
= `git fetch origin` + `worktree_registry sweep --exclude-current`。`--exclude-current` 保證**從任一 worktree 跑都不誤清自己**。sweep 只清三種保守形狀（dangling-landed / detached-orphan / registry-resolved），base 分支與 primary worktree 絕對保護——放心跑。

### 2. 讀地圖，建立 intent 理解
`orchestrate` 不幫你理解任務。先讀地圖：`kg-router`（capability matrix / 冷啟動路由）、`docs/registry.yml`（活文檔控制面）、對應 **SoT**（`docs/reference/product_surface.md` 查功能是否已存在、`tech_index.md` 查模組/endpoint/env、feature_boundary/* 查 iOS scope）。避免重造既有功能。

### 3. 純 research / 唯讀 → 不開 worktree
若 intent 是調查、盤點、回答問題、讀碼分析（**無程式碼寫入**）→ **直接做、直接回報，不開 worktree**。開 worktree 只為了承載會進 main 的 commit。`orchestrate open` 依 intent 類型命名分支（debug/* | feat/* | research/*）——research/* 分支僅用於**會產出 commit 的**探索（如寫 spike/POC）；純唯讀不需要。

### 4. 寫 code → 隔離工作樹開發到 cutover

**a. 拆 phase**：載入 `phased` skill，把任務切成可獨立 commit 的 phase plan。

**b. open**：
```
ops/worktree_orchestrate.py open --intent "<原始 intent 文字>" --slug <kebab-slug> --json
```
建 `.claude/worktrees/<slug>`、分支 `<type>/<slug>`（type 由 intent 自動判定），並在 P2 登記簿**誕生即登記**。記下回傳的 `path`。

**c. 逐 phase 實作（phased 模式）**：在 worktree 內做第 N phase 時，**同步派 code review agent 審 N-1 phase**（鐵律 4 逐項 review，鐵律 5 所有 Agent 背景化）。每個 phase 收尾 commit。**每 phase 後 fetch + rebase** 讓分支貼著 origin/main（減少 cutover 衝突）：
```
git -C <path> fetch origin && git -C <path> rebase origin/main
```

**d. 全 phase 完 → gate**（impact-based，顯式跑；.githooks 只 best-effort，不可依賴）：
```
ops/worktree_orchestrate.py gate --worktree <path> --json
```
它 diff `<path>` vs origin/main，把改動路由到既有 gate 工具並彙總 `verdict`（block/warn/pass），把結果**記錄下來**（綁 worktree + HEAD sha）供 cutover 核對。impact→gate 對應：
- `ios/**` → `ios_ops.sh build` **＋** `build --catalyst`（sim 綠 ≠ Catalyst 綠）＋ `quality impact`（swift）＋ `test --unit`（動 View/UI/nav 再加 `--ui`）
- design-system / tokens / 生成 CSS / `ios/**/Models|UIComponents/` → `verify_design_system.sh`
- `docs/**.md` → `docs_lint.sh --files` ＋ conflict-marker 掃描 ＋ `verified_against` 可達性
- `backend/**.py` → 只跑 diff 內的**目標測試檔**；純 src 改動無目標測試 = **warn advisory**（不跑全套，全套有已知 pre-existing 假失敗）

先 `gate --plan-only --json` 可預覽選出的 gate 集合而不執行。**block 必修**（回去修再重跑 gate）；**warn 是 advisory**——不擋 cutover，處置權在你（driving agent），land 時會標「landed with warnings」。iOS build/test 很耗時 → 背景執行、主線不阻塞（鐵律 5）。

**e. 非 block 才 cutover**：
```
ops/worktree_orchestrate.py cutover --worktree <path> --json          # dry-run 預覽
ops/worktree_orchestrate.py cutover --worktree <path> --commit --json # 進 main
```
它**要求新鮮的非 block verdict**（verdict ∈ {pass, warn} 且記錄的 HEAD == 當前 HEAD；stale/缺紀錄/block 會被拒）→ fetch → rebase onto origin/main → **ff push HEAD:main**。`warn` 會 land 並在輸出/JSON 標 `warnings: [<gate 名>]`（「landed with warnings」）。進 main 已長期授權（不先問）。

**f. resolve — 清乾淨、登記閉環**：
```
ops/worktree_orchestrate.py resolve --worktree <path> --json          # dry-run 看計畫
ops/worktree_orchestrate.py resolve --worktree <path> --commit --json
```
先過 **landed-floor**（tree-diff 判分支是否已進 base）：**未 land 的分支拒絕拆除**（避免 cutover 前誤呼叫 resolve 而 force-discard 未落地工作），要強拆傳 `--force`。過了 floor = 登記簿 resolve→merged + `git worktree remove` + `branch -D`（local，遠端若存在也刪）+ **刪該 worktree 的 gate-record cache**。清完真正零殘骸。

## 硬邊界

- **deploy 生產（wordnexus.lol）是獨立閘、必徵使用者同意**——**不含在自動 cutover**。進 main ≠ 部署。要部署走 `devops` skill 並先取得明確 go（鐵律 7 生產禁令 + 熱路徑徵同意）。
- **不重造 gate**：`gate` 只路由到既有工具。要加可斷言的 gate → 改對應工具本身，不在 orchestrate 內判 pass/fail。
- **動 agent-facing surface**（本 CLI/skill 本身）→ 同 PR 同步 `docs/reference/tech_index.md` / `product_surface.md`（見根 CLAUDE.md「改 user/agent-facing 介面」）。
- 收尾照 `kg-receipt`：驗證輸出 + 交接點。工具摩擦記 tooling debt（鐵律 9）。

## 一眼流程圖
```
preflight ─▶ 讀地圖 ─▶ research? ──yes──▶ 直接做（不開 worktree）
                          │no
                          ▼
              phased 拆 phase ─▶ open ─▶ [每 phase: 實作 + review N-1 + fetch/rebase]
                          ─▶ gate(block?) ──yes──▶ 修
                                   │no（pass/warn）
                                   ▼
                          cutover(進 main) ─▶ resolve(landed-floor→清乾淨)
                          ┄┄┄ deploy 另議、必徵同意 ┄┄┄
```
