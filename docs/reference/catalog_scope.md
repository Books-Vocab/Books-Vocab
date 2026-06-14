<!-- doc-meta
tier: reference
authority: SoT
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Views/
  - ios/BooksAndVocab/Debug/
verified_against: 83840bbd
-->
# KG iOS Catalog Scope Bible (SoT)

> 第一性原理 litmus：catalog 的原子 = **「手機會看到的視圖」+「其必要組件」**。使用者的眼睛會落在它上面嗎？會 → IN；那是工程基質 → OUT。borderline 寧可 OUT，但**只有確認 OUT 才 CUT** —— 既有 manifest surface 一律先驗 callsite 再裁決。
>
> 本表是 catalog 收錄範圍的唯一真相。重拍 / 補齊 / 砍除一律以此為準；探索儀器（review gallery）只 show 本表 IN 的東西，regression 網可續拍全部但不外顯。

## Summary

> **2026-06-09 收斂校正**：下方「處方」欄是原始規劃估計；「現況」欄是 CatalogScene 源碼實測（CUT 爭戰後）。最大修正 = **組件數被嚴重低估**：10 個真組件原被誤宣告為 `eng()`（藏在 engineering lane、未計數），已 reclassify 回 `block()`。故真實 IN 遠高於原估 62。

| 指標 | 處方（原估） | 現況（源碼實測，終局） |
|---|---|---|
| IN — screen（feature-surface） | 18 | **18** |
| IN — overlay | 17 | **13** |
| IN — 必要組件（block） | 27 | **45**（+10 從 eng lane 正名 + campaign 3a/2 新增） |
| **IN 合計** | 62 | **76** |
| eng（OUT，誠實 lane-filtered，不計 IN） | （未列） | **5**（KG Vocab Row／Pending Vocab Presenter／Review Fold ×3） |
| **catalog surface 總數** | — | **81** |
| CUT — 該砍 | 58 | 已砍 ~41（含 Bookshelf grab-bag）；餘為已 reclassify 或 eng-lane 化 |
| MISSING — app 有但 catalog 缺 | 18 | 18（多數耦合，見下） |
| RELOCATE | 3 | ✅ 3 已落地 |

**lane 真相修正**：gallery 的 engineering-only lane 曾因 stale profile eligibility 壓過 declared kind 而誤標（Selection Toolbar 等被當 engineering）；已修 `classify_lane` 讓 declared 權威（commit b9691720）。現 eng lane = 真正的 5 個工程內構件。

**多裝置拍攝（2026-06-10 起）**：`CatalogSnapshotTests` 的 device 清單 = iPhone 15 Pro portrait + iPad Pro 11 landscape（各 light/dark，共 4 變體；iPad 是 web 重寫 responsive 的寬版標準答案）。輸出依 device dir 自動分層；`review_manifest.json` 帶 `devices` 欄位（iPhone 首位＝預設），`UIreview.html` 以 device 切換鈕分裝置瀏覽（scene 的 light/dark 配對 scoped 在單一裝置內）；ops 驗證的 expectedPng = scenarios × deviceVariantCount（Swift 端印 `resolved.deviceVariantCount`，舊 log fallback 2）。

### 計數契約（可復現）
**「必要組件」= 有自身 sourceFile + 多於一個可區分狀態 + 使用者可指名的具名視圖物件**。凡「以 scenario 覆蓋為畫面狀態」「折入母視圖狀態」者**不計入組件數**，僅作母視圖的 state 列出。主表中被計數者標 `[組件]`，折入者標 `(折入狀態)`。

### Preview auth 契約（無 fallback）
Catalog scenario 可用 DEBUG-only `CatalogPreviewAuth` 注入登入狀態，但不得由 `isLoggedIn` 推導假 user/token/name/email。logged-in scenario 必須明示 `userId` / `token` / `displayName` / `userEmail`；logged-out scenario 必須明示 nil。`CatalogCoverageTests.catalogPreviewAuthDoesNotFallbackToImplicitUserState` 直接掃 Debug source，擋短式 constructor、preview fallback literal 與 `displayName ??` / `userEmail ??` 類型的隱式補值。

### Preview entitlement 契約（無本地假資料）
Paywall / Pro 相關 Catalog scenario 的 subscription status 必須來自 UI World `entitlements.*` seed。`PaywallScenarios` 只能用 `FixtureDatasetStore.requireEntitlementsSeed` fail-fast 取 seed，再注入 DEBUG-only `PreviewSubscriptionManager`；不可在 Debug source 內用 `KGSubscriptionStatus(...)` / `makeStatus` / `source: "admin"` / `last_synced_at` 重新造一套假訂閱資料。`CatalogCoverageTests.paywallCatalogDoesNotDeclareLocalSubscriptionStatusFixtures` 直接掃 Paywall source 擋回退。

