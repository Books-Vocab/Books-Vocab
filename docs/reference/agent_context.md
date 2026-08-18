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

## Role identity gate（所有任務命令前）

任何 agent 在修改檔案或執行任務命令前，必須先確認以下五種且僅五種 canonical identity：
`Manager`、`Integrator`、`Direct-assignment Child`、`Ticket Factory Child`、`Ticket Delivery Child`。
其中三種 Child 的差別是工作責任，不是聊天層身份；`work_mode` 分別是
`direct-assignment`、`ticket-factory`、`ticket-delivery`。Docs Steward／Review service 是內部支援工具路徑，
不是第六種交付身份，也不能取得 primary 落地權。

角色未確認時，唯一允許的操作是唯讀角色／context 判定：
`./ops/context_route.py identify --role <identity> [--work-mode <mode>] --json`，再用同一組 identity／mode
執行 `route`／`render`。在這之前不得修改檔案、claim ticket、open/adopt worktree、跑 Gate、整合、
cutover、resolve、sync、deploy 或其他任務命令。`identify` 的 `status=confirmed` 只證明身份宣告完整，
不授予 primary、staging 或 production 權限；真正權限仍由 worktree registry、operator contract 與
Manager 明示授權決定。

| canonical identity | work mode | 開工前必備 | 停止／落地邊界 |
|---|---|---|---|
| **Manager** | `none` | current primary、origin/main、integration state 視野 | 唯一負責 current-main admission、Gate、檔案衝突修復、cutover、resolve、sync；deploy 另需 release 意圖 |
| **Integrator** | `none` | assigned batch、Scope／檔案佔用矩陣 | 只 fan-out、staging fan-in、保留衝突證據，交 staging handoff 給 Manager |
| **Direct-assignment Child** | `direct-assignment` | exact source thread、structured Scope | 只做自己的 Scope；局部驗證後 commit＋typed hand-back |
| **Ticket Factory Child** | `ticket-factory` | factory 任務、structured Scope | 只把問題收斂成可派工 contract，不做產品整合或 primary 落地 |
| **Ticket Delivery Child** | `ticket-delivery` | dispatch／campaign ticket 與 ticket Scope | 只完成 ticket Scope；局部驗證後以 outcomes、exact HEAD、typed seal hand-back |

