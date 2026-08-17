<!-- doc-meta
tier: reference
authority: SoT
update_trigger: agent_context_changed
scope:
  - CLAUDE.md
  - .claude/agents/
  - .claude/skills/
  - .claude/commands/
  - docs/sop/review_discipline.md
  - docs/registry.yml
  - ops/context_plane.json
  - ops/context_route.py
  - ops/skill_route.py
verified_against: bf9606b84d4209ea3884a5f1519323fdd374b33f
-->
# KG Agent Context Index

這是角色視野與未知問題升級的唯一索引。它只回答「此角色現在該知道什麼、下一步去哪裡查」；
各 domain 的內容仍由 `docs/registry.yml` 指向的 SoT 負責，不在這裡複製。

## 載入規則

每個 session 依序處理：

1. **Global kernel**：遵守根 `CLAUDE.md` 的安全、TDD、驗證、worktree、receipt、bounded review
   與並行協作硬邊界。這些是所有角色共用的約束，不因角色縮減；需要切片時跑
   `./ops/context_route.py render --role <role> --json`，不要自行讀整份 sibling skill。
2. **Role profile**：讀下表中自己那一列，以及該列的 assigned ticket／task brief；不預載兄弟角色、
   全產品版圖或整份 delivery 歷史。section 缺失、重複或 source/HEAD 在讀取期間變動時，loader
   必須拒絕，不得 fallback 到全文。
3. **Authority lookup**：遇到未知才沿「升級索引」讀下一層；不要用記憶、archive、snapshot 或
   另一個 agent 的散文取代 SoT。`docs/registry.yml` 仍是 owner／trigger／source authority；
   context route manifest 只負責 slice 與 route selection。
4. **Stop / escalate**：仍無法判定時，保留目前工作狀態，依下方 escalation contract 交給正確的
   owner；不可用猜測擴大 scope。

一般 route 不載入 router 的 Tool Friction deep reference；只有 typed task=`tool-friction` 或實際遇到
工具摩擦時，才由 `./ops/context_route.py render --role <role> --task tool-friction --json` 載入。該 reference 的
查重、`dispatch --stream APP` 與 receipt／stream 分流規則是此條件式 context 的唯一內容來源。

只有實際執行 `docs_lint.sh --registry` 或診斷 generated check 時，才用
`./ops/context_route.py render --role <role> --task docs-registry --json` 載入 registry gate deep reference；一般 docs
audit 不預載 generated 的 live-state 歷史。

Global kernel 的內容仍以根 `CLAUDE.md` 為準；本索引不重抄其規則。`kg-agent-context` 是薄入口，
不取代 `kg-router`、`worktree-flow` 或 `kg-receipt`。

## Role profiles

| role | minimum context | do not preload | escalation start |
|---|---|---|---|
| **Ticket Factory** (`platform-steward`) | `kg-agent-context`、`kg-router`、`kg-receipt` 的立單／stream／contract 規則、`./ops/backlog.py lifecycle --json`、需求本身 | Delivery Team fan-in、Gate/cutover、domain implementation、完整產品技術地圖 | `docs/registry.yml` 的 trigger → 產品／技術 SoT；Ticket Factory 持續負責 raised → `dispatchable`，或立即具名的使用者／外部阻塞；若修法需要 code／merge，保留 ticket id、fix_site、groom／contract evidence，交由 `delivery-coordinator` 從 `./ops/backlog.py dispatch` 取得，不自行修產品 code |
| **Delivery Team Integrator** (`delivery-coordinator`) | `kg-agent-context`、assigned batch、backlog lifecycle、`worktree-flow` 的停止點／批次整合／`close-wave`／並發段、`docs/sop/release.md` | Ticket Factory 的 triage 細節、未被 batch 指向的 domain 文件、Catalog 與其他 team 的內部狀態 | 先查 assigned ticket 的 `fix_site` 與 registry trigger；日常依 Gate tier 只跑所需深度，跨功能根目錄且已有真實 S3 route 才升 S3；若尚無 S3 route 不虛構高層證據，留在 S2 並暴露缺口；非重大 S2/S3 BLOCK 可用具名既有 ticket 帶過，重大或 S0/S1/S4 BLOCK 退回；Gate BLOCK 時依 hand-back 的 exact source thread ID 退回原提交者；只在 state／collision／primary race 等不穩定狀況傳 thread message |
| **Delivery Child** (`backend-engineer`、`ios-engineer`、`ops-engineer`) | `kg-agent-context`、assigned groomed ticket、自己的 agent contract、`worktree-flow` 的 child stop／hand-back、最小 domain SoT | Ticket Factory 流程、Integrator 批次收尾、其他 domain、全量 Gate／release 文件 | 開發／hand-back 以 S0+受影響 S1 為最低證據，不自行升級全量 Gate；hand-back 必須附 exact source thread ID（跨 host 加 source host ID）；Gate BLOCK 後由原 thread 修正並以新 commit／新 hand-back 回交；依 assigned path／trigger 查 registry，再向 Integrator 回報跨界或不可判定問題 |
| **Docs Steward** (`docs-steward`) | `kg-agent-context`、assigned docs ticket、`kg-docs-control-plane`、`docs/registry.yml`、最小受影響 SoT | `worktree-flow` child stop／hand-back、domain implementation、全量 release 文件；只有明示 handback task 才載入 worktree slices | 依 registry trigger／impact 查 SoT；只有實際 hand-back 才載入 child stop／handoff slice，跨界時交回 Integrator |
| **Review service** (`code-reviewer`) | `kg-agent-context`、指定 commit SHA × scope、`docs/sop/review_discipline.md` | 業務全景、未被 scope 觸及的 domain 文件、任何 code modification | 只把 block／nit／tooling debt 回給 caller；不自行修 code 或改寫 scope |

