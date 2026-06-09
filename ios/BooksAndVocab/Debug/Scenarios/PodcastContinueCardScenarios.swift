#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `PodcastContinueCard` (the series-hero primary CTA).
/// Not the hero itself — that surface is covered elsewhere. Each scenario feeds
/// a synthetic `PodcastEpisode` / `PodcastProgress` into the card across its
/// `PodcastHeroAction` states (resume / fresh / replay / preview / gated).
enum PodcastContinueCardScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Continue Card") {
            Scenario("In Progress (Resume)", layout: .fillH) {
                PodcastContinueCardScene(
                    episode: PodcastContinueCardScenarios.episode(2, "On Deep Work and Attention"),
                    progress: PodcastProgress(episodeRemoteId: "s-1_ep_2", lastPlayedTime: 410, completed: false),
                    action: .resume
                )
            }

            Scenario("Fresh (Play)", layout: .fillH) {
                PodcastContinueCardScene(
                    episode: PodcastContinueCardScenarios.episode(1, "The Comfort Crisis"),
                    progress: nil,
                    action: .play
                )
            }

            Scenario("Completed (Replay)", layout: .fillH) {
                PodcastContinueCardScene(
                    episode: PodcastContinueCardScenarios.episode(1, "The Comfort Crisis"),
                    progress: PodcastProgress(episodeRemoteId: "s-1_ep_1", lastPlayedTime: 932, completed: true),
                    action: .replay
                )
            }

            Scenario("Free Preview", layout: .fillH) {
                PodcastContinueCardScene(
                    episode: PodcastContinueCardScenarios.episode(1, "The Comfort Crisis", preview: true),
                    progress: nil,
                    action: .preview
                )
            }

            Scenario("Gated (Sign In / Upgrade / Unavailable)", layout: .fillH) {
                PodcastContinueCardGatedScene()
            }
        }
    }

    // MARK: - Fixtures

    fileprivate static func episode(
        _ n: Int,
        _ title: String,
        audio: Bool = true,
        preview: Bool = false
    ) -> PodcastEpisode {
        let e = PodcastEpisode(remoteId: "s-1_ep_\(n)", episodeNumber: n, title: title, durationSec: 932)
        e.audioAvailable = audio
        e.previewAvailable = preview
        return e
    }
}

// MARK: - Scene harnesses

private struct PodcastContinueCardScene: View {
    let episode: PodcastEpisode
    let progress: PodcastProgress?
    let action: PodcastHeroAction

    var body: some View {
        AppThemeContainer {
            ScrollView {
                PodcastContinueCard(episode: episode, progress: progress, action: action)
                    .padding(AppSpacing.s4)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

/// Stacks the three non-actionable / auth-gated variants so the disabled
/// treatment (muted disc, lock chevron) is reviewable in one frame.
private struct PodcastContinueCardGatedScene: View {
    var body: some View {
        AppThemeContainer {
            ScrollView {
                VStack(spacing: AppSpacing.s4) {
                    PodcastContinueCard(
                        episode: PodcastContinueCardScenarios.episode(1, "The Comfort Crisis"),
                        progress: nil,
                        action: .signIn
                    )
                    PodcastContinueCard(
                        episode: PodcastContinueCardScenarios.episode(3, "Habits That Compound"),
                        progress: nil,
                        action: .upgrade
                    )
                    PodcastContinueCard(
                        episode: PodcastContinueCardScenarios.episode(4, "Pending Upload", audio: false),
                        progress: nil,
                        action: .unavailable
                    )
                }
                .padding(AppSpacing.s4)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
