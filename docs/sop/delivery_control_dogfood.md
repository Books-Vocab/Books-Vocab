<!-- doc-meta
tier: sop
authority: derived
update_trigger: delivery-control-dogfood-changed
scope:
  - docs/reference/delivery_model.md
  - ops/delivery.py
  - ops/delivery_control/
  - ops/worktree_registry.py
  - ops/worktree_orchestrate.py
  - .github/workflows/pr-readiness.yml
  - .github/workflows/pr-gate.yml
  - .github/workflows/merge-group-required.yml
verified_against: f74b739123384e16936c6c984a22b8befe9f2865
-->
# Delivery Control Dogfood SOP

目的：以四個 top-level tasks 驗證 KG delivery control 能在不囤積本地 worktree、不繞過 required／hold、且 GitHub merge queue 正常時，持續接近每小時 12 個 merged PR。這是 canary 操作流程，不是另一套 Issue／PR／registry 狀態庫。

角色、hard gate 與生命週期語義以 [`docs/reference/delivery_model.md`](../reference/delivery_model.md) 為準。本 SOP 只定義第一次上線的啟動、觀測、升級與停止程序。

## 啟動前硬條件

正式 tasks 尚未建立前，在 canonical checkout 執行：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg dogfood-preflight \
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/2366/kg \
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/7e07/kg \
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/be28/kg \
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/e695/kg
```

只有 `result.ready=true` 才能建立四個 tasks。preflight 必須同時證明：

- canonical checkout 是 clean `main`，且 local `main == origin/main`；
- `main` 已 protected、required contexts 包含短 gate `required`、native merge queue 已啟用；
- delivery inventory 中只剩 canonical main；若啟動器使用 detached supervision checkout，必須以
  `--supervision-worktree` 逐一列出 exact path。未列出的 worktree 一律仍算 delivery／unknown
  blocker；不得用 `.codex` 路徑前綴或名稱猜測來排除；
- 沒有可行動的 active development、local handback、cleanup lease、blocked lane、unmapped／duplicate PR 或 source problem；
- 歷史 source problem、owner-recovery residue、無 physical worktree 的 terminal branch residue，以及明確 security/P0/P1 hold
  必須被 control plane 以 quarantine counters 明確標示。它們仍保留原始 evidence、不可 merge／刪除／接管，
  但不能阻塞與其無關的 delivery lane；任何新鮮且可行動的同類問題仍會讓 preflight fail。
- 現存 PR reservoir 為空；security／P0／P1 hold 必須先得到 terminal disposition，不能藏在 canary baseline。

candidate Issue reservoir 可以是空的；clean-slate baseline 只要求 read-only candidate query 可被可信解析，不要求啟動前先囤候選或建立本地 backlog。

這些條件任一失敗都只修該 blocker；不得以人工改 registry、刪 dirty worktree、跳過 branch rule 或降低 hard gate 讓 preflight 變綠。
quarantine 是可驗證的隔離投影，不是 cleanup 成功、owner 恢復、PR mapping 或 security clearance 的替代品。

控制面 PR 合併前不得預先修改 production repository rules。部署順序固定為：合併本控制面 PR → canonical `main` ff-only 同步 → 在 repository settings 啟用 native merge queue 並把 short `required` 設為 required context → 用 read-only API 讀回 merge queue 與 branch protection → 清到只剩 canonical worktree → 跑 preflight → 最後才建立四個 tasks。

## 四個 tasks 與唯一職責

| Task | 唯一責任 | 可用 mutation | 禁止事項 |
|---|---|---|---|
| Backlog Scout（BS） | 維持 GitHub 20–30 個 open exact-label candidate；去重、建立唯一 Issue；選擇無 collision Scope；依 `desired_new_solvers` fan-out | Issue、owner-bound worktree 的正常 admission | push／PR／merge；自己實作 product code；保存第二套 backlog |
| PR Integrator（PI） | 事件式消費 typed handback；建立／更新唯一 PR；readback；publication 後立即釋放 local assets；metadata／required repair | `publish`、`release-published`、`repair-pr-metadata`、exact terminal cleanup | 修改 product code；接管 owner branch；merge／enqueue |
| Codebase Manager（CM） | 只處理 merge-front；exact admission；native enqueue；landing 後 ff-only sync；把 merged receipt 交給 PI cleanup | `queue`、`sync-main`、明確 hold reconcile | 修 PR body／product code；等待 routine advisory；手動 merge |
| Supervisor | 以約 300 秒 watchdog tick 讀取 deterministic facts 與四個 task 活動；控制 freeze／ramp；升級事故 | task-level freeze／resume 與明確事故升級 | 成為產品 owner；替 BS／PI／CM 執行 mutation；把 agent 自述當 facts |

四個 top-level tasks 彼此直接交接事件；Supervisor 不當 routine progress recipient。所有可硬性判定的 gate 由 `ops/delivery.py`、registry CAS、GitHub rules 與 Actions 執行，agent 只選擇 bounded next action。

事件只負責喚醒下一個責任人，不能取代 current facts。固定路由如下：

| Event | 直接接收者 | 接收後唯一動作 |
|---|---|---|
| candidate admitted／capacity slot opened | BS | 派一條 exact owner／Scope 的 IS lane |
| `kg.worktree.handback.v1` | PI | 立即 publish／readback／local release |
| PR contract／required outcome | PI | body-only repair、required trigger，或同 owner `resume-published` |
| confidence／CR／DS outcome | PI | 非嚴重者送 BS 建 follow-up；P0／P1／security 先 durable hold，再送 BS |
| exact required SUCCESS、無 hold | CM | final read；可入列即 native enqueue |
| merge landing | CM → PI | CM ff-only sync；PI exact terminal cleanup |
| baseline／candidate occupancy changed | PI／CM → BS | 只重讀 GitHub／registry facts，再補供給 |
| 事故、SLO／capacity 失守、無法分類 | 該 owner → Supervisor | 只送 exact blocker；Supervisor freeze／ramp，不代做 mutation |

事件可以延遲、重送或遺失；每個 receiver 都必須先重讀 GitHub／Git／registry，依 idempotent command 收斂。禁止用 task 訊息計數、推定 Ready、保存 PR queue 或回報 routine progress 給 Supervisor。

## Lifecycle conformance matrix

第一次 dogfood 前，用下表核對原始 delivery lifecycle；「agent decision」只能用於無法純機械判斷的 bounded judgment，其輸出仍須落回 GitHub／registry durable facts。

| Lifecycle contract | Deterministic owner／evidence | Agent responsibility |
|---|---|---|
| User direct assignment 或 BS Issue intake | `kg.delivery.candidate.v1`、exact label、GitHub Issue；direct packet 不強制建 Issue | BS 去重、Severity／Priority／Acceptance 判斷 |
| Issue Solver／Worker dispatch | candidate occupancy、registry external IDs、owner／Scope admission | BS 依 `desired_new_solvers` fan-out；不自行實作 |
| branch／worktree claim | registry lock、generation、exact Scope、collision | IS／Worker 只在指定 worktree 實作 |
| focused implementation → commit | Git clean HEAD、exact diff operations | IS／Worker 做最小修復與 focused proof |
| typed handback | `kg.worktree.handback.v1` seal、digest、origin main、Validation、initial holds | owner 交回；PI 不改 code／不補造證據 |
| handback → durable PR | `delivery.py receipt/publish`、unique PR mapping、CAS push、exact readback | PI 事件式立即執行 |
| publication 後 local release | cleanup lease、worktree／local branch absence readback | PI 立即清理；不以等待 CI 為理由保留 |
| exact abandoned PR | unique PR／typed body／published registry／local absence／remote SHA readback | PI 只對已證明可放棄的同一 PR 執行 `abandon-pr`；dirty、unknown、remote drift 一律保留 |
| readiness／required | typed PR receipt validator、short `required`、exact manual retrigger | PI 修 metadata／trigger transient retry |
| required code failure | `resume-published` same-owner generation+1 transaction | 原 owner 修 code、fresh handback；PI 更新同一 PR |
| full confidence／CR／DS | GitHub check／review facts；typed／label hold | PI 分類 follow-up；嚴重者先 durable hold |
| merge-front freshness | `reanchor` same-owner CAS、fresh handback／PR required | CM 只選隊首，不批次重建後方 PR |
| admission／merge | exact queue gate、native merge queue、merge-group `required` | CM enqueue，不手動 merge、不等 routine advisory |
| landing／main sync／cleanup | `sync-main` ff-only CAS、`cleanup-merged` terminal proof | CM sync；PI 刪 exact remote residue並 terminalize |
| release／deploy | 獨立 release／deploy SOP、approval／health／rollback | 不因一般 merge 自動觸發 |

## 事件與命令

### BS：維持供應

1. 只把 GitHub 中 open、帶 exact `delivery:candidate` label，且 body 通過 `kg.delivery.candidate.v1` 驗證的 Issue 視為 candidate；不得另建本地 backlog。BS 先用 `render-candidate-body` 產生 Severity／Priority／exact Scope／Acceptance／initial holds，再用 `validate-candidate-body` 驗證最後要寫入 GitHub 的 body；label-only Issue 不算供給。
2. `replenish_candidates` 出現時 fan-out 互不重疊的 read-only auditors，把 reservoir 補向 20–30；每個發現先做 Issue／PR history、active Scope、physical worktree 去重。
3. `desired_new_solvers` 只消費 controller 已排除 nonterminal registry occupancy 的既有 candidates；即使同 cycle 正在補貨，仍可安全 dispatch 現有候選。
4. 需要追蹤者建立唯一 Issue；明確 user assignment 可直接走 Worker。只把一個 intent／owner／exact Scope 的 lane 派給 Solver，不把數個可獨立問題綁成一個 PR。
5. Solver 只跑 focused proof，commit clean 後以 supported registry command 產生 `kg.worktree.handback.v1`；Issue contract 的每個初始 hard hold 都必須以 `hand-back --hold` 原樣寫入 immutable seal，PI 不可自行推測或清除。

```bash
./ops/delivery.py render-candidate-body --payload-file '<candidate.json>' > '<issue-body.md>'
./ops/delivery.py validate-candidate-body --body-file '<issue-body.md>'
./ops/worktree_registry.py hand-back --branch '<branch>' --outcomes '<validation.json>' [--hold security]
```

canary promotion 前 `canary_solver_limit=1`；不能直接為追求數量啟動 8–12 lanes。

### PI：handback 到 PR

收到 handback 事件即執行：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg receipt --lane '<lane-id>'
./ops/delivery.py --repo /Users/chenliangyu/project/kg publish --lane '<lane-id>' --title '<title>'
```

