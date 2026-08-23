<!-- doc-meta
tier: reference
authority: SoT
update_trigger: delivery-model-changed
scope:
  - CLAUDE.md
  - .github/
  - .claude/agents/
  - .claude/skills/
  - .claude/skills/catalog.json
  - docs/reference/project_onboarding.md
  - docs/reference/agent_context.md
  - docs/runbook/system.md
  - docs/sop/review_discipline.md
  - docs/sop/doc_sync.md
  - docs/sop/delivery_control_dogfood.md
  - docs/sop/release.md
  - ops/context_plane.json
  - ops/context_route.py
  - ops/agent_onboard.py
  - ops/task_registry.py
  - ops/lib/streaming_command.py
  - ops/delivery.py
  - ops/delivery_control/
  - ops/worktree_registry.py
  - ops/worktree_orchestrate.py
verified_against: afe016c4ea2fcbd7306f9c4f40b4556e77865100
-->
# GitHub-native Delivery Model

這是 KG 交付模型的唯一權威文件。它定義工作如何進入系統、如何收斂到 PR，以及本機工具不能承擔什麼；它不記錄某一張 Issue、某一個 PR 或某一輪工作的即時狀態。

## 第一性原理

GitHub 是整套交付控制面：

| 交付問題 | 唯一 owner |
|---|---|
| 新工作、風險與缺口的發現 | User／Backlog Scout（observation） |
| 需要排序、追蹤或 fan-out 的 durable demand | GitHub Issue |
| 要不要做、為什麼做、完成判準 | GitHub Issue（可選） |
| 優先順序、視圖、里程碑 | GitHub Project |
| 一次實作的隔離空間 | branch + local worktree |
| 變更、討論、review、驗證、合併請求 | Pull Request |
| 自動測試與 required checks | GitHub Actions |
| 合併後的產品真相 | GitHub `main` |
| 合併後的正式發布與生產安全 | Release／Deploy SOP |

最重要的規則是：

> Issue 是規劃與派工工具，不是程式碼交付工具；PR 是所有程式碼變更的共同交付入口。

所有 code change 都要走：

```text
branch → commit → PR → required + advisory confidence／CR／DS → CM merge → main → release/deploy（若有明確意圖）
```

`main` 不接受直接寫入。merge 不是 production approval；release、deploy、health gate、rollback 仍由各自安全邊界控制。

## Agent onboarding contract

所有代理先經 [`project_onboarding.md`](project_onboarding.md) 建立 KG 的共同概覽，再確認 canonical identity、工作入口與 assignment，最後才載入 primary skill 和 bounded domain docs。可執行入口是：

```bash
./ops/agent_onboard.py --identity '<identity>' --intent '<intent>' --entry '<entry>' [--specialist-intent '<identity-scoped specialist>'] --evidence '<JSON object containing the required assignment evidence>' --json
```

`--evidence` 缺少任一 assignment requirement 時，onboarding 會在 assignment fail closed；只有 `status=ready` 才會載入 skill 與 domain。`ops/context_plane.json` 是身份、入口、context intent 與 skill intent mapping 的 machine-readable SoT；`.claude/skills/catalog.json` 是 primary skill、dependency、optional、forbidden 與 closure 的 SoT。`ops/context_route.py` 與 `ops/skill_route.py` 只保留給 maintainer 做 `validate`／`--diagnostic` cross-validation；agent-facing loader 唯一是 `ops/agent_onboard.py`。

Onboarding 的成功只代表上下文 contract 完整，不代表 GitHub、merge、release、deploy 或 production 授權。route、identity、worktree hand-back 與 process evidence 都不能取代 branch protection、Actions required checks、environment approval 或 production safety wrapper。文件記技術與操作真相；skill 記載代理的載入、協調與交接方法，不保存 Issue／PR／Project 狀態。

## 角色

角色是責任邊界，不是本機組織階層，也不是第二套權限系統。GitHub repository rules、branch protection、Actions environment approval、production wrapper 與帳號權限才是真正的授權來源。

| 角色 | 責任 | 不負責 |
|---|---|---|
| **CM — Codebase Manager** | 協調整體交付；驗證 exact Ready tuple；控制 merge queue／merge；每次 landing 後讓本地 `main` 與 `origin/main` 精確同步 | 修改產品 code、修改 Worker／Issue Solver worktree、修 PR body／registry、代替 IM 發 PR |
| **IM — Issues Manager** | 管理 GitHub Issue／Project；排序與派工；控制本地 worktree lifecycle；接收 Worker／Issue Solver 的 local hand-back；push 已提交的 exact branch、建立／更新 PR、維護 PR metadata／readiness；收到 CM terminal receipt 後清理三項 Git 資產 | 修改產品 code、替 Worker commit／解 code conflict、merge／enqueue、代替 CM 決定 merge |
| **Worker** | 接受 User／IM 的直接指派；依 `dispatch_channel` 與派遣者討論，只在指定 local branch/worktree 修改 code／test、驗證、建立 local commit，交回乾淨 exact HEAD | 不使用 GitHub／`gh`；不建立或修改 Issue／PR、不 push、不 review、不 merge／enqueue、不碰其他 worktree |
| **Issue Solver** | 只消除已進入 GitHub Issue 的工作；接受 IM 傳入的 Issue assignment packet，只在指定 local branch/worktree 修改 code／test、驗證、建立 local commit，交回乾淨 exact HEAD | 不使用 GitHub／`gh`；不接手未進 Issue 的直接指派，不 claim／修改 Issue、不建立或修改 PR、不 push、不 review、不 merge／enqueue |
| **CR — Code Reviewer** | 對所有 PR 做獨立的正確性、測試、回歸、架構與安全審查；把結論留在 PR | 管理 Issue；擁有 merge 權限；建立本地 review cycle |
| **DS — Docs Steward** | 對所有 PR 判斷文件 impact；維護 registry、metadata、SoT domain SOP／reference，執行 docs lint | 建立本地工作項目資料庫；複製 PR lifecycle |

