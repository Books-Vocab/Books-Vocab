//
//  VocabCalendarGrid.swift
//  Books & Vocab
//
//  月曆格子元件，顯示每日複習活動色階。
//

import SwiftUI

struct VocabCalendarGrid: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let displayedMonth: Date
    let activityMap: [String: Int]
    @Binding var selectedDay: String?

    private static let calendar = Calendar.current
    private static let dayFormatter = AppDateFormatters.dayKey

    // Locale-aware, Monday-first (matches the Monday-start day grid below).
    private let weekdaySymbols = LocaleAwareFormatter.shared.mondayFirstWeekdaySymbols(short: true)
    private let columns = Array(repeating: GridItem(.flexible(), spacing: AppSpacing.s1), count: 7)
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
        VStack(spacing: appSkin.spacing.microGap) {
            // Weekday header
            LazyVGrid(columns: columns, spacing: AppSpacing.s1) {
                ForEach(Array(weekdaySymbols.enumerated()), id: \.offset) { _, symbol in
                    Text(symbol)
                        .font(appSkin.typography.monoLabel)
                        .foregroundStyle(appSkin.palette.quaternaryText)
                        .frame(maxWidth: .infinity)
                }
            }

            // Day grid
            LazyVGrid(columns: columns, spacing: AppSpacing.s1) {
                ForEach(monthDays) { cell in
                    if cell.dayNumber == 0 {
                        Color.clear
                            .aspectRatio(1, contentMode: .fit)
                            .frame(maxWidth: .infinity)
                    } else {
                        dayView(cell)
                    }
                }
            }
        }
        .enableInjection()
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
                    .font(appSkin.typography.caption)
                    .foregroundStyle(
                        cell.isToday ? AppColors.chartHighlight :
                        isSelected ? appSkin.palette.primaryText :
                        appSkin.palette.secondaryText
                    )

                // Activity dot
                Circle()
                    .fill(count > 0 ? dotColor(count) : Color.clear)
                    .frame(width: 5, height: 5)
            }
            .frame(maxWidth: .infinity)
            .aspectRatio(1, contentMode: .fit)
            .background(
                RoundedRectangle(cornerRadius: appSkin.radii.tiny, style: .continuous)
                    .fill(isSelected ? appSkin.palette.mutedFill : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: appSkin.radii.tiny, style: .continuous)
                    .fill(count > 0 ? cellFill(count) : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: appSkin.radii.tiny, style: .continuous)
                    .stroke(appSkin.palette.cardBorder.opacity(0.5), lineWidth: 0.5)
            )
        }
        .buttonStyle(.plain)
    }

    private func dotColor(_ count: Int) -> Color {
        switch count {
        case 1...3: return AppColors.chartHighlight.opacity(0.5)
        case 4...7: return AppColors.chartHighlight.opacity(0.75)
        default: return AppColors.chartHighlight
        }
    }

    private func cellFill(_ count: Int) -> Color {
        // 提高低活動 cell 的 opacity（0.06 對米色卡片背景對比過低，
        // 導致連續低活動日視覺融合成 pill；intensity 由底部 dot 區分）
        switch count {
        case 1...3: return AppColors.chartHighlight.opacity(0.12)
        case 4...7: return AppColors.chartHighlight.opacity(0.16)
        case 8...14: return AppColors.chartHighlight.opacity(0.20)
        default: return AppColors.chartHighlight.opacity(0.26)
        }
    }
}

private struct DayCell: Identifiable {
    let id: String
    let dayNumber: Int
    let dayKey: String?
    let isToday: Bool
}

#Preview("VocabCalendarGrid") {
    @Previewable @State var selectedDay: String?

    let cal = Calendar.current
    let formatter = AppDateFormatters.dayKey
    let month = Date()
    var activity: [String: Int] = [:]
    if let firstOfMonth = cal.date(from: cal.dateComponents([.year, .month], from: month)),
       let range = cal.range(of: .day, in: .month, for: firstOfMonth) {
        for day in range where day % 3 != 0 {
            var comps = cal.dateComponents([.year, .month], from: month)
            comps.day = day
            if let date = cal.date(from: comps) {
                activity[formatter.string(from: date)] = (day % 11) + 1
            }
        }
    }

    return AppThemeContainer {
        VocabCalendarGrid(
            displayedMonth: month,
            activityMap: activity,
            selectedDay: $selectedDay
        )
        .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}
