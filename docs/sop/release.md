<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - ops/
  - backend/
verified_against: 44d0c76c5
-->
# Release / 部署 / 版本管理 — 三平面心智模型

> 拓樸事實 SoT 見 [`docs/reference/host_topology.md`](../reference/host_topology.md)；後端手動部署細節見 [`docs/sop/deploy.md`](deploy.md)；iOS 出 build / TestFlight 見 [`docs/sop/ios.md`](ios.md) §發版。本文是**跨前後端的 release 流程正本**。

## 為什麼三平面

`git push origin main` 本來身兼兩職：**備份**（推 GitHub）＋**觸發後端生產部署**（reconciler 盯 origin/main）。把無所謂的雜事和唯一有生產後果的決定綁在同一個鍵，是版控不清晰的根源。三平面把它拆開：每平面一個真相、一個動詞、一條紅線。

| 平面 | 問題 | 真相 ref | 動詞 | 生產後果 |
|---|---|---|---|---|
| **develop** | 我接受了什麼 | 本地 `main` | `cutover`（worktree→本地 main，離線；ff **＋可能一顆 ledger repair commit**） | 無 |
| **backup** | 碼在機器外安全嗎 | `origin/main` | `sync`（push origin/main） | **無**（reconciler 不看 main） |
| **release** | 世界該跑什麼 | `origin/prod` + tag | `deploy`（推 origin/prod）/ `release`（統一入口） | **有（唯一）** |

**唯一碰生產 = `deploy`（backend）/ `release`（前後端統一）。** `sync` 只是備份；取得明示 backup 意圖後可重複執行，develop 授權本身不包含它。

### `cutover` 為什麼不是純 ff

develop 平面**前進本地 main 的方式**仍是 ff——被 gate 過的那顆 sha 原封不動落地（payload 的 `sha`）。但 cutover 的 rebase 發生在 gate **之後**，而 rebase 會改寫分支上的 commit sha；ledger entry 的 `fixed_by` 因此在落地那一刻才指得到正確的 commit。所以 ff 完成後，cutover 會在**同一把 trunk 鎖內**跑 `backlog.py reanchor --commit`，有改動就自己 commit 一顆（訊息帶 `Review-Exempt: machine-repair`，該 token 由 `ops/review_audit.sh` 檢查「只碰 `docs/runbook/backlog/*.json`」，不是自由通行證）。原本還有第二步 `render --commit`，隨那份 generated view 移出版控而移除（IMP-20260807-b9526c）——已經沒有 tracked 的衍生檔需要在主幹上被修。

同一把鎖內、**且在所有 post-ff refusal 之後**，cutover 還會把這顆落地 sha 蓋到這條分支在波次佇列裡的結案上（payload 的 `staged_closures`；佇列＝`<primary>/.cache/backlog_anchor_queue.jsonl`，由 `backlog.py stage` 寫入、`anchor` 消費）。**位置是契約的一部分**：`make_commit_state` 認 HEAD **或** main 任一可達，所以一次被拒絕的 cutover 若已蓋了 sha，從還沒拆掉的工作樹跑 `anchor` 會判 ok，把 entry 關在一顆不在任何主幹上的 commit——而下游沒有任何人會抱怨。

**因此本地 main 的 tip 可能不是 payload 的 `sha`**——那顆在 `trunk_tip`。兩者相同表示這次沒有東西需要重推導。repair 任一步失敗一律把 `docs/runbook` 還原回 HEAD 再回報（`repair.restored`），因為留下髒 primary 會讓**之後每一次** cutover 都被拒。

### `catchup`：trunk 動了之後的那一步

`gate` 與 `cutover` 在分支落後本地 main 時都會拒絕並要你先追上。那一步現在是 `catchup --commit`（原本是叫你自己跑 `git rebase main`）。當初的差別是：rebase 會在那份 **generated** 的 ledger view 上衝突（實測十條分支一輪，3–6 條中招），而那個檔沒有「該保留哪一邊」的問題——它是 store 的純函數，正解就是重跑 generator，所以 `catchup` 曾內建一個「衝突集合恰好等於該檔就自動重生」的解析器。**該檔已移出版控（IMP-20260807-b9526c），衝突源與那個解析器一併消失**：現在 `catchup` 就是一次乾淨的 rebase，衝突一律 abort 交人——本來就該如此。rebase 完 HEAD 就動了：已取得 develop 授權者必須跑 fresh `gate`；授權前只有一般且無存活 integration state 的工作樹可 catchup，完成後重新 `hand-back` 更新 SHA。整合樹 base 前進時必須走下方 abort／驗來源／teardown／重建路徑。

