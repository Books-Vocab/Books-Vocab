<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/
verified_against: c907585a0
-->
# UI State Matrix

Date: 2026-06-02
Scope: `ios/BooksAndVocab`

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
- `ios/BooksAndVocab/Views/Reader/ReaderView.swift`
- `ios/BooksAndVocab/Views/Reader/ReaderViewPresenter.swift`
- `ios/BooksAndVocab/Views/Reader/TranslationPanelPresenter.swift`
- `ios/BooksAndVocab/Views/Reader/TranslationVocabPresenter.swift`

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
| Translation / explanation failed | `translationErrorMessage` / `explanationErrorMessage` 有值 | `VocabStateMessageCard` 錯誤卡 + 重試 CTA（`onRetryTranslation` / `onRetryExplanation`，wire 在 `ReaderView+Panels.swift` + `PDFReaderView.swift`） | 已覆蓋 |
| Empty panel | `contentMode == .empty` | `VocabStateMessageCard("尚未取得翻譯", "text.viewfinder", "請重新選取文字，或稍後再試一次。")` + footer toolbar（含 dismiss） | 已覆蓋 |

判斷：
- Reader 主容器狀態已經清楚
- Translation panel 所有 contentMode 分支皆有明確 UX；`.empty` 透過 `VocabStateMessageCard` 提示用戶重新選字
- 翻譯 / 解釋失敗已是明確 error state（`VocabStateMessageCard` 錯誤卡 + 重試 CTA）

---

## Vocabulary

主要檔案：
- `ios/BooksAndVocab/Views/Vocabulary/VocabularyListView.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Scenes/KGVocabView.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Scenes/KGVocabPresenter.swift`
- `ios/BooksAndVocab/Views/Vocabulary/SyncView.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncPresenter.swift`
- `ios/BooksAndVocab/Views/Vocabulary/KnowledgeGraphView.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Scenes/KnowledgeGraphPresenter.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Scenes/TodayReviewPresenter.swift`

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

### Dictionary Card State（V1）

主要檔案：`Scenes/AddLinkSheet.swift` + `Scenes/AddLinkCoordinator.swift`（建卡流程）、`Scenes/WordDetailSheet.swift` + `Scenes/WordDetailSceneState.swift` + `Presentation/DictionaryDetailPresentation.swift`（詳情與 promotion）。

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| List filter：全部／學習／字典 | `KGVocabCoordinator` roleFilter | segmented filter + 排序 | 已覆蓋 |
| 字典搜尋 idle | 尚未輸入 | 提示文案 | 已覆蓋 |
| 字典搜尋 loading | 送出查詢中 | progress | 已覆蓋 |
| 字典搜尋無結果 | `hits.isEmpty` | empty state | 已覆蓋 |
| 字典搜尋被限流 | 429 | 稍後再試文案（`Retry-After` 60s） | 已覆蓋 |
| 字典查詢已關閉 | rollout flag off → 403 | 功能暫不可用文案 | 已覆蓋 |
| 義項／例句選取 | 展開 entry | sense/example picker | 已覆蓋 |
| 建卡並連結成功 | materialize 200 | targeted upsert + 關閉 sheet | 已覆蓋 |
| 重用既有卡 | notebook 內已有同字 | 直接連結，不換選定例句 | 已覆蓋 |
| Detail：離線 payload | 進入字典卡詳情 | 義項／例句切換 + 來源與授權 + 分享 | 已覆蓋 |
| Promotion queued / running | `promotionState` | 進行中指示，動作禁用 | 已覆蓋 |
| Promotion failed | `promotionState == .failed` | 錯誤 + 重試（仍是字典卡） | 已覆蓋 |
| Promotion success | role 轉 `learning` | 卡片切到學習面 | 已覆蓋 |
| Reader 高亮開關 | `readerHidden` toggle | 立即生效 + outbox 補送 | 已覆蓋 |
| Graph：dictionary badge / 次級節點 | node `cardRole` | badge + 次級樣式 + 導航 | 已覆蓋 |

