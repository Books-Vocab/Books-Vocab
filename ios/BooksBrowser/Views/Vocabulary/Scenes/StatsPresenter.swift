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

    @Query(filter: #Predicate<VocabularyEntry> {
        $0.syncStatus == 1 &&
        $0.actionType != "delete"
    })
    private var syncedEntries: [VocabularyEntry]

    @State private var summary: StatsPresentation.Summary?

    var body: some View {
        ScrollView {
            if let summary {
                VStack(spacing: vocabSkin.spacing.sectionGap) {
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
                        title: "計算統計資料...",
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
        .task {
            recompute()
        }
        .onChange(of: syncedEntries.count) { _, _ in
            recompute()
        }
    }

    private func recompute() {
        summary = StatsPresentation.buildSummary(from: syncedEntries)
    }

    // MARK: - Sections

    private func streakSection(_ summary: StatsPresentation.Summary) -> some View {
        HStack(spacing: vocabSkin.spacing.sectionGap) {
            statCard(
                title: "連續學習",
                value: "\(summary.currentStreak)",
                unit: "天",
                systemImage: "flame"
            )
            statCard(
                title: "最長紀錄",
                value: "\(summary.longestStreak)",
                unit: "天",
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
                Text(unit)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(vocabSkin.spacing.cardPadding)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
        )
    }

    private func heatmapSection(_ summary: StatsPresentation.Summary) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            sectionHeader(title: "學習日曆", systemImage: "calendar")

            VocabActivityHeatmap(activity: summary.activity, weeks: 20)
                .padding(vocabSkin.spacing.cardPadding)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .fill(vocabSkin.palette.cardBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                        )
                )
        }
    }

    private func forecastSection(_ summary: StatsPresentation.Summary) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
            sectionHeader(title: "複習預測", systemImage: "chart.bar")

            VocabForecastChart(buckets: summary.forecast)
                .frame(height: 160)
                .padding(vocabSkin.spacing.cardPadding)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .fill(vocabSkin.palette.cardBackground)
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                        )
                )
        }
    }

    private func totalsSection(_ summary: StatsPresentation.Summary) -> some View {
        HStack(spacing: vocabSkin.spacing.sectionGap) {
            miniStat(label: "總卡片數", value: "\(summary.totalCards)")
            miniStat(label: "今天到期", value: "\(summary.dueToday)")
            miniStat(label: "今天已複習", value: "\(summary.reviewedToday)")
        }
        .padding(vocabSkin.spacing.cardPadding)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
        )
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
