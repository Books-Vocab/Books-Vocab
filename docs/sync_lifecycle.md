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

### 同步失敗後重試

1. 上傳新增或刪除失敗時，單字會先標記為 `failed`
2. 同步頁仍會把它算進待處理項目
3. 下一次同步前，App 會自動把 `failed` 轉回 `pending` 再重試
4. 若失敗的是刪除，單字仍維持隱藏，避免違反使用者已經做出的刪除決定

## Phase 2 之後的建議

- 若未來真的用到 `failed`，要補明確 retry 規則
- 若未來支援編輯詞卡內容，`edit` 需要獨立轉移表
- 若同步流程再變複雜，優先擴充這份文件與測試，而不是把邏輯散回各個 View
