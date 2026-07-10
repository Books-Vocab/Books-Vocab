//
//  ExploreView.swift
//  Books & Vocab
//
//  Explore（共享牌組庫）頂層 section —— 唯讀官方牌組瀏覽（Phase 1b-iii，無複製鈕）。
//
//  鏡射 PodcastHomeView 的殼：自有 NavigationStack(path:)、guest-tolerant 目錄同步
//  `.task`、四態（loading/error/empty/content）。牌組來自獨立 `SharedDeck @Model` 的
//  `@Query`（型別層與私人 Notebook 隔離）。搜尋 + 分類/語言/官方/排序篩選在本機套用
//  於已同步目錄（Phase 1：官方目錄量小、離線友善；server-side q/cursor 分頁為後續）。
//

import SwiftUI
import SwiftData

/// 唯讀目錄的展示相位。內容為主（有牌組即 content），其餘退回 loading/error/空。
enum ExplorePhase: Equatable {
    case loading
    case error
    /// 真空 —— 目錄尚無牌組（非篩選造成）。
    case empty
    /// 有目錄但當前 search/filter 無結果。
    case noResults
    case content

    static func resolve(
        isSyncing: Bool, syncFailed: Bool,
        totalDeckCount: Int, filteredCount: Int,
        isFilteringOrSearching: Bool
    ) -> ExplorePhase {
        if filteredCount > 0 { return .content }
        if totalDeckCount > 0 && isFilteringOrSearching { return .noResults }
        if isSyncing { return .loading }
        if syncFailed { return .error }
        return .empty
    }
}

/// Explore 導航路由（value-based push；freeze 契約鏡射 PodcastNavRoute）。
enum ExploreNavRoute: Hashable {
    case deck(deckId: String)
}

