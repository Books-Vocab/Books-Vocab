#if DEBUG && canImport(Playbook)
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

    struct ManifestEntry {
        let id: String
        let categories: [String]
        let register: (Playbook) -> Void
    }

    enum Manifest {
        static let entries: [ManifestEntry] = [
            .init(id: "design_tokens", categories: ["Design Tokens"], register: TokenSheetScenarios.register),
            .init(
                id: "reader",
                categories: [
                    "Reader · Translation",
                    "Reader · TOC",
                    "Reader · Settings",
                    "Reader · Quota",
                    "Reader · Selection Tile",
                    "Reader · Step Control",
                ],
                register: ReaderScenarios.register
            ),
            .init(
                id: "notebook_detail",
                categories: ["Notebook Detail · Row", "Notebook Detail · CTA Pill"],
                register: NotebookDetailScenarios.register
            ),
            .init(
                id: "notebooks",
                categories: ["Notebooks · Stack", "Notebooks · Card"],
                register: NotebooksScenarios.register
            ),
            .init(
                id: "notebook_list",
                categories: ["Notebooks · Stack"],
                register: NotebookListScenarios.register
            ),
            .init(
                id: "vocabulary",
                categories: [
                    "Vocabulary · Overview",
                    "Vocabulary · Knowledge Graph",
                    "Vocabulary · Linked Card",
                    "Vocabulary · Add Link",
                ],
                register: VocabScenarios.register
            ),
            .init(
                id: "word_detail",
                categories: ["Word Detail · Sheet", "Word Detail · Card Document"],
                register: WordDetailScenarios.register
            ),
            .init(
                id: "podcast_player",
                categories: ["Podcast · Subtitle", "Podcast · Episode Row"],
                register: PodcastPlayerScenarios.register
            ),
            .init(id: "notebook_edit", categories: ["Notebook Edit"], register: NotebookEditSheetScenarios.register),
            .init(
                id: "banners",
                categories: [
                    "Banners · Review",
                    "Banners · Demo",
                ],
                register: BannerScenarios.register
            ),
            .init(id: "sync", categories: ["Sync"], register: SyncScenarios.register),
            .init(id: "paywall", categories: ["Paywall"], register: PaywallScenarios.register),
            .init(id: "word_edit", categories: ["Word Edit"], register: WordEditScenarios.register),
            .init(id: "archived_vocab", categories: ["Archived Vocab"], register: ArchivedVocabScenarios.register),
            .init(id: "collocation_explain", categories: ["Collocation Explain"], register: CollocationExplainScenarios.register),
            .init(id: "kg_empty", categories: ["KG Empty State"], register: KGVocabEmptyStateScenarios.register),
            .init(id: "heatmap", categories: ["Vocab Heatmap"], register: VocabActivityHeatmapScenarios.register),
            .init(id: "calendar_grid", categories: ["Vocab Calendar"], register: VocabCalendarGridScenarios.register),
            .init(id: "forecast", categories: ["Vocab Forecast"], register: VocabForecastScenarios.register),
            .init(id: "progress_capsule", categories: ["Progress Capsule"], register: ProgressCapsuleScenarios.register),
            .init(
                id: "notebook_filter_chip",
                categories: [
                    "Notebook Filter Chip · Chip",
                    "Notebook Filter Chip · Picker",
                ],
                register: NotebookFilterChipScenarios.register
            ),
            .init(id: "notebook_review_action_bar", categories: ["Notebook Review Action Bar"], register: NotebookReviewActionBarScenarios.register),
            .init(id: "selection_toolbar", categories: ["Selection Toolbar"], register: SelectionToolbarScenarios.register),
            .init(id: "podcast_hero", categories: ["Podcast Hero"], register: PodcastSeriesHeroScenarios.register),
            .init(id: "podcast_shelf", categories: ["Podcast Shelf"], register: PodcastShelfScenarios.register),
            .init(id: "podcast_badge", categories: ["Podcast Badge"], register: PodcastBadgeScenarios.register),
            .init(id: "podcast_follow_toggle", categories: ["Podcast Follow Toggle"], register: PodcastFollowToggleScenarios.register),
            .init(id: "podcast_settings_popover", categories: ["Podcast Settings Popover"], register: PodcastSettingsPopoverScenarios.register),
            .init(id: "login_sheet", categories: ["Login Sheet"], register: LoginSheetScenarios.register),
            .init(id: "vocab_highlight_picker", categories: ["Vocab Highlight Picker"], register: VocabHighlightPickerScenarios.register),
            .init(id: "delete_account_sheet", categories: ["Delete Account Sheet"], register: DeleteAccountSheetScenarios.register),
            .init(id: "translation_lang_settings", categories: ["Translation Language Settings"], register: TranslationLanguageSettingsScenarios.register),
            .init(id: "bookcard", categories: ["Book Card"], register: BookCardScenarios.register),
            .init(
                id: "vocab_components",
                categories: [
                    "Vocab Components · Tone Chip",
                    "Vocab Components · Tier Label",
                    "Vocab Components · Empty State",
                    "Vocab Components · Review Progress Bar",
                    "Vocab Components · Review Gradient Bar",
                ],
                register: VocabComponentScenarios.register
            ),
            .init(
                id: "vocab_shell_components",
                categories: [
                    "Vocab Shell · Chrome Icon Button",
                    "Vocab Shell · Search Field",
                    "Vocab Shell · Toolbar Glyph",
                    "Vocab Shell · Accessory Icon Button",
                    "Vocab Shell · Inline Action Button",
                    "Vocab Shell · Metric Hero Card",
                    "Vocab Shell · Section Header",
                    "Vocab Shell · Slider Row",
                    "Vocab Shell · Sort Pill",
                ],
                register: VocabShellComponentsScenarios.register
            ),
            .init(
                id: "card_sections",
                categories: [
                    "Card Sections · Hero",
                    "Card Sections · Examples",
                    "Card Sections · Explanation",
                    "Card Sections · Forms",
                    "Card Sections · Source",
                    "Card Sections · Primitives",
                    "Card Sections · Document",
                ],
                register: CardSectionsScenarios.register
            ),
            .init(
                id: "word_detail_components",
                categories: [
                    "Word Detail Components · Sync Badge",
                    "Word Detail Components · Graph Link Row",
                ],
                register: WordDetailComponentScenarios.register
            ),
            .init(id: "notebook_cover", categories: ["Notebook Cover"], register: NotebookCoverScenarios.register),
            .init(id: "link_reason_sheet", categories: ["Link Reason Sheet"], register: LinkReasonSheetScenarios.register),
            .init(id: "reader_notebook_picker", categories: ["Reader Notebook Picker"], register: ReaderNotebookPickerScenarios.register),
            .init(id: "subscription_views", categories: ["Subscription Views · Gate Card"], register: SubscriptionViewsScenarios.register),
            .init(id: "podcast_continue_card", categories: ["Podcast Continue Card"], register: PodcastContinueCardScenarios.register),
            .init(
                id: "settings_components",
                categories: [
                    "Settings Components · Section Header",
                    "Settings Components · Section Footer",
                    "Settings Components · Status Badge",
                    "Settings Components · Status Value",
                    "Settings Components · Status Summary",
                    "Settings Components · Disclosure Value",
                    "Settings Components · Menu Value",
                    "Settings Components · Title Subtitle",
                    "Settings Components · Chevron Icon",
                ],
                register: SettingsComponentsScenarios.register
            ),
            .init(
                id: "settings_controls",
                categories: [
                    "Settings Controls · Stepper",
                    "Settings Controls · Modifiers",
                    "Settings Controls · Input Field",
                ],
                register: SettingsControlsScenarios.register
            ),
            .init(
                id: "settings_actions",
                categories: [
                    "Settings Actions · Buttons",
                    "Settings Actions · Subscription",
                    "Settings Actions · Plan Table",
                ],
                register: SettingsActionsScenarios.register
            ),
            .init(
                id: "settings_sections",
                categories: [
                    "Settings Sections · Review",
                    "Settings Sections · Preferences",
                ],
                register: SettingsSectionsScenarios.register
            ),
            .init(
                id: "account_section",
                categories: [
                    "Account Section · Section",
                    "Account Section · Auth Summary",
                    "Account Section · Pro Badge",
                ],
                register: SettingsAccountSectionScenarios.register
            ),
            .init(id: "today_review_presenter", categories: ["Today Review Presenter"], register: TodayReviewPresenterScenarios.register),
            .init(id: "review_calendar_presenter", categories: ["Review Calendar Presenter"], register: ReviewCalendarScenarios.register),
            .init(id: "pending_vocab_presenter", categories: ["Pending Vocab Presenter"], register: PendingVocabPresenterScenarios.register),
            .init(id: "word_detail_presenter", categories: ["Word Detail Presenter"], register: WordDetailPresenterScenarios.register),
            .init(id: "translation_vocab_presenter", categories: ["Translation Vocab Presenter"], register: TranslationVocabPresenterScenarios.register),
            .init(id: "reader_settings_presenter", categories: ["Reader Settings Presenter"], register: ReaderSettingsPresenterScenarios.register),
            .init(id: "app_startup_recovery", categories: ["Startup Recovery"], register: AppStartupRecoveryScenarios.register),
            .init(id: "settings", categories: ["Settings"], register: SettingsScenarios.register),
            .init(id: "today_review", categories: ["Today Review"], register: TodayReviewScenarios.register),
            .init(id: "bookshelf", categories: ["Bookshelf"], register: BookshelfScenarios.register),
            .init(id: "welcome", categories: ["Welcome"], register: WelcomeScenarios.register),
        ]

        static var categoryNames: Set<String> {
            Set(entries.flatMap(\.categories))
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
