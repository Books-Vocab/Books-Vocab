---
name: worktree-flow
description: "KG 的隔離工作樹與多 team delivery-loop。當使用者要求 Delivery Team、隔離工作樹、把一輪工作整合進本地 main，或發布上生產時觸發；Ticket Factory 的 add／verify／groom 只走 backlog lifecycle，不因產票載入本 skill。編排 ops/worktree_orchestrate.py 原語（preflight / open / adopt / gate / catchup / land / integrate / close-wave / cutover / resolve / sync / deploy / sync-main / freeze）串起 P1 健康判定、P2 登記簿與既有 gate；純 research/唯讀不開 worktree。child worker 預設 commit＋hand-back；Delivery Team 的 Integrator 在取得當下 develop＋backup 授權後，以 close-wave --commit --sync 完成 primary＋origin/main 閉環。三平面：cutover=develop、sync=backup、deploy=release。"
user-invocable: true
version: 2.1.1
---

# worktree-flow

把「使用者需求 → Ticket Factory 產票 → 多個 Delivery Team thread 各自 fan-out → Integrator 合併 → primary＋origin/main」串成可重入的 delivery-loop；單一 child 仍以 `commit + hand-back` 作為自己的停止點。逐步呼叫原語 `ops/worktree_orchestrate.py`（下稱 `orchestrate`）。它只**編排**：P1 `ops/lib/worktree_state.py`（純健康判定）、P2 `ops/worktree_registry.py`（誕生→解決登記簿 + 孤兒哨兵）、與既有 gate 工具。**絕不重造 gate 判斷**。

## Progressive disclosure boundary

角色視野與未知升級的唯一索引是 `docs/reference/agent_context.md`，不是本 skill 的全文。Ticket Factory
只需讀 lane／ticket 交接語意；Delivery Child 只需讀「預設停止點」與「批次交回狀態」；Delivery Team
Integrator 才按當下 wave 讀「批次整合」／`close-wave`／「並發協調」。Round 6–8 壓測與歷史量測只有
明示壓測或工具調查才載入。遇到未知先回到 authority index，不以讀完整 skill 取代 escalation。

## 預設停止點（授權邊界）

**永遠先假設同 repo 有多個 session 同時工作。** child worker 正常做到：局部驗證 → commit → `./ops/worktree_registry.py hand-back --json` → 回報 branch／worktree／HEAD，然後停止。這個 hand-back 是 Delivery Team 內部交回，不是整個 team 完成；Integrator 可同一 thread 維護一個 integration worktree，孩子陸續回來就用 `integrate --append` fan-in。child 不自行跑 `gate`、`cutover`、`resolve` 或 `sync`。

只有擁有整批視野的 Integrator 在當下取得使用者對 develop＋backup 的明示授權，才可越過 child 停止點：① 確認本輪預期 child 已 hand-back；② 以 `close-wave --commit --sync` 進行唯一 fresh Gate、cutover、resolve、anchor、validate 與 origin/main sync。若只有 develop 授權，使用 `close-wave --commit` 停在本地 primary；若沒有授權，整合樹也只准 `integrate ... --commit --no-gate` 後 hand-back。一般工作樹的 branch-local `catchup` 完成後必須重新 hand-back；有存活 integration state 的整合樹禁止 catchup。這是協調政策，不放寬任何工具護欄；一旦獲授權仍完整走 fresh Gate，不能拿 targeted test 代替 Gate。

`--commit` 只控制各命令的**主要落地動作**，不是「沒帶就整個命令零副作用」的通則；`--json` 也只改輸出。出生／登記簿生命週期動詞沒有 dry-run：orchestrator `open`／`adopt` 與 registry `register`／`hand-back`／`resolve` 呼叫即寫。另有三個必記例外：`gate` 除 `--plan-only` 外會執行檢查並寫 verdict／history／失敗 log；`freeze on|off` 直接建立／刪除鎖，只有 `freeze status` 唯讀；`preflight` 不論 `--commit` 都會 `git fetch --prune`，該旗標只控制 sweep clearance。`open --backlog`／`--next-backlog` 必須在建立 branch/path 前原子取得獨佔認領；`hand-back` 必須立即寫入與當下 branch tip 綁定的交回戳記。呼叫前以子命令 help 為準，不可從有無 `--commit` 推導純讀性。

## 可溝通的兩條 lane（命名 SoT）

這是平行能力 lane，不是上下級階層：

- **Ticket Factory（票務隊）**：一個 thread 依需求大量 `add`、必要時 `verify`、`groom`，產出高品質、可排序、可執行的 dispatch-ready tickets；它不修 code，也不是一票一 thread。
- **Delivery Team（交付隊）**：可同時開 A/B/C 多個 thread；每個 thread 從不重疊的 task batch 開始，由該 thread 的 **Integrator** 派出 N 個 child worktree，持續把 child commit fan-in 到一個 integration worktree，最後自己完成整個 delivery-loop。

三種方法固定命名：**ticketed-loop** = `Ticket Factory → dispatch → Delivery Team → primary + origin/main`；**delivery-loop** = 單一 Delivery Team thread 的 `batch → N child worktrees → incremental fan-in → fresh Gate → cutover → resolve → anchor/validate → sync`；**direct-fix** = 使用者明示「直接改、不登記」時，完成修改後停在 hand-back（除非另有整批落地授權）。鎖競爭是正常等待：核心工具以指數退避、stderr heartbeat、非競爭錯誤 fail-closed，team 不需要互相輪詢喊話。

`close-wave` 是每個 Delivery Team Integrator 的可重入入口：它把批次組裝、唯一 fresh Gate、cutover、來源／整合樹 resolve、anchor、validate 串成一條可恢復流程；同一 `--slug` 重跑即可續接。`--commit` 完成本地 primary 閉環，`--sync` 明確完成 origin/main backup；不 deploy。其他 team 的 active worktree 可以存在，但本輪只處理明示的 source branches，最後整段 primary＋remote 臨界區由 delivery-loop lock 序列化。

### 正常不用聊天；異常才傳訊

正常協作的通訊面是 backlog、worktree registry、integration state、Gate receipt 與 lock heartbeat；不要用 thread 訊息同步每個進度。只有不穩定情境（衝突、state 損壞或過期、同一 source/fix-site 競爭、primary race、工具輸出與預期 schema 不符）才由 Integrator 使用內建 `multi_agent_v1__send_input`，直接通知受影響的 peer thread。訊息至少帶 `team/slug`、branch、worktree path、HEAD、state path、具體 blocker 與證據、要求的動作、需 pause 還是可 continue；禁止盲目 busy-loop，通知後繼續不相衝的工作或按 lock 的指數退避等待。

## 拓樸：本地 main 為主幹（core mental model）

**本地 `main` 是主幹**，兩個 origin ref 是不同平面的目標。worktree 從**本地 main** 分出、cutover **離線 ff 本地 main**（不碰網路、不部署）。本地 main 因此會**超前 origin** 幾個到幾十個 commit——這是正常的，不是「腐爛」。三平面：

- **develop = `cutover`**：worktree → 本地 main，離線、免費、可逆。
- **backup = `sync`**：本地 main → **origin/main**（機外備份鏡像），**零生產副作用**——reconciler 不看 main；取得明示 backup 意圖後可重複執行。
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

### 4. 寫 code → 隔離工作樹開發到 commit + hand-back

**a. 拆 phase**：載入 `phased` skill，把任務切成可獨立 commit 的 phase plan。

**b. open**：
```
ops/worktree_orchestrate.py open --intent "<原始 intent 文字>" --slug <kebab-slug> [--backlog IMP-xxxx ...] --json
```
**先在 P2 登記簿登記（= 認領），成功才** 建 `.claude/worktrees/<slug>` 與分支 `<type>/<slug>`（type 由 intent 自動判定）。記下回傳的 `path`。

單一協調者可先用 `./ops/backlog.py dispatch` 再明示 `--backlog`。**兩個以上協調者同步取票時改用 `--next-backlog`**：工具在同一把本機 registry lock 內，以 backlog 的既有 dispatch predicate/worst-first 排序選第一張尚未認領的票並立即登記；兩邊會拿到不同票，不會都讀到同一份 top-N snapshot 再讓敗方整批重試。明示 `--backlog` 也不能繞過未解的 `blocked_by`；同 slug/path 的第二次 `open` 由 exclusive birth 拒絕，不會把第一個成功者當成 idempotent update。

需要先把多票分區、quota、structured write sites 與 blocked/co-land 關係一次凍結時，使用 `campaign-reserve --request-file <manifest.json> --commit --json`；它在 canonical registry lock 內重讀 primary base、backlog 與 active claims，驗證通過後才原子保存 campaign manifest 與 registry reservation。之後以 `open --next-backlog --campaign <campaign-id> --partition <partition-id>` 從該分區逐票轉移 reservation→active claim；普通 `open --next-backlog` 會排除尚未轉移的 reserved tickets。path/symbol/mode 不明或跨票 collision 預設 fail-closed，除非 request 具名 `blocked_by` 或相同 `co_land_group` 的序列化證據。

`dispatch`（＝`list --dispatch`）的集合是已梳理 ∧ 未解 ∧ 未被認領 ∧ 未被阻擋，worst-first。**不要用 `list` 挑票**——它含已結案、別人認領中的，或仍在等未結案前置票的。它仍有兩個範圍邊界：認領由**本機**登記簿推導（跨機時樂觀），看板的**延後不套用**。

**波次結案流程（hunter 全程不碰 store）**：修好後在自己的工作樹跑 `./ops/backlog.py stage <id> --verdict CONFIRMED-FIXED --by <你> --evidence '<你跑的命令>'（命令含反引號時用 `--evidence-file <路徑>`）`（無 `--status`，恆為 `fixed`）——寫進 gitignored 的 `<primary>/.cache/backlog_anchor_queue.jsonl`，**不碰 store**（理由是那顆 sha：rebase 前你不知道落地 sha，自己填就是 orphaned `fixed_by`；「不重生 view」那半個舊理由已隨 view 移出版控退場）。`cutover` 在**所有 post-ff refusal 之後**把真正的落地 sha 蓋上去（payload 的 `staged_closures`），波次結束開一條 worktree 跑 `./ops/backlog.py anchor --commit` 一次回填（全有或全無，未蓋 sha 的 row 會被具名保留而不是靜默套用；壞掉的 row 用 `./ops/backlog.py unstage <id> --commit` 取下，這是 all-or-nothing 的逃生口）。`resolve` 拆樹時會把這條分支還沒回填的結案**列出來但不擋**（payload 的 `pending_anchor`）——這是**正常狀態不是警告**（stage→cutover→resolve 本來就在 anchor 之前），列它是因為拆樹後那些 id 只剩 gitignored 檔裡一行；gate、docs lint 與任何讀 store 的入口都看不到它。