struct ExploreView: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.catalogTaskPolicy) private var catalogTaskPolicy

    @Query(filter: #Predicate<SharedDeck> { !$0.isSoftDeleted }, sort: \.sortOrder)
    private var decks: [SharedDeck]

    @State private var navigationPath = NavigationPath()
    @State private var isSyncing = false
    @State private var syncFailed = false
    @State private var filter = ExploreFilter()

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }
    private var columns: [GridItem] { [layoutMode.bookshelfGridItem] }
    private var coverHeight: CGFloat { layoutMode.bookshelfCoverHeight }

    private var filteredDecks: [SharedDeck] {
        let byId = Dictionary(decks.map { ($0.remoteId, $0) }, uniquingKeysWith: { first, _ in first })
        return filter.apply(to: decks.map(\.projection)).compactMap { byId[$0.remoteId] }
    }

    private var availableCategories: [String] {
        Array(Set(decks.compactMap(\.category))).sorted()
    }

    private var availableLanguagePairs: [String] {
        Array(Set(decks.compactMap(\.languagePair))).sorted()
    }

    private var phase: ExplorePhase {
        ExplorePhase.resolve(
            isSyncing: isSyncing, syncFailed: syncFailed,
            totalDeckCount: decks.count, filteredCount: filteredDecks.count,
            isFilteringOrSearching: filter.isSearching || filter.hasActiveFilters
        )
    }

    var body: some View {
        NavigationStack(path: $navigationPath) {
            ZStack {
                appTheme.palette.pageBackground.ignoresSafeArea()
                switch phase {
                case .loading: loadingState
                case .error: errorState
                case .empty: emptyState
                case .noResults: noResultsState
                case .content: content
                }
            }
            .navigationTitle(L10n.string("app.section.explore"))
            .largeNavigationBarTitle()
            .searchable(
                text: $filter.searchText,
                prompt: L10n.string("explore.search.prompt")
            )
            #if targetEnvironment(macCatalyst)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(action: { Task { await refreshCatalog() } }) {
                        AppToolbarGlyph(systemImage: "arrow.clockwise")
                    }
                    .accessibilityLabel(L10n.string("explore.refresh"))
                    .accessibilityIdentifier("explore.refreshButton")
                    .help(L10n.string("explore.refresh"))
                }
            }
            #endif
            .navigationDestination(for: ExploreNavRoute.self) { route in
                switch route {
                case .deck(let deckId):
                    SharedDeckDetailView(deckId: deckId)
                }
            }
            .task(id: authManager.isLoggedIn) {
                guard catalogTaskPolicy.runsTasks else { return }
                await syncCatalog(showToastOnFailure: false)
            }
        }
        .enableInjection()
    }

    // MARK: - Content

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppSpacing.s3) {
                filterBar
                deckGrid
            }
            .padding(.top, AppSpacing.s2)
            .animateContentFade(filteredDecks.count)
        }
        #if !targetEnvironment(macCatalyst)
        .refreshable { await refreshCatalog() }
        #endif
    }

    private var deckGrid: some View {
        LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
            ForEach(filteredDecks) { deck in
                NavigationLink(value: ExploreNavRoute.deck(deckId: deck.remoteId)) {
                    ExploreDeckCard(deck: deck, coverHeight: coverHeight)
                }
                .buttonStyle(.bookshelfCard)
                .accessibilityIdentifier("explore.deck.\(deck.remoteId)")
                .transition(.bookshelfCard)
            }
        }
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
    }

    // MARK: - Filter bar

    @ViewBuilder
    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.s2) {
                sortMenu
                if !availableCategories.isEmpty {
                    ForEach(availableCategories, id: \.self) { category in
                        ExploreFilterChip(
                            title: SharedDeckFormat.categoryDisplayName(category),
                            isSelected: filter.category == category
                        ) {
                            filter.category = (filter.category == category) ? nil : category
                        }
                    }
                }
                if !availableLanguagePairs.isEmpty {
                    ForEach(availableLanguagePairs, id: \.self) { pair in
                        ExploreFilterChip(
                            title: pair,   // 語言對代碼（如 en-zh）；render-safe，非 i18n key
                            isSelected: filter.languagePair == pair
                        ) {
                            filter.languagePair = (filter.languagePair == pair) ? nil : pair
                        }
                    }
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        .accessibilityIdentifier("explore.filterBar")
    }

    private var sortMenu: some View {
        Menu {
            Picker(L10n.string("explore.sort.label"), selection: $filter.sort) {
                ForEach(ExploreSort.allCases) { option in
                    Text(L10n.string(option.titleKey)).tag(option)
                }
            }
        } label: {
            ExploreFilterChipLabel(
                title: L10n.string(filter.sort.titleKey),
                systemImage: "arrow.up.arrow.down",
                isSelected: false
            )
        }
        .accessibilityLabel(L10n.string("explore.sort.label"))
        .accessibilityIdentifier("explore.sortMenu")
    }

    // MARK: - States

    private var emptyState: some View {
        stateScroll {
            AppEmptyStateContent(
                title: L10n.string("explore.empty.title"),
                systemImage: "sparkles",
                description: L10n.string("explore.empty.description"),
                guidanceText: L10n.string("explore.empty.guidance"),
                style: .bookshelf(appTheme)
            )
        }
    }

    private var noResultsState: some View {
        stateScroll {
            AppEmptyStateContent(
                title: L10n.string("explore.noResults.title"),
                systemImage: "magnifyingglass",
                description: L10n.string("explore.noResults.description"),
                action: AppEmptyStateAction(
                    title: L10n.string("explore.noResults.clear"),
                    systemImage: "xmark.circle",
                    handler: { filter = ExploreFilter() }
                ),
                style: .bookshelf(appTheme)
            )
        }
    }

    private var errorState: some View {
        stateScroll {
            AppEmptyStateContent(
                title: L10n.string("explore.error.title"),
                systemImage: "exclamationmark.triangle",
                description: L10n.string("explore.error.description"),
                guidanceText: L10n.string("explore.error.guidance"),
                action: AppEmptyStateAction(
                    title: L10n.string("explore.retry"),
                    systemImage: "arrow.clockwise",
                    handler: { Task { await refreshCatalog() } }
                ),
                style: .bookshelf(appTheme)
            )
        }
    }

    private var loadingState: some View {
        VStack {
            Spacer()
            AppStateMessageCard(
                title: L10n.string("explore.loading.title"),
                systemImage: "arrow.triangle.2.circlepath",
                description: L10n.string("explore.loading.description")
            ) {
                ProgressView().controlSize(.small)
            }
            .frame(maxWidth: 420)
            Spacer()
        }
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
    }

    @ViewBuilder
    private func stateScroll<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        ScrollView {
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)
                content()
                Spacer(minLength: 120)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        #if !targetEnvironment(macCatalyst)
        .refreshable { await refreshCatalog() }
        #endif
    }

    // MARK: - Sync

    @MainActor
    private func syncCatalog(showToastOnFailure: Bool) async {
        isSyncing = true
        defer { isSyncing = false }
        let outcome = await SharedDeckCatalogService(kgService: kgService).syncAll(context: modelContext)
        syncFailed = outcome == .listFetchFailed
        if syncFailed && showToastOnFailure {
            toastCoordinator.warning(L10n.string("explore.error.title"))
        }
    }

    @MainActor
    private func refreshCatalog() async {
        await syncCatalog(showToastOnFailure: true)
    }
}
