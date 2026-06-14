#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `PodcastHomeView` surface.
///
/// `PodcastHomeView` is `@Query`-backed (`PodcastSeries` filtered by
/// `!isSoftDeleted`, plus `PodcastProgress`) and normally runs a network
/// auto-sync `.task`. `CatalogTaskPolicy.disabled` skips that task so the view
/// renders purely off the seeded in-memory store. Series, episodes, and auth
/// state come from UI World `runtimePodcast.*` / `auth.*` seeds.
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

    var runtimePodcastIDs: [UIWorldRuntimePodcastFixtureID] {
        switch self {
        case .populated, .noProgress:
            return [.playablePreview, .tieredCatalog]
        case .single:
            return [.playablePreview]
        case .empty:
            return []
        }
    }

    var includesContinueProgress: Bool {
        switch self {
        case .populated, .single:
            return true
        case .noProgress, .empty:
            return false
        }
    }
}

// MARK: - Scene harness

private struct PodcastHomeScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth

    init(fixture: PodcastHomeFixture) {
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.container = Self.makeContainer(for: fixture)
        self.auth = Self.makeAuth(from: authSeed)
    }

    var body: some View {
        AppThemeContainer {
            PodcastHomeView()
                .modelContainer(container)
                .environment(\.authManager, auth)
                .environment(\.catalogTaskPolicy, .disabled)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    private static func makeContainer(for fixture: PodcastHomeFixture) -> ModelContainer {
        do {
            let container = try ModelContainer(
                for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            for (index, fixtureID) in fixture.runtimePodcastIDs.enumerated() {
                let seed = FixtureDatasetStore.requireRuntimePodcastSeed(for: fixtureID)
                let episodes = materialize(seed: seed, index: index, into: container.mainContext)
                if fixture.includesContinueProgress, let episode = episodes.first {
                    insertProgress(episode: episode, played: min(episode.durationSec / 3, 612), into: container.mainContext)
                }
            }
            try container.mainContext.save()
            return container
        } catch {
            preconditionFailure("Failed to materialize UI World runtimePodcast seeds for PodcastHomeViewScenarios.\(fixture): \(error)")
        }
    }

    @discardableResult
    private static func materialize(
        seed: UIWorldRuntimePodcastSeed,
        index: Int,
        into context: ModelContext
    ) -> [PodcastEpisode] {
        let series = PodcastSeries(
            remoteId: seed.seriesRemoteId,
            title: seed.seriesTitle,
            hostNames: seed.hostNames
        )
        series.color = seed.color
        series.coverPattern = seed.coverPattern
        series.episodeCount = seed.episodes.count
        series.totalDurationSec = seed.durationSec
        series.sortOrder = seed.sortOrder + index
        series.isFollowed = index == 0
        context.insert(series)

        var episodes: [PodcastEpisode] = []
        for episodeSeed in seed.episodes {
            let episode = PodcastEpisode(
                remoteId: episodeSeed.remoteId,
                episodeNumber: episodeSeed.episodeNumber,
                title: episodeSeed.title,
                durationSec: episodeSeed.durationSec
            )
            episode.audioAvailable = episodeSeed.audioAvailable
            episode.previewAvailable = episodeSeed.previewAvailable
            episode.previewDurationSec = episodeSeed.previewDurationSec
            episode.subtitleAvailable = episodeSeed.subtitleAvailable
            episode.series = series
            context.insert(episode)
            episodes.append(episode)
        }
        return episodes
    }

    private static func insertProgress(
        episode: PodcastEpisode,
        played: Double,
        into context: ModelContext
    ) {
        let progress = PodcastProgress(
            episodeRemoteId: episode.remoteId,
            lastPlayedTime: played,
            completed: false
        )
        context.insert(progress)
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        guard seed.isLoggedIn else {
            preconditionFailure("UI World auth.signedIn must be logged in for PodcastHomeViewScenarios")
        }
        return CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email
        )
    }
}
#endif
