#if DEBUG
import Foundation

/// Shared frozen-clock resolver for the marketing catalog scenes (Knowledge
/// Graph `Populated graph` + Vocabulary `Reviewed · Marketing`).
///
/// Reads `marketingCapture.reviewClock.frozenEpoch` when a frozen marketing UI
/// World is injected; otherwise returns the supplied QA fallback so
/// non-marketing renders (and every existing QA scene) keep their hardcoded /
/// wall-clock anchor untouched.
///
/// The frozen epoch equals the marketing world's
/// `review_settings_progress_paused_at` (single SoT), so aligning both the graph
/// `now` and the review-settings paused-at to it lets the ReviewGradient expand
/// its colour layers (fresh green → amber → due → overdue red) instead of
/// collapsing to all-green under a stale 2026-06-01 anchor.
enum MarketingReviewClock {
    /// Frozen "now" for marketing catalog scenes, or `fallback` when no frozen
    /// marketing world is injected.
    static func now(fallback: Date) -> Date {
        guard let epoch = FixtureDatasetStore.marketingCapture()?.reviewClock?.frozenEpoch else {
            return fallback
        }
        return Date(timeIntervalSince1970: TimeInterval(epoch))
    }
}
#endif
