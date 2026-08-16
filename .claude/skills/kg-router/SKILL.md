---
name: kg-router
description: "KG 新對話冷啟動與任務路由。當使用者要求盤點、設計流程、找入口、接手陌生任務、判斷該用哪個 skill/doc/tool，或任務橫跨 docs/ops/iOS/backend/podcast/release 時觸發；角色視野改由 kg-agent-context progressive disclosure。"
user-invocable: true
version: 1.1.0
---

# KG Router

本 skill 是新對話第一層 bootloader。它不做業務實作，只把任務導向正確的 skill、SoT 與 typed tool。

## Cold Start

1. 先把使用者意圖映射為 `.claude/skills/catalog.json` 的 typed intent；先跑
   `./ops/skill_route.py validate --json`，再跑 `route --intent <intent> --json`。自然語言只提供候選，
   不得把多個 keyword 命中當成多個 primary。
2. `kg-router` 只作 bootstrap；依 route 的 `requires` 順序載入，`optional`／`closure` 只有明示需求
   或收尾階段才載入。`skill_route.py` 的輸出不是 capability 或 production 授權。
3. 若 thread 已有 Ticket Factory／Delivery Team／child／review 身分，另跑
   `./ops/context_route.py render --role <role> --json`；只讀選中的 role／authority slices，不能 fallback 全文。
4. 只有要判定 side effect 或 command capability 時才跑 `./ops/capability_matrix.py --json`；功能、endpoint、
   env、DB、ops、iOS authority 依 `docs/registry.yml` 與 `docs/reference/agent_context.md` 的 index 查最小 SoT。

## Routing Table

Skill inventory、typed intent、dependency、exclusion 與 fixtures 只看
`.claude/skills/catalog.json`；不要在此維護第二份 keyword table。常用控制面入口：

| 判定 | typed entrypoint |
|---|---|
| skill primary／dependency | `./ops/skill_route.py route --intent <intent> --json` |
| role／surface／task context | `./ops/context_route.py render --role <role> [--surface <surface>] [--task <task>] --json` |
| side effect／capability | `./ops/capability_matrix.py --json --tier <tier>` |
| docs impact／lint | `kg-docs-control-plane` → `./ops/docs_impact.py`／`./ops/docs_lint.sh` |
| delivery／worktree | route 選 `worktree-flow` → `ops/worktree_orchestrate.py` |

Domain skill 的深層 CLI、SOP、reference 只在 primary route 已選定且 authority index 指向時再讀；
不因冷啟動預載整份 domain skill。

## Hard Stops

- 不直接讀 DB 或遠端檔案來替代 `ops-cli` / `ops-edit` / safe wrapper。
- 不用 stale docs 覆蓋 live command output。
- 不把 docs impact hints 當成自動必改清單；要用語意 trigger 判斷。
- 不自行升級到 production-capable surface；先明示 side effect 與驗證方式。

## Tool Friction

只有 typed task 是 `tool-friction`，或目前確實遇到工具摩擦時，才讀
`.claude/skills/kg-router/references/tool-friction.md`；一般冷啟動、docs audit 與 domain route 不預載。

## Output Contract

路由完成後，至少回報：

- `intent`: 任務類型與 capability tier
- `context`: role profile、實際載入的 authority、刻意未載入的深層 context
- `authority`: 讀過的 SoT doc 或 JSON surface
- `entrypoint`: 下一步 typed command / skill
- `validation`: 完成後應跑的 gate
- `risk`: 是否跨 production / external push / local build / data write
- `escalation`: 未知問題若未自行解決，具名 owner、證據與下一步
- `tooling debt`: 小摩擦記錄；若已修工具,列 regression command
