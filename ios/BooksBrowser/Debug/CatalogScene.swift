#if DEBUG && canImport(Playbook)
import Foundation
import Playbook
import PlaybookUI
import SwiftUI

/// DEBUG-only Playbook catalog of KG SwiftUI surfaces.
///
/// 啟用方式:
/// 1. Xcode → Product → Scheme → Edit Scheme → Run → Arguments → Launch Arguments
///    加 `-catalog`
/// 2. ⌘R 跑 Debug build,app 啟動進 catalog 而非正常 UI
///
/// 截圖協作流程: simulator 跑著時用 `xcrun simctl io booted screenshot foo.png`,
/// 把 PNG 路徑貼給 Claude 即可協作視覺迭代。詳見 docs/sop/ios.md §Playbook Catalog。
///
/// ## Taxonomy as source of truth (2026-06)
/// 每個 Playbook category 由 `CatalogSurface` 宣告 `kind`(lane) / `feature` /
/// `screen`(真實全螢幕身分)。iOS source 是 surface 分類的唯一真相;離線 gallery
/// (`ops/catalog_review_*.py`) 消費 `catalog_index.json` 而非從像素/檔名反推。
/// 契約由 `CatalogCoverageTests` 強制:每個 `ScreenID` 恰好一個 `featureScreen`
/// surface(無重複、無缺漏);新增 category 必須宣告 kind。
struct CatalogScene: View {
    // Why: static let 確保 scenarios 只註冊一次 (Swift static init 是 thread-safe + lazy)。
    // 若改成 instance-level 每次 View init 都會重複註冊,Playbook 內部 storage
    // 會出現重複 entries。
    private static let playbook: Playbook = buildPlaybook()

    struct ScenarioDescriptor: Hashable {
        let category: String
        let title: String
    }

    struct Filter {
        let groups: Set<String>
        let scenarios: Set<ScenarioDescriptor>

        var isEmpty: Bool { groups.isEmpty && scenarios.isEmpty }

        func includes(category: String, title: String) -> Bool {
            if groups.contains(category) { return true }
            return scenarios.contains(.init(category: category, title: title))
        }
    }

    /// Lane of a catalog surface — declared at source, consumed by the gallery.
    enum SurfaceKind: String {
        case featureScreen   // a real, full app screen (has a ScreenID)
        case overlay         // sheet / popover / panel presented over a screen
        case buildingBlock   // composable component (card / row / bar / chip)
        case engineering     // dev harness / presenter-only / token sheet
    }

    /// Product feature a surface belongs to.
    enum Feature: String {
        case reader, vocabulary, notebook, bookshelf, podcast
        case review, settings, monetization, onboarding, misc
    }

    /// Identity of a real, full app screen. Drives the catalog coverage + no-dup
    /// contract: each case maps to exactly one `featureScreen` surface.
    /// `CaseIterable` so `CatalogCoverageTests` coverage assertion is exhaustive.
    enum ScreenID: String, CaseIterable {
        // covered (each has a featureScreen surface)
        case reader, pdfReader, bookshelf, settings
        case todayReview, todayReviewPhase, knowledgeGraph
        case stats, sync, vocabularyList, podcastHome, welcome
        // pending coverage — authored in P3 (see Manifest.pendingCoverage)
        case podcastPlayer, podcastEpisodeList, notebookList
        case settingsAccountDetail, translationLanguageSettings, appStartupRecovery
        // NOTE: KGVocabView is never presented standalone — VocabularyListView's
        // logged-in path renders it — so it is covered by the .vocabularyList
        // screen surface + the "KG Vocab Presenter" component, not its own screen.
    }

    /// Declared taxonomy for one Playbook category. `screen` is non-nil iff
    /// `kind == .featureScreen`.
    struct CatalogSurface {
        let category: String
        let kind: SurfaceKind
        let feature: Feature
        let screen: ScreenID?
    }

    struct ManifestEntry {
        let id: String
        let surfaces: [CatalogSurface]
        let register: (Playbook) -> Void

