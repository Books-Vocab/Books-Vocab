# Manual Graph Links — Design Spec

## Problem

Graph links 目前 100% 由後端 pipeline 自動生成（embedding 相似度 + LLM 判定）。使用者無法：
1. 手動建立 pipeline 沒抓到的連結
2. 刪除不認同的自動連結

## Scope

- 手動添加 link（iOS → Backend）
- 刪除 link（`rejected` 狀態，阻止 pipeline 再生）
- 不含：圖譜視圖入口、embedding 推薦、使用者自填 reason、confidence 自訂

---

## Design

### 1. 手動添加 Link

#### 使用者流程
1. 在 WordDetailSheet 的 link 區塊，點擊「+」按鈕
2. 彈出搜尋框，即時過濾現有詞彙（排除自身、已連結的詞）
3. 選擇目標詞 → 送出
4. 顯示 loading 狀態
5. 後端呼叫 LLM 判定 `kind`（對比/相關）+ 撰寫 `reason`
6. 回傳結果，iOS 更新 UI 顯示新 link

#### Backend API

**`POST /api/graph/links`**

Request:
```json
{
  "from_id": "card_id_a",
  "to_id": "card_id_b",
  "notebook_id": "default"
}
```

Response（成功）:
```json
{
  "id": "abc123def456",
  "fromId": "card_id_a",
  "toId": "card_id_b",
  "kind": "contrasts_with",
  "confidence": 1.0,
  "reason": "..."
}
```

處理邏輯：
1. 驗證兩張卡片都存在且未刪除/封存
2. 檢查 `graph.has_link(from_id, to_id)` — 若已有 active link，回傳 409 Conflict
3. 若存在 `rejected` link，將其狀態改回 `active` 並重新生成 reason（而非建立新 link）
4. 呼叫專用 LLM prompt 取得 `kind` + `reason`
5. `graph.add_link(from_id, to_id, kind, confidence=1.0, reason)`
6. `cards.touch(from_id)` + `cards.touch(to_id)` — 觸發增量同步
7. 回傳 `GraphLinkResponse`

#### 專用 LLM Prompt

與自動 pipeline 的 Judge prompt 不同。語義：

> 使用者認為這兩個詞有關聯。請判斷它們的關係更接近「對比」（contrasts_with：意思相近但用法/語氣/程度不同）還是「相關」（shares_usage：常出現在相同語境或搭配使用）。並用繁體中文撰寫一句簡短的原因說明。

不允許回傳 `not_applicable`。必定產出 `kind` + `reason`。

### 2. 刪除 Link

#### 新狀態：`rejected`

在 `GraphLink.status` 加入第四個狀態值：

```
Literal["candidate", "active", "deprecated", "rejected"]
```

語義區分：
| 狀態 | 觸發者 | 語義 | Pipeline 再生 |
|------|--------|------|--------------|
| `deprecated` | 系統（刪卡/封存） | 卡片不可用，link 暫時隱藏 | 可（restore 時恢復） |
| `rejected` | 使用者 | 使用者否決此關聯 | 阻擋 |

#### `has_link()` 修改

```python
def has_link(self, id_a: str, id_b: str) -> bool:
    # 現有邏輯改為：active 或 rejected 都算「已存在」
    if lk.status in ("active", "rejected"):
        ...
```

這確保 `add_candidate()` 不會為已 reject 的配對重新建立候選。

#### Backend API

**`DELETE /api/graph/links/{link_id}?notebook_id=default`**

處理邏輯：
1. 找到 link，驗證屬於該使用者
2. 將 status 設為 `rejected`
3. `cards.touch(from_id)` + `cards.touch(to_id)` — 觸發增量同步
4. 回傳 204 No Content

#### iOS 刪除入口

在 WordDetailSheet 的 link 項目上提供刪除操作（swipe-to-delete 或長按選單），呼叫 DELETE API。

### 3. iOS 端架構

#### 新增元件
- **AddLinkSheet**：搜尋框 + 詞彙清單，用於選擇目標詞
- **觸發按鈕**：link 區塊標題旁的「+」按鈕

#### 搜尋過濾邏輯
- 從 `allEntries` 過濾：排除自身、已連結的詞、已封存/刪除的詞
- 即時搜尋，匹配 `word` 欄位（不區分大小寫）

#### 狀態管理
- 添加：呼叫 API → 成功後更新本地 `graphLinksJSON` → UI 刷新
- 刪除：呼叫 API → 成功後從本地 `graphLinksByKind` 移除該 link → UI 刷新
- 兩者都 touch cards，下次增量同步會拉到最新狀態

### 4. 資料流

```
手動添加：
  iOS [+] → POST /api/graph/links → LLM judge → graph.add_link() → touch cards → Response
  iOS ← 更新 graphLinksJSON ← 下次 sync 或即時回寫

刪除：
  iOS [swipe] → DELETE /api/graph/links/{id} → graph status→rejected → touch cards → 204
  iOS ← 移除該 link from local cache

Pipeline 再生阻擋：
  新卡片 → embed → find candidates → add_candidate() → has_link() 檢查
  → 若 rejected link 存在 → 跳過該配對
```

### 5. Edge Cases

| 情境 | 處理 |
|------|------|
| 兩詞已有 active link，使用者再次嘗試 | 409 Conflict，iOS 提示已存在 |
| 使用者 reject 後又想重建同一對 | POST API 檢測到 rejected link → 改回 active + 重新生成 reason |
| 目標詞在請求期間被刪除 | API 回傳 404，iOS 提示詞已不存在 |
| LLM 呼叫失敗 | API 回傳 502，iOS 提示稍後再試 |
| 離線時操作 | 不支援離線手動 link，需要網路連線（LLM 是必要依賴） |

### 6. 不做的事（明確排除）

- 圖譜視圖中的手動 link 入口
- Embedding 推薦候選詞
- 使用者自填 reason 或 confidence
- 編輯已有 link 的 kind/reason
- 批量操作
- 離線支援