Release operator 是 CM 所管理的執行能力，不是另一套產品管理層：它只能依 release SOP 與明確批准執行發布、部署或 rollback。

### Backlog Scout 與 PI 控制職能

Backlog Scout 與 PI 是交付控制迴圈中的職能，不是新的 canonical onboarding identity，也不擁有本地 backlog／PR lifecycle：

- **Backlog Scout** 接收 User 發現或主動觀測缺口；需要排序、追蹤、拆解或未來 fan-out 時，先把需求與 acceptance 固化到 GitHub Issue。Scout 可依 deterministic controller 的 capacity 建議 fan-out：Issue-backed 工作交 Issue Solver；只有已具備 User／IM direct-assignment packet、`dispatch_channel` 與 recipient 的 bounded 工作才交 Worker。聊天只運送 assignment，不是需求或狀態 SoT。
- **PI** 是 IM 承擔的 publication/integration execution 職能。它收到 exact typed hand-back 後立即把 branch／PR 發布到 GitHub，再釋放 local worktree／branch；不等待 CI 才建立 PR，也不把 publication 誤報成 Ready。GitHub remote branch + PR 才是等待 required／advisory outcomes 的 durable queue。
- **Supervisor** 在 dogfood 階段只讀取 delivery facts、容量決策與四個 top-level thread 活動，負責 freeze/ramp 與事故升級；它不成為產品 owner、不接管 worktree，也不替 PI／CM 執行 mutation。穩態成立後可降低監控頻率，但不能移除 deterministic gates。
- Scout fan-out 與 PI publication 都只消費 GitHub、Git、registry 與 typed receipt 的 current facts；controller CLI 不發訊息、不建立 agent chat 狀態，也不另存 Issue／PR／queue lifecycle。

### 嚴格責任邊界

本模型明確分離「本地實作面」與「GitHub 控制面」：

- Worker／Issue Solver 的輸入是 assignment packet，不是 GitHub session。IM 將 Issue URL／acceptance／structured Scope／base SHA 傳入；實作者不需要也不得直接呼叫 GitHub API。
- Worker／Issue Solver 可以在本地建立 commit；這是 code hand-back 的一部分，不是 GitHub 交付。hand-back 必須是乾淨 worktree、local branch、exact HEAD、Scope 與驗證證據。
- Worker direct assignment 必須明確記錄 `dispatch_channel=im|user`：IM 派遣時 Worker 和同一個 IM 討論並 hand-back 給同一個 IM；User 派遣時 Worker 和 User 討論，hand-back 給 User 指定的 IM，未指定時由 Worker 在 hand-back 前選定一個 IM。
- IM 只處理 Issue、Project、worktree ledger 與 Git transport／PR metadata。它可以 push Worker 已存在的 commit、開／更新 PR、觸發 checks，但不能改檔案、staging、commit 內容或解 code conflict。
- CM 只處理交付協調、Ready admission、merge queue／merge 與 main synchronization。任何 code 或 PR metadata 修正都退回 IM／原 Worker，不由 CM 代修。
- CR／DS 各自把 review／docs impact 結論留在 PR；兩者都不修改 caller worktree。

「Ready」分兩層：IM 只能交付一個已存在、非 draft、證據完整的 Ready candidate；CM 必須用當下 live `origin/main`、exact physical HEAD／Scope、required／readiness、typed seal、branch rules 與 durable hold 再驗證後，才可入 queue／merge。CR／DS 仍把結論留在 PR，但 routine／advisory 結論不形成隱性 hard gate；只有被 repository rule 要求或升級成 P0／P1／security hold 才阻擋。

`ops/context_plane.json` 與 `ops/context_route.py` 內部保留執行層 mapping 以維持既有入口相容；這些 key 不屬於 canonical identity、權限或工作狀態，不應出現在 agent-facing onboarding、assignment 或交接語義中。

## 兩條正式工作路徑

### A. 直接指派

適用於 User 或 IM 已經清楚知道要改什麼的明確工作，例如小型修復、界定清楚的重構或直接交辦。它不需要 Issue，也不進入 Issue 排序。

```text
User / IM / Backlog Scout（完整 direct-assignment packet）
    ↓ direct assignment
Worker
    ↓
branch + worktree → code + tests → local commit + typed hand-back
    ↓
PI publish exact commit + PR → release local worktree/branch
    ↓
GitHub durable PR → required + advisory confidence／CR／DS → CM native merge queue → main → release/deploy（若需要）
```

PR 仍必須寫清楚指派內容、修改範圍、驗收方式、測試證據、文件影響與 production／rollback 風險。

直接指派的 hand-back recipient 不由 Worker 自行模糊推定：

- `dispatch_channel=im`：`dispatch_owner` 是討論對象，也是唯一 hand-back recipient；若另給 `handback_target`，必須相同。
- `dispatch_channel=user`：討論對象固定是 User；`handback_target` 可指定 IM，省略時 Worker 必須先選定 IM，才能交回 hand-back。

### B. Issue 流程

適用於需要討論、排序、拆解、Project／milestone 視圖或未來追蹤的工作。

```text
User / Backlog Scout
    ↓
GitHub Issue → Project priority / triage → Scout fan-out
    ↓
Issue Solver claim
    ↓
IM 建立 dedicated worktree → code + tests → local commit + typed hand-back
    ↓
PI publish exact commit + PR → release local worktree/branch
    ↓
GitHub durable PR → required + advisory confidence／CR／DS → CM native merge queue → main → release/deploy（若需要）
```

