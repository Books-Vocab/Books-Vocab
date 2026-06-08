#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the podcast streaming-shelf cards.
///
/// `PodcastSeriesCard` (poster-style series tile) and `PodcastContinueRailCard`
/// (resume-rail card) are distinct podcast-feature components from the series
/// header (`Podcast Hero`) and the series-hero CTA (`Podcast Continue Card`).
/// They previously rode inside the `Bookshelf` building-block grab-bag; relocated
/// here so they live on the podcast slice they belong to.
enum PodcastShelfCardsScenarios {
    static func register(in playbook: Playbook) {
        // PodcastSeriesCard streaming-meta stress baselines:
        // the `主持人 · N 集` meta line is single-line tail-truncated, so the
        // long-host / multi-host / a11y3 cases prove card height stays uniform.
        playbook.addScenarios(of: "Podcast Series Card") {
            Scenario("Normal", layout: .compressed) {
                PodcastSeriesCardScene(title: "Atomic Habits Unpacked", hosts: ["Ava Chen"], count: 7)
            }
            Scenario("Long host", layout: .compressed) {
                PodcastSeriesCardScene(
                    title: "Finding Flow: The Science of Optimal Experience",
                    hosts: ["Mihaly Csikszentmihalyi", "Alexandra Penultimate-Featherstonehaugh"],
                    count: 24
                )
            }
            Scenario("Narrow", layout: .compressed) {
                PodcastSeriesCardScene(title: "Let Them, Let Me", hosts: ["Leo Park", "Ava Chen"], count: 8, width: 120)
            }
            Scenario("A11y3", layout: .compressed) {
                PodcastSeriesCardScene(title: "Hidden Hand", hosts: ["Leo Park"], count: 12)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }

        // PodcastContinueRailCard streaming-shelf 卡：固定寬，
        // resume/no-progress/長標題/大時數/a11y3 證明卡高一致 + 單行截斷 + clock
        // monospacedDigit 對齊。
        playbook.addScenarios(of: "Podcast Continue Rail Card") {
            Scenario("Resume", layout: .compressed) {
                PodcastContinueRailCardScene(seriesTitle: "Atomic Habits Unpacked", epTitle: "On Deep Work", epNumber: 2, duration: 1832, played: 612)
            }
            Scenario("No progress", layout: .compressed) {
                PodcastContinueRailCardScene(seriesTitle: "Atomic Habits Unpacked", epTitle: "The Comfort Crisis", epNumber: 1, duration: 1832, played: nil)
            }
            Scenario("Long title", layout: .compressed) {
                PodcastContinueRailCardScene(seriesTitle: "Finding Flow: The Science of Optimal Experience", epTitle: "A Very Long Episode Title That Must Truncate Cleanly On One Line", epNumber: 12, duration: 5432, played: 1700)
            }
            Scenario("Large numbers", layout: .compressed) {
                PodcastContinueRailCardScene(seriesTitle: "The Long Haul", epTitle: "Marathon Session", epNumber: 8, duration: 12_345, played: 321)
            }
            Scenario("A11y3", layout: .compressed) {
                PodcastContinueRailCardScene(seriesTitle: "Hidden Hand", epTitle: "Origins", epNumber: 3, duration: 1832, played: 900)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// PodcastSeriesCard baseline harness. Model construction touches `@MainActor`
/// paths, so it lives in a `View` body.
private struct PodcastSeriesCardScene: View {
    let title: String
    let hosts: [String]
    let count: Int
    var width: CGFloat = 160

    var body: some View {
        let series = PodcastSeries(remoteId: "s-prev", title: title, hostNames: hosts)
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue
        series.episodeCount = count
        return AppThemeContainer {
            PodcastSeriesCard(series: series)
                .frame(width: width)
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

/// PodcastContinueRailCard baseline harness — model 構造同樣觸 `@MainActor` 路徑，
/// 故置於 `View` body。`played == nil` → 無進度卡。
private struct PodcastContinueRailCardScene: View {
    let seriesTitle: String
    let epTitle: String
    let epNumber: Int
    let duration: Double
    let played: Double?

    var body: some View {
        let series = PodcastSeries(remoteId: "s-prev", title: seriesTitle, hostNames: ["Ava Chen"])
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue
        let ep = PodcastEpisode(remoteId: "s-prev_ep_\(epNumber)", episodeNumber: epNumber, title: epTitle, durationSec: duration)
        let progress = played.map { PodcastProgress(episodeRemoteId: ep.remoteId, lastPlayedTime: $0) }
        return AppThemeContainer {
            PodcastContinueRailCard(episode: ep, series: series, progress: progress)
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif

#endif