判斷：
- 這面的 state 幾乎全部由後端狀態驅動，UI 不得自行推導——特別是**不能用 `cardRole` 推導 Reader 高亮**（見 `feature_boundary/reader.md`）
- promotion 是唯一的 role 轉移入口，且單向；UI 不提供降級

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
| Remembered / forgot feedback | submit action | sound feedback（可關閉）+ haptic（可關閉）+ card swap | 已覆蓋 |
| Save failure / persistence failure | `modelContext.save()` 失敗 | `onSaveFailure` → `toast.error(L10n.string("todayReview.saveFailure"))` | 已覆蓋 |
| 卡片版面：自然放得下 | `totalHeight <= available`（natural 層） | 各欄位全長呈現＝出貨既有卡片視覺 | 已覆蓋 |
| 卡片版面：逐級精簡 | `totalHeight > available` | 依固定順序退讓（例句 radius → 解釋 2/1 行 → 搭配詞 2/1 列 +N → 連結 2/1 項 + 單列摘要 +N → 最後才收 spacing/padding） | 已覆蓋 |
| 卡片版面：minimal 仍溢出 | `requiresScrollFallback`（多見於 Accessibility Dynamic Type） | 該面改垂直捲動；**不隱藏使用者勾選的欄位** | 已覆蓋 |
| 卡片版面：欄位資料缺席 | `ReviewCardContentAvailability` 該欄為 false | 本次不畫，**profile 不變**（下張卡有資料就回來）；`graphLinks` 恆可用——無連結時畫加連結入口 | 已覆蓋 |
| 卡片版面：正面／反面預算 | 正面階段常駐 reveal zone | 正面預算＝contentHeight − revealZoneReserve 且不隨 reveal 階段變動；反面拿正面實佔後的餘額 | 已覆蓋 |
| 版面編輯器入口不可用 | `!isCardInteractive`（fling / 推進中） | toolbar 鈕點擊 no-op（與 shuffle / prev / next 同一把鎖） | 已覆蓋 |
| 開編輯器時 autoplay 正在播 | tap 入口 | `pauseForInterruption()` 暫停；**關閉後不自動恢復**（`todayReview.autoplay.paused` identifier 可判讀） | 已覆蓋 |

### Review Card Layout Editor State（`ReviewCardLayoutEditor`）

兩個入口共用同一頁：複習 toolbar sheet（`ReviewCardLayoutEditorSheet`）與 設定 ▸ 偏好 ▸ 複習卡片（`navigationDestination`）。

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Mode = 辨識 / 產出 | `modePicker` 分段選擇 | 兩模式各自獨立的欄位配置；由複習畫面進入時預選**畫面上那張卡的模式** | 已覆蓋 |
| Face = 正面 / 背面 | `facePicker` 分段選擇 | 切換編輯中的那一面；預覽區同步 | 已覆蓋 |
| Locked core row | 恆常 | `lock.fill` 鎖定列（正面＝題目、背面＝答案），**無 toggle 可關**；模式語意非 profile 欄位 | 已覆蓋 |
| 欄位開 / 關 | `toggle.<field>` | 開啟時重排回 `canonicalOrder`（不是附加到尾端）；直寫 store，背後卡片即時重排 | 已覆蓋 |
| 該面零可選欄位 | `activeFields.isEmpty` | 預覽區顯示空狀態說明（`reviewCardLayout.preview.empty`）＋鎖定列仍在——卡片不會變成空白 | 已覆蓋 |
| Settings 摘要：預設 | `profile == .default`（兩模式四面全深比較） | 偏好列尾顯示「預設」 | 已覆蓋 |
| Settings 摘要：自訂 | 任一模式任一面與預設不同 | 偏好列尾顯示「自訂」 | 已覆蓋 |
| Reset 目前模式 | `reset.currentMode` | 只還原當前模式兩面，另一模式不動 | 已覆蓋 |
| Reset 全部 | `reset.all`（destructive） | 兩模式四面全還原成預設 | 已覆蓋 |
| 跨裝置衝突 | iCloud KV 外部變更通知 | updatedAt LWW 整組原子取代；時戳不可信（非有限 / 超界 / 版本不明）時整包忽略，不半套 | 已覆蓋 |