Issue 的 acceptance 是需求真相；PR 的 diff、conversation、checks、review 與驗證證據是實作真相。Issue 關聯可由 PR 自動 close，但不把 Issue 狀態再寫入 repo。

## PR 收斂規則

Worker 與 Issue Solver 的實作能力、測試要求與 local hand-back 標準相同，差別是 Worker 處理 direct assignment、Issue Solver 只消除 Issue work。PI 由 IM 負責，從 exact hand-back 立即建立或修復同一個 PR，再釋放 local assets；每個 PR 應讓人能回答：

- 這是 direct assignment 還是 Issue work；若有 Issue，關聯哪一張。
- 改了什麼、為什麼改、範圍與非目標是什麼。
- 哪些測試／Actions 實際通過，命令、exit status 與 exact HEAD 是什麼。
- 是否影響文件、資料、CloudKit、migration、release、deploy 或 rollback。
- CR 與 DS 是否完成各自檢查；未完成時不得宣稱「完整 review／docs 結論已綠」，但不因此偽造未配置的 hard gate。

CM 只在 PR 的 typed contract、required checks、branch rules、mergeability 與安全條件滿足後合併；CR／DS 若揭露 P0／P1／security 必須先成為 durable hold，routine advisory 不等待。PR merge 後才進入 release／deploy SOP；任何外部帳號批准、production 寫入或 rollback 仍是獨立的明確動作。

### Hand-back、PR 與 cleanup invariant

- local hand-back 不是完成；PI 必須把它轉成真實 PR，否則該工作只能標記為 `hand-back pending PR`，不可算 Ready 或完成。
- hand-back 必須保留 dispatch provenance 與 recipient：IM dispatch 回同一 IM；User dispatch 回指定 IM 或 Worker 在交接前選定的 IM；沒有 recipient 不得宣稱 hand-back 完成。
- typed `kg.worktree.handback.v1` hand-back 必須在交接當下以 `git ls-remote origin refs/heads/main` 捕獲 `origin_main_sha`；delivery control 只把這個 registry seal 正規化成 `kg.delivery.handback.v1`，並以 machine receipt 嵌入 PR body。seal 同時綁定 lane／owner thread／claim generation／branch／absolute worktree path／base／parent／HEAD／observed origin main／content digest／structured Scope／focused Validation／初始 P0、P1、security holds；owner、delegation 或 Scope 變更會開始新 generation 並使舊 hand-back 失效，任一不一致都 fail closed。Issue 上宣告的 `initial_holds` 必須由同一 owner 在 hand-back 時逐項帶入；PI 不可把未清除的初始 hold 洗掉。
- registry 在 `register`／`scope-set` 的同一個 ledger lock 內，同時檢查 external ID 與 structured Scope；`active`、`cleanup_pending` 與尚未 terminal 的 `published` claim 都持續占有 Scope。一般 register 不可把 published branch／path 當成可覆寫 owner；只有 supported same-owner transaction 能先原子終止舊 generation 再建立新 claim。衝突不得延後到 publish 才發現，也不得以 `compact` 消除：compact 只正規化 record shape，不刪除 `active`／`cleanup_pending`／`published`，也不丟棄已驗證的 terminal proof；`merged`／`abandoned` audit history 保持可追溯。
- local hand-back 的 `origin_main_sha` 是交接時的觀測證據，不是 publication gate 或 current-main Ready 證據。只要 recorded base 同時是 live `origin/main` 與 worktree HEAD 的 ancestor，歷史 base 的 clean committed hand-back 可立即 durable publish；不要求 live `origin/main` 已是 worktree HEAD 的 ancestor。只有 merge-front 才由 CM 以當下 live `origin/main`、exact PR／registry／receipt base、HEAD／Scope 與 required checks 驗證 freshness；`main` 前進後，已發布 PR 留在 GitHub reservoir，輪到 merge-front 時再由同 owner JIT reanchor，舊 receipt 不得直接當成 Ready。
- PI 的 `publish` transaction 先以 exact readback 讓 remote branch + 非 draft PR durable，再以 registry CAS 記錄 PR target 的 `published_base_sha`，最後取得 registry `cleanup_pending` lease；lease 期間同 branch／path 不可重新 claim，local worktree／branch 移除並精確讀回後才完成為 `published`。原始 hand-back 的 `base_sha` 是 immutable provenance，`published_base_sha` 是 GitHub target 的獨立觀測；兩者不可互相覆寫。`published` 只證明 local assets 已可釋放，不複製 GitHub PR 狀態。中斷的 CAS 或 lease 必須由同 receipt／同 PR 重試，PR 等待 CI／review 時只保留 remote branch／PR；需要修改時由 IM 重新開 dedicated worktree。
- publication 後 required 若揭露 code failure，正確的 local resume 不是保留 idle worktree，也不是用一般 register 覆寫 published owner。PI 先以 `resume-published` 對 exact original generation／owner／branch／remote HEAD／Scope 做 CAS；舊 published generation 以 audit evidence terminalize，新 active generation+1 保留原 recorded base，並從 remote PR HEAD 重建 clean worktree。command 不跑測試、不 hand-back、不 push、不 force-push；原 owner 修復後建立 fresh hand-back，PI 只更新既有唯一 PR。stale merge-front 則使用另一個 `reanchor` transaction，把 fresh generation base 對齊 caller 指定且仍為 live 的 `origin/main`；兩者不可混用。
- publication 後若 registry CAS 或 local removal 中斷，已建立的 PR 不回退；同一 typed receipt 以 idempotent retry 收斂。local removal 前、每一項 local／remote asset mutation 前與 terminal disposition 前，都重新讀取 exact PR target／branch／head／body tuple；任何 drift 都保留 `cleanup_pending` 與尚未處理的資產。CM merge 後，IM／PI 再以 exact merged PR receipt 清除 remote branch，並以帶 digest 的 `kg.worktree.terminal-proof.v1`（lane、PR number、MERGED state、target=`main`、branch、head）把 local disposition terminalize 為 `merged`；一般 orchestrator 不能直接宣告 merged。任何 SHA／Scope／path drift 都只阻擋該 lane，不得 bulk sweep 或跨 lane 清理。
- `worktree_orchestrate.py resolve --remove` 是受 CAS 保護的 local terminal cleanup，而不是一般刪除捷徑。它先驗證 exact expected generation／HEAD、target worktree clean、local branch ref 未漂移且 remote branch 不存在；registry transition 成功後，再重讀 remote／local ref，移除 target worktree，並只在 HEAD 仍 exact 且 remote 仍 absent 時刪除該條 local branch。任何 dirty、remote appearance、ref drift、讀取錯誤或 branch mismatch 都 fail-closed 並保留資產；它永遠不刪 remote branch、canonical `main` 或未知 worktree。這形成「registry disposition → worktree removal → local branch removal → exact readback」閉環，而不把 cleanup 完成誤報成只有 worktree 消失。
- 舊版 PR／registry 若沒有 typed receipt，只能走 migration-only 的 terminal cleanup：`cleanup-merged --pr`、`abandon-pr --pr` 與 `cleanup-abandoned --branch` 逐條以唯一 branch／PR、terminal status、exact base／HEAD／Scope、無 dirty／physical collision／remote drift 的 CAS 證據收斂；它們不補寫 receipt、不修 registry、不接管 owner。任何 hold、重複歷史、PR history、head 漂移或無法證明的 branch 都保留並回報 blocker。對已經 abandoned 但仍保留有效 handback 的 ownerless clean branch，先走 owner recovery；確認沒有 owner、PR history、physical worktree 或 ref drift 後，才可由明確 operator 執行 `discard-abandoned-handback`，寫入帶 digest 的 discard proof，再刪除 exact refs。這條路徑不適用於有 owner、dirty、unknown 或 remote-drift 的 branch。
- 每次 merge／queue landing 後，CM 必須 `fetch` 並以安全的 fast-forward 路徑使 local `main` 與 `origin/main` 相同；若 local main dirty、diverged 或 drift，停止後續 admission，不得 force reset 掩蓋問題。