### PDF Reader asset 契約（無 synthetic missing-file book）
`PDFReaderViewScenarios` 的 `Manifest PDF` 狀態必須取 UI World `bookshelf.with_books_library` seed 內的 PDF `Book` row，且該 row 必須以 `bookAssetRef` 指向 `assets.books.catalog_reader_pdf`。scenario 必須用 `FixtureDatasetStore.requireInstalledAssetURL` 物化檔案，並驗證安裝位置是 `Documents/Books/<fileName>`；缺 row、缺 asset ref、缺資產、hash/byteSize 不符、unsafe install path、row `fileName` 與 asset 檔名不一致都直接 fail-fast。`CatalogCoverageTests.pdfReaderCatalogUsesUIWorldBookAsset` 擋回 synthetic `catalog-missing.pdf` / `Sample PDF` / `File unavailable` error-only fixture；`BookshelfFixturesTests.withBooksLibraryDeclaresManifestPDFBook` 驗 repo UI World 與 generated demo 都有可由 PDFKit 讀取的 PDF asset。

### Word Edit vocabulary 契約（無本地 VocabularyEntry literal）
`WordEditScenarios` 的 populated / empty-explanation / long-content / long-word 狀態必須取 UI World `vocabulary.wordEdit` seed。scenario 必須把該 seed materialize 成 in-memory SwiftData `Notebook` + `VocabularyEntry` rows，再以 manifest 內的 word 選取 entry；缺 seed、缺 entry、row state key 漏宣告、SwiftData seed/save 失敗都直接 fail-fast。`CatalogCoverageTests.wordEditCatalogUsesUIWorldVocabularySeed` 擋回本地 `sampleEntry`、`Sample Book` 與 inline `VocabularyEntry(...)`。

### KG Vocab search 契約（無本地搜尋資料 / auth）
`KGVocabSearchScenarios` 的 matches / single-match / no-match 狀態必須取 UI World `vocabulary.searchVocabNotebook` seed，並用 UI World `auth.signedIn` 注入登入狀態。scenario 必須把 vocabulary seed materialize 成 in-memory SwiftData rows，且在 construction time 驗證 query 對 manifest entries 的命中數（多筆 / 單筆 / 零筆）符合 scenario；缺 seed、auth 非 logged-in、query drift、row state key 漏宣告或 SwiftData seed/save 失敗都直接 fail-fast。`CatalogCoverageTests.kgVocabSearchCatalogUsesUIWorldVocabularyAndAuthSeeds` 擋回本地 `KGVocabSearchFixtures`、inline `VocabularyEntry(...)` / `Notebook(...)` 與硬寫 catalog user/token。

### Notebook filter picker 契約（無本地 Notebook row / empty fallback）
`NotebookFilterChipScenarios` 的 with-notebooks / empty-list 狀態必須取 UI World `notebook.*` seed；empty-list 也必須是 manifest 內明示的 `notebook.empty`，不可用本地 `[]` 表示。scenario 必須透過 `NotebookFixtures.renderModel(for:)` materialize notebooks，選取狀態只能用 manifest row 的 `remoteId`；缺 seed、selected index drift、SwiftData seed/save 失敗都直接 fail-fast。`NotebookFixtures` 的 container 是非 optional；不能用 nil container 或空列表當渲染 fallback。`CatalogCoverageTests.notebookFilterChipCatalogUsesUIWorldNotebookSeeds` 擋回 `sampleNotebooks`、inline `Notebook(remoteId:)`、`notebooks: []` 與硬寫 `nb-1`。

### Settings subscription 契約（無本地 section fixture）
`SettingsSubscriptionSectionScenarios` 的 active/loading/pricing-unavailable/free 狀態必須取 UI World `settings.*` seed 的 `subscription` slice；`subscription_free` 也必須存在於 repo UI World / generated demo manifest。scenario source 不可直接引用 `SettingsPresenterPreviewData.*.subscription!`、不可保留 `inactiveFreeFixture`，也不可手建 `SettingsPresenterState.SubscriptionSection(...)`。

### Settings account detail 契約（無本地 auth/danger fixture）
`SettingsAccountDetailScenarios` 的 subscribed/deleting/logged-out/long-identity 狀態必須取 UI World `settings.*` seed；長字串壓力狀態是 `settings.account_long_identity`，且 repo UI World / generated demo manifest 都必須宣告。scenario source 不可直接引用 `SettingsPresenterPreviewData.*.auth` / `.danger`，不可保留 `loggedOutAuth` / `longInfoAuth`，也不可手建 `SettingsPresenterState.AuthSection(...)` 或 `DangerSection(...)`。

