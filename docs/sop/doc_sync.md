<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - docs/
verified_against: 4e2d680ba
-->
# Doc-Sync Agent SOP

你是 background doc-sync agent。任務:把一段 code commit 的改動同步到對應文檔並**自行 commit**。主線已繼續工作,你獨立完成、不回頭問。

`docs/registry.yml` 是文檔控制平面的機器可讀 SoT:每份活文檔的 `kind`、權威性、語意 trigger、source hint、generator、check(generated 專用的等值檢查命令)都先看 registry。`sources` 可用 `!path` / `!glob` 排除 broad source 下的已知誤報(例如 docs tooling 不應觸發 deploy/safety/host docs)。下方路由表是人類速查,若衝突以 registry 為準。

## 輸入

主線給你:**commit hash / range** + **一兩句改動摘要**。其餘自己查。

## 步驟

1. `git show <hash>` / `git diff <range>` 看實際改了什麼。
2. 先讀 `docs/registry.yml`,必要時跑 `./ops/docs_impact.py --since <base>` 取得 path-hint 候選;若要調 registry source hint 精度或追查為何某份 doc 沒出現在提示裡,再補跑 `./ops/docs_impact.py --files <paths...> --explain` 看 `!path` / `!glob` 排除規則是否把 broad match 壓掉。`match_type=exact|broad|suppressed-partial|suppressed` 是 impact 的第一層理由欄位；human output 也會直接印 match-type legend 與 recommended review order，預設先看 `exact`，再看 `suppressed-partial`，最後才看 `broad` 候選。`--explain` 不只會列完全 suppressed 的 doc,也會在仍有有效 impact 的 row 上附 `excluded_changed=` / `excluded_by=`，讓 partial suppression 也看得見。再把 diff 對應到 registry 的語意 trigger,用下方**路由表**輔助判斷影響哪些 doc(可能 0 份 → 回報「無需同步」即收工)。impact hint 是提示,不是自動同步命令。
3. 每份目標 doc:`grep` 舊命令/欄位/旗標/模組名清單,凡引用到被改掉的舊狀態 → 更新成新狀態。**不臆造**:找不到對應 doc 或拿不準就如實回報,別硬寫。
4. **reference / contract / policy** 類活文檔:更新內容後把 frontmatter `verified_against` 改成被同步的 code commit(短 hash)。
   **判準是 `origin/main` 可達,不是「main 可達」**——本 repo 的拓樸是**本地 main 為主幹、超前 origin**(`ops/worktree_orchestrate.py` 的 cutover 只前進本地 main,推 origin 是另一個刻意動作),所以「local main 可達」**不蘊含**「origin/main 可達」。CI 解析的是後者,IMP-0038 那批 orphan 錨點正是卡在這個差上:本機 `docs_lint` 全綠、CI 全紅。
   **不變式(構造,不是紀律)**:錨點必須是一個**最終會進 origin/main 且 SHA 不被改寫**的 commit。與 `origin/main` 的 merge-base 永遠滿足;**自己分支的 HEAD 不滿足**——`cmd_cutover` 在 `merge --ff-only` **之前**先對分支跑 `git rebase <本地 main>`,rebase 把分支上每個 sha 改寫成 orphan。分支已貼著本地 main 時是 no-op、sha 得以保留,但那是常態不是保證,**不可依賴**。(孤兒成因的正本在 `ops/backlog.py` 的 ledger schema,此處不複述。)
   **已知代價,接受之**:錨在 base 意味著錨點不含本次改動。這是規則的內在性質、不是個案債,**不要為它開手動 re-bump 待辦**——那正是 IMP-0038 已經失敗過一次的方案(沒人記得做)。
   **機器守衛是 advisory 級,不是硬閘**(IMP-20260805-9bb2d2 起):`ops/docs_lint.sh` 的第一層仍是 **HEAD 可達**(ERROR),第二層才驗 **`$ORIGIN_REF` 可達**(預設 `origin/main`,可用 `KG_DOCS_LINT_ORIGIN_REF` 覆寫),命中時印帶機器 token `origin-unreachable` 的 **WARN** 加一個可照抄的替代 sha。**刻意只到 WARN**:worktree pre-cutover 錨在分支自身 commit 是合法情境,升 ERROR 會把整條 worktree 流程擋死——所以它會**提醒你**,但不會**代替你**。寫入前仍自己跑一次:
   ```
   git merge-base --is-ancestor <anchor> origin/main   # rc=0 才可寫
   ```
   **禁止**寫只存在於 worktree 分支的 ephemeral hash,也**禁止**寫字面 `HEAD`(自我滿足的錨點,任何可達性檢查都判不了它——已知 3 份 doc 是這個形狀)。

   **若錨點是由程式寫入的(generator / render / 任何自動化寫入點),另加兩條**——這兩條是實測換來的:`ops/backlog.py` 的錨點在三個版本裡錨到三個不同的錯值(HEAD → 宣稱 merge-base 實為 local main tip → local main merge-base),**三次 `docs_lint` 都綠**,因為它驗的是 HEAD 可達而三個錯答案全部滿足。那不是連續三次粗心,是**缺少能區分對錯的觀測**——在那種狀態下重寫幾次都一樣。
   - **fallback chain 不得靜默降級**:第一順位取不到就往下掉、卻不出聲,等於把「我錨到哪一級」變成不可觀測。降級必須 `stderr` 印出降到哪一級與原因。(同 IMP-0057 引的 "an enumerated hole beats an anonymous one";實例:`git merge-base --short` 不是有效選項,該 argv 永遠失敗並靜默落到 `git rev-parse --short main`,docstring 宣稱錨 merge-base 而程式物理上做不到。)
   - **每個寫入點都要有 origin-可達的正控斷言**,否則錯值與對值長得一模一樣:
     ```
     assert run(["git","merge-base","--is-ancestor", anchor, "origin/main"]).returncode == 0
     ```
     **判準會活得比實作久,所以這裡寫判準不寫實作**——指某支「照抄它」正是上述三次錯誤的載體。
   - **正控本身不得在缺少驗證對象時靜默 skip**。`if not has_origin_main: skip()` 讀起來合理(沒有 origin 就驗不了),但**缺 origin/main 的環境正是降級會發生的環境**——沒有 origin 的 clone、fetch 過期的機器、淺 clone 的 CI。於是斷言在最需要它的地方消失,而套件仍全綠。要嘛讓它**紅**並明說「此環境無法驗證錨點,先 `git fetch origin`」,要嘛把 skip **計數並在總結印出**,**不要讓它變成沉默**。這與上面兩條同源:三者都是「檢查存在但在該響的時候不可能響」。