確認後的第一性邊界固定如下：Manager 唯一看守 primary／current-main／origin/main；Integrator 只做
fan-out 與 staging fan-in；三種 Child 只做自己的 Scope、局部驗證、commit 與 typed hand-back。任何 agent
遇到角色、Scope、權限或責任不確定，先停在這道 gate，不猜、不改、不把聊天層的「主要 AI」身份當成交付角色。

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
| **Manager** (`manager`) | `kg-agent-context`、`worktree-flow` 的 Manager 落地段、assigned staging handoff／Gate receipt、`docs/sop/release.md` | Ticket Factory Child 的 triage 細節、child domain implementation、未納入本輪的 worktree | 先重查 current `main`／`origin/main`、integration state、source hand-back SHA 與 Scope；Manager 是唯一 primary／origin/main 落地責任者，也是 current-main admission、檔案衝突與 Gate BLOCK 歸屬的裁決者；可執行 gated continuation、`close-wave --commit`、`cutover --commit`、`resolve --via-integration`、`sync --commit`；`deploy` 仍需另外的 release 意圖；Child slice defect 依 exact source thread ID 原路退回，整合／衝突問題由 Manager-owned staging 修復 |
| **Integrator** (`delivery-coordinator`) | `kg-agent-context`、assigned batch、backlog lifecycle、Scope／檔案佔用矩陣、`worktree-flow` staging／並發段 | Ticket Factory triage、未被 batch 指向的 domain 文件、Manager primary／release context | 先對帳 child hand-back、source tip、Scope 與 integration state；只做 fan-out、`integrate --commit --no-gate`、`--append`、衝突證據整理與 staging tree 清理；不得自行解檔案衝突、catchup、看守 primary、跑 Gate/cutover/sync；直接交 staging handoff 給 Manager |
| **Direct-assignment Child** (`backend-engineer`、`ios-engineer`、`ops-engineer`) | `kg-agent-context`、structured Scope、agent contract、`worktree-flow` child stop／hand-back、最小 domain SoT | Ticket Factory contract、Integrator staging、Manager primary／release context、全量 Gate、primary commit 拓撲 | 僅能在自己的 Scope 內實作；S0＋受影響 S1 後 commit＋typed hand-back；不追蹤 primary、不 catchup、不跑 Gate/cutover/resolve/sync/deploy |
| **Ticket Factory Child** (`platform-steward`) | `kg-agent-context`、`kg-router`、`kg-receipt` 的立單／stream／contract 規則、`./ops/backlog.py lifecycle --json`、factory Scope | Delivery Team fan-in、Gate/cutover、domain implementation、完整產品技術地圖 | 持續把問題收斂到 contract-ready／dispatchable 或具名外部阻塞；不修產品 code、不 claim delivery ticket、不落地 primary |
| **Ticket Delivery Child** (`backend-engineer`、`ios-engineer`、`ops-engineer`) | `kg-agent-context`、dispatch／campaign ticket、ticket Scope、agent contract、`worktree-flow` child stop／hand-back、最小 domain SoT | Ticket Factory triage、Integrator staging、Manager primary／release context、全量 Gate、primary commit 拓撲 | 只完成 ticket Scope；S0＋受影響 S1 後附 exact source thread ID、HEAD、seal hand-back；不追蹤 primary、不 catchup、不跑 Gate/cutover/resolve/sync/deploy |
| **Docs Steward** (`docs-steward`) | 已確認 canonical identity 的 caller 所指定的 docs slice、`kg-docs-control-plane`、`docs/registry.yml`、最小受影響 SoT | 自行選擇交付身份、worktree／primary 落地權、domain implementation、全量 release 文件 | 先由 caller 完成五種 identity gate；再依 registry trigger／impact 查 SoT。Docs Steward 只是支援路徑，沿用 caller 的身份與權限，不產生獨立交付 receipt；跨界時把證據交回 caller |
| **Review service** (`code-reviewer`) | `kg-agent-context`、指定 commit SHA × scope、`docs/sop/review_discipline.md` | 業務全景、未被 scope 觸及的 domain 文件、任何 code modification | 只把 block／nit／tooling debt 回給 caller；不自行修 code 或改寫 scope |

## Ticket Factory Child 的完成線與責任邊界

Ticket Factory Child 的核心責任是：任何問題進入後，持續負責到它成為可派工工作，或被明確判定為真正需要
使用者／外部權限的事項。`groomed` 不是完成線；`contract-ready` 才是 Ticket Factory Child 的完成線。

| 狀態／看板語彙 | Ticket Factory Child 的意義 | 機器對應與責任歸屬 |
|---|---|---|
| `open` | 問題已記錄，但尚未形成工作 | backlog entry；仍由 Ticket Factory Child triage |
| `triaged`／`queued` | 修法方向已寫清楚，但仍可能未通過契約檢查 | lifecycle `status=triaged`；groomed 不等於 contract-ready |
| `contract-not-ready` | 驗收、依賴、證據或 baseline 尚未補完整 | 人類語彙；機器對應為既有 lifecycle `status=contract-blocked` 或 `dispatch.withheld_contract`，不得新增另一個 status，也不得派出 |
| `dispatchable` | 可直接交給 Delivery Team，五條 dispatch 條件都成立 | 衍生分類，不新增 lifecycle status；唯一正式入口是 `dispatch`／`list --dispatch` |
| `held` | 已被 worktree 認領，交由 Delivery Team 執行 | worktree registry 推導，不儲存為 backlog status |
| `fixed`／`wont-fix` | 已有可追溯的修復或明確收尾結果 | backlog lifecycle 結案，須保留 acceptance／resolution 證據 |