`publish` 驗證 owner／generation／branch／path／base／parent／HEAD／Scope／digest，push 並建立或更新唯一 PR，做 exact remote-head readback，再用 cleanup lease 移除 local worktree／local branch。歷史 base 可以 durable publish；不要求 current-base，也不等待大型 local gate 或 GitHub CI。

若 publication 已成功、local release 中斷，只重試：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg release-published --pr '<number>'
```

已確認是 owner 無法繼續、PR 未 merge、registry 與 remote branch 完整對應，且 local assets 已不存在時，才可執行可重試的 terminal abandonment：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg abandon-pr --pr '<number>'
```

這不是一般 cleanup，也不是 dirty／unknown worktree 的刪除捷徑；transaction 會先 exact-readback，關閉唯一 PR、CAS terminalize registry、以預期 SHA 刪除 remote branch，再做 final readback。任一步不吻合就 fail closed，保留可恢復狀態。

metadata 漂移只修同一 PR：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg repair-pr-metadata --pr '<number>'
```

若 controller 回傳 `trigger_required` 或確認 exact required `FAILURE`，PI 只對同一 published tuple 觸發 deterministic repair：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg trigger-required --pr '<number>'
```

command 會再次驗證 unique PR mapping、typed receipt、registry generation、Scope／paths、base／HEAD 與 canonical body；required 已 `PENDING`／`SUCCESS` 時拒絕。dispatch 保留所有 P0／P1／security holds，且不代表 Ready／merge eligibility。

