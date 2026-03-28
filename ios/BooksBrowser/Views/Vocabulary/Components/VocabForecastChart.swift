//
//  VocabForecastChart.swift
//  BooksBrowser
//
//  複習排程預測長條圖。
//

import SwiftUI

struct VocabForecastChart: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let buckets: [StatsPresentation.ForecastBucket]

    private var maxCount: Int {
        buckets.map(\.count).max() ?? 1
    }

    var body: some View {
        if !buckets.isEmpty {
            VStack(alignment: .leading, spacing: vocabSkin.spacing.inlineGap) {
                GeometryReader { geo in
                    let barWidth = max((geo.size.width - CGFloat(buckets.count - 1) * 3) / CGFloat(buckets.count), 8)
                    let chartHeight = geo.size.height - 20 // leave space for labels

                    HStack(alignment: .bottom, spacing: 3) {
                        ForEach(buckets) { bucket in
                            VStack(spacing: 2) {
                                if bucket.count > 0 {
                                    Text("\(bucket.count)")
                                        .font(vocabSkin.typography.monoLabel)
                                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                                }

                                RoundedRectangle(cornerRadius: 3, style: .continuous)
                                    .fill(barColor(for: bucket))
                                    .frame(
                                        width: barWidth,
                                        height: bucket.count > 0
                                            ? max(chartHeight * CGFloat(bucket.count) / CGFloat(max(maxCount, 1)), 4)
                                            : 2
                                    )

                                Text(bucket.label)
                                    .font(vocabSkin.typography.monoLabel)
                                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                                    .lineLimit(1)
                                    .frame(width: barWidth)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                }
            }
        }
    }

    private func barColor(for bucket: StatsPresentation.ForecastBucket) -> Color {
        if bucket.id == buckets.first?.id {
            return vocabSkin.palette.accent
        }
        return vocabSkin.palette.accent.opacity(0.55)
    }
}
