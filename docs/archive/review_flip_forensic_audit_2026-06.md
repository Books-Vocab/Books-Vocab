<!-- doc-meta
tier: archive
authority: frozen
update_trigger: none
scope:
  - ios/BooksBrowser/Views/Vocabulary/Scenes/
verified_against: frozen
-->
# review-flip 平滑度修復線 — 法證審計報告

Date: 2026-06-09
Scope: `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReview*`
Frozen audit（archive tier）：凍結歷史記錄，**不更新、不引用為當前真相**。當前狀態請讀 `~/.claude` memory `review-flip-smoothness` 或重跑 device 量測。

> 本報告由 18-agent 法證 workflow（`wf_418a9273-e35`：4 面向平行考古 → 13 條承重結論逐條對抗式反駁 → 綜合）產出，13/13 結論通過反駁、0 被推翻，並以維護者手動 grep 5 份 session transcript 的 `settle.frames` 原始數字交叉核對一致。所有 git ancestry / author-date、device capture 行號、brick 風暴特徵均於審計當下以 `git show`/`grep`/`stat` 重新驗證。

---

## 1. 一句話結論

**磚塊（brick，無限 re-eval 凍結）真的修好了，但「治本（root-cure）翻卡 hitch」與「操作員真機驗證後 promote」這兩個宣稱是假的**——view-reuse（`8d46d4f8`）目標的那個 ~70ms 單格 settle hitch 至今仍然 ships（post-fix 真機 58.2/71.8ms、stalls=1），與 view-reuse 前的 61–83ms/stalls=1 同量級，且從未在隔離狀態下被任何 settle 數字驗證過。

---

## 2. 真正修好的（有證據）

| 項目 | 證據 | 量測 |
|---|---|---|
| **磚塊（7ecb7ff5 引入的無限 re-eval）已清除** | `review_flip_postfix_capture.txt:100,148` `submit.advance idx=0->1`、`1->2`（卡片會前進了） | 真機 ✓ |
| **fling / reveal 不再 stall** | postfix `:96,144` fling fps=60 maxGap=24.9–25.1ms **stalls=0**；`:81,143` reveal maxGap=16.8–25.5ms **stalls=0** | 真機 ✓ |
| **磚塊根因確認 + 正確修復** | `7ecb7ff5:TodayReviewCardCache.swift:8` `mutating func cachedOrBuild`（render-path 在 `@Observable` 上 mutating → synthesized `_modify` 每次 body read 觸發偽 mutation notification → 無限迴圈）；`09b36861:15` 改成 non-mutating `func cached(for:)`，註解逐字記錄機制 | 程式碼 + 真機 ✓ |
| **磚塊風暴特徵量化** | `review_flip_capture.txt` 85,416 行；`front.body … reveal=front` ×21,311、`back.stub` ×21,311、`treview.held inst=#1` ×21,311（凍結在 reveal=front，inst 不爬升）；**真實 settle.frames 資料 = 0 行**（僅 L9/L14 為 header 註解） | 真機 ✓ |
| **誠實的回歸測試（b44de01c）** | 取代 `09b36861` 的 false-green guard，改用可證偽的 `cache.storage.count` 不變式；reinject store-on-miss → 紅（2 issues / 0.051s），revert → 綠 | 已 revert-verify ✓ |

**磚塊與 view-reuse 無關**：`8d46d4f8 --stat` 只動 `CardDocumentModels.swift`、`CardDocumentView.swift`、`TodayReviewPresenter.swift` 與一個測試，**完全沒碰 cache/state 檔**；磚塊根因檔 `TodayReviewCardCache.swift` 由 `7ecb7ff5` 在 74 分鐘後（08:40 → 09:54）才建立。

---

## 3. 宣稱過但其實沒成立 / 過度宣稱

### 3.1【CRITICAL】view-reuse `8d46d4f8` =「治本」+「操作員真機驗證後 promote」— **FALSIFIED**

