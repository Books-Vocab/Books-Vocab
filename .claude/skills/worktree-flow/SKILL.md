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

**c. 逐 phase 實作（phased 模式）**：在 worktree 內做第 N phase 時，**同步派 code review agent 審 N-1 phase**（鐵律 4 逐項 review，鐵律 5 所有 Agent 背景化）。每個 phase 收尾 commit。**每 phase 後 rebase 本地 main**（離線，讓分支貼著本地主幹、減少 cutover 衝突）：
```
git -C <path> rebase main
```

**d. 全 phase 完 → gate**（impact-based，顯式跑；.githooks 只 best-effort，不可依賴）：
```
ops/worktree_orchestrate.py gate --worktree <path> --json
```
它 diff `<path>` vs 本地 `main`，把改動路由到既有 gate 工具並彙總 `verdict`（block/warn/pass），把結果**記錄下來**（綁 worktree + HEAD sha）供 cutover 核對。impact→gate 對應：
- `ios/**` → `ios_ops.sh build` **＋** `build --catalyst`（sim 綠 ≠ Catalyst 綠）＋ `quality impact`（swift）＋ `test --unit`；**動到 UITest 檔**則另加 `test --ui --file <該 UITest 類> --dataset marketing_demo`（**只跑受影響的 UI 測試類，非全套**——全套當 block 會被 codebase 已知 UI flaky 誤擋每次 iOS cutover）
- design-system / tokens / 生成 CSS / `ios/**/Models|UIComponents/` → `verify_design_system.sh`
- `docs/**.md` → `docs_lint.sh --files` ＋ conflict-marker 掃描 ＋ `verified_against` 可達性
- `backend/**.py` → 只跑 diff 內的**目標測試檔**；純 src 改動無目標測試 = **warn advisory**（不跑全套，全套有已知 pre-existing 假失敗）
- `ops/**.py` → `uv run --no-project --python 3.13 --with pytest pytest`（沙箱 uv，不碰 backend/uv.lock；block）：改 `ops/tests/test_X.py` 跑該檔；改 src（含 `ops/lib/`）跑對應 `ops/tests/test_<basename>`。每個 target 都做存在性檢查（以 worktree 為準：同 diff 新增的測試看得到、已刪除的不會塞給 pytest），**解析不到既存測試 = 跑整個 `ops/tests/`**（sandbox-unsafe 測試須自帶 dep-guard skip，前例見 `test_demo_ios_spec_emitter.py`）。`ops/*.sh` 無 pytest 對應，不選 gate

先 `gate --plan-only --json` 可預覽選出的 gate 集合而不執行。**block 必修**（回去修再重跑 gate）；**warn 是 advisory**——不擋 cutover，處置權在你（driving agent），land 時會標「landed with warnings」。iOS build/test 很耗時 → 背景執行、主線不阻塞（鐵律 5）。

**e. 非 block 才 cutover（離線落地本地 main）**：
```
ops/worktree_orchestrate.py cutover --worktree <path> --json          # dry-run 預覽
ops/worktree_orchestrate.py cutover --worktree <path> --commit --json # ff 本地 main
```
它**要求新鮮的非 block verdict**（verdict ∈ {pass, warn} 且記錄的 HEAD == 當前 HEAD；stale/缺紀錄/block 會被拒）→ rebase 上本地 `main` → 在 primary 上 **`git merge --ff-only` 前進本地 main**（受 per-repo 鎖序列化）。**離線、不 push、不部署。** 護欄：primary 必須在 `main` 上且 **tracked-clean、無 merge/rebase 進行中**（ff 會更新 primary 工作區）——髒了會被拒，先 commit/撤離。`warn` 會 land 並標 `warnings: [<gate 名>]`。落地本地 main 已長期授權（不先問）。

