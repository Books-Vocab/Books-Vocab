<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Models/VocabularyEntry.swift
  - ios/BooksAndVocab/Views/Vocabulary/SyncView.swift
  - ios/BooksAndVocab/Views/Vocabulary/AutoSyncMonitor.swift
  - ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncCoordinator.swift
  - ios/BooksAndVocab/Views/Vocabulary/Scenes/KGVocabCoordinator.swift
  - ios/BooksAndVocab/Views/Vocabulary/Scenes/NotebookReconciler.swift
  - ios/BooksAndVocab/Views/Reader/ReaderVocabularyContext.swift
  - ios/BooksAndVocab/Views/Podcast/PodcastVocabularyContext.swift
  - ios/BooksAndVocab/Services/AuthManager.swift
  - ios/BooksAndVocab/Services/BackgroundSyncActor.swift
  - ios/BooksAndVocab/Services/KGService+Sync.swift
  - ios/BooksAndVocab/Services/KGService+VocabCRUD.swift
  - ios/BooksAndVocab/Services/KGService+Models.swift
  - backend/src/kg/api_models/vocab.py
  - backend/src/kg/routers/vocab.py
  - backend/src/kg/vocab_intake.py
  - backend/src/kg/vocab_crud.py
  - backend/src/kg/vocab_handlers/intake.py
  - backend/src/kg/vocab_handlers/crud.py
verified_against: 0c9e3b7c8
-->
# Sync Lifecycle

這份文件描述 Books & Vocab 本地生詞與 KG 雲端同步時的最小規則，目的不是講實作細節，而是固定「每種狀態應該怎麼表現」。

## 核心欄位

- `syncStatus`
  - `0`: `pending`
  - `1`: `synced`
  - `2`: `failed`
- `actionType`
  - `add`
  - `delete`
  - `edit`

Swift 端應優先透過 `VocabularyEntry` 的 typed helper 使用這些狀態，而不是直接散落比較 magic number 或 magic string。

## 規則表

| 狀態 | 代表意思 | 會出現在閱讀器 | 會出現在待同步 | 會出現在知識庫 |
| --- | --- | --- | --- | --- |
| `pending + add` | 本地新增，待送上雲端 | 是 | 是 | 否 |
| `synced + add` | 已與雲端一致 | 是 | 否 | 是 |
| `pending + delete` | 本地已要求刪除，待送上雲端 | 否 | 是 | 否 |
| `failed + add` | 上次新增同步失敗，可重試 | 是 | 是 | 否 |
| `failed + delete` | 上次刪除同步失敗，可重試 | 否 | 是 | 否 |

## 主要轉移

### 本地新增單字

1. 建立 `VocabularyEntry`
2. 呼叫 `restorePendingEntry()`
3. 顯示在閱讀器與待同步清單

### 本地新增上傳成功（`pending + add` → `synced + add`）

1. `SyncCoordinator` 批次上傳 → `POST /api/vocab` 回 `VocabAddResponse{ cardIds, duplicates, ... }`
2. **`cardIds` 以 client 送出的『原始』word 為 key**（非後端清洗後的 word），`created` 與 `duplicate`（已存在）兩種情況都回填對應 card id
3. 對每筆 entry：`response.cardIds[entry.word]` 命中即回填 `kgCardId` 並 `markSynced()` 直接出列
4. **不變式**：收斂依據是回傳的 cardId（= 卡片確實存在 server，權威確認），**不**靠 pull-merge 用 content 字面比對——後端 `_clean_content` 會 strip 尾標點 / 首字小寫（如 `"chateau,"`→`"chateau"`），content 比對跨此邊界必然 miss，曾導致該類 entry 永久卡在 `pending + add` 重送（修復見 vocab_intake：response key 改回原始 word）
5. 無 cardId 回傳（異常）的 entry 保持 `pending + add`，下次重試
6. **不變式（contract）**：`cardIds` 的 key 必須是 client submitted word 的 **byte-exact echo**，後端**不得**對 key 做任何 normalization（NFC/大小寫/trim）——iOS 以 `entry.word` 逐字節查找，任何後端側轉換都會讓配對 silent miss。清洗只作用於**儲存的 content**，不作用於 response key

