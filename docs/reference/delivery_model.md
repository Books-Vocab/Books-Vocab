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
verified_against: 2a7930c04f661c266ce05b3568f375e1db2a39f1
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
branch → commit → PR → Actions + CR + DS → CM merge → main → release/deploy（若有明確意圖）
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
- Scout fan-out 與 PI publication 都只消費 GitHub、Git、registry 與 typed receipt 的 current facts；controller CLI 不發訊息、不建立 agent chat 狀態，也不另存 Issue／PR／queue lifecycle。

### 嚴格責任邊界

本模型明確分離「本地實作面」與「GitHub 控制面」：

- Worker／Issue Solver 的輸入是 assignment packet，不是 GitHub session。IM 將 Issue URL／acceptance／structured Scope／base SHA 傳入；實作者不需要也不得直接呼叫 GitHub API。
- Worker／Issue Solver 可以在本地建立 commit；這是 code hand-back 的一部分，不是 GitHub 交付。hand-back 必須是乾淨 worktree、local branch、exact HEAD、Scope 與驗證證據。
- Worker direct assignment 必須明確記錄 `dispatch_channel=im|user`：IM 派遣時 Worker 和同一個 IM 討論並 hand-back 給同一個 IM；User 派遣時 Worker 和 User 討論，hand-back 給 User 指定的 IM，未指定時由 Worker 在 hand-back 前選定一個 IM。
- IM 只處理 Issue、Project、worktree ledger 與 Git transport／PR metadata。它可以 push Worker 已存在的 commit、開／更新 PR、觸發 checks，但不能改檔案、staging、commit 內容或解 code conflict。
- CM 只處理交付協調、Ready admission、merge queue／merge 與 main synchronization。任何 code 或 PR metadata 修正都退回 IM／原 Worker，不由 CM 代修。
- CR／DS 各自把 review／docs impact 結論留在 PR；兩者都不修改 caller worktree。