## 版號事實 SoT 表（iOS）

「哪個版號說法可信」只有一個答法：先問**這是哪一個事實**，再看誰是它的 owner。四個事實各有唯一 owner，任一份文檔、腳本輸出或人的記憶都不是。

| # | 事實 | 唯一 owner | 怎麼查 | 誰寫進去 |
|---|---|---|---|---|
| ① | **我要發什麼版號 / build** | `ios/BooksAndVocab.xcodeproj/project.pbxproj` 的 `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`（**project-level build settings**；target-level override 已全數刪除，測試 bundle 靠繼承，見 `fe4a82355`）。backend 對應面是 `backend/pyproject.toml` | `./ops/release.sh status` 的「專案版號」行 | `release.sh bump ios` / `bump-build ios`（委派 `release_bump.sh`） |
| ② | **(version, build) 由哪顆 commit 產生** | repo 的 **build tag** `ios/<x.y.z>+<build>`。immutable；同一 marketing version 下可多顆並存（`2.0.0+5` 與 `2.0.0+6` 同時為真） | `git tag -l 'ios/*+*'`；`./ops/release.sh status` 的「build tag 對照」表 | `release.sh tag ios` / `release ios` / `resubmit ios`，在 upload 成功後封版 |
| ③ | **哪顆 build 上架了** | **App Store Connect，唯一權威**。**不快取成 repo 內的事實**——只能在需要時現查 | `./ops/asc_shipped.py`（stdout 一行 `<version> <build>`；查不到就非零退出，不猜）；旁證 `./ops/asc.sh versions` / `review-status` / `builds` | Apple。我們只讀 |
| ④ | **某 marketing version 上架的是哪顆 commit** | **版本級 tag** `ios/<x.y.z>` — 就是 ②③ 的 join | `git rev-list -n1 ios/<x.y.z>`；`./ops/release.sh status` 的「已上架 tag」行 | **只有** `./ops/release.sh shipped ios --yes`，在 ASC 查證後物化。immutable，工具不移動；衝突一律 refuse 交人裁決 |

**為什麼非拆成四格不可**：ASC 對這個 app 只保留**一筆** `appStoreVersions` 記錄，`versionString` 是可變欄位、已被原地改寫七次（1.4→1.5→1.6→2.0.0→2.0.1→2.0.0），而 build number 每個 marketing version 重新計數（`build 1` 在本 app 歷史裡出現過六次）。**Apple 不保留歷史**，於是「(version, build) 由哪顆 commit 產生」這個事實**只有 repo 能保存，而且必須在封版當下捕捉——事後無法重建**（2.0.0 那次的重建靠夾擠 pbxproj 編輯時戳與送審時戳，是考古不是查詢）。②③ 分開存、④ 只當 join，就是為了讓任何一邊都不宣稱它不擁有的事實。設計理由正本見 `075673f79` / `fcd523434` 的 commit message。

**由此推出的兩條規則**（工具已實作，不靠自律）：
- `ios/<x.y.z>` 的存在**本身就是上架證據**，所以新版 guard 是真檢查而非 operator 背書：須有上架 tag、新版須嚴格遞增、且**不得跳過「有 build tag 但沒有上架 tag」的版本**（後者正是 ios/2.0.1 事故的形狀）。舊的 `--new-version-after-ready <previous>` typed attestation **已移除**，傳入會 hard-error 並指向替代路徑。
- `tag ios` / `release ios` / `resubmit ios` **不產生** `ios/<x.y.z>`。upload 完成的那一刻沒有人知道會不會過審。

### 機制上線前的舊 tag：刻意不重新詮釋

`ios/<x.y.z>` 的現行語意自 `075673f79` 起才成立。在那之前 `tag ios` 打在 bump 的那一刻，意思是「這裡把版號改成了 x.y.z」，**與上架無關**。既有兩顆舊 tag 因此不能照新語意讀，且兩顆都已推上 origin：