### Settings account section 契約（無本地 auth/pro fixture）
`SettingsAccountSectionScenarios` 的 logged-out / subscribed / loading / pricing / logged-out-error 與 Auth Summary pro/free/long-identity 狀態必須取 UI World `settings.*` seed；logged-out error 是 `settings.account_logged_out_error`，long identity 是 `settings.account_long_identity`。scenario source 不可保留 `loggedOutWithError` / `longIdentityState`，不可手建 `SettingsPresenterState.AuthSection(...)`，也不可用本地 `isProActive: true/false` 決定 Pro badge。

### Settings preferences section 契約（無本地 preference fixture）
`SettingsSectionsScenarios` 的 `SettingsPreferencesSection` auto-sync on/off/hidden 狀態必須取 UI World `settings.*.preferences` seed；auto-sync off 是 `settings.preferences_auto_sync_off`，logged-out/no-sync-row 是 `settings.preferences_logged_out_no_sync`。scenario source 不可手建 `SettingsPresenterState.PreferencesSection(...)`，也不可在 Debug source 寫死 `autoSyncEnabled` / `showAutoSync`。

### Settings review section 契約（無本地 ReviewSettings fixture）
`SettingsSectionsScenarios` 的 `SettingsReviewSection` relaxed/intensive/custom/paused 狀態必須取 UI World `settings.*.reviewSettings` seed；relaxed 使用 `settings.subscription_free`，intensive 使用 `settings.preferences_auto_sync_off`，custom 使用 `settings.account_long_identity`，paused 使用 `settings.preferences_logged_out_no_sync`。scenario source 不可手建 `ReviewSettings(...)`、不可寫死 `mode: .relaxed/.intensive/.custom`、不可用本地 `Date(timeIntervalSince1970:)` 或 `isProgressPaused: true` 決定暫停狀態。

### 裁決紀錄（borderline，已拍板，2026-06-09）
1. **Word Detail Loading Shimmer → OUT**：shimmer 是 Card Document 的 loading 皮、非可指名物件，降為 V11 Card Document 的 `shimmer` 狀態，不獨立計組件。
2. **計數粒度 → 維持折入**：catalog 原子是視圖；chrome header / autoplay bar / completion celebration 不可獨立瀏覽、只在母視圖內有意義，折入當狀態。promote 門檻＝跨視圖共用或有值得單獨檢視的豐富獨立狀態。
3. **Editorial Cover Composition → 折入**：作 Notebook Stacked Cover 的 with-name 狀態，不獨立 surface。

> 三項裁決一致裁向「精簡／視圖為根」，與本表反 catalog 膨脹的主旨對齊。相對 workflow 草稿，IN 必要組件由 29 降為 27（shimmer、editorial 兩項降為狀態）。

---

## 跨 feature 共用組件（先定義一次）

| 共用組件 | sourceFile | 服務視圖 | catalog |
|---|---|---|---|
| **Translation Panel** | `Reader/TranslationPanel.swift`（reader）、`Podcast/PodcastPlayerView.swift`（podcast 內嵌） | Reader View、PDF Reader、Podcast Player | reader 版 KEEP；**podcast 版 NEW** |
| **Vocab Highlight Picker** | `Reader/VocabHighlightColorPresetPicker.swift` | Reader（標色 preset）、Podcast Settings Popover | **KEEP**（`CatalogScene.swift:196` 已存在，5 scenario：Paper/Blue/Sage/Rose/Dark）；服務兩入口 |
| **Subscription Paywall Sheet** | `Settings/SubscriptionPaywallSheet.swift` | Settings、Lifecycle/monetization | 同一 surface KEEP —— 兩 feature 指向同檔，不重複建 |
| **Free vs Pro comparison table** | `Settings/SubscriptionPaywallSheet.swift` | Paywall | KEEP；唯一定義 |
| **Archived Vocab Sheet** | `Vocabulary/Scenes/ArchivedVocabSheet.swift` | Vocabulary List、Notebook List | KEEP；唯一 surface，服務兩入口 |
| **WordRow** | `Vocabulary/Components/WordRow.swift` | Vocabulary List、Archived Vocab Sheet | KEEP |
| **Login Sheet** | `Auth/LoginSheet.swift` | Welcome、Bookshelf、Notebook、Settings 登入 gate | KEEP；social button 為 primitive，OUT |

> 去重原則：同 sourceFile 的 surface 只定義一次，其餘 feature 以「服務視圖」引用，不另開 surface。

---

## 主表（以視圖為根）

### Feature: Reader

#### V1. Reader View (EPUB chrome) — `screen` — KEEP
`Reader/ReaderView.swift`
- states：loading / populated / error-iCloud / error-offline / error-general
- Reader chrome header（`ReaderViewPresenter+Headers.swift`）— expanded / compact / compact-no-progress —（折入狀態）

#### V2. PDF Reader View — `screen` — KEEP
`Reader/PDFReaderView.swift` — populated-manifest-pdf / loading / error-unreadable / error-corrupt

