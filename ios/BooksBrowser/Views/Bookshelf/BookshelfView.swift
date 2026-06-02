#if os(iOS)
//
//  BookshelfView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import TipKit
import UniformTypeIdentifiers
import Inject

/// 書架主頁 — 簡約留白設計
struct BookshelfView: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }
    @Environment(\.bookshelfImportService) private var bookshelfImportService
    @Environment(\.bookFileManager) private var bookFileManager
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Query(sort: \Book.dateLastRead, order: .reverse) private var books: [Book]
    @Query(filter: #Predicate<PodcastSeries> { !$0.isDeleted }, sort: \.sortOrder)
    private var podcastSeries: [PodcastSeries]

    /// 已追蹤的浮上來；同組內維持 server `sortOrder`。`@Query` macro 不支援多重
    /// SortDescriptor，這裡 in-memory 穩定排序（O(n log n)，series 數 << 100）。
    private var sortedPodcastSeries: [PodcastSeries] {
        podcastSeries.enumerated()
            .sorted { lhs, rhs in
                if lhs.element.isFollowed != rhs.element.isFollowed {
                    return lhs.element.isFollowed && !rhs.element.isFollowed
                }
                return lhs.offset < rhs.offset
            }
            .map(\.element)
    }
    @State private var coordinator = BookshelfCoordinator()
    @State private var showLoginSheet = false
    @State private var navigationPath = NavigationPath()

    /// regular (Mac/iPad) only: the podcast series whose episode-list + player
    /// render as a root-level master pane on this NavigationStack root (depth=0)
    /// instead of being pushed. compact keeps this `nil` and pushes via
    /// `PodcastNavRoute.series` instead (see `PodcastSeriesActivation`). Driving
    /// selection from a root-level `@State` is what makes the trailing
    /// `safeAreaInset` player immune to the depth=1 remount/pop (runtime-confirmed
    /// root cause; mirrors `NotebookListView.selectedNotebookId`).
    @State private var selectedSeriesRemoteId: String?

    private var columns: [GridItem] { [layoutMode.bookshelfGridItem] }

    private var coverHeight: CGFloat { layoutMode.bookshelfCoverHeight }

    var body: some View {
        NavigationStack(path: $navigationPath) {
            ZStack {
                appTheme.palette.pageBackground
                    .ignoresSafeArea()

                // root content 恒定：books grid / empty。這是 NavigationStack
                // 的直接 root subtree，其 structural identity **必須穩定**。
                // 過去用 `if/else` 在 bookGrid ↔ PodcastEpisodeListView 之間
                // 替換 root content，會在顯示過 podcast pane 後**永久破壞**該
                // NavigationStack 的 value-based push（NAVDBG 坐實：碰過 podcast
                // 後 `NavigationLink(value: book)` 不再驅動 navigationPath，
                // reader 於 path=0 短暫 onAppear 後立即 onDisappear，無法進入
                // 閱讀頁）。對齊 NotebookListView 的 root-恒定模式。
                if books.isEmpty && podcastSeries.isEmpty {
                    emptyState
                } else {
                    bookGrid
                }

                // regular (Mac/iPad): a selected podcast series renders its
                // episode-list + inline player as an **overlay pane** stacked
                // on top of the (always-present) book grid — NOT a push, and
                // NOT a root-content swap. Showing / hiding only mutates this
                // overlay layer, so the book grid's root identity is untouched
                // and reader push stays intact. The pane paints an opaque
                // background to fully cover the grid beneath. compact never
                // sets `selectedSeriesRemoteId` (it pushes instead), so this is
                // regular-only.
                if layoutMode.usesInlineDetail, let seriesId = selectedSeriesRemoteId {
                    PodcastEpisodeListView(seriesId: seriesId)
                        .id(seriesId)
                        .background(appTheme.palette.pageBackground.ignoresSafeArea())
                        .transition(.contentSwap)
                }

                if coordinator.isLoading {
                    loadingOverlay
                        .transition(.overlayFade)
                }
            }
            .safeAreaInset(edge: .top, spacing: 0) {
                if let message = coordinator.errorMessage, !coordinator.showError {
                    importErrorBanner(message: message)
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        .padding(.top, AppSpacing.s2)
                        .transition(.statusRowReveal)
                }
            }
            .animation(AppMotion.phaseChange, value: coordinator.showError)
            .animation(AppMotion.phaseChange, value: coordinator.errorMessage)
            .navigationTitle("書庫".localized)
            .largeNavigationBarTitle()
            .animatePhaseChange(books.isEmpty)
            .animateContentFade(coordinator.isLoading)
            // navigationDestination 統一掛在 NavigationStack root —
            // 避免 nested-modifier 競爭。Podcast 改 value-based push 後
            // 由此處接住路由（PR 追查 podcast tap freeze 的根因之一）。
            .navigationDestination(for: Book.self) { book in
                switch book.format {
                case .epub, .txt, .md:
                    ReaderView(book: book)
                case .pdf:
                    PDFReaderView(book: book)
                }
            }
            // Both `.series` and `.episode` cases are kept for the compact
            // (iPhone) push path. In regular (Mac/iPad) `.series` is never
            // pushed (it renders as a root-level master via
            // `selectedSeriesRemoteId`) and `.episode` is never pushed either
            // (the inline player handles it), but the destination must stay
            // registered — removing it would break the compact route.
            .navigationDestination(for: PodcastNavRoute.self) { route in
                switch route {
                case .series(let seriesRemoteId):
                    PodcastEpisodeListView(seriesId: seriesRemoteId)
                case .episode(let episodeRemoteId):
                    PodcastPlayerView(episodeId: episodeRemoteId)
                }
            }
            // regular → compact flip (iPad multitasking shrink / Catalyst window
            // resize): drop the root-level master selection so we don't strand a
            // two-pane layout or an orphaned player in compact. Mirrors
            // `PodcastDetailPresentation` dismiss + `NotebookListView` reconcile.
            .onChange(of: layoutMode) { _, newMode in
                if !newMode.usesInlineDetail {
                    selectedSeriesRemoteId = nil
                }
            }
            .toolbar {
                ToolbarItemGroup(placement: .topBarLeading) {
                    // regular: a root-level podcast master pane is showing →
                    // prepend an explicit back (no system back exists at depth=0).
                    // Settings stays reachable alongside it (its only entry point
                    // on Catalyst/iPad is this gear — must not be replaced).
                    if layoutMode.usesInlineDetail, selectedSeriesRemoteId != nil {
                        Button {
                            withAnimation(AppMotion.phaseChange) {
                                selectedSeriesRemoteId = nil
                            }
                        } label: {
                            AppToolbarGlyph(systemImage: "chevron.left")
                        }
                        .accessibilityLabel("返回".localized)
                        .accessibilityIdentifier("bookshelf.podcastBackButton")
                    }
                    Button(action: coordinator.presentSettings) {
                        AppToolbarGlyph(systemImage: "gearshape")
                    }
                    .accessibilityIdentifier("bookshelf.settingsButton")
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: coordinator.presentImporter) {
                        AppToolbarGlyph(systemImage: "plus")
                    }
                    .accessibilityIdentifier("bookshelf.importButton")
                }
            }
            .fileImporter(
                isPresented: $coordinator.isImporting,
                allowedContentTypes: [
                    UTType(filenameExtension: "epub") ?? .data,
                    .plainText,
                    UTType(filenameExtension: "md") ?? .data,
                    .pdf,
                ],
                allowsMultipleSelection: true
            ) { result in
                coordinator.handleFileImport(
                    result,
                    modelContext: modelContext,
                    importService: bookshelfImportService,
                    toastCoordinator: toastCoordinator
                )
            }
            .alert(
                coordinator.errorDiagnosis.map { L10n.format("匯入錯誤・%@", $0) } ?? "匯入錯誤".localized,
                isPresented: $coordinator.showError
            ) {
                Button("確定".localized, role: .cancel, action: coordinator.dismissError)
            } message: {
                Text(coordinator.errorMessage ?? "未知錯誤".localized)
            }
            .settingsSheet(isPresented: $coordinator.showSettings)
            .sheet(isPresented: $showLoginSheet) {
                LoginSheet()
            }
            .task {
                if authManager.isLoggedIn {
                    await PodcastSyncService(kgService: kgService).syncAll(context: modelContext)
                    await warmFollowedSeriesAudio()
                }
            }
        }
        // 匯入書籍 ⌘I(Mac menu)— 對應 toolbar importButton。
        .focusedSceneValue(\.importBook, ImportBookAction { coordinator.presentImporter() })
        .enableInjection()
    }

    // MARK: - 空狀態

    @Environment(\.openURL) private var openURL

    private var emptyState: some View {
        ScrollView {
            // Mochi 16/24 節奏 — 用 s4 取代既有 s5(20)，對齊 Mochi long-form 留白
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: "尚無書籍".localized,
                    systemImage: "book",
                    description: "匯入電子書開始閱讀（EPUB・TXT・MD・PDF）".localized,
                    guidanceText: "點擊上方匯入按鈕加入你的第一本書",
                    style: .bookshelf(appTheme)
                )

                TipView(EPUBGuideTip()) { action in
                    if action.id == EPUBGuideTip.guideActionID {
                        openURL(AppURLs.guide)
                    }
                }
                .padding(.horizontal)

                Button("匯入".localized) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appAction(.outline))
                .fixedSize(horizontal: false, vertical: true)

                if !authManager.isDemoMode && !authManager.isLoggedIn {
                    Button(action: { showLoginSheet = true }) {
                        Label("登入帳號".localized, systemImage: "person.crop.circle")
                    }
                    .buttonStyle(.appAction(.outline))

                    Button(action: {
                        authManager.enterDemoMode(modelContainer: modelContext.container)
                    }) {
                        HStack(spacing: 6) {
                            Image(systemName: "play.circle")
                            Text("體驗複習與圖譜".localized)
                        }
                        .font(AppFonts.caption(weight: .medium))
                        .foregroundStyle(appTheme.palette.accent)
                    }
                    .buttonStyle(.plain)
                }

                Spacer(minLength: 120)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        .refreshable {
            if authManager.isLoggedIn {
                await PodcastSyncService(kgService: kgService).syncAll(context: modelContext)
            }
        }
    }

    // MARK: - 書籍網格

    private var bookGrid: some View {
        ScrollView {
            VStack(spacing: 0) {
                // 書籍 section
                if !books.isEmpty {
                    LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
                        ForEach(books) { book in
                            NavigationLink(value: book) {
                                BookCard(book: book, coverHeight: coverHeight)
                            }
                            .buttonStyle(.bookshelfCard)
                            .accessibilityLabel("\(book.title), \(book.author)")
                            .accessibilityHint("點兩下開始閱讀".localized)
                            .transition(.bookshelfCard)
                            .contextMenu {
                                Button(role: .destructive) {
                                    coordinator.deleteBook(
                                        book,
                                        modelContext: modelContext,
                                        fileManager: bookFileManager,
                                        toastCoordinator: toastCoordinator
                                    )
                                } label: {
                                    Label("刪除".localized, systemImage: "trash")
                                }
                            }
                        }
                    }
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                    .padding(.top, AppSpacing.s2)
                }

                // Mochi 北極星二：書籍 ↔ 播客之間用 AppAirDivider 切群組（hairline + 32pt margin）
                if !books.isEmpty && !sortedPodcastSeries.isEmpty {
                    AppAirDivider()
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                }

                // 播客 section
                if !sortedPodcastSeries.isEmpty {
                    LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
                        ForEach(sortedPodcastSeries) { series in
                            seriesCard(series)
                                .buttonStyle(.bookshelfCard)
                                .accessibilityLabel("\(series.title), podcast")
                                .transition(.bookshelfCard)
                                .contextMenu {
                                    Button {
                                        toggleFollow(series)
                                    } label: {
                                        Label(
                                            (series.isFollowed ? "取消追蹤" : "追蹤").localized,
                                            systemImage: series.isFollowed ? "star.slash" : "star"
                                        )
                                    }
                                }
                        }
                    }
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                    .padding(.top, books.isEmpty ? AppSpacing.s2 : 0)
                }
            }
            .animateContentFade(books.count + podcastSeries.count)

            epubGuideHint
                .padding(.top, AppSpacing.s6)
                .padding(.bottom, AppSpacing.s7)
        }
        .refreshable {
            if authManager.isLoggedIn {
                await PodcastSyncService(kgService: kgService).syncAll(context: modelContext)
            }
        }
    }

    /// Series row activation branch:
    /// - regular (Mac/iPad): tap drives `@State selectedSeriesRemoteId` so the
    ///   episode-list renders as a root-level master pane (no push) — the
    ///   structural Catalyst remount fix. Selected card gets an accent stroke
    ///   overlay (mirrors `NotebookActivationSurface` selectInline).
    /// - compact (iPhone): bit-for-bit unchanged value-based push via
    ///   `navigationDestination(for: PodcastNavRoute.self)`.
    @ViewBuilder
    private func seriesCard(_ series: PodcastSeries) -> some View {
        switch PodcastSeriesActivation.activation(
            seriesRemoteId: series.remoteId,
            layoutMode: layoutMode
        ) {
        case .selectInline(let seriesRemoteId):
            Button {
                withAnimation(AppMotion.phaseChange) {
                    selectedSeriesRemoteId = seriesRemoteId
                }
            } label: {
                PodcastSeriesCard(series: series, coverHeight: coverHeight)
                    .overlay {
                        if selectedSeriesRemoteId == seriesRemoteId {
                            RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                                .stroke(appTheme.palette.accent, lineWidth: 1.5)
                        }
                    }
            }
        case .push(let route):
            NavigationLink(value: route) {
                PodcastSeriesCard(series: series, coverHeight: coverHeight)
            }
        }
    }

    // MARK: - EPUB 取得提示

    private var epubGuideHint: some View {
        Link(destination: AppURLs.guide) {
            Text("了解更多".localized)
                .font(AppFonts.caption2())
                .foregroundStyle(appTheme.palette.quaternaryText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, AppSpacing.s2)
        }
    }

    // MARK: - 匯入錯誤橫幅

    /// Alert 關閉後仍持續顯示的 inline error；提供「再試匯入」與「關閉」CTA。
    /// 對齊 `ui_state_matrix.md`：alert 是 transient，inline banner 是 persistent。
    @ViewBuilder
    private func importErrorBanner(message: String) -> some View {
        AppStateMessageCard(
            title: coordinator.errorDiagnosis.map { L10n.format("匯入錯誤・%@", $0) } ?? "匯入錯誤".localized,
            systemImage: "exclamationmark.triangle",
            description: message.localized
        ) {
            HStack(spacing: AppSpacing.s2) {
                Button("再試匯入".localized) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appCompactAction(.primary))

                Button("關閉".localized) {
                    coordinator.clearError()
                }
                .buttonStyle(.appCompactAction(.outline))
            }
        }
    }

    // MARK: - 載入覆蓋層

    private var loadingOverlay: some View {
        ZStack {
            appTheme.palette.scrim
                .ignoresSafeArea()

            VStack(spacing: AppSpacing.s4) {
                if let ratio = coordinator.loadingProgress {
                    ProgressView(value: ratio, total: 1.0)
                        .progressViewStyle(.linear)
                        .frame(width: AppBookshelfMetrics.loadingProgressWidth)
                } else {
                    ProgressView()
                        .scaleEffect(1.0)
                }
                Text(coordinator.loadingMessage)
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(AppBookshelfMetrics.loadingOverlayPadding)
            .compatibleGlass(in: .rect(cornerRadius: AppRadius.md))
        }
    }

    /// Predictive prefetch: warm AVFoundation's connection for the first
    /// episode of each followed series so tapping it from the shelf reaches
    /// `.ready` almost instantly. Mirrors Spotify/Audible behaviour where the
    /// app speculates on the most-likely next play. Bounded by the preloader's
    /// own LRU cap (5) — extra series silently skip rather than thrash.
    @MainActor
    private func warmFollowedSeriesAudio() async {
        let token: String
        do {
            token = try await kgService.currentAuthToken()
        } catch {
            return  // No auth → preload would 401; skip silently.
        }
        let headers = ["Authorization": "Bearer \(token)"]
        for series in podcastSeries where series.isFollowed {
            guard
                let first = (series.episodes ?? [])
                    .filter({ $0.audioAvailable })
                    .min(by: { $0.episodeNumber < $1.episodeNumber }),
                let urlStr = first.audioURL,
                let url = URL(string: urlStr)
            else { continue }
            PodcastAssetPreloader.shared.preload(url: url, headers: headers)
        }
    }

    /// Series 右鍵/長按選單的追蹤切換。樂觀翻轉 + 失敗回滾,與
    /// `PodcastEpisodeListView.toggleFollow` 共用 `PodcastFollowToggle` 契約。
    @MainActor
    private func toggleFollow(_ series: PodcastSeries) {
        var outcome: PodcastFollowToggle.Outcome = .saved
        withAnimation(AppMotion.phaseChange) {
            outcome = PodcastFollowToggle.perform(series: series) {
                modelContext.safeSave()
            }
        }
        if outcome == .rolledBack {
            toastCoordinator.error("追蹤狀態儲存失敗".localized)
        }
    }
}

// MARK: - 書架卡 Button Style（Mochi 北極星五：TapFeedback triplet，無 elevation 升降）

/// 書架封面卡 press feedback：scale + opacity + haptic，resting/press 都不換 elevation 階。
/// 取代既有 `.liftable`（liftable 會 z1↔z2 切換，違反 list 卡 resting z0 的鐵律）。
private struct BookshelfCardButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? AppMotion.TapFeedback.scaleDown : 1)
            .opacity(configuration.isPressed ? AppMotion.TapFeedback.opacityDip : 1)
            .animation(AppMotion.TapFeedback.animation, value: configuration.isPressed)
            .sensoryFeedback(.selection, trigger: configuration.isPressed) { _, newValue in newValue }
    }
}

extension ButtonStyle where Self == BookshelfCardButtonStyle {
    fileprivate static var bookshelfCard: BookshelfCardButtonStyle { BookshelfCardButtonStyle() }
}
#endif
