#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `PodcastHomeView` surface.
///
/// `PodcastHomeView` is `@Query`-backed (`PodcastSeries` filtered by
/// `!isSoftDeleted`, plus `PodcastProgress`) and normally runs a network
/// auto-sync `.task`. `CatalogTaskPolicy.disabled` skips that task so the view
/// renders purely off the seeded in-memory store.
///
/// `PodcastHomePhase.resolve` is `seriesCount`-first: any seeded series ⇒
/// `.content` (grid + 「繼續收聽」 shelf when un-completed progress exists); an
/// empty store ⇒ `.empty`. The env-default services (`KGService`, toast,
/// `authManager`) are `MainActor`-constructed, so each scene seeds its container
/// and renders inside a `@MainActor` View body (mirrors `ArchivedVocabScene`).
enum PodcastHomeViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Home View") {
            Scenario("Content / Populated", layout: .fill) {
                PodcastHomeScene(fixture: .populated)
            }
            Scenario("Content / Single series", layout: .fill) {
                PodcastHomeScene(fixture: .single)
            }
            Scenario("Content / No continue shelf", layout: .fill) {
                PodcastHomeScene(fixture: .noProgress)
            }
            Scenario("Empty", layout: .fill) {
                PodcastHomeScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum PodcastHomeFixture {
    case populated
    case single
    case noProgress
    case empty
}

// MARK: - Scene harness

/// `@MainActor` body: seeds a fresh in-memory `ModelContainer` (the `@Model`
/// inits touch `@MainActor`) and renders the real `PodcastHomeView` with
/// auto-sync skipped. Series carry `color`/`coverPattern`/`episodeCount`/
/// `totalDurationSec`; un-completed `PodcastProgress` with `lastPlayedTime > 0`
/// drives the 「繼續收聽」 shelf via `continueItems`.
private struct PodcastHomeScene: View {
    let container: ModelContainer

    init(fixture: PodcastHomeFixture) {
        let container = try! ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext
        Self.seed(fixture, into: context)
        try? context.save()
        self.container = container
    }

    var body: some View {
        AppThemeContainer {
            PodcastHomeView()
                .modelContainer(container)
                .environment(\.catalogTaskPolicy, .disabled)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    private static let palette = ["#4A90D9", "#E0719A", "#3FB68B", "#F2A65A", "#7E6CCB"]
    private static let patterns: [NotebookCoverPattern] = [.waves, .dots, .grid, .circles, .lines]

    private static func seed(_ fixture: PodcastHomeFixture, into context: ModelContext) {
        switch fixture {
        case .empty:
            return

        case .single:
            let (series, episodes) = makeSeries(
                index: 0,
                title: "Atomic Habits Unpacked",
                hosts: ["Ava Chen"],
                episodeTitles: ["The 1% Rule", "Identity-Based Habits", "Make It Obvious"],
                followed: true,
                context: context
            )
            insertProgress(episode: episodes[1], played: 612, completed: false, into: context)
            _ = series

        case .noProgress:
            seedCatalog(into: context)
            // Intentionally no PodcastProgress → continueItems empty → grid only.

        case .populated:
            let all = seedCatalog(into: context)
            // Two un-completed resumes (newest-updated first in the shelf) plus
            // one completed entry that must be filtered OUT of the shelf.
            insertProgress(episode: all[0].1[1], played: 612, completed: false, into: context)
            insertProgress(episode: all[1].1[0], played: 1700, completed: false, into: context)
            insertProgress(episode: all[2].1[0], played: 1832, completed: true, into: context)
        }
    }

    @discardableResult
    private static func seedCatalog(
        into context: ModelContext
    ) -> [(PodcastSeries, [PodcastEpisode])] {
        let specs: [(String, [String], [String], Bool)] = [
            ("Atomic Habits Unpacked", ["Ava Chen"],
             ["The 1% Rule", "Identity-Based Habits", "Make It Obvious"], true),
            ("Finding Flow: The Science of Optimal Experience",
             ["Mihaly Csikszentmihalyi", "Alexandra Featherstone"],
             ["What Is Flow", "Autotelic Personality"], true),
            ("Deep Work in a Distracted World", ["Leo Park"],
             ["Attention Residue", "The Shutdown Ritual", "Embracing Boredom", "Drain the Shallows"], false),
            ("Hidden Hand", ["Maya Lin"],
             ["Origins", "Markets & Myths"], false),
        ]
        return specs.enumerated().map { idx, spec in
            makeSeries(
                index: idx,
                title: spec.0,
                hosts: spec.1,
                episodeTitles: spec.2,
                followed: spec.3,
                context: context
            )
        }
    }

    private static func makeSeries(
        index: Int,
        title: String,
        hosts: [String],
        episodeTitles: [String],
        followed: Bool,
        context: ModelContext
    ) -> (PodcastSeries, [PodcastEpisode]) {
        let series = PodcastSeries(remoteId: "series-\(index)", title: title, hostNames: hosts)
        series.color = palette[index % palette.count]
        series.coverPattern = patterns[index % patterns.count].rawValue
        series.episodeCount = episodeTitles.count
        series.sortOrder = index
        series.isFollowed = followed
        context.insert(series)

        var episodes: [PodcastEpisode] = []
        var total: Double = 0
        for (epIdx, epTitle) in episodeTitles.enumerated() {
            let duration = Double(1500 + epIdx * 332)
            total += duration
            let ep = PodcastEpisode(
                remoteId: "series-\(index)_ep_\(epIdx + 1)",
                episodeNumber: epIdx + 1,
                title: epTitle,
                durationSec: duration
            )
            ep.audioAvailable = true
            ep.series = series
            context.insert(ep)
            episodes.append(ep)
        }
        series.totalDurationSec = total
        return (series, episodes)
    }

    private static func insertProgress(
        episode: PodcastEpisode,
        played: Double,
        completed: Bool,
        into context: ModelContext
    ) {
        let progress = PodcastProgress(
            episodeRemoteId: episode.remoteId,
            lastPlayedTime: played,
            completed: completed
        )
        context.insert(progress)
    }
}
#endif
