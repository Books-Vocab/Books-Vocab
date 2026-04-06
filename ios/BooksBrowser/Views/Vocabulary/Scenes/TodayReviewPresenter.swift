import SwiftUI

// MARK: - State

struct TodayReviewPresenterState {
    struct LinkGroup: Identifiable {
        let id: String
        let label: String
        let items: [KGCardLinkSummary]
        let overflowCount: Int
    }

    /// Pre-computed layout metrics for blocks after the first `.example` in backDocument.
    /// Separates the gap-dependent count from fixed heights so `answerExampleRadius`
    /// doesn't need to iterate blocks every frame.
    struct PostExampleMetrics {
        /// Total fixed height from post-example blocks (excluding gap contributions).
        let fixedHeight: CGFloat
        /// Number of gap units needed (one per post-example block).
        let gapCount: Int

        func totalHeight(gap: CGFloat) -> CGFloat {
            fixedHeight + CGFloat(gapCount) * gap
        }

        /// Iterate backDocument blocks once, returning pre-computed metrics.
        static func from(_ backDoc: CardDocument) -> PostExampleMetrics {
            var fixedHeight: CGFloat = 0
            var gapCount = 0
            var seenExample = false
            for block in backDoc.blocks {
                switch block {
                case .example:
                    seenExample = true
                case .divider:
                    if seenExample { fixedHeight += AppMetrics.dividerThin; gapCount += 1 }
                case .meaning(let meaning):
                    if seenExample {
                        // fixedSize: 每段最多 3 行（lineLimit），多段累加
                        let lineCount = meaning.paragraphs.count * 3
                        fixedHeight += CGFloat(lineCount) * 22; gapCount += 1
                    }
                case .collocations(let items):
                    if seenExample {
                        let rows = max(1, (items.count + 1) / 2)
                        fixedHeight += CGFloat(rows) * 32; gapCount += 1
                    }
                default:
                    if seenExample { fixedHeight += 30; gapCount += 1 }
                }
            }
            return .init(fixedHeight: fixedHeight, gapCount: gapCount)
        }
    }

    struct CurrentCard {
        let card: CardPresentation
        let linkGroups: [LinkGroup]
        let backDocument: CardDocument
        /// Pre-computed post-example block metrics — avoids re-iterating blocks every frame.
        let postExampleMetrics: PostExampleMetrics
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
    let isAutoPlaying: Bool
    let isAutoPlayPaused: Bool
}

// MARK: - Presenter

struct TodayReviewPresenter: View {
    // internal — extension files 需要存取
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.vocabSkin) var vocabSkin
    @Environment(\.dynamicTypeSize) var dynamicTypeSize
    @Environment(\.speechService) private var speechService

    // 動畫狀態 — dismissPhase 是唯一的互動鎖
    @State var frozenSwipeIntensity: Double = 0
    @State var swipeOffset: CGFloat = 0
    @State var containerWidth: CGFloat = 393
    @State var dismissPhase: DismissPhase = .idle
    @State var suppressTransition = false
    @State var flingHapticTrigger = 0
    @State private var celebrationTriggered = false
    @State var stackRotations: [Double] = [
        .random(in: -1.0...1.0),
        .random(in: -1.0...1.0)
    ]

    enum DismissPhase {
        case idle
        case animatingOut
    }