「Ready」分兩層：IM 只能交付一個已存在、非 draft、證據完整的 Ready candidate；CM 必須用當下 live `origin/main`、exact physical HEAD／Scope、required／readiness、typed seal、CR／DS 再驗證後，才可入 queue／merge。

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
GitHub durable PR → required + advisory outcomes → CR + DS → CM native merge queue → main → release/deploy（若需要）
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
GitHub durable PR → required + advisory outcomes → CR + DS → CM native merge queue → main → release/deploy（若需要）
```

Issue 的 acceptance 是需求真相；PR 的 diff、conversation、checks、review 與驗證證據是實作真相。Issue 關聯可由 PR 自動 close，但不把 Issue 狀態再寫入 repo。

## PR 收斂規則

Worker 與 Issue Solver 的實作能力、測試要求與 local hand-back 標準相同，差別是 Worker 處理 direct assignment、Issue Solver 只消除 Issue work。PI 由 IM 負責，從 exact hand-back 立即建立或修復同一個 PR，再釋放 local assets；每個 PR 應讓人能回答：

- 這是 direct assignment 還是 Issue work；若有 Issue，關聯哪一張。
- 改了什麼、為什麼改、範圍與非目標是什麼。
- 哪些測試／Actions 實際通過，命令、exit status 與 exact HEAD 是什麼。
- 是否影響文件、資料、CloudKit、migration、release、deploy 或 rollback。
- CR 與 DS 是否完成各自檢查；未完成時不得宣稱 ready。

CM 只在 PR 的 required checks、review、文件影響與安全條件滿足後合併。PR merge 後才進入 release／deploy SOP；任何外部帳號批准、production 寫入或 rollback 仍是獨立的明確動作。

### Hand-back、PR 與 cleanup invariant

- local hand-back 不是完成；PI 必須把它轉成真實 PR，否則該工作只能標記為 `hand-back pending PR`，不可算 Ready 或完成。
- hand-back 必須保留 dispatch provenance 與 recipient：IM dispatch 回同一 IM；User dispatch 回指定 IM 或 Worker 在交接前選定的 IM；沒有 recipient 不得宣稱 hand-back 完成。
- typed `kg.worktree.handback.v1` hand-back 必須在交接當下以 `git ls-remote origin refs/heads/main` 捕獲 `origin_main_sha`；delivery control 只把這個 registry seal 正規化成 `kg.delivery.handback.v1`，並以 machine receipt 嵌入 PR body。lane／owner thread／claim generation／branch／absolute worktree path／base／parent／HEAD／observed origin main／content digest／structured Scope 任一不一致都 fail closed。
- local hand-back 的 `origin_main_sha` 是交接時的執行證據，不是 current-main Ready 證據；IM／CM 仍須以當下 live `origin/main`、exact physical HEAD／Scope 與 PR checks 重新驗證。`main` 前進後，舊 receipt 必須重新驗證，不得直接當成 Ready。
- PI 的 `publish` transaction 先以 exact readback 讓 remote branch + 非 draft PR durable，再取得 registry `cleanup_pending` lease；lease 期間同 branch／path 不可重新 claim，local worktree／branch 移除並精確讀回後才完成為 `published`。`published` 只證明 local assets 已可釋放，不複製 GitHub PR 狀態。中斷的 lease 必須由同 receipt 重試，PR 等待 CI／review 時只保留 remote branch／PR；需要修改時由 IM 重新開 dedicated worktree。
- publication 後若 registry CAS 或 local removal 中斷，已建立的 PR 不回退；同一 typed receipt 以 idempotent retry 收斂。CM merge 後，IM／PI 再以 exact merged PR receipt 清除 remote branch，並把 local disposition terminalize 為 `merged`；任何 SHA／Scope／path drift 都只阻擋該 lane，不得 bulk sweep 或跨 lane 清理。
- 每次 merge／queue landing 後，CM 必須 `fetch` 並以安全的 fast-forward 路徑使 local `main` 與 `origin/main` 相同；若 local main dirty、diverged 或 drift，停止後續 admission，不得 force reset 掩蓋問題。

### Required 與 advisory outcomes

`.github/workflows/pr-readiness.yml` 先用 `ops/delivery.py validate-pr-body` 驗證 PR body 只含一份合法 `kg.delivery.handback.v1` machine receipt，並把 receipt 綁到 exact PR HEAD；workflow 不自行重寫另一套 regex schema。`.github/workflows/pr-gate.yml` 的 workflow `pr-gate` 會產生短、可重現的 `required` check run；它只回答這個 PR 是否滿足 repository 基線，不代表所有受影響 domain 都已完整驗證。

同一 workflow 的 `confidence` check run 是 advisory outcome：它提供完整的**受影響** backend／iOS／UI／ops fan-out，nonblocking 只代表不佔用 native merge queue 的串行 gate，不代表可忽略。慢速 backend／ops／iOS lane 由可測的 changed-path policy 選擇：明確無關才會顯示 `skipped`，未知或改動 routing policy 時 fail-closed 為全跑；被選中的 lane 必須 `success`。

因此固定採以下判讀：

- GitHub 對 exact PR HEAD 列出的所有 required checks 都成功，才是 merge 的最低 Actions 條件；仍須滿足 typed receipt、live base、CR、DS、branch rules 與其他安全條件。
- `confidence` 失敗、缺失、非預期 `skipped`、取消或未完成時，PR 不得宣稱「完整綠」；也不得進入受影響的 release／deploy 路徑。
- CM 只有在 GitHub 已顯示 exact merged `main` 對每個被選中的慢速 surface 啟動等價驗證時，才可取消已被取代的 PR confidence；取消本身不是 PASS，完整結論以該 `main` run 的 terminal 結果為準。
- confidence 結果是 GitHub check run 的證據，不在 repo 內另建本地 confidence／merge 狀態；若要重跑，針對同一 PR HEAD 或 exact `main` 重新觸發 Actions。

### GitHub durable queue 與 CM landing

PI publication 後，remote branch + typed PR 是 durable PR reservoir；local worktree 不是等待區。CM 只把符合以下 exact tuple 的 candidate 送進 GitHub native merge queue：registry `published` receipt、PR body／changed paths／head、live `origin/main` 與 PR／receipt／registry base、GitHub required outcomes、mergeability，以及沒有 P0／P1／security hold。repository 沒有 native merge queue rule 時必須拒絕，不得改成本地 queue 或手動 merge。

native merge queue 以 exact current base、exact head 與 target branch=`main` admission；adapter 只呼叫 GraphQL `enqueuePullRequest(expectedHeadOid)`，不使用可能直接合併的 auto-merge CLI。admission 後 `main` tip 前進不是失敗，merge queue 會建立新 merge group 並重跑獨立、短且 blocking 的 `required`；若 PR 被 retarget 或 head 改變，adapter 必須以 `dequeuePullRequest` 撤銷仍存在的 native queue entry 並 fail closed。landing 後 CM 只在 canonical checkout clean、位於 `main` 且 local／origin refs 仍符合 preflight 時做 `--ff-only` sync；任何 race、dirty 或 divergence 都 fail closed。

## Deterministic feedback controller

`ops/delivery.py` 是一次一個 command 的 deterministic control surface，不是 daemon、agent dispatcher 或狀態庫。`inspect` 從 registry、physical worktrees、GitHub PR／required checks 與 caller 提供的 owner runtime facts 分類每條 lane；`metrics` 只量測 reservoirs；`plan` 只回傳同一組 facts 推導的 capacity actions。source malformed／unreachable 時保留 lane problem 或 source problem，不捏造供給；任何 `source_problems` 都把 `desired_new_solvers` 固定為 0，先建議 inspect／bounded recovery。一條 lane 的 collision、dirty、owner loss、duplicate PR、stale tuple 或 required failure 不授權修改其他 lane。

預設 feedback policy 的健康吞吐目標是每小時 12 merges，且有健康供給時最長 300 秒至少 landing 一個；這是 capacity SLO，不是繞過 required／review 的時限。projected supply floor 是 10（owner-mapped open PR + publishable hand-back + active development）、open PR ceiling 是 15、required-green target 是 3、required p95 上限是 240 秒、每 cycle 最多建議 4 個新 solver。controller 會平行建議 drain publishable hand-backs、local release、required-green enqueue、required repair、terminal cleanup 與 bounded blocker recovery；只有在未飽和、projected supply 不足且 cadence 慢時，才建議 Scout fan-out 新 solver。`min_required_green` 是可觀測 policy target；目前 solver birth 的數量由 projected supply gap 計算，不會單獨因 required-green 低於 3 增生。CLI `plan` 目前也未注入 required p95 observation，因此 p95 threshold 本身不會觸發 throttle；實際自動 saturation guard 是 owner-mapped open PR 達 15。

## 本機 coordinator 的窄責任

本機 coordinator 是多 worktree 的執行環境安全工具，不是產品管理系統。IM 使用它控制 worktree lifecycle；Worker／Issue Solver 只在已指定的 path 內實作：

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

## 遷移後的判斷準則

保留真正產品程式碼與測試、backend／iOS 測試入口、GitHub Actions、PR template／required checks、deployment safety wrapper、生產批准／health gate／rollback、CloudKit／資料庫／域名／App Store／TestFlight SOP、docs registry／impact／lint、薄型本地 coordinator，以及長任務 process-safety ledger。凡是只為模擬 GitHub Issue、Project、PR、review、merge 或狀態追蹤而存在的本地描述、資料庫、看板與流程，都不屬於這個模型。
