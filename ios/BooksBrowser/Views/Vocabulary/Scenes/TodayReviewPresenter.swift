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
                                } else if state.revealStage == .back {
                                    revealExpandZone(
                                        title: "點一下查看細節",
                                        minHeight: max(geo.size.height * vocabSkin.metrics.reviewCompletionHeightRatio, 140),
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
            .sensoryFeedback(.success, trigger: state.rememberedFeedbackTrigger)
            .sensoryFeedback(.warning, trigger: state.forgotFeedbackTrigger)
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
                .padding(.vertical, vocabSkin.spacing.chipVerticalPadding + 2)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )

            Button(action: onShuffle) {
                HStack(spacing: 6) {
                    Image(systemName: "shuffle")
                        .font(vocabSkin.typography.iconTiny)
                    Text("洗牌")
                        .font(vocabSkin.typography.captionStrong)
                }
                .foregroundStyle(state.canShuffle ? vocabSkin.palette.secondaryText : vocabSkin.palette.quaternaryText)
                .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
                .padding(.vertical, vocabSkin.spacing.chipVerticalPadding + 2)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.mutedFill)
                )
            }
            .buttonStyle(.plain)
            .disabled(!state.canShuffle || !isCardInteractive)

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
                    answerFoldSurface(card)
                        .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                        .transition(.paperFoldFromTop)
                }

                if state.revealStage.showsDetails {
                    detailFoldSheet(currentCard)
                        .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                        .transition(.paperFoldFromTop)
                }
            }
            .id(cardIdentity)
            // 舊卡瞬間消失（已在畫面外）；新卡從牌堆位置升頂
            .transition(.asymmetric(
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
        let scale: CGFloat = 1.0 - CGFloat(depth) * 0.025
        let yOff: CGFloat = CGFloat(depth) * 5
        let rotation = stackRotations[depth - 1]

        return ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder.opacity(TodayReviewMetrics.cardBorderOpacity), lineWidth: 1)
                )
                .shadow(color: vocabSkin.palette.shadow.opacity(0.18), radius: 2, y: 1)

            if depth == 1, let nextCard = state.nextCard {
                VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                    HStack(spacing: 6) {
                        if let pos = nextCard.card.partOfSpeech {
                            Text(pos)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                        }
                        Spacer()
                    }
                    Spacer(minLength: vocabSkin.metrics.reviewFoldHintBottomInset)
                    Text(nextCard.card.word)
                        .font(reviewFrontWordFont(for: nextCard.card.word))
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineLimit(2)
                        .minimumScaleFactor(0.7)
                    Spacer(minLength: vocabSkin.metrics.reviewTopBarTopInset)
                }
                .padding(reviewCardPadding)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .allowsHitTesting(false)
            }
        }
        .frame(height: frontCardHeight)
        .scaleEffect(scale)
        .offset(y: yOff)
        .rotationEffect(.degrees(rotation), anchor: .center)
        .opacity(depth == 1 ? TodayReviewMetrics.cardBorderActiveOpacity : 0.35)
    }

    // MARK: - Swipe Gesture + Fling Animation

    private var screenWidth: CGFloat { UIScreen.main.bounds.width }

    private var cardOpacity: Double {
        1.0 - Double(abs(swipeOffset)) / screenWidth * (1.0 - vocabSkin.metrics.reviewSwipeOpacityFloor)
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
    /// 動畫三階段（全部顯式 withAnimation，零 .animation() modifier）：
    /// 1. fling: swipeFlingSpring 甩出畫面
    /// 2. noAnim: 瞬間重置 swipeOffset
    /// 3. stackPromotionSpring: callback 觸發 .id() 變更 → .transition() 升頂
    ///    不需要 isPromoting 或 frame gap — transition 在同一幀處理 active→identity
    private func flingCard(direction: CGFloat, isFromButton: Bool = false, callback: @escaping () -> Void) {
        guard dismissPhase == .idle else { return }
        dismissPhase = .animatingOut

        Task { @MainActor in
            // 按鈕蓄力微動
            if isFromButton {
                withAnimation(AppMotion.buttonWindupSpring) {
                    swipeOffset = -direction * 8
                }
                try? await Task.sleep(for: .milliseconds(60))
            }

            // 甩出畫面
            withAnimation(AppMotion.swipeFlingSpring) {
                swipeOffset = direction * screenWidth * 1.3
            }
            try? await Task.sleep(for: .milliseconds(120))

            // 瞬間重置 swipeOffset（卡片已在畫面外，跳回不可見）
            var noAnim = Transaction(animation: nil)
            noAnim.disablesAnimations = true
            withTransaction(noAnim) {
                swipeOffset = 0
            }

            // 換卡 + 升頂 — .transition() 在 .id() 變更時自動處理：
            //   removal(.identity): 舊卡瞬間消失
            //   insertion(.scale+.offset): 新卡從牌堆位置彈出
            // 用 completion 確保動畫真正結束才恢復互動
            await withCheckedContinuation { continuation in
                withAnimation(AppMotion.stackPromotionSpring) {
                    stackRotations = [.random(in: -1...1), .random(in: -1...1)]
                    callback()
                } completion: {
                    continuation.resume()
                }
            }

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
            Button(action: onPrevious) {
                Image(systemName: "chevron.left").font(vocabSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoPrevious || !isCardInteractive)

            Button(action: onNext) {
                Image(systemName: "chevron.right").font(vocabSkin.typography.iconNavigation)
            }
            .disabled(!state.canGoNext || !isCardInteractive)
        }
        .foregroundStyle(vocabSkin.palette.secondaryText)
    }

    private var feedbackButtons: some View {
        let spring = AppMotion.feedbackButtonSpring
        let buttonsDisabled = dismissPhase != .idle || !state.revealStage.showsAnswer

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
            .frame(minHeight: minHeight, alignment: .top)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
