//
//  VocabForecastChart.swift
//  BooksBrowser
//
//  Lollipop chart for review schedule forecast.
//

import SwiftUI

struct VocabForecastChart: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let buckets: [StatsPresentation.ForecastBucket]

    @State private var tappedIndex: Int?

    private let dotSize: CGFloat = 8

    private var isCompact: Bool { buckets.count > 14 }

    private var maxCount: Int { buckets.map(\.count).max() ?? 1 }

    var body: some View {
        if !buckets.isEmpty {
            GeometryReader { geo in
                let labelHeight: CGFloat = 16
                let countLabelHeight: CGFloat = isCompact ? 0 : 14
                let chartHeight = geo.size.height - labelHeight - countLabelHeight - vocabSkin.spacing.inlineGap

                ZStack(alignment: .bottom) {
                    // Baseline
                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)
                        .offset(y: -labelHeight)

                    // Lollipops
                    HStack(alignment: .bottom, spacing: 0) {
                        ForEach(Array(buckets.enumerated()), id: \.element.id) { index, bucket in
                            lollipopColumn(index: index, bucket: bucket, chartHeight: chartHeight, labelHeight: labelHeight)
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

    // MARK: - Lollipop Column

    @ViewBuilder
    private func lollipopColumn(index: Int, bucket: StatsPresentation.ForecastBucket, chartHeight: CGFloat, labelHeight: CGFloat) -> some View {
        let effectiveDotSize = isCompact ? dotSize * 0.7 : dotSize
        let stemHeight: CGFloat = bucket.count > 0
            ? max(chartHeight * CGFloat(bucket.count) / CGFloat(max(maxCount, 1)), effectiveDotSize)
            : 0

        VStack(spacing: 0) {
            // Count label
            if !isCompact && bucket.count > 0 {
                Text("\(bucket.count)")
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                    .frame(height: 14)
            } else {
                Spacer()
                    .frame(height: isCompact ? 0 : 14)
            }

            // Dot + Stem
            ZStack(alignment: .top) {
                if bucket.count > 0 {
                    // Stem
                    Rectangle()
                        .fill(vocabSkin.palette.accent.opacity(0.3))
                        .frame(width: 1, height: stemHeight)
                        .frame(maxHeight: .infinity, alignment: .bottom)

                    // Dot at top
                    dotView(index: index, bucket: bucket, size: effectiveDotSize)
                } else {
                    // Empty: tiny dot on baseline
                    Spacer()
                    Circle()
                        .fill(vocabSkin.palette.mutedFill)
                        .frame(width: 3, height: 3)
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
            withAnimation(AppMotion.feedbackPulse) { tappedIndex = index }
            Task {
                try? await Task.sleep(for: .seconds(1.5))
                withAnimation(AppMotion.contentFade) { tappedIndex = nil }
            }
        }
    }

    // MARK: - Dot

    @ViewBuilder
    private func dotView(index: Int, bucket: StatsPresentation.ForecastBucket, size: CGFloat) -> some View {
        if index == 0 {
            // Today: filled accent with muted halo
            ZStack {
                Circle()
                    .fill(vocabSkin.palette.mutedFill)
                    .frame(width: size * 1.8, height: size * 1.8)
                Circle()
                    .fill(vocabSkin.palette.accent)
                    .frame(width: size, height: size)
            }
        } else {
            // Stroke-only circle
            Circle()
                .strokeBorder(vocabSkin.palette.accent.opacity(0.55), lineWidth: 1.5)
                .frame(width: size, height: size)
        }
    }

    // MARK: - Date Label

    @ViewBuilder
    private func dateLabel(index: Int, bucket: StatsPresentation.ForecastBucket) -> some View {
        let text: String? = {
            if index == 0 { return "今天" }
            if index == 6, buckets.count > 7 { return "1w" }
            if index == buckets.count - 1 { return bucket.label }
            return nil
        }()

        if let text {
            Text(text)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
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
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(vocabSkin.palette.primaryText)
            .padding(.horizontal, vocabSkin.spacing.microGap)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(vocabSkin.palette.cardBackground)
                    .shadow(color: vocabSkin.palette.shadow, radius: 2, y: 1)
            )
            .offset(x: xOffset, y: -(chartHeight + labelHeight + vocabSkin.spacing.inlineGap))
            .transition(.opacity)
    }
}