- **`ios/1.6.0`**（`cddef104a`）— 舊語意的 bump 點，**不代表上架**。1.6 底下 Apple 端存在四顆 build（1/2/3/4，2026-08-05 查證），而 ASC 只留當前那一筆 version 記錄、1.6 的那筆早被改寫掉，**哪顆 build 上架了現在已不可考**。因此這顆 tag **刻意不重新詮釋、不移動、不刪除**——這是「repo 不宣稱它不擁有的事實」的實例。唯一能把它升格成合格 ④ 的路是人工判定後 `shipped ios --commit <sha>`，而該路徑會把結果明確標記為「人工斷言，不是查證出來的 join」；在沒人能判定的今天，維持現狀勝過造一個看起來權威的答案。
- **`ios/2.0.0`**（`caacbb2db`）— 同為舊語意，且**已知指錯**：指向 build 5 的封版 commit，實際上架的是 28 個 `ios:` commit、五天之後的 build 6。與 1.6.0 不同，這次的對應關係被考古出來了，但**重新指向一顆已推出去的 tag 是人的決定、不是工具的**，故仍待人工裁決。`shipped ios` 遇到這種矛盾會 refuse 並印出精確補救指令（刪本地 + 刪 origin + 重跑），絕不自行移動。

## 動詞對照

### Develop 平面授權預設

一般 session 預設假設同 repo 有其他工作同時進行，完成局部驗證與 commit 後執行 `./ops/worktree_registry.py hand-back --json`，保留工作樹並交回；不自行執行會觸發 Gate 的 `integrate`、`gate`、`land`、`cutover` 或 `resolve` 或 `close-wave`。授權前可對一般工作樹做 branch-local `catchup`，批次純組裝則只能使用 `integrate ... --commit --no-gate`；兩者完成後都重新 hand-back。有存活 integration state 的整合樹禁止 catchup；main 前進時須 abort、核對來源 hand-back tip、明示 teardown，再從新 main 重建。只有使用者當下明示「目前沒有其他 agent/session 工作」且授權本 session 直接 gate + cutover，才可進 develop 平面。這只解鎖會觸發 Gate 的最終 `integrate ... --commit`（fresh 或 `--continue`）／`gate`／`land`／`cutover`／`resolve` 或 `close-wave`；`sync`、`deploy`、`release` 仍須另有明示 backup／release 意圖。此政策只決定誰在何時呼叫動詞，不改變下表的工具語意與護欄。

| 動詞 | 工具 | 讀 | 前進 | 副作用 |
|---|---|---|---|---|
| `cutover` | `ops/worktree_orchestrate.py cutover --commit` | worktree branch | 本地 `main`（ff，**之後可能再 +1 顆 repair commit**） | 無—離線可逆 |
| `land` | `ops/worktree_orchestrate.py land --worktree <path> --commit` | 本地 `main` | 本地 `main`（取 FIFO 名次後 catchup→gate→cutover 一氣呵成） | 無—離線可逆；**已取得落地授權後**,多條獨立工作樹的預設序列化路徑（手動序列實測 N=10 只有 2/10 收斂） |
| `catchup` | `ops/worktree_orchestrate.py catchup --commit` | 本地 `main` | worktree branch（rebase） | 無—只動那條 worktree |
| `integrate` | 來源先 `./ops/worktree_registry.py hand-back --json`；授權前 `integrate --slug <s> --branches <b...> --commit --no-gate`；取得 develop 授權後才執行會觸發 Gate 的 fresh／`--continue --commit` | 本地 `main` + N 條來源分支 | **新開的整合 worktree**（cherry-pick，**非 merge**）| 無—**不前進任何共享 ref**。`--no-gate` 只組裝並 hand-back；state 不可跨 catchup，base 移動須 abort／驗來源／teardown／重建；最終 integrate 只跑一次 Gate，落地仍另跑 `cutover` |
| `close-wave` | 交付隊收斂協調器的可重入入口：`close-wave --slug <s> --branches <b...> --commit`；同 slug 重跑可續接命名衝突／Gate／cutover／來源 resolve／anchor／validate 停點，最後才拆整合樹 | 本地 `main` + 來源 branches + backlog anchor queue | 本地 `main`（透過整合樹再 `cutover`） | 無—develop 內部閉環；**不**自動 `sync`、`deploy` 或跨越其他 active worktree。仍須先滿足正常 develop 授權 |
| `sync` | `ops/worktree_orchestrate.py sync --commit` | 本地 main | `origin/main`（守護 ff） | **零** |
| `deploy` | `ops/worktree_orchestrate.py deploy --commit` | 本地 main | `origin/prod`（守護 ff） | **生產**—reconciler 部署 |
| `tag` | `ops/release.sh tag <api\|ios> <v>` | 版號檔 | 版號 commit + tag + push origin main。**api 打 `api/x.y.z`；ios 打 `ios/x.y.z+<build>`（build 級封版，不是上架標記）** | 備份/標記，無生產 |
| **`release`** | `ops/release.sh release <backend\|ios> <v>` | 版號檔、本地 main | backend：bump→tag→deploy→**等收斂**；iOS：bump→upload→封 build tag | **生產** |
| `resubmit ios` | `ops/release.sh resubmit ios` | 版號檔、本地 main | marketing 版號不動，build +1→upload→封 `ios/x.y.z+<build>` | **外部**—TestFlight 上傳不可逆 |
| `shipped ios` | `ops/release.sh shipped ios` | ASC（現查）+ build tag | `ios/x.y.z`（上架標記）+ push origin | 無—唯讀查 ASC，只寫 tag |

