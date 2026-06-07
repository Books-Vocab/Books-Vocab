#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `ReviewCalendarPresenter`.
///
/// The presenter is fully `@Query`-driven (SwiftData), so each scenario seeds a
/// dedicated in-memory `ModelContainer` with synthetic `ReviewRecord`s and renders
/// the real view against it. Seeding happens inside a `@MainActor` View scene
/// (`mainContext` insert is main-actor isolated).
enum ReviewCalendarScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Review Calendar Presenter") {
            Scenario("Today populated", layout: .fill) {
                ReviewCalendarScene(seed: .todayMix)
            }
            Scenario("Heavy month streak", layout: .fill) {
                ReviewCalendarScene(seed: .heavyMonth)
            }
            Scenario("Empty DB", layout: .fill) {
                ReviewCalendarScene(seed: .empty)
            }
        }
    }
}

// MARK: - Seed definition

private enum ReviewCalendarSeed {
    case todayMix
    case heavyMonth
    case empty

    /// Builds `(word, feedback, dayOffset, hour, minute)` tuples relative to "now".
    var records: [(word: String, feedback: Int, dayOffset: Int, hour: Int, minute: Int)] {
        switch self {
        case .empty:
            return []
        case .todayMix:
            return [
                ("serendipity", 1, 0, 9, 12),
                ("ephemeral", 0, 0, 9, 18),
                ("quintessential", 1, 0, 14, 3),
                ("ubiquitous", 1, 0, 20, 41),
                ("obfuscate", 0, 0, 21, 7),
                // some history so the calendar grid shows activity
                ("luminous", 1, -1, 8, 0),
                ("vex", 0, -3, 19, 30),
                ("candor", 1, -7, 11, 11),
            ]
        case .heavyMonth:
            var out: [(String, Int, Int, Int, Int)] = []
            let words = ["aberration", "benevolent", "cacophony", "deference",
                         "elucidate", "fastidious", "garrulous", "harangue"]
            // dense activity across the trailing 28 days
            for day in 0..<28 {
                let count = (day % 4) + 1
                for k in 0..<count {
                    let w = words[(day + k) % words.count]
                    out.append((w, (day + k) % 3 == 0 ? 0 : 1, -day, 8 + k, k * 7))
                }
            }
            return out
        }
    }
}

// MARK: - Scene harness
// Seeds mainContext in `init`; kept nonisolated so the nonisolated Scenario
// closure can construct it. Safe because Playbook renders on the main thread
// (marking the struct @MainActor would block the Scenario-closure call).

private struct ReviewCalendarScene: View {
    let seed: ReviewCalendarSeed
    private let container: ModelContainer

    init(seed: ReviewCalendarSeed) {
        self.seed = seed
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        // ReviewRecord plus siblings the presenter's container universe expects.
        let container = try! ModelContainer(
            for: ReviewRecord.self,
            configurations: config
        )
        let context = container.mainContext
        let cal = Calendar.current
        let now = Date()
        for r in seed.records {
            let base = cal.date(byAdding: .day, value: r.dayOffset, to: now) ?? now
            var comps = cal.dateComponents([.year, .month, .day], from: base)
            comps.hour = r.hour
            comps.minute = r.minute
            let when = cal.date(from: comps) ?? base
            context.insert(
                ReviewRecord(
                    word: r.word,
                    entryID: nil,
                    feedback: r.feedback,
                    reviewedAt: when
                )
            )
        }
        self.container = container
    }

    var body: some View {
        AppThemeContainer {
            ReviewCalendarPresenter()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
