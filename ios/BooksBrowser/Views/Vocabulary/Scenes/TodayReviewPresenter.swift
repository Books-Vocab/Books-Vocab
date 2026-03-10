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
}

// MARK: - Presenter

struct TodayReviewPresenter: View {
    // internal — extension files 需要存取
    @Environment(\.vocabSkin) var vocabSkin
    @Environment(\.dynamicTypeSize) var dynamicTypeSize

    // 動畫狀態 — dismissPhase 是唯一的互動鎖
    @State private var swipeOffset: CGFloat = 0
    @State private var dismissPhase: DismissPhase = .idle
    @State private var suppressTransition = false
    @State private var flingHapticTrigger = 0
    @State private var stackRotations: [Double] = [
        .random(in: -1.0...1.0),
        .random(in: -1.0...1.0)
    ]

    private enum DismissPhase {
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
                                        title: "點一下展開",
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
            .sensoryFeedback(.impact(weight: .light), trigger: flingHapticTrigger)
            .sensoryFeedback(.error, trigger: state.persistenceFailureTrigger)
        }
    }

    // MARK: - Top Bar

    private var topBar: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(state.progressText)
                .font(vocabSkin.typography.monoLabel)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )

            Button {
                guard isCardInteractive else { return }
                onShuffle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(vocabSkin.typography.iconTiny)
                    Text("洗牌")
                        .font(vocabSkin.typography.captionStrong)
                }
                .foregroundStyle(state.canShuffle ? vocabSkin.palette.secondaryText : vocabSkin.palette.quaternaryText)
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPaddingLoose)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )
            }
            .buttonStyle(.plain)
            .disabled(!state.canShuffle)

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", action: onClose)
        }
        .padding(.horizontal, vocabSkin.metrics.reviewTopBarHorizontalInset)
        .padding(.top, vocabSkin.metrics.reviewTopBarTopInset)
        .padding(.bottom, vocabSkin.metrics.reviewTopBarBottomInset)
    }

    // MARK: - Card + Deck

    private func reviewCard(_ currentCard: TodayReviewPresenterState.CurrentCard) -> some View {
        let card = currentCard.card
        let cardIdentity = card.word + "-" + String(card.dateAdded.timeIntervalSinceReferenceDate)

        return ZStack(alignment: .top) {
            // 牌堆 — 不隨 .id() 銷毀重建
            cardStackLayers()
                .frame(height: frontCardHeight)

            // 互動卡片
            VStack(spacing: 0) {
                frontFoldSurface(card)

                if state.revealStage.showsAnswer {
                    answerFoldSurface(currentCard)
                        .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                        .transition(.paperFoldFromTop)
                }
            }
            .id(cardIdentity)
            // fling 時牌堆已同步升頂完畢，用 .identity 跳過 transition；
            // prev/next 導航仍走 scale+offset 升頂動畫
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
            // 不用 .animation() modifier — 所有動畫由 withAnimation 顯式控制
            .simultaneousGesture(swipeDragGesture)
        }
    }

    private func cardStackLayers() -> some View {
        ZStack(alignment: .top) {
            if state.remainingCount >= 2 { stackCard(depth: 2) }
            if state.remainingCount >= 1 { stackCard(depth: 1) }
        }
    }

    private func stackCard(depth: Int) -> some View {
        let progress = dismissProgress
        let effectiveDepth = CGFloat(depth) * (1.0 - progress)
        let scale: CGFloat = 1.0 - effectiveDepth * 0.025
        let yOff: CGFloat = effectiveDepth * 5
        let rotation = stackRotations[depth - 1] * Double(1.0 - progress)
        let baseOpacity = depth == 1 ? TodayReviewMetrics.cardBorderActiveOpacity : 0.35
        let targetOpacity: Double = depth == 1 ? 1.0 : TodayReviewMetrics.cardBorderActiveOpacity
        let opacity = baseOpacity + (targetOpacity - baseOpacity) * Double(progress)

        return ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderOpacity), lineWidth: 1)
                )
                .shadow(color: vocabSkin.palette.shadow.opacity(0.18), radius: 2, y: 1)

            if depth == 1, let nextCard = state.nextCard {
                reviewCardFront(nextCard.card)
                    .allowsHitTesting(false)
            }
        }
        .frame(height: frontCardHeight)
        .scaleEffect(scale)
        .offset(y: yOff)
        .rotationEffect(.degrees(rotation), anchor: .center)
        .opacity(opacity)
    }

    // MARK: - Swipe Gesture + Fling Animation

    private var screenWidth: CGFloat { UIScreen.main.bounds.width }

    private var cardOpacity: Double {
        1.0 - Double(abs(swipeOffset)) / screenWidth * (1.0 - vocabSkin.metrics.reviewSwipeOpacityFloor)
    }

    /// 甩出進度 (0=靜止, 1=完全離開) — 驅動牌堆同步升頂
    private var dismissProgress: CGFloat {
        min(abs(swipeOffset) / 200, 1.0)
    }

    private var swipeEnabled: Bool {
        state.revealStage.showsAnswer && dismissPhase == .idle
    }

    private var swipeDragGesture: some Gesture {
        DragGesture(minimumDistance: 15, coordinateSpace: .local)
            .onChanged { value in
                guard swipeEnabled else { return }
                guard abs(value.translation.width) > abs(value.translation.height) else { return }
                withAnimation(AppMotion.swipeTrackingSpring) {
                    swipeOffset = value.translation.width
                }
            }
            .onEnded { value in
                guard swipeEnabled else { return }
                let threshold = vocabSkin.metrics.reviewSwipeThreshold
                if value.translation.width < -threshold {
                    flingCard(direction: -1, callback: onForgot)
                } else if value.translation.width > threshold {
                    flingCard(direction: 1, callback: onRemembered)
                } else {
                    withAnimation(AppMotion.swipeSnapBackSpring) {
                        swipeOffset = 0
                    }
                }
            }
    }

    /// 統一的甩出動畫 — swipe 和按鈕共用
    ///
    /// 牌堆升頂不再是獨立階段 — 透過 dismissProgress 與甩出同步進行。
    /// 滑動觸發時甩出動畫同步啟動（不經 Task 調度），消除一幀凍結。
    private func flingCard(direction: CGFloat, isFromButton: Bool = false, callback: @escaping () -> Void) {
        guard dismissPhase == .idle else { return }
        dismissPhase = .animatingOut
        flingHapticTrigger += 1

        // 滑動觸發：同步啟動甩出，與 dismissPhase 同幀渲染
        if !isFromButton {
            withAnimation(AppMotion.swipeFlingSpring) {
                swipeOffset = direction * screenWidth * 1.3
            }
        }

        Task { @MainActor in
            // 按鈕蓄力微動 → 甩出（按鈕路徑才需 Task 內的延遲）
            if isFromButton {
                withAnimation(AppMotion.buttonWindupSpring) {
                    swipeOffset = -direction * 8
                }
                try? await Task.sleep(for: .milliseconds(60))
                withAnimation(AppMotion.swipeFlingSpring) {
                    swipeOffset = direction * screenWidth * 1.3
                }
            }

            // stiffness=500: ~50ms 卡片已飛出螢幕、牌堆已升頂
            try? await Task.sleep(for: .milliseconds(60))

            // 瞬間換卡
            var noAnim = Transaction(animation: nil)
            noAnim.disablesAnimations = true
            withTransaction(noAnim) {
                suppressTransition = true
                swipeOffset = 0
                stackRotations = [.random(in: -1...1), .random(in: -1...1)]
                callback()
            }
            suppressTransition = false

            dismissPhase = .idle
        }
    }

    // MARK: - Swipe ↔ 按鈕連動

    private var swipeIntensity: Double {
        guard swipeEnabled else { return 0 }
        return max(-1, min(1, Double(swipeOffset / vocabSkin.metrics.reviewSwipeThreshold)))
    }

    private var forgotButtonScale: CGFloat   { 1.0 + CGFloat(max(-swipeIntensity, 0)) * 0.12 }
    private var forgotButtonOffset: CGFloat  { CGFloat(max(-swipeIntensity, 0)) * -4 }
    private var forgotButtonOpacity: Double  { 1.0 - max(swipeIntensity, 0) * 0.45 }
    private var forgotButtonGlow: Double     { max(-swipeIntensity, 0) }

    private var rememberedButtonScale: CGFloat   { 1.0 + CGFloat(max(swipeIntensity, 0)) * 0.12 }
    private var rememberedButtonOffset: CGFloat  { CGFloat(max(swipeIntensity, 0)) * -4 }
    private var rememberedButtonOpacity: Double  { 1.0 - max(-swipeIntensity, 0) * 0.45 }
    private var rememberedButtonGlow: Double     { max(swipeIntensity, 0) }

    // MARK: - Bottom Toolbar

    private var bottomToolbar: some View {
        VStack(spacing: 10) {
            if let msg = state.persistenceErrorMessage {
                VocabStateMessageCard(
                    title: "本機儲存失敗",
                    systemImage: "externaldrive.badge.exclamationmark",
                    description: msg
                )
                .transition(.overlayFade)
            }

            if dynamicTypeSize < .accessibility1 {
                HStack(spacing: 0) {
                    navButtons
                    Spacer()
                    feedbackButtons
                }
            } else {
                VStack(spacing: vocabSkin.spacing.inlineGap) {
                    feedbackButtons.frame(maxWidth: .infinity)
                    navButtons
                }
            }
        }
        .padding(.horizontal, vocabSkin.metrics.reviewToolbarHorizontalInset)
        .padding(.vertical, vocabSkin.metrics.reviewToolbarVerticalInset)
        .animation(AppMotion.reviewNavigationSpring, value: state.revealStage.showsAnswer)
        .animation(AppMotion.phaseChange, value: state.persistenceErrorMessage)
        .background(
            Rectangle()
                .fill(vocabSkin.palette.pageBackground)
                .shadow(
                    color: vocabSkin.palette.shadow.opacity(vocabSkin.metrics.reviewToolbarShadowOpacity),
                    radius: vocabSkin.metrics.reviewToolbarShadowRadius,
                    y: vocabSkin.metrics.reviewToolbarShadowY
                )
                .ignoresSafeArea(edges: .bottom)
        )
    }

    private var navButtons: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Button { guard isCardInteractive else { return }; onPrevious() } label: {
                Image(systemName: "chevron.left").font(vocabSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoPrevious)

            Button { guard isCardInteractive else { return }; onNext() } label: {
                Image(systemName: "chevron.right").font(vocabSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoNext)
        }
        .foregroundStyle(vocabSkin.palette.secondaryText)
    }

    private var feedbackButtons: some View {
        let spring = AppMotion.feedbackButtonSpring
        let buttonsDisabled = !state.revealStage.showsAnswer

        return HStack(spacing: vocabSkin.metrics.sectionHeaderGap) {
            Button { flingCard(direction: -1, isFromButton: true, callback: onForgot) } label: {
                HStack(spacing: 4) {
                    Image(systemName: "xmark")
                    Text("忘記")
                    if state.forgotCount > 0 {
                        Text("·\(state.forgotCount)").font(vocabSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
            }
            .buttonStyle(.vocabAction(.destructive))
            .disabled(buttonsDisabled)
            .overlay(alignment: .center) {
                if forgotButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.destructive.opacity(forgotButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(forgotButtonScale)
            .offset(y: forgotButtonOffset)
            .opacity(forgotButtonOpacity)
            .animation(spring, value: swipeIntensity)

            Button { flingCard(direction: 1, isFromButton: true, callback: onRemembered) } label: {
                HStack(spacing: 4) {
                    Image(systemName: "checkmark")
                    Text("記得")
                    if state.rememberedCount > 0 {
                        Text("·\(state.rememberedCount)").font(vocabSkin.typography.monoLabel)
                    }
                }
                .frame(minWidth: vocabSkin.metrics.reviewActionMinWidth)
            }
            .buttonStyle(.vocabAction(.success))
            .disabled(buttonsDisabled)
            .overlay(alignment: .center) {
                if rememberedButtonGlow > 0 {
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.success.opacity(rememberedButtonGlow * 0.10))
                        .allowsHitTesting(false)
                }
            }
            .scaleEffect(rememberedButtonScale)
            .offset(y: rememberedButtonOffset)
            .opacity(rememberedButtonOpacity)
            .animation(spring, value: swipeIntensity)
        }
    }

    // MARK: - Completion / Expand Zone

    private var completionState: some View {
        VStack(spacing: vocabSkin.metrics.cardBlockPadding) {
            Spacer()
            VocabEmptyStateContent(
                title: "今天複習完成",
                systemImage: "checkmark.circle",
                description: "這一輪 session 的卡片都處理完了。"
            )
            Button("返回生詞庫", action: onClose)
                .buttonStyle(.ghost(vocabSkin.palette.primaryText))
            Spacer()
        }
        .padding(.horizontal, vocabSkin.metrics.cardBlockPadding)
    }

    private func revealExpandZone(
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
