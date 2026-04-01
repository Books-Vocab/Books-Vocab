# Bilateral Hide/Unhide Immediate Sync Implementation Plan

**Goal:** 補齊 iOS 端的即時雙向隱藏/恢復同步，讓使用者在 A 詳情把 B 隱藏或恢復後，B 詳情中的 A 也立刻反映同一狀態，不必等待下一次 sync。

**Current State:** Backend 已把 link 視為單一雙向關係，`hidden` 是同一條 link 的狀態；但 iOS 目前只 optimistic 更新當前畫面的 `entry.graphLinksByKind`，沒有同步修改對端 `VocabularyEntry` 的本地快取。

**Target State:** 維持 server 為唯一真相來源，iOS 在 hide/unhide/delete 成功前先做局部 optimistic bilateral patch；若 API 失敗，A/B 兩側一起 rollback。背景 sync 仍保留，作為最終收斂機制而非主要互動依賴。

**Tech Stack:** SwiftUI, SwiftData, existing KG REST API

---

## Scope

### In Scope
- `WordDetailSheet` 的 hide / unhide / delete 本地同步策略
- `VocabularyEntry` graph link JSON 的雙卡局部更新 helper
- 失敗 rollback 行為
- 單元測試 / presenter-state 測試覆蓋 A/B 雙向可見性
- 文件化驗收案例

### Out of Scope
- Backend API 調整
- sync 排程或背景同步機制重寫
- Graph / Today Review 的資訊架構變更
- 批次隱藏/恢復操作

---

## Problem Summary

目前資料語意正確，但互動體感不完整：

1. 使用者在 A 詳情把 B 隱藏後，A 畫面會立刻變 hidden
2. 同一時刻若開啟 B 詳情，本地 `VocabularyEntry` 仍可能保留舊的 active link
3. 直到下一次 pull sync，B 才會收斂到 server 狀態

這造成短暫 UI 不一致，也讓「雙向 link」的心智模型被破壞。

---

## Design Principles

1. **Server authority**
   - backend 仍是隱藏狀態唯一真相來源
   - iOS 只做 optimistic mirror，不自行發明新語意

2. **Local bilateral patch**
   - 已知受影響的是同一條 `link.id` 與兩張 card，應直接更新兩側本地快取
   - 不依賴全量/增量 sync 才呈現正確畫面

3. **Symmetric rollback**
   - API 失敗時，A/B 兩側一起回滾，避免另一種不一致

4. **Minimal blast radius**
   - 只更新受影響的兩張 card 與單一 link
   - 不改動現有 sync actor 與 backend contract

---

## File Map

| File | Responsibility |
|------|----------------|
| `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift` | hide/unhide/delete 改為 bilateral optimistic update + rollback |
| `ios/BooksBrowser/Models/VocabularyEntry.swift` | 新增 graph link mutation helper，避免在 View 內散落 JSON 操作 |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift` | 使用 helper 找到對端 card 並同步 patch |
| `ios/BooksBrowser/Tests/...` 或既有 iOS test target 對應檔案 | 加入 bilateral hide/unhide/delete 測試 |
| `docs/superpowers/plans/2026-03-31-bilateral-hide-sync.md` | 本計劃文件 |

---

## Implementation Strategy

### Task 1: 抽出可重用的 link mutation helper

**Files:**
- Modify: `ios/BooksBrowser/Models/VocabularyEntry.swift`

**Objective:**
把「用 `link.id` 修改 `graphLinksByKind` 中某個 link」這件事集中成 helper，避免 `WordDetailSheet` 重複做字典搜尋、陣列替換、空 group 清理。

**Implementation:**
- 新增 helper，例如：
  - `mutateLink(id: String, _ transform: (KGCardLinkSummary) -> KGCardLinkSummary?) -> Bool`
  - 回傳 `Bool` 表示是否找到並更新到該 link
- 行為規則：
  - 找到指定 `link.id` 後，允許：
    - replace: 回傳新 link
    - remove: 回傳 `nil`
  - 若 group 清空，移除該 key
  - 只更新一次；相同 `link.id` 不應在多個 group 並存

**Acceptance:**
- 可以用單一 helper 完成 hide/unhide/delete 三種本地變更
- View 層不再直接手寫重複字典 mutation

---

### Task 2: 在 WordDetailSheet 實作 bilateral optimistic hide/unhide

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift`

**Objective:**
當 A 隱藏或恢復 B 時，同步更新：
- A entry 中指向 B 的 link
- B entry 中指向 A 的同一個 `link.id`

**Implementation:**
- 新增 private helper：
  - 取得對端 entry：用 `link.cardId` 對 `allEntries` 建 lookup
  - 對 A/B 同時套用 `mutateLink`
- hide flow：
  1. 對 A/B 本地同時 `withHidden(true)`
  2. 呼叫 `kgService.hideLink`
  3. 若失敗，A/B 同時 rollback 成 `withHidden(false)`
- unhide flow：
  1. 對 A/B 本地同時 `withHidden(false)`
  2. 呼叫 `kgService.unhideLink`
  3. 若失敗，A/B 同時 rollback 成 `withHidden(true)`