---

## Settings

主要檔案：
- `ios/BooksAndVocab/Views/Settings/SettingsView.swift`
- `ios/BooksAndVocab/Views/Settings/SettingsPresenter.swift`
- `ios/BooksAndVocab/Views/Settings/SettingsCoordinator.swift`

### UI Feedback Preferences

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Sound feedback on/off | `FeedbackSettingsStore.soundFeedbackEnabled` | Settings 偏好列；`appFeedback` 播放短促非語音 UI 音效 | 已覆蓋 |
| Haptic feedback on/off | `FeedbackSettingsStore.hapticFeedbackEnabled` | Settings 偏好列；`appFeedback` gate `.sensoryFeedback` | 已覆蓋 |
| Content audio isolation | TTS / Podcast event | 維持各自既有服務與設定，不受 UI feedback switches 影響 | 已覆蓋 |

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
| Product pricing unavailable | `state.pricingUnavailableMessage != nil` | `pricingUnavailableCard`（`VocabStateMessageCard`） | 已覆蓋 |

判斷：
- Settings 的 section-level state 已經不差
- pricing unavailable 已收斂到 `VocabStateMessageCard`；殘留的 detail-text fallback（auth error、offline label）仍非明確 state 分層

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
  `AppSkeletonLine` / `AppSkeletonCard` primitive 已備齊；目前唯一 callsite 在 `VocabSceneShell.swift:52`（`.loadingSkeleton` phase 用 `AppSkeletonCard(lineCount: 2)`），透過 `VocabSceneShell` 間接覆蓋 KGVocab / Sync / TodayReview / KnowledgeGraph / PodcastEpisodeList 等場景；其餘獨立 loading（Bookshelf import overlay、PodcastPlayer `.loading`、ReaderView publication load）仍用 ProgressView 或 state message card

---

## Next UX Priorities

### Priority 1（已完成）

原列項皆已補成明確 presentation：
- Reader translation `empty` → `VocabStateMessageCard`
- Reader translation / explanation error → 錯誤卡 + 重試 CTA
- Today Review persistence failure → `todayReview.saveFailure` toast
- Settings subscription unavailable pricing → `pricingUnavailableCard`

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

## Notebook Card (HStack book-row, `NotebookCard`)

主要檔案：
- `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCard.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookPalette.swift`
- `ios/BooksAndVocab/Views/Vocabulary/Components/NotebookCoverPatterns.swift`

> Book-row redesign 後 `NotebookCard` 不再用 `NotebookStackedCoverView`(該 view 改由 Bookshelf / Podcast / EditSheet preview 維持);stack depth / rotation / deck press 行為僅在那些 surface 生效。

### Variants

| State | 觸發條件 | 視覺 |
|------|---------|------|
| 使用中 | `isActive == true` | cover 左欄 name 旁 5pt 圓點(`NotebookPalette.darken(cover, by: 0.5)`),取代舊 3pt spine / 「使用中」pill |
| 有待複習 | `dueCount > 0` | metadata 右欄 `N 詞` row 後接 5pt warning 圓點 + count;`dueCount == 0` 時不顯示 |
| 空 notebook | `cardCount == 0` | metadata 改顯示「尚未加入單字」placeholder,**不**渲染 `N 詞` / ProgressCapsule |
| 一般狀態 | `cardCount > 0` | metadata 顯示 `N 詞` monoLabel + ProgressCapsule(4pt, fillColor=coverColor) |
| Pending sync | `pendingCount > 0` | 頂部 TipView(`SyncPendingTip`),卡片內不顯示 chip |
| 自訂照片封面 | `coverImagePath != nil` | cover 左欄底層改用 image fill,仍套 noise pattern + name overlay |
| Editorial rule | always | cover 內 1pt rule(寬 cover×0.3,色 darken 0.5);cover/metadata 間 0.5pt 垂直 cardBorder rule |

