#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the `PodcastShelf` carousel container (title + horizontal
/// card rail). The card-level baselines live in `BookshelfScenarios`; here we prove
/// the *shelf* composition: multi-card rail, single card, long title truncation,
/// and a11y3 vertical growth.
enum PodcastShelfScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Shelf") {
            Scenario("Continue rail / Full", layout: .fillH) {
                PodcastShelfScene(kind: .full, title: "繼續收聽")
            }
            Scenario("Continue rail / Single card", layout: .fillH) {
                PodcastShelfScene(kind: .single, title: "繼續收聽")
            }
            Scenario("Continue rail / Long shelf title", layout: .fillH) {
                PodcastShelfScene(
                    kind: .full,
                    title: "繼續收聽：你最近開始但還沒聽完的所有單集都在這裡"
                )
            }
            Scenario("Continue rail / A11y3", layout: .fillH) {
                PodcastShelfScene(kind: .full, title: "繼續收聽")
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// Shelf-level harness. `PodcastSeries` / `PodcastEpisode` / `PodcastProgress` are
/// SwiftData `@Model` types whose inits touch `@MainActor` paths, so fixture
/// construction must live in a `View` body (same reason as the card harnesses in
/// `BookshelfScenarios`).
private struct PodcastShelfScene: View {
    enum Kind { case full, single }
    let kind: Kind
    let title: String

    var body: some View {
        let series = PodcastSeries(
            remoteId: "s-shelf",
            title: "Atomic Habits Unpacked",
            hostNames: ["Ava Chen"]
        )
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue

        func ep(_ n: Int, _ t: String, _ dur: Double = 1832) -> PodcastEpisode {
            PodcastEpisode(remoteId: "s-shelf_ep_\(n)", episodeNumber: n, title: t, durationSec: dur)
        }
        func prog(_ n: Int, _ played: Double) -> PodcastProgress {
            PodcastProgress(episodeRemoteId: "s-shelf_ep_\(n)", lastPlayedTime: played)
        }

        return AppThemeContainer {
            ScrollView {
                PodcastShelf(title: title) {
                    PodcastContinueRailCard(
                        episode: ep(2, "On Deep Work"),
                        series: series,
                        progress: prog(2, 612)
                    )
                    if kind == .full {
                        PodcastContinueRailCard(
                            episode: ep(5, "A Very Long Episode Title That Should Truncate Cleanly", 5432),
                            series: series,
                            progress: prog(5, 1700)
                        )
                        PodcastContinueRailCard(
                            episode: ep(8, "Marathon Session", 12_345),
                            series: series,
                            progress: prog(8, 321)
                        )
                        PodcastContinueRailCard(
                            episode: ep(1, "The Comfort Crisis"),
                            series: series,
                            progress: nil
                        )
                    }
                }
                .padding(.vertical, AppSpacing.s4)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif

#endif
