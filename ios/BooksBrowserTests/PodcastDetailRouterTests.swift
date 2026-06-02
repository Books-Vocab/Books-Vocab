import Foundation
import Testing
@testable import BooksBrowser

/// Episode-layer activation decision.
///
/// The episode-list → player split-pane (inline detail on regular layouts) was
/// collapsed into a single-column push navigation: tapping an episode now always
/// pushes `PodcastPlayerView` onto BookshelfView's NavigationStack via
/// `PodcastNavRoute.episode`, on every layout. `activation` therefore returns
/// `.push` unconditionally — there is no longer an inline branch.
///
/// (Series-layer activation is unchanged; see `PodcastSeriesActivationTests`.)
@MainActor
@Suite("PodcastEpisodeActivation")
struct PodcastEpisodeActivationTests {
    @Test func pushesOnRegularLayout() {
        #expect(
            PodcastEpisodeActivation.activation(
                episodeRemoteId: "ep-1",
                layoutMode: .regular
            ) == .push(route: .episode(episodeRemoteId: "ep-1"))
        )
    }

    @Test func pushesOnCompactLayout() {
        #expect(
            PodcastEpisodeActivation.activation(
                episodeRemoteId: "ep-1",
                layoutMode: .compact
            ) == .push(route: .episode(episodeRemoteId: "ep-1"))
        )
    }

    @Test func pushRouteCarriesEpisodeIdVerbatim() {
        #expect(
            PodcastEpisodeActivation.activation(
                episodeRemoteId: "abc-xyz-42",
                layoutMode: .regular
            ) == .push(route: .episode(episodeRemoteId: "abc-xyz-42"))
        )
    }
}