### Theme / Press / a11y

| State | 觸發條件 | 行為 |
|------|---------|------|
| Light mode | `colorScheme == .light` | cover 套 Morandi palette 12 色;`primaryText #37352F` 對全 12 色 ≥ AA 7:1(`NotebookCoverContrastTests` 鎖) |
| Dark mode | `colorScheme == .dark` | `NotebookCard.coverColor` 自動套 `NotebookPalette.darken(_, by: 0.2)` 使 `primaryText #E6E6E3` 對 cover ≥ AA 4.5:1(test 鎖) |
| Press | `NavigationLink` + `.buttonStyle(.plain)` | 無 deck press 動畫(`NotebookDeckButtonStyle` 不適用於 row)、無 offset/scale;按壓由 SwiftUI default highlight + nav push 提供 |
| Dynamic Type `.accessibility3` | a11y size | metadata truncate,row 高度固定 72pt 不縮放 |

整 row 為單一 a11y element(`children: .ignore` + label = `name + cardCount + 狀態`)。

### Legacy stack(`NotebookStackedCoverView`,Bookshelf / Podcast / EditSheet preview 仍用)

| State | 觸發條件 | 視覺 |
|------|---------|------|
| 空本 | `cardCount == 0` | 單張平面卡(`layerCount=1`),無下層 ghost |
| 薄堆 | `1...50` | 2 層(1 ghost + 1 頂層) |
| 中堆 | `51...200` | 3 層 |
| 厚堆 | `200+` | 4 層(上限) |
| Editorial rotation | layerCount ≥ 2 | 每層 ±1.5° per-notebook deterministic(`stableSeed(for: data.name)` djb2 → `seedJitter`),anchor `.bottom`;跨 launch 同角度 |
| Press(此 surface) | `NotebookDeckButtonStyle` `isPressed == true` | 頂層 offset −14pt + scale 0.97;ghost 每深一層額外下沉 1pt;haptic `.selection`。Rotation 不參與 press 動畫 |
| Reduce Motion | `accessibilityReduceMotion == true` | 關閉 offset/scale;保留 opacity dip + haptic + push transition;rotation 保留 |

---

## Bookshelf

主要檔案：
- `ios/BooksAndVocab/Views/Bookshelf/BookshelfView.swift`
- `ios/BooksAndVocab/Views/Bookshelf/BookshelfCoordinator.swift`
- `ios/BooksAndVocab/Views/Bookshelf/BookshelfMetrics.swift`

> Bookshelf 是 EPUB/PDF/TXT/MD 書籍 + Podcast Series 的統一書庫入口。同一 `NavigationStack` 同時承載 `Book` 與 `PodcastNavRoute` push。`BookshelfImportError.classify` 把底層錯誤分類成 `unsupportedExtension` / `iCloudUnavailable` / `unknown` 等 diagnosed 形式。

