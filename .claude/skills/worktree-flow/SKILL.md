---
name: worktree-flow
description: "隔離工作樹 intent→cutover 全流程。當使用者開新 session 丟一個 debug / dev / research intent 並要在隔離 git worktree 自動開發到 merge 進本地 main 時觸發。編排 ops/worktree_orchestrate.py 原語（preflight / open / adopt / gate / cutover / resolve / sync / deploy / sync-main / freeze）串起 P1 健康判定 + P2 登記簿 + 既有 gate 工具；純 research/唯讀不開 worktree。三平面：cutover=develop（離線落地本地 main）、sync=backup（推 origin/main 備份、零生產副作用）、deploy=release（推 origin/prod=唯一觸發生產部署）。亦涵蓋「需要 main」的任務路由（bootstrap 悖論→adopt、repo 手術→freeze）。"
user-invocable: true
version: 2.0.0
---

# worktree-flow

把「使用者丟 intent → 隔離工作樹開發 → gate → 進本地 main」串成一條可執行流水線。你是**單一執行 agent**，逐步呼叫原語 `ops/worktree_orchestrate.py`（下稱 `orchestrate`）。它只**編排**：P1 `ops/lib/worktree_state.py`（純健康判定）、P2 `ops/worktree_registry.py`（誕生→解決登記簿 + 孤兒哨兵）、與既有 gate 工具（`ios_ops.sh` / `verify_design_system.sh` / `docs_lint.sh` / `pytest`）。**絕不重造 gate 判斷**。

所有 mutation 子指令 **dry-run 預設，`--commit` 才落地**。`--json` 給機器判讀。

## 拓樸：本地 main 為主幹（core mental model）

**本地 `main` 是主幹**，兩個 origin ref 是不同平面的目標。worktree 從**本地 main** 分出、cutover **離線 ff 本地 main**（不碰網路、不部署）。本地 main 因此會**超前 origin** 幾個到幾十個 commit——這是正常的，不是「腐爛」。三平面：

- **develop = `cutover`**：worktree → 本地 main，離線、免費、可逆。
- **backup = `sync`**：本地 main → **origin/main**（機外備份鏡像），**零生產副作用**——reconciler 不看 main，推幾次都無所謂。
- **release = `deploy`**：本地 main → **origin/prod**，felix reconciler 盯 origin/prod、有 backend 變更就跑健康 gate 部署。**唯一碰生產。**

**cutover = 落地、sync = 備份、deploy = 發布（唯一碰生產）**，三者刻意分開。動詞語意正本見 `docs/sop/release.md`。

## 流程（照序）

### 1. preflight — 清殘骸 + fetch
```
ops/worktree_orchestrate.py preflight --json          # dry-run 先看
ops/worktree_orchestrate.py preflight --commit --json # 確認殘骸可清才落地
```
= `git fetch origin` + `worktree_registry sweep --exclude-current`。`--exclude-current` 保證**從任一 worktree 跑都不誤清自己**。sweep 只清三種保守形狀（dangling-landed / detached-orphan / registry-resolved），base 分支與 primary worktree 絕對保護——放心跑。

