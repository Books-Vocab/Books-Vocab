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
                PodcastEpisodeListViewScene(fixture: .populated)
            }
            Scenario("Empty · no episodes yet", layout: .fill) {
                PodcastEpisodeListViewScene(fixture: .empty)
            }
        }
    }
}

// MARK: - Fixtures

private enum PodcastEpisodeListFixture {
    case populated
    case empty
}

// MARK: - Scene harness

private struct PodcastEpisodeListViewScene: View {
    static let seriesId = "series-atomic-habits"
    let container: ModelContainer
    let auth: CatalogPreviewAuth

    init(fixture: PodcastEpisodeListFixture) {
        let container = try! ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        Self.seed(fixture, into: container.mainContext)
        try? container.mainContext.save()
        self.container = container
        self.auth = CatalogPreviewAuth(
            isLoggedIn: true,
            userId: "catalog-podcast-user",
            token: "catalog-podcast-token",
            displayName: "Catalog Podcast User",
            userEmail: "catalog-podcast@example.com"
        )
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                PodcastEpisodeListView(seriesId: Self.seriesId)
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    private static func seed(_ fixture: PodcastEpisodeListFixture, into context: ModelContext) {
        let series = PodcastSeries(
            remoteId: seriesId,
            title: "Atomic Habits Unpacked",
            hostNames: ["Ava Chen", "Leo Park"]
        )
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue
        context.insert(series)

        guard fixture == .populated else { return }

        let episodes: [(Int, String, Double)] = [
            (1, "The Comfort Crisis", 1832),
            (2, "On Deep Work", 2014),
            (3, "Habit Stacking in Practice", 1567),
            (4, "Members-only Deep Dive", 2456),
        ]
        for (number, title, duration) in episodes {
            let ep = PodcastEpisode(remoteId: "\(seriesId)_ep_\(number)", episodeNumber: number, title: title, durationSec: duration)
            ep.series = series
            context.insert(ep)
        }
    }
}
#endif
