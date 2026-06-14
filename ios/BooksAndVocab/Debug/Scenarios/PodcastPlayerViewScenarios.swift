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
/// `PodcastPlayerView(episodeId:)` resolves its episode/series via a synchronous
/// `modelContext.fetch` (no `@Query` race) and builds its `PodcastPlayerViewModel`
/// in `.task(id:)`. An audio-less episode does NOT short-circuit to a loaded
/// player — its async load reports "無音訊 URL" while the captured frame is stuck
/// on the `.idle` loading spinner (a non-deterministic race). So the preview state
/// drives the DEBUG-only catalog preview environment seam instead: it builds a synchronous,
/// AVPlayer-free `.ready` viewModel (seeded duration + synthetic SRT, paused
/// mid-episode) so the real player chrome renders deterministically — no audio,
/// no network. See `PodcastPlayerCatalogPreview` / `catalogReadyPreview`.
///
/// Two surface states:
/// - **Preview episode** → catalog preview environment seam → `playerCore` renders the live
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
    let preview: PodcastPlayerCatalogPreview?

    init(fixture: PodcastPlayerFixture) {
        let container = try! ModelContainer(
            for: PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self, VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let (episodeId, loggedIn) = Self.seed(fixture, into: container.mainContext)
        try? container.mainContext.save()
        self.container = container
        self.episodeId = episodeId
        self.auth = loggedIn
            ? CatalogPreviewAuth(
                isLoggedIn: true,
                userId: "catalog-podcast-player-user",
                token: "catalog-podcast-player-token",
                displayName: "Catalog Podcast Player User",
                userEmail: "catalog-podcast-player@example.com"
            )
            : CatalogPreviewAuth(
                isLoggedIn: false,
                userId: nil,
                token: nil,
                displayName: nil,
                userEmail: nil
            )
        // The preview-player fixture drives the catalog seam → deterministic,
        // AVPlayer-free `.ready` chrome with a populated, mid-episode transcript.
        // The locked-gate fixture never loads audio, so it needs no preview.
        self.preview = fixture == .previewPlayer
            ? .init(durationSec: 1832, currentSec: 6.09, subtitleSRT: Self.sampleSRT)
            : nil
    }

    var body: some View {
        AppThemeContainer {
            // The player's chrome (inline nav bar + settings gear) lives in the
            // SwiftUI nav-bar host; by design (#672) it carries no internal
            // NavigationStack and relies on an ambient one from its push context.
            // The harness must supply it (mirrors PodcastEpisodeListViewScenarios),
            // else the top renders as an empty void.
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

    /// Synthetic WORD-level SRT (one cue per word, gap-free + monotonic), 11
    /// sentences. Three constraints shaped it:
    ///  1. A sentence-level SRT collapses each sentence to one "word" cue → the
    ///     karaoke follow-underline relay takes the `tailExit` path and the bar
    ///     overshoots to the row's right edge. Per-word timing makes `currentSec`
    ///     land mid-word ("quietly", 3rd sentence) → a short capsule under one word.
    ///  2. The transcript's auto-scroll-to-current does NOT run in a static
    ///     Playbook snapshot (it's an onAppear scroll), so the captured frame sits
    ///     at scroll offset 0. The current sentence must therefore be in the FIRST
    ///     viewport — sentence 3 is visible without scrolling, highlighted in place.
    ///  3. 11 sentences (vs the few visible) fill the viewport top-to-bottom so the
    ///     player reads like a real mid-episode screen, not a sparse one.
    /// DEBUG catalog fixture — English copy (the app teaches English), no L10n.
    static let sampleSRT = """
    1
    00:00:00,000 --> 00:00:00,420
    Welcome

    2
    00:00:00,420 --> 00:00:00,840
    back

    3
    00:00:00,840 --> 00:00:01,260
    to

    4
    00:00:01,260 --> 00:00:01,680
    Deep

    5
    00:00:01,680 --> 00:00:02,100
    Work,

    6
    00:00:02,100 --> 00:00:02,520
    Decoded.

    7
    00:00:02,520 --> 00:00:02,940
    Today

    8
    00:00:02,940 --> 00:00:03,360
    we

    9
    00:00:03,360 --> 00:00:03,780
    trace

    10
    00:00:03,780 --> 00:00:04,200
    the

    11
    00:00:04,200 --> 00:00:04,620
    comfort

    12
    00:00:04,620 --> 00:00:05,040
    crisis.

    13
    00:00:05,040 --> 00:00:05,460
    Easy

    14
    00:00:05,460 --> 00:00:05,880
    distraction

    15
    00:00:05,880 --> 00:00:06,300
    quietly

    16
    00:00:06,300 --> 00:00:06,720
    erodes

    17
    00:00:06,720 --> 00:00:07,140
    our

    18
    00:00:07,140 --> 00:00:07,560
    focus.

    19
    00:00:07,560 --> 00:00:07,980
    The

    20
    00:00:07,980 --> 00:00:08,400
    thesis

    21
    00:00:08,400 --> 00:00:08,820
    is

    22
    00:00:08,820 --> 00:00:09,240
    simple

    23
    00:00:09,240 --> 00:00:09,660
    and

    24
    00:00:09,660 --> 00:00:10,080
    a

    25
    00:00:10,080 --> 00:00:10,500
    little

    26
    00:00:10,500 --> 00:00:10,920
    uncomfortable.

    27
    00:00:10,920 --> 00:00:11,340
    Discomfort

    28
    00:00:11,340 --> 00:00:11,760
    chosen

    29
    00:00:11,760 --> 00:00:12,180
    on

    30
    00:00:12,180 --> 00:00:12,600
    purpose

    31
    00:00:12,600 --> 00:00:13,020
    builds

    32
    00:00:13,020 --> 00:00:13,440
    durable

    33
    00:00:13,440 --> 00:00:13,860
    attention.

    34
    00:00:13,860 --> 00:00:14,280
    We

    35
    00:00:14,280 --> 00:00:14,700
    start

    36
    00:00:14,700 --> 00:00:15,120
    with

    37
    00:00:15,120 --> 00:00:15,540
    a

    38
    00:00:15,540 --> 00:00:15,960
    writer

    39
    00:00:15,960 --> 00:00:16,380
    who

    40
    00:00:16,380 --> 00:00:16,800
    deleted

    41
    00:00:16,800 --> 00:00:17,220
    every

    42
    00:00:17,220 --> 00:00:17,640
    app

    43
    00:00:17,640 --> 00:00:18,060
    but

    44
    00:00:18,060 --> 00:00:18,480
    one.

    45
    00:00:18,480 --> 00:00:18,900
    She

    46
    00:00:18,900 --> 00:00:19,320
    wrote

    47
    00:00:19,320 --> 00:00:19,740
    for

    48
    00:00:19,740 --> 00:00:20,160
    ninety

    49
    00:00:20,160 --> 00:00:20,580
    unbroken

    50
    00:00:20,580 --> 00:00:21,000
    minutes

    51
    00:00:21,000 --> 00:00:21,420
    each

    52
    00:00:21,420 --> 00:00:21,840
    morning.

    53
    00:00:21,840 --> 00:00:22,260
    The

    54
    00:00:22,260 --> 00:00:22,680
    first

    55
    00:00:22,680 --> 00:00:23,100
    week

    56
    00:00:23,100 --> 00:00:23,520
    felt

    57
    00:00:23,520 --> 00:00:23,940
    almost

    58
    00:00:23,940 --> 00:00:24,360
    unbearable.

    59
    00:00:24,360 --> 00:00:24,780
    By

    60
    00:00:24,780 --> 00:00:25,200
    the

    61
    00:00:25,200 --> 00:00:25,620
    third

    62
    00:00:25,620 --> 00:00:26,040
    week

    63
    00:00:26,040 --> 00:00:26,460
    the

    64
    00:00:26,460 --> 00:00:26,880
    silence

    65
    00:00:26,880 --> 00:00:27,300
    became

    66
    00:00:27,300 --> 00:00:27,720
    a

    67
    00:00:27,720 --> 00:00:28,140
    tool.

    68
    00:00:28,140 --> 00:00:28,560
    Focus,

    69
    00:00:28,560 --> 00:00:28,980
    it

    70
    00:00:28,980 --> 00:00:29,400
    turns

    71
    00:00:29,400 --> 00:00:29,820
    out,

    72
    00:00:29,820 --> 00:00:30,240
    is

    73
    00:00:30,240 --> 00:00:30,660
    a

    74
    00:00:30,660 --> 00:00:31,080
    muscle

    75
    00:00:31,080 --> 00:00:31,500
    you

    76
    00:00:31,500 --> 00:00:31,920
    can

    77
    00:00:31,920 --> 00:00:32,340
    train.

    78
    00:00:32,340 --> 00:00:32,760
    So

    79
    00:00:32,760 --> 00:00:33,180
    today,

    80
    00:00:33,180 --> 00:00:33,600
    pick

    81
    00:00:33,600 --> 00:00:34,020
    one

    82
    00:00:34,020 --> 00:00:34,440
    hard

    83
    00:00:34,440 --> 00:00:34,860
    thing

    84
    00:00:34,860 --> 00:00:35,280
    and

    85
    00:00:35,280 --> 00:00:35,700
    stay

    86
    00:00:35,700 --> 00:00:36,120
    with

    87
    00:00:36,120 --> 00:00:36,540
    it.
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