### 已同步單字被刪除

1. 既有單字先是 `synced + add`
2. 使用者刪除時呼叫 `queueDelete()`
3. 單字立刻從閱讀器與知識庫隱藏
4. 等下一次同步把刪除請求送到 KG

### 雲端資料拉回本地

1. 若本地是 `pending + delete`，保留本地刪除意圖，不被遠端覆寫
2. 若遠端卡片存在且未刪除，合併內容後呼叫 `markSynced()`
3. 若遠端回傳 soft delete，本地直接刪除

**merge 回報實際變動量**（`BackgroundSyncActor.PullResult` → `KGPullOutcome`）：pull 回傳 `inserted` / `updated` / `deleted` 三個計數，`hasChanges` 即三者之和 > 0。UI 憑此區分「同步真的改了東西」與「同步跑完、什麼都沒變」。

- `updated` 只計**使用者可見內容**真的不同的詞條，判準集中在純函式 `BackgroundSyncActor.contentDiffers(card:from:)`（translation / pos / note / difficultyTier / inflections / collocations / examples / mode / graphLinks / isArchived / notebookId / book source）。
- **複習狀態刻意不算變動**（`lastReviewedAt` / `reviewCount` / `nextReviewAt` / `streak` / `lapse`）。它每次複習都由本機推上去、下一輪 incremental pull 再原樣拉回；若計入，任何一次複習後的同步都會被判為「單字庫有變化」——這正是要避免的假陽性。
- SwiftData 對屬性是「指派即髒」，所以判準必須在覆寫欄位**之前**取樣，事後問 `hasChanges` 得不到答案。

### 批次刪除 / 封存回應的三個 bucket：`*_words` / `not_found` / `failed`

batch-delete（`POST /api/vocab/batch-delete`）與 batch-archive（`PATCH /api/vocab/batch-archive`）回傳**三個互斥清單**（後端 `kg/vocab_crud.py`）：

| bucket | 語意 | server 端狀態 | client 應對 |
| --- | --- | --- | --- |
| `deleted_words` / `updated_words` | 這次操作成功 | 卡片已刪 / 封存狀態已改，graph 已同步 | 本地收斂（成功語意） |
| `not_found` | **lookup 查無此字**（前一次已刪 / race） | server 上本就不存在 | 本地收斂（成功語意，刪除意圖已達成） |
| `failed` | graph 操作失敗已**回滾** | 卡片**仍存在 server**（原狀態） | **不可收斂**；保持 `failed + delete/edit`，下次 sync 重試 |

- `failed` 鍵是**向後相容的附加欄位**（Pydantic `BatchDeleteResponse` / `BatchArchiveResponse` 預設空 list）。舊 client 忽略未知鍵即可；關鍵改動是 graph-失敗的字**不再**出現在 `not_found`，因此舊 client 也不會再把仍存在 server 的字誤收斂（#720）。
- **可本地收斂集合 = `deleted_words ∪ not_found`**（`SyncCoordinator.locallyResolvableDeletes(from:)`，`SyncCoordinator` 與 `KGVocabCoordinator.retryPendingDeletes` 共用此純函數）。
- **封存同理可本地收斂集合 = `updated_words ∪ not_found`**（`KGVocabCoordinator.locallyResolvableArchives(from:)`）。`not_found` 代表 server 已無此字，封存意圖對本地而言已可收斂；`failed` 才保持未收斂並重試。
- `failed` 內的字（或任何「三個 bucket 都不在」的字）才 `markSyncFailed()` 進重試。
- 後端 batch lookup key 為 `_normalize_word(_clean_content(word))`：尾標點 / 首字大小寫等儲存層清洗後等價的輸入會命中同一張卡。完全相同的 submitted word 只執行一次；同一清洗 key 的不同 submitted word 會沿用首次 outcome，但 response bucket 仍 echo 各自的原始 word，讓 iOS 以本地 `entry.word` 收斂。
- **不變式 1**：絕不可把 `not_found` 當刪除失敗 → 否則永久卡死的隱形重試迴圈。
- **不變式 2**：絕不可把 `failed` 當成功收斂 → 該字 server 仍存在，本地移除會造成 client/server 永久分歧（#720 根因；後端已把 graph-失敗字從 `not_found` 移到 `failed` 修正此半邊）。

