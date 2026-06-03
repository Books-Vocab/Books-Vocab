<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/BooksBrowser/
  - backend/src/kg/
verified_against: 613a2528
-->
# Sync Lifecycle

這份文件描述 BooksBrowser 本地生詞與 KG 雲端同步時的最小規則，目的不是講實作細節，而是固定「每種狀態應該怎麼表現」。

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

### 已同步單字被刪除

1. 既有單字先是 `synced + add`
2. 使用者刪除時呼叫 `queueDelete()`
3. 單字立刻從閱讀器與知識庫隱藏
4. 等下一次同步把刪除請求送到 KG

### 雲端資料拉回本地

1. 若本地是 `pending + delete`，保留本地刪除意圖，不被遠端覆寫
2. 若遠端卡片存在且未刪除，合併內容後呼叫 `markSynced()`
3. 若遠端回傳 soft delete，本地直接刪除

### 批次刪除 / 封存回應的三個 bucket：`*_words` / `not_found` / `failed`

batch-delete（`POST /api/vocab/batch-delete`）與 batch-archive（`PATCH /api/vocab/batch-archive`）回傳**三個互斥清單**（後端 `kg/vocab_crud.py`）：

| bucket | 語意 | server 端狀態 | client 應對 |
| --- | --- | --- | --- |
| `deleted_words` / `updated_words` | 這次操作成功 | 卡片已刪 / 封存狀態已改，graph 已同步 | 本地收斂（成功語意） |
| `not_found` | **lookup 查無此字**（前一次已刪 / race） | server 上本就不存在 | 本地收斂（成功語意，刪除意圖已達成） |
| `failed` | graph 操作失敗已**回滾** | 卡片**仍存在 server**（原狀態） | **不可收斂**；保持 `failed + delete/edit`，下次 sync 重試 |

- `failed` 鍵是**向後相容的附加欄位**（Pydantic `BatchDeleteResponse` / `BatchArchiveResponse` 預設空 list）。舊 client 忽略未知鍵即可；關鍵改動是 graph-失敗的字**不再**出現在 `not_found`，因此舊 client 也不會再把仍存在 server 的字誤收斂（#720）。
- **可本地收斂集合 = `deleted_words ∪ not_found`**（`SyncCoordinator.locallyResolvableDeletes(from:)`，`SyncCoordinator` 與 `KGVocabCoordinator.retryPendingDeletes` 共用此純函數）。
- `failed` 內的字（或任何「三個 bucket 都不在」的字）才 `markSyncFailed()` 進重試。
- **不變式 1**：絕不可把 `not_found` 當刪除失敗 → 否則永久卡死的隱形重試迴圈。
- **不變式 2**：絕不可把 `failed` 當成功收斂 → 該字 server 仍存在，本地移除會造成 client/server 永久分歧（#720 根因；後端已把 graph-失敗字從 `not_found` 移到 `failed` 修正此半邊）。

### 同步失敗後重試

1. 上傳新增或刪除失敗時，單字會先標記為 `failed`
2. 同步頁仍會把它算進待處理項目
3. 下一次同步前，App 會自動把 `failed` 轉回 `pending` 再重試
4. 若失敗的是刪除，單字仍維持隱藏，避免違反使用者已經做出的刪除決定
5. **`not_found` 不是失敗**（見上節）— 已不存在於 server 的字本地直接收斂，不進此重試迴圈；反之 batch 回應的 `failed` bucket 才是 server 端 graph 操作失敗（卡片仍在），須進此重試迴圈

## 同步觸發鏈

`KGService.backgroundSync` 是共用 resync 入口，由以下觸發：post-login / scenePhase→active / ⌘R menu / Settings 手動同步。其執行序：

1. vocab pull / push（本文上述狀態流轉）
2. **podcast catalog**（Phase 3，序執行於 vocab pull 後）— `PodcastSyncService.syncAll` 併入 backgroundSync，使 podcast catalog 共用上述所有觸發；自我防禦、不 throw，失敗僅記 log 不影響 vocab。**不變式**：空 server list（`/api/podcasts` 回 `[]`）視為非權威，reconcile **不**對 series/episode 下 tombstone（避免 S3 index 短暫讀不到時 mass soft-delete）。詳見 `docs/reference/feature_boundary/podcast.md §同步觸發`。

## 知識圖譜變更的傳播（server 端 touch barrier）

知識圖譜連結（建立 / hide / unhide / delete）本身不在上述 `syncStatus` 流轉中。client 透過 `get_modified_since(updated_at)` 抓 card 增量，看到 card 變更後**重拉該 card 的 links**。因此每個 graph op 必須在改完 graph 後 **bump 兩端 card 的 `updated_at`**（`cards_store.touch`），否則 graph 變了但 client 永遠抓不到 → 靜默不一致。

- **不變式**：graph 變更後 touch 失敗**不可被吞掉**。`backend/src/kg/vocab_graph_ops.py:_touch_both` 保證：兩端皆嘗試 touch（一端失敗不跳過另一端，只要任一端 `updated_at` 前進 client 仍能收斂）、失敗 `logger.error`（可觀測）並 re-raise（不假裝成功）。
- **可逆 op（hide / unhide、create 的 unhide 分支）**：touch 失敗時回滾 graph 變更，使 graph 與 card 狀態一致。
- **不可逆 op（hard delete、create 新連結）**：不乾淨回滾，僅靠 barrier 的「可觀測 + re-raise」。

## Phase 2 之後的建議

- 若未來真的用到 `failed`，要補明確 retry 規則
- 若未來支援編輯詞卡內容，`edit` 需要獨立轉移表
- 若同步流程再變複雜，優先擴充這份文件與測試，而不是把邏輯散回各個 View
