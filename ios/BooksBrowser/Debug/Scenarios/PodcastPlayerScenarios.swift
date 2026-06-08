#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Podcast player surface.
///
/// `PodcastPlayerView` / `PodcastControlsView` are coupled to
/// `PodcastPlayerViewModel` whose state is `private(set)` and only populated by
/// real audio/subtitle loading — they cannot be driven to a meaningful frame
/// without hacking the production view model. The subtitle transcript core
/// (`PodcastSentenceLevelView`) is catalogued as Bubble Cell / Transcript Column
/// under `podcast_sentence_cells`; this entry renders only:
/// - `PodcastEpisodeRow` (episode list row, takes `PodcastEpisode` + progress)
enum PodcastPlayerScenarios {
    static func register(in playbook: Playbook) {
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
#endif