**在做 backlog 上的單就一定要帶 `--backlog`**：它把那幾張單認領給這條 worktree，另一個 active 記錄已持有其一即 **refuse（rc 非 0）**，payload 的 `conflicts` 指名持有者的 branch 與 path。搶輸時**不會留下分支也不會留下目錄**——認領在建任何東西之前發生。認領的壽命 = 記錄 active 的壽命，所以 `resolve` / `sweep` 自動釋放，**沒有另一個 release 動詞**。`worktree_registry.py list` 的 `backlog` / `claimed` 欄回答「誰在做哪張單、拿多久了」。

**c. 逐 phase 實作（phased 模式）**：在 worktree 內做第 N phase 時，**同步派 code review agent 審 N-1 phase**（鐵律 4 逐項 review，鐵律 5 所有 Agent 背景化）。每個 phase 收尾 commit。預設不因「可能稍後要 gate」而在每 phase 主動 rebase；那會讓平行 session 的主幹前進反覆改寫本分支。只有已取得本節授權、準備進 gate，或整合者明示要求追主幹時才執行：
```
<path>/ops/worktree_orchestrate.py catchup --worktree <path> --commit
```

**c2. trunk 動了 → catchup**（`gate` / `cutover` 拒絕並說「落後本地 main」時做這一步）：
```
<path>/ops/worktree_orchestrate.py catchup --worktree <path> --json          # dry-run：落後幾顆、動了哪些檔
<path>/ops/worktree_orchestrate.py catchup --worktree <path> --commit --json # rebase 上本地 main
```
它就是那句「你先 `git rebase main`」變成的命令，差別只有一個而且很要緊：rebase 會在
那個 generated 的 ledger view 上衝突（實測十條分支一輪 3–6 條中招）——**該檔已於 IMP-20260807-b9526c 移出版控**，所以這個衝突源今天不存在了，
而那個檔沒有「留哪一邊」的問題——它是 store 的純函數，正解是重跑 generator，所以 `catchup` 曾內建一個
「衝突集合恰好等於該檔就自動重生」的解析器。**該解析器已隨檔案一起移除**：今天 `catchup` 就是一次乾淨的
rebase，**任何**衝突都 abort 交你（那是真的決定），也不再有 `regenerated` 這個 payload 欄位。rebase 完 HEAD 就動了：已取得 develop 授權、準備落地者必須立即跑 fresh `gate`；授權前只有**一般且無存活 integration state** 的工作樹可為追主幹執行 catchup，完成後重新 `hand-back` 更新 SHA 並停止。整合樹走批次段的 abort／驗來源／teardown／重建，不能因 catchup 自動跨過停止點或破壞 state。

**c3. 已獲明示授權且多條獨立工作樹要落地 → 用 `land`，不要手動排 gate/cutover**：

> **適用範圍（先讀這句，不然會做反）**：`land` 不是一般 session 的預設收尾。只有使用者已明示
> 目前沒有其他 agent/session 工作並授權本 session gate + cutover 時，本段才適用。**同一批 fan-out 出去的受派者不適用**：那批的落地權在整合者，
> 受派者做到 commit 為止就停（見下方「批次交回狀態」，那段是契約正本）。兩者都叫「多條工作樹
> 同時在跑」，處置**相反**——搞混的代價不是效率而是正確性：各自 land 的批次拿不到「N 份放
> 一起還綠不綠」那個答案，而 2026-08-06 十一條分支的實測裡，整合後 review 找出的五筆 BLOCK
> 每一筆在自己分支的 gate 下都是綠的。
```
<path>/ops/worktree_orchestrate.py land --worktree <path> --json           # dry-run：目前排隊多深
<path>/ops/worktree_orchestrate.py land --worktree <path> --commit --json  # 取號 → catchup → gate → cutover
```
**這是取得落地授權後，多條獨立工作樹的序列化路徑；不是一般 session 的預設路徑。** 底下 d/e 那條手動序列在單獨一條工作樹時完全正確，但**多條同時跑會不收斂**：
本地 main 是唯一主幹、cutover 是線性 ff，所以任何一條落地就讓其餘全部變「落後」，而補救動作
（catchup → 重跑 gate → 再 cutover）本身也在同一場競賽裡。實測 throwaway clone 十條並行照 d/e 手動跑：
**只有 2/10 落地**，八條被 `behind main` 擋下（五條在 cutover、三條連 gate 都不給跑）；N=3 雖然 3/3 落地
但花了 6 次 gate。改用 `land`：**10/10 落地、恰好 10 次 gate**、primary 乾淨、`validate` 0 problems。

差別在臨界區的寬度。`cutover` 只把 ff 序列化，擋得住兩條互相踩，擋不住「我 gate 完的那一刻 trunk 已經動了」；
`land` 先取一個 **FIFO 名次**，再把 catchup → gate → cutover **整段**跑在那個名次裡，所以被 gate 的樹就是落地的樹，
一次就過。用 FIFO 而不是 flock，是因為 flock 不公平，而反覆輸掉競賽的必然是 gate 最慢的那條——混合批次裡就是 iOS。
`--queue-timeout` 量的是**佇列多久沒動**，不是你等了多久（等多久本來就該正比於前面幾條的 gate 時間）。
**注意 `land` 是 advisory**：它只在所有落地者都走它時才保證一次過；有人繞過去直接 `cutover --commit` 仍可能
在你 gate 到一半推進 trunk（安全不受影響——`cutover` 自己的不變式會擋下未經 gate 的樹——但你會多跑一輪）。

**`land` 取到名次後、進 gate 之前會先驗一次 primary tracked-clean**（IMP-20260808-636848），命中就直接 EXIT_BLOCK
並在 payload 標 `refused_before: "gate"`、列出 `dirty_files`。這條存在的理由是代價分佈：`cutover` 原本只在 ff 前驗，
所以「primary 髒」要等整輪 gate 跑完才發現——實測 574 秒的 gate 工作直接丟掉，而髒的來源是**整合者自己三秒前**寫進
primary 的 backlog 結案。**批次整合者的對策不是靠這條預檢，而是別讓 primary 變髒**：`backlog.py stage` 把結案停在
gitignored 的 anchor queue（不碰 store），整批 land 完再 `anchor` 一次回填。預檢只是把踩到時的代價從十分鐘降到毫秒。
（ff 前那次檢查仍在且**不可刪**：primary 可能在 gate 期間才變髒，兩次問的是不同時刻的問題。）

**d. 已取得本節明示授權後，全 phase 完 → gate**（impact-based，顯式跑；.githooks 只 best-effort，不可依賴）：
```
<path>/ops/worktree_orchestrate.py gate --worktree <path> --json
```
**`gate` / `cutover` 一律用工作樹自己那份 orchestrator（上面的絕對路徑形式），不是裸 `ops/...`。** 理由：gate 的**工具**是以工作樹為 cwd 執行的，所以**路由規則必須同代**——從主 repo 跑會用主 repo 的規則去排一組分支版工具的 gate（實測排出 8 道 vs 分支的 11 道，輸出形狀完全相同）。工具現在會自己擋，判決紀錄也帶 orchestrator 身分、cutover 會核對——但**它擋得很窄，別把它讀成「跑錯樹會有人喊」**：這道閘只在**分支真的改了這支工具本身**時觸發（三態語意與比對機制見 SoT `docs/reference/tech_index.md` 的 `worktree_orchestrate.py` 段）。所以它守的是「路由規則與工具同代」，**不是「你人在哪棵樹」**——後者今天沒有任何機器直接在守，見下方「硬邊界」第一條。正確形式仍是上面這行。

它 diff `<path>` vs 本地 `main`，把改動路由到既有 gate 工具並彙總 `verdict`（block/warn/pass），把結果**記錄下來**（綁 worktree + HEAD sha + base 包含性）供 cutover 核對。

同一工作樹追加變更時，gate 可在**輸入指紋仍一致**且新增 diff 不屬於該 gate 責任範圍時重用先前的
`pass/warn`；record 與 cutover payload 會列出 `reused_from_head`、輸入檔案集合、指紋與每道 gate
的 rerun 理由。這不放寬 fresh current-HEAD、base containment、orchestrator identity 或
`inconclusive` 護欄；未知 scope、輸入集合或內容變動、舊格式 record 一律重跑。看見 `reused` 不等於
「這顆 HEAD 沒驗」——它是同一組已量過輸入的結果重用，且仍由 current HEAD 的新 record 綁定。
其中 iOS 可執行 gate 的工具輸入依真實 delegate 分開：build/Catalyst 指向 build runner，
unit/UI/live-compile 指向 test runner；只修 test runner 時可重用已綠 build，共用 `ios_ops.sh` 或
共用 helper 變更則兩邊都失效。未具名的新 iOS gate 維持整個 iOS surface 的保守 scope，不猜依賴。