### 同步失敗後重試

1. 上傳新增或刪除失敗時，單字會先標記為 `failed`
2. 同步頁仍會把它算進待處理項目
3. 下一次同步前，App 會自動把 `failed` 轉回 `pending` 再重試
4. 若失敗的是刪除，單字仍維持隱藏，避免違反使用者已經做出的刪除決定
5. **`not_found` 不是失敗**（見上節）— 已不存在於 server 的字本地直接收斂，不進此重試迴圈；反之 batch 回應的 `failed` bucket 才是 server 端 graph 操作失敗（卡片仍在），須進此重試迴圈

## 同步觸發鏈

### `pullCardsToLocal` single-flight（所有 pull 路徑共用）

vocab pull 有五個呼叫點：`KGVocabView.task`（進頁自動）、pull-to-refresh、錯誤 banner 的重試、`SyncCoordinator` 的 pipeline 輪詢、以及 `backgroundSync`。過去只有 `backgroundSync` 有 claim 鎖，其餘各跑各的——生產日誌可見同一個 `?since=` cursor 被兩個請求同時帶出去（兩輪在對方寫回 boundary 前各自讀了同一個值）。現在 `KGService.pullCardsToLocal` 是一層 single-flight wrapper：

- **同 `notebookId` 的併發呼叫合流**到同一輪 pull，只發一次 `GET /api/vocab`；合流者拿到結果，但 progress 回呼只給發起者。
- 實際工作跑在 **unstructured `Task`** 裡，因此**不繼承呼叫端的取消**。從 `.task` / `.refreshable` 發起的 pull 不會因為 view 重繪或離場而被砍掉——那正是舊行為把 `URLError.cancelled`(-999) 一路包成 `KGError.networkError`、在使用者面前顯示「網路錯誤：已取消」的成因。
- 取消不是失敗：`authenticatedRequest` 把 -999 轉成 `CancellationError`，`backgroundSync` 的 phase 回報略過它，單字本 banner 也不因它改變畫面。

`KGService.backgroundSync` 是共用 resync 入口，由以下觸發：post-login / scenePhase→active / ⌘R menu / Settings 手動同步。其執行序：

0. **logout-cleanup gate**（claim 鎖成功後、任何 sync 工作前）— `await sessionInvalidator.waitForPendingLocalDataCleanup()`。詳見下節「logout-cleanup gate 不變式」。
1. vocab pull / push（本文上述狀態流轉）
2. **podcast catalog**（Phase 3，序執行於 vocab pull 後）— `PodcastSyncService.syncAll` 併入 backgroundSync，使 podcast catalog 共用上述所有觸發；自我防禦、不 throw，失敗僅記 log 不影響 vocab。**不變式**：空 server list（`/api/podcasts` 回 `[]`）視為非權威，reconcile **不**對 series/episode 下 tombstone（避免 S3 index 短暫讀不到時 mass soft-delete）。詳見 `docs/reference/feature_boundary/podcast.md §同步觸發`。

## 複習事件上傳水位（review-event push watermark）

複習事件（`ReviewRecord` → `PATCH /api/vocab/review-events`）是 **append-only 帳本**，不進上述 `syncStatus × actionType` 狀態機；它自己的收斂條件是**水位**而非狀態轉移。

