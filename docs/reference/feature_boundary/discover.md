<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Views/Explore/
  - ios/BooksAndVocab/Models/SharedDeck.swift
  - ios/BooksAndVocab/Services/SharedDeckCatalogService.swift
verified_against: 888dde5f0
-->
# Explore (Shared Decks) Feature Boundary

> Explore（探索）= 第 5 個 top-level section（`AppPrimarySection.explore`），
> 共享牌組庫的 iOS 對外 surface。後端 namespace 是 `shared_decks`、公開路由 `/api/decks`
> （endpoint / DTO / store 見 `docs/reference/tech_index.md`）。**禁用 `library` 一詞**
> —— 那是 EPUB/PDF 書庫（Bookshelf），命名碰撞會混淆。
>
> **Phase 1–2（本切片）**：guest 瀏覽 / 預覽官方策展牌組（Phase 1）＋**複製官方牌組
> 進私人 Notebook 即時複習**（Phase 2）。Explore section 由 `KGFeatureFlags.exploreEnabled`
> **DEBUG-only** gate—— Release build 不曝光，待 Release-flip（telemetry 補齊）。
> publish / rate / report 與 ShareLink deep-link 分享一律 Phase 2/3 fast-follow，見「範圍邊界」。

## 檔案清冊

### 導航接線（ContentView）

| 檔案 | 說明 |
|------|------|
| `ContentView.swift` | `enum AppPrimarySection` 加 `case explore`（`titleKey="app.section.explore"`、`systemImage="sparkles"`）。gate 走 `visibleCases(podcastEnabled:exploreEnabled:)`；iOS TabView 分支 render `ExploreView()`（`accessibilityIdentifier("tab.explore")`）+ macCatalyst `NavigationSplitView` sectionContent 分支（Catalyst parity 必驗）。 |
| `Models/KGFeatureFlags.swift` | `static let exploreEnabled`：**compile-time `#if DEBUG` 常數**（DEBUG→`true`、Release→`false`）。整個 Explore 面在 Release 零曝光；測試 `AppPrimarySectionTests`。 |

### Model Layer（唯讀 mirror）

| 檔案 | 說明 |
|------|------|
| `Models/SharedDeck.swift` | `@Model final class SharedDeck` —— 唯讀 mirror，**刻意不 reuse `Notebook @Model`**（否則 public/official 牌組滲進私人 Notebooks `@Query`）。欄位：`remoteId`（server 鑄造 deckId，穩定鍵）/ `title` / `authorLabel?` / `isOfficial`（source-driven badge，非 client-settable）/ `category?` / `languagePair?` / `tags` / `cardCount` / `downloadCount` / `ratingAvg?` / `ratingCount` / `color?` / `coverPattern?`（procedural cover，復用 `NotebookCoverView`，**非** image path）/ `updatedAt?` / `sortOrder`（server browse 次序固化）/ `isSoftDeleted`（`@Attribute(originalName:"isDeleted")` 本機 tombstone，鏡射 `PodcastSeries`）/ `syncedAt`。須 register 進 ModelContainer schema。 |
| `Models/SharedTypes.swift` | wire models（lenient decode，ignore unknown keys）：`SharedDeckSummary` / `SharedDeckCard` / `SharedDeckListResponse` / `SharedDeckDetail` / `SharedDeckCardsResponse`。 |
| `Models/Notebook.swift` | provenance 欄位（**Phase 2 copy 起 stamp**）：`sourceSharedDeckId: String?` / `sourceVersion: Int?`（跨裝置 sync 走 `KGNotebook` + `NotebookResponse`；copy 落地卡是已 synced server rows，不進 outbox——sync 語意見 `docs/reference/sync_lifecycle.md`）。 |

### Service Layer（PodcastSyncService analog）

| 檔案 | 說明 |
|------|------|
| `Services/SharedDeckCatalogService.swift` | `final class SharedDeckCatalogService` = `PodcastSyncService` 1:1 analog。`optionallyAuthedData(from:kgService:)` guest browse（無 token 亦放行）；`fetchDeckList(query:)` / `fetchDeckDetail(deckId:)` / `fetchDeckCards(deckId:cursor:limit:)`；`syncAll(context:)` **全目錄 cursor 分頁**（跟 `nextCursor` 抓完整個 catalog 再 reconcile；**截斷對稱化**——分頁被截斷時 skip reconcile，partial set 絕不驅動 mass-delete）→ upsert + `reconcileLocalState(serverSummaries:context:)` **empty-response mass-delete guard**（空 server list 視為非權威、不下 tombstone）。nested `BrowseQuery`（filter → `URLQueryItem`）。測試 `SharedDeckCatalogServiceTests` / `SharedDeckModelIsolationTests` / `SharedDeckWireDecodeTests`。 |
| `Services/KGService+Decks.swift` | copy 傳輸擴充。`copyDeck(deckId:idempotencyKey:notebookName:)` 打 `POST /api/decks/{id}/copy`（`DeckCopyResponse`）；`pullCopiedDeck(...)` post-copy **notebook-first targeted pull**——複製後只針對新 notebook + 其卡做 incremental pull，讓卡片與新本即時可複習（既有 synced server rows，不進 outbox）。測試 `SharedDeckCopyPullTests`。 |

### View Layer（`Views/Explore/`）