**f. resolve — 清乾淨、登記閉環**：
```
ops/worktree_orchestrate.py resolve --worktree <path> --json          # dry-run 看計畫
ops/worktree_orchestrate.py resolve --worktree <path> --commit --json
```
先過 **landed-floor**（tree-diff 判分支是否已進本地 main）：**未 land 的分支拒絕拆除**（避免 cutover 前誤呼叫 resolve 而 force-discard 未落地工作），要強拆傳 `--force`。過了 floor = 登記簿 resolve→merged + `git worktree remove` + `branch -D`（local，遠端若存在也刪）+ **刪該 worktree 的 gate-record cache**。清完真正零殘骸。

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
護欄：primary 在 `main` 上、**origin/prod** 是本地的**嚴格祖先**（乾淨 ff，**絕不 force-push**；origin/prod 分岔會拒並指向 sync-main/pull）；已同步則 noop。dry-run 會列出 range 內的 **backend 檔**——有 backend 變更 = felix reconciler（盯 origin/prod）會跑**生產 rollout**（健康 gate + auto-rollback，deploy 不重跑）；純非 backend = 只前進 origin/prod、不碰生產。**deploy 一律推整段 range，backend 偵測只是提示、不 gate push。** 發布是刻意動作——多個 cutover 可先攢著、一次 deploy 批次上線。版號發布走 `ops/release.sh release <backend|ios>`（backend bump→tag→deploy；iOS bump→upload→tag，見 `docs/sop/release.md`）。

## 「需要 main」的任務路由

宣稱「這要在 main 上做」時先問：**要的是 main 的內容還是身分？** 內容 → fresh worktree（更乾淨）。真需要 primary 的只有三類，各有原語：

- **bootstrap 悖論**（primary checkout 過舊、連本工具鏈都沒有）→ 裸 `git worktree add -b <branch> <path> origin/main`（純 git 原語，不需任何 repo 工具）→ `cd <path>` → `ops/worktree_orchestrate.py adopt --intent "<why>"`（`--worktree` 預設 cwd）補登記 ledger，之後照常走 gate/cutover/resolve。
- **primary 落後 origin**（本地 main 反被 origin 超前——在本地為主模型下**不正常**，只發生在：剛 clone 的機器、或 felix 部署 clone 其 main 追 origin、或別台 push 了東西）→ `sync-main`（dry-run 預設）。護欄三綠才動：tracked-clean（untracked 不擋）＋ primary 在 main 上且無 merge/rebase 進行中 ＋ 嚴格落後 origin（ancestor check）。分岔的 main **絕不** auto-merge/rebase——refusal 指向 cutover。**注意方向**：sync-main 是 origin→本地（追上 origin）；日常開發機的本地 main 是超前 origin 的，sync-main 在那是 noop。
- **stop-the-world repo 手術**（history rewrite / aggressive gc / 共享 hooks·config）→ 先 `freeze on --reason "<surgery>"`：open/adopt/cutover/sync/sync-main/**deploy** 全拒（顯示 reason），resolve/sweep/preflight/gate 放行（排空用）。排空到 registry 零 active → 備份 refs → 執行手術 → 驗證 → `freeze off`。
- **primary 上的 tracked 檔實質修改**（做著做著冒出來的）→ 撤離：`git diff` 導出 patch → worktree 內 apply → cutover 落地 → primary `git checkout --` 還原。primary 只允許「可再生」變更，絕不在 local main commit。

## 並發協調（多 session 常態）

同倉多 session 並發是常態，refuse 是**協調事件、不是死路**——refuse 訊息本身就是行動指引（列髒檔、給選項），照它做，不要死等輪詢：

- **cutover 被 primary 髒態擋** → 髒檔多半是另一個 session（co-tenant）留的：用 session-mgmt MCP `list_sessions` 查同倉 running session → `send_message` 發協調請求（請其 commit 或說明佔用）。是自己的殘留就 commit 或撤到 worktree（見上方「需要 main」路由末條）。gate verdict 綁 worktree HEAD 仍有效——primary 乾淨後**直接重跑 cutover**，不必重跑 gate。
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