`groom` 只把票放入 queued／groomed 階段，補齊 `brief`、`plan`、`fix_site`、結構化 `scope` 與
acceptance；它不宣稱可派工。只有 `contract_status=ready`、`contract_baseline=red`、
`contract_evidence`／checked metadata 完整且逐票 backlog contract preflight（`./ops/backlog.py preflight <id> --json`）通過，才越過 contract-ready 完成線；全 store 另以 `./ops/backlog.py validate --baseline-check` 驗證。
`dispatch` 是 Delivery Team 唯一正式取票入口；`list`、手動轉交或聊天訊息都不能替代它。

contract blocker 不可只留下泛稱 `blocked`：缺欄位就補齊；命令不存在就修成可重跑命令；測試依賴未落地
就拆成可獨立派工的 contract-repair／investigation／evidence ticket；baseline 不成立就重新取證或重寫
問題定義；duplicate、no-op、已修或不再成立就依 lifecycle 具名收斂為 `wont-fix`。真正需要使用者決策、
GUI-only 或外部權限時，立即具名升級對象、阻塞原因、證據與下一步，票保持 `contract-blocked`，不得偽造 ready。

Ticket Factory Child 不修產品 code、不做整合、不做 cutover；它負責把工作定義到能被修，並把 contract-ready
票交給 Delivery Team。分析 agent 可以 fan-out，但只回傳結構化提案，不直接寫 backlog；所有 ledger write
由單一控制點依當下證據序列化完成。fan-out 優先順序固定為 bounded bug、重構、工具摩擦、測試維護、文件修復；開放式產品行為、策略與 open-ended discovery 不自行臆測，先升級決策。

角色不是階層命令，而是資訊與落地邊界。Integrator 是 Delivery Team 的 fan-out／staging 協調者，遇到檔案衝突只保留證據並交 Manager；
Manager 是唯一把 staging 送進 primary／origin/main、處理 current-main admission 與整合修復的角色；Child 的停止點永遠是自己的
`commit + typed hand-back`，不把 primary 的 commit 拓撲當成自己的工作。完整動詞與授權邊界分別以 `ops/backlog.py lifecycle --json`、`dispatch`、
 registry admission 與 `worktree-flow` 為準。

Fan-out 的淺規則：優先選 bounded bug、refactor、tooling friction、test maintenance、docs 等可獨立驗收的工作；新產品行為、策略、open-ended discovery、跨面產品變更需 parent 明示後才列為 fan-out 優先項。這只是 agent 的排序／派工指引，不是 backlog lifecycle、acceptance 或 status 的新契約。

## 驗證層級與耗時控制面

- Child 開發／hand-back：S0 + 受影響 S1；Integrator staging：S0 + 受影響的快速檢查，不跑 Manager Gate；Manager 整合／cutover：S0 + 受影響 S2；只有跨模組且存在真實 route 才升 S3；S4 僅用於發布。較低層級的證據不可冒充較高層級。
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

- **Ticket Factory Child**：修法需要 code／merge／release 判斷 → 只補 ticket 的可執行描述，交由 Delivery
  Team；不替 Integrator 做整合決策。
- **Direct-assignment／Ticket Delivery Child**：跨 bounded context、fix-site 重疊、ticket 與 SoT 衝突 → 暫停越界動作，向
  Integrator 回報證據與選項。
- **Manager**：source／state／primary race、Gate BLOCK、cutover、resolve 或 sync 的落地決策 → 讀 staging handoff、
  registry 與 exact source thread ID；Child slice defect 原路退回，整合／檔案衝突由 Manager 在 staging 修復，不把 Integrator staging handoff 當 child receipt。
- **Integrator**：source／state／工具 schema 不一致或衝突證據（但尚未落地 primary）→ 用內建
  thread message 通知受影響 peer；訊息至少帶 canonical contract 的 `team/slug`、`branch`、
  `worktree path`、`HEAD`、`state path`、具體 blocker 與證據、要求的動作，以及
  `pause|continue` 判定；不得自行解檔案衝突或要求 Child catchup；若是 child Gate BLOCK，另依 hand-back receipt 的 exact source thread ID
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
