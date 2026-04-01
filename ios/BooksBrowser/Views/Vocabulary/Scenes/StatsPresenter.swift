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
                        graphEntrySection
                        streakSection(summary)
                        heatmapSection(summary)
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
        .task(id: recomputeKey) {
            let entries = filteredEntries
            let records = filteredReviewRecords
            let days = forecastDays
            summary = StatsPresentation.buildSummary(
                from: entries,
                reviewRecords: records,
                forecastDays: days
            )
            graphLinks = await loadGraphLinks()
        }
        .sheet(isPresented: $showCalendar) {
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

    private var recomputeKey: Int {
        var hasher = Hasher()
        hasher.combine(syncedEntries.count)
        hasher.combine(reviewRecords.count)
        hasher.combine(filter.selectedIds)
        hasher.combine(forecastDays)
        return hasher.finalize()
    }

    // MARK: - Graph Entry

    private var graphEntrySection: some View {
        NavigationLink {
            KnowledgeGraphView(allEntries: filteredEntries)
        } label: {
            VocabCard(padding: 0) {
                VStack(spacing: 0) {
                    graphEntryHeader
                        .padding(vocabSkin.metrics.cardBlockPadding)

                    graphEntryBody
                        .frame(height: 140)
                }
            }
        }
        .buttonStyle(.liftable)
    }

    private var graphEntryHeader: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.accent)
            Text("關聯圖".localized)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.primaryText)
            Spacer()
            if let graphLinks, !graphLinks.isEmpty {
                let nodes = graphThumbnailNodes
                Text("\(nodes.count) 詞 · \(graphLinks.count) 連結")
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
            Image(systemName: "chevron.right")
                .font(vocabSkin.typography.iconSmall)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
    }

    @ViewBuilder
    private var graphEntryBody: some View {
        if let graphLinks {
            let nodes = graphThumbnailNodes
            let nodeIDs = Set(nodes.map(\.id))
            let edges = KnowledgeGraphPresentation.edges(from: graphLinks, validNodeIDs: nodeIDs)

            if nodes.isEmpty {
                VocabStateMessageCard(
                    title: "探索單字建立連結".localized,
                    systemImage: "point.3.connected.trianglepath.dotted"
                )
            } else {
                GraphThumbnailWebView(
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