- **`gate` / `cutover` 必須用工作樹自己那份 orchestrator**（`<worktree>/ops/worktree_orchestrate.py`）：gate 的工具以工作樹為 cwd 執行，路由規則必須同代，否則會用另一版的規則排 gate 而輸出形狀完全相同。工具自身以 sha256 比對後 refuse，判決紀錄帶 `orchestrator` 身分、cutover 一併核對。`resolve` 例外，用主 repo 那份（它會刪掉工作樹本身）。
- **`cutover` 的新鮮度是兩軸**：HEAD（判決**讀**的碼）與 base（判決落地時**身旁**的碼）。base 落後即拒——cutover 的第一個動作就是 rebase 上本地 main，所以落後的樹被判過也不是落地的那棵，而 HEAD 檢查看不到（HEAD 沒動，動的是 base）。`gate` 也會提前拒，省下白跑的 gate。修法：`catchup --commit` → **重跑 gate** → cutover（IMP-20260806-945e01）。
- `deploy` 的 `--upstream` 預設 `origin/prod`；`sync` 的預設 `origin/main`。兩者共用守護引擎 `_guarded_advance`（primary 在 main、origin/<dest> 為 local 嚴格祖先、絕不 force、noop、ls-remote 事後驗證）。
- `sync` 別於 `sync-main`：`sync` 是 local→origin（備份推出）；`sync-main` 是 origin→local（追上 origin，用於 fresh clone）。
- `tag`（原名 `publish`，別名保留）push origin main = 版號 commit 的備份 + tag 標記，**非部署**。iOS 新 marketing version 的 direct tag 一樣過 `guard_ios_new_version`（見上「版號事實 SoT 表」的兩條規則），不能繞過。
- `release <backend|ios>` / `resubmit ios` 須在 primary、on `main` 執行（發布本地主幹）。`shipped ios` 只讀 ASC + 打 tag，不受此限。
- `changelog ios` 的區間錨在**上架 tag**、不是 build tag——這條規則的單一 owner 是 `ops/lib/release_tags.sh`（`release_last_tag`），`release.sh` 與 `release_changelog.sh` 共用同一份。曾各持一份副本，只改一邊的後果是 changelog 靜默錨到 build tag、印出「無變更」（`47e9fea97`）。

## develop 平面之前：批次整合

一批工作分散在 N 個工作樹時，develop 平面之前還有一步收斂。**與三平面相關的只有一件事：
批次整合不是第四個平面**——它發生在 develop 平面之前，產出仍是一次普通的 `cutover`。

受派者完成最後一顆 commit 後，必須在自己的工作樹執行
`./ops/worktree_registry.py hand-back --json`；`integrate` 會把這個戳記與來源 branch 現在的
tip 做一致性檢查。尚有其他 session 或尚未取得 develop 授權時，fresh／continue 一律加
`--no-gate`，整合樹完成純組裝後也 commit + hand-back；等條件成立，才由握有整批視野的整合
session 在最終整合樹跑唯一 Gate。流程正本與交回契約皆在 `.claude/skills/worktree-flow/SKILL.md`
「批次整合」段（含「批次交回狀態」子段）。

## Release 流程

**backend**（`release backend x.y.z`）＝ `bump api`（若版號檔≠x.y.z）→ `tag api x.y.z`（commit 版號 + `api/x.y.z` + push origin main）→ `orchestrate deploy --commit`（推 origin/prod → felix reconciler 健康 gate 部署 wordnexus.lol）→ **等生產收斂**。dry-run 預設，`--yes` 才執行。

### 為什麼 backend 多了第四步「等收斂」

