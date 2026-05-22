# KG Workspace Agent Guide

## Identity

| key | value |
|-----|-------|
| project key | `kg` |
| local root | `.` |
| backend | `backend` |
| ios | `ios` |
| remote | `~/knowledge_graph_api` |
| domain | `wordnexus.lol` |
| container | `knowledge-graph-api` |
| port | `8000` |

## 對話啟動流程（每次對話強制執行）

1. **Deep Scan（inline dispatch）** — 立即 inline dispatch 5-7 個 opus general-purpose agent 平行掃描全專案（無對應 skill）。不等結果，繼續下一步。
2. **掃描 skill 觸發條件** — 對照使用者的第一句話，凡符合已註冊 skill 的觸發描述，立即載入。「不確定是否符合」= 符合。
3. **確認 scope** — 本任務是否 project-scoped。若涉及跨專案，切回 repo root 遵循根 `CLAUDE.md`。
4. **匯總 Deep Scan 結果** — agent 完成後呈現問題清單，供使用者參考或挑選處理。

## Skill 系統（8 個 skill）

| Skill | 觸發 | 用途 |
|-------|------|------|
| `design` | 做 feature / 加功能 / 改行為 | 想法 → spec → plan |
| `execute` | 有 plan 要執行 | plan → worktree → opus agents → review → PR |
| `app-debug` | bug / test failure / 異常行為 | 根因調查 + 平行假說驗證 |
| `devops` | 部署 / 狀態 / 用戶查詢 / 額度 / 遠端操作 / 維護 | 生產環境運維全覽 |
| `data-analysis` | 分析用戶 / 圖譜 / 連結 / 額度 / 嵌入 / 閾值調優 | 深度資料分析 |
| `cleanup` | `/cleanup` 或「收尾」 | merge PRs → update docs → git cleanup → test → deploy |
| `podcast` | EPUB → podcast pipeline | 深度分析 → 規劃 → 腳本 → TTS → 字幕 |
| `swarm` | 「瘋狂做」「自己決策」「不要問」「壓榨我」「≥10 agents 並行」「不然換 codex」類語境 | 切「專案維護者」模式 — 自主補上下文、自主決策、組織 ≥10 並行 agent 直到任務閉環，不問人 |

### Skill 規則

- 觸發條件符合就**立即** `Skill()` 調用，不問使用者。
- 多個同時符合則全部載入。
- **所有 agent 一律 `model: "opus"`。無例外。**

## 鐵律（全域規則，不可繞過）

1. **TDD** — 先寫 failing test，確認紅，寫最小實作，確認綠。不可跳過。
2. **驗證先於宣稱** — 說「完成」「通過」「修好」之前，必須有當下的驗證輸出作為證據。「should work」= 謊言。
3. **根因先於修復** — 遇到 bug 必須確認根因才動手改。不可看到錯就補 patch。
4. **逐項 review，不批次** — 每完成一個 fix/feature 立即 dispatch review agent 審核，發現問題當場修，確認 PASS 後才進下一個。禁止「全部寫完再一起 review」。此規則適用所有程式碼修改，無論是否走 execute skill。
5. **不主動跑 iOS test** — 除非使用者明確說「跑測試」，否則禁止主動執行 `ios_test.sh`。**無例外，包含 worktree 中的 subagent。** `ios_build.sh` 和 backend `pytest` 不受此限。
6. **不寫 memory** — 禁止寫入 `.claude/projects/*/memory/`。所有持久化規則寫在 `CLAUDE.md` 或 `docs/`。
7. **長時操作一律背景執行** — 任何 Agent 調用必須帶 `run_in_background: true`；任何耗時 Bash 也必須帶 `run_in_background: true`（含 `ios_build.sh`、`ios_test.sh`、backend `pytest`、deploy/rsync、長下載、長 install）。**主線不阻塞**，完成由 notification 觸發。**無例外**。
8. **Surface-sync 檢查** — 改 user/agent-facing 介面(`backend/ops_*.py`、`backend/*_cli.py`、admin endpoint、CLI subcommand、env var、設定 schema)時,必須 grep `.claude/skills/`、`docs/references/product_surface.md`、`docs/references/tech_index.md`、`docs/dev/` `docs/ops/`,凡引用到舊命令/欄位/旗標清單就在**同一 PR 內同步**。下個 agent 不知道新功能 = 任務沒閉環,**不算完成**。檢查時機:每個 phase commit 前、PR 開出前各掃一次。Review agent prompt 必須含此項檢查。
9. **主動查文檔(Doc Lookup Discipline)** — 凡涉及 backend endpoint / iOS 模組 / env var / DB schema / 既有 feature / ops 工作流,**判斷「這需要查一下」就立即讀 `docs/references/` 或 `docs/dev/`,不靠記憶或假設**。對 subagent 同樣適用:dispatch 有複雜度 / 依賴性 / 耦合性的工作時,prompt 必須明確授權 agent「拿不準就讀 doc,不要省 token」。純樣板修改(typo、rename)不適用。

