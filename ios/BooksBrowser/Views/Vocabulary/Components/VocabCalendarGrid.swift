//
//  VocabCalendarGrid.swift
//  BooksBrowser
//
//  月曆格子元件，顯示每日複習活動色階。
//

import SwiftUI

struct VocabCalendarGrid: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let displayedMonth: Date
    let activityMap: [String: Int]
    @Binding var selectedDay: String?

    private static let calendar = Calendar.current
    private static let dayFormatter = AppDateFormatters.dayKey

    private let weekdaySymbols = ["一", "二", "三", "四", "五", "六", "日"]
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 7)
    private let todayKey = VocabCalendarGrid.dayFormatter.string(from: Date())

    private var monthDays: [DayCell] {
        let cal = Self.calendar
        let comps = cal.dateComponents([.year, .month], from: displayedMonth)
        guard let firstOfMonth = cal.date(from: comps),
              let range = cal.range(of: .day, in: .month, for: firstOfMonth) else { return [] }

        // Monday=1 ... Sunday=7 → offset
        let firstWeekday = cal.component(.weekday, from: firstOfMonth)
        // Convert to Monday-based: Mon=0, Tue=1, ..., Sun=6
        let mondayOffset = (firstWeekday + 5) % 7

        var cells: [DayCell] = []

        // Leading blanks
        for i in 0..<mondayOffset {
            cells.append(DayCell(id: "blank-\(i)", dayNumber: 0, dayKey: nil, isToday: false))
        }

        for day in range {
            var dayComps = comps
            dayComps.day = day
            guard let date = cal.date(from: dayComps) else { continue }
            let key = Self.dayFormatter.string(from: date)
            cells.append(DayCell(
                id: key,
                dayNumber: day,
                dayKey: key,
                isToday: key == todayKey
            ))
        }
        return cells
    }

    var body: some View {
        VStack(spacing: vocabSkin.spacing.microGap) {
            // Weekday header
            LazyVGrid(columns: columns, spacing: 4) {
                ForEach(weekdaySymbols, id: \.self) { symbol in
                    Text(symbol)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                        .frame(maxWidth: .infinity)
                }
            }

            // Day grid
            LazyVGrid(columns: columns, spacing: 4) {
                ForEach(monthDays) { cell in
                    if cell.dayNumber == 0 {
                        Color.clear
                            .aspectRatio(1, contentMode: .fit)
                    } else {
                        dayView(cell)
                    }
                }
            }
        }
    }

    private func dayView(_ cell: DayCell) -> some View {
        let count = cell.dayKey.flatMap { activityMap[$0] } ?? 0
        let isSelected = cell.dayKey == selectedDay

        return Button {
            withAnimation(AppMotion.chipSelect) {
                selectedDay = cell.dayKey
            }
        } label: {
            VStack(spacing: 1) {
                Text("\(cell.dayNumber)")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(
                        cell.isToday ? vocabSkin.palette.accent :
                        isSelected ? vocabSkin.palette.primaryText :
                        vocabSkin.palette.secondaryText
                    )

                // Activity dot
                Circle()
                    .fill(count > 0 ? dotColor(count) : Color.clear)
                    .frame(width: 5, height: 5)
            }
            .frame(maxWidth: .infinity)
            .aspectRatio(1, contentMode: .fit)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                    .fill(isSelected ? vocabSkin.palette.mutedFill : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                    .fill(count > 0 ? cellFill(count) : Color.clear)
            )
        }
        .buttonStyle(.plain)
    }

    private func dotColor(_ count: Int) -> Color {
        switch count {
        case 1...3: return vocabSkin.palette.accent.opacity(0.5)
        case 4...7: return vocabSkin.palette.accent.opacity(0.75)
        default: return vocabSkin.palette.accent
        }
    }

    private func cellFill(_ count: Int) -> Color {
        switch count {
        case 1...3: return vocabSkin.palette.accent.opacity(0.06)
        case 4...7: return vocabSkin.palette.accent.opacity(0.12)
        case 8...14: return vocabSkin.palette.accent.opacity(0.18)
        default: return vocabSkin.palette.accent.opacity(0.24)
        }
    }
}

private struct DayCell: Identifiable {
    let id: String
    let dayNumber: Int
    let dayKey: String?
    let isToday: Bool
}