**開跑前先擋一道：分支落後本地 main 就直接拒**（EXIT_BLOCK，payload 帶 `behind_commits` / `base_changed_files`，**不寫任何判決紀錄**）。理由：cutover 的第一個動作就是 rebase 上本地 main，所以落後的樹被 gate 判過也不會是落地的那棵——判決會綁到一棵不存在的樹（IMP-20260806-945e01：實測 58 commits 落後的分支，main 上多出的 UITest 檔在工作樹裡根本不存在，`--grep` 選三個類靜默只匹配到兩個）。修法是 `catchup --commit`（見下方 c2），然後**重跑 gate**。`--plan-only` 不受此擋（它不跑也不記，是拒絕訊息指定的預覽出口）。impact→gate 對應：
- `ios/**` → `ios_ops.sh build` **＋** `build --catalyst`（sim 綠 ≠ Catalyst 綠）＋ `quality impact`（swift）＋ `test --unit`；**動到一般 UITest 檔**則另加 `test --ui --file <該 UITest 類> --dataset marketing_demo`（**只跑受影響的 UI 測試類，非全套**——全套當 block 會被 codebase 已知 UI flaky 誤擋每次 iOS cutover）。`LiveDemoAccessUITests` 是 Release＋實機＋live backend 專用契約，cutover gate 只跑 Release iphoneos build-for-testing 編譯 gate 並明示 runtime advisory；不得拿 simulator/fixture 偽裝其 runtime evidence，送審前仍須走 App Review `demo-run`。
- design-system / tokens / 生成 CSS / `ios/**/Models|UIComponents/` → `verify_design_system.sh`
- `docs/**.md` → `docs_lint.sh --files` ＋ conflict-marker 掃描 ＋ `verified_against` 可達性
- `backend/**.py` → 只跑 diff 內的**目標測試檔**；純 src 改動無目標測試 = **warn advisory**（不跑全套，全套有已知 pre-existing 假失敗）
- `ops/**.py` → `uv run --no-project --python 3.13 --with pytest pytest`（沙箱 uv，不碰 backend/uv.lock；block）：改 `ops/tests/test_X.py` 跑該檔；改 src（含 `ops/lib/`）跑對應 `ops/tests/test_<basename>`。每個 target 都做存在性檢查（以 worktree 為準：同 diff 新增的測試看得到、已刪除的不會塞給 pytest）；**若 worktree 有 `ops/tests/` 目錄但解析不到既存測試，跑整個 `ops/tests/`（block）**；若是 synthetic worktree 且沒有測試樹，改列具名 `ops-pytest-unavailable`（warn，不把缺少測試基礎設施誤判成變更失敗）。只要 diff 本身包含任何 `ops/tests/` 路徑，即使測試樹缺失也維持 fallback block，避免刪測試被降級。sandbox-unsafe 測試須自帶 dep-guard skip，前例見 `test_demo_ios_spec_emitter.py`）
- `**.sh`（**全 repo 減去 `SHELL_GATE_EXCLUDED_TREES`＝目前只有 `frozen/`**；IMP-0057 把範圍從「`ops/` ＋ repo root」放寬到這裡，因為 `ops/` 之外還有 12 支 tracked 腳本完全無路由，其中 `backend/view_logs.sh` 早就被 `ops/test_devops.sh` 測著——測試檔改動會觸發 gate、被測的那支不會，跟 IMP-0052 同形。`frozen/` 的排除是**具名**的，不是無聲的：冷凍快照掛上 gate 只會讓 ③ 的 advisory 永遠列著 7 個沒人打算補測試的檔，而長期有雜訊的 advisory 沒人看）→ 四層：① `ops-shell-syntax`＝對每個改動的腳本跑語法檢查（block，只需 shell 本身，沒有機器會靜默跳過——約 1/3 的 ops 腳本根本沒有自己的測試，這是它們唯一拿得到的檢查）。**直譯器讀 shebang 決定**（`bash`/`sh`/`zsh`），**沒有 shebang 一律當 bash**（6 支 `ops/lib/*.sh` 是 source 進來的、無 shebang，把「未知」當「跳過」會讓它們從有語法地板退化成沒有），**認不出的 shebang、或本機沒裝那個直譯器,則跳過並在 summary 具名**——拿 `bash -n` 打一支非 bash 腳本產生的假紅、或為了缺一個 `zsh` 而判紅（GitHub ubuntu runner 預設就沒有 zsh），都是拿機器的事實去說腳本的壞話，在 gate 眼中與真紅無從分辨。**若這次一支都沒真的檢查到（全部被跳過），這道 gate 回 `warn` 而非 `pass`**——它是 block 級 gate，顏色就是一種宣稱，而「我什麼都沒驗」不該與「全部通過」共用同一個顏色；不判 block 是因為缺直譯器不是這條分支的錯（同 `inconclusive` 的判斷）；② `ops-shell:<test>`＝該腳本自己的測試（block），依慣例 `ops/tests/test_X.sh` → `ops/test_X.sh` 解析，**慣例只在 `ops/` 與 repo root 適用**（那裡 basename 唯一；別處只認 `OPS_SHELL_TEST_ALIASES` 的具名條目，否則 `lab/podcast/start.sh` 會解析到 root `start.sh` 的候選，被判「覆蓋」而其實沒執行過它一行），名字對不上者查 `OPS_SHELL_TEST_ALIASES`，存在性一律以 worktree 為準；③ `ops-shell-untested`＝**具名**列出解析不到測試的腳本（warn）。**CI 觸發面要同步**：`.github/workflows/ops-suite.yml` 的 `paths` 只有 `ops/**` 一條有共同前綴，`ops/` 之外的 7 支(含 repo root 兩支)只能逐條列，由 `test_the_workflow_triggers_on_every_routed_script_outside_ops` 釘住——漏一條就重演 IMP-0052 的「cutover 看得到、CI 看不到」。**這條路由讓 `ops/tests/test_gate_can_fail.sh` 第一次有了自動觸發點**——改它就會跑它。④ `ops-shell-scan`＝**repo 級跨檔掃描**（block，入口 `ops/shell_scan.sh`，整 repo 掃一次、不做 per-file，與 `ops/tests/test_script_help.sh` 共用同一份實作）。前三層全是 per-file 的，所以一道「關於整棵樹」的檢查不屬於任何單一腳本，也就**沒有任何 diff 觸發得到它**——抓「`$VAR` 緊接**任何非 ASCII 字元**」那道守衛（2026-08-08 前只認十一個全形標點：，。、：；！？「」（），放寬成 byte class；漢字才是本 repo 最常見的形狀）自 2026-08-05（`48d877b91`）起就正確、帶正控、一跑就精準指出檔名行號，卻從未被 gate 執行過，直到 2026-08-08 讓 `devops.sh:669` 一路撐到 `land`（診斷約 30 分鐘，IMP-20260808-3bbfa2）。**缺口在 routing 不在守衛**，所以修法是路由＋一個共用入口，不是在 orchestrator 裡重造掃描
- `**.yml` / `**.yaml` → `data-plane:<工具>`＝`DATA_PLANE_OWNERS` 宣告的 owner 工具（block）：`ops/ui_quality_plane.yml` → 它的 `validate` ＋ `ops/tests/test_ui_quality_plane.sh`；`docs/registry.yml` → `docs_lint.sh --registry`。無 owner 者由 `data-plane-unowned` **具名**列出（warn）。**這裡刻意沒有 `bash -n` 那種通用語法底線**——stdlib 沒有 YAML parser，而 orchestrator 是零依賴（bootstrap 悖論要求它在工具鏈之前就能跑），自己手刻一個會讓判決變成「我的 parser 的性質」而非檔案的性質。`NEUTRAL_RULES` 樹下的 yml（`promotion/`、`frozen/`）維持 neutral，不重新收編
- `docs/runbook/backlog/*.json`（**頂層**，kaizen ledger）→ `backlog-validate`＝`backlog.py validate --baseline-check`（block；旗標是 ratchet 的執法點，不是可省的裝飾）＋`data-plane:ops/docs_lint.sh`＝`docs_lint.sh --registry`（block）。**兩道一起選當初是刻意的，但第二道今天答的已經不是原本那個問題**：它被加進來是因為 `validate` 答不出「generated view 還跟不跟得上 store」，而那道檢查是 registry 的 `check:`（→ `render --check`）在守。**該 registry entry 隨 view 移出版控一併刪除（IMP-20260807-b9526c），registry 現在 0 筆 `kind: generated`**，所以 `docs_lint.sh --registry` 今天只驗控制平面本身（44 份 doc 的 path/kind/generator 有效性），不再驗 view 新鮮度——view 已 gitignored，過期也不會有人吃紅。路由仍在（`ops/worktree_orchestrate.py:867`），但**選它的理由已經不成立**，`:874` 的註解還寫著那個不存在的 `check:`；這是待處置的 tooling debt，不要照舊理由複述。**改 `ops/backlog.py` 本身也會選 `backlog-validate`**：只鍵在資料的話，檢查器可以改到讓整個 store 失效卻只跑自己的 fixture 就綠掉，下一個無關的 agent 動任何一筆 entry 就吃到不是他造成的紅（IMP-20260805-9a51e9 的 plan 正是這個形狀）。**只吃頂層**：`validate_store` 是非遞迴 glob，子目錄的檔案路由得到卻永遠讀不到，那是空洞過關。此前 `validate` 全 repo 零自動呼叫者（唯一提及是 `platform-steward.md` 的一句散文）。

先 `gate --plan-only --json` 可預覽選出的 gate 集合而不執行。**block 必修**（回去修再重跑 gate）；**warn 是 advisory**——不擋 cutover，處置權在你（driving agent），land 時會標「landed with warnings」。

**第三種 status：`inconclusive`（渲染成 `~`，IMP-20260805-4ec901）**——那道 gate**真的紅了，但那個紅不歸這條分支**。linked worktree 與 primary **共用 `refs/`**（`git rev-parse --path-format=absolute --git-path refs/tags` 兩邊逐字元回同一個路徑，不是各自一份——省略 `--path-format=absolute` 的話 primary 回相對路徑、worktree 回絕對路徑，字串不同但指的是同一個檔），所以有人在 primary 跑 `release.sh` 建/刪 tag 時，正在這裡跑、且會讀 repo 全域 tag 狀態的 child（`ops/test_ios_ops.sh` 的 release/TestFlight 案例）就會以 rc=1 收場。實測 2026-08-05：批次 gate 中它回 371 passed / 1 failed，同一份輸入單獨重跑 371 全綠 exit 0——**紅綠是機器狀態的函數**，與 device-lock 那條同形。orchestrator 因此在每道 shell gate **前後各取一次 tag 快照**（綠的那條路徑不取第二次：綠不需要歸因），rc≠0 且快照有變就標 `inconclusive`：**rc 原封保留**，summary 開頭寫明變了幾個 tag。三件事跟著改變：① `aggregate_verdict` 把它折成 **warn**（折成 block 會為別人的 tag 手術殺掉你的工作，折成 pass 則是宣稱一個沒人證明過的東西）；② `land` 的 warnings 清單會列出它；③ **它不計入 never-green 連勝**——被污染的紅不是「這道 gate 從沒綠過」的證據。**`cutover` 會拒絕落地**直到你重跑那道 gate——因為 warn 是會落地的，只折成 warn 等於把「這個紅無從歸因」變成「附註後出貨」，那是解除武裝的方向；而觸發源不只 `release.sh`，任何併發 session 的 `preflight`/`catchup`/`sync`/`deploy` 都會跑 `git fetch --prune` 帶進 origin 的新 tag。**你該做的**：等 tag 手術結束後重跑那道 gate，不要當成自己的 bug 去追。快照讀不到時（非 repo / git 失敗）一律當**未量測**而非「全部 tag 被刪」，所以壞掉的探針只會讓機制沉默，不會把誠實的紅洗成 inconclusive。

**block 的 summary 怎麼讀**（IMP-20260808-c47253）：失敗**shell** gate 的 `summary` 依序是 `exit <rc>` → **含失敗標記的行**（`✗` U+2717 / **`✘` U+2718**（Swift Testing 用這個，與前者幾乎同形）/ `FAIL` / `AssertionError` / `not ok` / `error:` / **`[review][block]`**，至多 20 行）→ 尾巴 → `full output: <path>`。**先讀那幾行具名失敗行，再決定要不要開 log**；抽不到任何標記時會明說 `no failure-marked lines found`，**而且尾巴的標題會改成 `tail (NOT failure lines — …)`**——那代表這道 gate 印的東西不帶任何已知標記，**底下那幾行只是 log 的最後幾行，可能是通過的行，不要當證據讀**，此時直接開 log。（2026-08-09 前兩個分支共用素標題 `tail:`，於是 `review-receipts` 紅燈時把 `[review][ok]` 顯示在證據欄位裡，實測害一個 session 誤判成假紅：IMP-20260808-8b4690。）log 落在 `<anchor>/.cache/worktree_gates/<key>.<gate>.log`，**每次跑該 gate 前先刪、綠了就不留、`resolve` 一併清**，所以你看到的一定是這次的。在此之前 summary 只有尾巴——實測一次 block 的 summary 全長 94 字元，失敗斷言的名字在被截掉的上面幾十行，於是唯一能做的是重跑並祈禱重現。**不要再靠重跑取得失敗名字。**
（internal gate——`ops-shell-syntax` / `docs-conflict-markers` / `docs-verified-against` / `coverage`——在 Python 內自組具名 summary，沒有 log 指標，那是對的，不是漏掉。）