### Bookshelf Container State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Idle empty（無書 + 無 podcast） | `books.isEmpty && podcastSeries.isEmpty` + `CloudKitMirroringMonitor.phase ∈ {settled, localOnly}` | `emptyState` ScrollView：`AppEmptyStateContent`（真「尚無書籍」）+ EPUB 指南 TipView + 匯入 CTA + 登入 / Demo 雙 CTA | 已覆蓋 |
| CloudKit 還原確認中 | `books.isEmpty` + `phase == .waitingFirstEvent` | emptyState 內 `cloudRestoreStatus`：`ProgressView` + `正在確認 iCloud 書庫…`（`bookshelf.emptyState.cloudStatus`） | 已覆蓋 |
| CloudKit 還原中 | `books.isEmpty` + `phase == .restoring` | emptyState 內 `cloudRestoreStatus`：`ProgressView` + `正在從 iCloud 取回書庫…`（`bookshelf.emptyState.cloudStatus`） | 已覆蓋 |
| CloudKit 同步失敗 | `books.isEmpty` + `phase == .failed(msg)` | emptyState 內 `cloudRestoreStatus`：`Label` + `exclamationmark.icloud` + `iCloud 書庫同步異常・<msg>` | 已覆蓋 |
| Books + podcast 並存 | 任一非空 | `bookGrid` LazyVGrid（書先、podcast series 後）+ pull-to-refresh | 已覆蓋 |
| Import loading overlay | `coordinator.isLoading == true` | scrim + linear `ProgressView`（`loadingProgress` 有值）或 indeterminate spinner + `loadingMessage` | 已覆蓋 |
| Import error alert | `coordinator.showError == true` | system alert，title `匯入錯誤・<diagnosis>` | 已覆蓋 |
| Import error persistent banner | `errorMessage != nil && !showError` | `safeAreaInset(.top)` `AppStateMessageCard`，含「再試匯入 / 關閉」雙 CTA | 已覆蓋 |
| 部分成功匯入 | `succeeded > 0 && failures.count > 0` | toast warning + alert（保留 inline banner） | 已覆蓋 |
| 批次全失敗 | `succeeded == 0 && failures.count > 1` | alert message 為 per-file diagnosis 條列 | 已覆蓋 |
| Background podcast sync 進行中 | `.task` 內 `PodcastSyncService.syncAll` 跑著 | 無顯式 UI（靜默） | 缺口（Priority 3） |
| Background podcast sync 失敗 | sync 拋例外 | 無 UI，僅 log | 缺口（Priority 2） |

### Book Card State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Cover decoded | `decodedCoverImage != nil` | 平台 image fill | 已覆蓋 |
| Cover placeholder | 無 cover data 或解碼中 | mutedFill + `book` SF symbol + title + format 標 | 已覆蓋 |
| 閱讀進度 | `book.progression > 0` | accent capsule + 百分比 mono 文字 | 已覆蓋 |
| iCloud 待下載 | `book.needsICloudDownload` 或 `state == .notDownloaded` | `icloud.and.arrow.down` 徽章 | 已覆蓋 |
| iCloud 下載中 | `state == .downloading(progress)` | `ICloudProgressBadge`（圓環 + 數字） | 已覆蓋 |
| iCloud 下載失敗 | `state == .failed` | `retryBadge`（`exclamationmark.icloud` warning tint，tap 觸發 `triggerDownload` 重試；`BookCard.swift:134,154`） | 已覆蓋 |
| 長按 context | context menu | 刪除（destructive） | 已覆蓋 |

### Podcast Series Card State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| 一般 series | always | `NotebookCoverView`（pattern + name）+ `waveform` 角標 + episode count | 已覆蓋 |
| 已追蹤 | `series.isFollowed == true` | 左上 `star.fill` 角標 + a11y label `已追蹤` | 已覆蓋 |
| 自訂封面 | `series.coverImagePath != nil` | cover image fill 取代 pattern | 已覆蓋 |

### Bookshelf Auth / Paywall

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Demo mode | `authManager.isDemoMode` | empty state 不再顯示登入 / Demo CTA | 已覆蓋 |
| 未登入 + 非 Demo | `!isDemoMode && !isLoggedIn` | empty state 多出「登入帳號 / 體驗複習與圖譜」雙 CTA | 已覆蓋 |
| 已登入 ready | `isLoggedIn` | `.task` 觸發 `PodcastSyncService.syncAll` + audio prefetch | 已覆蓋 |
| Paywall | 無 — Bookshelf 本身不擋 paywall | n/a | n/a（paywall 落在 Reader / Vocabulary） |