### Required 與 advisory outcomes

`.github/workflows/pr-readiness.yml` 先用 `ops/delivery.py validate-pr-body` 驗證 PR body 只含一份合法 `kg.delivery.handback.v1` machine receipt，並把 receipt 綁到 exact PR HEAD；workflow 不自行重寫另一套 regex schema。`.github/workflows/pr-gate.yml` 的 workflow `pr-gate` 會產生短、可重現的 `required` check run；它只回答這個 PR 是否滿足 repository 基線，不代表所有受影響 domain 都已完整驗證。若 exact published PR 的 required 為 `ABSENT` 或 `FAILURE`，PI 可用 `trigger-required` 重新 dispatch 同一 workflow；command 在 dispatch 前重讀 unique PR mapping、registry receipt、body、paths、base／HEAD 與目前 check status，manual workflow 也必須收到 exact PR number／base／HEAD，checkout 後再次證明 HEAD。`PENDING`／`SUCCESS` 拒絕重複 dispatch；這個修復不清除 hold，也不產生 merge eligibility。

同一 workflow 的 `confidence` check run 是 advisory outcome：它提供完整的**受影響** backend／iOS／UI／ops fan-out，nonblocking 只代表不佔用 native merge queue 的串行 gate，不代表可忽略。慢速 backend／ops／iOS lane 由可測的 changed-path policy 選擇：明確無關才會顯示 `skipped`，未知或改動 routing policy 時 fail-closed 為全跑；被選中的 lane 必須 `success`。

因此固定採以下判讀：

- GitHub 對 exact PR HEAD 列出的所有 required checks 都成功，才是 merge 的最低 Actions 條件；仍須滿足 typed receipt、live base、branch rules 與其他安全條件。CR／DS 的 routine advisory 不等待；其 P0／P1／security 發現必須以 durable hold 呈現。
- `confidence` 失敗、缺失、非預期 `skipped`、取消或未完成時，PR 不得宣稱「完整綠」；也不得進入受影響的 release／deploy 路徑。
- CM 只有在 GitHub 已顯示 exact merged `main` 對每個被選中的慢速 surface 啟動等價驗證時，才可取消已被取代的 PR confidence；取消本身不是 PASS，完整結論以該 `main` run 的 terminal 結果為準。
- confidence 結果是 GitHub check run 的證據，不在 repo 內另建本地 confidence／merge 狀態；若要重跑，針對同一 PR HEAD 或 exact `main` 重新觸發 Actions。

### GitHub durable queue 與 CM landing

