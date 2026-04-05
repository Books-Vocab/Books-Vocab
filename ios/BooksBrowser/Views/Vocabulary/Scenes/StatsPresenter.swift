//
//  StatsPresenter.swift
//  BooksBrowser
//
//  學習統計儀表板場景。
//

import SwiftUI
import SwiftData

struct StatsPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.colorScheme) private var colorScheme

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

    private static let sixMonthsAgo = Calendar.current.date(byAdding: .month, value: -6, to: Date()) ?? Date()

    init(filter: NotebookFilter = NotebookFilter()) {
        self.filter = filter
        let cutoff = Self.sixMonthsAgo
        _reviewRecords = Query(
            filter: #Predicate<ReviewRecord> { $0.reviewedAt > cutoff },
            sort: \ReviewRecord.reviewedAt,
            order: .reverse
        )
    }

    var body: some View {
        VocabSceneShell(phase: summary == nil
            ? .loading(title: "計算統計資料...".localized, systemImage: "chart.bar")
            : .content
        ) {
            if let summary {
                ScrollView {
                    VStack(spacing: vocabSkin.spacing.sectionGap) {
                        #if os(macOS)
                        HStack(alignment: .top, spacing: vocabSkin.spacing.sectionGap) {
                            graphEntrySection
                                .frame(maxWidth: .infinity)
                            VStack(spacing: vocabSkin.spacing.sectionGap) {
                                streakSection(summary)
                                heatmapSection(summary)
                            }
                            .frame(maxWidth: .infinity)
                        }
                        #else
                        graphEntrySection
                        streakSection(summary)
                        heatmapSection(summary)
                        #endif
                        forecastSection(summary)
                        totalsFooter(summary)
                    }
                    .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
                    .padding(.top, vocabSkin.metrics.pageTopInset)
                    .padding(.bottom, vocabSkin.metrics.pageBottomInset)
                }
                .vocabCanvasBackground()
                .opacity(contentReady ? 1 : 0)
                .scaleEffect(contentReady ? 1 : 0.98)
                .onAppear {
                    withAnimation(AppMotion.contentReveal) {
                        contentReady = true
                    }
                }
            }
        }
        .animatePhaseChange(summary != nil)
        .task(id: summaryKey) {
            let entries = filteredEntries
            let records = filteredReviewRecords
            let days = forecastDays
            summary = StatsPresentation.buildSummary(
                from: entries,
                reviewRecords: records,
                forecastDays: days
            )
        }
        .task(id: graphKey) {
            // Fetches account-level links. Re-runs only when graphKey changes
            // (auth state or entries.count), NOT on every view appearance —
            // appearance ≠ staleness. Known gap: hide/unhide while entries.count
            // is stable will not auto-refresh the thumbnail until the next auth
            // event or card add/remove. Long-term fix: promote KGGraphLink to
            // @Model so @Query observers across stats/graph/word-detail views
            // refresh automatically on any mutation (see spec:
            // docs/superpowers/specs/ — SwiftData migration for KGGraphLink).
            graphLinks = await loadGraphLinks()
        }
        .toastSheet(isPresented: $showCalendar) {
            ReviewCalendarPresenter()
        }
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

    private func loadGraphLinks() async -> [KGGraphLink] {
        if authManager.isDemoMode {
            return DemoDataProvider.demoGraphLinks
        }
        guard authManager.isLoggedIn else { return [] }
        return (try? await kgService.pullGraphLinks()) ?? []
    }

    private var summaryKey: Int {
        var hasher = Hasher()
        hasher.combine(syncedEntries.count)
        hasher.combine(reviewRecords.count)
        hasher.combine(filter.selectedIds)
        hasher.combine(forecastDays)
        return hasher.finalize()
    }

    /// Graph thumbnail refresh trigger. `pullGraphLinks` is an account-level
    /// API — it returns ALL links regardless of notebook filter — so filter
    /// changes must NOT invalidate this cache (filter only affects local node
    /// filtering downstream). `forecastDays` is similarly irrelevant. Only
    /// auth toggles and entries.count (new cards may trigger backend link
    /// generation) should trigger a re-pull.
    private var graphKey: Int {
        var hasher = Hasher()
        hasher.combine(syncedEntries.count)
        hasher.combine(authManager.isLoggedIn)
        hasher.combine(authManager.isDemoMode)
        return hasher.finalize()
    }

    // MARK: - Graph Entry

    private var graphEntrySection: some View {
        let nodes = graphThumbnailNodes
        let nodeIDs = Set(nodes.map(\.id))
        let edges = graphLinks.map {
            KnowledgeGraphPresentation.edges(from: $0, validNodeIDs: nodeIDs)
        } ?? []

        return NavigationLink {
            KnowledgeGraphView(allEntries: filteredEntries)
        } label: {
            VocabCard(padding: 0) {
                VStack(spacing: 0) {
                    graphEntryHeader(nodeCount: nodes.count)
                        .padding(vocabSkin.metrics.cardBlockPadding)

                    graphEntryBody(nodes: nodes, edges: edges)
                        #if os(macOS)
                        .frame(minHeight: 280)
                        #else
                        .frame(height: 140)
                        #endif

                    if let avgRatio = averageRatio(of: nodes), !nodes.isEmpty {
                        healthBar(ratio: avgRatio)
                            .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
                            .padding(.bottom, 8)
                    }
                }
            }
        }
        .buttonStyle(.liftable)
    }

    private func graphEntryHeader(nodeCount: Int) -> some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.accent)
            Text("關聯圖".localized)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.primaryText)
            Spacer()
            if let graphLinks, !graphLinks.isEmpty {
                Text("\(nodeCount) 詞 · \(graphLinks.count) 連結")
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
            Image(systemName: "chevron.right")
                .font(vocabSkin.typography.iconSmall)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
    }

    @ViewBuilder
    private func graphEntryBody(nodes: [KnowledgeGraphNode], edges: [KnowledgeGraphEdge]) -> some View {
        if graphLinks != nil {
            if nodes.isEmpty {
                VocabStateMessageCard(
                    title: "探索單字建立連結".localized,
                    systemImage: "point.3.connected.trianglepath.dotted"
                )
            } else {
                GraphThumbnailWebView(
                    holder: graphHolder,
                    nodes: nodes,
                    edges: edges,
                    theme: KnowledgeGraphPresentation.theme(for: vocabSkin),
                    colorScheme: colorScheme
                )
            }
        } else {
            ProgressView()
                .controlSize(.small)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private var graphThumbnailNodes: [KnowledgeGraphNode] {
        guard let graphLinks else { return [] }
        return KnowledgeGraphPresentation.nodes(
            from: filteredEntries,
            links: graphLinks,
            showIsolatedNodes: false
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
                    RoundedRectangle(cornerRadius: 1)
                        .fill(LinearGradient(
                            stops: stops,
                            startPoint: .leading,
                            endPoint: .trailing
                        ))
                        .frame(height: 2)

                    Triangle()
                        .fill(vocabSkin.palette.primaryText)
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
        HStack(spacing: vocabSkin.spacing.sectionGap) {
            statCard(
                title: "連續學習".localized,
                value: "\(summary.currentStreak)",
                unit: "天".localized,
                systemImage: "flame"
            )
            statCard(
                title: "最長紀錄".localized,
                value: "\(summary.longestStreak)",
                unit: "天".localized,
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
            VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
                HStack(spacing: vocabSkin.spacing.microGap) {
                    Image(systemName: systemImage)
                        .font(vocabSkin.typography.iconSmall)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                    Text(title)
                        .font(vocabSkin.typography.captionStrong)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    Text(value)
                        .font(vocabSkin.typography.numericHero)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .contentTransition(.numericText())
                    Text(unit)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func heatmapSection(_ summary: StatsPresentation.Summary) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            Button { showCalendar = true } label: {
                HStack(spacing: vocabSkin.spacing.microGap) {
                    sectionHeader(title: "學習日曆".localized, systemImage: "calendar")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(vocabSkin.typography.iconSmall)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                }
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
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            HStack {
                sectionHeader(title: "複習預測".localized, systemImage: "chart.bar")
                Spacer()
                VocabTabSelector(
                    options: [
                        VocabTabOption(id: 7, title: "7天"),
                        VocabTabOption(id: 14, title: "14天"),
                        VocabTabOption(id: 30, title: "30天"),
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
        Text("\(summary.totalCards) 張卡片 · \(summary.dueToday) 張到期 · 今天已複習 \(summary.reviewedToday) 張")
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(vocabSkin.palette.quaternaryText)
            .frame(maxWidth: .infinity, alignment: .center)
    }

    private func sectionHeader(title: String, systemImage: String) -> some View {
        HStack(spacing: vocabSkin.spacing.microGap) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconSmall)
            Text(title)
                .font(vocabSkin.typography.captionStrong)
        }
        .foregroundStyle(vocabSkin.palette.tertiaryText)
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