#### V3. Translation Panel (reader) — `overlay` — KEEP（共用）
`Reader/TranslationPanel.swift` — loading / populated-translation / saved / explanation-only / expanded / error-translation / error-explanation / logged-out / panel-large

#### V4. Reader Settings Panel — `overlay` — KEEP
`Reader/ReaderSettingsPanel.swift` — populated / font-min / font-max

#### V5. Table of Contents — `overlay` — KEEP
`Reader/TOCView.swift` — loading / loaded / empty / failed

#### V6. Reader Notebook Picker — `overlay` — KEEP
`Reader/ReaderNotebookPicker.swift` — populated / empty

#### V6b. Vocab Highlight Picker — `overlay` — KEEP（共用，見上）
`Reader/VocabHighlightColorPresetPicker.swift` — Paper / Blue / Sage / Rose / Dark
- 裁決：具名 picker overlay、有自身 5 態、使用者主動開啟選色 → IN（swatch 是其內部 token，OUT）

---

### Feature: Vocabulary

#### V7. Vocabulary List View — `screen` — KEEP
`Vocabulary/Scenes/KGVocabView.swift`
- states：loading / empty(no entries) / empty(no match) / empty(logged out) / populated / error / offline·pending-delete banner / selection mode / overflow
- `[組件]` **Word Row**（`WordRow.swift`）— learned/due/unlearned/selected/overflow/tone+progress — KEEP
- `[組件]` **Review State Tab Selector**（`VocabShellComponents.swift`）— single/multi/with-counts/zero — **NEW**
- `[組件]` **Sort Pill**（`VocabShellComponents+Actions.swift`）— default/active — KEEP
- `[組件]` **Review CTA Pill**（`VocabShellComponents+Actions.swift`）— due/unlearned/mixed/hidden — **NEW**
- `[組件]` **Selection Toolbar**（`SelectionToolbar.swift`）— 1/N selected — **NEW**
- `[組件]` **Tone Chip**（`VocabComponents.swift`）— neutral/positive/negative — KEEP
- `[組件]` **Review Progress Bar**（`VocabComponents.swift`）— empty/partial/full/gradient — KEEP
- `[組件]` **Empty State Card**（`KGVocabEmptyState.swift`）— no-entries/no-match/logged-out/filter-empty — KEEP

#### V8. Translation Pending List — `screen` — KEEP
`Vocabulary/Scenes/PendingVocabPresenter.swift` — empty / populated / overflow
- Pending Word Row → OUT（generic row primitive）

#### V9. Knowledge Graph View — `screen` — KEEP
`Vocabulary/KnowledgeGraphView.swift` — loading / empty(no cards) / empty(no links) / populated / error / settings overlay open
- `[組件]` **Graph Canvas**（`GraphWebView.swift`）— populated/node-tapped/isolated/color-by-ratio — **NEW**（簽名級主視覺）
- `[組件]` **Graph Force Settings Overlay**（`KnowledgeGraphPresenter.swift`）— open/closed — **NEW**

#### V10. Stats / Overview Dashboard — `screen`（feature=review）— KEEP
`Vocabulary/Scenes/StatsPresenter.swift` — loading / empty / populated / logged-out(gate) / graph-thumb error / graph-thumb stale
- `[組件]` **Graph Thumbnail Entry Card**（`GraphThumbnailWebView.swift`）— loading/empty/populated+health/error — **NEW**
- `[組件]` **Streak / Stat Hero Card**（`VocabShellComponents+Lists.swift`）— zero/active/transition — KEEP
- `[組件]` **Activity Heatmap**（`VocabActivityHeatmap.swift`）— empty/sparse/dense — KEEP
- `[組件]` **Forecast Chart**（`VocabForecastChart.swift`）— 7/14/30 buckets/empty/populated — KEEP