**block 的 summary 若附上 `no green ever recorded for this gate on this machine`**：那不是判決，是提示——本機的 gate 歷史裡這道 gate 從未綠過。可能是你的改動真的壞了，也可能這道 gate 在這台機器上**結構性不可能過**（`ios-build-catalyst` 缺簽章憑證擋掉每一次 iOS cutover 兩個月，就是這個形狀）。**先花一分鐘確認它能不能過**（在乾淨的 base 上單獨跑那道 gate 的命令），再決定要修改動還是修 gate。**永遠不要因此繞過流程**——工具壞了就照鐵律 9 修工具並登記 backlog。iOS build/test 很耗時 → 背景執行、主線不阻塞（鐵律 5）。

**Gate 的機器 review 證據**：每道實際 gate 的 record 與 `history.jsonl` 都帶 `machine_state`，包含判決前後的 load average、active worktree 數、以及偵測到的 `xcodebuild` / `ios_test.sh`（只記 PID＋類型，不留 raw argv）。對 `ios-test-unit`、`ops-shell:test_ios_test_discovery.sh`、`ops-ci-coverage` 這三類敏感 gate，若判紅時確實觀測到同機 iOS 工具鏈行程，summary 會明說「可能不可重現」、列出污染行程，並給出安靜狀態的完整重跑命令；**仍維持紅燈，絕不自動 retry**。這是歸因證據，不是把紅降成綠，也不是重跑替代根因分析。

`gate` 執行每個實際 child gate 時，進度只寫 stderr：`start` / `spawned` / 每 20 秒 `heartbeat`；child 正常 exit 時另寫 `done` + rc，stdout 保持單一 `kg.worktree.gate.v1` JSON。**`heartbeat` 不只證明 gate 還活著，也證明它在不在前進**——安靜的 child 會自己招認（`stalled` 及其餘欄位語意見下段正本）。progress 絕不回顯 raw argv（避免 token/password 洩漏）；中斷會向上拋出並終止整個 isolated child process group，不能只殺直接 child 留下孫行程。操作者不得把 stdout/stderr 合併後再解析 JSON，也不得用靜默 `capture_output` 旁路這個 runner。

**gate child 的 `LC_CTYPE` 是工具選定的 `C.UTF-8`，不是繼承你的 shell**（IMP-20260808-3bbfa2；`phase=start` 行尾
的 `lcCtype=` 就是那個值）。所以**「我手跑是綠的」不構成 gate 誤判的證據**——互動 shell 這裡 `LC_CTYPE` 未設（C locale，
bash 逐 byte 判字元），gate 走的是嚴格的 UTF-8 解析路徑，`$VAR` 緊接**任何非 ASCII 字元**在前者無害、在後者是
`set -u` 致死。**不限全形標點——漢字最常見**（`$sha中文`），em-dash / 刪節號 / `é` / emoji / NBSP 同樣致死；
bash 判的是「下一個 byte 是否 ≥ 0x80」。守衛是 `ops/shell_scan.sh`（cutover 的 `ops-shell-scan`，block）。
要在手上重現 gate 的環境：`env -u LC_ALL LC_CTYPE=C.UTF-8 <你的命令>`。

**推論**：gate 紅而你手跑綠時，**「假紅」不是預設解釋**。2026-08-08 round2 批次實測——三道 BLOCK 全部
確定性可重現、零道與機器忙碌有關。要分辨的是兩類真原因，**不是先在它們之間排序**：① **locale**（本段
上方；症狀是手跑綠、gate 紅，且改換 `LC_CTYPE=C.UTF-8` 手跑就重現）；② **機器狀態污染**（同倉另一個
session 動了 refs／裝置鎖被佔），那類已經有專屬判定 `inconclusive`，見上方該段——它會自己說出來，不必
你猜。兩者都不是「重跑看看」。

**而「假紅」這個解釋之所以特別危險，是因為它同時（a）不需要改任何碼、（b）建議的下一步剛好是最省事的
「重跑」。任何同時滿足這兩點的解釋，要先當嫌疑犯而不是先當答案。** 本輪的實例：`test_ios_test_discovery`
63 條裡紅 2 條，我手跑 63/63 全綠並已寫下「假紅」——救回來的不是紀律，是一個不對稱：同一個 assert 區塊
裡**前面**兩條綠、**後面**兩條紅。在「假紅」假設下說不通，順著問才發現腳本是在兩者之間 `set -u` 當場死。

orchestrator 自己的 mutation / network subprocess 同樣不得旁路可見進度 runner；完整分類、輸出與保密契約以 `docs/reference/tech_index.md` 的 `ops/lib/streaming_command.py` 段落為正本。

**e. 已取得本節明示授權且非 block，才 cutover（離線落地本地 main）**：
```
<path>/ops/worktree_orchestrate.py cutover --worktree <path> --json          # dry-run 預覽
<path>/ops/worktree_orchestrate.py cutover --worktree <path> --commit --json # ff 本地 main
```
它**要求新鮮的非 block verdict**（verdict ∈ {pass, warn}、記錄的 HEAD == 當前 HEAD、**產出該判決的 orchestrator == 工作樹現在這份**、且**本地 `main` 的 tip 已被 worktree HEAD 包含**；stale/缺紀錄/block/換版本/落後 base 都會被拒）→ rebase 上本地 `main` → 在 primary 上 **`git merge --ff-only` 前進本地 main**（受 per-repo 鎖序列化）。**離線、不 push、不部署。** ff 完成後、**同一把鎖內**還會跑一次 post-landing repair（今天只剩 `backlog.py reanchor --commit` 一步；原本其後接的 `render --commit` → `validate --baseline-check` 隨那份 generated view 移出版控而移除）：cutover 的 rebase 在 gate **之後**改寫了分支 sha，ledger entry 的 `fixed_by` 要到落地那一刻才指得到正確的 commit。有改動它就自己 commit 一顆（`Review-Exempt: machine-repair`，`review_audit.sh` 會檢查這顆只碰 ledger）。**所以本地 main 的 tip 可能不是 payload 的 `sha`**——那顆在 `trunk_tip`；repair 的結果在 `repair`（`ok` / `committed` / `restored` / `steps`），失敗會把 `docs/runbook` 還原回 HEAD 再回報，不留髒 primary。護欄：primary 必須在 `main` 上且 **tracked-clean、無 merge/rebase 進行中**（ff 會更新 primary 工作區）——髒了會被拒，先 commit/撤離。`warn` 會 land 並標 `warnings: [<gate 名>]`。**能做不等於已授權做**：沒有「目前只有本 session」加「直接 gate + cutover」的當下明示，就回到本節頂端的 hand-back 停止點。

**base 包含性這一條 dry-run 也會拒**（帶 `behind_commits` / `base_changed_files`），修法 `catchup --commit`（見 c2）後**必須重跑 gate**。包含性通過時 rebase 是 no-op，所以**落地的 sha == 被 gate 的 sha**；這條等式在鎖內 rebase 之後、ff 之前**再驗一次**（payload `gated_sha` / `rebased_sha`）——包含性檢查在鎖外，別的 session 可能在那之間 cutover 前進了主幹，而 rebase 刻意是對**當下**主幹做的。此時 main 不會前進，工作樹已被 rebase，重跑 gate 即可。

**f. resolve — 清乾淨、登記閉環**：
```
ops/worktree_orchestrate.py resolve --worktree <path> --json          # dry-run 看計畫
ops/worktree_orchestrate.py resolve --worktree <path> --commit --json
# --branch 只在 git 已經不認得該路徑（admin entry 沒了）且 ledger 也查不到時才需要，
# 而且它不會放寬任何護欄：git 若對該路徑報出不同分支，帶 --branch 一律被拒。
```
（`resolve` 刻意用**主 repo** 那份，不比照 gate/cutover：它是拆除動作，會刪掉 `<path>` 本身，且不路由任何 gate。）

先定 **目標身分**：branch 一律取自 `git worktree list --porcelain`，**絕不**問 `rev-parse`——worktree 的 `.git` 一旦消失（`worktree remove` 會先刪它、再慢慢 rm 樹，中途被 timeout 砍就是這個狀態），git 的 repo discovery 會**往上走**找到 primary、回答 `main`，而 porcelain 仍誠實報出真分支＋`prunable`（IMP-20260806-1359bd：曾因此排出 `branch -D main` 與 `push origin --delete main`，只被 git 自己的拒絕擋下）。

再過 **landed-floor**（tree-diff 判分支是否已進本地 main）：**未 land 的分支拒絕拆除**（避免 cutover 前誤呼叫 resolve 而 force-discard 未落地工作），要強拆傳 `--force`。過了 floor = 登記簿 resolve→merged + `git worktree remove`（entry 若是 `prunable`，先跑帶 heartbeat 的 `rm -rf` 把樹清掉，`worktree remove` 才有辦法成功）+ `branch -D`（local，遠端若存在也刪）+ **刪該 worktree 的 gate-record cache 與同目錄的失敗 gate 輸出 log**（`<key>.<gate>.log`，payload 回 `gate_logs_removed`）。清完真正零殘骸。**critical step 失敗即停**，不再往下跑刪分支（payload 帶 `aborted_after`）。

**被拒時看 `reason_code`，別讀散文**：`not-a-worktree` / `detached-head` / `ambiguous-ledger` = **EXIT_USAGE(64)**，你指錯路徑或該路徑需要 `--branch` 才有辦法指名；`protected-branch` / `primary-worktree` / `branch-contradicts-git` / `uncorroborated-branch` / `rm-target-unvetted` / `unsafe-step` = **EXIT_BLOCK(1)**，安全拒絕，改指令沒用，先確認你要拆的到底是哪一個 worktree。`--force` **只**降 landed-floor，**不**降任何身分護欄。**不要因為被拒就去跑 `git worktree prune`**：那會刪掉 admin entry＝該路徑唯一的 path→branch 復原資訊（也會連帶收掉其他 session 中斷 teardown 的 entry），之後只剩手打 `--branch`；正解是把 `--worktree` 指到對的路徑。`adopt` 也救不了這個狀態（它經 `--show-toplevel` 解析，對 `.git` 已消失的目錄會解到 primary 然後拒絕）。

**唯一刻意留下的檔案**：同目錄的 `.cache/worktree_gates/history.jsonl`（append-only gate 行為日誌，per-machine、gitignored、`resolve` 不刪，有測試釘住）。它是「這道 gate 曾經綠過嗎」的唯一資料來源——刪掉等於讓 never-green 偵測失憶。**別把它當殘骸清掉。**