- **水位欄位（不變式）**：`ReviewRecord.pushedAt: Date?`。`nil` = 尚欠伺服器。`buildReviewEventsPushPayload` 只取 `pushedAt == nil`，並依 `reviewedAt` 遞增排序。
- **為何需要**：後端以 `event_id` 去重，client 端若無水位就無法區分「已上傳」與「新事件」，只能整份重送。2026-08-05 生產實測（帳號 000287）：9,542 筆事件、約 3.4MB、10 次序列 PATCH，佔一次同步 17s 中的 15.4s，伺服器每次皆回 `inserted=0, skipped=9542`。
- **逐批確認（不變式）**：`pushReviewEvents` 在**每個 batch 回應後**立即 `markReviewEventsPushed`，不是整輪結束才記。batch 才是伺服器實際接受的單位；後續 batch 失敗（離線 / 401 / 此突發自身觸發的 429）不可回退已落地的批次——這正是大量歷史事件能**跨多次同步分批排空**而非每次從頭的原因。
- **拉回即已確認（不變式）**：`mergeReviewEvents` 對插入的遠端事件直接寫 `pushedAt`。它來自伺服器就已在伺服器上；不標記會讓下一次推送把整份拉回的歷史原樣送回，水位永遠排不空。
- **遷移策略（刻意不 backfill）**：欄位為 optional，既有列一律以 `nil` 進場、在升級後第一次同步完整排空一次——成本恰等於舊行為，且不可能把「其實從未上傳成功」的事件誤標為已上傳。之後穩態為 ~0。

伺服器端對應：`ReviewEventStore.insert_many` 以分塊 `IN` 查詢一次取回已存在的 `event_id`（chunk 500，低於 SQLite 3.32 前 999 個繫結變數上限），取代逐筆 `session.get`。同一批 payload 內重複的 `event_id` 由迴圈內累加的 id 集合擋下（舊版靠 autoflush，改批次取回後必須顯式維持）。

## logout-cleanup gate 不變式（重登↔sync 競態防線）

`AuthManager.logout` 排程的本地清理（`clearLocalData`）會跳 `BackgroundSyncActor`、是真實 suspension。快速「登出→重登」時，若 sync 在 cleanup 收尾前動工，會搶用尚未清乾淨的 sync boundary 跑 incremental（後端全部 skip → 本地空庫卻自認最新），且拉回的資料又被 resume 的 cleanup 再清一遍 —— 2026-06-09 帳號 000287 單字本事故根因。防線：

- **單點 gate（不變式）**：sync 動任何工作前必先等 logout cleanup 鏈收尾。gate 只在 `backgroundSync` claim 鎖成功後的**唯一入口**生效（`await sessionInvalidator.waitForPendingLocalDataCleanup()`），因此**四個觸發點（post-login / scenePhase→active / ⌘R menu / Settings 手動）全部**自動經過同一道 gate；call site 不再各自重複 gate。無 pending cleanup 時 gate 立即返回（正常冷啟登入不被拖慢）。
- **cleanup 鏈化（不變式）**：連續 logout 時 `pendingLocalDataCleanup` 保留前一個 handle 並 chain（新 cleanup `await previousCleanup?.value` 才動工），故同一時間至多一個 cleanup 跑、零互踩。gate 只 await 最新 handle 即隱含前序全部收尾。
- **generation re-check（防 TOCTOU）**：`waitForPendingLocalDataCleanup` 進場記 `localDataCleanupGeneration`，await 完若 generation 已被新 logout 遞增則重 loop，直到鏈上最後一個 cleanup 完成 —— 單次 await 只跟得到進場當下 handle，re-check 補住懸掛期間又 logout 的窗口。
- **gate 期間被擋的是同一次 sync（不變式）**：sync 被 gate 擋下等待，等待結束後**是同一次 sync 繼續往下跑**（非取消後補跑），因此「等 cleanup」與「跳過這次 sync 待下次補跑」語意等價，**不會漏 sync**。
- **Accepted residual**：gate 通過後、sync 真正動工前，caller（非 MainActor 的 `backgroundSync`）resume 有一次 executor hop；logout 恰落在此窗口仍會與新 cleanup 並行。徹底閉合需 sync 內部 generation re-check/abort（另案），現靠空庫安全網 + 帳號切換清 boundary 緩解。

