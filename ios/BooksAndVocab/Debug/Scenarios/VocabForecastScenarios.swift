#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `VocabForecastChart` — the review schedule bar chart.
/// Feeds synthetic `StatsPresentation.ForecastBucket` points across happy,
/// stress (compact >14 buckets), sparse and empty states.
enum VocabForecastScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocab Forecast") {
            Scenario("7-day forecast", layout: .fillH) {
                ForecastScene(buckets: Self.buckets(counts: [12, 5, 8, 3, 6, 9, 4]))
            }
            Scenario("14-day forecast", layout: .fillH) {
                ForecastScene(buckets: Self.buckets(counts: [12, 5, 8, 3, 6, 9, 4, 2, 7, 1, 5, 3, 6, 2]))
            }
            Scenario("Compact (30 days)", layout: .fillH) {
                ForecastScene(buckets: Self.buckets(counts: (0..<30).map { ($0 * 7 + 3) % 13 }))
            }
            Scenario("Sparse — single spike", layout: .fillH) {
                ForecastScene(buckets: Self.buckets(counts: [18, 0, 0, 0, 0, 0, 0]))
            }
            Scenario("Empty — zero forecast", layout: .fillH) {
                ForecastScene(buckets: Self.buckets(counts: Array(repeating: 0, count: 14)))
            }
            Scenario("Large counts", layout: .fillH) {
                ForecastScene(buckets: Self.buckets(counts: [0, 644, 1024, 4096, 9999, 0, 207, 1144, 88, 0, 12, 2048, 512, 1]))
            }
        }
    }

    // MARK: - Fixtures

    private static func buckets(counts: [Int]) -> [StatsPresentation.ForecastBucket] {
        counts.enumerated().map { index, count in
            StatsPresentation.ForecastBucket(id: "d\(index)", label: "+\(index)d", count: count)
        }
    }
}

// MARK: - Scene harness

private struct ForecastScene: View {
    let buckets: [StatsPresentation.ForecastBucket]

    var body: some View {
        AppThemeContainer {
            VocabForecastChart(buckets: buckets)
                .frame(height: 160)
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
