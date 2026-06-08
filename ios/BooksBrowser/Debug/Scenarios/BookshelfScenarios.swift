#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the Bookshelf surface.
/// Reuses fixture-driven preview scenes so Preview / Catalog / Snapshot stay aligned.
enum BookshelfScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Bookshelf") {
            Scenario("Card / Progress", layout: .fill) {
                AppThemeContainer {
                    BookshelfCardFixtureScene(fixtureID: .progressCard)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Card / Placeholder", layout: .fill) {
                AppThemeContainer {
                    BookshelfCardFixtureScene(fixtureID: .placeholderCard)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            // NOTE: full-library states (Empty / With Books) live on the
            // "Bookshelf View" featureScreen surface (real `BookshelfView`).
            // This "Bookshelf" surface is building-block scoped: book cards +
            // podcast cards + loading. The former library fixtures here were a
            // byte-identical duplicate of Bookshelf View and were removed.
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    BookshelfLoadingPreview()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            // PodcastSeriesCard streaming-meta stress baselines (軸 B Phase 2):
            // the `主持人 · N 集` meta line is single-line tail-truncated, so the
            // long-host / multi-host / a11y3 cases prove card height stays uniform.
            Scenario("Podcast Card / Normal", layout: .fill) {
                PodcastSeriesCardScene(title: "Atomic Habits Unpacked", hosts: ["Ava Chen"], count: 7)
            }
            Scenario("Podcast Card / Long host", layout: .fill) {
                PodcastSeriesCardScene(
                    title: "Finding Flow: The Science of Optimal Experience",
                    hosts: ["Mihaly Csikszentmihalyi", "Alexandra Penultimate-Featherstonehaugh"],
                    count: 24
                )
            }
            Scenario("Podcast Card / Narrow", layout: .fill) {
                PodcastSeriesCardScene(title: "Let Them, Let Me", hosts: ["Leo Park", "Ava Chen"], count: 8, width: 120)
            }
            Scenario("Podcast Card / A11y3", layout: .fill) {
                PodcastSeriesCardScene(title: "Hidden Hand", hosts: ["Leo Park"], count: 12)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
            // PodcastContinueRailCard streaming-shelf 卡（軸 B Phase 3-2）：固定寬，
            // resume/no-progress/長標題/大時數/a11y3 證明卡高一致 + 單行截斷 + clock
            // monospacedDigit 對齊。
            Scenario("Podcast Continue / Resume", layout: .fill) {
                PodcastContinueRailCardScene(seriesTitle: "Atomic Habits Unpacked", epTitle: "On Deep Work", epNumber: 2, duration: 1832, played: 612)
            }
            Scenario("Podcast Continue / No progress", layout: .fill) {
                PodcastContinueRailCardScene(seriesTitle: "Atomic Habits Unpacked", epTitle: "The Comfort Crisis", epNumber: 1, duration: 1832, played: nil)
            }
            Scenario("Podcast Continue / Long title", layout: .fill) {
                PodcastContinueRailCardScene(seriesTitle: "Finding Flow: The Science of Optimal Experience", epTitle: "A Very Long Episode Title That Must Truncate Cleanly On One Line", epNumber: 12, duration: 5432, played: 1700)
            }
            Scenario("Podcast Continue / Large numbers", layout: .fill) {
                PodcastContinueRailCardScene(seriesTitle: "The Long Haul", epTitle: "Marathon Session", epNumber: 8, duration: 12_345, played: 321)
            }
            Scenario("Podcast Continue / A11y3", layout: .fill) {
                PodcastContinueRailCardScene(seriesTitle: "Hidden Hand", epTitle: "Origins", epNumber: 3, duration: 1832, played: 900)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// PodcastSeriesCard baseline harness. Model construction touches `@MainActor`
/// paths, so it lives in a `View` body (same reason as `BookshelfWithBooksScene`).
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
/// 故置於 `View` body（同 `PodcastSeriesCardScene`）。`played == nil` → 無進度卡。
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
