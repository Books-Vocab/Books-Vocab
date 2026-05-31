#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Today Review surface.
/// Reuses `TodayReviewPresenterPreviewData` so state and stub cards
/// stay in lock-step with the existing `#Preview` blocks.
enum TodayReviewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review") {
            Scenario("Front", layout: .fill) {
                scene(
                    state: TodayReviewPresenterPreviewData.state(stage: .front),
                    showHint: true
                )
            }
            Scenario("Back", layout: .fill) {
                scene(
                    state: TodayReviewPresenterPreviewData.state(stage: .back),
                    showHint: false
                )
            }
            Scenario("Completed", layout: .fill) {
                scene(
                    state: TodayReviewPresenterPreviewData.completedState,
                    showHint: false
                )
            }
            Scenario("Autoplay", layout: .fill) {
                scene(
                    state: TodayReviewPresenterPreviewData.autoplayState(),
                    showHint: false
                )
            }
        }
    }

    private static func scene(state: TodayReviewPresenterState, showHint: Bool) -> some View {
        let cb = TodayReviewPresenterPreviewData.noopCallbacks
        return AppThemeContainer {
            TodayReviewPresenter(
                state: state,
                isHelpPresented: false,
                showFirstRunHint: showHint,
                onClose: cb.onClose, onAdvanceReveal: cb.onAdvanceReveal, onCollapseReveal: cb.onCollapseReveal,
                onShuffle: cb.onShuffle, onPrevious: cb.onPrevious, onNext: cb.onNext,
                onForgot: cb.onForgot, onRemembered: cb.onRemembered, onLinkTap: cb.onLinkTap,
                onAddLink: cb.onAddLink,
                onToggleAutoPlay: cb.onToggleAutoPlay, onToggleAutoPlayPause: cb.onToggleAutoPlayPause,
                onDetailTap: cb.onDetailTap, onToggleHelp: cb.onToggleHelp,
                onExplainCollocation: cb.onExplainCollocation,
                onViewCollocationExplanation: cb.onViewCollocationExplanation,
                onDeleteCollocationExplanation: cb.onDeleteCollocationExplanation
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
