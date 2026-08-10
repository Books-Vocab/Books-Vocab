<!-- doc-meta
tier: reference
authority: derived
update_trigger: code-change
scope:
  - ios/BooksAndVocab/Views/Bookshelf/
  - ios/BooksAndVocab/Models/Book.swift
  - ios/BooksAndVocab/Models/BookManifest.swift
  - ios/BooksAndVocab/Models/BookLibraryReconciler.swift
  - ios/BooksAndVocab/AppOrphanBookRecovery.swift
  - ios/BooksAndVocab/AppStartupRecovery.swift
  - ios/BooksAndVocab/Services/BookMetadataRepairService.swift
  - ios/BooksAndVocab/Services/BookMetadataExtracting.swift
  - ios/BooksAndVocab/Services/CloudKitMirroringMonitor.swift
verified_against: 18f37badc
-->
# Bookshelf Feature Boundary

## 檔案清冊

### Container Layer（組裝 + 路由）

| 檔案 | 說明 |
|------|------|
| `BookshelfView.swift` | 主容器 `struct BookshelfView: View`，**純書籍書架** + 匯入流程；row 子 view 已抽出至 `Components/`。**podcast 已抽離為獨立頂層 section**（見 `podcast.md` `PodcastHomeView`）——本 view 不再持有 podcast query / overlay master pane / `selectedSeriesRemoteId` / `PodcastNavRoute` 路由 / podcast 同步觸發。**Navigation 契約（仍守）**：root 必須 `NavigationStack(path: $navigationPath)`（app 持有 `@State NavigationPath`），**不可** bare `NavigationStack { }`；**root content 恒定**：bookGrid / emptyState 由 `if books.isEmpty` 直接決定，**不可**用 `if/else` 替換 root content（root-content swap 在顯示過替換內容後會**永久破壞** value-based push，NAVDBG 坐實）。`navigationDestination(for: Book.self)` 接住書籍 → reader 的 value-based push（freeze-fix 契約 PR #366/#368/#370/#373）。書本 UI 來源仍為本地 SwiftData `@Query`、無遠端 catalog；書籍檔案/metadata 的恢復權威由 `BookManifest` sidecar + `BookLibraryReconciler` 補強（匯入、刪除、閱讀進度、reader notebook 綁定皆 write-through；正常啟動補 manifest-backed missing row / missing manifest / 同檔名去重，裸檔補 row 僅限明確 recovery opt-in，避免 CloudKit 匯入競態；含 legacy `Documents/EPUBs` / `.icloud` placeholder）。另有 `BookMetadataRepairService`（`BooksAndVocabApp` launch 一次性 background `.task`）：對本機可讀但 metadata 仍是 UUID fallback（title=UUID／空 author／nil cover）的 `.epub` row，從 EPUB 重抽 title/author/cover 做高信心修復（不用 `Untitled`/UUID/檔名 base 覆蓋、不蓋乾淨欄位），回寫 row 並經 manifest merge-on-write 保留 progress/locator/notebook——除錯「重啟後書名/封面變了」時看這裡。`.refreshable`（iOS/iPadOS，掛 emptyState + bookGrid）與 Mac toolbar `bookshelf.refreshButton` 觸發的是**帳號資料背景同步**（詞庫/複習/KG，**非**刷新書本清單），均經 `coordinator.sync` → `ExplicitSync` 統一回饋,且共用**資格 gate**（登出 / demo → 靜默 no-op，對齊自動同步;空書架正是登出用戶畫面,故必擋以免誤觸 `unauthorized` 而誤彈「登入已過期」）。Mac ⌘R 由 `MacMenuCommands` 全域擁有，toolbar 鈕**不**重綁。鏡射 `NotebookListView.swift` root-恒定模式。**emptyState 三分化（2026-06-11 書庫透明化）**：`emptyState` 內掛 `cloudRestoreStatus`（@ViewBuilder，讀 `CloudKitMirroringMonitor.shared.phase`）——`waitingFirstEvent` / `restoring` 顯示 `ProgressView` + 提示（`cloudCheckingHint` / `cloudRestoringHint`），`failed` 顯示 `exclamationmark.icloud` + 錯誤（`cloudSyncErrorHint`），`settled` / `localOnly` **不渲染**（0 列才講「尚無書籍」）。a11y id `bookshelf.emptyState.cloudStatus`（waiting/restoring 才渲染）。**root content 恒定契約與既有 CTA / `bookshelf.emptyState` a11y id 均未動**，狀態線只在既有 emptyState 內追加，文案走 `BookshelfCopy` + `L10n` |
| `BookshelfPreviews.swift` | `#Preview` 集中地（mock data scaffolds、各 row 型態樣本） |

### Observability Layer（CloudKit mirroring 透明化）