判斷：
- Import 流程的 alert + persistent banner 雙層配置是目前 cross-surface 最成熟的 error pattern
- 殘留缺口集中在「背景同步沒有可見訊號」：podcast sync running / failed、warmFollowedSeriesAudio 失敗皆靜默
- iCloud 下載六態齊全（current / downloading / notDownloaded / failed），`.failed` 已有專屬可重試徽章，與「沒下過」明確區分
- **空書架 CloudKit 還原三分化已補齊**（`CloudKitMirroringMonitor.phase`）：本地 0 列不再一律講「尚無書籍」——還原確認中 / 還原中顯示 ProgressView 提示、同步失敗顯示 `exclamationmark.icloud` 警示，只有 `settled`（首次 import 成功收尾）/ `localOnly` 才渲染真空 emptyState

---

## Podcast

主要檔案：
- `ios/BooksAndVocab/Views/Podcast/PodcastEpisodeListView.swift`
- `ios/BooksAndVocab/Views/Podcast/PodcastPlayerView.swift`
- `ios/BooksAndVocab/Views/Podcast/PodcastPlayerViewModel.swift`（`PodcastPlayerState`、`PodcastSubtitleLoadState`、`SleepTimerMode`）
- `ios/BooksAndVocab/Views/Podcast/PodcastSubtitleView.swift`
- `ios/BooksAndVocab/Views/Podcast/PodcastControlsView.swift`
- `ios/BooksAndVocab/Views/Podcast/PodcastSettingsPopover.swift`

> 音訊與字幕狀態**獨立**：`state` 走 audio lifecycle，`subtitleState` 走 SRT 載入；字幕失敗不阻斷播放。

### Episode List State（`PodcastEpisodeListView`）

由 `VocabScenePhase` 驅動，透過 `VocabSceneShell` 統一渲染。

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Initial loading | `isLoading && !hasLoadedOnce` | `.loadingSkeleton` → `AppSkeletonCard` | 已覆蓋 |
| Load error | `loadError != nil && rawEpisodes.isEmpty` | `.error` phase，title `無法載入集數`，retry 重跑 `reloadFromStore` | 已覆蓋 |
| Empty episodes（首載後） | `rawEpisodes.isEmpty && hasLoadedOnce` | `.empty` phase，title `尚無集數` + `waveform.slash` | 已覆蓋 |
| Populated | episodes 非空 | hero + episode rows（accent divider 區隔） | 已覆蓋 |
| Continue / Resume CTA | `progressMap[ep].lastPlayedTime > 0 && !completed` | hero primary CTA 文字「繼續播放」 | 已覆蓋 |
| All completed | `rawEpisodes.allSatisfy(completed)` | hero CTA 文字「重新播放」 | 已覆蓋 |
| Audio 暫不可用 | `!target.audioAvailable` | CTA 文字「音訊暫不可用」+ `icloud.slash` + disabled | 已覆蓋 |
| Navigation lock | `navigationLocked == true`（tap 後 1s） | 所有 push CTA disabled，避免雙 push freeze | 已覆蓋 |
| Follow toggle 儲存失敗 | `PodcastFollowToggle.perform` 回 `.rolledBack` | toast error `追蹤狀態儲存失敗` + 自動回滾 star | 已覆蓋 |
| Sort 切換 | `sort` 變更 | menu pick + 動畫排序 | 已覆蓋 |
| Refresh after load error | `loadError != nil` 但 `rawEpisodes` 非空（殘留） | content 仍顯示 + 上方插入 `AppBanner`（`載入失敗，顯示快取資料` + retry CTA → `reloadFromStore()`；`podcast.episodeList.staleBanner`） | 已覆蓋 |

