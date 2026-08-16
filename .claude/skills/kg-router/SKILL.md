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

使用 typed tool 遇到摩擦時先判斷嚴重度：

- 小問題：不影響正確性、不會誘導繞路，例如文案可更清楚。記到 receipt 的 `tooling debt`，回到原目標。
- 中大型問題：help 失準、入口漂移、JSON 不穩、錯誤訊息不可行動、工具讓 agent 想繞過 typed surface。立即停下來修工具/skill/doc,跑對應 regression，再回到原目標。
- 生產或資料寫入路徑上的摩擦預設視為中大型問題。

非當場修掉者一律立單,但**立單前先查重**:`./ops/backlog.py list --grep '<關鍵字或檔名>'`(不分大小寫 regex,掃 detail/resolution/plan/fix_site,與其他旗標取交集)。命中就接手既有票別開新的——鄰居單常常是 `fix_site` 命中而 detail 完全沒提到那個檔。確認沒有才 `./ops/backlog.py add`（**自由文字含反引號 / `$` / 跳脫字元時改用 `--<flag>-file <路徑>`**——argv 會先過你的 shell，反引號在那裡是命令替換，句子會在工具看到之前被改掉且無人抗議） 立單,**先選對 stream 再填**(能一句話講清楚就順手補 `--brief` / `--scope`,那是手機看板唯一顯示得出來的東西,梳理階段工具當場就會要求（蓋 groom 戳記時擋）)——選錯 stream 等於選錯 owner:

批次 wave worker 必須改用 `add --stage`，讓票留在共用 gitignored queue 並由整合者 `anchor --commit`；一般單線工作才用裸 `add` 立即寫 store。

票的角色邊界、狀態與常見情境一律讀 `./ops/backlog.py lifecycle --json`；`groom` 讓票可執行且是 dispatch 前置，`verify` 重新取證但與 dispatch 正交。不要在 router 另造流程版本。

- `--stream IMP` → owner `platform-steward`
- `--stream APP` → owner 對應 Line worker(`ios-engineer` / `backend-engineer`),取票 `./ops/backlog.py dispatch --stream APP`(**不是** `list --stream APP`——`list` 會連已結案與別人認領中的一起吐給你)

本節分的是**嚴重度**(小 / 中大),stream 分的是**誰是 owner**——兩者正交,一筆 entry 要各答一次。哪個缺陷屬哪條 stream 的可判定判準見 `kg-receipt`「Stream 分流」(那是 SoT,此處不複製路徑清單,免得兩邊漂移)。

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
