import Foundation
import Testing
@testable import BooksBrowser

/// Series-layer activation decision:
/// - regular (Mac/iPad, `usesInlineDetail == true`) → `.selectInline` so the
///   episode-list + player render as a root-level master pane on the
///   BookshelfView NavigationStack root (depth=0), never pushed. This removes
///   the depth=1 push entry that the trailing `safeAreaInset` player would
///   otherwise remount/pop (NAVDBG-confirmed root cause).
/// - compact (iPhone) → `.push(.series(...))` (bit-for-bit unchanged path).
@MainActor
@Suite("PodcastSeriesActivation")
struct PodcastSeriesActivationTests {
    @Test func selectsInlineOnRegularLayout() {
        #expect(
            PodcastSeriesActivation.activation(
                seriesRemoteId: "series-1",
                layoutMode: .regular
            ) == .selectInline(seriesRemoteId: "series-1")
        )
    }

    @Test func pushesOnCompactLayout() {
        #expect(
            PodcastSeriesActivation.activation(
                seriesRemoteId: "series-1",
                layoutMode: .compact
            ) == .push(route: .series(seriesRemoteId: "series-1"))
        )
    }

    @Test func selectInlineCarriesSeriesIdVerbatim() {
        let activation = PodcastSeriesActivation.activation(
            seriesRemoteId: "abc-xyz-42",
            layoutMode: .regular
        )
        #expect(activation == .selectInline(seriesRemoteId: "abc-xyz-42"))
    }

    @Test func pushRouteCarriesSeriesIdVerbatim() {
        let activation = PodcastSeriesActivation.activation(
            seriesRemoteId: "abc-xyz-42",
            layoutMode: .compact
        )
        #expect(activation == .push(route: .series(seriesRemoteId: "abc-xyz-42")))
    }
}