## 知識圖譜變更的傳播（server 端 touch barrier）

知識圖譜連結（建立 / hide / unhide / delete）本身不在上述 `syncStatus` 流轉中。client 透過 `get_modified_since(updated_at)` 抓 card 增量，看到 card 變更後**重拉該 card 的 links**。因此每個 graph op 必須在改完 graph 後 **bump 兩端 card 的 `updated_at`**（`cards_store.touch`），否則 graph 變了但 client 永遠抓不到 → 靜默不一致。

- **不變式**：graph 變更後 touch 失敗**不可被吞掉**。`backend/src/kg/vocab_graph_ops.py:_touch_both` 保證：兩端皆嘗試 touch（一端失敗不跳過另一端，只要任一端 `updated_at` 前進 client 仍能收斂）、失敗 `logger.error`（可觀測）並 re-raise（不假裝成功）。
- **可逆 op（hide / unhide、create 的 unhide 分支）**：touch 失敗時回滾 graph 變更，使 graph 與 card 狀態一致。
- **不可逆 op（hard delete、create 新連結）**：不乾淨回滾，僅靠 barrier 的「可觀測 + re-raise」。
- **notebook 隔離硬化（manual link）**：card store 為 per-user、graph 為 per-notebook，故 `create_manual_link` 必填 `notebook_id`，兩端卡片的 `notebook_id` 須等於之，否則以 `NotFoundError(404)` 拒絕（語意：該卡不存在於此 notebook），杜絕跨 notebook 連結。後端為權威；iOS `AddLinkSheet` 候選 filter 額外加 `notebookId == sourceEntry.notebookId` 做 defense-in-depth（#776，`backend/src/kg/vocab_graph_ops.py`）。

## 共享牌組（Explore）與 sync 邊界

共享牌組庫（Explore）**不進**上述 `syncStatus × actionType` 狀態機：

- **browse = guest-tolerant public GET**：`SharedDeckCatalogService`（`PodcastSyncService` analog）走 `/api/decks*` 唯讀 mirror，router 無 auth dependency、容忍過期 bearer→guest；upsert 進獨立 `SharedDeck @Model`（**非** `VocabularyEntry`/`Card`），**永不進 client outbox**，故不觸發 vocab 上傳/刪除轉移。reconcile 保 empty-response mass-delete guard（空 server list 視為非權威、不下 tombstone），與 podcast catalog 同範式。
- **copy provenance（`source_shared_deck_id`/`source_version`/`source_shared_card_guid`）**：欄位 day-one 建（`Card` / `Notebook` / `NotebookResponse` / iOS `Notebook @Model`）；browse（Phase 1）**不 stamp**、pull-only，**Phase 2 server-side copy 寫入**。契約結構在設計時已 anticipate、落地後不變：複製卡由 server 蓋 fresh `updated_at`，經**既有 incremental pull**（`?since` / post-copy notebook-first targeted pull）作為**已 synced server rows** 落地（**NO SRS / graph transport**——SRS 全新、graph link server 端 remap，皆不經 sync 傳輸），**永不進 outbox**，故本 `syncStatus × actionType` 狀態機結構性不受影響（詳見 `docs/plans/2026-07-09-shared-decks-library.md §4.1`）。

## Phase 2 之後的建議

- 若未來真的用到 `failed`，要補明確 retry 規則
- 若未來支援編輯詞卡內容，`edit` 需要獨立轉移表
- 若同步流程再變複雜，優先擴充這份文件與測試，而不是把邏輯散回各個 View
