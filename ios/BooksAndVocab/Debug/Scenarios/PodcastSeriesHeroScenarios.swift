#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for `PodcastSeriesHero` — the streaming-style series header
/// (blurred-artwork backdrop + floating cover + title + host/length meta).
///
/// The hero is pure presentation driven by a single `PodcastSeries`. Its meta
/// line (`主持人 · N 集 · 共 X 小時 Y 分`) assembles conditionally, so the
/// scenarios exercise: full meta, multi-host stress (title/meta wrapping),
/// meta-less fresh series (no hosts / no episodes), short single-segment meta,
/// and an a11y3 baseline to prove the multi-line title/meta stays bounded.
enum PodcastSeriesHeroScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Hero") {
            Scenario("Full meta", layout: .fill) {
                PodcastSeriesHeroScene(
                    title: "Atomic Habits Unpacked",
                    hosts: ["Ava Chen", "Leo Park"],
                    episodeCount: 7,
                    totalDurationSec: 7 * 932
                )
            }
            Scenario("Long title · multi host", layout: .fill) {
                PodcastSeriesHeroScene(
                    title: "Finding Flow: The Science of Optimal Experience",
                    hosts: ["Mihaly Csikszentmihalyi", "Alexandra Penultimate-Featherstonehaugh"],
                    episodeCount: 24,
                    totalDurationSec: 24 * 1_840
                )
            }
            Scenario("Fresh · no meta", layout: .fill) {
                PodcastSeriesHeroScene(
                    title: "The Comfort Crisis",
                    hosts: [],
                    episodeCount: 0,
                    totalDurationSec: 0
                )
            }
            Scenario("Episodes only", layout: .fill) {
                PodcastSeriesHeroScene(
                    title: "Hidden Hand",
                    hosts: [],
                    episodeCount: 3,
                    totalDurationSec: 0
                )
            }
            Scenario("A11y3", layout: .fill) {
                PodcastSeriesHeroScene(
                    title: "Let Them, Let Me",
                    hosts: ["Leo Park", "Ava Chen"],
                    episodeCount: 12,
                    totalDurationSec: 12 * 1_205
                )
                .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// `PodcastSeriesHero` baseline harness. `PodcastSeries` construction touches
/// `@MainActor` paths, so it lives in a `View` body (same reason as the
/// `PodcastSeriesCardScene` harness in `PodcastShelfCardsScenarios`).
private struct PodcastSeriesHeroScene: View {
    let title: String
    let hosts: [String]
    let episodeCount: Int
    let totalDurationSec: Double

    var body: some View {
        let series = PodcastSeries(remoteId: "s-hero", title: title, hostNames: hosts)
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue
        series.episodeCount = episodeCount
        series.totalDurationSec = totalDurationSec
        return AppThemeContainer {
            PodcastSeriesHero(series: series)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif

#endif
