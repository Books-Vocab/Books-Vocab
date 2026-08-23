<!-- doc-meta
tier: runbook
authority: derived
update_trigger: workflow-change
scope:
  - .github/
  - ops/delivery.py
  - ops/delivery_control/
  - ops/worktree_registry.py
  - ops/worktree_orchestrate.py
  - ops/devops_kg_safe.sh
  - ops/release.sh
verified_against: afe016c4ea2fcbd7306f9c4f40b4556e77865100
-->
# KG Change Runbook

角色、入口與 PR 收斂規則以 [`docs/reference/delivery_model.md`](../reference/delivery_model.md) 為準。本 runbook 只描述執行順序與本機邊界。

## Entry paths

### Direct assignment → Worker

適用於 User 或 IM 已經給出明確目標、範圍與驗收的工作；不需要先建立 Issue。

1. Worker 確認 assignment、`dispatch_channel=im|user`、branch、worktree 與 structured Scope；IM channel 另確認 `dispatch_owner`，User channel 可帶 `handback_target`。Backlog Scout 只有在持有這份完整 direct-assignment packet 時才能 fan-out Worker。
2. 在 branch/worktree 以 TDD 實作與測試，commit 保持小而可 review。
3. 依 channel 和對象討論：IM channel 和派遣 IM 討論並 hand-back 給同一 IM；User channel 和 User 討論，hand-back 給指定 IM，未指定則先選定一個 IM。
4. 建立 local commit 與 typed hand-back；Worker 不開 PR、不 push。PI 收到 hand-back 後立即以 exact HEAD 建立 durable PR，再釋放 local worktree／branch。

### GitHub Issue → Issue Solver

適用於需要排序、Project／milestone、討論、拆解或長期追蹤的工作。

1. User／Backlog Scout 把需要排序、追蹤或 fan-out 的發現寫成 GitHub Issue；IM 在 Issue 補齊背景、影響、acceptance、非目標與必要 domain context。
2. IM／Scout 依 GitHub Project／triage 與 `delivery.py plan` 的 capacity 建議 fan-out；Issue Solver claim 後確認 branch、worktree 與 structured Scope。`plan` 不會自行 dispatch agent。
3. Issue Solver 依 Issue 實作與測試，commit 保持小而可 review，建立 typed hand-back 給派遣的 IM；PI 立即發布 exact PR 並關聯 Issue，再釋放 local assets。

## Common PR convergence

1. Worker 與 Issue Solver 都把所有 code change 收進同一個 PR 流程：`branch → local commit → typed hand-back → PI publish + local release → durable GitHub PR`；Worker 的 direct assignment packet 必須留下 dispatch provenance 與 hand-back recipient。
2. PR 描述變更、測試命令與 exit status、風險、文件影響、rollback 方式，並標明 direct assignment 或關聯 Issue。
3. `pr-readiness` 先用 typed machine receipt 驗證 exact PR HEAD；PR 的所有 GitHub required checks、branch rules、mergeability 與必要 environment approval 滿足後，CM 才可送入 native merge queue。CR／DS／完整 confidence 的 routine 結論平行收斂、不形成隱性 hard gate；若揭露 P0／P1／security，必須先寫成 durable hold。`pr-gate` 的 short `required` 上游各有 3 分鐘 hard stop、聚合本身 1 分鐘；backend／ops／iOS 的完整**受影響** `confidence` 是 advisory outcome，依 fail-closed changed-path policy 同時平行收斂，不形成所有 PR 的全域串行門檻。
4. merge group 跑獨立 short `required`；landing 後 CM cleanup exact merged residue，並從 canonical clean `main` 做 ff-only sync。GitHub `main` 是產品真相；依 release 意圖執行版本發布，production deploy 不因一般 merge 自動發生。

workflow `pr-gate` 的 check run `confidence` 失敗、非預期 skip、取消或缺失必須保留為真實偏離並追蹤 fix-forward／rollback；它不會被 `required` 覆蓋，也不能被重新描述成 PASS。只有 CM 已確認 exact `main` 對相同受影響 surface 啟動等價驗證時，才可取消已被取代的 PR run；完整結論仍等主線 terminal result。合併速度與完整驗證是兩個不同的控制面。

## Deterministic delivery control cycle

