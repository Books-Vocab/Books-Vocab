//
//  PodcastEpisodeListViewScenarios.swift
//  Books & Vocab
//
//  Catalog scenarios for `PodcastEpisodeListView` (series detail + episode list).
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the full `PodcastEpisodeListView` surface (播客單集列表).
///
/// The view takes a `seriesId` and hydrates from the store in
/// `.task(id: seriesId) { reloadFromStore() }` — an explicit `modelContext.fetch`
/// (no `@Query`, no network), so seeding a fresh in-memory store with the series +
/// its episodes renders the populated / empty list deterministically. A logged-in
/// `CatalogPreviewAuth` is injected (the follow toggle + access tier read auth);
/// wrapped in a `NavigationStack` so the toolbar follow button has a bar.
enum PodcastEpisodeListViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Episode List View") {
            Scenario("Populated · series + episodes", layout: .fill) {
                PodcastEpisodeListViewScene(fixture: .tieredCatalog)
            }
            Scenario("Empty · no episodes yet", layout: .fill) {
                PodcastEpisodeListViewScene(fixture: .playablePreview, episodeLimit: 0)
            }
        }
    }
}

// MARK: - Scene harness

private struct PodcastEpisodeListViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let seriesId: String

    init(fixture: UIWorldRuntimePodcastFixtureID, episodeLimit: Int? = nil) {
        let seed = FixtureDatasetStore.requireRuntimePodcastSeed(for: fixture)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.container = Self.makeContainer(from: seed, episodeLimit: episodeLimit)
        self.auth = Self.makeAuth(from: authSeed)
        self.seriesId = seed.seriesRemoteId
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                PodcastEpisodeListView(seriesId: seriesId)
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func makeContainer(
        from seed: UIWorldRuntimePodcastSeed,
        episodeLimit: Int?
    ) -> ModelContainer {
        do {
            let container = try ModelContainer(
                for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let series = PodcastSeries(
                remoteId: seed.seriesRemoteId,
                title: seed.seriesTitle,
                hostNames: seed.hostNames
            )
            series.color = seed.color
            series.coverPattern = seed.coverPattern
            series.episodeCount = seed.episodes.count
            series.totalDurationSec = seed.durationSec
            series.sortOrder = seed.sortOrder
            container.mainContext.insert(series)

            let episodes = episodeLimit.map { Array(seed.episodes.prefix($0)) } ?? seed.episodes
            for episodeSeed in episodes {
                let episode = PodcastEpisode(
                    remoteId: episodeSeed.remoteId,
                    episodeNumber: episodeSeed.episodeNumber,
                    title: episodeSeed.title,
                    durationSec: episodeSeed.durationSec
                )
                episode.series = series
                episode.audioAvailable = episodeSeed.audioAvailable
                episode.previewAvailable = episodeSeed.previewAvailable
                episode.previewDurationSec = episodeSeed.previewDurationSec
                episode.subtitleAvailable = episodeSeed.subtitleAvailable
                container.mainContext.insert(episode)
            }
            try container.mainContext.save()
            return container
        } catch {
            preconditionFailure("Failed to materialize UI World runtimePodcast.\(seed.seriesRemoteId): \(error)")
        }
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        guard seed.isLoggedIn else {
            preconditionFailure("UI World auth.signedIn must be logged in for PodcastEpisodeListViewScenarios")
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
