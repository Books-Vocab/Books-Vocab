#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Podcast player surface.
///
/// `PodcastPlayerView` / `PodcastControlsView` / `PodcastSubtitleView` are all
/// coupled to `PodcastPlayerViewModel` whose state is `private(set)` and only
/// populated by real audio/subtitle loading — they cannot be driven to a
/// meaningful frame without hacking the production view model. So this catalog
/// renders the data-driven leaf views instead:
/// - `PodcastSentenceLevelView` (the subtitle transcript core, takes plain
///   `[PodcastSentence]`)
/// - `PodcastEpisodeRow` (episode list row, takes `PodcastEpisode` + progress)
enum PodcastPlayerScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Subtitle transcript
        playbook.addScenarios(of: "Podcast · Subtitle") {
            Scenario("Two speakers (L)", layout: .fill) {
                SubtitleScene(size: .large)
            }
            Scenario("Two speakers (XL)", layout: .fill) {
                SubtitleScene(size: .xLarge)
            }
            Scenario("Highlighted vocab", layout: .fill) {
                SubtitleScene(size: .large, lookedUpWords: ["comfortable", "question"])
            }
        }

        // MARK: Episode row
        playbook.addScenarios(of: "Podcast · Episode Row") {
            Scenario("Variants", layout: .fill) {
                episodeRowStack()
            }
        }
    }

    // MARK: - Episode row scene

    private static func episodeRowStack() -> some View {
        func episode(_ n: Int, _ title: String, audio: Bool = true, subtitle: Bool = true) -> PodcastEpisode {
            let ep = PodcastEpisode(remoteId: "ep-\(n)", episodeNumber: n, title: title, durationSec: 932)
            ep.audioAvailable = audio
            ep.subtitleAvailable = subtitle
            return ep
        }

        let skin = AppSkin.previewNeutral
        return AppThemeContainer {
            VStack(spacing: 0) {
                PodcastEpisodeRow(episode: episode(1, "The Comfort Crisis"))
                PodcastEpisodeRow(
                    episode: episode(2, "On Deep Work and Attention"),
                    progress: PodcastProgress(episodeRemoteId: "ep-2", lastPlayedTime: 410)
                )
                PodcastEpisodeRow(
                    episode: episode(3, "Habits That Compound"),
                    progress: PodcastProgress(episodeRemoteId: "ep-3", lastPlayedTime: 932, completed: true)
                )
                PodcastEpisodeRow(episode: episode(4, "Members-only Deep Dive"), locked: true)
                PodcastEpisodeRow(episode: episode(5, "Pending Upload", audio: false, subtitle: false))
            }
            .padding(.vertical)
            .background(skin.palette.pageBackground.ignoresSafeArea())
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Subtitle scene harness

/// PodcastLiveAnchor / PlaybackAnchor 建構 touches `@MainActor`, so the synthetic
/// transcript is built inside a `View` body (which is main-actor isolated).
private struct SubtitleScene: View {
    let size: PodcastSubtitleSize
    var lookedUpWords: Set<String> = []

    var body: some View {
        let s1 = PodcastSentence(
            id: 0, speaker: "Maya",
            text: "OK so here's a question.",
            startTime: 0, endTime: 2.2,
            words: [
                PodcastSubtitleCue(id: 1, startTime: 0, endTime: 0.4, speaker: "Maya", word: "OK"),
                PodcastSubtitleCue(id: 2, startTime: 0.4, endTime: 0.8, speaker: "Maya", word: "so"),
                PodcastSubtitleCue(id: 3, startTime: 0.8, endTime: 1.2, speaker: "Maya", word: "here's"),
                PodcastSubtitleCue(id: 4, startTime: 1.2, endTime: 1.6, speaker: "Maya", word: "a"),
                PodcastSubtitleCue(id: 5, startTime: 1.6, endTime: 2.2, speaker: "Maya", word: "question."),
            ]
        )
        let s2 = PodcastSentence(
            id: 1, speaker: "Kai",
            text: "We live in the most comfortable era.",
            startTime: 2.2, endTime: 5.2,
            words: [
                PodcastSubtitleCue(id: 6, startTime: 2.2, endTime: 2.7, speaker: "Kai", word: "We"),
                PodcastSubtitleCue(id: 7, startTime: 2.7, endTime: 3.0, speaker: "Kai", word: "live"),
                PodcastSubtitleCue(id: 8, startTime: 3.0, endTime: 3.2, speaker: "Kai", word: "in"),
                PodcastSubtitleCue(id: 9, startTime: 3.2, endTime: 3.5, speaker: "Kai", word: "the"),
                PodcastSubtitleCue(id: 10, startTime: 3.5, endTime: 4.0, speaker: "Kai", word: "most"),
                PodcastSubtitleCue(id: 11, startTime: 4.0, endTime: 4.7, speaker: "Kai", word: "comfortable"),
                PodcastSubtitleCue(id: 12, startTime: 4.7, endTime: 5.2, speaker: "Kai", word: "era."),
            ]
        )

        return AppThemeContainer {
            PodcastSentenceLevelView(
                sentences: [s1, s2],
                renderState: SubtitleRenderState(from: s2, hostNames: ["Maya", "Kai"]),
                liveAnchor: PodcastLiveAnchor(value: PlaybackAnchor(mediaTime: 4.3, wallClock: 0, rate: 0)),
                duration: 5.2,
                isPlaying: false,
                hostNames: ["Maya", "Kai"],
                subtitleSize: size,
                initialScrollPositionResolved: true,
                scrollLeadId: 1,
                lookedUpWords: lookedUpWords,
                highlightPreferences: .default,
                onSentenceTap: { _ in },
                onWordTap: { _, _ in },
                onPhraseTap: { _, _ in },
                onExplainTap: { _, _ in }
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
