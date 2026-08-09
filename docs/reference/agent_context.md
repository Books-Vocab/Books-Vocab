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
verified_against: 7046dd9bf
-->
# KG Agent Context Index

這是角色視野與未知問題升級的唯一索引。它只回答「此角色現在該知道什麼、下一步去哪裡查」；
各 domain 的內容仍由 `docs/registry.yml` 指向的 SoT 負責，不在這裡複製。

## 載入規則

每個 session 依序處理：

1. **Global kernel**：遵守根 `CLAUDE.md` 的安全、TDD、驗證、worktree、receipt、bounded review
   與並行協作硬邊界。這些是所有角色共用的約束，不因角色縮減。
2. **Role profile**：讀下表中自己那一列，以及該列的 assigned ticket／task brief；不預載兄弟角色、
   全產品版圖或整份 delivery 歷史。
3. **Authority lookup**：遇到未知才沿「升級索引」讀下一層；不要用記憶、archive、snapshot 或
   另一個 agent 的散文取代 SoT。
4. **Stop / escalate**：仍無法判定時，保留目前工作狀態，依下方 escalation contract 交給正確的
   owner；不可用猜測擴大 scope。

Global kernel 的內容仍以根 `CLAUDE.md` 為準；本索引不重抄其規則。`kg-agent-context` 是薄入口，
不取代 `kg-router`、`worktree-flow` 或 `kg-receipt`。

## Role profiles

| role | minimum context | do not preload | escalation start |
|---|---|---|---|
| **Ticket Factory** (`platform-steward`) | `kg-agent-context`、`kg-router`、`kg-receipt` 的立單／stream 規則、`./ops/backlog.py lifecycle --json`、需求本身 | Delivery Team fan-in、Gate/cutover、domain implementation、完整產品技術地圖 | `docs/registry.yml` 的 trigger → 產品／技術 SoT；若修法需要 code／merge，保留 ticket id、fix_site、groom evidence，交由 `delivery-coordinator` 從 `./ops/backlog.py dispatch` 取得，不自行修 code |
| **Delivery Team Integrator** (`delivery-coordinator`) | `kg-agent-context`、assigned batch、backlog lifecycle、`worktree-flow` 的停止點／批次整合／`close-wave`／並發段、`docs/sop/release.md` | Ticket Factory 的 triage 細節、未被 batch 指向的 domain 文件、Catalog 與其他 team 的內部狀態 | 先查 assigned ticket 的 `fix_site` 與 registry trigger；再讀所需 domain SoT；只在 state／collision／primary race 等不穩定狀況傳 thread message |
| **Delivery Child** (`backend-engineer`、`ios-engineer`、`ops-engineer`、`docs-steward`) | `kg-agent-context`、assigned groomed ticket、自己的 agent contract、`worktree-flow` 的 child stop／hand-back、最小 domain SoT | Ticket Factory 流程、Integrator 批次收尾、其他 domain、全量 Gate／release 文件 | 依 assigned path／trigger 查 registry；先讀 domain SoT，再向 Integrator 回報跨界或不可判定問題 |
| **Review service** (`code-reviewer`) | `kg-agent-context`、指定 commit SHA × scope、`docs/sop/review_discipline.md` | 業務全景、未被 scope 觸及的 domain 文件、任何 code modification | 只把 block／nit／tooling debt 回給 caller；不自行修 code 或改寫 scope |

角色不是階層命令，而是資訊邊界。Integrator 是 Delivery Team thread 的主 agent；child 的停止點
永遠是自己的 `commit + hand-back`，Ticket Factory 只產出 groomed ticket，不宣稱修復完成。完整動詞與
授權邊界分別以 `ops/backlog.py lifecycle --json` 與 `worktree-flow` 為準。

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
  `pause|continue` 判定。正常進度仍讀 registry／state／receipt，不聊天同步。
- **所有角色**：真正的使用者策略、預算、不可逆 production／GUI-only 動作或安全紅線 → 升級使用者，
  不用文件假裝替使用者做取捨。

### Tooling debt

工具摩擦的分流與 receipt 欄位依 `kg-receipt`「Tooling Debt」及 `kg-router`「Tool Friction」；本索引
只要求先查重，並在未修復時把 `IMP` tooling debt 交給正確 owner，不無聲繞過 typed surface。

## Scope guard

「不知道」不是讀完整 repo 的許可。先沿一條 authority edge 走一步；只有 SoT 明確要求的相鄰文件才
加入 context。若仍沒有答案，留下 escalation receipt／message，讓下一個角色接續，而不是把 Ticket
Factory、Integrator、domain worker 的三種視野重新拼成一份萬用 skill。
