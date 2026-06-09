//
//  VocabActivityHeatmap.swift
//  Books & Vocab
//
//  類似 GitHub 貢獻圖的學習活動熱力圖。
//

import SwiftUI

struct VocabActivityHeatmap: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let activity: [String: Int]  // "yyyy-MM-dd" -> count
    let thresholds: [Int]
    let weeks: Int

    init(activity: [String: Int], thresholds: [Int] = [], weeks: Int = 20) {
        self.activity = activity
        self.thresholds = thresholds
        self.weeks = weeks
    }

    private static let calendar = Calendar.current
    private static let dayFormatter = AppDateFormatters.dayKey

    private let cellSize: CGFloat = 13
    private let cellSpacing: CGFloat = 3
    // Alternate rows (Mon/Wed/Fri/Sun, Monday=0) — labeled rows in the every-other-row layout.
    private static let weekdayIndices = [0, 2, 4, 6]
    // Locale-aware, Monday-first; subset to `weekdayIndices`
    // to match the heatmap's every-other-row label layout.
    private let weekdayLabels: [String] = {
        let all = LocaleAwareFormatter.shared.mondayFirstWeekdaySymbols(short: true)
        return Self.weekdayIndices.compactMap { all.indices.contains($0) ? all[$0] : nil }
    }()

    @State private var grid: [[CellData]] = []

    private static func buildGrid(activity: [String: Int], weeks: Int) -> [[CellData]] {
        let today = Date()
        let cal = calendar

        // 找到本週一
        var comps = cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: today)
        comps.weekday = 2 // Monday
        let thisMonday = cal.date(from: comps) ?? today

        var columns: [[CellData]] = []
        for weekOffset in stride(from: -(weeks - 1), through: 0, by: 1) {
            guard let weekStart = cal.date(byAdding: .weekOfYear, value: weekOffset, to: thisMonday) else { continue }
            var column: [CellData] = []
            for dayOffset in 0..<7 {
                guard let date = cal.date(byAdding: .day, value: dayOffset, to: weekStart) else { continue }
                let key = dayFormatter.string(from: date)
                let count = activity[key] ?? 0
                let isFuture = date > today
                column.append(CellData(key: key, count: count, isFuture: isFuture))
            }
            columns.append(column)
        }
        return columns
    }

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.microGap) {
            ScrollView(.horizontal, showsIndicators: false) {
                ScrollViewReader { proxy in
                    HStack(alignment: .top, spacing: 0) {
                        // Weekday labels
                        VStack(alignment: .trailing, spacing: 0) {
                            ForEach(0..<7, id: \.self) { row in
                                if let index = Self.weekdayIndices.firstIndex(of: row) {
                                    Text(weekdayLabels[index])
                                        .font(appSkin.typography.monoLabel)
                                        .foregroundStyle(appSkin.palette.quaternaryText)
                                        .frame(height: cellSize + cellSpacing)
                                } else {
                                    Color.clear
                                        .frame(height: cellSize + cellSpacing)
                                }
                            }
                        }
                        .padding(.trailing, appSkin.spacing.microGap)

                        HStack(spacing: cellSpacing) {
                            ForEach(Array(grid.enumerated()), id: \.offset) { weekIndex, column in
                                VStack(spacing: cellSpacing) {
                                    ForEach(column, id: \.key) { cell in
                                        cellView(cell)
                                    }
                                }
                                .id(weekIndex)
                            }
                        }
                    }
                    .onAppear {
                        proxy.scrollTo(grid.count - 1, anchor: .trailing)
                    }
                }
            }

            // Legend
            HStack(spacing: appSkin.spacing.microGap) {
                Text("少".localized)
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.quaternaryText)
                ForEach(1..<5, id: \.self) { level in
                    let size: CGFloat = level >= 3 ? cellSize * 1.15 : cellSize
                    Circle()
                        .fill(levelColor(level))
                        .frame(width: size, height: size)
                }
                Text("多".localized)
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }
        }
        .task { grid = Self.buildGrid(activity: activity, weeks: weeks) }
        .onChange(of: activity) { _, new in grid = Self.buildGrid(activity: new, weeks: weeks) }
        .enableInjection()
    }

    @ViewBuilder
    private func cellView(_ cell: CellData) -> some View {
        if cell.isFuture {
            Color.clear
                .frame(width: cellSize, height: cellSize)
        } else {
            let level = intensityLevel(cell.count)
            let dotSize: CGFloat = level >= 3 ? cellSize * 1.15 : cellSize
            Circle()
                .fill(levelColor(level))
                .frame(width: dotSize, height: dotSize)
                .frame(width: cellSize, height: cellSize) // outer frame for consistent grid spacing
        }
    }

    private func intensityLevel(_ count: Int) -> Int {
        guard count > 0 else { return 0 }
        if thresholds.count < 3 { return 1 }
        if count <= thresholds[0] { return 1 }
        if count <= thresholds[1] { return 2 }
        if count <= thresholds[2] { return 3 }
        return 4
    }

    private func levelColor(_ level: Int) -> Color {
        switch level {
        case 0: return Color.clear
        case 1: return appSkin.palette.mutedFill
        case 2: return AppColors.chartHighlight.opacity(0.35)
        case 3: return AppColors.chartHighlight.opacity(0.6)
        default: return AppColors.chartHighlight
        }
    }
}

private struct CellData {
    let key: String
    let count: Int
    let isFuture: Bool
}

#Preview("VocabActivityHeatmap") {
    let cal = Calendar.current
    let formatter = AppDateFormatters.dayKey
    var activity: [String: Int] = [:]
    for offset in 0..<120 where offset % 4 != 0 {
        if let date = cal.date(byAdding: .day, value: -offset, to: Date()) {
            activity[formatter.string(from: date)] = (offset % 13) + 1
        }
    }

    return AppThemeContainer {
        VocabActivityHeatmap(
            activity: activity,
            thresholds: [2, 5, 9],
            weeks: 20
        )
        .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}
