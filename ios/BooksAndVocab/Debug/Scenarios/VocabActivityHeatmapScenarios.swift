#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `VocabActivityHeatmap` — GitHub-style learning activity grid.
/// Driven entirely by synthetic `[String: Int]` (yyyy-MM-dd -> count) fixtures.
enum VocabActivityHeatmapScenarios {
    static let projectionClock: StatsProjectionClock = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? calendar.timeZone
        let components = DateComponents(
            calendar: calendar,
            timeZone: calendar.timeZone,
            year: 2026,
            month: 6,
            day: 1,
            hour: 12
        )
        guard let now = calendar.date(from: components) else {
            preconditionFailure("VocabActivityHeatmapScenarios requires a valid fixed UTC anchor")
        }
        return StatsProjectionClock(now: now, calendar: calendar)
    }()

    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocab Heatmap") {
            Scenario("Dense · graded", layout: .compressed) {
                HeatmapScene(
                    activity: Self.gradedActivity(),
                    thresholds: [2, 5, 9],
                    weeks: 20,
                    projectionClock: Self.projectionClock
                )
            }
            Scenario("Sparse", layout: .compressed) {
                HeatmapScene(
                    activity: Self.sparseActivity(),
                    thresholds: [2, 5, 9],
                    weeks: 20,
                    projectionClock: Self.projectionClock
                )
            }
            Scenario("No thresholds (flat level)", layout: .compressed) {
                HeatmapScene(
                    activity: Self.gradedActivity(),
                    thresholds: [],
                    weeks: 20,
                    projectionClock: Self.projectionClock
                )
            }
            Scenario("Empty", layout: .compressed) {
                HeatmapScene(
                    activity: [:],
                    thresholds: [2, 5, 9],
                    weeks: 20,
                    projectionClock: Self.projectionClock
                )
            }
            Scenario("Short range (8 weeks)", layout: .compressed) {
                HeatmapScene(
                    activity: Self.gradedActivity(),
                    thresholds: [2, 5, 9],
                    weeks: 8,
                    projectionClock: Self.projectionClock
                )
            }
        }
    }

    // MARK: - Fixtures

    /// Every non-multiple-of-4 day in the last 120 days, counts cycling 1...13
    /// to exercise all four intensity levels.
    private static func gradedActivity() -> [String: Int] {
        var activity: [String: Int] = [:]
        for offset in 0..<120 where offset % 4 != 0 {
            if let date = projectionClock.date(byAdding: .day, value: -offset, to: projectionClock.now) {
                activity[projectionClock.dayKey(date)] = (offset % 13) + 1
            }
        }
        return activity
    }

    /// Occasional low-count days — exercises the mostly-empty grid path.
    private static func sparseActivity() -> [String: Int] {
        var activity: [String: Int] = [:]
        for offset in stride(from: 0, to: 120, by: 11) {
            if let date = projectionClock.date(byAdding: .day, value: -offset, to: projectionClock.now) {
                activity[projectionClock.dayKey(date)] = 1
            }
        }
        return activity
    }
}

// MARK: - Scene harness

private struct HeatmapScene: View {
    let activity: [String: Int]
    let thresholds: [Int]
    let weeks: Int
    let projectionClock: StatsProjectionClock

    var body: some View {
        AppThemeContainer {
            VocabActivityHeatmap(
                activity: activity,
                thresholds: thresholds,
                weeks: weeks
            )
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
        .environment(\.statsProjectionClock, projectionClock)
    }
}
#endif
