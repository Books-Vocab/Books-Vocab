# KG Workspace Agent Guide

## Identity

**KG = Knowledge Graph 英語詞彙學習 app** — EPUB/PDF/TXT/MD reader 選詞 → 翻譯 → 詞庫 → 知識圖譜 → today review → podcast。  
Monorepo:`ios/`(SwiftUI BooksBrowser app)+ `backend/`(FastAPI / Python)+ `chrome-extension/` + `lab/`(Claude Code Gateway 等)+ `ops/` + `docs/`,單一 `.git`。

| key | value |
|-----|-------|
| project key | `kg` |
| backend | `backend` |
| ios | `ios` |
| remote | `~/knowledge_graph_api` |
| domain | `wordnexus.lol` |
| container | `knowledge-graph-api` |
| port | `8000` |
| commit prefix | `ios:` / `api:` / `ops:` / `docs:` |

## 對話啟動流程

1. **掃描 skill 觸發條件** — 對照使用者第一句話,凡符合已註冊 skill 的觸發描述,立即 `Skill()` 載入。「不確定是否符合」= 符合。
2. **確認 scope** — 任務是否 project-scoped。若涉及跨專案,切回 repo root 遵循根 `CLAUDE.md`。
3. **依任務性質判斷是否需要 deep scan** — 模糊請求(「看看現況」「整理一下」「有什麼可以做」)才 dispatch 2-5 個 opus general-purpose agent 平行掃描;具體任務(typo / 單檔修改 / 已指明範圍)**不要** deep scan。

## Skill 系統(KG 專屬 8 個 + plugin 全域可用)

| Skill | 觸發 | 用途 |
|-------|------|------|
| `design` | 做 feature / 加功能 / 改行為 | 想法 → spec → plan |
| `execute` | 有 plan 要執行 | plan → worktree → opus agents → review → PR |
| `app-debug` | bug / test failure / 異常行為 | 根因調查 + 平行假說驗證 |
| `devops` | 部署 / 狀態 / 用戶查詢 / 額度 / 遠端操作 / 維護 | 生產環境運維全覽 |
| `data-analysis` | 分析用戶 / 圖譜 / 連結 / 額度 / 嵌入 / 閾值調優 | 深度資料分析 |
| `cleanup` | `/cleanup` 或「收尾」 | merge PRs → update docs → git cleanup → test → deploy |
| `podcast` | EPUB → podcast pipeline | 深度分析 → 規劃 → 腳本 → TTS → 字幕 |
| `swarm` | 「瘋狂做」「不要問」「壓榨我」「≥10 agents 並行」等情緒語境,或使用者明示「autonomous 多 agent 執行 + don't-ask」 | 切「專案維護者」模式 — 自主補上下文、決策、組織 ≥10 並行 agent 直到任務閉環 |

**另有 plugin skill 全域可用**(`anthropic-skills:*`、`review`、`verify`、`run`、`code-review`、`init`、`schedule`、`loop`、`update-config` 等),觸發描述見 system reminder。

### 規則
- 觸發條件符合就**立即** `Skill()` 調用,不問使用者。多個同時符合則全部載入。
- **所有 Agent() 一律 `model: "opus"` + `run_in_background: true`。無例外。**

## 鐵律(全域,7 條,不可繞過)

1. **TDD** — failing test → 紅 → 最小實作 → 綠。不可跳過。
2. **驗證先於宣稱** — 說「完成 / 通過 / 修好」前必須有當下驗證輸出。「should work」= 謊言。
3. **根因先於修復** — 遇 bug 必須確認根因才動手。不可看到錯就補 patch。
4. **逐項 review,不批次** — 每完成一個 fix/feature 立即 dispatch review agent,PASS 才下一個。禁「全部寫完再一起 review」。適用所有程式碼修改,不限 execute skill。
5. **長時操作背景執行** — 任何 `Agent()` 與耗時 Bash(`ios_build.sh`、`ios_test.sh`、backend `pytest`、deploy/rsync、長下載/install)一律 `run_in_background: true`。**主線不阻塞**,完成由 notification 觸發。
6. **主動查文檔(Doc Lookup Discipline)** — 涉及 endpoint / 模組 / env var / DB schema / 既有 feature / ops 工作流,**判斷「這需要查一下」就立即讀對應 reference,不靠記憶**。dispatch 有複雜度的工作時,prompt 必須明示「拿不準就讀 doc,不要省 token」。純樣板修改(typo / rename)不適用。
7. **生產禁用指令** — `docker compose down -v` / `docker system prune -a` / `rm -rf /home/ubuntu/*`(涵蓋 data dir)永遠禁止。運維走 `ops/devops_kg_safe.sh`,不繞過 wrapper。完整見 `docs/ops/SAFETY_POLICY.md`。

## Scope 規則(觸發式,非 always-on)