**Important details:**
- 對端 entry 不存在時，只更新當前 entry，不要 crash
- 以 `link.id` 為主，不用 `word` 或 `cardId` 模糊比對
- 不要重新建整包 links；只 patch 單一 link

**Acceptance:**
- A hide B 後，立刻打開 B 詳情，A 應已是 hidden
- A restore B 後，B 詳情中的 A 也立刻恢復 active

---

### Task 3: 將 delete 也補成 bilateral optimistic remove + rollback

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift`

**Objective:**
目前 delete 只從當前 entry 移除 link。要改成 A/B 兩邊都先移除，失敗時兩邊一起插回。

**Implementation:**
- delete flow：
  1. 在 A/B 兩側先 remove `link.id`
  2. 呼叫 `kgService.deleteLink`
  3. 若失敗，A/B 兩側都按原 group 資訊 re-insert 同一個 `KGCardLinkSummary`

**Note:**
- rollback 需要保留原始 `link.kind` 與完整 `KGCardLinkSummary`
- 對端若不存在，rollback 僅作用於當前 entry

**Acceptance:**
- A 刪除 B 後，B 詳情不需等 sync 就看不到 A
- API 失敗時，A/B 兩側都恢復

---

### Task 4: 補測試，鎖住 bilateral behavior

**Files:**
- Modify/Add: iOS test target 對應檔案

**Required test cases:**
1. hide optimistic update updates both entries
2. hide rollback restores both entries on API failure
3. unhide optimistic update updates both entries
4. unhide rollback restores both entries on API failure
5. delete optimistic update removes from both entries
6. delete rollback reinserts into both entries on API failure
7. counterpart missing does not crash and still updates current entry

**Test shape:**
- 建立兩張 `VocabularyEntry`：A、B
- 讓 A/B 都持有同一個 `link.id` 的對向 summary
- 觸發對應 action
- 驗證兩張 entry 的 `graphLinksByKind`

**Acceptance:**
- 沒有只測 A 不測 B 的單邊測試
- rollback 測試必須驗證兩側一起恢復

---

## Proposed API/Model Contract

不變。沿用既有：
- backend `CardLinkSummaryResponse.hidden`
- iOS `KGCardLinkSummary.hidden`
- hide/unhide/delete API path

本次只補齊本地狀態傳播。

---

## UX Outcome

### Before
- A hide B
- A 畫面立刻變 hidden
- B 畫面短時間仍顯示 active
- 等 sync 才一致

### After
- A hide B
- A/B 畫面都立刻一致
- 若 server 失敗，A/B 一起回滾
- sync 僅作最終一致性保險

---

## Validation Plan

### Manual
1. 開 A 詳情，確認看到 B
2. 對 B 執行隱藏
3. 不做 sync，直接打開 B 詳情
4. 確認 A 已 hidden
5. 對 A 執行恢復
6. 確認 A/B 兩側皆回 active
7. 對任一側執行刪除
8. 確認另一側也立即消失

### Failure-path Manual
1. 讓 hide/unhide/delete API 故意失敗
2. 確認目前 entry rollback
3. 確認對端 entry 也 rollback
4. 確認 banner error 仍正常出現

### Automated
- iOS unit/presentation tests for bilateral patch helpers
- 若 repo 有 UI preview/state test 能力，增加對 hidden row/state 的回歸驗證

---

## Risks

1. **View-layer mutation duplication**
   - 若不先抽 helper，hide/unhide/delete 三套邏輯容易分叉

2. **Counterpart lookup miss**
   - 某些入口可能拿不到完整 `allEntries`
   - 解法：lookup miss 時降級為單邊更新，但保留 server sync 收斂

3. **Rollback reinsertion ordering**
   - re-insert 可能改變 group 內順序
   - 若順序重要，需保留原 index；若目前 UI 無排序契約，可接受 append rollback

4. **Concurrent edits**
   - 使用者快速連點 hide/unhide/delete 可能造成本地狀態競爭
   - 初版先維持現有行為；若發生實際問題，再加 action gating

---

## Recommended Commit / PR Structure

### Commit 1
`ios: add bilateral local graph-link mutation helpers`

### Commit 2
`ios: sync hide unhide and delete across linked card details`

### Commit 3
`ios: add bilateral graph-link optimistic update tests`

如果要保持 PR 小，也可壓成單一 commit：
- `ios: sync graph link hide state across both card details`

---

## PR Description Draft

### Summary
- make hide/unhide/delete optimistic updates bilateral in local iOS state
- keep backend as source of truth
- add rollback coverage so both card details stay consistent on API failure

### Why
- backend link state is already bidirectional
- iOS only updated the current detail card, causing temporary mismatch until sync

### Validation
- targeted iOS tests for bilateral optimistic update and rollback
- manual verification from both A and B detail screens

---

## Definition of Done

- A hide B 後，B detail 立即看到 A hidden
- A unhide B 後，B detail 立即看到 A active
- A delete B 後，B detail 立即看不到 A
- hide/unhide/delete API 失敗時，A/B 兩側一致 rollback
- 不需依賴背景 sync 才呈現正確結果
- 測試覆蓋 bilateral optimistic update 與 rollback