### Player Container State（`PodcastPlayerView` × `PodcastPlayerState`）

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| VM 尚未建立 | `viewModel == nil` | `ProgressView("載入中…")` | 已覆蓋（過渡態） |
| `.idle` / `.loading` | audio 未 ready | 置中 `ProgressView` + `載入音訊…` 文案 | 已覆蓋 |
| `.error(msg)` | audio 載入或中斷失敗 | `xmark.octagon` hero + `音訊載入失敗` + msg + 重試 CTA（`reloadEpisode`） | 已覆蓋 |
| `.ready` / `.playing` / `.paused` | audio ready 之後 | subtitle view + `PodcastControlsView` + 底部 `TranslationPanel` overlay | 已覆蓋 |
| Episode 切換中 | `.task(id: episodeId)` re-run | 先存舊 progress → 重建 VM；中間透過 `viewModel == nil` 顯示 `ProgressView` | 已覆蓋 |
| Scene phase 退出 | `scenePhase != .active` | 自動 saveProgress（無 UI） | 已覆蓋 |
| 未取得 audio URL | `loadEpisode` 找不到 local 或 remote URL | `vm.reportError("無音訊 URL")` → `.error` | 已覆蓋 |
| 認證 token 失敗 | `kgService.currentAuthToken()` throw | `.error` 帶錯誤訊息 | 已覆蓋 |
| Local file 播放 | `episode.localAudioPath` 存在 | 無 auth header，直接 file:// | 已覆蓋（無顯式 indicator） |
| 系統中斷 / route change | engine `onSystemPause` | VM 從 `.loading` / `.playing` 拉回 `.paused` | 已覆蓋 |
| Mid-stream 失敗後 didEnd | engine `onPlaybackFinished` 與 `.error` 競爭 | 守 `if case .error` 不 clobber error UI | 已覆蓋 |

### Subtitle State（`PodcastSubtitleLoadState`）

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| `.idle` | 未啟動（初始 / pre-load 過渡） | 無 overlay，純句子層渲染 | 已覆蓋 |
| `.loading` | `setSubtitleLoading()`（無 inline、有 URL） | Capsule hint overlay：spinner + `字幕載入中…`（`podcast.subtitleLoading`） | 已覆蓋 |
| `.loaded` | fetch 成功 / inline subtitle | 句子層 + 高亮字 + cue tracking | 已覆蓋 |
| `.failed` | fetch / decode 失敗 | `AppStateMessageCard` overlay：`字幕載入失敗` + `音訊仍可正常播放` + 重試 CTA（`onRetrySubtitle`） | 已覆蓋 |
| `.unavailable` | `markSubtitleUnavailable()`（episode 無 subtitle URL） | `AppStateMessageCard` overlay：`此集無逐句字幕` + `音訊仍可正常播放`（無重試 CTA；`podcast.subtitleUnavailable`） | 已覆蓋 |

### Translation Panel State（podcast surface）

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| 無查詢 | `translationHandler.wordSelection == nil` | 不顯示 panel | 已覆蓋 |
| 查詢中 | `translationHandler.isTranslating == true` | `TranslationPanel` shared state message + spinner | 已覆蓋（共用 Reader pattern） |
| 翻譯結果 | `translationResult` 有值 | translation body | 已覆蓋 |
| Explain only | `isExplanationOnly == true` | explanation body | 已覆蓋 |
| 翻譯 / 解釋失敗 | `translationErrorMessage` / `explanationErrorMessage` | 共用 `TranslationPanel` 渲染 `VocabStateMessageCard` 錯誤卡 + 重試 CTA（`onRetryTranslation` / `onRetryExplanation` → `retryLastLookup`，與 Reader 對齊；`PodcastPlayerView.swift:345-352`） | 已覆蓋 |
| 自動暫停 | `autoPauseOnLookup` + panel 出現 | VM `pause()` + `autoPausedByTranslation = true`，dismiss 後自動 resume | 已覆蓋 |