### 5a. 隨手備份（sync，零生產副作用）
本地 main 累積 cutover 後、想把碼推出機器**只為備份**（不上生產）時：
```
ops/worktree_orchestrate.py sync --json           # dry-run
ops/worktree_orchestrate.py sync --commit --json  # 守護式 ff push 本地 main → origin/main
```
`sync` 走 **backup 平面**：把本地 main 鏡像到 **origin/main**，**reconciler 不看 main → 零生產副作用**；只有取得明示 backup 意圖後才可執行，屆時可安全重複，已同步則 noop。護欄同 deploy（primary 在 main、origin/main 為本地嚴格祖先、絕不 force）。跟 `sync-main` 方向相反：`sync` 是 local→origin（備份推出）；`sync-main` 是 origin→local（追上 origin，剛 clone/felix 部署機用）。

### 5b. 要上生產才 deploy（release 平面，唯一碰生產）
本地 main 累積若干 cutover 後、**你決定要上生產**時：
```
ops/worktree_orchestrate.py deploy --json           # dry-run：看會推幾個 commit、是否觸發 rollout
ops/worktree_orchestrate.py deploy --commit --json  # ff push 本地 main → origin/prod
```
護欄：primary 在 `main` 上、**origin/prod** 是本地的**嚴格祖先**（乾淨 ff，**絕不 force-push**；origin/prod 分岔會拒並指向 sync-main/pull）；已同步則 noop。dry-run 會列出 range 內的 **backend 檔**——有 backend 變更 = felix reconciler（盯 origin/prod）會跑**生產 rollout**（健康 gate + auto-rollback，deploy 不重跑）；純非 backend = 只前進 origin/prod、不碰生產。**deploy 一律推整段 range，backend 偵測只是提示、不 gate push。** 發布是刻意動作——多個 cutover 可先攢著、一次 deploy 批次上線。版號發布走 `ops/release.sh release <backend|ios>`（backend bump→tag→deploy→等生產收斂；iOS bump→upload→tag，見 `docs/sop/release.md`）。

## 「需要 main」的任務路由

宣稱「這要在 main 上做」時先問：**要的是 main 的內容還是身分？** 內容 → fresh worktree（更乾淨）。真需要 primary 的只有三類，各有原語：