若 required failure 是 code failure而不是可重觸發的 transient failure，publication 後的 local assets 已被正確清除，PI 不可要求 owner 在不存在的 worktree 修 code。先用 original published generation、owner、branch 與 exact remote HEAD 重建同一 owner lane：

```bash
./ops/worktree_orchestrate.py resume-published \
  --lane '<lane-id>' --branch '<branch>' \
  --owner-thread-id '<thread-id>' --claim-generation '<generation>' \
  --expected-remote-head '<exact-pr-head>' --path '<new-worktree-path>'
```

command 只在 remote branch／receipt／owner／Scope 與 released local assets exact 時，把舊 published generation terminalize 並建立 generation+1 active claim；它不跑測試、不 hand-back、不 push，也不 force-push。原 owner 修復、commit、fresh typed handback 後，PI 只更新既有唯一 PR。

`confidence`／CR／DS 是 parallel advisory evidence，PI 不等待它們才發布或交給 CM。若在 merge 前揭露 P0／P1／security，PI 必須先用 `reconcile-holds` durable 表示；其他失敗送 BS 建獨立 follow-up。若結果在 landing 後才完成，不能改寫成 PASS，仍依 severity 走 follow-up 或 release／rollback 升級。

PI 的每次 metadata／hold／required 修復都保留原始 commit、owner、Scope 與 PR identity；新 generation 只能由 same-owner transaction 建立，不能用 body repair 或 reanchor 洗掉 initial hold。

