# Hide Links + Hard Delete — Design Spec

## Problem

目前使用者對不想看到的 graph link 只有一個操作：**刪除（reject）**。刪除是軟刪除（`status="rejected"`），link 記錄永久保留在 graph store 中。

問題：
1. 有些 link 品質不差但使用者當下不想看到，刪除太重 — 刪了就無法恢復
2. 被刪除的 link 仍佔 graph store 空間，累積成 zombie records
3. 刪除與「使用者否決此關聯」語意綁定，無法表達「暫時不想看到」

## Scope

- 新增「隱藏連結」操作（`status="hidden"`）— 兩個介面都生效，可恢復
- 將現有刪除改為硬刪除 — 真正移除 GraphLink 記錄
- 新增 blocked pairs 機制 — 阻止 pipeline 重建已硬刪的連結
- 遷移現有 `rejected` 記錄
- 不含：批量隱藏/刪除、隱藏 link kind 分類、隱藏管理頁面

---

## Design

### 1. 三種操作的語意

| 操作 | 觸發 | Backend 行為 | Word Detail | Graph / Review | 可恢復 | 阻止 Pipeline |
|------|------|-------------|-------------|----------------|--------|---------------|
| **隱藏** | context menu「隱藏連結」 | `status → "hidden"` | 淡化顯示、只有單字 | 不顯示 | 是 | 是（`has_link` 包含 hidden） |
| **恢復** | context menu「恢復連結」 | `status → "active"` | 正常顯示 | 正常顯示 | — | — |
| **刪除** | context menu「刪除連結」 | 硬刪 GraphLink + `(from,to)` 加入 `_blocked_pairs` | 消失 | 消失 | 不可恢復 | 是（`_blocked_pairs` 阻擋） |

### 2. GraphLink Status 變更

```
Before: Literal["candidate", "active", "deprecated", "rejected"]
After:  Literal["candidate", "active", "deprecated", "hidden"]
```

`"rejected"` 被移除，由硬刪除 + blocked pairs 取代。`"hidden"` 取代 `"rejected"` 的位置。

### 3. Blocked Pairs — 防止 Pipeline 重建

#### 資料結構

```python
_blocked_pairs: set[tuple[str, str]]  # (min_id, max_id) 正規化排序
```

正規化規則：`tuple(sorted([from_id, to_id]))`，確保 `(A, B)` 和 `(B, A)` 是同一個 pair。

#### 持久化

新增 `blocked_{notebook_id}.json`，與 `graph_{nb}.json`、`candidates_{nb}.json` 同目錄：

```json
[["card_id_a", "card_id_b"], ["card_id_c", "card_id_d"]]
```

使用與 `_save_links` 相同的三階段原子寫入（tmp → rotate bak → promote）。

#### Pipeline 防護

`_has_link_unlocked` 和 candidate admission 邏輯修改為同時檢查：
1. `_links` 中是否有 `active` 或 `hidden` 的 link
2. `_blocked_pairs` 中是否有該 pair

任一命中即跳過，不建立候選。

#### Blocked pair 清理

當 card 被永久刪除時，相關 blocked pairs 可一併移除（該 card 不會再有任何連結）。在 `delete_vocab_word` / `batch_delete_vocab_words` 中（非 `deprecate_links_for`）呼叫 `remove_blocked_pairs_for(card_id)`。注意不能在 `deprecate_links_for` 中清理，因為 archive 也呼叫 `deprecate_links_for`，而 archive → unarchive 後 blocked pairs 仍需保留以阻止 pipeline 重建。

### 4. Backend API 變更

#### 新增端點

```
PATCH /api/graph/links/{link_id}/hide?notebook_id=...
PATCH /api/graph/links/{link_id}/unhide?notebook_id=...
```

回傳 204 No Content。兩者都 `cards.touch(from_id, to_id)` 觸發增量同步。

#### 修改端點

```
DELETE /api/graph/links/{link_id}?notebook_id=...
```

行為從軟刪除改為：
1. 從 `_links` 硬刪 GraphLink（含 `_unindex_link`）
2. `(from_id, to_id)` 加入 `_blocked_pairs`
3. `cards.touch(from_id, to_id)`
4. 回傳 204

