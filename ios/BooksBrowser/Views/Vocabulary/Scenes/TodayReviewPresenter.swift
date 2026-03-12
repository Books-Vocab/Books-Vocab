import SwiftUI

// MARK: - State

struct TodayReviewPresenterState {
    struct LinkGroup: Identifiable {
        let id: String
        let label: String
        let items: [KGCardLinkSummary]
        let overflowCount: Int
    }

    struct CurrentCard {
        let card: CardPresentation
        let linkGroups: [LinkGroup]
    }

    let progressText: String
    let currentCard: CurrentCard?
    let nextCard: CurrentCard?
    let revealStage: TodayReviewRevealStage
    let canShuffle: Bool
    let canGoPrevious: Bool
    let canGoNext: Bool
    let remainingCount: Int
    let forgotCount: Int
    let rememberedCount: Int
    let rememberedFeedbackTrigger: Int
    let forgotFeedbackTrigger: Int
    let persistenceFailureTrigger: Int
    let persistenceErrorMessage: String?
    let isAutoPlaying: Bool
    let isAutoPlayPaused: Bool
}

// MARK: - Presenter

struct TodayReviewPresenter: View {
    // internal — extension files 需要存取
    @Environment(\.vocabSkin) var vocabSkin
    @Environment(\.dynamicTypeSize) var dynamicTypeSize
    @Environment(\.speechService) private var speechService

    // 動畫狀態 — dismissPhase 是唯一的互動鎖
    @State var swipeOffset: CGFloat = 0
    @State var containerWidth: CGFloat = 393
    @State var dismissPhase: DismissPhase = .idle
    @State var suppressTransition = false
    @State var flingHapticTrigger = 0
    @State var stackRotations: [Double] = [
        .random(in: -1.0...1.0),
        .random(in: -1.0...1.0)
    ]

    enum DismissPhase {
        case idle
        case animatingOut
    }

    let state: TodayReviewPresenterState
    let onClose: () -> Void
    let onAdvanceReveal: () -> Void
    let onCollapseReveal: () -> Void
    let onShuffle: () -> Void
    let onPrevious: () -> Void
    let onNext: () -> Void
    let onForgot: () -> Void
    let onRemembered: () -> Void
    let onLinkTap: (KGCardLinkSummary) -> Void
    let onToggleAutoPlay: () -> Void
    let onToggleAutoPlayPause: () -> Void
    let onDetailTap: () -> Void

    /// 給 extension 判斷能否互動
    var isCardInteractive: Bool {
        dismissPhase == .idle
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let currentCard = state.currentCard {
                    topBar

                    GeometryReader { geo in
                        ScrollView {
                            VStack(spacing: 0) {
                                reviewCard(currentCard)
                                    .padding(.horizontal, vocabSkin.metrics.reviewCardHorizontalInset)
                                    .padding(.top, vocabSkin.metrics.reviewCardTopInset)
                                    .padding(.bottom, vocabSkin.metrics.reviewCardBottomInset)

                                if state.revealStage == .front {
                                    revealExpandZone(
                                        title: "點一下展開".localized,
                                        minHeight: max(geo.size.height * vocabSkin.metrics.reviewFrontHeightRatio, 180),
                                        action: onAdvanceReveal
                                    )
                                } else if state.revealStage.showsAnswer {
                                    Spacer(minLength: 0)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: geo.size.height, alignment: .top)
                        }
                    }

                    bottomToolbar
                } else {
                    completionState
                }
            }
            .frame(maxWidth: 600)
            .frame(maxWidth: .infinity)
            .vocabCanvasBackground()
            .toolbar(.hidden, for: .navigationBar)
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.width
            } action: { newWidth in
                containerWidth = newWidth
            }
            .sensoryFeedback(.impact(weight: .light), trigger: flingHapticTrigger)
            .sensoryFeedback(.error, trigger: state.persistenceFailureTrigger)
        }
    }

    // MARK: - Card

    func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card
        let cardIdentity = card.word + "-" + String(card.dateAdded.timeIntervalSinceReferenceDate)

        return ZStack(alignment: .top) {
            // 牌堆 — 不隨 .id() 銷毀重建
            cardStackLayers()
                .frame(height: frontCardHeight)

            // 互動卡片
            VStack(spacing: 0) {
                frontFoldSurface(card)
                    .overlay(alignment: .topTrailing) {
                        HStack(spacing: vocabSkin.spacing.inlineGap) {
                            VocabChromeIconButton(
                                systemImage: "speaker.wave.2.fill",
                                label: "播放發音".localized,
                                action: { speechService.speak(card.word) }
                            )
                            VocabChromeIconButton(
                                systemImage: "arrow.up.right",
                                label: "查看詳情".localized,
                                action: { guard isCardInteractive else { return }; onDetailTap() }
                            )
                        }
                        .padding(reviewCardPadding)
                    }

                if state.revealStage.showsAnswer {
                    answerFoldSurface(currentCard)
                        .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                        .transition(.paperFoldFromTop)
                }
            }
            .id(cardIdentity)
            .transition(suppressTransition ? .identity : .asymmetric(
                insertion: .scale(scale: TodayReviewMetrics.promoteScale)
                    .combined(with: .offset(x: 0, y: TodayReviewMetrics.promoteYOffset)),
                removal: .identity
            ))
            .offset(x: swipeOffset)
            .rotationEffect(
                .degrees(Double(swipeOffset) / screenWidth * vocabSkin.metrics.reviewSwipeMaxRotation),
                anchor: .bottom
            )
            .opacity(cardOpacity)
            .simultaneousGesture(swipeDragGesture)
        }
    }

    // MARK: - Completion / Expand Zone

    var completionState: some View {
        VStack(spacing: vocabSkin.metrics.cardBlockPadding) {
            Spacer()
            VocabEmptyStateContent(
                title: "今天複習完成".localized,
                systemImage: "checkmark.circle",
                description: "這一輪 session 的卡片都處理完了。".localized
            )
            Button("返回生詞庫".localized, action: onClose)
                .buttonStyle(.ghost(vocabSkin.palette.primaryText))
            Spacer()
        }
        .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
    }

    func revealExpandZone(
        title: String,
        minHeight: CGFloat,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            VStack(spacing: 10) {
                Capsule(style: .continuous)
                    .fill(vocabSkin.palette.quaternaryTextFaint)
                    .frame(width: 56, height: 3)
                Text(title)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.quaternaryText.opacity(TodayReviewMetrics.dimTextOpacity))
            }
            .frame(maxWidth: .infinity)
            .frame(minHeight: minHeight, maxHeight: .infinity, alignment: .top)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