### CM：merge-front 與 landing

CM 只選一個 merge-front。`reanchor_front` 出現時先要求原 owner 對既有 `LaneState.REANCHOR` 使用 supported JIT reanchor；不重建後方 PR、不批次 rebase。supported command 會原子保存舊 generation 的 publication audit、建立同 owner 的 fresh generation 與 worktree，但不代替 owner rebase／測試／hand-back／push：

```bash
./ops/worktree_orchestrate.py reanchor \
  --merge-front-pr '<number>' --lane '<lane-id>' --branch '<branch>' \
  --owner-thread-id '<thread-id>' --claim-generation '<generation>' \
  --expected-remote-head '<old-pr-head>' --live-main '<exact-origin-main>' \
  --path '<new-worktree-path>'
```

fresh typed handback 更新同一 PR 並重跑 required 後，CM 執行：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg queue --pr '<number>'
```

`queue` 必須 final-read exact current base／head／Scope／receipt、non-draft、mergeable、required SUCCESS、native merge queue 與無 durable P0／P1／security hold。只有 GitHub exact readback 已證明 PR landed，才執行：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg sync-main
```

`sync-main` 只允許 clean `main` 的 ff-only CAS；queue admission 本身不等於 merge landing。

PI 收到 exact merged PR receipt 後完成：

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg cleanup-merged --pr '<number>'
```

完成 readback 必須是 remote branch、local worktree、local branch皆不存在，registry 保存 validated terminal proof。

### Supervisor：只看 facts

```bash
./ops/delivery.py --repo /Users/chenliangyu/project/kg inspect
SUPERVISION_ARGS=(
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/2366/kg
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/7e07/kg
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/be28/kg
  --supervision-worktree /Users/chenliangyu/.codex/worktrees/e695/kg
)
./ops/delivery.py --repo /Users/chenliangyu/project/kg metrics "${SUPERVISION_ARGS[@]}"
./ops/delivery.py --repo /Users/chenliangyu/project/kg plan "${SUPERVISION_ARGS[@]}"
```

`metrics` 與 `plan` 必須沿用 preflight 的 explicit supervision paths；不傳這些參數時，命令會把 supervision infrastructure checkout 當成 delivery worktree，不能拿來判斷 dogfood readiness。

固定看：最近一小時 merges、inter-merge p50／p95、candidate／active solver／handback／open PR／required-green／merge queue depth、六段 latency p95、collision rate、required failure rate、idle worktree、source problems，以及
quarantined source／lane／PR／terminal residue counters。agent 說「正在做」不計入容量；quarantine counters 也不算 active supply。

Supervisor 的 watchdog tick 只用來避免 supervisor 睡死，不代表每 300 秒執行一次完整 pipeline，也不代表自動喚醒被 freeze／archived 的角色。每次 tick 讀取 `watchdog` 的 structured runtime receipt；只有 lease 過期或 progress stale 才產生 deterministic `wake_id`，再由外部 Codex thread scheduler 執行一次性喚醒。`frozen`／`archived` 永遠 `noop`，缺 receipt 只能 `escalate`。Supervisor 的 deterministic plan 會把低水位轉成具體 action：`replenish_candidates`、`fill_required_capacity`、`restore_merge_buffer`、`reanchor_front`、`trigger_required`、`reconcile_idle_worktrees` 或 `recover_merge_cadence`。它只發出可驗證的 bounded action，不替角色寫 code、推 branch 或手動修 registry；任何 unknown／dirty／remote drift 轉成 exact blocker 並 freeze 相關 birth。

## Canary 與容量升級

1. **Canary 1 lane**：只允許一個 Solver，走完整 handback → PR → required → native queue → merge → sync → terminal cleanup。
2. **Promotion proof**：15 分鐘觀測窗內完成至少 3 個 exact merges；沒有 local residue、unmapped PR、source problem 或 hard-hold bypass。
3. **Ramp 4 lanes**：確認 required 並行、PR body repair、stale merge-front reanchor 與一條 blocked lane 不會停止其他 lane。
4. **Ramp 8 lanes**：維持 10–15 open PR、active Solver target 8／ceiling 12、至少 3 個 merge-ready／native-queue candidates；required 同時至少 3–4。green candidate 必須立即 enqueue，不為了做出數字而停在 PI；active 與 durable PR 是兩個不同 reservoir，不能相加後只補到 10。
5. **Steady state**：候選 20–30、active Solver 8–12、handback→PR p95 ≤60 秒、required p95 ≤240 秒、required-success→enqueue p95 ≤30 秒、每小時 ≥12 merges、inter-merge p95 ≤300 秒。

只有真實 candidate、GitHub、runner 與 merge queue 健康時才評估 merge SLO；供應或平台失效時，輸出 exact capacity blocker，不偽造工作。

這些水位是 feedback control，不是硬湊數字：active Solver、durable open PR、required-running 與 merge-ready queue 是四個不同 reservoir；不能把它們相加後宣稱達標，也不能因 cadence 暫時健康就停止補 active supply。

## Freeze／rollback 條件

以下任一發生，Supervisor 立即禁止新 solver birth，保留既有 GitHub PR 作 durable queue，並只做 bounded recovery：

- actionable source inventory 不完整、actionable unmapped／duplicate PR、unknown／dirty collision；
- live-lane collision pressure >20%；BS 必須重新分割 Scope，不能靠增加 Solver 掩蓋；
- required p95 >240 秒或 runner 容量耗盡；
- native merge queue／required branch rule缺失；
- local main drift／dirty／diverged；
- publication 後仍有 idle local worktree；
- terminal proof、remote branch或 registry readback 不一致；
- P0／P1／security hold 未被 durable 表示或疑似被洗掉。

已 quarantine 的歷史 residue 不會自動解除 freeze；它只從「是否能啟動無關 canary」判斷中隔離，仍需在後續
bounded cleanup／owner recovery cycle 中取得 exact proof 才能 terminalize。任何 quarantine 計數增加、同一 branch
重新出現 physical worktree、或新 PR 沒有 exact owner mapping，都立即回到 actionable blocker。

Freeze 不關閉或重建已發布 PR，也不刪 dirty／unknown worktree。修復後重新跑 `dogfood-preflight`；只有 baseline 或 canary phase 所需條件重新成立才 resume。

## Dogfood 完成判定

第一次 dogfood 只有在下列證據同時存在時才可標記成功：

- 四個 tasks 的角色邊界沒有交叉 mutation；
- 至少一輪 canary promotion 與一輪 ramp，且每次 landing 後 local main同步；
- handback 等待區與 CI 等待中的 local worktree 均為 0；
- PR body、required、merge-group required、hold、cleanup 的正反向案例都有實際或 fixture 證據；
- `inspect`／`metrics`／`plan` 可解釋每個 action，append-only telemetry failure 不阻擋已完成 transaction；
- 完整 tests、workflow contract、docs impact／registry／lint 綠。

本次實作刻意不新增常駐 daemon 或第二套 queue；controller 仍是 deterministic recommendation layer，GitHub／Actions／registry CAS 才是 durable enforcement。這是相對於原始圖的明確偏移，原因是先保留現有 GitHub-native authority boundary，避免把 agent memory 或本地資料庫變成另一個生命週期真相。

若 merge rate 未達 12/hour，結果必須指出當前最慢階段與量測值；不能以增加 agent 數量取代瓶頸診斷。