PI publication 後，remote branch + typed PR 是 durable PR reservoir；local worktree 不是等待區。publication 明確建立 target branch=`main`，並在 preflight 與 final readback 拒絕 retarget race；歷史 base 可以先 durable publish，但不能直接 Ready。canonical body 除 Scope／Validation／receipt 外，也固定產生 Impact 與 `kg.delivery.holds.v1`；`delivery-hold:p0`／`delivery-hold:p1`／`delivery-hold:security` labels、typed holds 與 legacy `PUBLISH ONLY` 取聯集，PI 更新 tuple 不得把 hold 洗掉。`base_sha` 保留 hand-back provenance；GitHub PR target 另存為 `published_base_sha`，若 publication 與 registry CAS 分離失敗，`record-published-base --pr` 只能在 exact PR／registry／body／Scope／head readback 後重試，不能覆寫 hand-back base。若 human-readable metadata 漂移但 typed receipt 仍可解析，PI 可在 exact published registry／HEAD／Scope readback 後 body-only 修復同一 PR，不重建 worktree。CM 只把符合以下 exact tuple 的 candidate 送進 GitHub native merge queue：registry `published` receipt、PR body／changed paths／head、live `origin/main` 與 PR／receipt／registry base、GitHub required outcomes、mergeability，以及沒有 P0／P1／security hold。repository 沒有 native merge queue rule 時必須拒絕，不得改成本地 queue 或手動 merge。

native merge queue 以 exact current base、exact head、canonical typed body 與 target branch=`main` admission；adapter 只呼叫 GraphQL `enqueuePullRequest(expectedHeadOid)`，不使用可能直接合併的 auto-merge CLI。inventory 直接觀測 GraphQL `mergeQueueEntry` 並把已入列 PR 分成 `pr_queued`；admission 後 `main` tip 前進不是 receipt failure，merge queue 會建立新 merge group 並重跑獨立、短且 blocking 的 `required`。若 PR 被 retarget 或 head／body 改變，只有 queue entry ID 仍是本次 transaction 建立的 entry 才能 `dequeuePullRequest`，replacement entry 必須保留並 fail closed。landing 後 CM 只在 canonical checkout clean、位於 `main` 且 local／origin refs 仍符合 preflight 時做 `--ff-only` sync；任何 race、dirty 或 divergence 都 fail closed。

## Deterministic feedback controller

四個 top-level tasks 的首次上線、canary promotion、freeze／rollback 與完成條件依 [`docs/sop/delivery_control_dogfood.md`](../sop/delivery_control_dogfood.md)；正式 tasks 只能在 deterministic `dogfood-preflight` 通過後建立。

`ops/delivery.py` 是一次一個 command 的 deterministic control surface，不是 daemon、agent dispatcher 或狀態庫。`inspect` 從 registry、physical worktrees、GitHub PR／required checks 與 caller 提供的 owner runtime facts 分類每條 lane；`metrics` 只量測 reservoirs；`plan` 只回傳同一組 facts 推導的 capacity actions。完整 inventory 仍呈現所有 malformed source；raw registry 非 object、無效 external ID 與未知 status 都進入 `source_problems`，不會被 normalization 靜默丟棄。publication 的 collision projection 只解析 active／cleanup Scope，cleanup 則只解析 receipt 指定的 exact claim，因此無關 terminal legacy 問題不會封鎖獨立 transaction，目標 claim／Scope 不可解析仍 fail closed。`source_problems` aggregate 仍讓 readiness 與 audit 保持 fail-closed；metrics 另外輸出 `source_problem_scope_counts` 與 `actionable_global_source_problems`。global source uncertainty、unmapped PR、duplicate PR mapping 或未完成的 `cleanup_pending` lease 都把 `desired_new_solvers` 固定為 0，先建議 inspect／bounded recovery；branch-scoped registry residue 與 `git_objects` observation 只阻止受影響的 branch/object cleanup，不能封鎖 exact、無 collision 的其他候選 dispatch。cleanup lease 已有 durable PR，仍計入供給，但不能再生新 solver。一條 lane 的 collision、dirty、owner loss、stale tuple 或 required failure 不授權修改其他 lane。

Watchdog 的 read／claim 邊界也是控制面契約：`watchdog` 只做唯讀決策；外部 scheduler 必須呼叫 `watchdog-claim`，由 runtime receipt 的 cycle／last-action CAS 在 dispatch 前保留唯一 wake。只有 `wake_claimed=true` 的 `wake` 可以建立一次 Supervisor turn；CLI 另外以 `verdict=wake-authorized`／exit 0 明確標示唯一 dispatch 授權，`verdict=no-wake`／exit 2 即使 `ok=true` 仍只是觀測結果，不得被 shell caller 當成成功 dispatch。`noop`、`escalate` 或 claim conflict 都不得建立 session。這個 claim 不代表 thread 一定可喚醒，也不取代 scheduler 對真實 thread state、freeze／archive 與 receipt freshness 的查詢；它只消除同一 stale receipt 被兩個 scheduler 同時消費的 race。

Issue intake 與 candidate reservoir 是兩個不同的觀測層。`issue-inventory` 先以 `kg.delivery.issue-inventory.v1` 完整分頁讀取所有 open Issues；raw total 永遠包含 quarantine、legacy、malformed、blocked、owner-bound 與已發布／終止歷史，不能用 candidate label 查詢代替。每個可解析 Issue 僅能有一個 deterministic disposition：`source_problem` → `security_hold` → `owner_bound` → `published_pr` → `terminal_history` → `dispatchable_candidate` → `blocked` → `legacy_unmapped` → `triage_required`。Issue body SHA-256、updatedAt、registry mapping、命中的 PR numbers 與原因都隨 inventory 輸出；API 缺欄位或分頁不完整也會保留 raw count 並產生 source problem。

現有 `candidate_issues` 語義保持不變：它只是 raw inventory 投影出的、具 exact `delivery:candidate` label 與一份合法 `kg.delivery.candidate.v1` body、且沒有 nonterminal owner／Scope mapping 的可派工子集。candidate contract 的 Severity、Priority、structured Scope、Acceptance 與初始 P0／P1／security holds 必須全部可驗證；label-only、body-only、malformed 或帶安全 hold 的 Issue 都不會進 dispatchable reservoir。controller 不保存本地 backlog 或 Issue lifecycle，GitHub raw inventory 才是完整需求觀測。

