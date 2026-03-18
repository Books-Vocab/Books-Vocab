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

    let filter: NotebookFilter

    @Query(filter: #Predicate<VocabularyEntry> {
        $0.syncStatus == 1 &&
        $0.actionType != "delete"
    })
    private var syncedEntries: [VocabularyEntry]

    @Query var reviewRecords: [ReviewRecord]

    @State private var summary: StatsPresentation.Summary?
    @State private var showCalendar = false

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
        ScrollView {
            if let summary {
                VStack(spacing: vocabSkin.spacing.sectionGap) {
                    graphEntrySection
                    streakSection(summary)
                    heatmapSection(summary)
                    forecastSection(summary)
                    totalsSection(summary)
                }
                .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
                .padding(.top, vocabSkin.metrics.pageTopInset)
                .padding(.bottom, vocabSkin.metrics.pageBottomInset)
            } else {
                VStack {
                    Spacer(minLength: 120)
                    VocabStateMessageCard(
                        title: "計算統計資料...".localized,
                        systemImage: "chart.bar"
                    ) {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Spacer()
                }
                .padding(vocabSkin.metrics.cardBlockPadding)
            }
        }
        .vocabCanvasBackground()
        .animation(AppMotion.phaseChange, value: summary != nil)
        .task {
            recompute()
        }
        .onChange(of: syncedEntries.count) { _, _ in
            recompute()
        }
        .onChange(of: reviewRecords.count) { _, _ in
            recompute()
        }
        .onChange(of: filter) { _, _ in
            recompute()
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

    private func recompute() {
        summary = StatsPresentation.buildSummary(
            from: filteredEntries,
            reviewRecords: filteredReviewRecords
        )
    }

    // MARK: - Graph Entry

    private var graphEntrySection: some View {
        NavigationLink {
            KnowledgeGraphView(allEntries: filteredEntries)
        } label: {
            VocabCard {
                HStack(spacing: vocabSkin.spacing.inlineGap) {
                    Image(systemName: "point.3.connected.trianglepath.dotted")
                        .font(vocabSkin.typography.iconMedium)
                        .foregroundStyle(vocabSkin.palette.accent)
                    Text("關聯圖".localized)
                        .font(vocabSkin.typography.captionStrong)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(vocabSkin.typography.iconSmall)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                }
            }
        }
        .buttonStyle(.plain)
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
                    VocabActivityHeatmap(activity: summary.activity, weeks: 20)
                }
            }
            .buttonStyle(.plain)
        }
    }

    private func forecastSection(_ summary: StatsPresentation.Summary) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            sectionHeader(title: "複習預測".localized, systemImage: "chart.bar")

            VocabCard {
                VocabForecastChart(buckets: summary.forecast)
                    .frame(height: 160)
            }
        }
    }

    private func totalsSection(_ summary: StatsPresentation.Summary) -> some View {
        VocabCard {
            HStack(spacing: vocabSkin.spacing.sectionGap) {
                miniStat(label: "總卡片數".localized, value: "\(summary.totalCards)")
                miniStat(label: "今天到期".localized, value: "\(summary.dueToday)")
                miniStat(label: "今天已複習".localized, value: "\(summary.reviewedToday)")
            }
        }
    }

    private func miniStat(label: String, value: String) -> some View {
        VStack(spacing: 2) {
            Text(value)
                .font(vocabSkin.typography.monoEmphasis)
                .foregroundStyle(vocabSkin.palette.primaryText)
            Text(label)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
        }
        .frame(maxWidth: .infinity)
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
