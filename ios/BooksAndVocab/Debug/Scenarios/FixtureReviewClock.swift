#if DEBUG
import Foundation

/// Shared frozen-clock resolver for Catalog scenarios that render review state.
///
/// Reads `scenarioContext.reviewClock.frozenEpoch` when a frozen UI
/// World is injected; otherwise returns the supplied QA fallback so
/// independent scenarios keep their hardcoded /
/// wall-clock anchor untouched.
///
/// The frozen epoch equals the UI World's
/// `review_settings_progress_paused_at` (single SoT), so aligning both the graph
/// `now` and the review-settings paused-at to it lets the ReviewGradient expand
/// its colour layers (fresh green → amber → due → overdue red) instead of
/// collapsing to all-green under a stale 2026-06-01 anchor.
enum FixtureReviewClock {
    /// Frozen "now" for structured scenarios, or `fallback` when the UI World
    /// does not provide one.
    static func now(fallback: Date) -> Date {
        guard let epoch = FixtureDatasetStore.scenarioContext()?.reviewClock?.frozenEpoch else {
            return fallback
        }
        return Date(timeIntervalSince1970: TimeInterval(epoch))
    }
}
#endif