- **bootstrap 悖論**（primary checkout 過舊、連本工具鏈都沒有）→ 裸 `git worktree add -b <branch> <path> origin/main`（純 git 原語，不需任何 repo 工具）→ `cd <path>` → `ops/worktree_orchestrate.py adopt --intent "<why>"`（`--worktree` 預設 cwd）補登記 ledger，之後回到本 skill 頂端的授權邊界。
- **primary 落後 origin**（本地 main 反被 origin 超前——在本地為主模型下**不正常**，只發生在：剛 clone 的機器、或 felix 部署 clone 其 main 追 origin、或別台 push 了東西）→ `sync-main`（dry-run 預設）。護欄三綠才動：tracked-clean（untracked 不擋）＋ primary 在 main 上且無 merge/rebase 進行中 ＋ 嚴格落後 origin（ancestor check）。分岔的 main **絕不** auto-merge/rebase——refusal 指向 cutover。**注意方向**：sync-main 是 origin→本地（追上 origin）；日常開發機的本地 main 是超前 origin 的，sync-main 在那是 noop。
- **stop-the-world repo 手術**（history rewrite / aggressive gc / 共享 hooks·config）→ 先 `freeze on --reason "<surgery>"`：open/adopt/catchup/**integrate**/**close-wave**/land/cutover/sync/sync-main/**deploy** 全拒（顯示 reason），resolve/sweep/preflight/gate 放行（排空用）。排空到 registry 零 active → 備份 refs → 執行手術 → 驗證 → `freeze off`。
- **primary 上的 tracked 檔實質修改**（做著做著冒出來的）→ 撤離：`git diff` 導出 patch → worktree 內 apply → commit + hand-back → primary `git checkout --` 還原；之後仍回到頂端授權邊界。primary 只允許「可再生」變更，絕不在 local main commit。

## 批次整合（每個 Delivery Team thread：N 個工作樹 → 一次完整閉環）

單線 develop 流程（open→gate→cutover→resolve）是為**一條 child 分支**寫的；真正的 team 單位是
一個 Delivery Team thread，不是一張 ticket。Integrator 從一個不重疊的 task batch 出發，fan-out N 個
child worktree，孩子回來就可用 `integrate --append` 追加到同一 integration round；等預期 child 都回來後，
由 Integrator 以 `close-wave --commit --sync` 完成唯一 fresh Gate、primary cutover 與 remote sync。
不要讓 child 各自 gate+cutover，也不要把 hand-back 誤當整個 team 的完成。

### 批次交回狀態（本段是契約正本）

**所有 session 的預設上行交回狀態都是「在自己的工作樹裡 commit 完」，不是「已經進 main」；批次受派者更無例外。**
`gate`／`cutover` 屬於**取得使用者 develop 授權的 Delivery Team Integrator**——握有整批視野的那個
thread；`sync` 屬於取得 backup 授權的同一個 delivery-loop 收尾。task brief 的「邊界」一欄要寫明
child 只交回 commit＋hand-back，並要求回報分支名與工作樹路徑。單一受派者、單一工作樹、非批次任務
仍停在 commit + hand-back；只有 Team Integrator 才能把整輪送進 primary＋origin/main。
**因此受派者不跑 `land`**——`land` 內含 cutover。上方 c3 的佇列是給彼此獨立的 session 的，不是給同一批 fan-out 的；派工單的「邊界」一欄要把這句寫進去，因為 c3 讀起來很像在鼓勵每條各自落地。
受派 child 建樹時帶 `open --delegated`（或對既有樹用 `adopt --delegated`）把這個邊界寫進 ledger；`cutover`／`land` 對仍標記為 delegated 的工作樹會在 gate/verdict 之前以 `refusal=delegated` fail closed。只有整合者明確解除標記後才可落地；省略旗標在 register/adopt 時保留既有標記。

**每棵工作樹都有自己的暫存面。** `open` 會建立並回傳
`<worktree>/.cache/agent-scratch/`（JSON 欄位 `scratch_dir`）；`.cache/` 已被 Git 忽略，
Gate 與 commit 不會把它當成程式碼。受派者的暫存檔一律寫進自己回傳的 `scratch_dir`，檔名仍要帶
用途與必要的唯一尾碼；不要在 session 共用目錄使用 `red.log`、`out.json`、`gate.err` 這類裸檔名。
`resolve` 拆除工作樹時會一併清掉該目錄；若 scratch 無法建立或不是 gitignored，`open` 會 fail closed。

**交回前還要留下機器可讀的 hand-back 戳記。** 受派者在自己的工作樹完成最後一顆 commit 後執行：

```
./ops/worktree_registry.py hand-back --json
```

它會把 `handed_back_at` / `handed_back_sha` 寫入該工作樹的 active 登記；child 不跑 gate、cutover、sync 或 deploy。具名批次可另以 `--outcomes <json>` 交回每張 claimed ticket 的結果（`changed`、`no-op-existing-fix`、`changed-but-not-closable`、`blocked`、`triage-only`），工具會要求 acceptance status/evidence、驗證 ticket set，並對可整合結果產生含 identity/base/tip/digest 的 hand-back seal；changed 結果還須通過 review audit。Integrator 的 `integrate` 在 dry-run 與 commit 兩種模式都會檢查每條來源分支：沒有 active hand-back 戳記或 seal 就拒絕，戳記後 branch tip 改變也拒絕，並列出兩顆 SHA。`--allow-unhanded` 只供 legacy/imported branch 明確繞過缺 seal，不能繞過 tip mismatch 或不合法 seal；正常批次不應使用。

Campaign child 若交回的是一輪子整合，必須再以 `--campaign <id> --partition <id> --role child --manifest <completed.json>` 將 completed integration manifest 投影成不可變 child receipt；manifest head 必須等於 hand-back tip，且 campaign digest、partition ticket set、typed outcome seal 全部存在。父整合使用 `integrate --campaign <id> --parent`（不可同時給 `--branches`），會在建立 worktree 前以 registry lock 保留唯一 parent owner，對帳所有 expected partitions 後才自動生成 source queue；缺 child、重複 partition/branch/ticket、foreign campaign/source、stale tip、digest 漂移、seal 與 receipt outcome 不一致均 fail-closed，失敗不得留下 parent claim。完成 manifest 保留每票 source/child/parent SHA 與 outcome、acceptance、closure；`--abort --commit` 只釋放 parent reservation，不刪 child receipt。

`integrate --commit` 另會把每條有 hand-back 的來源在 registry 內**原子保留給該 integration branch**；另一輪若重複納入同一來源，會具名列出 owner 並拒絕，敗方剛開的空整合樹會自清。`--abort --commit` 釋放保留；正常完成後保留持續到來源分支被 resolve。只要來源仍 active，連 `--force` 都不能先刪 integration tree，避免先抹掉唯一的來源→整合 owner 邊。

Integrator 若有 child 在初始組裝後才 hand-back，可在同一個仍未 Gate 的 round 執行：

```
ops/worktree_orchestrate.py integrate --slug <wave> --append \
  --branches <late-child> --commit --json
```

`--append` 只追加已 hand-back 且尚未被其他 round 保留的 source，永遠不偷跑 Gate；最後由同一 slug
進 `close-wave`。若 Gate 已開始，late child 不可偷偷塞入已驗證結果，應保留為下一輪或在不穩定情況用
thread message 通知 Integrator／peer，不能改寫既有 state。

**Gate-first review 與批次規模（有界，不追求完美）**：Gate 是預設的機器 review。普通 fan-out 的受派者做到 commit；只有取得 develop 授權、握有整批視野的整合者，才在合併後跑一次 fresh Gate。Gate BLOCK 就退回修正，Gate 通過且 receipt 完整即可落地，不因文字或風格 NIT 無限追加 LLM reviewer。LLM review 只對高風險或複雜 scope 作例外；同一個完整 `commit SHA × scope` 最多兩輪，第二輪仍 BLOCK 就停在 adjudication，由 driving agent 決定修、接受或列 follow-up，不自動派第三輪。

若例外情況確實需要同時派 LLM reviewer，批次大小用當下量到的 slot 上限推導，不背魔術數字：令 `S`=可同時存活的 agent slot、`R`=保留給協調/收尾的安全餘裕、`W`=受派者、`L`=同時 reviewer，必須滿足 `W + L ≤ S − R`；若每位受派者各佔一位 reviewer，則 `W ≤ floor((S − R) / 2)`。本機實測 `S=20`，取 `R=2` 時理論上限為 9，實務預設收在 **8**；若不派 LLM reviewer，則不套用除以二，仍按衝突面與整合成本決定批次。撞頂時不得重試或用 `Reviewed-by: self` 偽造已審；具名記錄「LLM review 未取得」，由整合後 fresh Gate 承擔機器 review，複雜 scope 再由 driving agent 做一次有界裁決。

理由不是階級，是資訊：

- **合併後的 gate 才回答得了該問的問題。** 每個受派者各自 gate，證明的是「我的改動在我 fork
  出去的那個舊 main 上是綠的」。要問的是「N 份放在一起還綠不綠」，而那個問題在它們合併之前
  **無法提出**。N 次隔離 gate 的資訊量因此少於一次合併後 gate。
- **順序與衝突是全域決定。** 哪個順序衝突最少、共用檔（如 `docs/reference/tech_index.md`）的
  衝突該怎麼解，需要同時看到全部 N 份 diff。受派者結構上看不到，不是它不夠盡責。
- **同一個衝突只能解一次。** 同一張表被 N 條分支各自對著移動中的 main 解一次，會得到 N 個
  互相矛盾的解法，而每一個在它自己的分支上都看起來對。
- **verdict 綁 HEAD。** N 個受派者輪流 cutover，前一個 ff 掉 main、後一個就得 rebase、
  verdict 立刻 stale 要重跑；第 N 個要重 gate N-1 次。（`land` 動詞把這件事變成公平佇列而非
  重跑風暴——見 c3——但它解的是「排隊」，不是「合併後才看得見的缺陷」。）
- **自己批改自己的作業。** 讓寫碼的同一個節點決定它通過並推進共享 main，是鐵律4（逐項 review、
  不批次）與 `docs/sop/review_discipline.md` 的範圍。**不是鐵律2**——鐵律2 要的是「宣稱前有當下
  驗證輸出」，不管那份輸出誰產生。

**實證（2026-08-06，11 條分支的批次；修補落在 `339918579` `375f51707` `1954a9b2d`
`809b451d9` `4612626e1` `7bdb4b98e`，gate 修復落在 `2c5efa1d4`）**：整合後對六筆修補派 review，
找出**五筆 BLOCK**——而每一筆在它自己的分支 gate 下都是綠的。若各自 cutover，五筆全部會進 main。
同一批還有一個只有整合者看得到的形狀：`script-help` 的七個違規裡，三個是 main 上既有、三個由
某條分支帶入、一個由某次 review 修補帶入——沒有任何單一受派者看得到這個分布。

流程：

1. **`integrate` 在授權前只做組裝**（開整合樹 → 依序 cherry-pick → 衝突具名停）；因為不帶 `--no-gate` 的 `integrate --commit` 會直接跑 Gate，尚有其他 session 或尚未取得頂端雙重明示授權時，一律明寫 `--no-gate`：
```
ops/worktree_orchestrate.py integrate --slug integrate-<batch> --branches <b1> <b2> … --json
#   ↑ dry-run：逐顆列出每條分支會被 pick 的 commit，什麼都不建
ops/worktree_orchestrate.py integrate --slug integrate-<batch> --branches <b1> <b2> … --commit --no-gate --json
```
   需要盤點已暫停的整合時，使用獨立的唯讀投影，不要直接讀暫存 JSON 或猜下一步：
```
ops/worktree_orchestrate.py integrate --slug integrate-<batch> --status --json
```
   `--status` 只接受 `--slug`、`--state`、`--json`；它不取得 integration lock、不 mkdir、不建立
   worktree/verdict，也不隱式 continue、Gate 或 abort。輸出固定列出 phase（picking / conflicted /
   gate-pending / gate-blocked）、picked/remaining/conflicts、current HEAD/source tips、reservation
   owner、gate freshness 與恰一個 `next_action`。state/branch/HEAD/source/owner/gate drift 回 rc1 並具名
   problem；unknown slug、unreadable state 或與 mutation/source flags 併用回 rc64。freeze 期間仍可查，
   因為它沒有 mutation path。
   **`cherry-pick` 而非 `merge`**（工具內建，不是慣例）：merge 會讓每條來源分支的整段祖先
   變成結果的祖先，把它**碰巧帶著**的別人的 commit 一起復活（實測踩過——兩條分支各帶著另一個
   session 已丟棄的 commit）。picking 是逐顆的，所以進來的每一顆都是有人指名的。來源分支
   **解不出 / 帶 merge commit / 在 `main..<branch>` 沒有任何 commit**，一律**具名拒絕**
   （EXIT_USAGE）——靜靜跳過一顆 commit 正是這個動詞存在要防的事。
2. **衝突只解一次**。工具停在那一顆並具名衝突檔（payload 的 `conflicts` / `stopped` /
   `picked` / `remaining`）。在整合工作樹裡解、`git add`；授權前的 continue 同樣一律 `--no-gate`：
```
ops/worktree_orchestrate.py integrate --slug integrate-<batch> --continue --commit --no-gate --json
```
   這會保留 in-flight state、排空 queue 並明確回報 `gated=false`。完成純組裝後可由 Integrator 繼續追加 child；只有預期 child 全部回來且使用者給出 delivery-loop 授權後，才在同一棵最終整合樹執行
```
ops/worktree_orchestrate.py integrate --slug integrate-<batch> --continue --commit --json
```
   只跑一次綁定最終 HEAD 的 Gate。`--no-gate` 不產生 verdict、不構成放行，也不能被「機器不忙」之類環境判斷取代；授權邊界是唯一差別。Integrator 的 team-level 完成命令是 `close-wave --commit --sync`，不是 child 的 hand-back。

   **integration state 不可跨 rebase。** `--no-gate` 保存的 `picked[].new_sha` 綁定當下組裝結果；對該整合樹跑 `catchup` 會改寫 commit，state 不會跟著重錨。若本地 main 在純組裝後前進，不得 `catchup → --continue`：先 `integrate --abort --commit` 釋放來源保留，確認每條來源 branch 的 hand-back tip 仍匹配，再對舊整合樹做 `resolve --force` 的 dry-run 與明示 teardown（此時唯一工作是可由來源重建的 picks），最後從新 main 以同一來源重建。已取得 develop 授權者可讓 fresh `integrate --branches ... --commit` 在重建後直接跑唯一 Gate；未授權者仍用 `--no-gate`、hand-back、STOP。
   ### 衝突：rerere 可能先動手，而且不出聲
   先在目前這個 clone 檢查 `git config --get rerere.enabled`。若輸出 `true` 且
   `rerere.autoUpdate` 未設，Git 可能已把先前記錄的解法寫進工作區，但索引仍顯示 `UU`。
   因此看到 `UU <file>` 卻找不到衝突標記，不代表 cherry-pick 半途崩潰；這是 rerere 可能替你
   預解了檔案。這個設定是 `.git/config` 的 per-clone 狀態，不進版控；oscar 於 2026-08-08
   實測為 `true`，felix 的兩個 clone 實測為 unset，所以每次要以當下檢查為準。

   還剩哪些衝突未解的憑證是 `git rerere status`，不是掃衝突標記。文件本身可能描述衝突標記，
   未以行首錨定的 grep 會把散文當成殘留；`docs-conflict-markers` gate 的行首檢查只回答「已
   commit 的檔案是否留有標記」，不回答「rerere 預解是否正確」，兩件事不能互換。

   對 rerere 預解的檔案，在 `git add` 之前先取差集：
```
git diff --name-only --diff-filter=U
git rerere status
git rerere diff
```
   對差集中沒有列在 `git rerere status` 的檔案，逐檔看 `git rerere diff` 究竟改了什麼；不接受
   該預解時，使用 `git rerere forget <path>`，或用 `git checkout -m <path>` /
   `git checkout --conflict=diff3 <path>` 把真正的衝突取回來，確認後才 `git add`。不要因為檔案
   裡沒有標記就目視掃過後直接收下。

   rerere replay 的是另一個脈絡下對同一衝突雜湊做過的決定；雜湊相同不代表這次仍然正確。
   rr-cache 條目預設保留 60 天（`gc.rerereResolved`），所以它是需要驗證的 resolver，不是正確性
   證明。

   解法原則不變：生成產物重跑 generator，不手改；表格列用前後綴接合再修散文；純新增的
   程式碼 hunk 取兩邊。要放棄整批用 `--abort --commit`——它只解掉進行中的 cherry-pick 並忘掉
   整合狀態，**工作樹留著**（拆除是 `resolve` 的事，也只有它會過 landed-floor）。
3. **取得 develop 授權後，合併後那一次 gate 才由最終會觸發 Gate 的 `integrate ... --commit`（fresh 或 `--continue`）跑**，verdict **綁整合後的 HEAD**，不是任一原分支的
   HEAD——那正是本段開頭那五筆 BLOCK 逃掉的地方。in-flight 狀態存在
   `<anchor>/.cache/worktree_integrations/<slug>.json`（per-machine、gitignored），以 per-slug lock
   序列化 start/continue/abort 並以 atomic replace 寫入。Gate BLOCK 時 state 保留，修完用
   `--continue --commit` 只重走 Gate（其中輸入未變的成功 gate 會依 input fingerprint 重用）；
   pass/warn 後 state 移成 `completed/<slug>-<head>.json` manifest，保留來源 SHA、pick 對應與 verdict。
4. **`integrate` 不落地**：verdict 非 block 後**你**再跑一次 `cutover`。「非 block 才准落地」
   那條規則只住在 `cutover` 裡，`integrate` 不重判——這是「不重造 gate」硬邊界的直接後果，
   而不是省事。
5. **resolve 每一條來源分支**——見下方警告。

### `close-wave`：Delivery Team 的自動閉環收尾

當本 Delivery Team 預期的 child 都已 commit + hand-back，且 Integrator 取得本輪 delivery-loop（develop＋backup）授權，使用：

```bash
./ops/worktree_orchestrate.py close-wave \
  --slug <wave-slug> --branches <source-a> <source-b> ... --commit --sync --json
```

它先以 `integrate --commit --no-gate` 建立／續接整合 state（晚回 child 可先用同 slug `integrate --append`），再由整合樹自己的 orchestrator 跑唯一 fresh Gate；通過後依序 cutover、以 `--via-integration main` resolve 來源、`backlog.py anchor --commit`、`backlog.py validate --baseline-check`、resolve 整合樹，最後 `--sync` 把 exact primary tip 推到 `origin/main`。任何衝突或 Gate／resolve／anchor／sync 阻斷都保留 state，修正後**用同一 slug 重跑**；其他 team active worktree 不構成拒絕，本輪只處理明示 source branches，絕不誤殺 Catalog 或其他 session。這是可重入的 team-level delivery-loop，不是新的 develop plane，也不執行 `deploy`。

若該波次是沒有 backlog ticket 的獨立工具路徑，必須在 `close-wave` 與其底層 `integrate` 明示 `--independent`；未帶旗標時空 expected-ticket set 仍以具名拒絕收尾。獨立模式會把 `independent=true` 寫入 integration state／completed manifest，並在 registry 的 integration `intent` 留下 `independent-no-ticket:` marker；只有 Gate verdict 為 pass/warn 且 HEAD 精確相等、primary tracked-clean、integration queue 已清空，才允許空集合通過 cutover／validate／resolve／sync。恢復同一 slug 也必須重複原 opt-in，所有 provenance 會留在 phase receipt。

未取得授權時仍只能 `integrate --commit --no-gate`／`--append` 純組裝；不要把 `close-wave` 當成 child worker 的收尾命令。若正常 lock 競爭，等待工具 heartbeat／指數退避；若 state、primary 或 peer 不穩定，才用 thread message 做具名異常協調。

### 多輪同步、一次原子落地

多個 Delivery Team 可在不同 slug 的 integration tree 平行組裝；child 回來就由各自 Integrator 用 `integrate --append` 收進自己的 round，不互相傳進度。每個 team 的 final `close-wave --commit --sync` 會在 shared delivery-loop lock 內序列化 primary／origin/main 的最後 side effects；所以 Team B 不需要盯 Team A，也不應在 lock 競爭時重開 agent。所有存活 integration state 都必須維持自己的 fork base；若在 finalizer 開始前 main 已前進，abort、驗來源 hand-back tip、teardown、從新 main 重建；不要對有 state 的整合樹 catchup。整合後依序 resolve source、anchor/validate、resolve integration tree；`--via-integration REF` 只接受已是 base 祖先的 REF。

### Round 6–8 三 session 壓力測試契約（2026-08-09）

本輪是**刻意的壓力測試**：三個獨立協調 session、各取 15 張單、合計 45 張；票變多或工具摩擦變多本身不是失敗訊號。這段是本輪的拓撲與收斂契約，下一輪不應靠 prompt 臨時重推。

**啟動前建立共同基準。** 三個 session 必須記下同一顆本地 `main` SHA `M`，並在各自的批次 receipt 寫明 `session_id`、15 個 ticket id、integration branch。先用 `backlog.py validate --baseline-check` 驗 store，再對三份 ticket 集合做程式化對帳：id 不得重疊，`fix_site` 的檔案／行域不得交疊；有重疊就調整分配或排成具名前置，不靠三個 session 自己避讓。`open --next-backlog` 的 registry lock 只保證單票認領互斥，不替跨 session 的 fix-site 分區背書。

**三層拓撲，不讓 child 競爭 primary。** 每個 Delivery Team thread 在自己的 integration tree 收攏 15 張單；child 只做到 commit＋hand-back，不各自 gate／cutover。平行 Delivery Team 可各自用 `integrate ... --commit --no-gate` 組裝，晚回 child 用 `integrate --append`，各自保留自己的 state 與 receipt。每個 Team 的 Integrator 在自己的 final `close-wave --commit --sync` 內跑唯一 Gate、一次 cutover、來源 resolve、anchor/validate，再由 shared lock 序列化 primary／origin/main side effects；不需要等別的 Team 全部停止。

**Gate 用輸入變更決定，不用 commit 數量決定。** child／round integration 的 fresh 與 `--continue` 在未授權時一律加 `--no-gate`，只排空純 pick／衝突整理並保留 in-flight state；晚回 child 在 Gate 前用 `--append`，Gate 後留下一輪。取得本 Team delivery-loop 授權後，Integrator 用同一 state 跑一次 fresh Gate；base 已前進則依 abort／驗來源／teardown 規則從新 main 重建。Gate BLOCK 後只修該 Team integration tree，依 input fingerprint 只重跑失效或未知 scope 的 gate；成功 gate 可重用，未知依賴、輸入集合變動、orchestrator 不同代或 `inconclusive` 一律重跑。純 metadata 只跑 acceptance、`backlog.py validate --baseline-check` 與 review audit，不為此重跑不受影響的全量 Gate。

**Review 是有界的機器輔助，不是完美競賽。** 普通單一修補不自動配一對 LLM reviewer；高風險或複雜 scope 才例外派。沿用 `review_cycle.py` 的完整 `commit SHA × scope` 最多兩輪：第二輪仍 BLOCK 就進 driving-agent adjudication，選 `fix`、`accept` 或 `defer` 並具名；NIT 與 tooling debt 不得把 45 張單重新打開成無限迴圈。Gate 本身是獨立 review 層，fresh Gate 非 BLOCK 且 receipt／acceptance 齊全就是可交付的 80 分。

**壓測只量會影響決策的數字。** 三個 session 的共享 receipt／`.cache/coordination/` 應至少記：共同基準 `M`、各批 ticket／fix-site 對帳結果、source commit 數與衝突數、Gate planned／executed／reused／BLOCK／WARN、Gate wall-clock 與各階段 heartbeat、review cycle 次數、hand-back／resolve 殘留、primary cutover 次數，以及實際工具摩擦。工具問題若造成誤判、繞過、資料遺失或浪費一整輪 Gate，當場修並補回歸驗證；較小摩擦先記 receipt，不能因追求工具完美而中止壓測。

**Round 6–8 的完成條件。** 授權前的穩定交回點是：每個 Delivery Team batch 有且只有一個 owner，child 與 integration branch 全部 commit + hand-back，來源 commit 可追溯且衝突已具名解決，沒有任何 Gate／cutover。取得各 Team 自己的 delivery-loop 授權後，完整收斂條件才再加上：該 Team fresh Gate 無 BLOCK；每張單的 acceptance 或具名 manual evidence 已結案；`backlog.py validate --baseline-check` 為 0 problems；該 Team 的來源與 integration worktree 已 `resolve`，primary tracked-clean，`origin/main` 已同步，沒有未解 active registry 或 zombie process。WARN、延後的 NIT／tooling debt 與其理由要留在 receipt，不能冒充 PASS，也不必阻止進入下一輪。

**收尾（先保留手刻管線的歷史量測，再列真正 `integrate` 的量測）**：

> ⚠ **下列 2026-08-08 的 N=10 數字（含後面 `--via-integration` 那組）是手刻管線的歷史量測，不是 `integrate` 指令**。差別不只是重複實作：**那條管線帶著 `integrate` 刻意沒有的 `resolve_keep_both` 自動解衝突器**，所以「9/10 衝突但全綠」在手刻管線是自動達成的，換成 `integrate` 則由工具停下、再由 harness 明確解衝突後續跑。舊數字保留作歷史，不可當成 `integrate` 的可靠度證據；真正入口的新量測見下方。

`ops/worktree_loadtest.py --mode batch -n 10 --conflict shared` 在 2026-08-08 的手刻管線量到：整合本身全綠（9/10 cherry-pick 衝突、零列遺失、gate 跑 1 次、cutover landed、27.9 秒），但**十條來源分支全部拒絕拆除**。

2026-08-09 接線後以同一命令重跑真正的 `integrate` 管線：**10/10 commit、9/10 由 `integrate` 停在 shared 衝突、10/10 rows 保留、Gate=`warn` 且 0 BLOCK、cutover landed、85.3 秒、10/10 來源分支經 `--via-integration` 審計拆除、殘留 0、`validate` 0 problems**。這組才是 `integrate` 的量測；它證明的是工具能在衝突後由明確 resolver 續跑並保留資料，不把舊手刻數字冒充成新入口的證據。

所以請把下面這段當成必經流程而不是例外處理，並先讀 `IMP-20260808-77f2bd`——那條在提議讓工具自己跑審計。批次整合過的分支清不掉，而**兩道拒絕的理由不同**——`sweep` 對「工作樹還在」的分支一律 KEEP（那與包含性無關），`resolve` 才是被包含性判準擋下。後者的判準是「這分支動過的每個檔，main 現在是不是就是這分支的版本」；而
cherry-pick 之後若 review 修補又改了同一批檔，main 上是**更新**的版本，工具分不出「被更好的
版本取代」與「根本沒進去」，於是保守拒絕。**那是對的**——寬鬆到能放行這種情況的規則，同樣會
放行真正沒落地的工作（實測：正是這個拒絕暴露了一顆整合時被漏掉的 commit）。

正確做法**不是**把規則改鬆，而是讓工具跑審計：`resolve --worktree <path> --via-integration main --commit`。它對每顆分支獨有的 commit 由強到弱比對——① patch-id（同一改動不同 sha）② 主旨**且**檔案清單完全相同（整合時改過內容）——任一顆對不上就具名拒絕，過了則在 stderr 說明有幾顆是靠較弱那階過的。`--commit` 的成功 audit 也會在刪來源樹前，把 integration ref 的實際 tip 蓋進該來源分支的 staged closures；否則 branch identity 隨 teardown 消失，worker 證據會永遠留在 unstamped queue。payload 的 `staged_closures`／`pending_anchor` 是這一步的收據。**N=10 實測：floor 仍 10/10 拒絕（沒改鬆），審計放行 10/10，剩餘卡住 0，工作樹殘留從 10 變 0**，兩階在同一次跑裡都用到了。

`--force`（「我看過了」）仍在，但它現在是最後手段而不是常態。下面三步是審計的內容，留著是為了讓你看得懂它在比什麼、以及它拒絕時該去查什麼：
- 每條分支的每顆 commit，主旨在 `base..main` 找得到對應嗎？（弱證明，但抓得到整批漏掉的 commit）
- 分支動過的檔案，在 main 上都存在嗎？（抓「新增了一個從未落地的檔」）
- 上兩步有可疑者 → 比對 patch-id 與**檔案清單**。檔案清單不同 = 不是同一個改動，即使主旨一樣。

審計後若確認某顆 commit 只存在於待刪分支（例如它是別的 session 的草稿、已被對方自己的後續
commit 取代），**先打 tag 再刪**：`git tag archive/superseded-draft-<sha> <sha>`。分支一刪就只剩
reflog，而 reflog 會過期；tag 成本為零、風險歸零，也不必替別人的工作賭。

## 並發協調（多 session 常態）

> **範圍**：本段講的是**彼此獨立的 session**——各自帶著自己的 intent，但預設都停在 commit + hand-back，不各自 cutover；衝突由之後取得明示授權的整合者處理。同一批 fan-out 出去的受派者同樣遵守上方「批次交回狀態」。

同倉多 session 並發是常態，refuse 是**協調事件、不是死路**——refuse 訊息本身就是行動指引（列髒檔、給選項），照它做，不要死等輪詢：

- **cutover 被 primary 髒態擋** → **工具已經替你在共用信箱留言了**（IMP-20260806-42d183）：拒絕當下會 append 一則具名紀錄到 `<primary>/.cache/coordination/broadcast.md`（被擋的分支 + 髒檔清單 + 「gate 判決仍有效、primary 乾淨後重跑 cutover 即可」），payload 的 `broadcast` 欄是它寫到哪。**同一天＋同一分支＋同一組髒檔只會留一次**（重跑 cutover 輪詢不會洗版；髒檔集合變了、或隔天又擋一次，才算新資訊再留一則——**沒有人真的會照紀錄末尾說的去刪它**，所以 key 帶日期，否則同一條分支下週被同一支檔擋住時會一則都不留）。**`land` 的 pre-gate 檢查同樣會留言**（同一支 helper）。留言是 best-effort：寫不進去就**不留、不提**，拒絕理由一字不變——`.cache/` 是 gitignored 的暫存不是 SoT，拿寫檔失敗換掉診斷會比沒有這功能更糟。這則留言是**被動通道**，對方不一定會讀，所以急件仍該主動推：用 session-mgmt MCP `list_sessions` 查同倉 running session → `send_message` 發協調請求（請其 commit 或說明佔用）。是自己的殘留就 commit 或撤到 worktree（見上方「需要 main」路由末條）。gate verdict 綁 worktree HEAD 仍有效——primary 乾淨後**直接重跑 cutover**，不必重跑 gate（髒 primary 不會讓本地 main 前進）。**但若這段期間別的 session cutover 了**（本地 main 前進），cutover 會改以 base 落後為由拒——那時**必須**跑 `catchup --commit`（見 c2）並**重跑 gate**，不能只重跑 cutover。
- **政策**：primary 上工作**早 commit、常 commit**；agent 對 primary 是**過境不常駐**——別讓 uncommitted 改動在 primary 過夜擋別人的 cutover。
- **協調信箱（被動通道，優先於 send_message）**：`<repo>/.cache/coordination/broadcast.md`（全員）與 `<repo>/.cache/coordination/<slug>.md`（點對點，slug=你的 worktree slug）。`.cache/` gitignored、不進版控。**讀時機**（每個節點順手 `cat`，無檔即略過）：open 後、gate 前、cutover 被 refuse 時、暫停/待命前。**寫**：對其他 session 的非急件協調（排程、讓路、注意事項）寫進對方 `<slug>.md` 或 broadcast，**送出即完成、不等回覆**；急件（要對方立刻停手）才用 `send_message`（每則會跳使用者確認框，host 硬閘、配置免不了——所以批次合併、能少則少）。過期訊息由寫入者自清（附日期，處理完即刪）。

## Review loop 的停止條件

`review_cycle.py` 是鐵律 4 的收斂控制面：同一個完整 `commit SHA × scope` 第一次 BLOCK 修正後
最多再審一次；第二次仍有 BLOCK 就停在 `adjudication_required`，由 driving agent 做
`accept` / `fix` / `defer` 裁決，**不得自動派第三次完整 review**。NIT 與 TOOLING-DEBT
要分桶、具名追蹤，不得為了清掉它們把原始 scope 無限擴大。reviewer 中斷或逾時時先以
`cancel` 釋放 reservation，不得用它重置已完成的 review。每次新 commit 都是新 cycle；
狀態機與證據入口見 `ops/review_cycle.py` 及 `docs/sop/review_discipline.md`。

預設目標是可交付的 80 分：第三輪只留給確實複雜，或第二輪仍有多個明顯 release-blocking 缺陷
的 scope，並須具名說明理由。Gate 是另一道機器 review 閘門；gate BLOCK 會退回，fresh gate
通過後不應為了清 NIT 而無限重派 LLM reviewer。超過兩三輪時，先把 correctness 與邊際效益遞減
分開裁決，後者記成 follow-up。

## 硬邊界

- **呼叫端不得把長指令接進 tail / head / grep 這類會整段緩衝的過濾器**：實測 `./ops/ios_ops.sh test … 2>&1 | tail -20` 啟動背景任務後，output file 在整段執行期間維持 0 bytes，事後又只剩最後 N 行，會同時遮蔽 heartbeat 與前段進度。要截斷時先讓指令裸跑，或以 `> <log> 2>&1` 保留完整輸出，結束後再讀 log；否則會把正常執行誤判為卡死或 runner 缺陷（`IMP-20260805-f71e9b`）。
- **工作樹內一律 `git -C <工作樹絕對路徑>` 與絕對路徑，Bash 的 cwd 不保證在指令之間持久**：背景指令、heredoc 腳本或任何一次子行程都可能讓 cwd 漂回 primary checkout（**agent harness 更是每次 Bash 呼叫都重設 cwd**——實測前一次呼叫結束在 `/tmp`，下一次的 `pwd` 直接是 `/Users/chenliangyu/project/kg` ＝ primary）。漂回之後那些 repo-relative 指令**不報錯，只是安靜地改答另一個 repo 的問題**——不變式是「它回答的是 **primary** 的狀態」：`git status --porcelain` 回報 primary 的髒檔（primary 恰好乾淨時你就得到一句「乾淨」，而你的改動明明在別處）、`git add <只存在於工作樹的 path>` 報 `pathspec … did not match any files`、`./ops/i18n_lint.sh` 之類 repo-relative 工具驗的是主 checkout。
  - **單獨跑 `gate` 不會替你查 primary**；primary 端訊號現在由 gate 記錄 `primary_dirty` 與人讀警告具名； `IMP-20260808-b85f6a` 已讓空 diff 具名出現在 gate record 與人讀輸出：空 diff 仍是刻意合法的（工作已被 trunk 包含的分支本來就沒東西可 gate），只是現在會明說「no changes … no changed files were verified」並在 receipt 加 `no-changes`。所以編輯若整批漏進 primary，工作樹仍可能被兩道 meta gate 空跑而綠——連 **block 級**的 `review-receipts` 也一樣，因為 `main..HEAD` 根本沒有 commit 可稽核；但這個結果不再與正常 PASS 無聲同形：

    ```
    # gate PASS  (0 changed file(s), 2 gate(s))  orchestrator=<sha8> (worktree)
      ⚠ no changes in this worktree vs main — no changed files were verified. If you have been editing, the edits may have landed in the primary checkout instead (cwd drift); check `git -C <worktree> status` before trusting this PASS.
      ✓ review-receipts [pass] — exit 0: review_audit: auditing <被 gate 的樹>
      ✓ coverage [pass] — 0 covered, 0 neutral, 0 uncovered
    ```

    （`<sha8>` 與那個路徑因樹而異，其餘逐字。）現在會有醒目的警告與 machine-readable 的 `no-changes` receipt；`(no impact-based gates selected …)` 仍不會印，因為 `plan_gates` 尾端無條件 append `coverage`（該處註解自己就寫了「`plan` is never empty」），`cmd_gate` 的 `if not plan:` 仍是死碼。**看到 `no-changes` 或 `0 changed file(s)` 就停下來核對你人在哪棵樹**：這不是「改動很小」，而是「這棵樹沒有你的改動」。
  - **走 `land` 會被擋，但擋的理由指向別人**：`land` 取號後、**進 gate 之前**就跑 primary tracked-clean 檢查（`_primary_ff_ready`，:3023 排在 gate 的 :3043 之前——見上方 c3 段，那是刻意的成本設計），所以編輯漏進 primary 時它擋在昂貴的 gate 之前，並逐檔列出 `dirty:`，那些正是你的編輯。訊息也確實留了 `(b) if the leftovers are yours, commit them or evacuate them to a worktree` 這條路。**它缺的不是「可能是你的」，是成因**：沒有人告訴你這些檔之所以在 primary 是因為 cwd 漂了，而你那棵工作樹是空的。primary 若剛好乾淨（漏進去的編輯已被別人 commit，或漏到了第三棵樹），這道檢查一聲不吭。
  - **手動 `gate` → `cutover` 才是「綠已經記下來了才擋」**：`cutover` 只在 ff 前查 primary（:2630），那時錯的那輪 gate 已經跑完、判決已綁 HEAD 寫進紀錄。
  - **兩張票刻意分成兩端**：`IMP-20260808-b85f6a` 已提供 worktree 端的 `no-changes` 訊號；`IMP-20260808-e8ad13` 仍負責 primary 端未 commit tracked 改動的具名回報。兩者皆 warn 不 block，且可以單獨為真——primary 乾淨但工作樹是空的時候，只有前者看得見。
- **cutover/sync 不碰生產；deploy 才碰生產（唯一）**：cutover 只前進**本地** main（免費、可逆、不碰網路）；`sync` 只把本地 main 鏡像到 **origin/main** 備份（reconciler 不看 main → 零生產副作用）。生產部署發生在 `deploy` 把本地 main 推 **origin/prod** 之後——felix reconciler（launchd `com.kg.reconcile`，90s tick，盯 origin/prod）偵測前進且有 `backend/**` 變更即部署 wordnexus.lol（compose rebuild + 健康 gate + auto-rollback）。**因此「上生產」= 你刻意跑 `deploy`（或 `release.sh release`），不是每次 cutover、也不是 sync。** deploy 前確保要發布的 backend 變更 gate 已真實反映風險；資料面操作（migration/DB）仍走 `devops` skill 與鐵律 7。頂端的 gate + cutover 雙重授權**不包含** `sync`／`deploy`／`release`；這三者仍須使用者明示對應的備份或發布意圖。
- **不重造 gate**：`gate` 只路由到既有工具。要加可斷言的 gate → 改對應工具本身，不在 orchestrate 內判 pass/fail。
- **動 agent-facing surface**（本 CLI/skill 本身）→ 同 PR 同步 `docs/reference/tech_index.md` / `product_surface.md`（見根 CLAUDE.md「改 user/agent-facing 介面」）。
- 收尾照 `kg-receipt`：驗證輸出 + 交接點。工具摩擦記 tooling debt（鐵律 9）。

## 一眼流程圖
```
preflight ─▶ 讀地圖 ─▶ research? ──yes──▶ 直接做（不開 worktree）
                          │no
                          ▼
              phased 拆 phase ─▶ open(fork 本地 main) ─▶ [每 phase: 實作 + review N-1]
                          ─▶ 局部驗證 ─▶ commit ─▶ hand-back ─▶ 回報 branch/path/HEAD ─▶ STOP
                                                        │
          ├─ 批次組裝、尚未授權 ─▶ integrate --commit --no-gate ─▶ commit + hand-back ─▶ STOP
          └─ 使用者明示「無其他 session」且授權 gate+cutover？
                                      │yes
                                      ▼
                ┌─ 單線 ─▶ catchup（需要時） ─▶ fresh Gate
          └─ 批次 ─▶ child 陸續回來：integrate --append（不 Gate）
                          └▶ base 未動：integrate --continue --commit（唯一 fresh Gate）
                          └▶ base 已動：abort／驗來源／teardown／從新 main fresh integrate（唯一 fresh Gate）
                                      │pass/warn（BLOCK 則修後重跑）
                                      ▼
                  cutover(離線 ff 本地 main ＋ post-landing ledger repair) ─▶ resolve
                          └▶ anchor/validate ─▶ sync(backup) ─▶ Delivery Team 完成

          deploy 或 release(release) 仍是另外的使用者意圖；delivery-loop 的 --sync 只推 origin/main
```
