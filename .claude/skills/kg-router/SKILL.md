---
name: kg-router
description: "KG 新對話冷啟動與任務路由。當使用者要求盤點、設計流程、找入口、接手陌生任務、判斷該用哪個 skill/doc/tool，或任務橫跨 docs/ops/iOS/backend/podcast/release 時觸發。"
user-invocable: true
version: 1.0.0
---

# KG Router

本 skill 是新對話第一層 bootloader。它不做業務實作，只把任務導向正確的 skill、SoT 與 typed tool。

## Cold Start

1. 先讀使用者意圖，分成 `observer` / `operator` / `editor` / `production-capable`。
2. 跑 `./ops/capability_matrix.py --json`，確認是否已有 typed surface。
3. 若任務牽涉功能/endpoint/env/DB/ops/iOS 模組，讀 `docs/reference/product_surface.md` 或 `docs/reference/tech_index.md`。
4. 若任務牽涉文件同步，交給 `kg-docs-control-plane`。
5. 若任務牽涉完成回報或交接，交給 `kg-receipt`。

## Routing Table

| 意圖 | 首選入口 |
|---|---|
| 不知道能不能碰某 surface | `./ops/capability_matrix.py --json` |
| 生產狀態 / 用戶資料 / 部署 | `devops` skill + `./ops/devops_kg_safe.sh ...` |
| 成本 / 帳單 / drift | `billing` skill |
| 用戶資料、圖譜、額度深度分析 | `data-analysis` skill |
| bug / test failure / 異常行為 | `app-debug` skill |
| 隔離工作樹 intent→dev→merge 進 main；「需要 main」任務（bootstrap 補登記/追平 local main/repo 手術鎖） | `worktree-flow` skill + `ops/worktree_orchestrate.py`（preflight/open/adopt/gate/cutover/resolve/sync-main/freeze） |
| iOS build/test/release readiness | `./ops/ios_ops.sh commands --json`，再讀 `docs/sop/ios.md` |
| docs impact / lint / registry | `kg-docs-control-plane` skill |
| release version/changelog/tag | `./ops/release.sh status` |
| podcast pipeline / monitor / publish drift | `podcast` skill + `./ops/podcast_ops.py --help` |
| LLM prompt eval | `(cd lab/llm_eval && uv run python scripts/cli.py --help)` |

## Hard Stops

- 不直接讀 DB 或遠端檔案來替代 `ops-cli` / `ops-edit` / safe wrapper。
- 不用 stale docs 覆蓋 live command output。
- 不把 docs impact hints 當成自動必改清單；要用語意 trigger 判斷。
- 不自行升級到 production-capable surface；先明示 side effect 與驗證方式。

## Tool Friction

使用 typed tool 遇到摩擦時先判斷嚴重度：

- 小問題：不影響正確性、不會誘導繞路，例如文案可更清楚。記到 receipt 的 `tooling debt`，回到原目標。
- 中大型問題：help 失準、入口漂移、JSON 不穩、錯誤訊息不可行動、工具讓 agent 想繞過 typed surface。立即停下來修工具/skill/doc,跑對應 regression，再回到原目標。
- 生產或資料寫入路徑上的摩擦預設視為中大型問題。

## Output Contract

路由完成後，至少回報：

- `intent`: 任務類型與 capability tier
- `authority`: 讀過的 SoT doc 或 JSON surface
- `entrypoint`: 下一步 typed command / skill
- `validation`: 完成後應跑的 gate
- `risk`: 是否跨 production / external push / local build / data write
- `tooling debt`: 小摩擦記錄；若已修工具,列 regression command
