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
verified_against: 2a7930c04f661c266ce05b3568f375e1db2a39f1
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
3. `pr-readiness` 先用 typed machine receipt 驗證 exact PR HEAD；PR 的所有 GitHub required checks、CR review、DS 文件判斷與必要 environment approval 滿足後，CM 才可送入 native merge queue。`pr-gate` 的 short `required` 上游各有 3 分鐘 hard stop、聚合本身 1 分鐘；backend／ops／iOS 的完整**受影響** `confidence` 是 advisory outcome，依 fail-closed changed-path policy 同時平行收斂，不形成所有 PR 的全域串行門檻。
4. merge group 跑獨立 short `required`；landing 後 CM cleanup exact merged residue，並從 canonical clean `main` 做 ff-only sync。GitHub `main` 是產品真相；依 release 意圖執行版本發布，production deploy 不因一般 merge 自動發生。

workflow `pr-gate` 的 check run `confidence` 失敗、非預期 skip、取消或缺失必須保留為真實偏離並追蹤 fix-forward／rollback；它不會被 `required` 覆蓋，也不能被重新描述成 PASS。只有 CM 已確認 exact `main` 對相同受影響 surface 啟動等價驗證時，才可取消已被取代的 PR run；完整結論仍等主線 terminal result。合併速度與完整驗證是兩個不同的控制面。

## Deterministic delivery control cycle

唯一 command 入口是 `ops/delivery.py`。它輸出 `kg.delivery.command.v1` JSON；成功為 `ok: true`／exit 0，contract、source、CAS 或 I/O failure 為 `ok: false`／exit 1。global option 必須放在 subcommand 前；`--repo` 預設 current working directory，`--runtime-status-file` 是 caller 提供的 thread-id → state JSON，未提供或缺少 owner 時保留 `unknown`，不猜 reachable。

### 先觀測，再執行 exact action

```bash
./ops/delivery.py --runtime-status-file <owner-status.json> inspect
./ops/delivery.py metrics
./ops/delivery.py plan
```

- `inspect` 分類每條 known／unmapped lane，並分開回傳 lane problems 與 source problems。
- `metrics` 量測 active、publishable、durable PR、required-green／failed、cleanup、blocked 與 physical worktree reservoirs。
- `plan` 加上最近一小時 merge cadence，依 [delivery model](../reference/delivery_model.md#deterministic-feedback-controller) 的 policy 回傳可同時處理的 actions 與 `desired_new_solvers`；輸出只供 Scout／PI／CM 決策，不會 dispatch、enqueue 或 cleanup。

### PI publication 與 local release

```bash
./ops/delivery.py receipt --lane <lane-id>
./ops/delivery.py publish --lane <lane-id> --title '<canonical PR title>'
./ops/delivery.py release-published --pr <number>
```

`receipt` 只把唯一 active、clean、owner-bound、Scope-exact 的 `kg.worktree.handback.v1` 正規化為 `kg.delivery.handback.v1`。`publish` 先以 compare-and-swap push exact branch，建立／修復非 draft PR，驗證 PR readback 與 machine receipt，再把 local claim 轉成 `published` 並移除 local worktree／branch。若 durable PR 已完成、後續 registry transition 或 local removal 中斷，保留原錯誤，不回退 PR；修復 source 後重跑同一 `publish`，或用 `release-published` 從 PR receipt 完成 idempotent local release。

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
./ops/delivery.py --repo <canonical-checkout> sync-main
```

`queue` 只接受 registry `published`、PR body／paths／head／live base、all required checks、mergeability 都 exact 且無 hold 的 candidate，並用 exact head 送進 GitHub native merge queue；`--hold` 是 typed hard stop，不是 override。`cleanup-merged` 只依 exact merged PR receipt 移除匹配的 local residue／remote branch，再 terminalize registry record。`sync-main` 只在 `<canonical-checkout>` clean、位於 `main`、local ref 與 live `origin/main` 未在 preflight 後漂移時執行 `--ff-only`；不得在 feature worktree 執行，也沒有 force-reset fallback。

### 錯誤隔離

- source inventory 可局部解析時，malformed registry／PR／runtime／Git observation 留在對應 lane 或 `source_problems`；metrics 不把 unmapped／unknown 供給算成 owner-mapped durable supply。
- duplicate PR、Scope collision、dirty／missing worktree、owner unavailable、stale base／HEAD、required failure、hold 或 CAS race 只封鎖該 exact lane；不要因另一條 lane 綠就 bulk transition、delete 或重寫。
- publish、local release、queue、merged cleanup 與 main sync 都可重跑，但只在 readback 仍符合原 receipt 時 idempotent。`worktree_registry.py sweep --commit` 不可作 cleanup shortcut；逐 record 使用 exact generation／branch／path／HEAD transition。

## Local worktree boundary

`ops/worktree_registry.py` 是本機 ownership ledger：記錄 branch、path、thread、external IDs、Scope、hand-back、evidence 與 local disposition。`ops/worktree_orchestrate.py` 是本機 coordinator：建立／接管工作樹、檢查 overlap、執行必要 gate、保存 log、交回或移除工作樹。

GitHub Issue、Project、PR、CR／DS review、merge 與 release approval 不在本機 ledger 再存一份，也沒有本地 backlog、merge queue 或批次整合狀態。`published` 只表示 durable PR 已可取代 local assets，不是 PR lifecycle mirror。當本機與 GitHub 顯示不同，以 GitHub ref、PR 與 Actions 為準；local evidence 只能說明本機曾經驗證過什麼。

typed `kg.worktree.handback.v1` 交接會在 clean worktree 上讀取 live `origin/main`，把 SHA 記入 `origin_main_sha`，並要求 declared base、live main 與 physical tip 可證明 ancestry 相容；remote/main 不可讀或 ancestry 不相容時 fail closed。PI 只把它正規化成 PR 內的 `kg.delivery.handback.v1`，不變更 provenance。這個 local receipt 只代表交接當下的執行證據，不是 current-main Ready；`main` 前進後，PI／CM 必須重新查 live `origin/main`、exact PR／registry tuple 與 required checks。

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
