//
//  VocabForecastChart.swift
//  Books & Vocab
//
//  Bar chart for review schedule forecast.
//

import SwiftUI

struct VocabForecastChart: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let buckets: [StatsPresentation.ForecastBucket]

    @State private var tappedIndex: Int?
    @State private var dismissTask: Task<Void, Never>?

    private var isCompact: Bool { buckets.count > 14 }

    private var maxCount: Int { buckets.map(\.count).max() ?? 1 }

    var body: some View {
        Group {
            if !buckets.isEmpty {
                GeometryReader { geo in
                    let labelHeight: CGFloat = 16
                    let countLabelHeight: CGFloat = isCompact ? 0 : 14
                    let chartHeight = geo.size.height - labelHeight - countLabelHeight - appSkin.spacing.inlineGap
                    let columnWidth = geo.size.width / CGFloat(buckets.count)

                    ZStack(alignment: .bottom) {
                        // Baseline
                        Rectangle()
                            .fill(appSkin.palette.divider)
                            .frame(height: 1)
                            .offset(y: -labelHeight)

                        // Bars
                        HStack(alignment: .bottom, spacing: 0) {
                            ForEach(Array(buckets.enumerated()), id: \.element.id) { index, bucket in
                                barColumn(index: index, bucket: bucket, chartHeight: chartHeight, labelHeight: labelHeight, columnWidth: columnWidth)
                                    .frame(maxWidth: .infinity)
                            }
                        }

                        // Tooltip
                        if let idx = tappedIndex, idx < buckets.count {
                            tooltipView(for: idx, geo: geo, chartHeight: chartHeight, labelHeight: labelHeight)
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                }
            }
        }
        .enableInjection()
    }

    // MARK: - Bar Column

    @ViewBuilder
    private func barColumn(index: Int, bucket: StatsPresentation.ForecastBucket, chartHeight: CGFloat, labelHeight: CGFloat, columnWidth: CGFloat) -> some View {
        let barHeight: CGFloat = bucket.count > 0
            ? max(chartHeight * CGFloat(bucket.count) / CGFloat(max(maxCount, 1)), 4)
            : 0
        let barWidth = columnWidth * 0.5

        VStack(spacing: 0) {
            // Count label
            if !isCompact && bucket.count > 0 {
                Text("\(bucket.count)")
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .frame(height: 14)
            } else {
                Spacer()
                    .frame(height: isCompact ? 0 : 14)
            }

            // Bar area
            VStack(spacing: 0) {
                Spacer(minLength: 0)

                if bucket.count > 0 {
                    // 柱寬 = columnWidth × 0.5（14 bucket 下 ≈12pt）＝短邊，落在 pill 階。
                    AppRoundedRect(roundness: AppRoundness.pill)
                        .fill(index == 0
                              ? AppColors.chartHighlight
                              : AppColors.chartHighlight.opacity(0.35))
                        .frame(width: barWidth, height: barHeight)
                }
            }
            .frame(height: chartHeight)
            .frame(maxWidth: .infinity)

            // Date label below baseline
            dateLabel(index: index, bucket: bucket)
                .frame(height: labelHeight)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            dismissTask?.cancel()
            withAnimation(AppMotion.feedbackPulse) { tappedIndex = index }
            dismissTask = Task {
                try? await Task.sleep(for: .seconds(1.5))
                guard !Task.isCancelled else { return }
                withAnimation(AppMotion.contentFade) { tappedIndex = nil }
            }
        }
    }

    // MARK: - Date Label

    @ViewBuilder
    private func dateLabel(index: Int, bucket: StatsPresentation.ForecastBucket) -> some View {
        let text: String? = {
            if index == 0 { return "今天".localized }
            if index == 6, buckets.count > 7 { return "1週".localized }
            if index == buckets.count - 1 { return bucket.label }
            return nil
        }()

        if let text {
            Text(text)
                .font(appSkin.typography.monoLabel)
                .foregroundStyle(appSkin.palette.quaternaryText)
                .lineLimit(1)
        } else {
            Color.clear
        }
    }

    // MARK: - Tooltip

    @ViewBuilder
    private func tooltipView(for index: Int, geo: GeometryProxy, chartHeight: CGFloat, labelHeight: CGFloat) -> some View {
        let bucket = buckets[index]
        let columnWidth = geo.size.width / CGFloat(buckets.count)
        let xOffset = columnWidth * (CGFloat(index) + 0.5) - geo.size.width / 2

        Text("\(bucket.label): \(bucket.count)")
            .font(appSkin.typography.monoLabel)
            .foregroundStyle(appSkin.palette.primaryText)
            .padding(.horizontal, appSkin.spacing.rowMicroGap)
            .padding(.vertical, AppSpacing.microGap)
            .background(
                AppRoundedRect(roundness: AppRoundness.pill)
                    .fill(appSkin.palette.cardBackground)
                    .appElevation(.z1)
            )
            .offset(x: xOffset, y: -(chartHeight + labelHeight + appSkin.spacing.inlineGap))
            .transition(.overlayFade)
    }
}

#Preview("VocabForecastChart") {
    let counts = [12, 5, 8, 3, 6, 9, 4, 2, 7, 1, 5, 3, 6, 2]
    let buckets = counts.enumerated().map { index, count in
        StatsPresentation.ForecastBucket(id: "d\(index)", label: "+\(index)d", count: count)
    }

    return AppThemeContainer {
        VocabForecastChart(buckets: buckets)
            .frame(height: 160)
            .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}