#### GET 端點行為

| 端點 | Active | Hidden | 說明 |
|------|--------|--------|------|
| `GET /api/vocab` (card sync) — `linksByKind` | 包含 | 包含（標記 `hidden: true`） | iOS 需要知道 hidden links 來顯示淡化列 |
| `GET /api/graph/links` (圖譜) | 包含 | **排除** | 圖譜不顯示 hidden |

### 5. API Response Model 變更

```python
class CardLinkSummaryResponse(BaseModel):
    id: str
    cardId: str
    word: str
    kind: str
    label: str
    confidence: float
    reason: str
    hidden: bool = False   # NEW
```

### 6. Backend Service 層變更

#### `graph.py` — GraphStore

新增方法：
- `hide_link(link_id)` — status → `"hidden"`，觸發 `_save_links`
- `unhide_link(link_id)` — status → `"active"`，觸發 `_save_links`
- `hard_delete_link(link_id) -> (str, str)` — 移除 link、unindex、block pair、save both files、回傳 `(from_id, to_id)` 供 caller touch cards（取代 `reject_link`）
- `is_blocked(from_id, to_id)` — 查 `_blocked_pairs`
- `remove_blocked_pairs_for(card_id)` — 清理指定 card 的所有 blocked pairs

修改方法：
- `get_links_for(card_id)` — 回傳 `active` + `hidden`（目前只回傳 `active`）
- `_has_link_unlocked` — 改為檢查 `active` + `hidden` + `_blocked_pairs`
- `find_link_between` — 改為檢查 `active` + `hidden`（取代原本的 `active` + `rejected`）
- `_load` — 載入 `_blocked_pairs`；一次性遷移現有 `rejected` → blocked pairs + 刪除記錄
- `__init__` — 新增 `blocked_path` 參數
- `reject_link` — 移除（由新增方法 `hard_delete_link` 取代）

#### `vocab_service.py`

- `build_links_by_kind()` — 遍歷 `active + hidden` links，傳遞 `hidden=link.status=="hidden"` 到 response
- 新增 `hide_graph_link(link_id, graph, cards_store)`
- 新增 `unhide_graph_link(link_id, graph, cards_store)`
- `reject_graph_link` → 重命名為 `delete_graph_link`，改呼叫 `graph.hard_delete_link`

#### `vocab_graph.py`

- `graph_links_payload()` — 維持只回傳 `active`（已是如此）

#### `service_factories.py`

- `create_graph_store` — 傳入 `blocked_path=<user_dir>/blocked_{nb}.json`

### 7. iOS 變更

#### `SharedTypes.swift` — Model

```swift
struct KGCardLinkSummary: Codable, Identifiable, Equatable {
    let id: String
    let cardId: String
    let word: String
    let kind: String
    let label: String
    let confidence: Double
    let reason: String
    let hidden: Bool?          // NEW — optional 向後相容舊 JSON

    var isHidden: Bool { hidden ?? false }
    var isPending: Bool { id.hasPrefix("pending-") }
}
```

`hidden` 為 `Bool?` 確保舊的 `graphLinksJSON`（不含此欄位）仍可解碼。

#### `WordDetailComponents.swift` — Hidden Row 視覺

新增 `hiddenRowContent`：

```
Active:  [word]          → (arrow)     primaryText, reason below
         [reason caption]              tertiaryText

Hidden:  [word]                        quaternaryText, opacity 0.5
                                       無 reason、無 arrow、不可點擊展開
```

Context menu 差異：

| 狀態 | 選項 1 | 選項 2 |
|------|--------|--------|
| Active | 隱藏連結 `eye.slash` | 刪除連結 `trash` |
| Hidden | 恢復連結 `eye` | 刪除連結 `trash` |
| Pending | （無 context menu） | |

#### `CardPresentation.swift` — 分組

- `linkGroups` 包含所有 links（active + hidden）— 供 Word Detail 使用
- 新增 `activeLinkGroups` — 只含 active links，供 Review / metadata 使用
- `totalLinkCount` 只計 active links

