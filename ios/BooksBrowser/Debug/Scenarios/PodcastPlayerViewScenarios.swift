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
/// in `.task(id:)`. An audio-less episode does NOT short-circuit to a loaded
/// player — its async load reports "無音訊 URL" while the captured frame is stuck
/// on the `.idle` loading spinner (a non-deterministic race). So the preview state
/// drives the DEBUG-only `catalogPreview` seam instead: it builds a synchronous,
/// AVPlayer-free `.ready` viewModel (seeded duration + synthetic SRT, paused
/// mid-episode) so the real player chrome renders deterministically — no audio,
/// no network. See `PodcastPlayerView.CatalogPreview` / `catalogReadyPreview`.
///
/// Two surface states:
/// - **Preview episode** → `catalogPreview` seam → `playerCore` renders the live
///   `.ready` chrome (transcript + scrubber + transport + preview banner).
/// - **Locked gate** → a non-preview episode reached as a guest hits the
///   defense-in-depth `lockedGateView` (sign-in CTA) — audio is never loaded, so
///   no seam is needed (the gate is reached before any load).
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
    let preview: PodcastPlayerView.CatalogPreview?

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
        // The preview-player fixture drives the catalog seam → deterministic,
        // AVPlayer-free `.ready` chrome with a populated, mid-episode transcript.
        // The locked-gate fixture never loads audio, so it needs no preview.
        self.preview = fixture == .previewPlayer
            ? .init(durationSec: 1832, currentSec: 13, subtitleSRT: Self.sampleSRT)
            : nil
    }

    var body: some View {
        AppThemeContainer {
            player
                .modelContainer(container)
                .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    @ViewBuilder private var player: some View {
        if let preview {
            PodcastPlayerView(episodeId: episodeId, catalogPreview: preview)
        } else {
            PodcastPlayerView(episodeId: episodeId)
        }
    }

    /// Synthetic SRT so the catalog player shows a populated, mid-episode
    /// transcript (sentence 3 lands under `currentSec` = 13s). DEBUG catalog
    /// fixture — English copy (the app teaches English), so no L10n needed.
    static let sampleSRT = """
    1
    00:00:00,000 --> 00:00:05,200
    Welcome back to Deep Work, Decoded — the show about doing fewer things, far better.

    2
    00:00:05,200 --> 00:00:11,800
    Today we trace the comfort crisis: how constant, easy distraction quietly erodes deep focus.

    3
    00:00:11,800 --> 00:00:18,400
    The thesis is simple. Discomfort, chosen on purpose, is where durable attention gets built.

    4
    00:00:18,400 --> 00:00:25,000
    We start with a writer who deleted every app but one, then wrote for ninety unbroken minutes.
    """

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