### 2. 讀地圖，建立 intent 理解
`orchestrate` 不幫你理解任務。先讀地圖：`kg-router`（capability matrix / 冷啟動路由）、`docs/registry.yml`（活文檔控制面）、對應 **SoT**（`docs/reference/product_surface.md` 查功能是否已存在、`tech_index.md` 查模組/endpoint/env、feature_boundary/* 查 iOS scope）。避免重造既有功能。

### 3. 純 research / 唯讀 → 不開 worktree
若 intent 是調查、盤點、回答問題、讀碼分析（**無程式碼寫入**）→ **直接做、直接回報，不開 worktree**。開 worktree 只為了承載會進 main 的 commit。`orchestrate open` 依 intent 類型命名分支（debug/* | feat/* | research/*）——research/* 分支僅用於**會產出 commit 的**探索（如寫 spike/POC）；純唯讀不需要。

### 4. 寫 code → 隔離工作樹開發到 cutover

**a. 拆 phase**：載入 `phased` skill，把任務切成可獨立 commit 的 phase plan。

**b. open**：
```
ops/worktree_orchestrate.py open --intent "<原始 intent 文字>" --slug <kebab-slug> --json
```
建 `.claude/worktrees/<slug>`、分支 `<type>/<slug>`（type 由 intent 自動判定），並在 P2 登記簿**誕生即登記**。記下回傳的 `path`。

**c. 逐 phase 實作（phased 模式）**：在 worktree 內做第 N phase 時，**同步派 code review agent 審 N-1 phase**（鐵律 4 逐項 review，鐵律 5 所有 Agent 背景化）。每個 phase 收尾 commit。**每 phase 後 rebase 本地 main**——這是 **gate 的硬性前置**，不是減少衝突的方便：本地 main 的 tip 沒被分支 HEAD 包含時 `gate` 會直接拒（判決會綁到一棵不會落地的樹）：
```
git -C <path> rebase main
```

**d. 全 phase 完 → gate**（impact-based，顯式跑；.githooks 只 best-effort，不可依賴）：
```
<path>/ops/worktree_orchestrate.py gate --worktree <path> --json
```
**`gate` / `cutover` 一律用工作樹自己那份 orchestrator（上面的絕對路徑形式），不是裸 `ops/...`。** 理由：gate 的**工具**是以工作樹為 cwd 執行的，所以**路由規則必須同代**——從主 repo 跑會用主 repo 的規則去排一組分支版工具的 gate（實測排出 8 道 vs 分支的 11 道，輸出形狀完全相同）。工具現在會自己擋（sha256 不同即 refuse，判決紀錄也帶 orchestrator 身分、cutover 會核對），但正確形式仍是上面這行。

它 diff `<path>` vs 本地 `main`，把改動路由到既有 gate 工具並彙總 `verdict`（block/warn/pass），把結果**記錄下來**（綁 worktree + HEAD sha + base 包含性）供 cutover 核對。

**開跑前先擋一道：分支落後本地 main 就直接拒**（EXIT_BLOCK，payload 帶 `behind_commits` / `base_changed_files`，**不寫任何判決紀錄**）。理由：cutover 的第一個動作就是 rebase 上本地 main，所以落後的樹被 gate 判過也不會是落地的那棵——判決會綁到一棵不存在的樹（IMP-20260806-945e01：實測 58 commits 落後的分支，main 上多出的 UITest 檔在工作樹裡根本不存在，`--grep` 選三個類靜默只匹配到兩個）。修法就是上面 c. 那行 `git -C <path> rebase main`，然後**重跑 gate**。`--plan-only` 不受此擋（它不跑也不記，是拒絕訊息指定的預覽出口）。impact→gate 對應：
- `ios/**` → `ios_ops.sh build` **＋** `build --catalyst`（sim 綠 ≠ Catalyst 綠）＋ `quality impact`（swift）＋ `test --unit`；**動到一般 UITest 檔**則另加 `test --ui --file <該 UITest 類> --dataset marketing_demo`（**只跑受影響的 UI 測試類，非全套**——全套當 block 會被 codebase 已知 UI flaky 誤擋每次 iOS cutover）。`LiveDemoAccessUITests` 是 Release＋實機＋live backend 專用契約，cutover gate 只跑 Release iphoneos build-for-testing 編譯 gate 並明示 runtime advisory；不得拿 simulator/fixture 偽裝其 runtime evidence，送審前仍須走 App Review `demo-run`。
- design-system / tokens / 生成 CSS / `ios/**/Models|UIComponents/` → `verify_design_system.sh`
- `docs/**.md` → `docs_lint.sh --files` ＋ conflict-marker 掃描 ＋ `verified_against` 可達性
- `backend/**.py` → 只跑 diff 內的**目標測試檔**；純 src 改動無目標測試 = **warn advisory**（不跑全套，全套有已知 pre-existing 假失敗）
- `ops/**.py` → `uv run --no-project --python 3.13 --with pytest pytest`（沙箱 uv，不碰 backend/uv.lock；block）：改 `ops/tests/test_X.py` 跑該檔；改 src（含 `ops/lib/`）跑對應 `ops/tests/test_<basename>`。每個 target 都做存在性檢查（以 worktree 為準：同 diff 新增的測試看得到、已刪除的不會塞給 pytest），**解析不到既存測試 = 跑整個 `ops/tests/`**（sandbox-unsafe 測試須自帶 dep-guard skip，前例見 `test_demo_ios_spec_emitter.py`）
- `ops/**.sh` → 三層（IMP-0051）：① `ops-shell-syntax`＝對每個改動的腳本跑 `bash -n`（block，只需 bash，沒有機器會靜默跳過——約 1/3 的 ops 腳本根本沒有自己的測試，這是它們唯一拿得到的檢查）；② `ops-shell:<test>`＝該腳本自己的測試（block），依慣例 `ops/tests/test_X.sh` → `ops/test_X.sh` 解析，名字對不上者查 `OPS_SHELL_TEST_ALIASES`，存在性一律以 worktree 為準；③ `ops-shell-untested`＝**具名**列出解析不到測試的腳本（warn）。**這條路由讓 `ops/tests/test_gate_can_fail.sh` 第一次有了自動觸發點**——改它就會跑它
- `**.yml` / `**.yaml` → `data-plane:<工具>`＝`DATA_PLANE_OWNERS` 宣告的 owner 工具（block）：`ops/ui_quality_plane.yml` → 它的 `validate` ＋ `ops/tests/test_ui_quality_plane.sh`；`docs/registry.yml` → `docs_lint.sh --registry`。無 owner 者由 `data-plane-unowned` **具名**列出（warn）。**這裡刻意沒有 `bash -n` 那種通用語法底線**——stdlib 沒有 YAML parser，而 orchestrator 是零依賴（bootstrap 悖論要求它在工具鏈之前就能跑），自己手刻一個會讓判決變成「我的 parser 的性質」而非檔案的性質。`NEUTRAL_RULES` 樹下的 yml（`promotion/`、`frozen/`）維持 neutral，不重新收編
- `docs/runbook/backlog/*.json`（**頂層**，kaizen ledger）→ `backlog-validate`＝`backlog.py validate`（block）＋`data-plane:ops/docs_lint.sh`＝`docs_lint.sh --registry`（block）。**兩道一起選是刻意的**：`validate` 只答「每筆 entry 合不合 schema」，答不出「generated view 還跟不跟得上 store」——而動 store 就會讓 view 過期，那是本 repo 今天最常踩的坑；只選前者會讓 store-only 的 diff 宣稱「每個檔都被路由了」而真正會壞的東西沒人看。**改 `ops/backlog.py` 本身也會選 `backlog-validate`**：只鍵在資料的話，檢查器可以改到讓整個 store 失效卻只跑自己的 fixture 就綠掉，下一個無關的 agent 動任何一筆 entry 就吃到不是他造成的紅（IMP-20260805-9a51e9 的 plan 正是這個形狀）。**只吃頂層**：`validate_store` 是非遞迴 glob，子目錄的檔案路由得到卻永遠讀不到，那是空洞過關。此前 `validate` 全 repo 零自動呼叫者（唯一提及是 `platform-steward.md` 的一句散文）。

先 `gate --plan-only --json` 可預覽選出的 gate 集合而不執行。**block 必修**（回去修再重跑 gate）；**warn 是 advisory**——不擋 cutover，處置權在你（driving agent），land 時會標「landed with warnings」。

**block 的 summary 若附上 `no green ever recorded for this gate on this machine`**：那不是判決，是提示——本機的 gate 歷史裡這道 gate 從未綠過。可能是你的改動真的壞了，也可能這道 gate 在這台機器上**結構性不可能過**（`ios-build-catalyst` 缺簽章憑證擋掉每一次 iOS cutover 兩個月，就是這個形狀）。**先花一分鐘確認它能不能過**（在乾淨的 base 上單獨跑那道 gate 的命令），再決定要修改動還是修 gate。**永遠不要因此繞過流程**——工具壞了就照鐵律 9 修工具並登記 backlog。iOS build/test 很耗時 → 背景執行、主線不阻塞（鐵律 5）。

`gate` 執行每個實際 child gate 時，進度只寫 stderr：`start` / `spawned` / 每 20 秒 `heartbeat` 都帶 phase、elapsed、PID、alive；child 正常 exit 時另寫 `done` + rc，stdout 保持單一 `kg.worktree.gate.v1` JSON。progress 絕不回顯 raw argv（避免 token/password 洩漏）；中斷會向上拋出並終止整個 isolated child process group，不能只殺直接 child 留下孫行程。操作者不得把 stdout/stderr 合併後再解析 JSON，也不得用靜默 `capture_output` 旁路這個 runner。

orchestrator 自己的 mutation / network subprocess 同樣不得旁路可見進度 runner；完整分類、輸出與保密契約以 `docs/reference/tech_index.md` 的 `ops/lib/streaming_command.py` 段落為正本。

**e. 非 block 才 cutover（離線落地本地 main）**：
```
<path>/ops/worktree_orchestrate.py cutover --worktree <path> --json          # dry-run 預覽
<path>/ops/worktree_orchestrate.py cutover --worktree <path> --commit --json # ff 本地 main
```
它**要求新鮮的非 block verdict**（verdict ∈ {pass, warn}、記錄的 HEAD == 當前 HEAD、**產出該判決的 orchestrator == 工作樹現在這份**、且**本地 `main` 的 tip 已被 worktree HEAD 包含**；stale/缺紀錄/block/換版本/落後 base 都會被拒）→ rebase 上本地 `main` → 在 primary 上 **`git merge --ff-only` 前進本地 main**（受 per-repo 鎖序列化）。**離線、不 push、不部署。** 護欄：primary 必須在 `main` 上且 **tracked-clean、無 merge/rebase 進行中**（ff 會更新 primary 工作區）——髒了會被拒，先 commit/撤離。`warn` 會 land 並標 `warnings: [<gate 名>]`。落地本地 main 已長期授權（不先問）。

**base 包含性這一條 dry-run 也會拒**（帶 `behind_commits` / `base_changed_files`），修法 `git -C <path> rebase main` 後**必須重跑 gate**。包含性通過時 rebase 是 no-op，所以**落地的 sha == 被 gate 的 sha**；這條等式在鎖內 rebase 之後、ff 之前**再驗一次**（payload `gated_sha` / `rebased_sha`）——包含性檢查在鎖外，別的 session 可能在那之間 cutover 前進了主幹，而 rebase 刻意是對**當下**主幹做的。此時 main 不會前進，工作樹已被 rebase，重跑 gate 即可。

**f. resolve — 清乾淨、登記閉環**：
```
ops/worktree_orchestrate.py resolve --worktree <path> --json          # dry-run 看計畫
ops/worktree_orchestrate.py resolve --worktree <path> --commit --json
# --branch 只在 git 已經不認得該路徑（admin entry 沒了）且 ledger 也查不到時才需要，
# 而且它不會放寬任何護欄：git 若對該路徑報出不同分支，帶 --branch 一律被拒。
```
（`resolve` 刻意用**主 repo** 那份，不比照 gate/cutover：它是拆除動作，會刪掉 `<path>` 本身，且不路由任何 gate。）

先定 **目標身分**：branch 一律取自 `git worktree list --porcelain`，**絕不**問 `rev-parse`——worktree 的 `.git` 一旦消失（`worktree remove` 會先刪它、再慢慢 rm 樹，中途被 timeout 砍就是這個狀態），git 的 repo discovery 會**往上走**找到 primary、回答 `main`，而 porcelain 仍誠實報出真分支＋`prunable`（IMP-20260806-1359bd：曾因此排出 `branch -D main` 與 `push origin --delete main`，只被 git 自己的拒絕擋下）。

再過 **landed-floor**（tree-diff 判分支是否已進本地 main）：**未 land 的分支拒絕拆除**（避免 cutover 前誤呼叫 resolve 而 force-discard 未落地工作），要強拆傳 `--force`。過了 floor = 登記簿 resolve→merged + `git worktree remove`（entry 若是 `prunable`，先跑帶 heartbeat 的 `rm -rf` 把樹清掉，`worktree remove` 才有辦法成功）+ `branch -D`（local，遠端若存在也刪）+ **刪該 worktree 的 gate-record cache**。清完真正零殘骸。**critical step 失敗即停**，不再往下跑刪分支（payload 帶 `aborted_after`）。

**被拒時看 `reason_code`，別讀散文**：`not-a-worktree` / `detached-head` / `ambiguous-ledger` = **EXIT_USAGE(64)**，你指錯路徑或該路徑需要 `--branch` 才有辦法指名；`protected-branch` / `primary-worktree` / `branch-contradicts-git` / `uncorroborated-branch` / `rm-target-unvetted` / `unsafe-step` = **EXIT_BLOCK(1)**，安全拒絕，改指令沒用，先確認你要拆的到底是哪一個 worktree。`--force` **只**降 landed-floor，**不**降任何身分護欄。**不要因為被拒就去跑 `git worktree prune`**：那會刪掉 admin entry＝該路徑唯一的 path→branch 復原資訊（也會連帶收掉其他 session 中斷 teardown 的 entry），之後只剩手打 `--branch`；正解是把 `--worktree` 指到對的路徑。`adopt` 也救不了這個狀態（它經 `--show-toplevel` 解析，對 `.git` 已消失的目錄會解到 primary 然後拒絕）。

**唯一刻意留下的檔案**：同目錄的 `.cache/worktree_gates/history.jsonl`（append-only gate 行為日誌，per-machine、gitignored、`resolve` 不刪，有測試釘住）。它是「這道 gate 曾經綠過嗎」的唯一資料來源——刪掉等於讓 never-green 偵測失憶。**別把它當殘骸清掉。**

### 5a. 隨手備份（sync，零生產副作用）
本地 main 累積 cutover 後、想把碼推出機器**只為備份**（不上生產）時：
```
ops/worktree_orchestrate.py sync --json           # dry-run
ops/worktree_orchestrate.py sync --commit --json  # 守護式 ff push 本地 main → origin/main
```
`sync` 走 **backup 平面**：把本地 main 鏡像到 **origin/main**，**reconciler 不看 main → 零生產副作用**，推幾次都無所謂。護欄同 deploy（primary 在 main、origin/main 為本地嚴格祖先、絕不 force），已同步則 noop。跟 `sync-main` 方向相反：`sync` 是 local→origin（備份推出）；`sync-main` 是 origin→local（追上 origin，剛 clone/felix 部署機用）。

### 5b. 要上生產才 deploy（release 平面，唯一碰生產）
本地 main 累積若干 cutover 後、**你決定要上生產**時：
```
ops/worktree_orchestrate.py deploy --json           # dry-run：看會推幾個 commit、是否觸發 rollout
ops/worktree_orchestrate.py deploy --commit --json  # ff push 本地 main → origin/prod
```
護欄：primary 在 `main` 上、**origin/prod** 是本地的**嚴格祖先**（乾淨 ff，**絕不 force-push**；origin/prod 分岔會拒並指向 sync-main/pull）；已同步則 noop。dry-run 會列出 range 內的 **backend 檔**——有 backend 變更 = felix reconciler（盯 origin/prod）會跑**生產 rollout**（健康 gate + auto-rollback，deploy 不重跑）；純非 backend = 只前進 origin/prod、不碰生產。**deploy 一律推整段 range，backend 偵測只是提示、不 gate push。** 發布是刻意動作——多個 cutover 可先攢著、一次 deploy 批次上線。版號發布走 `ops/release.sh release <backend|ios>`（backend bump→tag→deploy→等生產收斂；iOS bump→upload→tag，見 `docs/sop/release.md`）。

## 「需要 main」的任務路由

宣稱「這要在 main 上做」時先問：**要的是 main 的內容還是身分？** 內容 → fresh worktree（更乾淨）。真需要 primary 的只有三類，各有原語：

- **bootstrap 悖論**（primary checkout 過舊、連本工具鏈都沒有）→ 裸 `git worktree add -b <branch> <path> origin/main`（純 git 原語，不需任何 repo 工具）→ `cd <path>` → `ops/worktree_orchestrate.py adopt --intent "<why>"`（`--worktree` 預設 cwd）補登記 ledger，之後照常走 gate/cutover/resolve。
- **primary 落後 origin**（本地 main 反被 origin 超前——在本地為主模型下**不正常**，只發生在：剛 clone 的機器、或 felix 部署 clone 其 main 追 origin、或別台 push 了東西）→ `sync-main`（dry-run 預設）。護欄三綠才動：tracked-clean（untracked 不擋）＋ primary 在 main 上且無 merge/rebase 進行中 ＋ 嚴格落後 origin（ancestor check）。分岔的 main **絕不** auto-merge/rebase——refusal 指向 cutover。**注意方向**：sync-main 是 origin→本地（追上 origin）；日常開發機的本地 main 是超前 origin 的，sync-main 在那是 noop。
- **stop-the-world repo 手術**（history rewrite / aggressive gc / 共享 hooks·config）→ 先 `freeze on --reason "<surgery>"`：open/adopt/cutover/sync/sync-main/**deploy** 全拒（顯示 reason），resolve/sweep/preflight/gate 放行（排空用）。排空到 registry 零 active → 備份 refs → 執行手術 → 驗證 → `freeze off`。
- **primary 上的 tracked 檔實質修改**（做著做著冒出來的）→ 撤離：`git diff` 導出 patch → worktree 內 apply → cutover 落地 → primary `git checkout --` 還原。primary 只允許「可再生」變更，絕不在 local main commit。

## 並發協調（多 session 常態）

同倉多 session 並發是常態，refuse 是**協調事件、不是死路**——refuse 訊息本身就是行動指引（列髒檔、給選項），照它做，不要死等輪詢：

- **cutover 被 primary 髒態擋** → 髒檔多半是另一個 session（co-tenant）留的：用 session-mgmt MCP `list_sessions` 查同倉 running session → `send_message` 發協調請求（請其 commit 或說明佔用）。是自己的殘留就 commit 或撤到 worktree（見上方「需要 main」路由末條）。gate verdict 綁 worktree HEAD 仍有效——primary 乾淨後**直接重跑 cutover**，不必重跑 gate（髒 primary 不會讓本地 main 前進）。**但若這段期間別的 session cutover 了**（本地 main 前進），cutover 會改以 base 落後為由拒——那時**必須** `git -C <path> rebase main` 並**重跑 gate**，不能只重跑 cutover。
- **政策**：primary 上工作**早 commit、常 commit**；agent 對 primary 是**過境不常駐**——別讓 uncommitted 改動在 primary 過夜擋別人的 cutover。
- **協調信箱（被動通道，優先於 send_message）**：`<repo>/.cache/coordination/broadcast.md`（全員）與 `<repo>/.cache/coordination/<slug>.md`（點對點，slug=你的 worktree slug）。`.cache/` gitignored、不進版控。**讀時機**（每個節點順手 `cat`，無檔即略過）：open 後、gate 前、cutover 被 refuse 時、暫停/待命前。**寫**：對其他 session 的非急件協調（排程、讓路、注意事項）寫進對方 `<slug>.md` 或 broadcast，**送出即完成、不等回覆**；急件（要對方立刻停手）才用 `send_message`（每則會跳使用者確認框，host 硬閘、配置免不了——所以批次合併、能少則少）。過期訊息由寫入者自清（附日期，處理完即刪）。

## 硬邊界

- **cutover/sync 不碰生產；deploy 才碰生產（唯一）**：cutover 只前進**本地** main（免費、可逆、不碰網路）；`sync` 只把本地 main 鏡像到 **origin/main** 備份（reconciler 不看 main → 零生產副作用）。生產部署發生在 `deploy` 把本地 main 推 **origin/prod** 之後——felix reconciler（launchd `com.kg.reconcile`，90s tick，盯 origin/prod）偵測前進且有 `backend/**` 變更即部署 wordnexus.lol（compose rebuild + 健康 gate + auto-rollback）。**因此「上生產」= 你刻意跑 `deploy`（或 `release.sh release`），不是每次 cutover、也不是 sync。** deploy 前確保要發布的 backend 變更 gate 已真實反映風險；資料面操作（migration/DB）仍走 `devops` skill 與鐵律 7。deploy/`release` 全自動授權（2026-07-10），但它是**唯一碰生產**的動作，寧可 dry-run 先看 range。
- **不重造 gate**：`gate` 只路由到既有工具。要加可斷言的 gate → 改對應工具本身，不在 orchestrate 內判 pass/fail。
- **動 agent-facing surface**（本 CLI/skill 本身）→ 同 PR 同步 `docs/reference/tech_index.md` / `product_surface.md`（見根 CLAUDE.md「改 user/agent-facing 介面」）。
- 收尾照 `kg-receipt`：驗證輸出 + 交接點。工具摩擦記 tooling debt（鐵律 9）。

## 一眼流程圖
```
preflight ─▶ 讀地圖 ─▶ research? ──yes──▶ 直接做（不開 worktree）
                          │no
                          ▼
              phased 拆 phase ─▶ open(fork 本地 main) ─▶ [每 phase: 實作 + review N-1 + rebase 本地 main]
                          ─▶ gate(block?) ──yes──▶ 修
                                   │no（pass/warn）
                                   ▼
                    cutover(離線 ff 本地 main) ─▶ resolve(landed-floor→清乾淨)
                                   │
                          （攢數個 cutover）
                                   ├──▶ sync --commit(push origin/main = 備份, 零生產)
                                   ▼
                    deploy --commit(push origin/prod = 觸發生產部署)
```
