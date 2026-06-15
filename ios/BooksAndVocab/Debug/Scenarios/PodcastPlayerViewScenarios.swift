//
//  PodcastPlayerViewScenarios.swift
//  Books & Vocab
//
//  Catalog scenarios for `PodcastPlayerView` (the full-screen podcast player).
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the full `PodcastPlayerView` surface (播客播放器).
///
/// The player scenarios are seeded from UI World `runtimePodcast.*` and
/// `auth.*` fixtures. The preview-player case still uses the DEBUG-only catalog
/// preview seam to avoid AVPlayer/network work in snapshots, but the duration,
/// episode row, auth state, and subtitle SRT all come from the manifest.
enum PodcastPlayerViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Player View") {
            Scenario("Preview episode · player", layout: .fill) {
                PodcastPlayerViewScene(fixture: .previewPlayer)
            }
            Scenario("Locked · sign-in gate", layout: .fill) {
                PodcastPlayerViewScene(fixture: .lockedGate)
            }
        }
    }
}

// MARK: - Fixtures

private enum PodcastPlayerFixture {
    case previewPlayer
    case lockedGate

    var runtimePodcastID: UIWorldRuntimePodcastFixtureID {
        switch self {
        case .previewPlayer:
            return .playablePreview
        case .lockedGate:
            return .tieredCatalog
        }
    }

    var authID: UIWorldAuthFixtureID {
        switch self {
        case .previewPlayer:
            return .signedIn
        case .lockedGate:
            return .guest
        }
    }
}

// MARK: - Scene harness

private struct PodcastPlayerViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let episodeId: String
    let preview: PodcastPlayerCatalogPreview?

    init(fixture: PodcastPlayerFixture) {
        let seed = FixtureDatasetStore.requireRuntimePodcastSeed(for: fixture.runtimePodcastID)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: fixture.authID)
        let materialized = Self.makeContainer(from: seed, fixture: fixture)
        self.container = materialized.container
        self.episodeId = materialized.episodeId
        self.auth = Self.makeAuth(from: authSeed)
        self.preview = fixture == .previewPlayer
            ? .init(durationSec: seed.durationSec, currentSec: 6.09, subtitleSRT: materialized.subtitleSRT)
            : nil
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                player
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private var player: some View {
        PodcastPlayerView(episodeId: episodeId)
            .environment(\.podcastPlayerCatalogPreview, preview)
    }

    // MARK: Seeding

    private struct MaterializedPodcastPlayer {
        let container: ModelContainer
        let episodeId: String
        let subtitleSRT: String
    }

    private static func makeContainer(
        from seed: UIWorldRuntimePodcastSeed,
        fixture: PodcastPlayerFixture
    ) -> MaterializedPodcastPlayer {
        do {
            let container = try ModelContainer(
                for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self, VocabularyEntry.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let subtitleURL = try FixtureDatasetStore.requireInstalledAssetURL(ref: seed.subtitleAssetRef)
            let subtitleSRT = try String(contentsOf: subtitleURL, encoding: .utf8)
            let series = try UITestFixtureSeed.makeRuntimePodcastSeries(
                from: seed,
                document: FixtureDatasetStore.requireDocument(),
                owner: "runtimePodcast.\(fixture.runtimePodcastID.rawValue)"
            )
            container.mainContext.insert(series)

            let episodeSeed = try selectedEpisodeSeed(from: seed, fixture: fixture)
            let episode = try UITestFixtureSeed.makeRuntimePodcastEpisode(
                from: episodeSeed,
                series: series,
                inlineSubtitle: subtitleSRT
            )
            container.mainContext.insert(episode)
            try container.mainContext.save()
            return .init(container: container, episodeId: episode.remoteId, subtitleSRT: subtitleSRT)
        } catch {
            preconditionFailure("Failed to materialize UI World runtimePodcast.\(seed.seriesRemoteId) for PodcastPlayerViewScenarios: \(error)")
        }
    }

    private static func selectedEpisodeSeed(
        from seed: UIWorldRuntimePodcastSeed,
        fixture: PodcastPlayerFixture
    ) throws -> UIWorldRuntimePodcastEpisodeSeed {
        switch fixture {
        case .previewPlayer:
            guard let episode = seed.episodes.first(where: { $0.previewAvailable }) else {
                throw PodcastPlayerFixtureError.missingPreviewEpisode(seed.seriesRemoteId)
            }
            return episode
        case .lockedGate:
            guard let episode = seed.episodes.first(where: { !$0.previewAvailable }) else {
                throw PodcastPlayerFixtureError.missingLockedEpisode(seed.seriesRemoteId)
            }
            return episode
        }
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email
        )
    }
}

private enum PodcastPlayerFixtureError: Error {
    case missingPreviewEpisode(String)
    case missingLockedEpisode(String)
}
#endif
