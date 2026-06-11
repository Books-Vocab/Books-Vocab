import SwiftUI
import Testing
@testable import BooksAndVocab

/// App-wide root-view stack budgets（推廣自 2026-06-11 Settings 真機 stack overflow 案，
/// 防線樣板見 `SettingsStackBudgetTests.swift`，修復 commit cdfabee2）。
///
/// iOS 真機 main thread stack 只有 1MB；Debug -Onone 下 SwiftUI 未特化泛型
/// （`VStack.init` / `ScrollView.init` 等）以 content **型別尺寸**做動態 stack
/// alloca，且中間值會被複製多次。把 section 樹 inline 在 `body` computed
/// property 會把單次求值撐爆（SettingsPresenter 實案 ~945KB → EXC_BAD_ACCESS）。
/// Simulator main thread 是 8MB，永遠重現不了 → 只能在型別尺寸層釘防線。
///
/// 防線：每個 root-level screen / presenter 的 opaque `Body` 型別尺寸。
/// 各 entry 的門檻按 2026-06-11 實測基線校準（基線寫在各 entry 註解），
/// 原則：現值留 ~30-50% 餘裕，但 re-inline 一個 section 量級的暴漲
/// （Settings 案 ≈ +8.6KB/section）必定超標。
///
/// 合法撞線時的處置：先確認新增的子樹是**獨立 View struct**（型別尺寸只算
/// 指標級 stored properties），而不是 inline 展開在 body / computed property
/// 裡（整棵子樹內嵌進型別）。是前者才准連同基線註解一起上調門檻；是後者
/// 請拆 struct（參考 cdfabee2 的 SettingsOtherSection 拆法）。
///
/// 已知不可量測而略過者：
/// - `ReaderViewPresenter<...>`：泛型，無法單獨取 `Body`；其唯一生產實例化
///   點是 `ReaderView.body`（ReaderView.swift:78），故 `ReaderView.Body`
///   的量測已涵蓋它整棵內嵌子樹。
@MainActor
struct RootViewStackBudgetTests {

    struct Entry: Sendable, CustomTestStringConvertible {
        let name: String
        let size: Int
        let budget: Int
        var testDescription: String { name }
    }

