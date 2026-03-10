//
//  VocabActivityHeatmap.swift
//  BooksBrowser
//
//  類似 GitHub 貢獻圖的學習活動熱力圖。
//

import SwiftUI

struct VocabActivityHeatmap: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let activity: [String: Int]  // "yyyy-MM-dd" -> count
    let weeks: Int

    init(activity: [String: Int], weeks: Int = 20) {
        self.activity = activity
        self.weeks = weeks
    }

    private static let calendar = Calendar.current
    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        return f
    }()

    private let cellSize: CGFloat = 13
    private let cellSpacing: CGFloat = 3
    private let weekdayLabels = ["一", "三", "五", "日"]
    private let weekdayIndices = [0, 2, 4, 6] // Mon, Wed, Fri, Sun (Monday=0)

    private var grid: [[CellData]] {
        let today = Date()
        let cal = Self.calendar

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
                let key = Self.dayFormatter.string(from: date)
                let count = activity[key] ?? 0
                let isFuture = date > today
                column.append(CellData(key: key, count: count, isFuture: isFuture))
            }
            columns.append(column)
        }
        return columns
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
            ScrollView(.horizontal, showsIndicators: false) {
                ScrollViewReader { proxy in
                    HStack(alignment: .top, spacing: 0) {
                        // Weekday labels
                        VStack(alignment: .trailing, spacing: 0) {
                            ForEach(0..<7, id: \.self) { row in
                                if weekdayIndices.contains(row) {
                                    Text(weekdayLabels[weekdayIndices.firstIndex(of: row)!])
                                        .font(vocabSkin.typography.monoLabel)
                                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                                        .frame(height: cellSize + cellSpacing)
                                } else {
                                    Color.clear
                                        .frame(height: cellSize + cellSpacing)
                                }
                            }
                        }
                        .padding(.trailing, vocabSkin.spacing.microGap)

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
            HStack(spacing: vocabSkin.spacing.microGap) {
                Text("少".localized)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                ForEach(0..<5, id: \.self) { level in
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(levelColor(level))
                        .frame(width: cellSize, height: cellSize)
                }
                Text("多".localized)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
    }

    @ViewBuilder
    private func cellView(_ cell: CellData) -> some View {
        if cell.isFuture {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(Color.clear)
                .frame(width: cellSize, height: cellSize)
        } else {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(levelColor(intensityLevel(cell.count)))
                .frame(width: cellSize, height: cellSize)
        }
    }

    private func intensityLevel(_ count: Int) -> Int {
        switch count {
        case 0: return 0
        case 1...3: return 1
        case 4...7: return 2
        case 8...14: return 3
        default: return 4
        }
    }

    private func levelColor(_ level: Int) -> Color {
        let base = vocabSkin.palette.accent
        switch level {
        case 0: return vocabSkin.palette.mutedFill
        case 1: return base.opacity(0.25)
        case 2: return base.opacity(0.50)
        case 3: return base.opacity(0.75)
        default: return base
        }
    }
}

private struct CellData {
    let key: String
    let count: Int
    let isFuture: Bool
}
