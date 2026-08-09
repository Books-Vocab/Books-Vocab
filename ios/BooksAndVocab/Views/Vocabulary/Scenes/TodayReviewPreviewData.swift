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

/// 「抽對了」的活證明：**不經 presenter**、不餵 20 個 no-op callback、不造一整份
/// `TodayReviewPresenterState`，只用卡片資料 + profile + 可用高度就畫得出一張卡。
/// 設定頁的即時預覽（APP-20260808-d4a707）與 catalog 走的是同一條路。
struct ReviewCardFixtureScene: View {
    @ObserveInjection private var inject
    let fixtureID: TodayReviewFixtureID
    var showsAnswer: Bool = true

    var body: some View {
        AppThemeContainer {
            GeometryReader { proxy in
                if let content = TodayReviewFixtures.renderModel(for: fixtureID).state.currentCard {
                    ReviewCardView(
                        content: content,
                        profile: .default,
                        viewport: ReviewCardViewport(containerHeight: proxy.size.height),
                        showsAnswer: showsAnswer,
                        interactive: false,
                        actions: .none
                    )
                    .padding(.horizontal, TodayReviewMetrics.cardHorizontalInset)
                }
            }
        }
        .environmentObject(AppAppearanceStore.preview)
        .enableInjection()
    }
}

#Preview("Review Card / Bare (front)") {
    ReviewCardFixtureScene(fixtureID: .front, showsAnswer: false)
}

#Preview("Review Card / Bare (back)") {
    ReviewCardFixtureScene(fixtureID: .back)
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
