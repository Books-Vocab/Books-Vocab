import Foundation

/// Pure, testable core of the podcast series "follow" toggle.
///
/// The View flips `isFollowed` optimistically (with animation) so the star
/// updates instantly. Before this helper existed, a failed `ModelContext.save()`
/// only logged a warning — the in-memory flip survived, so the UI kept showing
/// "followed" while nothing was persisted and the state vanished on relaunch.
///
/// `perform` couples the optimistic flip to the persistence result: on a failed
/// save it rolls the model back to its prior state so UI and storage stay
/// consistent. The `save` closure is injected so the rollback contract is
/// unit-testable without forcing a real SwiftData failure.
enum PodcastFollowToggle {
    enum Outcome: Equatable {
        /// The toggle persisted; the new `isFollowed` value stands.
        case saved
        /// The save failed; the model was reverted to its prior state.
        case rolledBack
    }

    /// Toggles `series.isFollowed`, persists via `save`, and rolls back the
    /// model (`isFollowed` + `updatedAt`) if `save` reports failure.
    ///
    /// - Parameters:
    ///   - series: the series whose follow flag is being toggled.
    ///   - save: persistence step — returns `true` on success, `false` on
    ///     failure (mirrors `ModelContext.safeSave()`).
    @discardableResult
    static func perform(
        series: PodcastSeries,
        save: () -> Bool
    ) -> Outcome {
        let previousFollowed = series.isFollowed
        let previousUpdatedAt = series.updatedAt

        series.isFollowed.toggle()
        series.updatedAt = Date()

        if save() {
            return .saved
        }

        // Persistence failed — revert so the UI never shows a phantom state.
        series.isFollowed = previousFollowed
        series.updatedAt = previousUpdatedAt
        return .rolledBack
    }
}