#### V11. Word Detail Sheet — `overlay` — KEEP
`Vocabulary/Scenes/WordDetailSheet.swift` — loading / populated / with-links / no-links / link-error banner / excluded-from-reader toggled
- `[組件]` **Card Document**（`CardDocumentView.swift`）— hero/meaning/example/collocations/source/rich-text/**shimmer**（loading 皮，折入此態）— KEEP（整卡為原子；內部 block 全 CUT）
- `[組件]` **Linked Card Overlay Stack**（`LinkedCardOverlayStack.swift`）— 1/stacked/empty — KEEP

#### V12. Word Edit Sheet — `overlay` — KEEP
`Vocabulary/Scenes/WordEditSheet.swift` — editing/populated/empty-fields

#### V13. Add Link Sheet — `overlay` — KEEP
`Vocabulary/Scenes/AddLinkSheet.swift` — empty/results/no-match/error banner

#### V14. Archived Vocab Sheet — `overlay` — KEEP（共用）
`Vocabulary/Scenes/ArchivedVocabSheet.swift` — empty/populated/search/no-results/unarchive-error

#### V15. Collocation Explain Sheet — `overlay` — KEEP
`Vocabulary/Components/CollocationExplainSheet.swift` — loading/populated/error

#### V16. Link Reason Sheet — `overlay` — KEEP
`Vocabulary/Overlay/LinkReasonSheet.swift` — populated(reason+confidence+actions)

#### V17. Review Calendar Sheet — `overlay`（feature=review）— KEEP
`Vocabulary/Scenes/ReviewCalendarPresenter.swift`（reclassify：實為可見 sheet）— current/prev-next nav/active month/empty month
- `[組件]` **Calendar Grid**（`VocabCalendarGrid.swift`）— empty/sparse/dense/today — KEEP

---

### Feature: Review (Today Review)

#### V18. Today Review Phase — `overlay`（4-state wrapper）— KEEP
`Vocabulary/Scenes/TodayReviewPhaseView.swift` — loading / empty / error(retry) / session
- Empty state card（共用 VocabSceneShell）—（折入 Empty scenario）

#### V19. Today Review Session — `overlay`（swipe deck + fold + reveal）— KEEP
`Vocabulary/Scenes/TodayReviewView.swift` + `TodayReviewPresenter.swift` — front / back / swiping-fling / autoplay / completion / multi-card / long-content overflow
- `[組件]` **Review Fold Card**（`ReviewFoldSurface.swift` + `TodayReviewPresenter+CardContent.swift`）— front-single / answer-open / production(cloze) / recognition / collapsing — **KEEP 但需 consolidate**（現拆 3 個 engineering surface：Segment/Chevron Pill/Paper Fold → 合併單一卡組件）
- `[組件]` **Swipe Deck**（`TodayReviewSwipeDeck.swift`）— idle/rising/single/next-preview — **NEW**（簽名級 2-deep 旋轉卡疊）
- `[組件]` **Card Answer Link Strip**（`TodayReviewPresenter+CardContent.swift`）— has-links / no-links — **NEW**
- Autoplay Control Bar（`TodayReviewPresenter+Toolbar.swift`）— playing/paused/sound/speed/at-start/at-end —（折入 Autoplay scenario）
- Completion celebration（`TodayReviewPresenter.swift`）— bounce-in —（折入 Completed scenario）

---

### Feature: Notebook

#### V20. Notebook List View — `screen` — KEEP
`Vocabulary/Scenes/NotebookListView.swift` — loading / empty(logged-in CTA) / empty(logged-out CTA) / populated / reconcile-error banner / sync-pending tip / covered
- `[組件]` **Notebook Card**（`NotebookCard.swift`）— populated/active/actionable/empty-notebook/pattern/custom-image/dark — KEEP
- `[組件]` **Stacked Notebook Cover**（`NotebookStackedCoverView`，live callsite `NotebookCard.swift:261` `.grid` style）— layerCount 0→1 / 1-50→2 / 51-200→3 / 200+→4 / pattern / custom-image / **with-name（Editorial Cover Composition 折入此態，`showsName:false` 由其接管 name）** — KEEP。`.grid` 每張 notebook 卡的立體封面本體；#671 換的是 list 排版，非 per-card 封面。
- `[組件]` **Notebook Review Action Bar**（`NotebookReviewActionBar.swift`）— both/due-only/unlearned-only/none/filtered/create-disabled — KEEP

#### V21. Notebook Edit Sheet — `overlay` — KEEP
`Vocabulary/Scenes/NotebookEditSheet.swift` — create / edit / color-picked / pattern-picked / photo-processing / photo-error / custom-image-set / save-disabled
- `[組件]` **Notebook Cover View**（`NotebookCoverPatterns.swift`）— color-only/pattern/custom-image/placeholder — KEEP

#### V22. Notebook Filter Picker Sheet — `overlay` — KEEP
`Vocabulary/Components/NotebookFilterChip.swift` — all/filtered/single-selection

---

### Feature: Bookshelf

#### V23. Bookshelf Screen (書庫) — `screen` — KEEP
`Bookshelf/BookshelfView.swift` — empty·logged-out / empty·logged-in / populated grid / single book / loading overlay / import-error alert / import-error inline banner / overflow
- `[組件]` **Book Cover Card**（`Components/BookCard.swift`）— cover-present/placeholder/progress-0/progress-N/last-read present-absent/long-title-author/format-badge/iCloud-states — KEEP

---

### Feature: Podcast

#### V24. Podcast Home — `screen` — KEEP
`Podcast/PodcastHomeView.swift` — loading / error / empty / populated / populated-with-continue-shelf
- `[組件]` **Podcast Series Card**（`PodcastSeriesCard.swift`）— default/followed/no-host/no-cover/long-title — **RELOCATE**（scenario 已在 `PodcastShelfCardsScenarios.swift`，搬至 podcast slice，不新建）
- `[組件]` **Podcast Continue Rail Card**（`PodcastShelf.swift`，scenario `PodcastShelfCardsScenarios.swift`）— Resume/No progress/Long title/Large numbers/A11y3 — **RELOCATE**（由 bookshelf 搬至 podcast slice）
- `[組件]` **Podcast Shelf (continue carousel)**（`PodcastShelf.swift`）— populated carousel — KEEP

#### V25. Podcast Episode List — `screen` — KEEP
`Podcast/PodcastEpisodeListView.swift` — loading-skeleton / error / empty / populated / stale-banner / sort-asc-desc
- `[組件]` **Podcast Series Hero**（`PodcastSeriesHero.swift`）— with-cover/no-cover/full-meta/no-host — KEEP
- `[組件]` **Podcast Continue Card**（`PodcastSeriesHero.swift`）— resume/play/replay/locked-Pro/locked-guest/unavailable — KEEP
- `[組件]` **Podcast Episode Row**（`PodcastEpisodeRow.swift`）— unplayed/in-progress/completed/locked/downloading/downloaded/download-failed/audio-unavailable — KEEP

#### V26. Podcast Player — `screen` — KEEP
`Podcast/PodcastPlayerView.swift` — bootstrap-loading / missing-episode / audio-loading / audio-error / ready-playing-paused / locked-guest / locked-Pro / free-preview
- `[組件]` **Transcript Column**（`PodcastSentenceLevelView.swift`）— follow/manual/current-highlight/vocab-highlight/selecting/subtitle-failed/size S-XXL — KEEP
- `[組件]` **Subtitle Bubble Cell**（`PodcastSentenceLevelView.swift`）— host-left-right/speaker-label/current/next/vocab-highlighted/selected — KEEP
- `[組件]` **Podcast Controls**（`PodcastControlsView.swift`）— playing/paused/scrubbing/buffered/rate — **NEW**
- `[組件]` **Preview Upgrade Banner**（`PodcastPlayerView.swift`）— free-preview active — **NEW**

#### V27. Podcast Settings Popover — `overlay` — KEEP
`Podcast/PodcastSettingsPopover.swift` — default/sleep-timer/auto-pause/word-follow/highlight-swatch
- 內嵌 Vocab Highlight Picker（見 V6b 共用，不重複計）

#### V28. Translation Panel (podcast) — `overlay` — **NEW**
`Podcast/PodcastPlayerView.swift`（內嵌共用 TranslationPanel）— loading / translated / saved / explanation / error / expanded-collapsed

---

### Feature: Settings

#### V29. Settings — `overlay`（featureScreen 殼）— KEEP
`Settings/SettingsView.swift` — logged-out / logged-in free / Pro active / authenticating / auth-error / syncing / guest-demo
- `[組件]` **Account Section**（`SettingsAccountSection.swift`）— logged-out/logged-in/authenticating/auth-error/Pro-badge — KEEP
- `[組件]` **Account Auth Summary row**（`SettingsAccountSection.swift`）— avatar/initials/person-fallback/Pro/free — KEEP
- `[組件]` **Subscription summary row**（`SettingsAccountSection.swift`）— Pro/free-CTA/pricing-unavailable — **NEW**
- `[組件]` **Preferences Section**（`SettingsPreferencesSection.swift`）— auto-sync hidden/on/off/appearance/language menu — KEEP
- `[組件]` **Sync status row**（`SettingsOtherSection.swift`）— connected/warning/syncing — **NEW**
- `[組件]` **Quota row**（`SettingsOtherSection.swift`）— has/exhausted/loading — **NEW**

#### V30. Settings Account Detail — `screen` — KEEP
`Settings/SettingsAccountDetailView.swift` — logged-in / deleting
- Danger operations card —（折入 deleting 狀態）

#### V31. Translation Language Settings — `screen` — KEEP
`Settings/TranslationLanguageSettingsView.swift` — populated / row-saving / save-error / selected-highlight
- `[組件]` **Selectable language row** — flag+native-name+checkmark/saving — **NEW**

#### V32. Review Rhythm Settings (複習節奏) — `screen` — **NEW（promote）**
`Settings/SettingsReviewSection.swift` — relaxed / intensive / custom(params) / paused-clock / unpaused
- `[組件]` **Review mode selection tile** — icon+name 可選 tile — **NEW**
- Pause toggle card —（折入畫面狀態）

#### V33. Subscription Detail (訂閱) — `screen` — **NEW（promote）**
`Settings/SettingsSubscriptionSection.swift` — Pro active / pricing-unavailable / restore-available / refreshing

#### V34. Subscription Paywall Sheet — `overlay` — KEEP（共用）
`Settings/SubscriptionPaywallSheet.swift` — inactive-marketing / active-pro / cancelled-but-active / admin-granted / loading-retry / purchasing / purchase-status
- `[組件]` **Free vs Pro comparison table** — KEEP（唯一定義；plan table）

#### V35. Delete Account Sheet — `overlay` — KEEP
`Settings/SettingsDeleteAccountSheet.swift` — idle/partially-checked/all-checked-countdown/ready/deleting

---

### Feature: Lifecycle & monetization

#### V36. Welcome — `screen` — KEEP
`Welcome/WelcomeView.swift` — step1-capture / step2-link / step3-review / dark
- Walkthrough page —（per-step full-screen scene 覆蓋）

#### V37. App Startup Recovery — `screen` — KEEP
`Startup/AppStartupRecoveryView.swift` — idle / working-retrying / working-clearing / retryFailed / cacheCleared / mailUnavailable / exhausted
- Recovery status banner — 6 態（折入畫面狀態，見 MISSING 補中間態）

#### V38. Login Sheet — `overlay` — KEEP（共用）
`Auth/LoginSheet.swift` — default / authenticating / error
- Social auth button → OUT（primitive）

#### V39. Pro Access Gate Card — `overlay` — KEEP
`Subscription/SubscriptionViews.swift` — locked-prompt

> 註：V34 Paywall 在 monetization 與 settings 兩份盤點重複 → 單一 surface，不重複計入 IN 視圖數。

---

## RELOCATE 清單（surface 真實存在但歸錯 slice，搬遷不新建）— ✅ campaign 2 已落地

- **Podcast Series Card** — ✅ 搬至 podcast slice，現為 `block("Podcast Series Card", .podcast)`（`PodcastShelfCardsScenarios.swift`）
- **Podcast Continue Rail Card** — ✅ 搬至 podcast slice，現為 `block("Podcast Continue Rail Card", .podcast)`（同檔）
- 搬遷後 **Bookshelf surface** 已移除 podcast 卡，僅剩 Book Card + Loading（collapse 待後續 campaign，見 CUT 清單）

---

## CUT 清單（依 litmus 該砍的 catalog surface）

### Card sub-block 拆分（engineering 子片，整卡才是原子）
- Card Document · Hero / Meaning / Example / Collocations / Source
- Card Sections · Document / Examples / Explanation / Forms / Hero / Primitives / Source

### Presenter / harness 殼（消費 surface 已存在）
- Reader Settings Presenter / Translation Vocab Presenter / KG Vocab Presenter / Word Detail Presenter
- Selection Toolbar（reader，系統 UIEditMenuInteraction，非自製 view）
- Settings Actions · Subscription（presenter 重複）/ Settings Controls · Modifiers / Modifiers showcase

### Generic primitive / token（使用者不指名）
- Reader · Selection Tile / Step Control / Quota（QuotaBar 僅 #Preview，死碼）
- Vocab Shell · Accessory/Chrome/Inline Action Icon Button / Search Field / Section Header / Slider Row / Toolbar Glyph
- Vocab Components · Review Gradient Bar / Tier Label / Vocabulary List Toolbar / Word Detail Components · Graph Link Row
- Progress Capsule（review，app-wide primitive）
- Settings · ParamRow / Social Badge / Account Section · Pro Badge
- Settings Components · Chevron Icon / Disclosure Value / Menu Value / Section Footer / Section Header / Status Badge / Status Summary / Status Value / Title Subtitle
- Settings Controls · Input Field / Stepper / Settings Actions · Buttons
- Word Detail Loading Shimmer（裁決①：降為 Card Document 的 shimmer 狀態）

### 跨 slice 誤填 / scope 重分配
- Review Fold · Chevron Pill / Paper Fold / Segment（合併為單一 Review Fold Card — 見 V19）
- Review Calendar Presenter（屬 Stats/Calendar slice，非 Today Review session）
- Sync Step Duration / Word Detail Components · Sync Badge（誤填 review）
- Notebook Detail · CTA Pill / Row（屬 VocabularyListView detail，非 Notebook slice）
- Settings Subscription Section（屬 settings slice，非 lifecycle）
- Account Section · Auth Summary（lifecycle 盤點視為 settings harness）

### 死碼 / 已遷移 relic
- Notebook Filter Chip · Chip（inline pill primitive，list 用 ActionBar 內建 filter pill）
- Bookshelf surface（buildingBlock grab-bag；搬走 podcast 卡後僅剩 Book Card + Loading，collapse 不留具名 surface）

### Podcast primitive / presenter
- Podcast Progress Ticker（葉子只渲染 Color.clear，15Hz tick 隔離殼，永不見）
- Podcast Follow Toggle（star toggle button primitive）
- Podcast Badge（已追蹤/新集數 badge primitive）
- Podcast · Subtitle（PodcastSubtitleView 單行 presenter 殼；真正可見的是 Transcript Column / Bubble Cell）

### Bookshelf badge
- iCloud Progress Badge（cover-overlay download badge；badge 為 OUT primitive；其對 Book Card 的影響為 card state，補 fixture 不補 surface）

---

## MISSING 清單（app 有、catalog 缺）

### 視圖層 — 需新 surface
- **Translation Panel (podcast)** — `overlay`（loading/translated/saved/explanation/error/expanded）
- **Review Rhythm Settings** — `screen`（promote）
- **Subscription Detail (訂閱)** — `screen`（promote）

### 必要組件層 — reconciled（2026-06-09 scout + render 驗證）

**已覆蓋（既有 scenario 已含 → MISSING 為 stale，不重建）：**
- ~~Review State Tab Selector / Review CTA Pill / Selection Toolbar（vocab）~~ — ✅ campaign 3a 落地（`VocabShellComponentsScenarios` + `SelectionToolbarScenarios`）
- ~~Card Answer Link Strip（review）~~ — ✅ Today Review「Back」scenario 已渲染（`currentCardSeed` 含 3 links；驗證 PNG 見 📎 相關:precise｜thorough +1 ⊕）→ 屬母視圖 state，依計數契約不另計組件
- ~~Subscription summary row（settings）~~ — ✅ `SettingsSubscriptionSectionScenarios`（4 態，含 `SettingsStatusBadge`）
- ~~Sync status row（settings）~~ — ✅ `SyncScenarios`（5 態 phase）
- ~~Translation language selectable row（settings）~~ — ✅ `TranslationLanguageSettingsScenarios`（4 語對，`SettingsSelectableRow` in context）
- ~~Review mode selection tile（settings）~~ — ✅ `SettingsSectionsScenarios`（寬鬆/密集/自訂，`SettingsSelectionTile`）
- ~~Free vs Pro comparison table（paywall）~~ — ✅ = 既存 `Settings Actions · Plan Table`（eng surface，唯一定義）
- ~~Quota row（settings）~~ — ✅ N/A：`QuotaBar` 已於 CUT 清單判死碼（僅 `#Preview`），不補

**真缺但耦合（非廉價：需 presenter/VM harness，暫不建以免污染生產 API）：**
- Graph Canvas / Graph Force Settings Overlay / Graph Thumbnail Entry Card（KG — `GraphWebView` WKWebView + force sim + private @State）
- Swipe Deck（review — gesture/motion private @State coordinator）
- Podcast Controls（`PodcastControlsView` 耦合 `PodcastPlayerViewModel` + KVO/audio session）
- Preview Upgrade Banner（podcast — `PodcastPlayerView` computed prop，耦合 `PodcastPlayerAccessState`）

### 畫面 / 組件狀態 — 既有 surface 補拍（2026-06-09 scout 驗證重分級）

**已覆蓋（既有 scenario 已含 → stale）：**
- ~~Today Review · long-content overflow card~~ — ✅ 本 PR 落地（`TodayReviewFixtureID.longContent` fixture + scenario，走 fixture seam）
- ~~Bookshelf · empty logged-out vs logged-in~~ — ✅ `BookshelfViewScenarios`「Empty shelf」
- ~~Bookshelf · Book Card format badge~~ — ✅ `BookCardScenarios`（EPUB/PDF badge）
- ~~Paywall active / expiring / admin~~ — ✅ `PaywallScenarios`（renewing / cancelled-but-active / admin-granted）
- ~~Login Sheet authenticating + error~~ — ✅ `LoginSheetScenarios`（Authenticating / Error）

**廉價可補（走既有 fixture seam，非污染 production view）：**
- Today Review · production-mode front card（cloze）— 加 `TodayReviewFixtureID` case + seed（`reviewMode: .fillBlank`）；注意 `allCases` ripple（fixture tests）。（long-content overflow 已於本 PR 落地，見上）

**耦合，暫不補（私有 @State / async / CloudKit — 補需污染生產 view 的 DEBUG init seam，前作者已刻意不做）：**
- Startup Recovery 中間態（working / cacheCleared / mailUnavailable）— **confirmed**：`phase` 私有 @State、點擊驅動，static snapshot 只達 `.idle`（見 `AppStartupRecoveryScenarios` docstring）
- Today Review · swiping/fling in-flight — motion/gesture private state
- Bookshelf · loading overlay（`BookshelfCoordinator.isLoading` 私有 @State，無注入 seam；舊 grab-bag 的合成 `BookshelfLoadingPreview` 已隨 Bookshelf surface CUT 移除）/ import-error inline banner（async import 失敗）/ iCloud states（CloudKit @Model metadata）
- Notebook List · reconcile-error / empty-logged-out / loading（coordinator 私有 @State；scout 標 cheap 但需驗 init seam）
- Notebook Edit · photo error / processing（sheet 私有 @State；同上）
- Stats logged-out gate state（需 `CatalogPreviewAuth` env 注入，待驗）
- Podcast Episode List · Stale Data Banner（`loadError`+episodes 私有 @State，待驗）
