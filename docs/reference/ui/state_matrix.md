<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/
verified_against: f63ace78
-->
# UI State Matrix

Date: 2026-03-09
Scope: `ios/BooksBrowser`

文檔網絡：
- 設計規範主文檔：`docs/sop/ui-design.md`
- 元件 / pattern inventory：`docs/reference/ui/components.md`
- 開發入口：`docs/sop/ios.md`
- App 架構脈絡：`docs/sop/architecture.md`

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
- `ios/BooksBrowser/Views/Reader/ReaderView.swift`
- `ios/BooksBrowser/Views/Reader/ReaderViewPresenter.swift`
- `ios/BooksBrowser/Views/Reader/TranslationPanelPresenter.swift`
- `ios/BooksBrowser/Views/Reader/TranslationVocabPresenter.swift`

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
- `ios/BooksBrowser/Views/Vocabulary/VocabularyListView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KGVocabPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/SyncView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/SyncPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/KnowledgeGraphView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/KnowledgeGraphPresenter.swift`
- `ios/BooksBrowser/Views/Vocabulary/Scenes/TodayReviewPresenter.swift`

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
- `ios/BooksBrowser/Views/Settings/SettingsView.swift`
- `ios/BooksBrowser/Views/Settings/SettingsPresenter.swift`
- `ios/BooksBrowser/Views/Settings/SettingsCoordinator.swift`

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
- Offline state：
  `AppOfflineBanner` modifier 已掛在 `ContentView` 根層，連線中斷時自動覆蓋 destructive tint capsule（已知 light mode 對比未達 WCAG AA，待 polish）

### 仍然不一致的

- Error severity：
  有些是 banner，有些是 card，有些只是文案
- Partial failure：
  Sync 有，但其餘路徑還沒有明確語法
- Silent success：
  某些成功狀態沒有顯示，只有資料靜默刷新
- Empty state policy：
  部分畫面是顯式 empty state，部分畫面是 `EmptyView()`
- Skeleton 載入：
  `AppSkeletonLine` / `AppSkeletonCard` primitive 已備齊但目前 0 callsites，多數 loading 仍用 state message card

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

### Priority 3（已完成）

Preview matrix 已補齊：
- Reader chrome: loading / compact / expanded / translation
- Translation panel: loading / guest / translation / explanation only / empty
- Reader settings: default
- Sync: signed out / no Pro / ready / running / failed / completed
- Settings: logged out / logged in active / sub loading / delete in progress
- Today Review: front / back / details / completed

新增或修改 UI 時，參考 `docs/reference/ui/review_checklist.md`。

---

## Notebook Stacked Cover (`NotebookStackedCoverView` / `NotebookCard.grid`)

主要檔案：
- `ios/BooksBrowser/Views/Vocabulary/Components/NotebookStackedCoverView.swift`
- `ios/BooksBrowser/Views/Vocabulary/Components/NotebookStackMetrics.swift`
- `ios/BooksBrowser/Views/Vocabulary/Components/NotebookCard.swift`

### Stack Depth

| State | 觸發條件 | 視覺 |
|------|---------|------|
| 空本 | `cardCount == 0` | 單張平面卡（`layerCount=1`），無下層 ghost |
| 薄堆 | `1...50` | 2 層（1 ghost + 1 頂層） |
| 中堆 | `51...200` | 3 層 |
| 厚堆 | `200+` | 4 層（上限） |

### Variants

| State | 觸發條件 | 視覺 |
|------|---------|------|
| 使用中(grid) | `isActive == true` && `.grid` | **D3** cover 左側 3pt vertical spine(色 `NotebookPalette.darken(coverColor, by: 0.4)`),在 `EditorialCoverComposition` ZStack 內、跟 cover 一起 rotation。**取代舊「使用中」accent-blue capsule pill**(已移除)。Hero 不渲染 spine(單本即 active 冗餘)。 |
| 有待複習 | `dueCount > 0` | metadata row 顯示「N 到期」chip(`palette.warning`);`dueCount == 0` 時 invisible placeholder 撐高保 grid 同高 |
| Pending sync | `pendingCount > 0` | 頂部 TipView(`SyncPendingTip`)出現,**卡片底部不再重複顯示 chip**(D2 移除) |
| 自訂照片封面 | `coverImagePath != nil` | 頂層 image fill,下層 ghost 仍 cream paper(不混照片) |
| Editorial rotation | grid + layerCount ≥ 2 | 每層 ±1.5° per-notebook deterministic(`stableSeed(for: data.name)` djb2 → `seedJitter`),anchor `.bottom`;同一本跨 launch 同角度 |
| Editorial cover composition | `.grid` and `.hero` | **D1** `.overlay(EditorialCoverComposition)` 套在既有 cover 上:serif name 左上 + hairline rule(寬 cover×0.25)+ `N 詞` 右下(cardCount > 0)+ spine(D3, grid+active);跟著 coverArea rotation 一起旋轉 |
| Editorial divider | `.grid` style | cover 與 metadata 之間 1pt `cardBorder` hairline rule(維持) |

### Theme / Press / a11y

| State | 觸發條件 | 行為 |
|------|---------|------|
| Light mode | `colorScheme == .light` | ghost = `paperLight` / `paperSepia` / `paperSepiaDeep` cream 三階;cover 套 Morandi palette 12 色之一;`primaryText #37352F` 對全 12 色 ≥ AA 7:1(`NotebookCoverContrastTests` 鎖) |
| Dark mode | `colorScheme == .dark` | ghost 同 cream 三階(dark variant pending design);`AppElevationModifier` shadow ×1.8;**`NotebookCard.coverColor` 自動套 `NotebookPalette.darken(_, by: 0.2)`** 使 `primaryText #E6E6E3` 對 cover ≥ AA 4.5:1(test 鎖) |
| Resting | `isPressed == false` | 頂層 z2 / ghost z1，無 offset |
| Pressed | `NotebookDeckButtonStyle` `isPressed == true` | 頂層 offset −14pt + scale 0.97；ghost 每深一層額外下沉 1pt；haptic `.selection` 觸發一次。**Rotation 不參與 press 動畫**（靜態 layout） |
| Release | `isPressed` true→false | 走 `AppMotion.cardDeckRelease` spring 回彈 |
| Reduce Motion | `accessibilityReduceMotion == true` | 關閉 offset/scale；保留 opacity dip + haptic + push transition；**rotation 保留**（屬 layout 非 motion，mount 後不再變動） |
| Dynamic Type `.accessibility3` | a11y size | metadata truncate，stack 幾何不縮放 |

整 stack 為單一 a11y element（`children: .ignore` + label = `name + cardCount + 狀態`），ghost 各自 `.accessibilityHidden(true)`。