`deploy` 只保證 **origin/prod 前進**——那是「我要求什麼」，不是「線上跑什麼」。真正的部署由 felix reconciler 非同步完成，失敗會自動回滾 + poison（冷卻 3600s），而它唯一的聲音是 felix 本機的 `~/Library/Logs/kg_reconcile.err.log`：沒有 push、沒有 mail、felix-status dashboard 也沒有 reconciler 面板。在 push 完就印 ✓，等於把「已回滾」宣告成「已發布」（鐵律 2）。

所以 `release backend` 在 deploy 之後守著看：輪詢 `https://wordnexus.lol/api/system/info`，直到自報 `version` 是本次 sha 的前綴才宣稱成功；逾時（預設 480s）非零退出，並印出實際觀測到的線上版本與查 reconciler log 的指令。

兩個容易踩的點，都已寫進實作與 `ops/test_release.sh`：

- **要不要等，用 `kg_reconcile.sh` 的 `paths_need_deploy` 判，不另寫一份正則。** `orchestrate deploy` 顯示的 `backend files` 是 `backend/` 前綴，刻意是 reconciler 那條窄正則的**超集**（只會 over-warn）。若拿它來決定等不等，range 內只有 `backend/uv.lock` 這種情況就會去等一場永遠不會發生的 rollout，然後假紅。
- **prefix 比對有 7 字元下限。** reconciler 寫進 `backend/VERSION` 的是 `git rev-parse --short`，長度隨 repo 成長變動，所以只能比前綴；沒有下限的話，一個回傳 `"d"` 的壞掉端點會命中任何以 d 開頭的 sha，把「壞掉」讀成「收斂」。

逾時**不代表**部署失敗——可能仍在 build。三種可能（仍在 build／gate 失敗已回滾／reconciler 停擺）由 `~/Library/Logs/kg_reconcile.{err,out}.log` 區分，錯誤訊息會印出這兩條指令。此時**不要重跑 `release`**：版號 tag 已存在，重跑會被 tag preflight 擋下；直接查 reconciler。

env knob：`KG_RELEASE_WAIT_SECS`（預設 480）、`KG_RELEASE_POLL_SECS`（10）、`KG_PUBLIC_URL`。要「推了就走、不等」請直接用 `orchestrate deploy --commit`——那條路本來就不等，語意上也誠實。

**ios 新版本**（`release ios x.y.z`）＝ `guard_ios_new_version`（讀 repo 的上架 tag 與 build tag，見上方兩條規則；**無 flag、無 operator 背書**）→ `bump ios` → `ios_release.sh --upload`（archive + 上傳 TestFlight）→ upload 成功後才封 `ios/x.y.z+<build>` + push。upload 失敗不留下 commit/tag/push；封版 tag 若已存在於**另一顆** commit 則在 upload **之前**就拒絕（同一顆 commit 且 pbxproj 乾淨＝重跑，noop）。

**ios 同版重送**（`resubmit ios`）＝ App Review 被拒／尚未上架就要換 binary：`bump-build ios`（marketing 不動、build +1）→ `--upload` → 封 `ios/x.y.z+<build>` + push。這條路徑以前是兩步手動且**不留任何紀錄**，正是 `ios/2.0.0` 脫鉤的成因（`888967dd9`）。

**ios 上架後**（`shipped ios --yes`）＝ 向 ASC 查 `READY_FOR_SALE` 的 (version, build) → join 對應的 build tag → 物化 `ios/<x.y.z>` 並推 origin。任何歧義都 refuse 不猜：ASC 不可達／無 `READY_FOR_SALE`／多筆 `READY_FOR_SALE`／版號或 build 格式不對／找不到 build tag／`ios/<x.y.z>` 已存在於不同 commit。找不到 build tag 時唯一逃生口是 `--commit <sha>`，輸出會標記「這是人工斷言，不是查證出來的 join」。已一致時為 noop，可排程或在中斷後重跑。

日常盤點：`ops/release.sh status`（各 component 待發版 commit + released gap + 專案版號 + build tag 對照；本地唯讀）。status 的 ios 段會在「目前的 (version, build) 沒有 build tag」時具名警告——那是「一顆 build 出去了卻沒留紀錄」唯一看得見的症狀。

## felix reconciler（release=deploy 自動收斂）