        var categories: [String] { surfaces.map(\.category) }
    }

    enum Manifest {
        // MARK: - Surface factories (concise annotation)

        private static func screen(_ c: String, _ f: Feature, _ s: ScreenID) -> CatalogSurface {
            .init(category: c, kind: .featureScreen, feature: f, screen: s)
        }
        private static func overlay(_ c: String, _ f: Feature) -> CatalogSurface {
            .init(category: c, kind: .overlay, feature: f, screen: nil)
        }
        private static func block(_ c: String, _ f: Feature) -> CatalogSurface {
            .init(category: c, kind: .buildingBlock, feature: f, screen: nil)
        }
        private static func eng(_ c: String, _ f: Feature) -> CatalogSurface {
            .init(category: c, kind: .engineering, feature: f, screen: nil)
        }
        /// Map a dynamic category list (e.g. macCatalyst-gated) to building blocks.
        private static func blocks(_ categories: [String], _ f: Feature) -> [CatalogSurface] {
            categories.map { block($0, f) }
        }

        /// Screens we intend to cover but haven't authored a surface for yet.
        /// `CatalogCoverageTests` allows exactly these ScreenIDs to be missing.
        /// Now empty: every ScreenID has a featureScreen surface (P3 complete).
        static let pendingCoverage: Set<ScreenID> = []