唯一 command 入口是 `ops/delivery.py`。它輸出 `kg.delivery.command.v1` JSON；成功為 `ok: true`／exit 0，contract、source、CAS 或 I/O failure 為 `ok: false`／exit 1。`dogfood-preflight` 完成觀測但 launch baseline 尚未 ready 時保留 `ok: true` 與完整 blockers、回 exit 2，方便啟動器 fail closed。global option 必須放在 subcommand 前；`--repo` 預設 current working directory，`--runtime-status-file` 是 caller 提供的單一 `kg.delivery.runtime.v1` receipt 檔，缺檔代表 `unknown`，不猜 reachable。`runtime-receipt` 以 atomic replace、時間單調性與可選 cycle CAS 寫入同一檔案；它只記錄 caller-owned liveness，不保存 Issue／PR／queue lifecycle。`dogfood-preflight` 的 supervision checkout 必須以重複的 `--supervision-worktree` exact path 明確傳入，未列出的 physical worktree 不得被排除。`watchdog` 是約 300 秒的唯讀 liveness tick，只產生 `noop`、`wake` 或 `escalate` 決策；它不能被 scheduler 當成喚醒授權。需要實際喚醒時，scheduler 必須改用同一 receipt 檔的 `watchdog-claim`，只有收到 `action=wake` 且 `wake_claimed=true` 才能建立一次 turn；`escalate`、`noop` 或 `wake_claimed=false` 都不得建立 session。`watchdog-claim` 在外部 dispatch 前以 receipt 的 cycle／last-action CAS 原子保留 wake；同一 stale receipt 的第二次呼叫會回 `escalate`，不會重送 wake。`RUNNING` runtime 過期只會 `escalate`，禁止猜測並行喚醒；只有非 active 的外部 thread 狀態加上 stale `IDLE`／到期 `WAITING` receipt 才可發一次 `wake_id`。`--repo` 只選 Git／GitHub 的 canonical target 與其明確 registry state；registry command module 在程序啟動時從正在執行的 `delivery.py` 同版本載入，且每次 registry mutation 先證明來源 checkout clean、source HEAD 與 target HEAD 完全相同，避免 stale detached checkout 套用舊 control-plane 語義。當 `delivery.py` 在 linked owner worktree 內執行時，Git mutation 仍錨定受保護的 `main` checkout，來源 worktree 只作 source-provenance target，確保 publication cleanup 不會嘗試移除自身執行中的 checkout；移除來源 worktree 後仍能完成最後 CAS。

### 先觀測，再執行 exact action

```bash
./ops/delivery.py --runtime-status-file <owner-status.json> inspect \
  --supervision-worktree <exact-supervision-path>
./ops/delivery.py metrics
./ops/delivery.py plan
./ops/delivery.py --runtime-status-file <supervisor-runtime.json> runtime-receipt \
  --thread-id <supervisor-thread> --state running --cycle-id <cycle-id> \
  --lease-seconds 600 --clear-last-action
./ops/delivery.py --runtime-status-file <supervisor-runtime.json> watchdog-claim \
  --supervisor-thread <supervisor-thread> --stale-after-seconds 300
```

外部 scheduler 只能用 `watchdog-claim` 的 `wake_claimed=true` 結果喚醒 Supervisor；`watchdog` 保留給唯讀觀測。收到 `wake` 但未取得 claim、`noop` 或 `escalate` 時，scheduler 必須結束本 tick，不建立 Codex session。