| 檔案 | 說明 |
|------|------|
| `ExploreView.swift` | 主場景：search field + filter chips（category / language-pair / official segment / sort）+ 四態（loading/empty/error/partial，見 `docs/reference/ui/state_matrix.md`）；counts/dates 走 `LocaleAwareFormatter`。 |
| `SharedDeckDetailView.swift` | 預覽（card count / sample cards / author + official badge / rating / download count）**＋ 複製 CTA**（Phase 2）：tap → destination picker（可建新本、預填名）→ 觸發 `SharedDeckCopyController`；4-state（idle / copying / done / error）+ offline / logged-out gate（離線或未登入時 CTA 停用並提示）。 |
| `SharedDeckCopyController.swift` | 複製編排（Phase 2）。持有 **stable `idempotencyKey`**（同一次複製意圖重試不產生重複 notebook）；驅動 `KGService+Decks.copyDeck` → `pullCopiedDeck`，管理 4-state 與 offline / logged-out gate。測試 `SharedDeckCopyControllerTests`。 |
| `ExploreDeckCard.swift` | Explore grid/list 的 deck 卡片元件。 |
| `ExploreFilterChip.swift` | filter chip 元件。 |
| `SharedDeckPresentation.swift` | Explore 呈現層純函式（view data 組裝）；測試 `SharedDeckPresentationTests`。 |

### Debug / Test 錨點

| 檔案 | 說明 |
|------|------|
| `Debug/Scenarios/ExploreViewScenarios.swift` / `SharedDeckDetailViewScenarios.swift` | Catalog surface scenarios（`CatalogScene` 註冊）。 |
| `Debug/Scenarios/SharedDeckCatalogFixtures.swift` | Catalog / UI-World 的 SharedDeck seed 資料。 |
| `BooksAndVocabUITests/ExploreNavigationUITests.swift` | Explore tab 導航 + a11y UITest（`AppPage` 加 Explore 入口）。 |

## 改動規則

- **新增 Explore 畫面 / 元件** → `Views/Explore/`；動工前讀 `docs/sop/ui-design.md` + `docs/reference/ui/{components,review_checklist,state_matrix}.md`；deck cover 復用 `NotebookCoverView`。每新 full-screen View 必 register `Debug/CatalogScene.swift` surface + UI-World scenario，否則 `CatalogCoverageTests` red。
- **改共享牌組 wire / model** → `Models/SharedTypes.swift`（lenient decode）+ `Models/SharedDeck.swift`（@Model，改欄位須 verify SwiftData lightweight migration）。**絕不** reuse `Notebook @Model`。
- **改 browse / sync 邏輯** → `Services/SharedDeckCatalogService.swift`（reconcile 純邏輯保 empty-response guard；`syncAll` 全目錄分頁保截斷對稱化）。
- **改複製流程（copy）** → client 走 `Views/Explore/SharedDeckCopyController.swift` + `Services/KGService+Decks.swift`（stable idempotencyKey、post-copy notebook-first targeted pull）；server-side clone 不變量與 `POST /api/decks/{deckId}/copy` 見 `docs/reference/tech_index.md`。**官方牌組可複製性**由 emitter curation guard `_assert_copyable` 在 emit 前把關（擋同 deck 內 NOCASE 同形字碰撞，否則 copy 端撞私人 `Card` `UNIQUE(content COLLATE NOCASE, notebook_id)` 致 count mismatch）——見 `docs/reference/tech_index.md` `build_official.py` 條目。
- **改後端 endpoint / DTO / store / env** → 見 `docs/reference/tech_index.md`（`/api/decks` router、`shared_decks.db` 6 表、DTO、cursor、caps env、`Notebook.is_staged` copy barrier）。
- **i18n 鐵律 8**：新 View 零 raw 中文；`app.section.explore` + 所有 Explore/preview keys 進全 5 lproj。使用者供給的 deck title / authorLabel 是 runtime 資料（i18n 覆蓋外）。

## 範圍邊界（Phase 分期）

| 能力 | Phase | 狀態 |
|------|-------|------|
| guest 瀏覽 / 預覽官方牌組（唯讀）| 1 | ✅ 本切片 |
| Explore section Release 曝光 | 2 | ⏳ DEBUG-gated（`exploreEnabled`）|
| 複製官方牌組進私人 Notebook（copy）+ destination picker + 即時複習 | 2 | ✅ 本切片 |
| ShareLink deep-link 分享 | 2 | ⏳ fast-follow（deferred、out-of-scope）|
| `deck_browse` / `deck_preview` / `deck_copy` telemetry 事件 | 2 | ⏳ 未實作（Release-flip 補）|
| Card / Notebook provenance stamp（`sourceSharedDeckId/Version` + `source_shared_card_guid`）| 2 | ✅ 本切片（copy 落地即 stamp）|
| PublishSheet / 「我發布的牌組」/ rating / report UI | 3 | 🔒 UGC，需執行長 go |

架構 SoT（資料模型 / API surface / 風險全集）：`docs/plans/2026-07-09-shared-decks-library.md`（archive，凍結規劃）。

## 相關 doc

- `docs/reference/tech_index.md` **(SoT)** — `/api/decks` router、`shared_decks.db` 表、DTO、cursor、env、`build_official.py` CLI
- `docs/reference/product_surface.md` **(SoT)** — 已實作能力清冊（Explore bullet）
- `docs/reference/feature_boundary/notebook.md` — 牌組容器（copy 目標，Phase 2）
- `docs/reference/sync_lifecycle.md` **(SoT)** — copy 語意（provenance inert / guest-tolerant browse 不進 outbox）
- `docs/reference/ops_state_plane.md` **(SoT)** — 官方注入 emitter（`build_official.py`）§4 入口偏差
