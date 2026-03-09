# UI State Matrix

Date: 2026-03-09
Scope: `booksbrowser_ios/BooksBrowser`

文檔網絡：
- 設計規範主文檔：`docs/ui-design.md`
- 元件 / pattern inventory：`docs/ui_component_pattern_inventory.md`
- 開發入口：`docs/ios-dev.md`
- App 架構脈絡：`booksbrowser_ios/Architecture.md`

## 這份文件是幹嘛的

這份文件回答的是：

- 這個畫面有哪些狀態？
- 這些狀態現在怎麼呈現？
- 哪些狀態已經有一致 UI？
- 哪些狀態還沒被完整覆蓋？

`component / pattern inventory` 解決的是「該用什麼」。
`state matrix` 解決的是「有哪些狀態不能漏」。

---

## Reader

主要檔案：
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderView.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/ReaderViewPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/TranslationPanelPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Reader/TranslationVocabPresenter.swift`

### Reader Container State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Publication loading | `isLoading == true` | reader loading overlay | 已覆蓋 |
| Publication rendering progress | `loadingPhase` 變化 | loading overlay 文案切換 | 已覆蓋 |
| Publication failed | `errorMessage != nil` | `ContentUnavailableView` | 已覆蓋 |
| Reader ready | `publication != nil && errorMessage == nil` | Readium navigator | 已覆蓋 |
| Paywall required | `!subscriptionManager.hasProAccess` | `SubscriptionPaywallSheet` | 已覆蓋 |

### Translation Panel State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Translation loading | `contentMode == .loading` | shared state message | 已覆蓋 |
| Guest mode / local save | `contentMode == .guest` | shared state message + save status | 已覆蓋 |
| Translation result | `contentMode == .translation` | translation body | 已覆蓋 |
| Explanation only | `contentMode == .explanationOnly` | explanation body | 已覆蓋 |
| Explanation loading | `isLoadingExplanation == true` | shared state message | 已覆蓋 |
| Translation / explanation failed | `translationResult` or `explanationText` 填錯誤文案 | 文本內顯示錯誤 | 部分覆蓋 |
| Empty panel | `contentMode == .empty` | `EmptyView()` | 缺口 |

判斷：
- Reader 主容器狀態已經清楚
- Translation panel 最大缺口是 `empty` 幾乎沒有顯式 UX
- 錯誤目前多數只是文案，不是明確 error state

---

## Vocabulary

主要檔案：
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/SyncView.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/KnowledgeGraphView.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Scenes/KnowledgeGraphPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift`

### Vocabulary List Routing State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Pending list tab | `selectedTab == 0` | pending vocab route | 已覆蓋 |
| Knowledge base tab, signed out | `selectedTab == 1 && !isLoggedIn` | login-required empty state | 已覆蓋 |
| Knowledge base tab, no Pro | `selectedTab == 1 && !hasProAccess` | paywall empty state | 已覆蓋 |
| Graph tab, no Pro | `selectedTab == 2 && !hasProAccess` | paywall empty state | 已覆蓋 |
| Export available | local pending entries exist | export menu | 已覆蓋 |

### KG Vocabulary State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Signed out | `!authManager.isLoggedIn` | empty state card | 已覆蓋 |
| Initial loading | `coordinator.isLoading && syncedEntries.isEmpty` | shared state message card | 已覆蓋 |
| Sync error banner | `errorMessage != nil` | `ErrorBannerView` | 已覆蓋 |
| Empty by search / review state | `rows.isEmpty` | empty state content | 已覆蓋 |
| Populated list | `rows.count > 0` | list card + rows | 已覆蓋 |
| Pending delete retry | pending deletes + error | banner retry action | 已覆蓋 |
| Background refresh success | `loadInitialData` 成功 | 無明確 success UI | 缺口 |

### Sync State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Signed out | `!isLoggedIn` | status hero | 已覆蓋 |
| No Pro | `!hasProAccess` | status hero + CTA | 已覆蓋 |
| Ready | `phase == .ready` | status hero + counts + CTA | 已覆蓋 |
| Running | `phase == .running` | progress hero + timeline | 已覆蓋 |
| Completed | `phase == .completed` | success hero + done CTA | 已覆蓋 |
| Failed | `phase == .failed` | error hero + summary + retry | 已覆蓋 |
| Partial failure | summary text from coordinator | summary text only | 部分覆蓋 |
| Cancelled | `cancelSync()` | failed phase + cancelled summary | 已覆蓋 |

判斷：
- Sync 是 vocabulary 裡最完整的 state machine
- 但 partial failure 還只是文字，沒有和 full failure 拉開更明確層級