#### `WordDetailSheet.swift` — 操作

新增：
- `handleHideLink(_ link:)` — optimistic：修改本地 `hidden` → true + PATCH API + rollback on failure
- `handleUnhideLink(_ link:)` — optimistic：修改本地 `hidden` → false + PATCH API + rollback on failure

修改：
- `handleDeleteLink` — 硬刪除無法 rollback（link 不可恢復），失敗時 re-insert

#### `KGService+Graph.swift` — API

```swift
func hideLink(linkId: String, notebookId: String) async throws
func unhideLink(linkId: String, notebookId: String) async throws
// deleteLink 不變（仍是 DELETE）
```

#### `TodayReviewState.swift` — Review

- `linkGroups` → 改用 `activeLinkGroups`，hidden links 不在複習卡上顯示

#### `WordDetailPresentation.swift` — Metadata

- `totalLinkCount` 用 `activeLinkGroups` 計算，hidden 不計入「N 個連結」

### 8. 資料遷移

在 `GraphStore._load()` 中自動處理（一次性）：

```python
# 遷移 rejected → blocked pairs
migrated = False
for lk in list(self._links.values()):
    if lk.status == "rejected":
        pair = tuple(sorted([lk.from_id, lk.to_id]))
        self._blocked_pairs.add(pair)
        del self._links[lk.id]
        self._unindex_link(lk)
        migrated = True
if migrated:
    self._save_links()
    self._save_blocked()
```

### 9. 對 `create_manual_link` 的影響

現有邏輯（`vocab_service.py:592-598`）在發現 rejected link 時「復活」它（同 ID、新 kind/reason）。

變更後有三種情境：

**A) 手動建立已有 hidden link 的 pair：**
- `find_link_between` 回傳該 hidden link（因為 `find_link_between` 現在包含 hidden）
- 行為：**unhide** 現有 link（status → active），不重新呼叫 LLM、不建立新 link
- 理由：hidden link 保留了原始的 kind + reason，直接恢復最合理

**B) 手動建立已 blocked 的 pair（先前硬刪過）：**
- `find_link_between` 回傳 None（link 已不存在）
- `is_blocked` 回傳 True
- 行為：先從 `_blocked_pairs` 移除該 pair，再正常建立新 link（呼叫 LLM 取得 kind + reason）
- 理由：`_blocked_pairs` 的目的是阻止 **pipeline 自動重建**，不應阻止**使用者主動建立**

**C) 手動建立已有 active link 的 pair：**
- `find_link_between` 回傳 active link
- 行為：409 Conflict（與目前相同）

### 10. Edge Cases

| 情境 | 處理 |
|------|------|
| 隱藏後 sync 到新裝置 | hidden link 隨 `linksByKind` 中的 `hidden: true` flag 同步，新裝置上也是淡化顯示 |
| 隱藏的 link 的對面 card 被刪除 | `build_links_by_kind` 已有 skip deleted card 邏輯，hidden link 也適用 |
| 隱藏的 link 的對面 card 被封存 | 同上 skip，hidden link 從 Word Detail 消失直到 card 取消封存 |
| Card 被刪除時清理 blocked pairs | 在 `delete_vocab_word` / `batch_delete_vocab_words` 中，`deprecate_links_for` 之後呼叫 `graph.remove_blocked_pairs_for(card_id)` |
| Graph view 中看不到 hidden link | 正確 — `GET /graph/links` 排除 hidden |
| Review card 中看不到 hidden link | 正確 — `activeLinkGroups` 排除 hidden |
| 手動建立已 blocked 的 pair | 從 `_blocked_pairs` 移除該 pair，正常建立新 link |
| Notebook merge（`merge_from`） | `_blocked_pairs` 也需合併到目標 notebook |

### 11. 不做的事（明確排除）

- 獨立的「隱藏連結管理」頁面（隱藏 link 在 Word Detail 已可見且可恢復）
- 批量隱藏/恢復操作
- 按 link kind 整批隱藏
- hidden link 的 reason 預覽（長按顯示等）
- blocked pairs 的管理介面