逐條處理使用唯讀 `./ops/delivery.py issue-inventory` 與 `./ops/delivery.py triage-plan`。`triage-plan` 先列 source／security，再列 triage、可派工 candidate、owner／PR recovery、legacy、blocked 與 terminal evidence；raw backlog 存在時 plan 必須輸出 `triage_existing_issues`，但不阻止已驗證 candidate 的獨立 dispatch。只有 raw inventory 完成分流後、candidate reservoir 低於 20，才輸出 `replenish_candidates`。Supervisor 因此必須分開回報 `raw_open_issues`、`dispatchable_candidate_issues`、`unadmitted_open_issues`、`triage_required_issues`、`legacy_open_issues`、`issues_with_active_claim`、`issues_with_published_pr`、`issue_source_problems`、`source_problem_scope_counts`、`actionable_global_source_problems`、`recoverable_quarantine`、`backlog_drained`、`pipeline_ready` 與 `ramp_ready`，不能再以「candidate=0」宣稱沒有工作。

准入只允許一次一張 Issue：`./ops/delivery.py admit-candidate --issue <number> --expected-updated-at <iso> --expected-body-sha256 <sha> --payload-file <candidate.json> --triage-reason <reason> --operator <identity>`。command 會在 mutation 前重讀 Issue／label／registry／PR，驗證 fingerprint、Scope collision、owner mapping 與 hold，再保留原 body、追加唯一 typed block、寫 body、exact readback，最後寫入 `delivery:candidate` label 並再讀回 body／label／contract。這是 application-level read-before/readback，不是假裝 GitHub 提供原子 CAS；任何 drift、label 不存在或 readback mismatch 都停止且不自動 retry／overwrite。Stage 1 的 label／branch-rule／native-queue 設定與單 Issue admission 分離，禁止批量把 raw Issues 改成 candidate。

`metrics.reanchor_required` 只計現有 `LaneState.REANCHOR`，大於 0 時另輸出 `reanchor_front`；controller 不在此重新解釋 REANCHOR 分類語義。`active_development` 只代表已投影且可驗證的開發 lane；為避免把 registry residue 誤報成「沒有進行中工作」，metrics 另外輸出 `active_registry_records`、`raw_active_registry_records`、`active_registry_without_worktree`、`active_registry_without_worktree_owner_bound`、`active_registry_without_worktree_ownerless`、`active_registry_without_worktree_owner_reachable`、`active_registry_without_worktree_owner_unreachable` 與 `malformed_active_registry_records`。其中 `active_registry_records` 只計可解析 claim，`raw_active_registry_records` 包含 malformed active record；沒有可驗證 path 的 malformed record 不會被推斷為「沒有 worktree」。只有 owner-bound 且 runtime status 可達的 split 才能輸出 `recover_owner_bound_lane`，要求原 owner 走 supported lifecycle 恢復；owner-bound 但 archived／notLoaded／unknown／其他不可達 status 只輸出 `audit_unreachable_owner_lanes`，禁止 wake、建立 session／worktree、takeover 或 cleanup；ownerless split 只輸出 `audit_ownerless_lanes`，同樣是 ownership audit signal。直接建構的舊版 metrics 若沒有 reachability split，保留原 aggregate 語義以維持相容；實際 inventory 一律以 runtime readback fail-closed。這些數字是待 owner／registry lifecycle reconciliation 的觀測數，不會被當成 Solver capacity 或授權清理。

每份 metrics snapshot 同時回傳 `live_main_sha` 與 `local_main_sha`，把決策綁定到同一次 inventory 的 `origin/main`／本地 main 讀取；任一值為 null 代表該來源讀取缺失，不能被解讀成「基線未變」或安全同步。metrics 的基線欄位與 `inspect`、`branch-review-plan`、dogfood readiness 使用同一份 inventory 觀測，不另造第二個 SHA 來源。

Branch refs 也是交付資產，但不等於 worktree 或 Solver WIP。metrics 另外投影 `branch_audit_items`、`local_orphan_branches`、`remote_orphan_branches`、`merged_branch_cleanup_ready` 與 `remote_drift_branches`；只要存在需要 reconciliation 的 branch asset，plan 就輸出 `audit_branch_lifecycle`。這個 action 只要求執行唯讀 `branch-audit`／分頁 `branch-review-plan`，不授權刪 branch、cleanup、建立 session 或接管 owner。只有 branch-audit 的 exact CAS preflight 或原 owner supported lifecycle 後續證明，才可進入相應 terminal／publish 路徑。

Capacity action 也嚴格區分「有工作可執行」與「歷史 SLO／quarantine 需要觀測」：`publish_handbacks` 只在 `handbacks_publishable > 0` 時出現；即使歷史 handback→PR p95 超過 60 秒，也只輸出 `audit_transport_slo`，不把不存在的 handback 偽裝成 PI 派工。`recoverable_quarantine > 0` 時輸出 `audit_quarantine`，讓被隔離的 source／lane／PR／terminal residue 有明確的 owner／terminal-evidence reconciliation signal；它不代表可 dispatch、cleanup、建立 session 或重試 mutation。近期 merge 數高於 `merge_to_sync_samples` 時輸出 `audit_sync_telemetry`，要求核對 CM 的 supported main-sync receipt；它是同步閉環的觀測缺口，不是自行執行 sync、建立 session 或重試 mutation 的授權。Dogfood preflight 同時把這個缺口列為 warning，但不把 observation 變成 blocker；只有實際的 main、PR、hold 或來源安全條件才阻止 readiness。`repair_required` 只代表實際 required failure／absence，`enqueue_green` 只代表現有 required-green reservoir；對應的 CI-start／queue-admission latency 超標分別輸出 `audit_ci_start_slo`／`audit_queue_admission_slo`。`recover_merge_cadence` 也只有在 open PR、handback、active development、required-green 或 native queue 供給存在時才出現；只有 cadence SLO 失守而沒有任何可恢復供給時，輸出 `audit_merge_cadence`。所有 observation action 都是告警／調查信號，不是建立 session、建立 worktree 或重試 mutation 的授權。