- **改 iOS View / UI** → 動手前讀 `docs/dev/ui-design.md`(規範) + `docs/references/ui_component_pattern_inventory.md`(現有元件) + `docs/references/ui_review_checklist.md`(自查 5 項) + `docs/references/ui_state_matrix.md`(狀態覆蓋);對應 feature scope 另讀 `docs/references/feature_boundary_<reader|vocabulary|settings>.md`。
- **iOS 編譯** → 唯一合法入口 `./ops/ios_build.sh` / `./ops/ios_test.sh`(共享 `shlock` 鎖,多 worktree 安全);細節見 `docs/dev/ios-dev.md`。**不主動跑 `ios_test.sh`**(包含 worktree subagent),除非使用者明確要求;`ios_build.sh` 與 backend `pytest` 不受此限。
- **改 user/agent-facing 介面**(`backend/ops_*.py`、`backend/*_cli.py`、admin endpoint、CLI subcommand、env var、設定 schema) → **同 PR 內**grep `.claude/skills/`、`docs/references/product_surface.md`、`docs/references/tech_index.md`、`docs/dev/`、`docs/ops/`,凡引用到舊命令/欄位/旗標清單立即同步。下個 agent 不知道新功能 = 任務沒閉環。Review agent prompt 必須含此項檢查。

## Doc 路由(語意 → 路徑)

不確定該讀哪份時對照本表。標 **(SoT)** 的衝突時權威。

| 我正在做 | 先讀 |
|---|---|
| 查功能是否已實作(避免重造) | `docs/references/product_surface.md` **(SoT)** |
| 查 endpoint / DB table / env var / iOS 模組叫什麼 | `docs/references/tech_index.md` **(SoT)** |
| 改 iOS Reader 任何檔案 | `docs/references/feature_boundary_reader.md` |
| 改 iOS Vocab / Sync / TodayReview / KG | `docs/references/feature_boundary_vocabulary.md` + `docs/references/sync_lifecycle.md` **(SoT)** |
| 改 iOS Settings | `docs/references/feature_boundary_settings.md` |
| 改 CSV / Card schema | `docs/references/backend_card_format.md` **(SoT)** |
| 改 sync 狀態流轉(`syncStatus` × `actionType`) | `docs/references/sync_lifecycle.md` **(SoT)** |
| 寫 backend test | `docs/references/backend_testing_strategy.md` |
| 發版前 smoke(15 分鐘) | `docs/references/smoke_checklist.md` |
| 部署 / 用戶查詢 / 額度 / 遠端 / 維護 | 觸發 `devops` skill(內含 SOP) |
| 502 / Caddy / SSL / DB 直查 / pipeline 鎖 / 用戶資料 | `docs/dev/debug.md` |
| 部署流程 / env / migration / Sentry env | `docs/dev/deploy.md` |
| backend 測試 / uv / provider registry / 任務派遣 | `docs/dev/backend-dev.md` |
| iOS 編譯 SOP / 模組速查 / Sentry iOS | `docs/dev/ios-dev.md` |
| UI 規範 / Motion 契約 / Token 禁令 | `docs/dev/ui-design.md` |
| iOS↔backend sync / 多帳戶隔離 / 架構脈絡 | `docs/dev/architecture.md` |
| Claude Code Gateway | `docs/ops/claude-code-gateway.md` |
| host / port / container 配置(Caddy 路由) | `docs/ops/BACKGROUND.md` **(SoT)** |
| 生產禁用指令 / preflight / rollback | `docs/ops/SAFETY_POLICY.md` **(SoT)** — 已寫進鐵律 7 |
| ops 流程 / change flow / hard stop | `docs/ops/SYSTEM_RUNBOOK.md` |

## Doc Tier 契約

每份 doc 的 frontmatter 都有 `tier`。改實作前先確認 tier:

- **reference** — *doc-as-code*。改實作必**同 PR** 更新對應 doc(routers / DB / env / iOS feature scope / CSV schema / host topology / safety)。標 **(SoT)** 者衝突時權威。
- **sop**(`docs/dev/*`) — SOP 流程變了才更新;不是 code-as-doc。
- **snapshot**(`docs/references/{ios_frontend_baseline, build_observability, feature_metrics_inventory}.md`) — 機器生成或 dated。讀前看 `verified_against`,**可能已過時**。
- **policy**(`docs/ops/SAFETY_POLICY.md`) — 動之前需明確決策,PR 必須說明改動原因。
- **archive**(`docs/references/{ui_strategy_*, vocab_design_system_audit}.md`) — 凍結歷史 strategy/audit,**不更新、不引用**。需要當前狀態請讀對應 sop / reference。

## Doc Freshness 自動同步

- 修改 backend router / DB schema / env var / ops 腳本 → 同 PR 更新 `docs/references/tech_index.md`
- 新增 user-facing feature(iOS / backend / admin / chrome) → 同 PR 在 `docs/references/product_surface.md` 追加 bullet
- iOS feature 重構(改檔名/分層/移檔) → 同 PR 更新對應 `docs/references/feature_boundary_*.md`
- sync 邏輯 / CSV schema / host topology / safety 規則變動 → 同 PR 更新對應 (SoT) doc
- iOS 大規模重構 PR 合併後執行 `ops/gen_ios_baseline.sh` 再生 `docs/references/ios_frontend_baseline.md`(script 產出,不手改)
