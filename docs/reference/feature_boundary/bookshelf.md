<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksBrowser/Views/Bookshelf/
verified_against: 6511588c
-->
# Bookshelf Feature Boundary

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `BookshelfView.swift` | ~300 | 主容器 `struct BookshelfView: View`，**純書籍書架** + 匯入流程；row 子 view 已抽出至 `Components/`。**podcast 已抽離為獨立頂層 section**（見 `podcast.md` `PodcastHomeView`）——本 view 不再持有 podcast query / overlay master pane / `selectedSeriesRemoteId` / `PodcastNavRoute` 路由 / podcast 同步觸發。**Navigation 契約（仍守）**：root 必須 `NavigationStack(path: $navigationPath)`（app 持有 `@State NavigationPath`），**不可** bare `NavigationStack { }`；**root content 恒定**：bookGrid / emptyState 由 `if books.isEmpty` 直接決定，**不可**用 `if/else` 替換 root content（root-content swap 在顯示過替換內容後會**永久破壞** value-based push，NAVDBG 坐實）。`navigationDestination(for: Book.self)` 接住書籍 → reader 的 value-based push（freeze-fix 契約 PR #366/#368/#370/#373）。書本為本地 `@Query`、無遠端 catalog；`.refreshable`（iOS/iPadOS，掛 emptyState + bookGrid）與 Mac toolbar `bookshelf.refreshButton` 觸發的是**帳號資料背景同步**（詞庫/複習/KG，**非**刷新書本清單），均經 `coordinator.sync` → `ExplicitSync` 統一回饋,且共用**資格 gate**（登出 / demo → 靜默 no-op，對齊自動同步;空書架正是登出用戶畫面,故必擋以免誤觸 `unauthorized` 而誤彈「登入已過期」）。Mac ⌘R 由 `MacMenuCommands` 全域擁有，toolbar 鈕**不**重綁。鏡射 `NotebookListView.swift` root-恒定模式 |
| `BookshelfPreviews.swift` | 133 | `#Preview` 集中地（mock data scaffolds、各 row 型態樣本） |

### Coordinator Layer（導航協調）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `BookshelfCoordinator.swift` | 223 | `@MainActor protocol BookshelfCoordinating` + `@Observable @MainActor` 實作，含匯入、刪除、批次選擇、open reader / podcast 導航狀態、顯式同步 `sync(...)`（吃窄協定 `any BackgroundSyncing`，`isSyncing` 重入守衛，委派 `ExplicitSync.run`） |

### Components Layer（row UI）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `Components/BookCard.swift` | 207 | `struct BookCard: View` — 書架單列 row（cover / 標題 / 進度 / context menu）。進度條永遠保留占位（0% 也不壓縮卡片高度），進度值 clamp 到 [0,1]，0% 時 a11y 隱藏 |

### Token Layer（local metric）

| 檔案 | 行數 | 說明 |
|------|------|------|
| `BookshelfMetrics.swift` | 15 | `enum AppBookshelfMetrics`，feature 內專用 spacing / cover 尺寸常數；跨 feature 共用值已升級至 `AppMetrics`（詳 `docs/snapshot/feature_metrics.md`） |

---

## 改動規則

- **新增書籍 row UI** → `Components/` 子目錄擴充（`BookCard` 或新增同層 row 元件）。播客 row 元件已隨 podcast section 遷出至 `Views/Podcast/`（見 `podcast.md`）
- **新增匯入流程** → `BookshelfView` body（建議走 `.sheet` + 既有 `appSheet` modifier）+ `BookshelfCoordinator` 加 navigation state
- **新增資料來源（書籍/播客以外的內容類型）** → 評估是否獨立成新 feature scope，避免 `BookshelfView` 繼續長
- **新增可復用 UI 元件** → 評估是否屬於 app shell 級（`AppShellComponents.swift`）；feature 專屬留在 `BookshelfView` 內
- **改顯式同步行為**（pull-to-refresh / toolbar 鈕 / ⌘R）→ 動 `Services/ExplicitSync.swift`（單一真相：資格 gate `isLoggedIn && !isDemoMode`〔登出/demo 靜默 no-op〕→ 成功彈 toast、失敗 warning + `lastBackgroundSyncError` read-then-clear）。eligibility 以 bool 傳入（不耦合 `AuthManaging`）。**勿**在 view/coordinator 重抄這段；自動同步（scenePhase / post-login）刻意維持成功靜默，見 `BooksBrowserApp`
- **新增 metric token** → 跨 feature 用先升級到 `AppMetrics`；單 feature 用留 `AppBookshelfMetrics`（參考 `feature_metrics.md` 升降規則）

## State 邊界

- `BookshelfCoordinator`：書架導航與 sheet 狀態（匯入 / 詳情 / 批次刪除確認），由 `BookshelfView` 持有，不外洩
- 書籍資料來源於 SwiftData `@Query` + `@Environment(\.modelContext)`，不放 coordinator（播客 series 已遷至 `PodcastHomeView`）
- 匯入進度狀態走 `ImportProgressCallback`（app shell 層），不放 feature

## 共用依賴

| Token | 用途 |
|-------|------|
| `AppTheme` | 色彩，`@Environment(\.appTheme)` |
| `AppMetrics` / `AppShellMetrics` | 間距、尺寸 |
| `AppMotion` | 動畫 token |
| `AppTransition` | 過渡動畫 |
| `AppBookshelfMetrics` | Bookshelf 專用 cover / progress / spacing 常數 |

## 相關 doc

- `docs/snapshot/feature_metrics.md` — `BookshelfMetrics` token 升降紀錄
- `docs/reference/feature_boundary/notebook.md` — bookshelf 透過 notebook 入口進入詞庫流程
- `docs/reference/feature_boundary/reader.md` — bookshelf 點書打開的 reader 主場景
- `docs/reference/feature_boundary/podcast.md` — podcast 已抽離為獨立頂層 section（`PodcastHomeView`），不再經書架進入