- `inspect` 分類每條 known／unmapped lane，並分開回傳 lane problems 與 source problems。
- `metrics` 量測 GitHub open exact-label candidate Issues（排除 nonterminal registry occupancy）、REANCHOR、active、publishable、durable PR、required-running／green／failed、native queue depth、cleanup、blocked 與 physical worktree reservoirs；candidate query／parsing failure 進 source problem。另把 live facts 與 canonical checkout `.cache/delivery_telemetry.ndjson` 的 append-only duration evidence 合併，計算最近一小時 hand-back→PR、PR→required-start、required duration、required-success→native enqueue、merge→main sync、merge→terminal cleanup 的 sample count／p95，並輸出 collision／required failure rate 與 idle worktree。telemetry 不是 lifecycle ledger；寫入失敗只回傳 machine warning，不回滾已完成的 publish／queue／cleanup／sync。malformed journal、CAS conflict 或跨來源時間倒流仍是 source problem，不被當成快速交付。
- `plan` 加上最近一小時 merge cadence，依 [delivery model](../reference/delivery_model.md#deterministic-feedback-controller) 的 policy 回傳可同時處理的 actions 與 `desired_new_solvers`；candidate 低於 20 時建議 `replenish_candidates`，REANCHOR 大於 0 時建議 `reanchor_front`。在 CI／PR／cleanup／source facts 健康且 durable PR 未達 ceiling 時，active Solver 即使在 cadence 尚健康時也補向 8、最多 12，每 cycle 最多 4 且不超過既有未占用 candidates；PR reservoir 與 active Solver reservoir 不合併計數。live-lane collision pressure 高於 20% 時輸出 `improve_scope_partition` 並停止新 solver birth。輸出只供 Scout／PI／CM 決策，不會 dispatch、enqueue、建立 Issue 或 cleanup。

Candidate Issue body 先由 deterministic contract 產生並重驗：

```bash
./ops/delivery.py render-candidate-body --payload-file <candidate.json> > <issue-body.md>
./ops/delivery.py validate-candidate-body --body-file <issue-body.md>
```

只有 exact `delivery:candidate` label 加一份合法 `kg.delivery.candidate.v1` contract 才算供給；contract 固定包含 Severity、Priority、structured Scope、Acceptance 與 initial hard holds。Issue 派工後的全部 canonical external IDs 都會占用 candidate，避免同 Issue 以不同 reference 重複 dispatch。

### 四角色 dogfood 啟動

首輪只建立 `Backlog Scout`、`PI`、`CM`、`Supervisor` 四個 top-level tasks；完整角色邊界、clean-slate preflight、repository-rule 部署順序、canary promotion、fault drill 與 freeze／rollback 步驟統一由 [`docs/sop/delivery_control_dogfood.md`](../sop/delivery_control_dogfood.md) 定義。Issue Solver 是 Scout 依 capacity decision fan-out 的子代理，不是第五個常駐控制角色。

### PI publication 與 local release

```bash
./ops/delivery.py receipt --lane <lane-id>
./ops/delivery.py publish --lane <lane-id> --title '<canonical PR title>'
./ops/delivery.py record-published-base --pr <number>
./ops/delivery.py release-published --pr <number>
./ops/delivery.py repair-pr-metadata --pr <number>
./ops/delivery.py trigger-required --pr <number>
./ops/delivery.py reconcile-holds --pr <number> --hold <p0|p1|security>
./ops/delivery.py reconcile-holds --pr <number> --clear-all
```

`receipt` 只把唯一 active、clean、owner-bound、Scope-exact 的 `kg.worktree.handback.v1` 正規化為 `kg.delivery.handback.v1`；focused Validation 與 hand-back 時的 initial P0／P1／security holds 都屬於 immutable receipt。owner／delegation／Scope 變更會遞增 claim generation 並清除舊 seal。Scope overlap 在 `register`／`scope-set` 的 ledger lock 內就對所有 `active`／`cleanup_pending`／`published` claim fail closed，不延後到 publish；一般 register 也不能把 published branch／path 當成可接管 owner。`publish` 先以 compare-and-swap push exact branch，明確建立 target=`main` 的非 draft PR，自動產生 Scope／Validation／Impact／typed receipt／typed holds，驗證 final PR target／head／body／paths，再取得 registry `cleanup_pending` lease；initial hold 在首次 PR publication 就必須 durable，existing PR 的 typed／label／legacy hold 則會被保留，不能因 reanchor 被清除。lease 會阻擋同 branch／path 的新 claim，也會讓 controller 停止增生 solver，local worktree／branch 精確移除後才完成為 `published`。`publish` 在 durable PR readback 後，以 registry CAS 另存 GitHub target 的 `published_base_sha`；原始 typed hand-back 的 `base_sha` 永遠不覆寫。若 publication 途中只完成 PR、尚未完成這個 CAS，可用 `record-published-base --pr` 對同一 exact PR／registry tuple 做一次性、可重試的觀測收斂；任一 drift 都拒絕 mutation。`repair-pr-metadata` 在 typed receipt 仍可解析時，以 exact published registry／HEAD／Scope 證據只重建同一 PR body，並把 draft 移到 ready；它不重建 worktree、不修改 title 或 code。`reconcile-holds` 是 PI 在 explicit clearance 後的 body-only metadata transaction；清除必須明確 `--clear-all`，且 durable hold label 尚在時拒絕。collision 與 cleanup 只讀可解析的 exact Scope／receipt，所以無關的 malformed terminal history 不會阻塞；目標 claim 不完整仍 fail closed。若 durable PR 已完成、後續 lease 或 local removal 中斷，保留原錯誤、不回退 PR；重跑同一 `publish`，或用 `release-published` 從 PR receipt 完成 idempotent local release。

`trigger-required` 只在同一 exact published PR 的 required 為 `ABSENT`／`FAILURE` 時 dispatch 帶 PR number／base／HEAD 的 workflow；`PENDING`／`SUCCESS` 拒絕重複觸發，hold 原樣保留且 dispatch 不代表 Ready。

若 required 是 code failure，published PR 已取代 local assets，使用 original owner 的 exact tuple 恢復修復環境；若只是 merge-front base stale，才使用 JIT reanchor：

```bash
./ops/worktree_orchestrate.py resume-published --lane <lane> --branch <branch> --owner-thread-id <thread> --claim-generation <generation> --expected-remote-head <sha> --path <new-path>
./ops/worktree_orchestrate.py reanchor --merge-front-pr <number> --lane <lane> --branch <branch> --owner-thread-id <thread> --claim-generation <generation> --expected-remote-head <sha> --live-main <sha> --path <new-path>
```

兩者都只做 exact same-owner local lifecycle transition，不操作 GitHub、不測試、不 hand-back、不 push；`resume-published` 保留 original recorded base，`reanchor` 以 `published_base_sha` 證明目前 PR 的既有 target 觀測，再把新的 owner generation 改用仍通過 remote CAS 的 live main。這兩個 base 不得混寫：原始 `base_sha` 保留 hand-back provenance，`published_base_sha` 只描述 GitHub PR target。owner 修復／rebase後必須重新 commit（若有變更）與 typed hand-back，PI 再更新同一 PR。

PR readiness workflow 的 parser 入口是：

```bash
./ops/delivery.py validate-pr-body --head-sha <exact-pr-head> --body-file <body.md>
```

省略 `--body-file` 時從 stdin 讀取。這個命令只驗證唯一 machine receipt 與 exact HEAD，不重算 local registry seal，也不代表 merge Ready。

### CM queue、terminal cleanup 與 main sync

```bash
./ops/delivery.py queue --pr <number>
./ops/delivery.py queue --pr <number> --hold <p0|p1|security>
./ops/delivery.py cleanup-merged --pr <number>
./ops/delivery.py discard-abandoned-handback --branch <branch> \
  --expected-head-sha <handback-head> --operator <identity> \
  --reason '<explicit discard rationale>'
./ops/delivery.py --repo <canonical-checkout> sync-main
```

`queue` 只接受 registry `published`、PR body／paths／head／live base、target branch=`main`、all required checks、mergeability 都 exact 且無 hold 的 candidate，並以 GraphQL `enqueuePullRequest(expectedHeadOid)` 送進 GitHub native merge queue；它不呼叫會在無 queue 情境退化成直接合併的 `gh pr merge --auto`。即使 caller 忘記 `--hold`，typed body、legacy `PUBLISH ONLY` 與 `delivery-hold:*` labels 任一存在都會阻擋 queue。canonical body 也在 mutation 前後納入 CAS。inventory 直接讀 `mergeQueueEntry`，已入列 PR 顯示 `pr_queued`；enqueue 後 `main` tip 自然前進由 merge group 重驗，不會讓 immutable receipt 失效或誤觸 required repair。retarget／head／body drift 時，只有 queue entry ID 仍等於本次 mutation 回傳值才可呼叫 `dequeuePullRequest`，若 entry 已被另一 transaction 取代只報衝突、不得移除。`--hold` 是額外 typed hard stop，不是 override。inventory 會對每個無 open mapping 的 `published` record 精確補讀同 branch 的 terminal PR，讓 merged cleanup 不會因 open-only 列表消失。`cleanup-merged` 在取得 lease 後、每項刪除前及 terminal disposition 前都重新讀取 exact merged PR target／branch／head／body；只依 exact receipt 移除匹配的 local residue／remote branch，最後由 delivery adapter 提交帶 digest 的 `kg.worktree.terminal-proof.v1`。若 PR tuple 漂移則保留 lease 與未刪資產，一般 `worktree_orchestrate resolve` 不能直接標記 merged。`sync-main` 只在 `<canonical-checkout>` clean、位於 `main`、local ref 與 live `origin/main` 未在 preflight 後漂移時執行 `--ff-only`；不得在 feature worktree 執行，也沒有 force-reset fallback。

`discard-abandoned-handback` 是 owner recovery 之後的最後一條窄路徑：只接受 ownerless、已 abandoned、具有效 typed handback、沒有任何 PR history、沒有 physical worktree、local／remote ref 仍等於 expected HEAD 的單一 branch。它先以 registry CAS 寫入帶 digest 的 `kg.worktree.discard-proof.v1`，再以 expected HEAD 刪除 exact local／remote ref；任何 owner、dirty worktree、PR history、remote drift 或 canonical main 問題都 fail closed。這不是批次 prune，也不會替有 owner 的 lane 做決策；同一 operator／reason 可安全重試。

### 錯誤隔離

- source inventory 可局部解析時，malformed registry／PR／runtime／Git observation 留在對應 lane 或 `source_problems`；raw registry 非 object、無效 external ID、unknown status 都必須可見，metrics 不把 unmapped／unknown 供給算成 owner-mapped durable supply。
- duplicate PR、Scope collision、dirty／missing worktree、owner unavailable、stale base／HEAD、required failure、hold 或 CAS race 只封鎖該 exact lane；不要因另一條 lane 綠就 bulk transition、delete 或重寫。
- publish、local release、queue、merged cleanup 與 main sync 都可重跑，但只在 readback 仍符合原 receipt 時 idempotent。`worktree_registry.py sweep --commit` 不可作 cleanup shortcut；逐 record 使用 exact generation／branch／path／HEAD transition。

## Local worktree boundary

`ops/worktree_registry.py` 是本機 ownership ledger 的相容 CLI facade：記錄 branch、path、thread、external IDs、Scope、hand-back、evidence 與 local disposition；admission、record normalization、handback、lifecycle、storage 與 parser 在 `ops/worktree_registry_core/` 分責。`ops/worktree_orchestrate.py` 是本機 coordinator：建立／接管工作樹、檢查 overlap、執行必要 gate、保存 log、交回或移除工作樹。

GitHub Issue、Project、PR、CR／DS review、merge 與 release approval 不在本機 ledger 再存一份，也沒有本地 backlog、merge queue 或批次整合狀態。`published` 只表示 durable PR 已可取代 local assets，不是 PR lifecycle mirror。當本機與 GitHub 顯示不同，以 GitHub ref、PR 與 Actions 為準；local evidence 只能說明本機曾經驗證過什麼。

typed `kg.worktree.handback.v1` 交接會在 clean worktree 上讀取 live `origin/main`，把 SHA 記入 `origin_main_sha`，並分別要求 declared base 是 live main 與 physical tip 的 ancestor；它刻意不要求 live main 已是 tip 的 ancestor，因此 main 前進不會阻止歷史-base handback durable publish。remote/main 不可讀、base 不在 main history 或 base 不在 tip history時才 fail closed。PI 只把它正規化成 PR 內的 `kg.delivery.handback.v1`，不變更 provenance。這個 local receipt 只代表交接當下的執行證據，不是 current-main Ready；只有 merge-front 由 CM 重新查 live `origin/main`、exact PR／registry tuple 與 required checks，必要時要求同 owner JIT reanchor。

恢復 active branch/path 的工作前，先重新 register 或 adopt；先前 hand-back receipt 僅保留為 audit evidence，不能替 resumed claim 釋放 admission。完整 admission rule 以 [delivery model](../reference/delivery_model.md) 為準；完成新一輪工作後重新 hand-back。

## 變更前檢查

- `git status --short`、branch、HEAD、remote tracking ref。
- active worktree 是否已占用相同 Scope。
- `./ops/capability_matrix.py --json` 是否允許要做的動作。
- 受影響的 SoT 文件與 `./ops/docs_impact.py --files ...`。
- production／不可逆步驟是否有明確批准；沒有就停在 dry-run。

## 變更後檢查

- 只宣稱有當下輸出的驗證；不要以 clean tree 或舊 receipt 代替。
- code、ops 或 CI 變更跑相應的最小測試；`.github/` 變更跑 YAML／shell／entrypoint 檢查。
- 文件變更跑 `./ops/docs_lint.sh`；registry 變更跑 `./ops/docs_lint.sh --registry`。
- delivery control 變更跑 `./ops/test_ops.sh delivery-control`；agent-facing CLI 變更同步 `./ops/delivery.py --help` 與 docs impact。
- PR 內列出 exact command、exit status、風險與未解項。

## Production boundary

API、host、資料庫、CloudKit、App Store、TestFlight 與 rollback 依各自 SOP；所有生產寫入都經 `ops/devops_kg_safe.sh`、`ops/release.sh` 或被明確列出的領域入口。GitHub merge 不是 production approval。