`ops/kg_reconcile.sh`（launchd `com.kg.reconcile`，90s tick，跑在 felix 專用生產 clone `~/kg-prod`）盯 **`origin/prod`**：一前進且含 backend 觸發路徑 → `git pull --ff-only origin prod` + 寫 `backend/VERSION` + `docker compose up -d --build --force-recreate` + 健康 gate（localhost + 外部 smoke + infra）；失敗自動 rollback + poison（**rollback 那次也 force-recreate**）。唯一例外：外部 smoke **全程拿不到任何 HTTP 回應**（felix 對外斷網，非服務回 5xx）不算失敗——部署照常落地並記 `smoke=unverified` + 告警，不回滾、不 poison（IMP-0061；判準與三分類表見 `docs/sop/deploy.md` §rollback + poison 行為）。`--force-recreate` 不是可省的：健康 gate 比對容器自報版本，而容器自報的是 bind-mount 進去、於 import 快取的 `backend/VERSION`，只隨行程重啟改變；而 `up -d --build` 只在 image digest 或解析後 compose config hash 變了才 recreate。命中觸發卻不進 image 的改動（compose.yml 註解、Dockerfile 註解、pyproject `[tool.*]`）兩者皆不變 → 容器不重啟 → 自報舊版 → gate 判失敗 → 回滾 + poison + 告警，而 poison 只冷卻 3600 秒，**於是每小時重演一次**（IMP-0056）。非 backend 變更只 ff-only 追 repo（**刻意不寫 VERSION 游標**，見 kg_reconcile.sh §2.4 註解）。origin/prod 未 seed → 優雅 noop（不崩）。

- **desired/actual 配對**：`origin/prod` = 期望部署狀態（release 推進）；`backend/VERSION`（felix-local git sha）= 實際部署狀態（reconciler 寫）；`/api/system/info` 回報實跑版供交叉驗證。
- **生產 clone `~/kg-prod` 專屬**：compose 從 `~/kg-prod/backend` build。`~/project/kg` 是 dev/resume-only，**永不在其 backend 跑 compose**（同 project name `backend` 會劫持生產容器）。`devops.sh`/`devops_kg_safe.sh` 的 `KG_REMOTE_DIR` 預設已指 `~/kg-prod/backend`。

## felix 生產切換（首次啟用：origin/main → origin/prod 拓樸遷移）

前置：挑「零 pending backend」窗口（`git diff <deployed>..origin/main -- backend/ | grep -E "$BACKEND_TRIGGER_RE"` 為空），使切換為純機制搬遷、零功能部署。全程在 felix。

| Step | 動作 | 碰生產 |
|---|---|---|
| **P0** | 三平面 code/docs/test 落地本地 main → `sync --commit` 推 origin/main。舊 reconciler self-update 成新碼 → fetch origin/prod（未 seed）→ noop（自動部署暫停、容器不動）。P0→P2 連續做 | 否 |
| **P1** seed prod | `D=$(cat ~/project/kg/backend/VERSION)`；驗 D 為 origin/main 祖先；`git push origin origin/main:refs/heads/prod`（origin/prod=main HEAD H，backend(H)==backend(D)） | 否 |
| **P2** clone | `git clone -b prod <url> ~/kg-prod`；`cp ~/project/kg/backend/.env ~/kg-prod/backend/.env`（含 `KG_DATA_DIR=~/kg-data` 絕對路徑）、`cp -R …/certs`、`printf '%s\n' "$H" > ~/kg-prod/backend/VERSION`。先不跑 compose | 否 |
| **🚦 GO GATE** | 回報狀態 + 健康快照，取得明確 go 才進 P3 | — |
| **P3** recreate | `launchctl bootout gui/$(id -u)/com.kg.reconcile`（防 race）→ `cd ~/kg-prod/backend && docker compose up -d --build`（同 project name/container_name/volume → 原地 recreate 同一顆容器）。驗 localhost + wordnexus.lol `/api/system/info`(version==H) | **是** |
| **P4** plist | 換 `~/Library/LaunchAgents/com.kg.reconcile.plist`（路徑+KG_RECON_REPO=~/kg-prod）→ 手動 `KG_RECON_REPO=~/kg-prod ~/kg-prod/ops/kg_reconcile.sh --dry-run` **必印 noop** → `launchctl bootstrap`。觀察前幾 tick noop | 是（應 noop） |
| **P5** 純化 | `~/project/kg` 還原純 dev（由人 `git pull` 追 main，reconciler 不碰）。確認 devops footgun fix 生效 | 否 |

**P3 rollback**：新容器不健康 → 因 project name 相同，從舊 `~/project/kg/backend`（checkout H；backend(H)==backend(D)）`docker compose up -d --build` 復原同顆容器（同 volume、data 未分岔）。徹底放棄：還原 plist + bootstrap 舊 reconciler + `git push origin :prod` + `rm -rf ~/kg-prod`。