### Controls / Seek Bar State

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Duration 未知 | `viewModel.duration == 0` | 拖曳 disabled（防 seek(0)）；文字顯示 `--:--` | 已覆蓋 |
| Buffered 區段 | `viewModel.bufferedEnd > 0` | accent.opacity(0.25) overlay capsule + easeOut 0.2s | 已覆蓋 |
| Dragging | `isDragging == true` | seek bar swipe spring + thumb 跟手 + 時間文字 follow dragTime | 已覆蓋 |
| 倍速切換 | tap rate chip | mono label capsule，VM `cycleRate()` | 已覆蓋 |
| Skip ±15s | tap forward/back | engine skip + 同步 currentTime | 已覆蓋 |

### Sleep Timer State（`SleepTimerMode`）

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| `.off` | 預設 | popover Picker 顯示「關閉」 | 已覆蓋 |
| `.minutes(N)` | 5 / 15 / 30 / 60 | Picker 選中 + `TimelineView` 每秒 tick 顯示「剩餘 mm:ss」 | 已覆蓋 |
| `.endOfEpisode` | 「結束本集」 | Picker 選中，無 deadline 倒數（依靠 `onPlaybackFinished` 結束時自動 reset） | 已覆蓋 |
| 倒數結束 | timer fire（`sleepTimerFiredTick`） | engine pause + mode 回 `.off` + `.sensoryFeedback(.success)` + `toastCoordinator.info(L10n.string("podcast.sleepTimer.fired.toast"))` | 已覆蓋 |

### Settings Popover

| State | 觸發條件 | 目前 UI | 狀態 |
|------|----------|--------|------|
| Open | `showSettingsPopover == true` | popover：字幕大小 segmented / 逐字跟隨 / 查詞時自動暫停 / 睡眠定時 + 倒數 | 已覆蓋 |
| 字幕大小變更 | `subtitleSize` 變更 | `@AppStorage` 持久化，subtitle view 立即套用 | 已覆蓋 |
| 逐字跟隨關閉 | `wordFollowEnabled == false` | 句子層不顯示 word underline | 已覆蓋 |

判斷：
- Player error / subtitle failure 是目前 podcast 最成熟的 state machine（hero error + inline retry）
- subtitle `.loading` hint、`.unavailable` 與 `.idle` 區分、sleep timer fire toast、episode list stale banner 皆已補齊
- 殘留缺口：Bookshelf 背景 podcast sync running / failed 仍靜默（podcast translation 錯誤卡重試 CTA 已與 Reader 對齊）

### Next UX Priorities（Bookshelf + Podcast 補充）

#### Priority 1（已完成）
- Podcast subtitle `.loading` inline hint（spinner + `字幕載入中…`，`PodcastSubtitleView.subtitleLoadingHint`）
- Sleep timer 倒數結束 toast + haptic（`.sensoryFeedback(.success)` + `podcast.sleepTimer.fired.toast`）
- Podcast subtitle `.unavailable` 與 `.idle` 區分（`subtitleUnavailableHint` + `此集無逐句字幕`）

#### Priority 2
- ~~Podcast translation 錯誤卡 wire 重試 CTA（`onRetryTranslation` / `onRetryExplanation`）~~ — 已完成（`PodcastPlayerView.swift:345-352`，與 Reader 對齊）
- Bookshelf background podcast sync 失敗 toast / status row
- ~~iCloud 書籍下載失敗 vs notDownloaded 的徽章區分~~ — 已完成（`BookCard.swift:134` `case .failed: retryBadge`）

> Episode list 「load error 但有殘留資料」的 stale banner 已完成（`AppBanner` + `podcast.episodeList.staleBanner`）。

#### Priority 3
- Bookshelf podcast sync running 的微 indicator（pull-to-refresh 期間 OK，自動 sync 期間缺）
- `warmFollowedSeriesAudio` 失敗的 telemetry（純 silent，不需 UI）