`branch-audit` 除了盤點 local／remote branch refs，也會以唯讀、最多 30 秒的 `git fsck --unreachable --no-reflogs` 觀測失去 ref 的 commit object。這些 object 只進入 `unreachable_commit_count`／sample quarantine，不會被自動恢復成 branch、推成 PR 或刪除；若 fsck timeout、invalid ref 或出現其他診斷，會以 `complete=false` 保留 machine-readable `source_problems`，並阻止所有受影響的清理判定，而不讓 supervisor heartbeat 無限等待。這讓「branch 已被刪除但 commit 尚未落 main」不再靜默消失，同時不把 Git garbage candidates 誤算成 active Solver。對多個 local orphan branch，orphan preflight 會先建立一個穩定的 canonical／registry／worktree／branch ref snapshot，再逐枝執行必要的 ancestor 檢查；這只消除重複 I/O，不降低任何 owner、PR history、remote ref、physical worktree、ancestor 或 source-problem gate。

若 branch ref 已消失但仍有具體 commit SHA，使用唯讀 `./ops/delivery.py unreachable-commit-inspect --commit <sha> --max-paths <n>` 取得 `kg.delivery.unreachable-commit.v1`。它先確認 SHA 出現在目前 `fsck` observation，再讀 parent、subject、bounded changed paths 與 path fingerprint；結果的 disposition 只能是保留待 owner／Issue／PR 關聯，或在 source problem／非 unreachable 時 fail closed。即使 fsck 有 malformed ref 等 `git_objects` source problem，只要目標 SHA 已被 stdout observation 看見，工具也會輸出 `complete=false` 的內容證據與 `source_problem_scope=git_objects`；這些證據不可建立 branch、PR、owner claim 或刪除 object，必須先修復 source problem 或完成原 owner lifecycle。

對於沒有 worktree、remote ref、PR history 或 registry claim，但仍含有未落地 commit 的 local orphan，`branch-audit` 不得直接刪除，也不能只回報一個無法行動的 blocker。每個 blocked local orphan 都提供唯讀 `review_command`，可執行 `./ops/delivery.py branch-inspect --branch <branch> --expected-head-sha <sha>`，取得 live main／branch HEAD、ahead／behind commit 數、最多 200 個排序後變更路徑、bounded commit subjects 與 change fingerprint；`changed_path_count` 與 `changed_paths_truncated` 明確表示是否還有未列出的路徑，而 fingerprint 仍涵蓋完整 raw diff。這份 `kg.delivery.branch-content.v1` 只是內容審查證據，不是 owner、Issue、PR 或 hand-back claim；審查後若要發布，仍回到原 owner／Scope lifecycle。若明確判定該 unlanded local-only branch 應丟棄，才可使用 `discard-unregistered-branch`，並同時通過 registry／PR／remote／physical／HEAD／content fingerprint 的雙重 CAS readback 與 `--confirm-unmerged` operator 確認；任何 source problem、owner evidence、remote drift 或物理 worktree 都會 fail closed。這使「發布、保留、明確丟棄」三條路徑都有 machine-readable terminal disposition，不把未落地 commit 靜默當成可刪垃圾。

當 local orphan 數量較多時，使用唯讀 `./ops/delivery.py branch-review-plan --offset <n> --limit <m>` 分頁取得 `kg.delivery.branch-content-review-plan.v1`。它只選取 branch-audit 已經證明是 local orphan、且沒有 worktree／remote／PR／registry owner claim 的項目，並且只把「tip 不是 live main ancestor」這個內容審查 blocker 送進 review plan；remote ref、PR history、registry claim、physical worktree 或 source problem 都留在 branch-audit／原 owner lifecycle，不會被誤送進 orphan content queue。再逐頁取得內容 fingerprint、ahead／behind、bounded paths 與 commit subjects；每個 review item 最多輸出 20 條排序後的 path sample，但 `changed_path_count`、`changed_paths_truncated` 與 fingerprint 仍保留完整 diff 證據，需看更多路徑時改用單一 branch 的 `branch-inspect`。`remaining_count=0` 只表示從該 offset 起沒有下一頁，不能單獨表示全局 review 完成。新增的 `reviewable_complete` 只有在 `offset=0`、整個 reviewable queue 可由這次回應耗盡、且當頁內容證據完整時才為 true；若從後續 offset 讀取最後一頁，它仍為 false，避免把未被本次命令證明的前頁當成已審查。`complete` 仍 additionally 要求 `audit_complete=true`，因為 remote／owner／registry／source blocker 被刻意排除在 review queue 外。它不會 publish、discard、建立 owner 或修改 registry；每個 review item 仍必須回到原 owner publish，或由 operator 以單一 branch 的 fingerprint＋雙重 CAS 明確丟棄。

