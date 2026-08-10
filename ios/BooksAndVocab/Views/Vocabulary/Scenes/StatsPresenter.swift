//
//  StatsPresenter.swift
//  Books & Vocab
//
//  學習統計儀表板場景。
//

import SwiftUI
import SwiftData

enum StatsScenePhase: Equatable {
    case loading
    case empty
    case content

    static func resolve(hasSummary: Bool, isEmpty: Bool) -> Self {
        guard hasSummary else { return .loading }
        return isEmpty ? .empty : .content
    }
}

struct StatsPresenter: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

    let filter: NotebookFilter

    @Query(filter: #Predicate<VocabularyEntry> {
        $0.syncStatus == 1 &&
        $0.actionType != "delete"
    })
    private var syncedEntries: [VocabularyEntry]

    /// init 覆寫為只載入近 6 個月的紀錄（統計用途不需全量）
    @Query var reviewRecords: [ReviewRecord]

    @AppStorage("stats_forecast_days") private var forecastDays = 14

    @State private var summary: StatsPresentation.Summary?
    @State private var showCalendar = false
    @State private var contentReady = false
    @State private var graphLinks: [KGGraphLink]?
    @State private var graphHolder = GraphThumbnailHolder()
    @State private var graphLoadError: Bool = false
    @State private var retryToken: Int = 0

    private static let sixMonthsAgo = Calendar.current.date(byAdding: .month, value: -6, to: Date()) ?? Date()

    /// Whether the graph `.task` may fetch links (demo/remote). Always true in
    /// production; the DEBUG catalog init disables it and injects links
    /// directly (mirrors `KnowledgeGraphView`'s DEBUG entry point).
    private let shouldLoadGraphData: Bool

    init(
        filter: NotebookFilter = NotebookFilter(),
        initialSummary: StatsPresentation.Summary? = nil
    ) {
        self.filter = filter
        self.shouldLoadGraphData = true
        _summary = State(initialValue: initialSummary)
        _contentReady = State(initialValue: initialSummary != nil)
        let cutoff = Self.sixMonthsAgo
        _reviewRecords = Query(
            filter: #Predicate<ReviewRecord> { $0.reviewedAt > cutoff },
            sort: \ReviewRecord.reviewedAt,
            order: .reverse
        )
    }

#if DEBUG
    /// Catalog/preview-only entry: injects the 關聯圖 card's links directly
    /// (UI World manifest-derived) and disables the remote graph `.task`, so
    /// snapshots never depend on network, demo mode, or auth session state.
    init(
        filter: NotebookFilter = NotebookFilter(),
        initialSummary: StatsPresentation.Summary? = nil,
        initialGraphLinks: [KGGraphLink],
        shouldLoadGraphData: Bool
    ) {
        self.filter = filter
        self.shouldLoadGraphData = shouldLoadGraphData
        _summary = State(initialValue: initialSummary)
        _contentReady = State(initialValue: initialSummary != nil)
        _graphLinks = State(initialValue: initialGraphLinks)
        let cutoff = Self.sixMonthsAgo
        _reviewRecords = Query(
            filter: #Predicate<ReviewRecord> { $0.reviewedAt > cutoff },
            sort: \ReviewRecord.reviewedAt,
            order: .reverse
        )
    }