    /// 基線（2026-06-11，Debug/sim arm64）寫在每行註解：`基線 <bytes>B`。
    /// 門檻 ≈ 基線 ×1.5 取整 KB，且（門檻 − 基線）一律 < 8.6KB（單一 section
    /// re-inline 的量級）。全表最大戶 KnowledgeGraphPresenter 20,689B，
    /// 距 1MB 真機 stack 仍兩個數量級，無需重構。
    static let entries: [Entry] = [
        // ── App 殼 ──
        .init(name: "ContentView", size: MemoryLayout<ContentView.Body>.size, budget: 8 * 1024),               // 基線 5,161B
        .init(name: "AppStartupRecoveryView", size: MemoryLayout<AppStartupRecoveryView.Body>.size, budget: 4 * 1024), // 基線 2,729B
        .init(name: "WelcomeView", size: MemoryLayout<WelcomeView.Body>.size, budget: 3 * 1024),               // 基線 2,136B
        .init(name: "LoginSheet", size: MemoryLayout<LoginSheet.Body>.size, budget: 6 * 1024),                 // 基線 3,728B
        // ── Bookshelf ──
        .init(name: "BookshelfView", size: MemoryLayout<BookshelfView.Body>.size, budget: 10 * 1024),          // 基線 6,729B
        // ── Reader ──
        .init(name: "ReaderView", size: MemoryLayout<ReaderView.Body>.size, budget: 7 * 1024),                 // 基線 4,491B
        .init(name: "PDFReaderView", size: MemoryLayout<PDFReaderView.Body>.size, budget: 2 * 1024),           // 基線 1,570B
        .init(name: "ReaderSettingsPresenter", size: MemoryLayout<ReaderSettingsPresenter.Body>.size, budget: 24 * 1024), // 基線 16,449B
        .init(name: "TranslationPanel", size: MemoryLayout<TranslationPanel.Body>.size, budget: 3 * 1024),     // 基線 2,048B
        // ── Vocabulary / KG / Review ──
        .init(name: "KGVocabView", size: MemoryLayout<KGVocabView.Body>.size, budget: 8 * 1024),               // 基線 5,528B
        .init(name: "KGVocabPresenter", size: MemoryLayout<KGVocabPresenter.Body>.size, budget: 13 * 1024),    // 基線 9,041B
        .init(name: "KnowledgeGraphView", size: MemoryLayout<KnowledgeGraphView.Body>.size, budget: 3 * 1024), // 基線 1,898B
        .init(name: "KnowledgeGraphPresenter", size: MemoryLayout<KnowledgeGraphPresenter.Body>.size, budget: 28 * 1024), // 基線 20,689B（全表最大）
        .init(name: "TodayReviewView", size: MemoryLayout<TodayReviewView.Body>.size, budget: 6 * 1024),       // 基線 4,000B
        .init(name: "TodayReviewPresenter", size: MemoryLayout<TodayReviewPresenter.Body>.size, budget: 7 * 1024), // 基線 5,096B
        .init(name: "OverviewTab", size: MemoryLayout<OverviewTab.Body>.size, budget: 5 * 1024),               // 基線 3,497B
        .init(name: "StatsPresenter", size: MemoryLayout<StatsPresenter.Body>.size, budget: 25 * 1024),        // 基線 17,451B
        .init(name: "SyncPresenter", size: MemoryLayout<SyncPresenter.Body>.size, budget: 17 * 1024),          // 基線 11,944B
        .init(name: "WordDetailSheet", size: MemoryLayout<WordDetailSheet.Body>.size, budget: 5 * 1024),       // 基線 3,627B
        .init(name: "WordDetailPresenter", size: MemoryLayout<WordDetailPresenter.Body>.size, budget: 10 * 1024), // 基線 6,842B
        // ── Notebook ──
        .init(name: "NotebookListView", size: MemoryLayout<NotebookListView.Body>.size, budget: 3 * 1024),     // 基線 2,120B
        .init(name: "NotebookListContent", size: MemoryLayout<NotebookListContent.Body>.size, budget: 9 * 1024), // 基線 6,321B
        // ── Podcast ──
        .init(name: "PodcastHomeView", size: MemoryLayout<PodcastHomeView.Body>.size, budget: 3 * 1024),       // 基線 2,049B
        .init(name: "PodcastEpisodeListView", size: MemoryLayout<PodcastEpisodeListView.Body>.size, budget: 11 * 1024), // 基線 7,299B
        .init(name: "PodcastPlayerScene", size: MemoryLayout<PodcastPlayerScene.Body>.size, budget: 10 * 1024), // 基線 6,731B
        .init(name: "PodcastPlayerView", size: MemoryLayout<PodcastPlayerView.Body>.size, budget: 3 * 1024),   // 基線 2,216B
        // ── Settings / Paywall ──（SettingsPresenter 及其 section 已由
        //    SettingsStackBudgetTests 覆蓋，此處不重複）
        .init(name: "SettingsView", size: MemoryLayout<SettingsView.Body>.size, budget: 4 * 1024),             // 基線 3,001B
        .init(name: "SubscriptionPaywallSheet", size: MemoryLayout<SubscriptionPaywallSheet.Body>.size, budget: 19 * 1024), // 基線 12,809B
    ]

    @Test(arguments: entries)
    func rootViewBodyTypeStaysWithinStackBudget(_ entry: Entry) {
        #expect(
            entry.size < entry.budget,
            "\(entry.name).Body size=\(entry.size)B budget=\(entry.budget)B — 子樹不得 inline 回 body/computed property（拆獨立 View struct，見本檔頭註解）"
        )
    }
}