預設 feedback policy 的健康吞吐目標是每小時 12 merges，且有健康供給時最長 300 秒至少 landing 一個；這是 capacity SLO，不是繞過 required 或 P0／P1／security hold 的時限。merge cadence 同時輸出最近一小時 count／rate、相鄰 landing 間隔 p50／p95 與距最後一次 landing 秒數。durable open PR floor／ceiling 是 10／15、active Solver target／ceiling 是 8／12、merge-ready／native-queue target 至少 3、required p95 上限是 240 秒、每 cycle 最多建議 4 個新 solver。只要 CI／PR／cleanup／source facts 健康且 durable PR 未達 ceiling，controller 即使在 cadence 尚健康時也把 active Solver 補到 8；到 12 或 PR ceiling 才 throttle。active Solver 是領先供給 reservoir，若等 cadence 變慢才補貨，實作 lead time 會造成可預測的斷料鋸齒。這個獨立 Solver band 是 Little's Law 所需的生產能力，不能用「PR + active 合計已到 10」取代，否則 reservoir 消耗後會斷料。controller 會平行建議 drain publishable hand-backs、local release、required-green enqueue、PR contract repair、required trigger／repair、terminal cleanup 與 bounded blocker recovery。`metrics` 從 registry、PR、exact required checks、native merge queue entry 與 append-only duration telemetry 量測最近一小時 hand-back→PR、PR→required-start、required duration、required-success→enqueue、merge→main sync、merge→terminal cleanup 的 sample count／p95，並回傳 required-running／absent、native queue depth、collision pressure、required failure rate、PR-contract failure 與 idle worktree。canary 的 collision pressure 定義為目前 live lanes 中 collision-blocked 的比例；高於 20% 時輸出 `improve_scope_partition` 並停止新 solver birth，等 dogfood 累積 admission event 後再升級為時間窗 collision rate。telemetry 只保存 operation duration evidence，不複製 Issue／PR／registry lifecycle；寫入失敗只能成為 machine-readable warning，不得回滾或阻擋已完成的 delivery mutation。JIT reanchor 的 hand-back timestamp 晚於既有 PR `created_at` 時改讀該 generation 的 publication journal，不把舊 PR 建立時間當負延遲；其他無法由同一 generation／HEAD 解釋的跨來源時間倒流才算 source problem。feedback policy 對前三段 transport／CI-start／admission latency分別採 60／60／30 秒 p95 SLA 並回傳對應 PI／CI／CM action；`plan` 直接用 observed required-duration p95，超過 240 秒即 throttle solver birth，不再依賴 caller 手動注入。

## 本機 coordinator 的窄責任

本機 coordinator 是多 worktree 的執行環境安全工具，不是產品管理系統。`ops/worktree_registry.py` 是相容 command facade；admission、records、handback、lifecycle、storage 與 parser 各自由 `ops/worktree_registry_core/` 的小模組維護，避免把 Git、ledger policy、schema validation 與 CLI parsing 混成單檔。IM 使用它控制 worktree lifecycle；Worker／Issue Solver 只在已指定的 path 內實作：

- 保留 worktree owner、branch/path、structured Scope、檔案 overlap、thread identity。
- 保留本地測試、exact HEAD、log／artifact 與 typed hand-back evidence。
- 幫助 IM／PI 建立、接管、驗證、交回、在 durable PR publication 後釋放 local assets，或在 exact terminal receipt 後安全清理。

它不負責：

- 建立、排序、認領或關閉 GitHub Issue／Project。
- 管理 PR lifecycle、review cycle、merge queue 或 merge permission；registry 的 `published`／`merged` 只是不允許模糊重用的 local disposition。
- 建立本地 backlog、Ticket Factory、Issue lifecycle、Project／board 或批次整合狀態。
- 把 worktree 或 agent 當成產品工作項目。
- 取代 GitHub Actions、CM merge、release、deploy、production approval 或 rollback。

Scope 只回答「本機哪個工作樹可改哪些檔案」；Issue acceptance、PR review 與 production approval 各自留在 GitHub 或 domain SOP。local hand-back 是交給 IM 的執行證據，不是第二個交付狀態機，也不等於 PR 已建立。

有效的 typed hand-back 只會釋放它所 seal 的那一個 idle claim 的本機 admission claim：branch/path 必須仍指向乾淨且與 sealed HEAD 相同的 worktree。重新 register、adopt 或 reuse active branch/path 會開始新的 claim，並使先前 receipt 的 admission release 失效；舊 receipt/seal 仍保留作 audit evidence。新的 claim 只有在 fresh hand-back 後才能再次釋放本機 admission，且這不改變 GitHub Issue、PR 或 merge 的狀態。

長任務的本機安全帳本另由 `ops/task_registry.py` 與 `ops/lib/streaming_command.py` 負責。它只記錄 process identity、process group、heartbeat、log path 與 terminal outcome，用來避免誤殺或靜默等待本機程序；它不是 Issue、Project、PR、backlog 或任何產品工作項目的狀態。

branch-audit 的 branch-scoped source problem 會同步投影到該 branch action 的 `source_incomplete` 分類與 blocker；這只改善觀測與下一步提示，不放寬任何 cleanup gate。

`branch-audit` 的每個 `source_problem_action` 另外標示 `actionability`：`blocking` 代表目前仍觀測到相符的 local／remote ref、physical worktree 或 PR，必須先走原 owner／source lifecycle；`quarantined_history` 代表只剩無現存交付資產的 malformed registry history。後者仍保留在完整 audit、並使整體 audit 保持 incomplete，但不應被計成 live WIP、wake、cleanup 或其他 mutation 授權；報告頂層的 `actionable_source_problems` 與 `quarantined_source_problems` 必須能加總回 source-problem action 數量。

## 遷移後的判斷準則

保留真正產品程式碼與測試、backend／iOS 測試入口、GitHub Actions、PR template／required checks、deployment safety wrapper、生產批准／health gate／rollback、CloudKit／資料庫／域名／App Store／TestFlight SOP、docs registry／impact／lint、薄型本地 coordinator，以及長任務 process-safety ledger。凡是只為模擬 GitHub Issue、Project、PR、review、merge 或狀態追蹤而存在的本地描述、資料庫、看板與流程，都不屬於這個模型。