## Git

- Monorepo：`.git` 涵蓋 iOS app、backend API、ops/docs
- Commit prefix：`ios:` / `api:` / `ops:` / `docs:`

## iOS 編譯（強制）

唯一合法方式（從 repo root 或任何 worktree）：

```bash
./ops/ios_build.sh          # build only (Release, ~15s incremental)
./ops/ios_test.sh           # run ALL unit tests
./ops/ios_test.sh -g "foo"  # run tests matching pattern "foo"
./ops/ios_test.sh testName  # run specific test by method name
```

兩者共用 `shlock` 排隊鎖 + DerivedData，多 worktree 可同時呼叫。

- Exit 0 → 成功，停止
- Exit 非 0 → 讀錯誤上下文 ±20 行，修正後重跑
- **禁止**：直接 `xcodebuild`、改機型、拿掉 `-quiet`、加 `2>&1 | grep`、加 `cd ios &&`

## iOS UI Design System（強制）

**觸發**：任何涉及 iOS View / UI 的新增或修改。

### 動手前必做
1. 讀 `docs/references/ui_component_pattern_inventory.md` — 現有元件與 pattern
2. 讀 `docs/references/ui_review_checklist.md` — 自查清單

### Token 禁令（零容忍）

| 禁止 | 替代 |
|------|------|
| raw color（`Color.red`、`Color(red:...)`、`#colorLiteral`）| `AppTheme` / `VocabSkin.Palette` / `AppColors` |
| raw font（`.font(.system(...))`、`Font.custom(...)`）| `AppFonts` / `VocabSkin.Typography` |
| raw spacing magic number | `AppShellMetrics` / `AppMetrics` / `VocabSkin.Spacing` |
| raw animation（`.spring(...)`、`.easeOut(...)`、`.default`）| `AppMotion` token |
| raw transition | `AppTransition` token |

### 元件復用
- 新增前查 inventory，復用優先序：現成 Pattern → Component → 擴充 Token → 新建
- 新建元件放入對應層級（App Shell / VocabSkin / Reader / Settings）

### 狀態覆蓋
- 每個新畫面/元件必須覆蓋：loading、empty、error、success/completed
- 參照 `docs/references/ui_state_matrix.md`

### Motion 契約
- 所有動畫走 `AppMotion` 語意 token（`Models/AppMetrics.swift`）
- 新動畫先在 `AppMotion` 新增 token，再引用
- 同類互動跨 feature 共用同一 token

### 環境注入
- Theme：`@Environment(\.appTheme)`
- VocabSkin：`@Environment(\.vocabSkin)`
- 不可硬建 instance

### 完工自查
- 對照 `docs/references/ui_review_checklist.md` 五大項
- 關鍵畫面須有 `#Preview`，不依賴登入/後端

## Reference Docs（按需讀取）

不確定 endpoint / DB / env var / 模組叫什麼,先查 **tech_index**;不確定功能是否已實作,先查 **product_surface**。

| 主題 | 路徑 |
|------|------|
| **product surface**(動手前對照,確認不重複建造) | `docs/references/product_surface.md` |
| **tech index**(routers / DB / env var / iOS 模組 / ops 腳本) | `docs/references/tech_index.md` |
| backend dev | `docs/dev/backend-dev.md` |
| deploy / env / migration | `docs/dev/deploy.md` |
| Claude Code Gateway | `docs/ops/claude-code-gateway.md` |
| incidents / 502 / caddy | `docs/dev/debug.md` |
| iOS build / xcode | `docs/dev/ios-dev.md` |
| UI design | `docs/dev/ui-design.md` |
| architecture / sync | `docs/dev/architecture.md` |
| UI component inventory | `docs/references/ui_component_pattern_inventory.md` |
| UI review checklist | `docs/references/ui_review_checklist.md` |
| UI state matrix | `docs/references/ui_state_matrix.md` |

## Doc Freshness 規則

- 修改 backend router / DB schema / env var / ops 腳本時,同 PR 內更新 `docs/references/tech_index.md`
- 新增 user-facing feature(iOS / backend / admin / chrome)時,同 PR 內在 `docs/references/product_surface.md` 追加 bullet
- iOS 大規模重構 PR 合併後,執行 `ops/gen_ios_baseline.sh` 更新 `docs/references/ios_frontend_baseline.md`(此檔為 script 產出,不要手改)
