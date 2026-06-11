#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the `PodcastShelf` carousel container (title + horizontal
/// card rail). The card-level baselines live in `PodcastShelfCardsScenarios`; here we prove
/// the *shelf* composition: multi-card rail, single card, long title truncation,
/// and a11y3 vertical growth.
enum PodcastShelfScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Podcast Shelf") {
            Scenario("Continue rail / Full", layout: .fillH) {
                PodcastShelfScene(fixture: .shelfContinue, title: "繼續收聽")
            }
            Scenario("Continue rail / Single card", layout: .fillH) {
                PodcastShelfScene(fixture: .shelfSingle, title: "繼續收聽")
            }
            Scenario("Continue rail / Long shelf title", layout: .fillH) {
                PodcastShelfScene(
                    fixture: .shelfContinue,
                    title: "繼續收聽：你最近開始但還沒聽完的所有單集都在這裡"
                )
            }
            Scenario("Continue rail / A11y3", layout: .fillH) {
                PodcastShelfScene(fixture: .shelfContinue, title: "繼續收聽")
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// Shelf-level harness. `PodcastSeries` / `PodcastEpisode` / `PodcastProgress` are
/// SwiftData `@Model` types whose inits touch `@MainActor` paths, so fixture
/// construction must live in a `View` body (same reason as the card harnesses in
/// `PodcastShelfCardsScenarios`).
private struct PodcastShelfScene: View {
    let fixture: PodcastFixtureID
    let title: String

    var body: some View {
        let model = PodcastFixtures.renderModel(for: fixture)

        return AppThemeContainer {
            ScrollView {
                PodcastShelf(title: title) {
                    ForEach(model.items, id: \.episode.remoteId) { item in
                        PodcastContinueRailCard(
                            episode: item.episode,
                            series: model.series,
                            progress: item.progress
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