        static let entries: [ManifestEntry] = [
            .init(
                id: "reader",
                surfaces: [
                    overlay("Reader · Translation", .reader),
                    overlay("Reader · TOC", .reader),
                    overlay("Reader · Settings", .reader),
                ],
                register: ReaderScenarios.register
            ),
            .init(
                id: "notebooks",
                surfaces: [block("Notebooks · Card", .notebook)],
                register: NotebooksScenarios.register
            ),
            .init(
                id: "notebook_list",
                surfaces: [block("Notebooks · Stack", .notebook)],
                register: NotebookListScenarios.register
            ),
            .init(
                id: "vocabulary",
                surfaces: [
                    block("Vocabulary · Overview", .vocabulary),
                    block("Vocabulary · Knowledge Graph", .vocabulary),
                    block("Vocabulary · Linked Card", .vocabulary),
                    block("Vocabulary · Add Link", .vocabulary),
                ],
                register: VocabScenarios.register
            ),
            .init(
                id: "word_detail",
                surfaces: [overlay("Word Detail · Sheet", .vocabulary), block("Word Detail · Card Document", .vocabulary)],
                register: WordDetailScenarios.register
            ),
            .init(
                id: "podcast_player",
                surfaces: [eng("Podcast · Episode Row", .podcast)],
                register: PodcastPlayerScenarios.register
            ),
            .init(id: "notebook_edit", surfaces: [block("Notebook Edit", .notebook)], register: NotebookEditSheetScenarios.register),
            .init(
                id: "banners",
                surfaces: [block("Banners · Review", .misc), block("Banners · Demo", .misc)],
                register: BannerScenarios.register
            ),
            .init(id: "sync", surfaces: [block("Sync", .review)], register: SyncScenarios.register),
            .init(id: "paywall", surfaces: [overlay("Paywall", .monetization)], register: PaywallScenarios.register),
            .init(id: "word_edit", surfaces: [block("Word Edit", .vocabulary)], register: WordEditScenarios.register),
            .init(id: "archived_vocab", surfaces: [block("Archived Vocab", .vocabulary)], register: ArchivedVocabScenarios.register),
            .init(id: "collocation_explain", surfaces: [block("Collocation Explain", .vocabulary)], register: CollocationExplainScenarios.register),
            .init(id: "kg_empty", surfaces: [block("KG Empty State", .vocabulary)], register: KGVocabEmptyStateScenarios.register),
            .init(id: "heatmap", surfaces: [block("Vocab Heatmap", .review)], register: VocabActivityHeatmapScenarios.register),
            .init(id: "calendar_grid", surfaces: [block("Vocab Calendar", .review)], register: VocabCalendarGridScenarios.register),
            .init(id: "forecast", surfaces: [block("Vocab Forecast", .review)], register: VocabForecastScenarios.register),
            .init(
                id: "notebook_filter_chip",
                surfaces: [overlay("Notebook Filter Chip · Picker", .notebook)],
                register: NotebookFilterChipScenarios.register
            ),
            .init(id: "notebook_review_action_bar", surfaces: [eng("Notebook Review Action Bar", .notebook)], register: NotebookReviewActionBarScenarios.register),
            .init(id: "selection_toolbar", surfaces: [eng("Selection Toolbar", .reader)], register: SelectionToolbarScenarios.register),
            .init(id: "podcast_hero", surfaces: [block("Podcast Hero", .podcast)], register: PodcastSeriesHeroScenarios.register),
            .init(id: "podcast_shelf", surfaces: [block("Podcast Shelf", .podcast)], register: PodcastShelfScenarios.register),
            .init(id: "podcast_settings_popover", surfaces: [overlay("Podcast Settings Popover", .podcast)], register: PodcastSettingsPopoverScenarios.register),
            .init(id: "login_sheet", surfaces: [overlay("Login Sheet", .monetization)], register: LoginSheetScenarios.register),
            .init(id: "vocab_highlight_picker", surfaces: [overlay("Vocab Highlight Picker", .vocabulary)], register: VocabHighlightPickerScenarios.register),
            .init(id: "delete_account_sheet", surfaces: [overlay("Delete Account Sheet", .settings)], register: DeleteAccountSheetScenarios.register),
            .init(id: "translation_lang_settings", surfaces: [screen("Translation Language Settings", .settings, .translationLanguageSettings)], register: TranslationLanguageSettingsScenarios.register),
            .init(id: "bookcard", surfaces: [block("Book Card", .bookshelf)], register: BookCardScenarios.register),
            .init(
                id: "vocab_components",
                surfaces: [
                    block("Vocab Components · Tone Chip", .vocabulary),
                    block("Vocab Components · Empty State", .vocabulary),
                    block("Vocab Components · Review Progress Bar", .vocabulary),
                ],
                register: VocabComponentScenarios.register
            ),
            .init(
                id: "vocab_shell_components",
                surfaces: [
                    block("Vocab Shell · Metric Hero Card", .vocabulary),
                    block("Vocab Shell · Sort Pill", .vocabulary),
                ],
                register: VocabShellComponentsScenarios.register
            ),
            .init(id: "notebook_cover", surfaces: [block("Notebook Cover", .notebook)], register: NotebookCoverScenarios.register),
            .init(id: "link_reason_sheet", surfaces: [overlay("Link Reason Sheet", .vocabulary)], register: LinkReasonSheetScenarios.register),
            .init(id: "reader_notebook_picker", surfaces: [overlay("Reader Notebook Picker", .reader)], register: ReaderNotebookPickerScenarios.register),
            .init(id: "subscription_views", surfaces: [block("Subscription Views · Gate Card", .monetization)], register: SubscriptionViewsScenarios.register),
            .init(id: "podcast_continue_card", surfaces: [block("Podcast Continue Card", .podcast)], register: PodcastContinueCardScenarios.register),
            .init(
                id: "podcast_shelf_cards",
                surfaces: [block("Podcast Series Card", .podcast), block("Podcast Continue Rail Card", .podcast)],
                register: PodcastShelfCardsScenarios.register
            ),
            .init(
                id: "settings_actions",
                surfaces: [
                    eng("Settings Actions · Plan Table", .settings),
                ],
                register: SettingsActionsScenarios.register
            ),
            .init(
                id: "settings_sections",
                surfaces: [
                    eng("Settings Sections · Review", .settings),
                    eng("Settings Sections · Preferences", .settings),
                ],
                register: SettingsSectionsScenarios.register
            ),
            .init(
                id: "account_section",
                surfaces: [
                    eng("Account Section · Section", .settings),
                    eng("Account Section · Auth Summary", .settings),
                ],
                register: SettingsAccountSectionScenarios.register
            ),
            .init(id: "review_calendar_presenter", surfaces: [eng("Review Calendar Presenter", .review)], register: ReviewCalendarScenarios.register),
            .init(id: "pending_vocab_presenter", surfaces: [eng("Pending Vocab Presenter", .review)], register: PendingVocabPresenterScenarios.register),
            .init(id: "app_startup_recovery", surfaces: [screen("Startup Recovery", .misc, .appStartupRecovery)], register: AppStartupRecoveryScenarios.register),
            .init(id: "vocabulary_list_view", surfaces: [screen("Vocabulary List View", .vocabulary, .vocabularyList)], register: VocabularyListViewScenarios.register),
            .init(id: "stats_view", surfaces: [screen("Stats View", .review, .stats)], register: StatsViewScenarios.register),
            .init(id: "podcast_home_view", surfaces: [screen("Podcast Home View", .podcast, .podcastHome)], register: PodcastHomeViewScenarios.register),
            .init(id: "bookshelf_view", surfaces: [screen("Bookshelf View", .bookshelf, .bookshelf)], register: BookshelfViewScenarios.register),
            .init(id: "knowledge_graph_view", surfaces: [screen("Knowledge Graph View", .vocabulary, .knowledgeGraph)], register: KnowledgeGraphViewScenarios.register),
            .init(id: "pdf_reader_view", surfaces: [screen("PDF Reader View", .reader, .pdfReader)], register: PDFReaderViewScenarios.register),
            .init(id: "sync_view_surface", surfaces: [screen("Sync View", .review, .sync)], register: SyncViewScenarios.register),
            .init(id: "notebook_list_view", surfaces: [screen("Notebook List View", .notebook, .notebookList)], register: NotebookListViewScenarios.register),
            .init(id: "podcast_episode_list_view", surfaces: [screen("Podcast Episode List View", .podcast, .podcastEpisodeList)], register: PodcastEpisodeListViewScenarios.register),
            .init(id: "podcast_player_view", surfaces: [screen("Podcast Player View", .podcast, .podcastPlayer)], register: PodcastPlayerViewScenarios.register),
            .init(id: "editorial_cover", surfaces: [block("Notebook Cover · Editorial", .notebook)], register: NotebookCardEditorialCoverScenarios.register),
            .init(id: "kg_vocab_row", surfaces: [eng("KG Vocab Row", .vocabulary)], register: KGVocabRowScenarios.register),
            .init(id: "podcast_sentence_cells", surfaces: [eng("Podcast · Transcript Column", .podcast), eng("Podcast · Bubble Cell", .podcast)], register: PodcastSentenceCellsScenarios.register),
            // `surfaces` 透過 enum 計算屬性同步 macCatalyst gating:非 Catalyst 時
            // register 為 no-op,manifest 亦回報空 categories,使覆蓋測試對稱。
            .init(id: "today_review_shortcut_chips", surfaces: blocks(TodayReviewShortcutScenarios.manifestCategories, .review), register: TodayReviewShortcutScenarios.register),
            .init(
                id: "review_fold_surface",
                surfaces: [
                    eng("Review Fold · Chevron Pill", .review),
                    eng("Review Fold · Paper Fold", .review),
                    eng("Review Fold · Segment", .review),
                ],
                register: ReviewFoldScenarios.register
            ),
            .init(id: "settings_account_detail", surfaces: [screen("Settings Account Detail", .settings, .settingsAccountDetail)], register: SettingsAccountDetailScenarios.register),
            .init(id: "settings_subscription_section", surfaces: [block("Settings Subscription Section", .settings)], register: SettingsSubscriptionSectionScenarios.register),
            .init(id: "today_review_phase_view", surfaces: [screen("Today Review Phase", .review, .todayReviewPhase)], register: TodayReviewPhaseScenarios.register),
            .init(id: "reader_view", surfaces: [screen("Reader View · Chrome", .reader, .reader)], register: ReaderChromeScenarios.register),
            .init(id: "settings", surfaces: [screen("Settings", .settings, .settings)], register: SettingsScenarios.register),
            .init(id: "today_review", surfaces: [screen("Today Review", .review, .todayReview)], register: TodayReviewScenarios.register),
            .init(id: "bookshelf", surfaces: [block("Bookshelf", .bookshelf)], register: BookshelfScenarios.register),
            .init(id: "welcome", surfaces: [screen("Welcome", .onboarding, .welcome)], register: WelcomeScenarios.register),
        ]