### Knowledge Graph State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Signed out | `!isLoggedIn` | empty state | 已覆蓋 |
| Loading | `isLoading` | empty state variant | 已覆蓋 |
| Error | `errorMessage != nil` | empty state variant | 已覆蓋 |
| No nodes | `nodes.isEmpty` | empty state variant | 已覆蓋 |
| Graph visible | nodes available | graph scene | 已覆蓋 |
| Settings drawer open | `showsSettings == true` | overlay panel | 已覆蓋 |

### Today Review State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Front | `revealStage == .front` | front fold card | 已覆蓋 |
| Back | `revealStage == .back` | answer fold | 已覆蓋 |
| Details | `revealStage == .details` | detail fold | 已覆蓋 |
| Completion | `currentCard == nil` | completion empty state | 已覆蓋 |
| Remembered / forgot feedback | submit action | haptic + card swap | 已覆蓋 |
| Save failure / persistence failure | `modelContext.save()` 失敗 | 無顯式 UI | 缺口 |

---

## Settings

主要檔案：
- `booksbrowser_ios/BooksBrowser/Views/Settings/SettingsView.swift`
- `booksbrowser_ios/BooksBrowser/Views/Settings/SettingsPresenter.swift`
- `booksbrowser_ios/BooksBrowser/Views/Settings/SettingsCoordinator.swift`

### Auth / Account State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Logged out | `!auth.isLoggedIn` | login section | 已覆蓋 |
| Logged in | `auth.isLoggedIn` | account summary + logout | 已覆蓋 |
| Auth error | `auth.authError != nil` | auth summary error text | 已覆蓋 |
| Delete confirm | `showDeleteAccountConfirm == true` | destructive alert | 已覆蓋 |
| Delete in progress | `isDeletingAccount == true` | danger button text switch | 已覆蓋 |
| Delete failed | `deleteAccountError != nil` | alert | 已覆蓋 |

### KG / Backend State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Signed out | `kg == nil` | section hidden | 已覆蓋 |
| Connected | `kg.isConnected == true` | connected badge / server count | 已覆蓋 |
| Offline | `kg.isConnected == false` | offline label | 已覆蓋 |
| Last sync available | `lastSyncDescription != nil` | row reveal | 已覆蓋 |
| Debug backend mode | debug section | local / prod switch | 已覆蓋 |

### Subscription State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| No subscription section | signed out | section hidden | 已覆蓋 |
| Free / inactive | `!pro.is_active` | status card | 已覆蓋 |
| Trial | `status.is_trial` | status card | 已覆蓋 |
| Active | `status.is_active` | status card | 已覆蓋 |
| Purchase / refresh loading | `subscriptionManager.isLoading` | CTA loading spinner | 已覆蓋 |
| Purchase status message | `purchaseStatusMessage != nil` | shared state message card | 已覆蓋 |
| App Store error | `lastError != nil` | shared state message card | 已覆蓋 |
| Product pricing unavailable | `priceLine` fallback | inline text only | 部分覆蓋 |

判斷：
- Settings 的 section-level state 已經不差
- 最大缺口是有些 fallback 仍然只用 detail text，而不是明確 state 分層

---

## Cross-Surface Findings

### 已經相對一致的

- Empty state：
  已大量收斂到 `AppEmptyState*` / `VocabEmptyState*`
- State message：
  Reader / Vocabulary / Settings 已開始收斂到 `AppStateMessage*` / `VocabStateMessageCard`
- Big status hero：
  Vocabulary sync / graph 已有清楚的大狀態模式

### 仍然不一致的

- Error severity：
  有些是 banner，有些是 card，有些只是文案
- Partial failure：
  Sync 有，但其餘路徑還沒有明確語法
- Silent success：
  某些成功狀態沒有顯示，只有資料靜默刷新
- Empty state policy：
  部分畫面是顯式 empty state，部分畫面是 `EmptyView()`

---

## Next UX Priorities

### Priority 1

把這些狀態補成明確 presentation：
- Reader translation `empty`
- Reader translation / explanation error
- Today Review persistence failure
- Settings subscription fallback / unavailable pricing

### Priority 2

把 partial failure 做成正式 pattern，而不是只留 summary text：
- Sync partial failure
- KGVocab delete retry result

### Priority 3

補 preview matrix，至少覆蓋：
- Reader loading / error / guest / translation / explanation loading / explanation error
- KG vocab signed out / loading / banner error / empty / populated
- Sync signed out / no Pro / ready / running / partial failure / failed / completed
- Settings logged out / logged in / subscription loading / purchase message / App Store error / delete failure