## Ticket Factory 的完成線與責任邊界

Ticket Factory 的核心責任是：任何問題進入後，持續負責到它成為可派工工作，或被明確判定為真正需要
使用者／外部權限的事項。`groomed` 不是完成線；`contract-ready` 才是 Ticket Factory 的完成線。

| 狀態／看板語彙 | Ticket Factory 的意義 | 機器對應與責任歸屬 |
|---|---|---|
| `open` | 問題已記錄，但尚未形成工作 | backlog entry；仍由 Ticket Factory triage |
| `triaged`／`queued` | 修法方向已寫清楚，但仍可能未通過契約檢查 | lifecycle `status=triaged`；groomed 不等於 contract-ready |
| `contract-not-ready` | 驗收、依賴、證據或 baseline 尚未補完整 | 人類語彙；機器通常是 `status=contract-blocked` 或 `dispatch.withheld_contract`，不得派出 |
| `dispatchable` | 可直接交給 Delivery Team，五條 dispatch 條件都成立 | 衍生分類，不新增 lifecycle status；唯一正式入口是 `dispatch`／`list --dispatch` |
| `held` | 已被 worktree 認領，交由 Delivery Team 執行 | worktree registry 推導，不儲存為 backlog status |
| `fixed`／`wont-fix` | 已有可追溯的修復或明確收尾結果 | backlog lifecycle 結案，須保留 acceptance／resolution 證據 |

`groom` 只把票放入 queued／groomed 階段，補齊 `brief`、`plan`、`fix_site`、結構化 `scope` 與
acceptance；它不宣稱可派工。只有 `contract_status=ready`、`contract_baseline=red`、
`contract_evidence`／checked metadata 完整且 `preflight` 通過，才越過 contract-ready 完成線。
`dispatch` 是 Delivery Team 唯一正式取票入口；`list`、手動轉交或聊天訊息都不能替代它。

contract blocker 不可只留下泛稱 `blocked`：缺欄位就補齊；命令不存在就修成可重跑命令；測試依賴未落地
就拆成可獨立派工的 contract-repair／investigation／evidence ticket；baseline 不成立就重新取證或重寫
問題定義；duplicate、no-op、已修或不再成立就依 lifecycle 具名收斂為 `wont-fix`。真正需要使用者決策、
GUI-only 或外部權限時，立即具名升級對象、阻塞原因、證據與下一步，票保持 `contract-blocked`，不得偽造 ready。

Ticket Factory 不修產品 code、不做整合、不做 cutover；它負責把工作定義到能被修，並把 contract-ready
票交給 Delivery Team。分析 agent 可以 fan-out，但只回傳結構化提案，不直接寫 backlog；所有 ledger write
由單一控制點依當下證據序列化完成。fan-out 優先順序固定為 bounded bug、重構、工具摩擦、測試維護、
文件修復；開放式產品行為、策略與 open-ended discovery 不自行臆測，先升級決策。

角色不是階層命令，而是資訊邊界。Integrator 是 Delivery Team thread 的主 agent；child 的停止點
永遠是自己的 `commit + hand-back`。完整動詞與授權邊界分別以 `ops/backlog.py lifecycle --json`、
`dispatch` 與 `worktree-flow` 為準。

Fan-out 的淺規則：優先選 bounded bug、refactor、tooling friction、docs、test maintenance 等可獨立驗收的工作；新產品行為、策略、open-ended discovery、跨面產品變更需 parent 明示後才列為 fan-out 優先項。這只是 agent 的排序／派工指引，不是 backlog lifecycle、acceptance 或 status 的新契約。