        static var categoryNames: Set<String> {
            Set(entries.flatMap(\.categories))
        }

        /// All declared surfaces, flattened.
        static var surfaces: [CatalogSurface] {
            entries.flatMap(\.surfaces)
        }

        /// Surfaces declared as real, full app screens.
        static var featureScreenSurfaces: [CatalogSurface] {
            surfaces.filter { $0.kind == .featureScreen }
        }

        /// Ground-truth taxonomy index for offline consumers (the Python catalog
        /// gallery, `ops/catalog_review_*.py`). Keyed by category (the on-disk
        /// snapshot folder name); each entry carries the source-declared
        /// kind/feature/screen. Emitted next to the PNGs by `CatalogSnapshotTests`
        /// as `catalog_index.json` so the gallery consumes truth instead of
        /// reverse-engineering it from transparent-margin pixels + title regex.
        static func indexJSONData() throws -> Data {
            var surfaceMap: [String: [String: String]] = [:]
            for surface in surfaces {
                var entry: [String: String] = [
                    "kind": surface.kind.rawValue,
                    "feature": surface.feature.rawValue,
                ]
                if let screen = surface.screen {
                    entry["screen"] = screen.rawValue
                }
                surfaceMap[surface.category] = entry
            }
            let root: [String: Any] = ["version": 1, "surfaces": surfaceMap]
            return try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys])
        }
    }

    /// Build a fresh `Playbook` with all KG surface scenarios registered.
    /// Exposed (internal-access) so `BooksBrowserTests` can drive PlaybookSnapshot
    /// against the same surface set as the in-app catalog.
    static func buildPlaybook(filter: Filter? = nil) -> Playbook {
        let pb = Playbook()
        for entry in Manifest.entries {
            entry.register(pb)
        }
        return filteredPlaybook(from: pb, using: filter)
    }

    static func filter(groups: [String], scenarios: [String]) -> Filter {
        let normalizedGroups = Set(groups.map(normalizeCategoryOrScenarioName))
        let normalizedScenarios = Set(scenarios.compactMap { descriptor(from: $0) })
        return .init(groups: normalizedGroups, scenarios: normalizedScenarios)
    }

    private static func filteredPlaybook(from playbook: Playbook, using filter: Filter?) -> Playbook {
        guard let filter, !filter.isEmpty else { return playbook }

        let scoped = Playbook()
        for store in playbook.stores {
            let category = store.category.rawValue
            let matchedScenarios = store.scenarios.filter { filter.includes(category: category, title: $0.title.rawValue) }
            guard !matchedScenarios.isEmpty else { continue }
            let targetStore = scoped.scenarios(of: store.category)
            for scenario in matchedScenarios {
                targetStore.add(scenario)
            }
        }
        return scoped
    }

    private static func descriptor(from rawValue: String) -> ScenarioDescriptor? {
        let normalized = normalizeCategoryOrScenarioName(rawValue)
        let segments = normalized.split(separator: "/", maxSplits: 1).map(String.init)
        guard segments.count == 2 else { return nil }
        return .init(category: segments[0], title: segments[1])
    }

    private static func normalizeCategoryOrScenarioName(_ rawValue: String) -> String {
        rawValue
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
    }

    var body: some View {
        PlaybookCatalog(title: "KG Catalog", playbook: Self.playbook)
    }
}

#Preview {
    CatalogScene()
}
#endif
