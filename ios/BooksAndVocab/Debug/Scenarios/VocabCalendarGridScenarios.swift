#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `VocabCalendarGrid`.
///
/// The grid is a pure presentational component: it takes a displayed month,
/// a `[dayKey: activityCount]` map, and a selected-day binding. All fixtures
/// here are synthetic so Catalog / Snapshot stay deterministic regardless of
/// the real review history. Day keys are produced with the same
/// `AppDateFormatters.dayKey` the component uses, so activity dots / cell fills
/// land on the intended days.
enum VocabCalendarGridScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocab Calendar") {
            // 一個月份的密集活動：覆蓋全部 intensity 階梯（dot + cellFill），
            // 證明色階分層與 Monday-first 排版。
            Scenario("Active month", layout: .fillH) {
                VocabCalendarGridScene(fixture: .activeMonth)
            }
            // 選中某一天：驗證 selected cell 的 mutedFill 背景與 primaryText。
            Scenario("Day selected", layout: .fillH) {
                VocabCalendarGridScene(fixture: .daySelected)
            }
            // 高強度壓力：所有天都是 15+ 活動，逼出最深的 cellFill / dot。
            Scenario("Heavy intensity", layout: .fillH) {
                VocabCalendarGridScene(fixture: .heavyIntensity)
            }
            // 空月份：沒有任何活動，只有日期數字與格線（empty state）。
            Scenario("No activity", layout: .fillH) {
                VocabCalendarGridScene(fixture: .noActivity)
            }
            // 含 today 的當月：驗證 today cell 的 chartHighlight 文字色。
            Scenario("Current month with today", layout: .fillH) {
                VocabCalendarGridScene(fixture: .currentMonth)
            }
        }
    }
}

private struct VocabCalendarGridScene: View {
    enum Fixture {
        case activeMonth
        case daySelected
        case heavyIntensity
        case noActivity
        case currentMonth
    }

    let fixture: Fixture

    @State private var selectedDay: String?

    private static let calendar = Calendar.current
    private static let formatter = AppDateFormatters.dayKey

    var body: some View {
        let config = makeConfig()
        return AppThemeContainer {
            VocabCalendarGrid(
                displayedMonth: config.month,
                activityMap: config.activity,
                selectedDay: $selectedDay
            )
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
        .onAppear { selectedDay = config.initialSelection }
    }

    private struct Config {
        let month: Date
        let activity: [String: Int]
        let initialSelection: String?
    }

    private func makeConfig() -> Config {
        switch fixture {
        case .activeMonth:
            let month = Self.fixedMonth()
            return Config(month: month, activity: Self.gradientActivity(in: month), initialSelection: nil)
        case .daySelected:
            let month = Self.fixedMonth()
            let activity = Self.gradientActivity(in: month)
            return Config(month: month, activity: activity, initialSelection: Self.dayKey(in: month, day: 15))
        case .heavyIntensity:
            let month = Self.fixedMonth()
            return Config(month: month, activity: Self.constantActivity(in: month, count: 20), initialSelection: nil)
        case .noActivity:
            let month = Self.fixedMonth()
            return Config(month: month, activity: [:], initialSelection: nil)
        case .currentMonth:
            return Config(month: Date(), activity: Self.gradientActivity(in: Date()), initialSelection: nil)
        }
    }

    /// Deterministic month (2024-03) so snapshots are stable across runs.
    private static func fixedMonth() -> Date {
        var comps = DateComponents()
        comps.year = 2024
        comps.month = 3
        comps.day = 1
        return calendar.date(from: comps) ?? Date()
    }

    private static func dayKey(in month: Date, day: Int) -> String? {
        var comps = calendar.dateComponents([.year, .month], from: month)
        comps.day = day
        return calendar.date(from: comps).map { formatter.string(from: $0) }
    }

    /// Spreads counts across every intensity band (1-3, 4-7, 8-14, 15+),
    /// skipping every fourth day so empty cells are also represented.
    private static func gradientActivity(in month: Date) -> [String: Int] {
        var map: [String: Int] = [:]
        guard let first = calendar.date(from: calendar.dateComponents([.year, .month], from: month)),
              let range = calendar.range(of: .day, in: .month, for: first) else { return map }
        for day in range where day % 4 != 0 {
            if let key = dayKey(in: month, day: day) {
                map[key] = ((day * 2) % 18) + 1
            }
        }
        return map
    }

    private static func constantActivity(in month: Date, count: Int) -> [String: Int] {
        var map: [String: Int] = [:]
        guard let first = calendar.date(from: calendar.dateComponents([.year, .month], from: month)),
              let range = calendar.range(of: .day, in: .month, for: first) else { return map }
        for day in range {
            if let key = dayKey(in: month, day: day) {
                map[key] = count
            }
        }
        return map
    }
}

#endif