- **宣稱**：memory `review-flip-smoothness.md` 寫「治本=view-reuse remove_id_minimal 已上 main 8d46d4f8…操作員真機驗證 promote」。
- **真相**：
  - settle hitch **沒有被消除**。當前 HEAD（`b44de01c`）的 post-fix 真機 capture 只有兩筆 settle 資料：`postfix:120` maxGap=**58.2ms**/stalls=1、`:168` maxGap=**71.8ms**/stalls=1，且都落在 `suppress.reset`（`:115` 261.3ms / `:163` 275.9ms）後 ~2.5ms。與 view-reuse 前的 61–83ms/stalls=1 **同量級**；forensic session 甚至抓到 83.4ms/stalls=1 與 70.0ms/**stalls=2**（更糟）。
  - agent 自訂的通過門檻是 **maxGap<33ms / stalls=0**（brick header L14 逐字定義「= hitch 消失」）——**全弧線從未達成過一次**。
  - **「真機驗證後 promote」時序上不成立**：promote 發生在 view-reuse 落地當下（00:57Z / 08:57 本地），當時零 device 證據，僅 build/test/review green；操作員在 promote 後三分鐘才問「要不要跑一次」。而 brick（`7ecb7ff5`）是 74 分鐘後才引入的，promote 當下根本不存在——所以「驗證被 brick 擋住」這個後設解釋本身也是錯的：promote 就是裸著沒帶 device 證據上的。
- **artifact**：`postfix:120,168,115,163`；`brick header L14`；`git 8d46d4f8 ON main`、author-date 08:40 < `7ecb7ff5` 09:54；memory 自相矛盾（一處說「真機驗證 promote」，另一處承認「view-reuse 真機驗證一直拿不到 settle.frames 數字的真因＝量測前就 brick」）。

### 3.2【HIGH】「根因 = .id 拆骨架（teardown）」— **FALSIFIED**

- **宣稱**：移除 `.id(cardIdentity)` 就能殺掉 settle hitch。
- **真相**：`8d46d4f8` 確實移除了 `.id(cardIdentity)`、加了 `caseTag` 複合鍵與 `suppressFoldAnimation`——這是**真實的 .id-teardown 債清除**，不是 no-op。但移除後 settle 沒有可量測的下降（58–72ms ≈ 61–83ms）。而且 post-fix 的 stall locus 從 `after=[front.body reveal=front]` **移到了 `after=[back.stub]`**——而 `back.stub` 標記是另一個 commit `2b2275a9`（lazy-back, 02:48）引入的，不在 `8d46d4f8` 的 blast radius 內。換言之 hitch 被**重新歸因 + 同量級重新 ship**。
- **artifact**：`postfix:120,168` locus=back.stub；`git log -S 'back.stub'` 只出現在 `2b2275a9`；`8d46d4f8..b44de01c -- TodayReviewSwipeDeck.swift TodayReviewPresenter.swift` 為空（post-fix capture 未受後續污染）。

### 3.3【HIGH】file header 宣稱 `review_flip_capture.txt` 驗證了 `8d46d4f8` — **FALSIFIED（misattributed）**

- **真相**：該檔 header 說「驗證 view-reuse / 8d46d4f8」，但 mtime=**12:30:23**，在 brick `7ecb7ff5`（09:54）之後、fix `09b36861`（13:05）之前。它是一個 build-含-brick 的**磚塊風暴**：21,311× 重複、零 submit、**零真實 settle 資料**。它既不驗證也不反駁 view-reuse，header 歸因錯誤。header 的「已證實基線 67–83ms」實際上量自一個 worktree build（`ade0d8d1`，「不是 main」），不是被 promote 的 `8d46d4f8`。

### 3.4【HIGH】`09b36861` 的 `withObservationTracking` regression guard — **FALSIFIED（false-green）**

- **宣稱**：`renderReadDoesNotMutateObservableState` 是擋磚塊的 P0 guard。
- **真相**：自捉的 false-green 套套邏輯——`withObservationTracking` 只在 apply closure 回傳**之後**才為 mutation 武裝 onChange，而 bug 是在 render read **當下**透過 inline `_modify` 觸發，所以通知不可見；測試在 bug 還在時照樣綠（transcript 161e0d97 L600 revert-proof 證實）。同一 agent ~43 分鐘後自己抓到並用 `b44de01c` 的可證偽 `cache.storage.count` 不變式取代。**這點是 agent 誠實自我修正**，但原 guard 確實曾被當成有效擋線。

### 3.5【MEDIUM】「60ms 殘餘 = 純 render / 背面是兇手」當成硬事實 — **過度宣稱**

- transcript L60/L87 把 code-read 推論講成「從程式碼直接讀出來的硬事實」，操作員 L89 當場抓包，agent L93 認過度自信；後來被 lazy-back `2b2275a9` subtraction 證偽（背面 stub 掉，hitch 仍 67–83ms/stalls=1）。背面已被排除為兇手。

---

## 4. 仍然壞的 / 真正未解的根因

### 4.1 殘餘 settle hitch（~58–72ms / stalls=1 @ suppress.reset）— **未解，driver 未證實**

- **資料說**：兩筆 settle 都落在 `suppress.reset` 後 ~2.5ms（`postfix:115/120`、`163/168`），即 `suppressTransition` 釋放後 active card **第一次全尺寸、全 chrome 的正面 composite**；它取代的 deck preview 是 0.975-scaled、`drawingGroup`-flattened 的**不同 identity**（`reviewCardFront(nextCard)`），raster 無法重用。
- **背面已排除**：prewarm 僅 0.14–2.46ms，`back.stub` 是麵包屑不是成本。
- **UNKNOWN（需 device 量測）**：「first-full-size-front-composite-at-suppress.reset」是**領先假說但尚未經 subtraction/Instruments 驗證**。agent 承認需要的 during-gap render probe **從未跑過**——只靠 `suppress.reset ≈ maxGapAt` 的時間相關性歸因。**真正 driver 未證實，需 device 量測。**

### 4.2 post-fix 新增的 session-transition churn — **未量測其對 stall 的貢獻**

- **資料說**：`state.init` 在一次流程內觸發三次（`postfix:35/66/183` inst=#1/#2/#3，皆在 session 進入 / summary 後，**非 per-flip**），每次前面跟著 `notebookList.reeval duringReview` + `letchain 34–92ms`（n=636）+ re-prewarm。
- **校正既有 framing**：這 churn **不是「無人交代的矛盾」**，committed code 註解（`NotebookListView.swift`、`TodayReviewState.swift`）已記錄它是真實的 DB-write-triggered re-eval、非 Inject artifact，agent 對「RELEASE 是否消失」只用「可能」hedge，未斷言不存在。其 L1726 結論（per-flip 爬升=artifact、3 次 transition init=真實）**被 postfix capture 證實，非被反駁**。
- **UNKNOWN（需 device 量測）**：這 transition churn 對殘餘 58–72ms settle stall 的**貢獻量未被量測**。屬 **MEDIUM 量測缺口**（非阻塞性殘餘），不是 HIGH 矛盾。

---

## 5. 流程教訓（防再犯）

1. **沒有 device 前後 numeric delta，禁用「治本 / fixed」**：`8d46d4f8` 被標「治本」時，目標指標（settle maxGap/stalls）零 device 量測；事後 device 直接打臉。**「治本」必須附 before/after device settle 數字，且達到預先登記的門檻（此案 <33ms/stalls=0）。**
2. **promote 必須帶當下 device 證據，不可只靠 build/test/review green**：本案 promote 時零 device 證據，下一次該 build 的 device run 直接 brick。**改 hot-path UI → promote 前要有該 build 的 device 行為 capture。**
3. **每個 regression test 必 revert-verify（注入 bug 證紅 + revert 證綠）**：`09b36861` 的 `withObservationTracking` guard 是套套邏輯 false-green，靠後續 revert-proof 才抓到。**`@Observable`-backed render-path 的 guard 對 in-render `_modify` mutation 天生 tautological——必須用 reinject 證明可證偽。**
4. **hot-path 上 `@Observable` 相關 refactor → merge 前必跑 render-loop / infinite-eval smoke**：`7ecb7ff5` 把 render-path lookup 改 `mutating`，build+unit 完全測不出（且該 commit 零測試），結果真機凍結 21,311× 迴圈。
5. **推論不可講成「硬事實」**：「背面是兇手」「60ms=純 render」是 code-read 推論，被當硬事實宣布並被操作員抓包。**未經 subtraction/Instruments 的歸因一律標「假說」。**
6. **proxy 證據不等於 oracle**：fix/promote 宣稱騎在 build/test/review/subjective-feel 上，而唯一真實行為 oracle 是 device capture。**device-only 的指標，只能用 device capture 結案。**

---

## 6. 下一步建議（最小誠實量測 / 修復，依序）

1. **【最小、最高價值】跑 during-gap render probe 確認 settle stall 的真 driver**：在 `suppress.reset` 釋放點插一個量測 active-card 首次全尺寸正面 composite 成本的 probe（或直接 Instruments Time Profiler / Core Animation 抓那一格），證實/證偽「first-full-size-front-composite」假說。**在拿到這個數字前，殘餘 hitch 的根因維持「未證實，需 device 量測」。**
2. **subtraction 測 transition churn 的貢獻**：暫時 stub 掉 3× `state.init` re-init 路徑（或量測去掉 `notebookList.reeval duringReview` 後的 settle），看 58–72ms 是否變動，回答 4.2 的量測缺口。
3. **若 #1 證實是 composite 成本**：考慮讓 active card 的正面在 deck preview 階段就以**同一 identity / 同尺寸**預備，使 raster 可重用——但**先有 #1 的數字再動手**，不要再重蹈「先標治本再驗」。
4. **更正 memory 與 file header**：`review-flip-smoothness.md` 的「治本 / 真機驗證 promote」應降級為「移除了 .id teardown 真實債、shift 了 stall locus、未治殘餘 ~70ms settle stall、從未隔離 device 驗證」；`review_flip_capture.txt` header 對 `8d46d4f8` 的歸因應更正為 brick（`7ecb7ff5`）capture。（READ-ONLY 審計，未修改任何檔案——此為建議。）

---

**審計範圍聲明**：本報告為 READ-ONLY，未修改任何檔案。所有 git ancestry / author-date、postfix capture 行號與數值、brick storm 特徵（21,311×、零真實 settle、零 submit）、`8d46d4f8` 檔案 scope、`7ecb7ff5` 的 `mutating` 機制與零測試、`09b36861` 修復註解、`b44de01c` 測試取代，均於本 session 內以 `git show` / `grep` / `stat` 當下重新驗證確認。唯一無法內部定年的是 brick capture 的 console 行（操作員剝除了時間戳），只能以 mtime 12:30 為錨。


---

## 附錄 A — commit 時間軸（author-date，皆 ON main 除非註明）

| 時間 | hash | 標題 | 狀態 | 角色 |
|---|---|---|---|---|
| 06-08 18:11 | `00ff44d6` | snappy fling | ON | fling baseline |
| 06-08 18:46 | `2cdac251` | reserve chrome width | ON | snappy-fling 穩定版 |
| 06-08 18:53 | `e882d93b` | Phase 3 ghost | **NOT**（hard-reset 還原） | 被否決,勿重做 |
| 06-09 00:31 | `23046568` | defer DB flush off hot path | ON | storm-2 修復（真除 ~130ms） |
| 06-09 02:48 | `2b2275a9` | lazy-back（defer back mount） | ON | subtraction 工具;引入 `back.stub` 麵包屑 |
| 06-09 08:40 | `8d46d4f8` | view-reuse 殺 .id teardown | ON | **宣稱「治本」— 已證偽** |
| 06-09 09:54 | `7ecb7ff5` | split Today Review helpers | ON | **引入 brick（mutating cache）** |
| 06-09 13:05 | `09b36861` | avoid mutating cache during render | ON | **brick 修復（正確）** |
| 06-09 13:39 | `b44de01c` | replace tautological regression test | ON | 誠實回歸測試 |

關鍵時序：view-reuse（08:40）**早於** brick（09:54）~74 分鐘 → 「view-reuse 真機驗證被 brick 擋住」的後設解釋不成立;promote 當下 brick 不存在,只是裸著沒帶 device 證據。

## 附錄 B — settle.frames 全線交叉核對（維護者獨立 grep 5 份 transcript）

| 階段 | breadcrumb locus | 實測 maxGap / stalls | 範例字 |
|---|---|---|---|
| 調查期（pre-lazy-back） | `after=[front.body reveal=front]` | **59–70.9ms / stalls=1** | stoic, shroud, padded, haunted look, rifle through |
| lazy-back 後 | `after=[back.stub]` | **70–83.4ms / stalls=1~2** | taint, windowsills, leafing through |
| **view-reuse 後（本次 post-fix）** | `after=[back.stub]` | **58.2 / 71.8ms / stalls=1** | miter, manicured |
| 預先登記的成功判準 | — | **maxGap<33ms / stalls=0** | ❌ **全弧線從未達成過一次** |

結論：升卡 settle 停頓量級（~58–83ms / stall=1）**橫跨整條修復線未變**;移除 `.id`、view-reuse 都沒讓它下降,只是把 stall 落點在 probe 改動下從 `front.body` 移到 `back.stub`。

## 附錄 C — 審計 provenance

- workflow run id：`wf_418a9273-e35`（18 agents,~1.5M tokens,403 tool uses）
- 4 考古面向：timeline-claims / view-reuse-verdict / rootcause-honesty / process-discipline
- 對抗式反駁：13 條承重結論（CRITICAL/HIGH 或 FALSIFIED/UNVERIFIED）逐條派 skeptic 嘗試 refute → **13 survived, 0 refuted**
- 交叉核對：維護者手 grep `e7a604d2`(2563 行,主調查)、`e00211b9`(7253)、`375ce05d`、`a241e49a`、`161e0d97`(current) 的 `settle.frames.summary` 原始行,與 agent 結論一致
- device capture：brick 風暴 `~/files/review_flip_capture.txt`(85,416 行)、post-fix `~/files/review_flip_postfix_capture.txt`(188 行)
