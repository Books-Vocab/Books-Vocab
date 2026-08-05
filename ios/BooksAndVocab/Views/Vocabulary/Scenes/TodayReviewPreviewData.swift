import SwiftUI

enum TodayReviewPresenterPreviewData {
    static var frontState: TodayReviewPresenterState { TodayReviewFixtures.state(for: .front) }
    static var backState: TodayReviewPresenterState { TodayReviewFixtures.state(for: .back) }
    static var completedState: TodayReviewPresenterState { TodayReviewFixtures.state(for: .completed) }
    static var autoplayState: TodayReviewPresenterState { TodayReviewFixtures.state(for: .autoplay) }

    static let noopCallbacks: (
        onClose: () -> Void,
        onAdvanceReveal: () -> Void,
        onCollapseReveal: () -> Void,
        onShuffle: () -> Void,
        onPrevious: () -> Void,
        onNext: () -> Void,
        onForgot: () -> Void,
        onRemembered: () -> Void,
        onLinkTap: (KGCardLinkSummary) -> Void,
        onAddLink: () -> Void,
        onToggleAutoPlay: () -> Void,
        onToggleAutoPlayPause: () -> Void,
        onChangeAutoPlaySpeed: () -> Void,
        onToggleAutoPlaySound: () -> Void,
        onAdjustLayout: () -> Void,
        onDetailTap: () -> Void,
        onToggleHelp: () -> Void,
        onExplainCollocation: (String) -> Void,
        onViewCollocationExplanation: (String) -> Void,
        onDeleteCollocationExplanation: (String) -> Void
    ) = ({}, {}, {}, {}, {}, {}, {}, {}, { _ in }, {}, {}, {}, {}, {}, {}, {}, {}, { _ in }, { _ in }, { _ in })
}

struct TodayReviewFixtureScene: View {
    let fixtureID: TodayReviewFixtureID

    private var renderModel: TodayReviewFixtureRenderModel {
        TodayReviewFixtures.renderModel(for: fixtureID)
    }

    var body: some View {
        let cb = TodayReviewPresenterPreviewData.noopCallbacks
        return AppThemeContainer {
            TodayReviewPresenter(
                state: renderModel.state,
                isHelpPresented: false,
                showFirstRunHint: renderModel.showFirstRunHint,
                onClose: cb.onClose, onAdvanceReveal: cb.onAdvanceReveal, onCollapseReveal: cb.onCollapseReveal,
                onShuffle: cb.onShuffle, onPrevious: cb.onPrevious, onNext: cb.onNext,
                onForgot: cb.onForgot, onRemembered: cb.onRemembered, onLinkTap: cb.onLinkTap,
                onAddLink: cb.onAddLink,
                onToggleAutoPlay: cb.onToggleAutoPlay, onToggleAutoPlayPause: cb.onToggleAutoPlayPause,
                onChangeAutoPlaySpeed: cb.onChangeAutoPlaySpeed,
                onToggleAutoPlaySound: cb.onToggleAutoPlaySound,
                onAdjustLayout: cb.onAdjustLayout,
                onDetailTap: cb.onDetailTap, onToggleHelp: cb.onToggleHelp,
                onExplainCollocation: cb.onExplainCollocation,
                onViewCollocationExplanation: cb.onViewCollocationExplanation,
                onDeleteCollocationExplanation: cb.onDeleteCollocationExplanation
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

#Preview("Today Review / Front") {
    TodayReviewFixtureScene(fixtureID: .front)
}

#Preview("Today Review / Back") {
    TodayReviewFixtureScene(fixtureID: .back)
}

#Preview("Today Review / Completed") {
    TodayReviewFixtureScene(fixtureID: .completed)
}

#Preview("Today Review / Autoplay") {
    TodayReviewFixtureScene(fixtureID: .autoplay)
}