5. 跑 `./ops/docs_lint.sh`,確認 **ERROR=0**。預設是日常 gate:驗 registry + 本分支/工作樹 changed docs,並用 `docs_impact.py` 印出 registry impact hints 供 reviewer 檢查；當 gate 偵測到 impact hints 時,也會直接提示 `./ops/docs_impact.py --since <base> --explain` 這條 follow-up 命令,方便追 suppression 細節，並明示「下面的 frontmatter checks 只覆蓋目前 checkout 裡有變更的 docs；non-doc 變更要以上方 impact hints 判讀」。`docs_lint.sh` 現在也會直接補一條 heuristic: `impact hints = sync candidates, STALE = freshness risk`，降低把 hint 當 hard requirement 的誤讀。若這次完全沒有 docs 被選進 lint,gate 也會直說,避免把 `no docs selected` 誤讀成工具無結論。impact hints 第一版 warn-only,不會因既有全 repo doc debt 失敗。
   需要全 repo 健康盤點時才跑 `./ops/docs_lint.sh --audit` 或 `--all`；audit 會暴露歷史 invalid anchor / stale debt,不得把既有 audit debt 當成本次 doc-sync 失敗。
   要盤點控制平面覆蓋率時跑 `./ops/docs_registry_coverage.py`；human output 會優先分 `active_unregistered`(應補進 registry 的活文檔)與 `backlog_unregistered`(archive/plans/specs/snapshot 等非日常 gate debt),並明示 backlog 只屬資訊、不屬日常 gate；不再重複把 backlog 傾倒成 generic `UNREGISTERED` 清單。`--help` 也會直接說 `--strict` 只對 active debt 失敗。`--strict` 只會因尚未登記的 active docs 失敗,用來追 registry coverage debt,不是日常 PR gate。