    let state: TodayReviewPresenterState
    let isHelpPresented: Bool
    let showFirstRunHint: Bool
    let onClose: () -> Void
    let onAdvanceReveal: () -> Void
    let onCollapseReveal: () -> Void
    let onShuffle: () -> Void
    let onPrevious: () -> Void
    let onNext: () -> Void
    let onForgot: () -> Void
    let onRemembered: () -> Void
    let onLinkTap: (KGCardLinkSummary) -> Void
    let onAddLink: () -> Void
    let onToggleAutoPlay: () -> Void
    let onToggleAutoPlayPause: () -> Void
    let onDetailTap: () -> Void
    let onToggleHelp: () -> Void

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
                        VStack(spacing: 0) {
                            reviewCard(currentCard, availableHeight: geo.size.height)
                                .padding(.horizontal, vocabSkin.metrics.reviewCardHorizontalInset)
                                .padding(.top, vocabSkin.metrics.reviewCardTopInset)
                                .padding(.bottom, vocabSkin.metrics.reviewCardBottomInset)

                            if state.revealStage == .front {
                                revealExpandZone(
                                    title: "點一下展開".localized,
                                    minHeight: max(geo.size.height * vocabSkin.metrics.reviewFrontHeightRatio, 180),
                                    action: onAdvanceReveal
                                )
                                .allowsHitTesting(isCardInteractive)
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                    }

                    bottomToolbar
                } else {
                    completionState
                }
            }
            #if os(macOS)
            .overlay {
                if isHelpPresented {
                    vocabSkin.palette.shadow.opacity(0.25)
                        .ignoresSafeArea()
                        .onTapGesture { onToggleHelp() }
                        .transition(.opacity)

                    shortcutHelpOverlay
                        .transition(.overlayFade)
                }
            }
            .animation(AppMotion.panelState, value: isHelpPresented)
            #endif
            .platformContentMaxWidth(for: LayoutMode(horizontalSizeClass: sizeClass))
            .vocabCanvasBackground()
            .platformHideNavigationBar()
            .onGeometryChange(for: CGFloat.self) { proxy in
                proxy.size.width
            } action: { newWidth in
                // 動畫進行中不更新，避免 truncateRadius 變化導致 view rebuild 中斷 transition
                guard dismissPhase == .idle, !state.revealStage.showsAnswer else { return }
                containerWidth = newWidth
            }
            .sensoryFeedback(.impact(weight: .light), trigger: flingHapticTrigger)
            .animation(AppMotion.panelState, value: isHelpPresented)
        }
    }

    // MARK: - Card

    func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard, availableHeight: CGFloat) -> some View {
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

                // 永遠存在於 view tree — 繞過 .id() + conditional insertion
                // 首次渲染不走 .transition() 的 SwiftUI 結構性限制。
                // PaperFoldModifier(Animatable) 直接驅動摺疊動畫。
                // frame(height:0) 使摺疊時不佔 layout 空間，
                // 但 minHeight 內部約束使 view 仍以完整尺寸渲染（fold 視覺正確）。
                answerFoldSurface(currentCard, availableHeight: availableHeight)
                    .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                    .modifier(PaperFoldModifier(progress: state.revealStage.showsAnswer ? 1 : 0))
                    .frame(height: state.revealStage.showsAnswer ? nil : 0, alignment: .top)
                    .allowsHitTesting(state.revealStage.showsAnswer)
            }
            .geometryGroup()
            .animation(dismissPhase == .idle ? AppMotion.reviewRevealSpring : nil,
                       value: state.revealStage.showsAnswer)
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
            #if os(macOS)
            .contentShape(Rectangle())
            .onTapGesture {
                guard isCardInteractive, state.revealStage == .front else { return }
                onAdvanceReveal()
            }
            #endif
        }
    }

    // MARK: - Completion / Expand Zone

    var completionState: some View {
        VStack(spacing: vocabSkin.metrics.cardBlockPadding) {
            Spacer()
            VocabEmptyStateContent(
                title: "今天複習完成".localized,
                systemImage: "checkmark.circle",
                description: "這一輪 session 的卡片都處理完了。".localized,
                guidanceText: "明天再來複習新到期的單字",
                symbolBounce: celebrationTriggered
            )
            .scaleEffect(celebrationTriggered ? 1 : 0.8)
            .opacity(celebrationTriggered ? 1 : 0)
            .onAppear {
                withAnimation(AppMotion.celebrationBounce) {
                    celebrationTriggered = true
                }
            }
            Button("返回單字本".localized, action: onClose)
                .buttonStyle(.ghost(vocabSkin.palette.primaryText))
            Spacer()
        }
        .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
        .sensoryFeedback(.success, trigger: celebrationTriggered)
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
