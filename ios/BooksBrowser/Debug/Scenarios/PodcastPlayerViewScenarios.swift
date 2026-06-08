//
//  PodcastPlayerViewScenarios.swift
//  BooksBrowser
//
//  Catalog scenarios for `PodcastPlayerView` (the full-screen podcast player).
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the full `PodcastPlayerView` surface (播客播放器).
///
/// `PodcastPlayerView(episodeId:)` resolves its episode/series via a synchronous
/// `modelContext.fetch` (no `@Query` race) and builds its `PodcastPlayerViewModel`
/// in `.task(id:)`. The audio load short-circuits when the episode has no
/// `audioURL` / `localAudioPath`, so seeding an audio-less episode renders the
/// real player chrome WITHOUT spinning up `AVPlayer` or hitting the network — the
/// player sits in its initial (loaded, paused-at-zero) state.
///
/// Two surface states:
/// - **Preview episode** → a preview-available episode is playable for any tier,
///   so `playerCore` (artwork + scrubber + transport) renders.
/// - **Locked gate** → a non-preview episode reached as a guest hits the
///   defense-in-depth `lockedGateView` (sign-in CTA) — audio is never loaded.
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
}

// MARK: - Scene harness

private struct PodcastPlayerViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let episodeId: String

    init(fixture: PodcastPlayerFixture) {
        let container = try! ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self, VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let (episodeId, loggedIn) = Self.seed(fixture, into: container.mainContext)
        try? container.mainContext.save()
        self.container = container
        self.episodeId = episodeId
        self.auth = CatalogPreviewAuth(isLoggedIn: loggedIn)
    }

    var body: some View {
        AppThemeContainer {
            PodcastPlayerView(episodeId: episodeId)
                .modelContainer(container)
                .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    /// Returns the episode remoteId to open + whether to inject a logged-in auth.
    private static func seed(_ fixture: PodcastPlayerFixture, into context: ModelContext) -> (String, Bool) {
        let series = PodcastSeries(
            remoteId: "series-deep-work",
            title: "Deep Work, Decoded",
            hostNames: ["Ava Chen", "Leo Park"]
        )
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue
        context.insert(series)

        // Audio-less episodes: the player loads its chrome but never starts AVPlayer.
        switch fixture {
        case .previewPlayer:
            let ep = PodcastEpisode(remoteId: "series-deep-work_ep_1", episodeNumber: 1, title: "The Comfort Crisis", durationSec: 1832)
            ep.previewAvailable = true
            ep.series = series
            context.insert(ep)
            return (ep.remoteId, true)
        case .lockedGate:
            let ep = PodcastEpisode(remoteId: "series-deep-work_ep_5", episodeNumber: 5, title: "Members-only Deep Dive", durationSec: 2456)
            ep.previewAvailable = false
            ep.series = series
            context.insert(ep)
            return (ep.remoteId, false)   // guest → sign-in gate
        }
    }
}
#endif