#endif

    var body: some View {
        VocabSceneShell(phase: currentPhase) {
            if let summary {
                ScrollView {
                    VStack(spacing: appSkin.spacing.sectionGap) {
                        graphEntrySection
                        streakSection(summary)
                        heatmapSection(summary)
                        forecastSection(summary)
                        totalsFooter(summary)
                    }
                    .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
                    .padding(.top, appSkin.metrics.pageTopInset)
                    .padding(.bottom, appSkin.metrics.pageBottomInset)
                }
                .vocabCanvasBackground()
                // UI-test hook: only reachable in the `.content` phase
                // (VocabSceneShell renders this closure for `.content` only),
                // so its existence proves the stats dashboard truly rendered
                // from a non-empty summary — not loading / empty / logged-out.
                .accessibilityIdentifier("overview.statsContent")
                .opacity(contentReady ? 1 : 0)
                .scaleEffect(contentReady ? 1 : 0.98)
                .onAppear {
#if KG_RUN_CATALOG_SNAPSHOTS
                    contentReady = true
#else
                    withAnimation(AppMotion.contentReveal) {
                        contentReady = true
                    }
#endif
                }
            }
        }
        .animatePhaseChange(summary != nil)
        .task(id: summaryKey) {
            let entries = filteredEntries
            let records = filteredReviewRecords
            let days = forecastDays
            let reviewNow = reviewSettingsStore.settings.reviewReferenceDate()
            summary = StatsPresentation.buildSummary(
                from: entries,
                reviewRecords: records,
                forecastDays: days,
                now: reviewNow
            )
        }
        .task(id: graphKey) {
            // Fetches account-level links. Re-runs only when graphKey changes
            // (auth state, entries.count, or retryToken bump from the inline
            // error retry button), NOT on every view appearance — appearance ≠
            // staleness. Known gap: hide/unhide while entries.count is stable
            // will not auto-refresh the thumbnail until the next auth event,
            // card add/remove, or manual retry. Long-term fix: promote
            // KGGraphLink to @Model so @Query observers across stats/graph/
            // word-detail views refresh automatically on any mutation.
            guard shouldLoadGraphData else { return }
            await loadGraphLinks()
        }
        .toastSheet(isPresented: $showCalendar) {
            ReviewCalendarPresenter(filter: filter)
        }
        .enableInjection()
    }

    // MARK: - Filtered Data

    private var filteredEntries: [VocabularyEntry] {
        filter.isFiltered
            ? syncedEntries.filter { filter.matches($0.notebookId) }
            : syncedEntries
    }

    private var filteredReviewRecords: [ReviewRecord] {
        filter.isFiltered
            ? reviewRecords.filter { filter.matches($0.notebookId) }
            : reviewRecords
    }

    private func loadGraphLinks() async {
        if authManager.isDemoMode {
            graphLinks = DemoDataProvider.demoGraphLinks
            graphLoadError = false
            return
        }
        guard authManager.isLoggedIn else {
            graphLinks = []
            graphLoadError = false
            return
        }
        do {
            graphLinks = try await kgService.pullGraphLinks()
            graphLoadError = false
        } catch {
            // Failure is scoped to the graph card only — summary is built from
            // local syncedEntries and never fails. If we have cached links,
            // keep showing them but flag staleness via a dot in the header.
            // If we have nothing yet, surface error inside the graph body
            // (not page-level).
            graphLoadError = true
        }
    }

    // MARK: - Phase Resolution

    private var currentPhase: VocabScenePhase {
        // Note: no page-level .error phase. `summary` is computed from local
        // `syncedEntries` (a SwiftData @Query) and cannot fail — so the only
        // failure mode is `pullGraphLinks`, which is scoped to the graph card
        // (handled inline via graphLoadError + retry button in graphEntryBody).
        guard let summary else {
            return .loading(
                title: StatsCopy.loadingTitle,
                systemImage: "chart.bar"
            )
        }
        if StatsScenePhase.resolve(hasSummary: true, isEmpty: isSummaryEmpty(summary)) == .empty {
            let title = filter.isFiltered
                ? L10n.string("目前沒有符合篩選條件的單字")
                : StatsCopy.emptyTitle
            let description = filter.isFiltered
                ? L10n.string("試試其他關鍵字，或取消部分篩選條件。")
                : StatsCopy.emptyDescription
            return .empty(
                title: title,
                systemImage: "chart.bar.xaxis",
                description: description
            )
        }
        return .content
    }

    private func isSummaryEmpty(_ summary: StatsPresentation.Summary) -> Bool {
        summary.totalCards == 0
            && summary.activity.values.allSatisfy { $0 == 0 }
            && summary.currentStreak == 0
            && summary.longestStreak == 0
    }

    private func retryGraphLoad() {
        graphLoadError = false
        retryToken &+= 1
    }

    private var summaryKey: Int {
        var hasher = Hasher()
        hasher.combine(syncedEntries.count)
        hasher.combine(reviewRecords.count)
        hasher.combine(filter.selectedIds)
        hasher.combine(forecastDays)
        hasher.combine(reviewSettingsStore.settings.isProgressPaused)
        hasher.combine(reviewSettingsStore.settings.progressPausedAt)
        return hasher.finalize()
    }

    /// Graph thumbnail refresh trigger. `pullGraphLinks` is an account-level
    /// API — it returns ALL links regardless of notebook filter — so filter
    /// changes must NOT invalidate this cache (filter only affects local node
    /// filtering downstream). `forecastDays` is similarly irrelevant. Auth
    /// toggles and entries.count (new cards may trigger backend link
    /// generation) trigger a re-pull; `retryToken` is bumped by the inline
    /// retry button so users can re-fetch after a network failure without
    /// changing other state.
    private var graphKey: Int {
        var hasher = Hasher()
        hasher.combine(syncedEntries.count)
        hasher.combine(authManager.isLoggedIn)
        hasher.combine(authManager.isDemoMode)
        hasher.combine(retryToken)
        return hasher.finalize()
    }

    // MARK: - Graph Entry

    @ViewBuilder
    private var graphEntrySection: some View {
        let nodes = graphThumbnailNodes
        let nodeIDs = Set(nodes.map(\.id))
        let edges = graphLinks.map {
            KnowledgeGraphPresentation.edges(from: $0, validNodeIDs: nodeIDs)
        } ?? []

        if graphLoadError && graphLinks == nil {
            // No cached data — show a non-navigating card with retry. Avoids
            // pushing the user into KnowledgeGraphView with empty state.
            VocabCard(padding: 0) {
                VStack(spacing: 0) {
                    graphEntryHeader(nodeCount: 0, showsChevron: false)
                        .padding(appSkin.metrics.cardBlockPadding)
                    graphErrorBody
                        .aspectRatio(1, contentMode: .fit)
                }
            }
        } else {
            NavigationLink {
                KnowledgeGraphView(allEntries: filteredEntries)
            } label: {
                VocabCard(padding: 0) {
                    VStack(spacing: 0) {
                        graphEntryHeader(nodeCount: nodes.count, showsChevron: true)
                            .padding(appSkin.metrics.cardBlockPadding)

                        graphEntryBody(nodes: nodes, edges: edges)
                            .aspectRatio(1, contentMode: .fit)

                        if let avgRatio = averageRatio(of: nodes) {
                            healthBar(ratio: avgRatio)
                                .padding(.horizontal, appSkin.metrics.cardBlockPadding)
                                .padding(.bottom, AppSpacing.s2)
                        }
                    }
                }
            }
            .buttonStyle(.liftable)
        }
    }

    private var graphErrorBody: some View {
        VStack(spacing: appSkin.spacing.inlineGap) {
            Image(systemName: "exclamationmark.triangle")
                .font(appSkin.typography.iconMedium)
                .foregroundStyle(appSkin.palette.warning)
            Text(StatsCopy.graphErrorTitle)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.primaryText)
            Button {
                retryGraphLoad()
            } label: {
                HStack(spacing: appSkin.spacing.rowMicroGap) {
                    Image(systemName: "arrow.clockwise")
                        .font(appSkin.typography.iconSmall)
                    Text(StatsCopy.retryTitle)
                        .font(appSkin.typography.caption)
                }
                .padding(.horizontal, appSkin.spacing.inlineGap)
                .padding(.vertical, appSkin.spacing.rowMicroGap)
                .background(appSkin.palette.warningBg, in: AppRoundedRect(roundness: AppRoundness.pill))
                .foregroundStyle(appSkin.palette.warning)
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(appSkin.metrics.cardBlockPadding)
    }

    private func graphEntryHeader(nodeCount: Int, showsChevron: Bool) -> some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(appSkin.typography.iconMedium)
                .foregroundStyle(AppColors.chartHighlight)
            Text(StatsCopy.graphTitle)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.primaryText)
            if graphLoadError && graphLinks != nil {
                // Stale dot — we have cached links but the latest pull failed.
                Circle()
                    .fill(appSkin.palette.warning)
                    .frame(width: 6, height: 6)
                    .accessibilityLabel(Text(StatsCopy.staleDataTitle))
            }
            Spacer()
            if let graphLinks, !graphLinks.isEmpty {
                Text(L10n.format(
                    "%@ · %@",
                    L10n.format("vocab_graph_node_count_plural", Int64(nodeCount)),
                    L10n.format("vocab_graph_link_count_plural", Int64(graphLinks.count))
                ))
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(appSkin.typography.iconSmall)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }
        }
    }

    @ViewBuilder
    private func graphEntryBody(nodes: [KnowledgeGraphNode], edges: [KnowledgeGraphEdge]) -> some View {
        switch StatsPresentation.graphThumbnailBodyKind(
            linksLoaded: graphLinks != nil,
            nodeCount: nodes.count
        ) {
        case .loading:
            ProgressView()
                .controlSize(.small)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case .empty:
            AppStateMessageContent(
                title: StatsCopy.graphEmptyTitle,
                systemImage: "point.3.connected.trianglepath.dotted",
                style: .vocab(appSkin)
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            .padding(appSkin.metrics.cardBlockPadding)
        case .graph:
            GraphThumbnailWebView(
                holder: graphHolder,
                nodes: nodes,
                edges: edges,
                theme: KnowledgeGraphPresentation.theme(for: appSkin),
                colorScheme: colorScheme
            )
        }
    }

    private var graphThumbnailNodes: [KnowledgeGraphNode] {
        guard let graphLinks else { return [] }
        let reviewNow = reviewSettingsStore.settings.reviewReferenceDate()
        return KnowledgeGraphPresentation.nodes(
            from: filteredEntries,
            links: graphLinks,
            showIsolatedNodes: false,
            now: reviewNow
        )
    }

    private func averageRatio(of nodes: [KnowledgeGraphNode]) -> Double? {
        let ratios = nodes.compactMap(\.ratio)
        guard !ratios.isEmpty else { return nil }
        return ratios.reduce(0, +) / Double(ratios.count)
    }

    private func healthBar(ratio: Double) -> some View {
        let stops: [Gradient.Stop] = [
            0, 0.15, 0.30, 0.45, 0.60, 0.72, 0.85, 1.0, 1.3, 2.0, 3.0
        ].map { r in
            Gradient.Stop(
                color: ReviewGradient.color(for: r),
                location: CGFloat(min(r / 3.0, 1.0))
            )
        }
        let position = CGFloat(min(max(ratio, 0), 3.0) / 3.0)

        return VStack(spacing: 0) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(LinearGradient(
                            stops: stops,
                            startPoint: .leading,
                            endPoint: .trailing
                        ))
                        .frame(height: 2)

                    Triangle()
                        .fill(appSkin.palette.primaryText)
                        .frame(width: 6, height: 5)
                        .offset(
                            x: geo.size.width * position - 3,
                            y: -4
                        )
                }
            }
            .frame(height: 7)
        }
    }

    // MARK: - Sections

    private func streakSection(_ summary: StatsPresentation.Summary) -> some View {
        HStack(spacing: appSkin.spacing.sectionGap) {
            statCard(
                title: StatsCopy.currentStreakTitle,
                value: "\(summary.currentStreak)",
                unit: StatsCopy.dayUnit,
                systemImage: "flame"
            )
            statCard(
                title: StatsCopy.longestStreakTitle,
                value: "\(summary.longestStreak)",
                unit: StatsCopy.dayUnit,
                systemImage: "trophy"
            )
        }
    }

    private func statCard(
        title: String,
        value: String,
        unit: String,
        systemImage: String
    ) -> some View {
        VocabCard {
            VStack(alignment: .leading, spacing: appSkin.spacing.rowMicroGap) {
                HStack(spacing: appSkin.spacing.rowMicroGap) {
                    Image(systemName: systemImage)
                        .font(appSkin.typography.iconSmall)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                    Text(title)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
                HStack(alignment: .firstTextBaseline, spacing: AppSpacing.microGap) {
                    Text(value)
                        .font(appSkin.typography.numericHero)
                        .foregroundStyle(appSkin.palette.primaryText)
                        .contentTransition(.numericText())
                    Text(unit)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func heatmapSection(_ summary: StatsPresentation.Summary) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            Button { showCalendar = true } label: {
                HStack(spacing: appSkin.spacing.rowMicroGap) {
                    sectionHeader(title: StatsCopy.calendarTitle, systemImage: "calendar")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(appSkin.typography.iconSmall)
                        .foregroundStyle(appSkin.palette.quaternaryText)
                }
                // .plain hit-testing falls through the Spacer gap between the
                // header and the chevron — same dead zone as SettingsNavigationRow.
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Button { showCalendar = true } label: {
                VocabCard {
                    VocabActivityHeatmap(
                        activity: summary.activity,
                        thresholds: summary.heatmapThresholds,
                        weeks: 20
                    )
                }
            }
            .buttonStyle(.liftable)
        }
    }

    private func forecastSection(_ summary: StatsPresentation.Summary) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
            HStack {
                sectionHeader(title: StatsCopy.forecastTitle, systemImage: "chart.bar")
                Spacer()
                VocabTabSelector(
                    options: [
                        VocabTabOption(id: 7, title: L10n.string("7天")),
                        VocabTabOption(id: 14, title: L10n.string("14天")),
                        VocabTabOption(id: 30, title: L10n.string("30天")),
                    ],
                    selection: $forecastDays
                )
            }

            VocabCard {
                VocabForecastChart(buckets: summary.forecast)
                    .frame(height: 160)
            }
        }
    }

    private func totalsFooter(_ summary: StatsPresentation.Summary) -> some View {
        Text(L10n.format(
            "%@ · %@ · %@",
            L10n.format("vocab_total_cards_plural", Int64(summary.totalCards)),
            L10n.format("vocab_due_cards_plural", Int64(summary.dueToday)),
            L10n.format("vocab_reviewed_cards_plural", Int64(summary.reviewedToday))
        ))
            .font(appSkin.typography.monoLabel)
            .foregroundStyle(appSkin.palette.quaternaryText)
            .frame(maxWidth: .infinity, alignment: .center)
    }

    private func sectionHeader(title: String, systemImage: String) -> some View {
        HStack(spacing: appSkin.spacing.rowMicroGap) {
            Image(systemName: systemImage)
                .font(appSkin.typography.iconSmall)
            Text(title)
                .font(appSkin.typography.caption)
        }
        .foregroundStyle(appSkin.palette.tertiaryText)
    }
}

private struct Triangle: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.midX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.maxX, y: 0))
        p.addLine(to: CGPoint(x: rect.minX, y: 0))
        p.closeSubpath()
        return p
    }
}