6. `git commit`,prefix `docs:`,訊息一句話講同步了什麼。結尾加:
   ```
   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
   ```
   git identity 用 repo global config(`Max0228`),**不要**手動 `-c user.email` 覆寫。

## 路由表(改了什麼 → 同步哪份)

| code 改動 | 同步 doc | tier |
|---|---|---|
| backend router / endpoint / DB table / env var / ops 腳本 / CLI subcommand | `docs/reference/tech_index.md` **(SoT)** | reference |
| 新增 user-facing feature(iOS / backend / admin / chrome) | `docs/reference/product_surface.md` **(SoT)** 追加 bullet | reference |
| iOS feature 重構(改檔名 / 分層 / 移檔) | 對應 `docs/reference/feature_boundary/<reader\|vocabulary\|notebook\|bookshelf\|podcast\|settings\|chrome>.md` | reference |
| UI 元件 / ViewModifier / 互動 pattern 新增或改 | `docs/reference/ui/components.md` | reference |
| UI / motion / 平台適配**規範**改變 | `docs/sop/ui-design.md` | sop |
| sync 狀態流轉(`syncStatus`×`actionType`) | `docs/reference/sync_lifecycle.md` **(SoT)** | reference |
| CSV / Card schema | `docs/reference/card_format.md` **(SoT)** | reference |
| host / port / container / Caddy 路由 | `docs/reference/host_topology.md` **(SoT)** | reference |
| 生產禁用指令 / preflight / rollback 規則 | `docs/policy/safety.md` **(SoT)** | policy |
| user/agent-facing 介面(admin endpoint / CLI flag / 設定 schema) | 另 grep `.claude/skills/`、`docs/sop/`、`docs/runbook/` 凡引用舊清單一併更新 | — |
| `lab/llm_eval/` 新增 prompt / dataset / judge / provider | `docs/reference/llm_eval.md` | reference |
| eval CLI 新增 flag / subcommand / output format / scoring rule | `docs/reference/llm_eval.md` + `docs/sop/llm_eval.md` | reference + sop |
| 文檔 workflow / registry / docs gate / impact detector / audit 語意改變 | `docs/registry.yml` + `docs/sop/doc_sync.md` + `docs/reference/tech_index.md` + agent/PR template 引用點 | registry + sop + reference |

## Tier 契約

- **contract / reference / policy** = 活契約或索引,改相關語意 surface 必同步 + bump `verified_against` 到 **`origin/main` 可達**的 code commit(判準與不變式見上方步驟 4;「local main 可達」不夠)。標 **(SoT)** 衝突時權威。
- **generated** = 機器產物,registry 必須有 `generator` **與 `check`**(等值檢查命令);不手改產物內容。`check` 缺了就是 `docs_lint.sh --registry` 的 ERROR;它一跑,產物與 generator 輸出不一致也會紅,並印出該跑哪條命令重生。
- **sop** = 流程變了才動;純實作變動不必碰。
- **policy** = 改動需在 commit message 說明原因。
- **snapshot / archive / legal / assets** = **不碰**(機器生成 / 凍結歷史 / 法務 / 行銷)。iOS 前端規模基線**不在此列也不在版控裡**:要當下數字就跑 `ops/gen_ios_baseline.sh`(只印 stdout,不寫檔),沒有產物要同步(IMP-20260808-b63206)。

## 邊界

- 只動文檔,**絕不碰 code**。
- 一次只處理交辦的 commit range。
- 簡潔:doc 追加用最小 bullet,不重寫整段。**完全禁簡體中文**。