## 驗證層級與耗時控制面

- Child 開發／hand-back：S0 + 受影響 S1；Integrator 批次整合：S0 + 受影響 S2；只有跨模組且存在真實 route 才升 S3；S4 僅用於發布。較低層級的證據不可冒充較高層級。
- 受影響的 orchestrator source 優先走 `ops/test_route.py` 的明確 route；每次先 collect-only，route 失效必回退父群，未知 source 不得變成零測試綠燈。
- 長測試 bundle 用 `ops/test_timing.py run --bundle <manifest> --json`，完成後讀 `status`／`wait`；不要自行輪詢 child。`estimate` 只回報區間與 confidence，歷史 ledger 是 gitignored 輔助證據，不改 gate verdict。

## Authority escalation index

先用 `docs/registry.yml` 的 `id`／`triggers`／`sources` 找 owner，再讀該 entry 的 `path`。下表只提供
常見未知的入口，不取代 registry：

| unknown | first authority | next authority |
|---|---|---|
| 不知道某功能是否存在、使用者看到什麼 | `reference.product_surface` | 對應 `reference.feature_boundary.*` |
| endpoint、module、DB table、env、CLI／ops surface | `reference.tech_index` | `sop.backend` 或 `reference.ops_state_plane` |
| iOS View／UI／feature scope | 對應 `reference.feature_boundary.reader|vocabulary|notebook|bookshelf|podcast|settings|discover` | `sop.ui_design`、`reference.ui_components`／`reference.ui_review_checklist`／`reference.ui_state_matrix`、`sop.ios` |
| sync／CSV／card lifecycle | `contract.sync_lifecycle` 或 `contract.card_format` | `reference.tech_index` |
| docs、registry、verified anchor、agent-facing surface | `sop.doc_sync`、`sop.docs_dogfood` | `kg-docs-control-plane` 與 `docs/registry.yml` |
| worktree、batch、lock、Gate、cutover、sync | `worktree-flow` | `sop.release`、assigned ticket receipt |
| review scope、輪數、停止條件 | `sop.review_discipline` | `kg-receipt` |
| production、host、rollback、不可逆動作 | `policy.safety` | `contract.host_topology`、`sop.deploy`、`devops` |
| 不知道該用哪個 typed tool | `./ops/capability_matrix.py --json` | `kg-router` |

若 path 不明，先跑 `./ops/docs_impact.py --files <path...> --explain`；若是 agent-facing command、
flag、skill 或 role contract，使用 registry 唯一清單做 `./ops/docs_impact.py --surface-scan '<pattern>'`，
不要自行用 broad `rg` 假造 impact。

## Unknown escalation contract

### 可由自己解決

- 只是 path、命令或既有功能名稱不確定：查 registry／capability matrix／對應 SoT。
- 只是測試入口不確定：先查 role row 指定的 SOP 與 acceptance；不要因不知道就跑全套。
- 只是 lock 競爭：依工具 heartbeat 與指數退避等待，不重開 child、不 busy-loop。

### 必須交給 owner

- **Ticket Factory**：修法需要 code／merge／release 判斷 → 只補 ticket 的可執行描述，交由 Delivery
  Team；不替 Integrator 做整合決策。
- **Delivery Child**：跨 bounded context、fix-site 重疊、ticket 與 SoT 衝突 → 暫停越界動作，向
  Integrator 回報證據與選項。
- **Delivery Team Integrator**：source／state／primary race、衝突或工具 schema 不一致 → 用內建
  thread message 通知受影響 peer；訊息至少帶 canonical contract 的 `team/slug`、`branch`、
  `worktree path`、`HEAD`、`state path`、具體 blocker 與證據、要求的動作，以及
  `pause|continue` 判定；若是 child Gate BLOCK，另依 hand-back receipt 的 exact source thread ID
  回到原提交者。正常進度仍讀 registry／state／receipt，不聊天同步。
- **所有角色**：真正的使用者策略、預算、不可逆 production／GUI-only 動作或安全紅線 → 升級使用者，
  不用文件假裝替使用者做取捨。

### Tooling debt

工具摩擦的分流與 receipt 欄位依 `kg-receipt`「Tooling Debt」及 `kg-router`「Tool Friction」；本索引
只要求先查重，並在未修復時把 `IMP` tooling debt 交給正確 owner，不無聲繞過 typed surface。

## Scope guard

「不知道」不是讀完整 repo 的許可。先沿一條 authority edge 走一步；只有 SoT 明確要求的相鄰文件才
加入 context。若仍沒有答案，留下 escalation receipt／message，讓下一個角色接續，而不是把 Ticket
Factory、Integrator、domain worker 的三種視野重新拼成一份萬用 skill。