| 檔案 | 說明 |
|------|------|
| `Services/CloudKitMirroringMonitor.swift` | `@MainActor @Observable final class CloudKitMirroringMonitor`（單例 `.shared`）。訂閱 `NSPersistentCloudKitContainer.eventChangedNotification`（`object: nil`——SwiftData 內部持有 container，app 層拿不到實例，但 notification 全程序廣播），framework `Event` 無 public init 故先映射成可測的 `MirroringEventSnapshot` 再餵狀態機。`Phase`：`localOnly`（未接 CloudKit：UI-testing ephemeral / fallback / local-only retry，空書架直接走真空語意）/ `waitingFirstEvent`（CloudKit 啟用但尚無事件）/ `restoring`（import in-flight）/ `failed(String)`（最近收尾事件失敗）/ `settled`（**首次 import 成功收尾後恆 settled——0 本書才可講「真空」**）。`emptyMeansEmpty` 供 UI 判斷「本地 0 列」是否解讀成「真的沒資料」。`configure(cloudKitEnabled:)` 由 `AppBootstrap` 四條 container 路徑宣告（ephemeral/fallback/local-only retry = false），`start()` 冪等訂閱。mirroring 活動全量留 `AppLog` 痕（書庫絞殺案的取證線）。雖在 `Services/` 但屬 bookshelf 觀測面，emptyState 狀態線唯一消費者 |

### Coordinator Layer（導航協調）

| 檔案 | 說明 |
|------|------|
| `BookshelfCoordinator.swift` | `@MainActor protocol BookshelfCoordinating` + `@Observable @MainActor` 實作，含匯入、刪除、批次選擇、open reader / podcast 導航狀態、顯式同步 `sync(...)`（吃窄協定 `any BackgroundSyncing`，`isSyncing` 重入守衛，委派 `ExplicitSync.run`） |

### Components Layer（row UI）

| 檔案 | 說明 |
|------|------|
| `Components/BookCard.swift` | `struct BookCard: View` — 書架單列 row（cover / 標題 / 進度 / context menu）。進度條永遠保留占位（0% 也不壓縮卡片高度），進度值 clamp 到 [0,1]，0% 時 a11y 隱藏 |

### Token Layer（local metric）

| 檔案 | 說明 |
|------|------|
| `BookshelfMetrics.swift` | `enum AppBookshelfMetrics`，feature 內專用 spacing / cover 尺寸常數；跨 feature 共用值已升級至 `AppMetrics`（詳 `docs/snapshot/feature_metrics.md`） |

---

## 改動規則

- **新增書籍 row UI** → `Components/` 子目錄擴充（`BookCard` 或新增同層 row 元件）。播客 row 元件已隨 podcast section 遷出至 `Views/Podcast/`（見 `podcast.md`）
- **新增匯入流程** → `BookshelfView` body（建議走 `.sheet` + 既有 `appSheet` modifier）+ `BookshelfCoordinator` 加 navigation state
- **新增資料來源（書籍/播客以外的內容類型）** → 評估是否獨立成新 feature scope，避免 `BookshelfView` 繼續長
- **新增可復用 UI 元件** → 評估是否屬於 app shell 級（`AppShellComponents.swift`）；feature 專屬留在 `BookshelfView` 內
- **改顯式同步行為**（pull-to-refresh / toolbar 鈕 / ⌘R）→ 動 `Services/ExplicitSync.swift`（單一真相：資格 gate `isLoggedIn && !isDemoMode`〔登出/demo 靜默 no-op〕→ 成功彈 toast、失敗 warning + `lastBackgroundSyncError` read-then-clear）。eligibility 以 bool 傳入（不耦合 `AuthManaging`）。**勿**在 view/coordinator 重抄這段；自動同步（scenePhase / post-login）刻意維持成功靜默，見 `BooksAndVocabApp`
- **新增 metric token** → 跨 feature 用先升級到 `AppMetrics`；單 feature 用留 `AppBookshelfMetrics`（參考 `feature_metrics.md` 升降規則）

## State 邊界

- `BookshelfCoordinator`：書架導航與 sheet 狀態（匯入 / 詳情 / 批次刪除確認），由 `BookshelfView` 持有，不外洩
- 書籍資料來源於 SwiftData `@Query` + `@Environment(\.modelContext)`，不放 coordinator（播客 series 已遷至 `PodcastHomeView`）
- 匯入進度狀態走 `ImportProgressCallback`（app shell 層），不放 feature
- **帳號生命週期**：書庫綁 **Apple ID 非 app 帳號**（`Book` 在 `CloudStore` CloudKit，檔案在 per-Apple-ID iCloud/Documents）。登出 / account-switch 的 `clearUserData`（`BackgroundSyncActor`）**刻意不刪 Book 行**——清掉只會讓重登後書架空白（檔案仍在、冷啟動 `AppOrphanBookRecovery` reconciler 又補回），且本地 delete 可能反向傳播到 CloudKit。登入轉換（`BooksAndVocabApp` post-login）另呼叫一次 `AppOrphanBookRecovery.run` 作安全網，即時補建任何被清空 / 尚未 CloudKit-sync 的列（2026-06-10）

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
